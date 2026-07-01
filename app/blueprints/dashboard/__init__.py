"""Dashboard blueprint for Haushaltsbuch.

Provides the home page (/) with personal and shared views of the user's
financial overview. View toggle is stored server-side in the Flask session.

Validates: Requirements 23.1, 23.2, 23.3, 23.4, 23.5
"""

from datetime import date
from decimal import Decimal

from flask import Blueprint, render_template, session, redirect, url_for, request, flash
from flask_login import login_required, current_user
from sqlalchemy import func

from app.extensions import db
from app.models.account import Account, AccountScope, AccountType
from app.models.budget import Budget, BudgetScope, SavingGoal, SavingGoalStatus, SavingGoalScope
from app.models.credit import Credit, CreditStatus, CreditScope
from app.models.planned_expense import PlannedExpense, PlannedExpenseScope
from app.models.transaction import (
    Transaction,
    TransactionScope,
    TransactionType,
    RecurringRule,
)
from app.services.balance_service import BalanceService
from app.services.budget_service import BudgetService

dashboard_bp = Blueprint(
    "dashboard",
    __name__,
    url_prefix="/",
    template_folder="templates",
)

_balance_service = BalanceService()
_budget_service = BudgetService()


@dashboard_bp.route("/")
@login_required
def index():
    """Display the home dashboard with personal or shared view.

    Validates: Requirements 23.1, 23.2, 23.3, 23.4, 23.5

    The view mode (personal/shared) is stored in session, defaulting to
    personal. The toggle is triggered via query parameter ?view=shared or
    ?view=personal.
    """
    # Handle view toggle via query parameter
    requested_view = request.args.get("view")
    if requested_view in ("personal", "shared"):
        session["dashboard_view"] = requested_view
        return redirect(url_for("dashboard.index"))

    view_mode = session.get("dashboard_view", "personal")

    if view_mode == "personal":
        context = _build_personal_context()
    else:
        context = _build_shared_context()

    context["view_mode"] = view_mode

    # Income rule for the cycle card
    income_rule = RecurringRule.query.filter_by(
        user_id=current_user.id,
        type=TransactionType.income,
        active=True,
        scope=TransactionScope.personal,
        name="Gehalt",
    ).first()
    context["income_rule"] = income_rule

    # Accounts for the income form dropdown
    personal_giro = Account.query.filter_by(
        owner_id=current_user.id, active=True, scope=AccountScope.personal, type=AccountType.spending
    ).all()
    context["personal_giro_accounts"] = personal_giro

    return render_template("dashboard/index.html", **context)


@dashboard_bp.route("/set-income", methods=["POST"])
@login_required
def set_income():
    """Create or update the monthly income recurring rule from the dashboard."""
    from app.services.balance_service import BalanceService

    amount = request.form.get("income_amount", type=float)
    account_id = request.form.get("income_account_id", type=int)

    if not amount or amount <= 0:
        flash("Bitte einen gültigen Betrag eingeben.", "danger")
        return redirect(url_for("dashboard.index"))

    if not account_id:
        flash("Bitte ein Konto auswählen.", "danger")
        return redirect(url_for("dashboard.index"))

    # Calculate next income date
    balance_service = BalanceService()
    next_income = balance_service.get_next_income_date(current_user)

    # Check if income rule already exists
    income_rule = RecurringRule.query.filter_by(
        user_id=current_user.id,
        type=TransactionType.income,
        active=True,
        scope=TransactionScope.personal,
        name="Gehalt",
    ).first()

    if income_rule:
        # Update existing
        income_rule.amount = Decimal(str(amount))
        income_rule.account_id = account_id
        income_rule.next_due_date = next_income
        flash("Gehalt erfolgreich aktualisiert.", "success")
    else:
        # Create new
        from app.models.transaction import RecurringFrequency
        income_rule = RecurringRule(
            name="Gehalt",
            type=TransactionType.income,
            frequency=RecurringFrequency.monthly,
            interval=1,
            amount=Decimal(str(amount)),
            next_due_date=next_income,
            active=True,
            scope=TransactionScope.personal,
            account_id=account_id,
            user_id=current_user.id,
        )
        db.session.add(income_rule)
        flash("Gehalt erfolgreich eingerichtet.", "success")

    db.session.commit()
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/run-recurring", methods=["POST"])
@login_required
def run_recurring():
    """Manually trigger recurring rule processing for the current user."""
    from app.services.recurring_service import RecurringService

    service = RecurringService()
    try:
        generated = service.process_due_rules(current_user)
        if generated:
            flash(f"{len(generated)} Transaktion(en) aus Daueraufträgen gebucht.", "success")
        else:
            flash("Keine fälligen Daueraufträge gefunden.", "info")
    except Exception as e:
        flash(f"Fehler: {e}", "danger")

    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/set-household-split", methods=["POST"])
