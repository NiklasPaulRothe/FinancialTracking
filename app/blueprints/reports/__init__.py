"""Reports blueprint for Haushaltsbuch.

Provides personal, shared, and net worth report views with income-cycle-aligned
period boundaries and date range filters.

Validates: Requirements 19.1, 19.2, 19.3, 19.4, 19.5, 19.6
"""

from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from sqlalchemy import and_, func

from app.extensions import db
from app.models.account import Account, AccountBalanceSnapshot, AccountScope
from app.models.budget import Budget, BudgetScope
from app.models.networth import NetWorthSnapshot
from app.models.transaction import Transaction, TransactionScope, TransactionType
from app.models.user import User
from app.services.banking_day_service import BankingDayService
from app.services.budget_service import BudgetService

reports_bp = Blueprint(
    "reports", __name__, url_prefix="/reports", template_folder="templates"
)

_banking_day_service = BankingDayService()
_budget_service = BudgetService()


# ---------------------------------------------------------------------------
# Income-cycle period boundary helpers
# ---------------------------------------------------------------------------


def _get_current_cycle_boundaries(user: User, reference_date: date | None = None) -> tuple[date, date]:
    """Compute income-cycle-aligned period boundaries for a user.

    Validates: Requirements 19.3, 19.4

    The current income cycle runs from the most recent effective income day
    to the day before the next effective income day.

    Args:
        user: The user whose income_day anchors the cycle.
        reference_date: Reference date (defaults to today).

    Returns:
        Tuple of (cycle_start, cycle_end) as inclusive dates.
    """
    if reference_date is None:
        reference_date = date.today()

    income_day = user.income_day

    # Find effective income day for the reference month
    effective_this_month = _banking_day_service.get_effective_income_day(
        income_day, reference_date.year, reference_date.month
    )

    if reference_date >= effective_this_month:
        # Current cycle started this month
        cycle_start = effective_this_month
        # End is day before next month's effective income day
        next_year, next_month = _next_month(reference_date.year, reference_date.month)
        effective_next = _banking_day_service.get_effective_income_day(
            income_day, next_year, next_month
        )
        cycle_end = effective_next - timedelta(days=1)
    else:
        # Current cycle started last month
        prev_year, prev_month = _prev_month(reference_date.year, reference_date.month)
        cycle_start = _banking_day_service.get_effective_income_day(
            income_day, prev_year, prev_month
        )
        cycle_end = effective_this_month - timedelta(days=1)

    return cycle_start, cycle_end


def _snap_to_income_cycle_boundaries(
    user: User, start_date: date, end_date: date
) -> tuple[date, date]:
    """Snap arbitrary dates to nearest income cycle boundaries.

    Validates: Requirement 19.5

    Finds the income cycle boundary that encloses the start_date (as cycle
    start) and the income cycle boundary that encloses the end_date (as cycle
    end).

    Args:
        user: The user whose income_day anchors the cycles.
        start_date: The desired start date.
        end_date: The desired end date.

    Returns:
        Tuple of (snapped_start, snapped_end) as inclusive dates.
    """
    # Find the cycle start that contains start_date
    snapped_start, _ = _get_current_cycle_boundaries(user, start_date)
    # Find the cycle end that contains end_date
    _, snapped_end = _get_current_cycle_boundaries(user, end_date)

    return snapped_start, snapped_end


def _parse_date_filters(user: User) -> tuple[date, date]:
    """Parse date range filters from request args, defaulting to current cycle.

    Validates: Requirements 19.4, 19.5

    If no dates provided, defaults to current income cycle.
    If dates provided, snaps to income cycle boundaries unless override is set.

    Args:
        user: The user for income_day reference.

    Returns:
        Tuple of (start_date, end_date).
    """
    start_str = request.args.get("start")
    end_str = request.args.get("end")

    if not start_str or not end_str:
        # Default to current income cycle (Req 19.4)
        return _get_current_cycle_boundaries(user)

    try:
        start_date = date.fromisoformat(start_str)
        end_date = date.fromisoformat(end_str)
    except (ValueError, TypeError):
        return _get_current_cycle_boundaries(user)

    # Snap to income cycle boundaries (Req 19.5) unless custom override
    custom = request.args.get("custom") == "1"
    if not custom:
        return _snap_to_income_cycle_boundaries(user, start_date, end_date)

    return start_date, end_date


