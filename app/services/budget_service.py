"""Budget service for Haushaltsbuch.

Implements budget creation with validation, period boundary calculation
aligned to income_day, utilisation calculation, and threshold notifications.

Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, func

from app.extensions import db
from app.models.budget import Budget, BudgetPeriod, BudgetScope
from app.models.transaction import Transaction, TransactionScope, TransactionType
from app.models.user import User
from app.services.banking_day_service import BankingDayService
from app.services.audit_service import AuditService


# Amount validation bounds (Requirement 6.8)
MIN_AMOUNT = Decimal("0.01")
MAX_AMOUNT = Decimal("999999999.99")


class BudgetService:
    """Service class for budget management, utilisation, and threshold checking.

    Handles budget CRUD, period boundary computation aligned to the user's
    income_day, and notification generation for 80%/100% thresholds.
    """

    def __init__(self) -> None:
        self._banking_day_service = BankingDayService()
        self._audit_service = AuditService()

    def create_budget(
        self,
        user: User,
        name: str,
        scope: str | BudgetScope,
        amount: Decimal,
        period: str | BudgetPeriod,
        start_date: date,
        category_id: int | None = None,
    ) -> Budget:
        """Create a new budget linked to the user.

        Validates: Requirements 6.1, 6.8

        Args:
            user: The user creating the budget.
            name: Budget name (1-100 characters).
            scope: 'personal' or 'shared'.
            amount: Spending limit (0.01 to 999,999,999.99).
            period: 'weekly', 'monthly', 'quarterly', or 'yearly'.
            start_date: The budget start date.
            category_id: Optional category FK. If None, budget is a total spending cap.

        Returns:
            The newly created Budget instance.

        Raises:
            ValueError: If name is empty or amount is out of range.
        """
        # Validate name (Req 6.8)
        if not name or not name.strip():
            raise ValueError("Budget name must not be empty.")
        name = name.strip()
        if len(name) > 100:
            raise ValueError("Budget name must not exceed 100 characters.")

        # Validate amount (Req 6.8)
        amount = Decimal(str(amount))
        if amount < MIN_AMOUNT or amount > MAX_AMOUNT:
            raise ValueError(
                f"Budget amount must be between {MIN_AMOUNT} and "
                f"{MAX_AMOUNT}. Got: {amount}"
            )

        # Resolve enum values
        if isinstance(scope, str):
            scope = BudgetScope(scope)
        if isinstance(period, str):
            period = BudgetPeriod(period)

        budget = Budget(
            name=name,
            scope=scope,
            category_id=category_id,
            amount=amount,
            period=period,
            start_date=start_date,
            user_id=user.id,
        )

        db.session.add(budget)
        db.session.flush()

        # Audit log (Req 22.1)
        self._audit_service.log_change(
            action="create",
            model="Budget",
            record_id=budget.id,
            old_values=None,
            new_values={
                "name": budget.name,
                "scope": budget.scope.value,
                "amount": str(budget.amount),
                "period": budget.period.value,
            },
            user_id=user.id,
        )

        db.session.commit()
        return budget

    def get_period_boundaries(
        self, budget: Budget, user: User, reference_date: date | None = None
    ) -> tuple[date, date]:
        """Calculate the current period boundaries for a budget.

        Validates: Requirement 6.2

        Period boundaries use the user's income_day as anchor:
        - monthly: income day N to day before income day N+1
        - weekly: 7-day windows starting from the effective income day
        - quarterly: 3 consecutive monthly income cycles
        - yearly: 12 consecutive monthly income cycles

        Args:
            budget: The budget to calculate boundaries for.
            user: The user owning the budget (provides income_day).
            reference_date: The date to find the period for (defaults to today).

        Returns:
            A tuple (period_start, period_end) as inclusive dates.
        """
        if reference_date is None:
            reference_date = date.today()

        income_day = user.income_day

        if budget.period == BudgetPeriod.monthly:
            return self._monthly_boundaries(income_day, reference_date)
        elif budget.period == BudgetPeriod.weekly:
            return self._weekly_boundaries(income_day, reference_date)
        elif budget.period == BudgetPeriod.quarterly:
            return self._quarterly_boundaries(income_day, reference_date)
        elif budget.period == BudgetPeriod.yearly:
            return self._yearly_boundaries(income_day, reference_date)
        else:
            raise ValueError(f"Unknown budget period: {budget.period}")

    def calculate_utilisation(
        self, budget: Budget, user: User, reference_date: date | None = None
    ) -> Decimal:
        """Calculate budget utilisation for the current period.

        Validates: Requirements 6.3, 6.6, 6.7

        Utilisation = sum of expense-type transactions matching budget's
        category (or all if none) and scope within the current period,
        divided by the budget amount.

        For shared budgets, includes expenses from both household members.

        Args:
            budget: The budget to calculate utilisation for.
            user: The user (used for period boundary calculation).
            reference_date: Optional reference date (defaults to today).

        Returns:
            Utilisation as a Decimal ratio (e.g. 0.75 = 75%).
        """
        period_start, period_end = self.get_period_boundaries(
            budget, user, reference_date
        )

        total_expenses = self._sum_expenses_in_period(
            budget, period_start, period_end
        )

        if budget.amount == 0:
            return Decimal("0")

        return total_expenses / budget.amount

    def check_thresholds(
        self, budget: Budget, user: User, reference_date: date | None = None
    ) -> list[str]:
        """Check if budget utilisation triggers threshold notifications.

        Validates: Requirements 6.4, 6.5

        Returns notification types that should be generated:
        - 'budget_warning' when utilisation >= 80%
        - 'budget_exceeded' when utilisation >= 100%

        Each notification type is returned at most once per budget per period
        (deduplication based on existing notifications for the current period).

        Args:
            budget: The budget to check.
            user: The user owning the budget.
            reference_date: Optional reference date (defaults to today).

        Returns:
            List of notification type strings to generate.
        """
        utilisation = self.calculate_utilisation(budget, user, reference_date)
        period_start, period_end = self.get_period_boundaries(
            budget, user, reference_date
        )

        notifications: list[str] = []

        # Check existing notifications for deduplication
        existing_types = self._get_existing_notification_types(
            budget, user, period_start, period_end
        )

        # 80% threshold (Req 6.4)
        if utilisation >= Decimal("0.8") and "budget_warning" not in existing_types:
            notifications.append("budget_warning")

        # 100% threshold (Req 6.5)
        if utilisation >= Decimal("1.0") and "budget_exceeded" not in existing_types:
            notifications.append("budget_exceeded")

        return notifications

    # -------------------------------------------------------------------------
    # Period boundary calculations
    # -------------------------------------------------------------------------

    def _monthly_boundaries(
        self, income_day: int, reference_date: date
    ) -> tuple[date, date]:
        """Calculate monthly period boundaries aligned to income_day.

        Monthly period: effective income day of month M to the day before
        effective income day of month M+1.
        """
        # Find the effective income day for the reference month
        effective_this_month = self._banking_day_service.get_effective_income_day(
            income_day, reference_date.year, reference_date.month
        )

        if reference_date >= effective_this_month:
            # We're in the period starting this month
            period_start = effective_this_month
            # End is day before next month's effective income day
            next_year, next_month = self._next_month(
                reference_date.year, reference_date.month
            )
            effective_next = self._banking_day_service.get_effective_income_day(
                income_day, next_year, next_month
            )
            period_end = effective_next - timedelta(days=1)
        else:
            # We're in the period that started last month
            prev_year, prev_month = self._prev_month(
                reference_date.year, reference_date.month
            )
            period_start = self._banking_day_service.get_effective_income_day(
                income_day, prev_year, prev_month
            )
            period_end = effective_this_month - timedelta(days=1)

        return period_start, period_end

    def _weekly_boundaries(
        self, income_day: int, reference_date: date
    ) -> tuple[date, date]:
        """Calculate weekly period boundaries.

        Weekly periods are 7-day windows starting from the effective income day
        of the current monthly cycle.
        """
        # First, find the monthly cycle start
        monthly_start, _ = self._monthly_boundaries(income_day, reference_date)

        # Calculate which 7-day window we're in
        days_since_start = (reference_date - monthly_start).days
        week_number = days_since_start // 7
        period_start = monthly_start + timedelta(days=week_number * 7)
        period_end = period_start + timedelta(days=6)

        return period_start, period_end

    def _quarterly_boundaries(
        self, income_day: int, reference_date: date
    ) -> tuple[date, date]:
        """Calculate quarterly period boundaries (3 consecutive income cycles)."""
        # Find current monthly cycle start
        monthly_start, _ = self._monthly_boundaries(income_day, reference_date)

        # Determine which quarter we're in based on month offset from start
        # Quarters start at months 1, 4, 7, 10 aligned to income cycles
        month = monthly_start.month
        # Quarter start months: 1, 4, 7, 10
        quarter_start_month = ((month - 1) // 3) * 3 + 1
        quarter_start_year = monthly_start.year

        period_start = self._banking_day_service.get_effective_income_day(
            income_day, quarter_start_year, quarter_start_month
        )

        # End is day before the start of the next quarter (3 months later)
        end_year, end_month = quarter_start_year, quarter_start_month
        for _ in range(3):
            end_year, end_month = self._next_month(end_year, end_month)

        effective_end = self._banking_day_service.get_effective_income_day(
            income_day, end_year, end_month
        )
        period_end = effective_end - timedelta(days=1)

        return period_start, period_end

    def _yearly_boundaries(
        self, income_day: int, reference_date: date
    ) -> tuple[date, date]:
        """Calculate yearly period boundaries (12 consecutive income cycles)."""
        # Find which yearly cycle we're in
        # A yearly cycle starts on the effective income day of a given month
        # We use January as the anchor month for yearly cycles
        effective_this_year = self._banking_day_service.get_effective_income_day(
            income_day, reference_date.year, 1
        )

        if reference_date >= effective_this_year:
            period_start = effective_this_year
            effective_next_year = self._banking_day_service.get_effective_income_day(
                income_day, reference_date.year + 1, 1
            )
            period_end = effective_next_year - timedelta(days=1)
        else:
            period_start = self._banking_day_service.get_effective_income_day(
                income_day, reference_date.year - 1, 1
            )
            period_end = effective_this_year - timedelta(days=1)

        return period_start, period_end

    # -------------------------------------------------------------------------
    # Expense summation
    # -------------------------------------------------------------------------

    def _sum_expenses_in_period(
        self, budget: Budget, period_start: date, period_end: date
    ) -> Decimal:
        """Sum expense-type transactions matching budget criteria within a period.

        Validates: Requirements 6.3, 6.6, 6.7

        - If budget has a category, only sums expenses in that category.
        - If budget has no category (NULL), sums all expenses (total spending cap).
        - For personal scope: only the budget owner's expenses.
        - For shared scope: both household members' expenses with shared scope.
        """
        # Determine the matching transaction scope
        if budget.scope == BudgetScope.personal:
            txn_scope = TransactionScope.personal
        else:
            txn_scope = TransactionScope.shared

        # Build query filters
        filters = [
            Transaction.type == TransactionType.expense,
            Transaction.scope == txn_scope,
            Transaction.date >= period_start,
            Transaction.date <= period_end,
        ]

        # Scope filtering (Req 6.7)
        if budget.scope == BudgetScope.personal:
            # Only the budget owner's transactions
            filters.append(Transaction.user_id == budget.user_id)
        # For shared scope: include all users' shared transactions (no user_id filter)

        # Category filtering (Req 6.6)
        if budget.category_id is not None:
            filters.append(Transaction.category_id == budget.category_id)

        result = db.session.query(
            func.coalesce(func.sum(Transaction.amount), Decimal("0"))
        ).filter(and_(*filters)).scalar()

        return Decimal(str(result)) if result is not None else Decimal("0")

    # -------------------------------------------------------------------------
    # Notification deduplication
    # -------------------------------------------------------------------------

    def _get_existing_notification_types(
        self,
        budget: Budget,
        user: User,
        period_start: date,
        period_end: date,
    ) -> set[str]:
        """Check which notification types already exist for this budget in the current period.

        Validates: Requirements 6.4, 6.5 (one notification per budget per period)

        Since the Notification model is not yet implemented, this attempts to
        query it if available, otherwise returns an empty set (allowing
        notifications to be generated).
        """
        try:
            from app.models.notification import Notification

            existing = (
                db.session.query(Notification.type)
                .filter(
                    Notification.entity_id == budget.id,
                    Notification.type.in_(["budget_warning", "budget_exceeded"]),
                    Notification.created_at >= period_start,
                    Notification.created_at <= period_end,
                )
                .all()
            )
            return {n.type for n in existing}
        except (ImportError, Exception):
            # Notification model not yet implemented; no deduplication available
            return set()

    # -------------------------------------------------------------------------
    # CRUD operations for blueprint
    # -------------------------------------------------------------------------

    def get_budgets_for_user(self, user: User) -> list[Budget]:
        """Get all budgets visible to the user.

        Personal budgets owned by the user plus all shared budgets
        (both household members can view/edit/delete shared budgets).

        Validates: Requirement 6.7

        Args:
            user: The requesting user.

        Returns:
            List of Budget instances ordered by name.
        """
        from sqlalchemy import or_

        return Budget.query.filter(
            or_(
                Budget.user_id == user.id,
                Budget.scope == BudgetScope.shared,
            )
        ).order_by(Budget.name).all()

    def edit_budget(
        self,
        budget_id: int,
        user: User,
        **updates,
    ) -> Budget:
        """Edit an existing budget.

        Validates: Requirement 6.7

        Args:
            budget_id: ID of the budget to edit.
            user: The requesting user.
            **updates: Fields to update (name, scope, category_id, amount, period, start_date).

        Returns:
            The updated Budget instance.

        Raises:
            ValueError: If budget not found or user has no access.
        """
        budget = db.session.get(Budget, budget_id)
        if budget is None:
            raise ValueError("Budget nicht gefunden.")

        # Access check: owner or shared budget
        if budget.user_id != user.id and budget.scope != BudgetScope.shared:
            raise ValueError("Kein Zugriff auf dieses Budget.")

        # Capture old values for audit
        old_values = {}
        for field in ("name", "scope", "category_id", "amount", "period", "start_date"):
            if field in updates:
                val = getattr(budget, field)
                if hasattr(val, "value"):
                    val = val.value
                elif isinstance(val, Decimal):
                    val = str(val)
                elif isinstance(val, date):
                    val = val.isoformat()
                old_values[field] = val

        for field in ("name", "scope", "category_id", "amount", "period", "start_date"):
            if field in updates:
                value = updates[field]
                if field == "scope" and isinstance(value, str):
                    value = BudgetScope(value)
                elif field == "period" and isinstance(value, str):
                    value = BudgetPeriod(value)
                setattr(budget, field, value)

        # Audit log (Req 22.1)
        if old_values:
            new_values = {}
            for field in old_values:
                val = getattr(budget, field)
                if hasattr(val, "value"):
                    val = val.value
                elif isinstance(val, Decimal):
                    val = str(val)
                elif isinstance(val, date):
                    val = val.isoformat()
                new_values[field] = val
            self._audit_service.log_change(
                action="update",
                model="Budget",
                record_id=budget.id,
                old_values=old_values,
                new_values=new_values,
                user_id=user.id,
            )

        db.session.commit()
        return budget

    def delete_budget(self, budget_id: int, user: User) -> None:
        """Delete a budget.

        Validates: Requirement 6.7

        Args:
            budget_id: ID of the budget to delete.
            user: The requesting user.

        Raises:
            ValueError: If budget not found or user has no access.
        """
        budget = db.session.get(Budget, budget_id)
        if budget is None:
            raise ValueError("Budget nicht gefunden.")

        # Access check: owner or shared budget
        if budget.user_id != user.id and budget.scope != BudgetScope.shared:
            raise ValueError("Kein Zugriff auf dieses Budget.")

        # Audit log (Req 22.1)
        self._audit_service.log_change(
            action="delete",
            model="Budget",
            record_id=budget.id,
            old_values={
                "name": budget.name,
                "scope": budget.scope.value,
                "amount": str(budget.amount),
                "period": budget.period.value,
            },
            new_values=None,
            user_id=user.id,
        )

        db.session.delete(budget)
        db.session.commit()

    def get_utilisation_with_details(
        self, budget: Budget, user: User
    ) -> dict:
        """Get utilisation details for display in the budget list.

        Returns a dict with utilisation percentage, spent amount,
        remaining amount, and color coding for progress bars.

        Color coding:
        - green (success): < 80%
        - yellow (warning): 80% to <100%
        - red (danger): >= 100%

        Args:
            budget: The budget.
            user: The user.

        Returns:
            Dict with keys: utilisation, spent, remaining, color,
            percentage (capped at 100 for bar width), percentage_raw.
        """
        utilisation = self.calculate_utilisation(budget, user)
        percentage_raw = float(utilisation * 100)
        spent = utilisation * budget.amount
        remaining = budget.amount - spent

        # Color coding: green < 80%, yellow 80-100%, red > 100%
        if percentage_raw >= 100:
            color = "danger"
        elif percentage_raw >= 80:
            color = "warning"
        else:
            color = "success"

        return {
            "utilisation": utilisation,
            "spent": spent,
            "remaining": remaining,
            "color": color,
            "percentage": min(percentage_raw, 100),  # Cap bar width at 100%
            "percentage_raw": percentage_raw,  # Actual percentage (can exceed 100)
        }

    # -------------------------------------------------------------------------
    # Date utilities
    # -------------------------------------------------------------------------

    @staticmethod
    def _next_month(year: int, month: int) -> tuple[int, int]:
        """Return (year, month) for the month following the given month."""
        if month == 12:
            return year + 1, 1
        return year, month + 1

    @staticmethod
    def _prev_month(year: int, month: int) -> tuple[int, int]:
        """Return (year, month) for the month preceding the given month."""
        if month == 1:
            return year - 1, 12
        return year, month - 1