@login_required
def set_household_split():
    """Configure household split tags and account."""
    import json

    account_id = request.form.get("split_account_id", type=int)
    person1_tag = request.form.get("person1_tag", "").strip()
    person2_tag = request.form.get("person2_tag", "").strip()
    shared_tag = request.form.get("shared_tag", "").strip()

    if not person1_tag or not person2_tag or not shared_tag:
        flash("Bitte alle Tag-Namen ausfüllen.", "danger")
        return redirect(url_for("dashboard.index"))

    current_user.household_split_account_id = account_id
    current_user.household_split_tags = json.dumps({
        "person1": person1_tag,
        "person2": person2_tag,
        "shared": shared_tag,
    })
    db.session.commit()
    flash("Haushaltsaufteilung konfiguriert.", "success")
    return redirect(url_for("dashboard.index"))


def _build_personal_context() -> dict:
    """Build template context for the personal dashboard view.

    Validates: Requirement 23.2
    """
    user = current_user

    # All active personal accounts
    personal_accounts = Account.query.filter_by(
        owner_id=user.id, active=True, scope=AccountScope.personal
    ).all()

    # Kontostand: Sum of all Giro accounts
    giro_accounts = [a for a in personal_accounts if a.type == AccountType.spending]
    kontostand = sum((a.balance for a in giro_accounts), Decimal("0.00"))

    # Verfügbar: Sum of available balances for Giro accounts (balance minus blocked)
    verfuegbar = Decimal("0.00")
    for account in giro_accounts:
        try:
            verfuegbar += _balance_service.get_available_balance(account.id)
        except (ValueError, Exception):
            verfuegbar += account.balance

    # Vermögen: Everything in every personal account minus personal credits
    total_all_accounts = sum((a.balance for a in personal_accounts), Decimal("0.00"))
    active_credits = Credit.query.filter_by(
        user_id=user.id,
        status=CreditStatus.active,
        scope=CreditScope.personal,
    ).all()
    total_credit_debt = sum((c.remaining_balance for c in active_credits), Decimal("0.00"))
    vermoegen = total_all_accounts - total_credit_debt

    # Notgroschen: Sum of all Saving accounts
    saving_accounts = [a for a in personal_accounts if a.type == AccountType.saving]
    notgroschen = sum((a.balance for a in saving_accounts), Decimal("0.00"))

    # Rücklagen: Sum of all Reserve accounts
    reserve_accounts = [a for a in personal_accounts if a.type == AccountType.reserve]
    ruecklagen = sum((a.balance for a in reserve_accounts), Decimal("0.00"))

    # Schulden: Credit card debt + credit debt
    credit_cards = [a for a in personal_accounts if a.type == AccountType.credit_card]
    credit_card_debt = sum(
        (abs(a.balance) for a in credit_cards if a.balance < 0), Decimal("0.00")
    )
    schulden = credit_card_debt + total_credit_debt

    # Income cycle progress bar
    income_cycle_progress = _compute_income_cycle_progress(user)

    # Spending by category in current income cycle (for pie chart)
    spending_by_category = _get_spending_by_category(user, income_cycle_progress)

    # Top 3 budgets by percentage used
    top_budgets = _get_top_budgets(user, BudgetScope.personal, limit=3)

    # Next 5 upcoming recurring expenses (personal, active, expense type)
    next_recurring = (
        RecurringRule.query.filter_by(
            user_id=user.id,
            active=True,
            scope=TransactionScope.personal,
            type=TransactionType.expense,
        )
        .order_by(RecurringRule.next_due_date.asc())
        .limit(5)
        .all()
    )

    # Unresolved planned expenses (personal)
    unresolved_planned = (
        PlannedExpense.query.filter_by(
            user_id=user.id,
            resolved=False,
            scope=PlannedExpenseScope.personal,
        )
        .order_by(PlannedExpense.created_at.asc())
        .all()
    )

    # Last 5 transactions (personal, sorted by date descending)
    last_transactions = (
        Transaction.query.filter_by(
            user_id=user.id,
            scope=TransactionScope.personal,
        )
        .order_by(Transaction.date.desc(), Transaction.created_at.desc())
        .limit(5)
        .all()
    )

    # Active credits (personal)
    active_credits = Credit.query.filter_by(
        user_id=user.id,
        status=CreditStatus.active,
        scope=CreditScope.personal,
    ).all()

    # Top 3 saving goals by progress percentage
    top_saving_goals = _get_top_saving_goals(user, SavingGoalScope.personal, limit=3)

    # Open credit card payments (unpaid, personal)
    open_cc_payments = (
        Transaction.query
        .join(Account, Transaction.account_id == Account.id)
        .filter(
            Transaction.user_id == user.id,
            Transaction.paid == False,  # noqa: E712
            Account.type == AccountType.credit_card,
            Account.scope == AccountScope.personal,
        )
        .order_by(Transaction.due_date.asc())
        .limit(5)
        .all()
    )

    return {
        "kontostand": kontostand,
        "verfuegbar": verfuegbar,
        "ruecklagen": ruecklagen,
        "vermoegen": vermoegen,
        "notgroschen": notgroschen,
        "schulden": schulden,
        "income_cycle_progress": income_cycle_progress,
        "spending_by_category": spending_by_category,
        "top_budgets": top_budgets,
        "next_recurring": next_recurring,
        "unresolved_planned": unresolved_planned,
        "last_transactions": last_transactions,
        "active_credits": active_credits,
        "top_saving_goals": top_saving_goals,
        "open_cc_payments": open_cc_payments,
    }