# ---------------------------------------------------------------------------
# Personal report route
# ---------------------------------------------------------------------------


@reports_bp.route("/personal")
@login_required
def personal():
    """Display personal report: income/expense totals, budget vs. actual, balance history.

    Validates: Requirements 19.1, 19.3, 19.4, 19.5, 19.6
    """
    start_date, end_date = _parse_date_filters(current_user)

    # Income/expense totals within period (personal scope)
    income_total = _sum_transactions_in_period(
        current_user.id, TransactionScope.personal, TransactionType.income,
        start_date, end_date
    )
    expense_total = _sum_transactions_in_period(
        current_user.id, TransactionScope.personal, TransactionType.expense,
        start_date, end_date
    )

    # Budget vs. actual: personal budgets
    budgets = Budget.query.filter(
        Budget.user_id == current_user.id,
        Budget.scope == BudgetScope.personal,
    ).order_by(Budget.name).all()

    budget_comparisons = []
    for budget in budgets:
        period_start, period_end = _budget_service.get_period_boundaries(
            budget, current_user, start_date
        )
        utilisation_details = _budget_service.get_utilisation_with_details(
            budget, current_user
        )
        budget_comparisons.append({
            "budget": budget,
            "spent": utilisation_details["spent"],
            "amount": budget.amount,
            "percentage_raw": utilisation_details["percentage_raw"],
            "color": utilisation_details["color"],
        })

    # Balance history: account balance snapshots within period (personal accounts)
    balance_history = _get_balance_history(
        current_user.id, AccountScope.personal, start_date, end_date
    )

    # Check if we have any data (Req 19.6)
    has_data = income_total > 0 or expense_total > 0 or len(budget_comparisons) > 0

    return render_template(
        "reports/personal.html",
        start_date=start_date,
        end_date=end_date,
        income_total=income_total,
        expense_total=expense_total,
        budget_comparisons=budget_comparisons,
        balance_history=balance_history,
        has_data=has_data,
    )


# ---------------------------------------------------------------------------
# Shared report route
# ---------------------------------------------------------------------------


@reports_bp.route("/shared")
@login_required
def shared():
    """Display shared report: shared-scope transactions and budgets only.

    Validates: Requirements 19.2, 19.3, 19.4, 19.5, 19.6
    """
    start_date, end_date = _parse_date_filters(current_user)

    # Income/expense totals within period (shared scope — both users)
    income_total = _sum_transactions_in_period(
        None, TransactionScope.shared, TransactionType.income,
        start_date, end_date
    )
    expense_total = _sum_transactions_in_period(
        None, TransactionScope.shared, TransactionType.expense,
        start_date, end_date
    )

    # Budget vs. actual: shared budgets only
    budgets = Budget.query.filter(
        Budget.scope == BudgetScope.shared,
    ).order_by(Budget.name).all()

    budget_comparisons = []
    for budget in budgets:
        utilisation_details = _budget_service.get_utilisation_with_details(
            budget, current_user
        )
        budget_comparisons.append({
            "budget": budget,
            "spent": utilisation_details["spent"],
            "amount": budget.amount,
            "percentage_raw": utilisation_details["percentage_raw"],
            "color": utilisation_details["color"],
        })

    # Balance history for shared accounts
    balance_history = _get_balance_history(
        current_user.id, AccountScope.shared, start_date, end_date
    )

    has_data = income_total > 0 or expense_total > 0 or len(budget_comparisons) > 0

    return render_template(
        "reports/shared.html",
        start_date=start_date,
        end_date=end_date,
        income_total=income_total,
        expense_total=expense_total,
        budget_comparisons=budget_comparisons,
        balance_history=balance_history,
        has_data=has_data,
    )


# ---------------------------------------------------------------------------
# Net worth report route
# ---------------------------------------------------------------------------


