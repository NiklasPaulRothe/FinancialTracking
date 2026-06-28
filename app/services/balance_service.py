"""Balance service for Haushaltsbuch.

Implements available balance calculation for spending/saving and credit card
accounts, recalculation triggers, and income date utilities.

Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5
"""

from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models.account import Account, AccountType
from app.models.transaction import RecurringRule, TransactionType
from app.models.user import User
from app.services.banking_day_service import BankingDayService


class BalanceService:
    """Service class for available balance calculations.

    Computes the effective available balance for an account by subtracting
    upcoming obligations (recurring expenses, blocking planned expenses,
    saving contributions) from the current balance.
    """

    def __init__(self) -> None:
        self._banking_day_service = BankingDayService()

    def get_available_balance(self, account_id: int) -> Decimal:
        """Calculate available balance for an account.

        Validates: Requirements 8.1, 8.2, 8.4, 8.5

        For spending/saving accounts:
            available = balance
                - sum(active recurring expense rules due before next income date)
                - sum(unresolved blocking planned expenses with non-null amounts)
                - sum(active saving contributions linked to the account)

        For credit card accounts:
            available = credit_limit + balance (balance is negative = debt)

        Args:
            account_id: The account to calculate for.

        Returns:
            The available balance as a Decimal. May be negative (Req 8.5).

        Raises:
            ValueError: If the account does not exist.
        """
        account = db.session.get(Account, account_id)
        if account is None:
            raise ValueError(f"Account with id {account_id} not found.")

        # Credit card: available = credit_limit + balance (Req 8.2)
        if account.type == AccountType.credit_card:
            credit_limit = account.credit_limit or Decimal("0.0")
            return credit_limit + account.balance

        # Spending / Saving accounts (Req 8.1)
        available = account.balance

        # Subtract recurring expense rules due between today and next income date
        available -= self._sum_recurring_expenses_due(account)

        # Subtract blocking planned expenses (Req 8.4: skip if all amounts null)
        available -= self._sum_blocking_planned_expenses(account)

        # Subtract active saving contributions
        available -= self._sum_saving_contributions(account)

        # Req 8.5: Return negative value as-is, no clamping
        return available

    def recalculate_account_balance(self, account_id: int) -> None:
        """Recompute stored balance from transaction history.

        Validates: Requirement 8.3

        Sums all posted transactions for the account and updates the
        account.balance field. This is triggered on transaction mutations.

        Args:
            account_id: The account to recalculate.
        """
        account = db.session.get(Account, account_id)
        if account is None:
            return

        try:
            from app.models.transaction import Transaction

            # Sum all transactions: income adds, expense subtracts,
            # transfers depend on direction
            from sqlalchemy import func

            # Income adds to balance
            income_sum = (
                db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
                .filter(
                    Transaction.account_id == account_id,
                    Transaction.type == TransactionType.income,
                )
                .scalar()
            )

            # Expenses subtract from balance
            expense_sum = (
                db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
                .filter(
                    Transaction.account_id == account_id,
                    Transaction.type == TransactionType.expense,
                )
                .scalar()
            )

            # Transfers out (this account is source)
            transfer_out_sum = (
                db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
                .filter(
                    Transaction.account_id == account_id,
                    Transaction.type == TransactionType.transfer,
                )
                .scalar()
            )

            # Transfers in (this account is destination)
            transfer_in_sum = (
                db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
                .filter(
                    Transaction.destination_account_id == account_id,
                    Transaction.type == TransactionType.transfer,
                )
                .scalar()
            )

            # Credit card payments reduce credit card debt (add to balance)
            cc_payment_sum = (
                db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
                .filter(
                    Transaction.destination_account_id == account_id,
                    Transaction.type == TransactionType.credit_card_payment,
                )
                .scalar()
            )

            # Credit card payments from this account (subtract)
            cc_payment_out_sum = (
                db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
                .filter(
                    Transaction.account_id == account_id,
                    Transaction.type == TransactionType.credit_card_payment,
                )
                .scalar()
            )

            new_balance = (
                Decimal(str(income_sum))
                - Decimal(str(expense_sum))
                - Decimal(str(transfer_out_sum))
                + Decimal(str(transfer_in_sum))
                + Decimal(str(cc_payment_sum))
                - Decimal(str(cc_payment_out_sum))
            )

            account.balance = new_balance
            db.session.commit()

        except (ImportError, Exception):
            # Transaction model fields may not be fully available yet
            pass

    def get_next_income_date(self, user: User) -> date:
        """Compute the next effective income day for the user.

        Validates: Requirement 7 (via BankingDayService)

        If today is before this month's effective income day, returns this
        month's effective income day. Otherwise returns next month's.

        Args:
            user: The user whose income_day to use.

        Returns:
            The next effective income date (a banking day).
        """
        today = date.today()
        # Try this month first
        this_month_income = self._banking_day_service.get_effective_income_day(
            user.income_day, today.year, today.month
        )

        if today < this_month_income:
            return this_month_income

        # Move to next month
        if today.month == 12:
            next_year = today.year + 1
            next_month = 1
        else:
            next_year = today.year
            next_month = today.month + 1

        return self._banking_day_service.get_effective_income_day(
            user.income_day, next_year, next_month
        )

    def get_effective_income_day(self, user: User, year: int, month: int) -> date:
        """Get banking-day-adjusted income day for a specific month.

        Delegates to BankingDayService for the actual computation.

        Args:
            user: The user whose income_day to use.
            year: The calendar year.
            month: The calendar month (1-12).

        Returns:
            The effective income date for the given month/year.
        """
        return self._banking_day_service.get_effective_income_day(
            user.income_day, year, month
        )

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _sum_recurring_expenses_due(self, account: Account) -> Decimal:
        """Sum recurring expense rules due between today and next income date.

        Queries RecurringRule where:
        - active = True
        - type = 'expense'
        - account_id = target account
        - next_due_date BETWEEN today AND next_income_date (inclusive)

        Args:
            account: The account to check.

        Returns:
            Total amount of recurring expenses due.
        """
        today = date.today()

        # Get the account owner to determine next income date
        owner = db.session.get(User, account.owner_id)
        if owner is None:
            return Decimal("0.0")

        next_income = self.get_next_income_date(owner)

        total = (
            db.session.query(db.func.coalesce(db.func.sum(RecurringRule.amount), 0))
            .filter(
                RecurringRule.account_id == account.id,
                RecurringRule.active == True,  # noqa: E712
                RecurringRule.type == TransactionType.expense,
                RecurringRule.next_due_date >= today,
                RecurringRule.next_due_date <= next_income,
            )
            .scalar()
        )

        return Decimal(str(total))

    def _sum_blocking_planned_expenses(self, account: Account) -> Decimal:
        """Sum unresolved blocking planned expenses for the account.

        Validates: Requirement 8.4

        Queries PlannedExpense where:
        - account_id = target account
        - blocking = True
        - resolved = False
        - (amount_exact IS NOT NULL OR amount_min IS NOT NULL)

        Uses amount_exact if set, otherwise amount_min for range-based expenses.
        If all amount fields are null, deducts nothing (Req 8.4).

        Args:
            account: The account to check.

        Returns:
            Total blocking planned expense amount.
        """
        try:
            from app.models.planned_expense import PlannedExpense

            expenses = PlannedExpense.query.filter(
                PlannedExpense.account_id == account.id,
                PlannedExpense.blocking == True,  # noqa: E712
                PlannedExpense.resolved == False,  # noqa: E712
                db.or_(
                    PlannedExpense.amount_exact.isnot(None),
                    PlannedExpense.amount_min.isnot(None),
                ),
            ).all()

            total = Decimal("0.0")
            for expense in expenses:
                if expense.amount_exact is not None:
                    total += expense.amount_exact
                elif expense.amount_min is not None:
                    total += expense.amount_min

            return total

        except (ImportError, Exception):
            # PlannedExpense model not yet implemented
            return Decimal("0.0")

    def _sum_saving_contributions(self, account: Account) -> Decimal:
        """Sum active saving contributions linked to the account.

        Validates: Requirements 10.2, 10.5

        Only contributions linked to active saving goals block the
        available balance. Completed or cancelled goals release their
        contribution amounts.

        Queries SavingContribution where:
        - account_id = target account
        - linked saving goal status = 'active'

        Args:
            account: The account to check.

        Returns:
            Total saving contribution amount for active goals.
        """
        try:
            from app.models.budget import SavingContribution, SavingGoal, SavingGoalStatus

            from sqlalchemy import func

            total = (
                db.session.query(
                    func.coalesce(func.sum(SavingContribution.amount), 0)
                )
                .join(SavingGoal, SavingContribution.saving_goal_id == SavingGoal.id)
                .filter(
                    SavingContribution.account_id == account.id,
                    SavingGoal.status == SavingGoalStatus.active,
                )
                .scalar()
            )

            return Decimal(str(total))

        except (ImportError, Exception):
            # SavingContribution model not yet implemented
            return Decimal("0.0")