def _build_shared_context() -> dict:
    """Build template context for the shared dashboard view.

    Validates: Requirement 23.3
    """
    user = current_user

    # All active shared accounts
    shared_accounts = Account.query.filter_by(
        scope=AccountScope.shared, active=True
    ).all()

    # Kontostand: Sum of all shared Giro accounts
    giro_accounts = [a for a in shared_accounts if a.type == AccountType.spending]
    kontostand = sum((a.balance for a in giro_accounts), Decimal("0.00"))

    # Verfügbar: Available balance on shared Giro accounts
    verfuegbar = Decimal("0.00")
    for account in giro_accounts:
        try:
            verfuegbar += _balance_service.get_available_balance(account.id)
        except (ValueError, Exception):
            verfuegbar += account.balance

    # Vermögen: All shared accounts minus shared credits
    total_all_shared = sum((a.balance for a in shared_accounts), Decimal("0.00"))
    shared_credits = Credit.query.filter_by(
        status=CreditStatus.active,
        scope=CreditScope.shared,
    ).all()
    total_shared_credit_debt = sum((c.remaining_balance for c in shared_credits), Decimal("0.00"))
    vermoegen = total_all_shared - total_shared_credit_debt

    # Notgroschen: Sum of shared Saving accounts
    saving_accounts = [a for a in shared_accounts if a.type == AccountType.saving]
    notgroschen = sum((a.balance for a in saving_accounts), Decimal("0.00"))

    # Rücklagen: Sum of shared Reserve accounts
    reserve_accounts = [a for a in shared_accounts if a.type == AccountType.reserve]
    ruecklagen = sum((a.balance for a in reserve_accounts), Decimal("0.00"))

    # Schulden: Shared credit card debt + shared credit debt
    credit_cards = [a for a in shared_accounts if a.type == AccountType.credit_card]
    credit_card_debt = sum(
        (abs(a.balance) for a in credit_cards if a.balance < 0), Decimal("0.00")
    )
    schulden = credit_card_debt + total_shared_credit_debt

    # Shared budget utilisation (top 3 shared budgets by percentage used)
    top_shared_budgets = _get_top_budgets(user, BudgetScope.shared, limit=3)

    # Spending by category for shared (use shared_income_day or fallback to personal)
    shared_income_day = user.shared_income_day or user.income_day
    # Build a fake progress dict for shared cycle
    from app.services.banking_day_service import BankingDayService
    banking_service = BankingDayService()
    today = date.today()
    try:
        # Compute shared cycle boundaries
        this_month_income = banking_service.get_effective_income_day(shared_income_day, today.year, today.month)
        if today >= this_month_income:
            shared_last_income = this_month_income
            if today.month == 12:
                shared_next_income = banking_service.get_effective_income_day(shared_income_day, today.year + 1, 1)
            else:
                shared_next_income = banking_service.get_effective_income_day(shared_income_day, today.year, today.month + 1)
        else:
            shared_next_income = this_month_income
            if today.month == 1:
                shared_last_income = banking_service.get_effective_income_day(shared_income_day, today.year - 1, 12)
            else:
                shared_last_income = banking_service.get_effective_income_day(shared_income_day, today.year, today.month - 1)
    except Exception:
        shared_last_income = date(today.year, today.month, 1)
        shared_next_income = date(today.year, today.month + 1, 1) if today.month < 12 else date(today.year + 1, 1, 1)

    shared_cycle_progress = {
        "last_income_date": shared_last_income,
        "next_income_date": shared_next_income,
    }
    shared_spending_by_category = _get_spending_by_category_shared(shared_last_income, shared_next_income)

    # Net settlement balance
    net_settlement = _get_net_settlement_balance(user)

    # Next 5 upcoming shared recurring expenses
    next_shared_recurring = (
        RecurringRule.query.filter_by(
            active=True,
            scope=TransactionScope.shared,
            type=TransactionType.expense,
        )
        .order_by(RecurringRule.next_due_date.asc())
        .limit(5)
        .all()
    )

    # Last 5 shared transactions
    last_shared_transactions = (
        Transaction.query.filter_by(
            scope=TransactionScope.shared,
        )
        .order_by(Transaction.date.desc(), Transaction.created_at.desc())
        .limit(5)
        .all()
    )

    return {
        "kontostand": kontostand,
        "verfuegbar": verfuegbar,
        "ruecklagen": ruecklagen,
        "vermoegen": vermoegen,
        "notgroschen": notgroschen,
        "schulden": schulden,
        "top_shared_budgets": top_shared_budgets,
        "spending_by_category": shared_spending_by_category,
        "net_settlement": net_settlement,
        "next_shared_recurring": next_shared_recurring,
        "last_shared_transactions": last_shared_transactions,
        "household_split": _compute_household_split(user),
        "top_shared_saving_goals": _get_top_saving_goals(user, SavingGoalScope.shared, limit=5),
    }