@reports_bp.route("/networth")
@login_required
def networth():
    """Display net worth chart with date range filters, 12-cycle default, projections.

    Validates: Requirements 18.2, 18.3, 18.4, 18.5, 19.3
    """
    # Default range: last 12 income cycles
    start_str = request.args.get("start")
    end_str = request.args.get("end")

    if start_str and end_str:
        try:
            start_date = date.fromisoformat(start_str)
            end_date = date.fromisoformat(end_str)
        except (ValueError, TypeError):
            start_date, end_date = _get_12_cycle_range(current_user)
    else:
        start_date, end_date = _get_12_cycle_range(current_user)

    # Fetch net worth snapshots
    snapshots = (
        NetWorthSnapshot.query
        .filter(
            NetWorthSnapshot.user_id == current_user.id,
            NetWorthSnapshot.snapshot_date >= start_date,
            NetWorthSnapshot.snapshot_date <= end_date,
        )
        .order_by(NetWorthSnapshot.snapshot_date)
        .all()
    )

    # Apply linear interpolation for missing dates (Req 18.4)
    chart_data = _interpolate_snapshots(snapshots, start_date, end_date)

    # Compute projections at 5-year intervals and retirement age (Req 18.3)
    projections = _compute_projections(current_user)

    # Check if sufficient data (Req 18.5)
    has_sufficient_data = len(snapshots) >= 2
    current_net_worth = _compute_current_net_worth(current_user)

    return render_template(
        "reports/networth.html",
        start_date=start_date,
        end_date=end_date,
        chart_data=chart_data,
        projections=projections,
        has_sufficient_data=has_sufficient_data,
        current_net_worth=current_net_worth,
        snapshots=snapshots,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _sum_transactions_in_period(
    user_id: int | None,
    scope: TransactionScope,
    txn_type: TransactionType,
    start_date: date,
    end_date: date,
) -> Decimal:
    """Sum transactions of a given type and scope within a period.

    Args:
        user_id: If set, filter to this user. If None, include all users (shared).
        scope: Transaction scope filter.
        txn_type: Transaction type filter.
        start_date: Period start (inclusive).
        end_date: Period end (inclusive).

    Returns:
        Total amount as Decimal.
    """
    filters = [
        Transaction.type == txn_type,
        Transaction.scope == scope,
        Transaction.date >= start_date,
        Transaction.date <= end_date,
    ]
    if user_id is not None:
        filters.append(Transaction.user_id == user_id)

    result = db.session.query(
        func.coalesce(func.sum(Transaction.amount), Decimal("0"))
    ).filter(and_(*filters)).scalar()

    return Decimal(str(result)) if result else Decimal("0")


def _get_balance_history(
    user_id: int,
    scope: AccountScope,
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Get daily balance history for accounts of the given scope.

    Returns a list of dicts with date and total_balance for charting.

    Args:
        user_id: The user whose accounts to include.
        scope: Account scope (personal or shared).
        start_date: Range start.
        end_date: Range end.

    Returns:
        List of {date, total_balance} dicts ordered by date.
    """
    # Get account IDs for the user with matching scope
    if scope == AccountScope.shared:
        # Shared accounts: include all shared accounts visible to user
        account_ids = [
            a.id for a in Account.query.filter(
                Account.scope == AccountScope.shared,
                Account.active == True,  # noqa: E712
            ).all()
        ]
    else:
        # Personal accounts owned by the user
        account_ids = [
            a.id for a in Account.query.filter(
                Account.owner_id == user_id,
                Account.scope == AccountScope.personal,
                Account.active == True,  # noqa: E712
            ).all()
        ]

    if not account_ids:
        return []

    # Query snapshots grouped by date, summing balances across accounts
    # Use the last snapshot per account per day
    from sqlalchemy import distinct

    # Subquery: for each (account, date) get the max snapshot id (latest)
    latest_sub = (
        db.session.query(
            func.max(AccountBalanceSnapshot.id).label("max_id"),
        )
        .filter(
            AccountBalanceSnapshot.account_id.in_(account_ids),
            AccountBalanceSnapshot.snapshot_date >= start_date,
            AccountBalanceSnapshot.snapshot_date <= end_date,
        )
        .group_by(
            AccountBalanceSnapshot.account_id,
            AccountBalanceSnapshot.snapshot_date,
        )
        .subquery()
    )

    # Get actual snapshots using the latest IDs
    rows = (
        db.session.query(
            AccountBalanceSnapshot.snapshot_date,
            func.sum(AccountBalanceSnapshot.balance).label("total_balance"),
        )
        .filter(AccountBalanceSnapshot.id.in_(db.session.query(latest_sub.c.max_id)))
        .group_by(AccountBalanceSnapshot.snapshot_date)
        .order_by(AccountBalanceSnapshot.snapshot_date)
        .all()
    )

    return [
        {"date": row.snapshot_date.isoformat(), "total_balance": float(row.total_balance)}
        for row in rows
    ]


def _get_12_cycle_range(user: User) -> tuple[date, date]:
    """Compute date range for the last 12 income cycles.

    Validates: Requirement 18.2 (12-cycle default)

    Args:
        user: The user for income_day reference.

    Returns:
        Tuple of (start_date, end_date).
    """
    today = date.today()
    _, cycle_end = _get_current_cycle_boundaries(user, today)

    # Go back 12 months to find the start
    start_year = today.year
    start_month = today.month
    for _ in range(12):
        start_year, start_month = _prev_month(start_year, start_month)

    cycle_start = _banking_day_service.get_effective_income_day(
        user.income_day, start_year, start_month
    )

    return cycle_start, cycle_end


def _interpolate_snapshots(
    snapshots: list[NetWorthSnapshot],
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Apply linear interpolation between snapshots for chart rendering.

    Validates: Requirement 18.4

    Fills gaps between data points with linearly interpolated values.

    Args:
        snapshots: Ordered list of NetWorthSnapshot objects.
        start_date: Chart start date.
        end_date: Chart end date.

    Returns:
        List of {date, value} dicts for every date in range.
    """
    if not snapshots:
        return []

    # Build a map of known points
    known: dict[date, float] = {}
    for s in snapshots:
        known[s.snapshot_date] = float(s.total_value)

    result = []
    sorted_dates = sorted(known.keys())

    # Generate daily points from start to end
    current = start_date
    while current <= end_date:
        if current in known:
            result.append({"date": current.isoformat(), "value": known[current]})
        else:
            # Find nearest adjacent known points
            prev_date = None
            next_date = None
            for d in sorted_dates:
                if d <= current:
                    prev_date = d
                if d >= current and next_date is None:
                    next_date = d

            if prev_date and next_date and prev_date != next_date:
                # Linear interpolation
                total_days = (next_date - prev_date).days
                elapsed_days = (current - prev_date).days
                ratio = elapsed_days / total_days if total_days > 0 else 0
                interpolated = known[prev_date] + ratio * (known[next_date] - known[prev_date])
                result.append({"date": current.isoformat(), "value": round(interpolated, 2)})
            elif prev_date:
                # Extrapolate forward from last known value
                result.append({"date": current.isoformat(), "value": known[prev_date]})
            elif next_date:
                # Before first known value — use first value
                result.append({"date": current.isoformat(), "value": known[next_date]})

        current += timedelta(days=1)

    return result


def _compute_projections(user: User) -> list[dict]:
    """Compute projected net worth at future intervals.

    Validates: Requirement 18.3

    Uses FV = PV × (1 + r)^n + PMT × [((1 + r)^n − 1) / r]
    where:
        PV = latest NetWorthSnapshot value
        r = assumed_annual_return / 12
        PMT = sum of active monthly saving contributions + ETF savings plan amounts
        n = months to target

    Intervals: 5, 10, 15, 20, 25, 30 years and target retirement age.

    Args:
        user: The user with configured assumed_annual_return and target_retirement_age.

    Returns:
        List of {label, years, projected_value} dicts.
    """
    # Get latest net worth snapshot
    latest_snapshot = (
        NetWorthSnapshot.query
        .filter(NetWorthSnapshot.user_id == user.id)
        .order_by(NetWorthSnapshot.snapshot_date.desc())
        .first()
    )

    if latest_snapshot is None:
        return []

    pv = float(latest_snapshot.total_value)
    r_annual = float(user.assumed_annual_return)
    r_monthly = r_annual / 12 if r_annual > 0 else Decimal("0")

    # Calculate PMT: sum of active monthly saving contributions + ETF savings plan amounts
    pmt = _get_monthly_contributions(user)

    # Projection intervals
    intervals_years = [5, 10, 15, 20, 25, 30]

    # Add retirement target if not already covered
    today = date.today()
    # Approximate user age from created_at (rough estimate; actual birthday not stored)
    # Use target_retirement_age - estimated years of service remaining
    # For simplicity, project to target retirement age as additional years
    # Since we don't store birth date, include retirement age target as extra marker
    retirement_years = user.target_retirement_age - 30  # rough assumption of current age 30
    if retirement_years > 0 and retirement_years not in intervals_years:
        intervals_years.append(retirement_years)
    intervals_years.sort()

    projections = []
    for years in intervals_years:
        n = years * 12  # months
        if r_monthly > 0:
            growth_factor = (1 + r_monthly) ** n
            fv = pv * growth_factor + pmt * ((growth_factor - 1) / r_monthly)
        else:
            fv = pv + pmt * n

        projections.append({
            "label": f"{years} Jahre",
            "years": years,
            "projected_value": round(fv, 2),
        })

    return projections


def _get_monthly_contributions(user: User) -> float:
    """Sum active monthly saving contributions and ETF savings plan amounts.

    Args:
        user: The user.

    Returns:
        Total monthly contribution amount.
    """
    total = Decimal("0")

    # Saving contributions (active saving goals)
    try:
        from app.models.budget import SavingContribution, SavingGoal, SavingGoalStatus

        contributions = (
            db.session.query(func.coalesce(func.sum(SavingContribution.amount), 0))
            .join(SavingGoal, SavingContribution.saving_goal_id == SavingGoal.id)
            .filter(
                SavingGoal.user_id == user.id,
                SavingGoal.status == SavingGoalStatus.active,
            )
            .scalar()
        )
        total += Decimal(str(contributions))
    except Exception:
        pass

    # ETF savings plan amounts (recurring rules linked to active plans)
    try:
        from app.models.etf import ETFSavingsPlan
        from app.models.transaction import RecurringRule

        etf_contributions = (
            db.session.query(func.coalesce(func.sum(RecurringRule.amount), 0))
            .join(ETFSavingsPlan, ETFSavingsPlan.recurring_rule_id == RecurringRule.id)
            .filter(
                ETFSavingsPlan.user_id == user.id,
                ETFSavingsPlan.active == True,  # noqa: E712
                RecurringRule.active == True,  # noqa: E712
            )
            .scalar()
        )
        total += Decimal(str(etf_contributions))
    except Exception:
        pass

    return float(total)


def _compute_current_net_worth(user: User) -> Decimal:
    """Compute the current net worth for a user (without snapshot).

    Validates: Requirement 18.5

    Calculated as:
        sum(active account balances)
        + sum(shares × current_price for active ETF positions)
        - sum(active credit remaining_balances)

    Args:
        user: The user.

    Returns:
        Current net worth as Decimal.
    """
    # Sum active account balances
    account_sum = (
        db.session.query(func.coalesce(func.sum(Account.balance), 0))
        .filter(
            Account.owner_id == user.id,
            Account.active == True,  # noqa: E712
        )
        .scalar()
    )
    total = Decimal(str(account_sum))

    # Add ETF portfolio value
    try:
        from app.models.etf import ETFPosition

        positions = ETFPosition.query.filter(
            ETFPosition.user_id == user.id,
            ETFPosition.shares > 0,
        ).all()
        for pos in positions:
            if pos.current_price is not None:
                total += pos.shares * pos.current_price
    except Exception:
        pass

    # Subtract active credit balances
    try:
        from app.models.credit import Credit, CreditStatus

        credit_sum = (
            db.session.query(func.coalesce(func.sum(Credit.remaining_balance), 0))
            .filter(
                Credit.user_id == user.id,
                Credit.status == CreditStatus.active,
            )
            .scalar()
        )
        total -= Decimal(str(credit_sum))
    except Exception:
        pass

    return total


# ---------------------------------------------------------------------------
# Date utilities
# ---------------------------------------------------------------------------


def _next_month(year: int, month: int) -> tuple[int, int]:
    """Return (year, month) for the month following the given month."""
    if month == 12:
        return year + 1, 1
    return year, month + 1


def _prev_month(year: int, month: int) -> tuple[int, int]:
    """Return (year, month) for the month preceding the given month."""
    if month == 1:
        return year - 1, 12
    return year, month - 1


# ---------------------------------------------------------------------------
# Sankey diagram route
# ---------------------------------------------------------------------------


@reports_bp.route("/sankey")
@login_required
def sankey():
    """Display a Sankey diagram showing money flow for an income cycle.

    Query params:
        cycle: integer offset (0 = current, -1 = previous, etc.)

    The diagram models flow as:
        Income sources → Expense categories → Accounts
    with special nodes for transfers and savings.
    """
    cycle_offset = request.args.get("cycle", 0, type=int)
    # Clamp: cannot go into the future
    if cycle_offset > 0:
        cycle_offset = 0

    # Compute cycle boundaries for the requested offset
    cycle_start, cycle_end = _get_offset_cycle_boundaries(current_user, cycle_offset)

    # Query personal transactions in the cycle
    transactions = Transaction.query.filter(
        Transaction.user_id == current_user.id,
        Transaction.scope == TransactionScope.personal,
        Transaction.date >= cycle_start,
        Transaction.date <= cycle_end,
    ).all()

    # Build Sankey data
    sankey_data = _build_sankey_data(transactions)

    return render_template(
        "reports/sankey.html",
        cycle_offset=cycle_offset,
        cycle_start=cycle_start,
        cycle_end=cycle_end,
        sankey_data=sankey_data,
    )


def _get_offset_cycle_boundaries(user: User, offset: int) -> tuple[date, date]:
    """Compute income cycle boundaries with a month offset.

    Args:
        user: The user whose income_day anchors the cycle.
        offset: 0 = current cycle, -1 = previous, -2 = two months ago, etc.

    Returns:
        Tuple of (cycle_start, cycle_end).
    """
    today = date.today()

    # Walk backwards/forwards by offset months from today
    ref_year = today.year
    ref_month = today.month

    steps = abs(offset)
    for _ in range(steps):
        if offset < 0:
            ref_year, ref_month = _prev_month(ref_year, ref_month)
        else:
            ref_year, ref_month = _next_month(ref_year, ref_month)

    # Build a reference date in the target month
    ref_date = date(ref_year, ref_month, min(today.day, 28))

    return _get_current_cycle_boundaries(user, ref_date)


def _build_sankey_data(transactions: list[Transaction]) -> dict:
    """Build Sankey nodes and links from a list of transactions.

    Flow structure (left to right):
        Income Sources → "Einkommen" → Categories → Descriptions
        Income Sources → "Einkommen" → "Gemeinsam" → Split items
        If spending > income: "Überschuss" node feeds into the deficit

    Args:
        transactions: All personal transactions in the cycle.

    Returns:
        Dict with "nodes" (list of {"name": str}) and
        "links" (list of {"source": int, "target": int, "value": float}).
    """
    from app.models.category import Category as CategoryModel
    from app.models.account import Account as AccountModel, AccountScope as AccScope
    from app.models.transaction import TransactionSplit

    # Separate by type
    incomes = [t for t in transactions if t.type == TransactionType.income]
    expenses = [t for t in transactions if t.type == TransactionType.expense]
    transfers = [t for t in transactions if t.type == TransactionType.transfer]

    total_income = sum(float(t.amount) for t in incomes)
    total_expenses = sum(float(t.amount) for t in expenses)

    # Calculate shared transfers total
    shared_transfer_total = 0.0
    shared_transfer_splits: dict[str, float] = {}

    for t in transfers:
        if t.destination_account_id:
            dest = db.session.get(AccountModel, t.destination_account_id)
            if dest and dest.scope == AccScope.shared:
                splits = TransactionSplit.query.filter_by(transaction_id=t.id).all()
                if splits:
                    for s in splits:
                        split_cat = db.session.get(CategoryModel, s.category_id)
                        split_name = s.description or (split_cat.name if split_cat else "Umbuchung")
                        shared_transfer_splits[split_name] = (
                            shared_transfer_splits.get(split_name, 0.0) + float(s.amount)
                        )
                        shared_transfer_total += float(s.amount)
                else:
                    desc = t.description or f"Umbuchung {t.date.strftime('%d.%m')}"
                    shared_transfer_splits[desc] = (
                        shared_transfer_splits.get(desc, 0.0) + float(t.amount)
                    )
                    shared_transfer_total += float(t.amount)

    total_outflow = total_expenses + shared_transfer_total

    if total_income == 0 and total_outflow == 0:
        return {"nodes": [], "links": []}

    # --- Build nodes and links ---
    nodes: list[dict] = []
    node_index: dict[str, int] = {}
    links: list[dict] = []

    def _get_or_add_node(name: str) -> int:
        if name not in node_index:
            node_index[name] = len(nodes)
            nodes.append({"name": name})
        return node_index[name]

    # Central income node
    income_idx = _get_or_add_node("Einkommen")

    # --- Stage 1: Income sources → Einkommen ---
    income_sources: dict[str, float] = {}
    for t in incomes:
        source_name = t.description or "Einkommen"
        income_sources[source_name] = income_sources.get(source_name, 0.0) + float(t.amount)

    for source_name, amount in sorted(income_sources.items(), key=lambda x: -x[1]):
        source_node = f"  {source_name}"  # leading spaces to differentiate from category nodes
        source_idx = _get_or_add_node(source_node)
        links.append({"source": source_idx, "target": income_idx, "value": round(amount, 2)})

    # --- Overspending: added later (at end) so it renders at the bottom ---
    overspend_amount = 0.0
    if total_outflow > total_income and total_income > 0:
        overspend_amount = total_outflow - total_income

    # The income node value represents the total outflow (either funded by income or overspending)
    # This ensures all flows balance

    # --- Stage 2: Einkommen → Categories ---
    category_descriptions: dict[str, dict[str, float]] = {}

    for t in expenses:
        if t.category_id:
            cat = db.session.get(CategoryModel, t.category_id)
            cat_name = cat.name if cat else "Sonstiges"
        else:
            cat_name = "Sonstiges"

        desc = t.description or f"Ausgabe {t.date.strftime('%d.%m')}"
        if cat_name not in category_descriptions:
            category_descriptions[cat_name] = {}
        category_descriptions[cat_name][desc] = (
            category_descriptions[cat_name].get(desc, 0.0) + float(t.amount)
        )

    for cat_name, desc_map in sorted(category_descriptions.items()):
        cat_total = sum(desc_map.values())
        cat_idx = _get_or_add_node(cat_name)
        links.append({"source": income_idx, "target": cat_idx, "value": round(cat_total, 2)})

    # --- Stage 2b: Einkommen → Gemeinsam ---
    if shared_transfer_total > 0:
        shared_idx = _get_or_add_node("Gemeinsam")
        links.append({"source": income_idx, "target": shared_idx, "value": round(shared_transfer_total, 2)})

        for desc, amount in sorted(shared_transfer_splits.items(), key=lambda x: -x[1]):
            desc_node = f"{desc}  "  # double space for uniqueness
            desc_idx = _get_or_add_node(desc_node)
            links.append({"source": shared_idx, "target": desc_idx, "value": round(amount, 2)})

    # --- If income > outflow, show remainder as "Gespart" ---
    if total_income > total_outflow:
        remainder = total_income - total_outflow
        if remainder > 0.01:
            saved_idx = _get_or_add_node("Gespart")
            links.append({"source": income_idx, "target": saved_idx, "value": round(remainder, 2)})

    # --- Overspending at the bottom (added last for positioning) ---
    if overspend_amount > 0:
        overspend_idx = _get_or_add_node("Überziehung")
        links.append({"source": overspend_idx, "target": income_idx, "value": round(overspend_amount, 2)})

    return {"nodes": nodes, "links": links}