def _compute_income_cycle_progress(user) -> dict:
    """Compute income cycle progress as percentage of days elapsed.

    Returns dict with 'percentage', 'last_income_date', 'next_income_date'.
    """
    today = date.today()

    try:
        next_income = _balance_service.get_next_income_date(user)

        # Compute last income date (previous cycle start)
        if today.month == 1:
            prev_year, prev_month = today.year - 1, 12
        else:
            prev_year, prev_month = today.year, today.month - 1

        last_income = _balance_service.get_effective_income_day(
            user, prev_year, prev_month
        )

        # If next_income is this month's income day and we haven't reached it
        # yet, then last_income should be from the month before
        this_month_income = _balance_service.get_effective_income_day(
            user, today.year, today.month
        )

        if today >= this_month_income:
            last_income = this_month_income
        # else last_income stays as previous month

        total_days = (next_income - last_income).days
        elapsed_days = (today - last_income).days

        if total_days > 0:
            percentage = min(100, max(0, int((elapsed_days / total_days) * 100)))
        else:
            percentage = 0

        return {
            "percentage": percentage,
            "last_income_date": last_income,
            "next_income_date": next_income,
        }
    except Exception:
        return {
            "percentage": 0,
            "last_income_date": None,
            "next_income_date": None,
        }


def _get_top_budgets(user, scope: BudgetScope, limit: int = 3) -> list[dict]:
    """Get top N budgets by utilisation percentage.

    Returns list of dicts with 'budget', 'spent', 'percentage'.
    """
    budgets = Budget.query.filter_by(
        user_id=user.id,
        scope=scope,
    ).all()

    budget_data = []
    for budget in budgets:
        try:
            details = _budget_service.get_utilisation_with_details(budget, user)
            spent = details.get("spent", Decimal("0.00"))
            percentage = (
                int((spent / budget.amount) * 100)
                if budget.amount > 0
                else 0
            )
            budget_data.append({
                "budget": budget,
                "spent": spent,
                "percentage": min(percentage, 999),  # Cap display at 999%
            })
        except Exception:
            budget_data.append({
                "budget": budget,
                "spent": Decimal("0.00"),
                "percentage": 0,
            })

    # Sort by percentage descending, take top N
    budget_data.sort(key=lambda x: x["percentage"], reverse=True)
    return budget_data[:limit]


def _get_top_saving_goals(user, scope: SavingGoalScope, limit: int = 3) -> list[dict]:
    """Get top N saving goals by progress percentage.

    Returns list of dicts with 'goal', 'contributed', 'percentage'.
    """
    from app.services.saving_goal_service import SavingGoalService

    _saving_service = SavingGoalService()

    goals = SavingGoal.query.filter_by(
        user_id=user.id,
        status=SavingGoalStatus.active,
        scope=scope,
    ).all()

    goal_data = []
    for goal in goals:
        contributed = _saving_service.get_contributions_total(goal)
        if goal.target_amount and goal.target_amount > 0:
            percentage = int((contributed / goal.target_amount) * 100)
        else:
            percentage = 0  # Open-ended goals have no progress percentage

        goal_data.append({
            "goal": goal,
            "contributed": contributed,
            "percentage": min(percentage, 999),
        })

    # Sort by percentage descending, take top N
    goal_data.sort(key=lambda x: x["percentage"], reverse=True)
    return goal_data[:limit]


def _get_net_settlement_balance(user) -> dict:
    """Get net settlement balance between partners.

    Returns dict with 'amount', 'direction' ('owes' or 'owed'), 'partner_name'.
    """
    from app.models.user import User
    from app.services.settlement_service import SettlementService

    _settlement_service = SettlementService()

    try:
        net_balance = _settlement_service.get_net_balance(user)
        partner = User.query.filter(User.id != user.id).first()
        partner_name = partner.username if partner else "Partner"

        if net_balance > 0:
            direction = "owed"  # Partner owes current user
        elif net_balance < 0:
            direction = "owes"  # Current user owes partner
        else:
            direction = "settled"

        return {
            "amount": abs(net_balance),
            "direction": direction,
            "partner_name": partner_name,
        }
    except Exception:
        return {
            "amount": Decimal("0.00"),
            "direction": "settled",
            "partner_name": "Partner",
        }


def _get_spending_by_category(user, income_cycle_progress: dict) -> list[dict]:
    """Get spending grouped by category for the current income cycle.

    Returns list of dicts with 'name', 'amount', 'color'.
    """
    from app.models.category import Category

    # Determine date range from income cycle
    last_income = income_cycle_progress.get("last_income_date")
    next_income = income_cycle_progress.get("next_income_date")

    if not last_income or not next_income:
        return []

    # Get all personal expenses in the current cycle
    expenses = (
        Transaction.query
        .filter(
            Transaction.user_id == user.id,
            Transaction.type == TransactionType.expense,
            Transaction.scope == TransactionScope.personal,
            Transaction.date >= last_income,
            Transaction.date < next_income,
        )
        .all()
    )

    if not expenses:
        return []

    # Group by category
    category_totals = {}
    for txn in expenses:
        cat_name = "Ohne Kategorie"
        if txn.category_id:
            cat = db.session.get(Category, txn.category_id)
            if cat:
                cat_name = cat.name
        category_totals[cat_name] = category_totals.get(cat_name, Decimal("0.00")) + txn.amount

    # Sort by amount descending
    sorted_cats = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)

    # Assign colors (cycle through a palette)
    colors = ["#ff8c00", "#22c55e", "#3b82f6", "#ef4444", "#a855f7", "#f59e0b", "#14b8a6", "#ec4899", "#6366f1", "#84cc16"]

    result = []
    for i, (name, amount) in enumerate(sorted_cats):
        result.append({
            "name": name,
            "amount": float(amount),
            "color": colors[i % len(colors)],
        })

    return result


def _get_spending_by_category_shared(last_income: date, next_income: date) -> list[dict]:
    """Get shared spending grouped by category for the current shared income cycle."""
    from app.models.category import Category

    expenses = (
        Transaction.query
        .filter(
            Transaction.type == TransactionType.expense,
            Transaction.scope == TransactionScope.shared,
            Transaction.date >= last_income,
            Transaction.date < next_income,
        )
        .all()
    )

    if not expenses:
        return []

    category_totals = {}
    for txn in expenses:
        cat_name = "Ohne Kategorie"
        if txn.category_id:
            cat = db.session.get(Category, txn.category_id)
            if cat:
                cat_name = cat.name
        category_totals[cat_name] = category_totals.get(cat_name, Decimal("0.00")) + txn.amount

    sorted_cats = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
    colors = ["#ff8c00", "#22c55e", "#3b82f6", "#ef4444", "#a855f7", "#f59e0b", "#14b8a6", "#ec4899", "#6366f1", "#84cc16"]

    result = []
    for i, (name, amount) in enumerate(sorted_cats):
        result.append({
            "name": name,
            "amount": float(amount),
            "color": colors[i % len(colors)],
        })

    return result


def _compute_household_split(user) -> dict:
    """Compute the household split breakdown based on tagged recurring rules.

    Uses recurring expense rules on the configured account, grouped by tags.
    Calculates monthly equivalent for each rule.
    Sum = personal_tag_total + 50% of shared_tag_total, rounded up to next 50€ + 50€.
    """
    import json
    import math

    result = {
        "configured": False,
        "person1": {"name": "", "items": [], "total": Decimal("0.00"), "payment": Decimal("0.00")},
        "person2": {"name": "", "items": [], "total": Decimal("0.00"), "payment": Decimal("0.00")},
        "shared": {"name": "", "items": [], "total": Decimal("0.00")},
        "account_id": None,
        "accounts": [],
    }

    # Get accounts for config dropdown
    all_accounts = Account.query.filter_by(owner_id=user.id, active=True).all()
    result["accounts"] = all_accounts

    # Check if configured
    if not user.household_split_tags:
        return result

    try:
        tags_config = json.loads(user.household_split_tags)
    except (json.JSONDecodeError, TypeError):
        return result

    person1_name = tags_config.get("person1", "")
    person2_name = tags_config.get("person2", "")
    shared_name = tags_config.get("shared", "")

    if not person1_name or not person2_name or not shared_name:
        return result

    result["configured"] = True
    result["person1"]["name"] = person1_name
    result["person2"]["name"] = person2_name
    result["shared"]["name"] = shared_name
    result["account_id"] = user.household_split_account_id

    # Get recurring rules for the configured account
    account_id = user.household_split_account_id
    if not account_id:
        return result

    rules = RecurringRule.query.filter(
        RecurringRule.account_id == account_id,
        RecurringRule.active == True,  # noqa: E712
        RecurringRule.type.in_([TransactionType.expense, TransactionType.transfer]),
    ).all()

    # Helper: compute monthly equivalent
    def monthly_equiv(rule):
        freq = rule.frequency.value
        interval = rule.interval
        amount = rule.amount
        if freq == "daily":
            return amount * Decimal("30") / Decimal(str(interval))
        elif freq == "weekly":
            return amount * Decimal("4.33") / Decimal(str(interval))
        elif freq == "monthly":
            return amount / Decimal(str(interval))
        elif freq == "quarterly":
            return amount / (Decimal("3") * Decimal(str(interval)))
        elif freq == "yearly":
            return amount / (Decimal("12") * Decimal(str(interval)))
        return amount

    # Categorize rules by their tags
    from app.models.transaction import Tag

    for rule in rules:
        monthly = monthly_equiv(rule).quantize(Decimal("0.01"))
        rule_tags = [t.name for t in rule.tags] if rule.tags else []

        item = {"name": rule.name, "amount": monthly}

        if person1_name in rule_tags:
            result["person1"]["items"].append(item)
            result["person1"]["total"] += monthly
        elif person2_name in rule_tags:
            result["person2"]["items"].append(item)
            result["person2"]["total"] += monthly
        elif shared_name in rule_tags:
            result["shared"]["items"].append(item)
            result["shared"]["total"] += monthly

    # Calculate payment: personal_total + 50% shared, round up to next 50€, add 50€
    shared_half = result["shared"]["total"] / Decimal("2")

    p1_raw = result["person1"]["total"] + shared_half
    p2_raw = result["person2"]["total"] + shared_half

    def round_up_50_plus_50(val):
        raw = float(val)
        rounded = math.ceil(raw / 10) * 10
        return Decimal(str(rounded + 50))

    result["person1"]["payment"] = round_up_50_plus_50(p1_raw)
    result["person2"]["payment"] = round_up_50_plus_50(p2_raw)

    return result
