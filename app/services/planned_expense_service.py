"""Planned expense service for Haushaltsbuch.

Implements CRUD operations for planned expenses, resolution via transaction
links, and unresolving when linked transactions are deleted.

Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
"""

from decimal import Decimal
from typing import Optional

from app.extensions import db
from app.models.planned_expense import PlannedExpense, PlannedExpenseScope
from app.models.transaction import TransactionPlannedExpense


class PlannedExpenseService:
    """Service class for planned expense operations.

    Manages the lifecycle of planned expenses including creation, editing,
    resolution via transaction links, and unresolving on transaction deletion.
    """

    def create(
        self,
        user_id: int,
        name: str,
        scope: PlannedExpenseScope,
        amount_exact: Optional[Decimal] = None,
        amount_min: Optional[Decimal] = None,
        amount_max: Optional[Decimal] = None,
        account_id: Optional[int] = None,
        blocking: bool = True,
    ) -> PlannedExpense:
        """Create a new planned expense.

        Validates: Requirement 9.1, 9.6

        Args:
            user_id: The user creating the expense.
            name: Name of the expense (1-100 characters).
            scope: PlannedExpenseScope enum value.
            amount_exact: Exact amount (mutually exclusive with range).
            amount_min: Minimum amount for range.
            amount_max: Maximum amount for range.
            account_id: Optional linked account.
            blocking: Whether this expense blocks available balance.

        Returns:
            The created PlannedExpense instance.

        Raises:
            ValueError: If validation fails (name length, amount_min > amount_max).
        """
        # Validate name length (Req 9.1)
        if not name or len(name.strip()) == 0:
            raise ValueError("Name must not be empty.")
        if len(name) > 100:
            raise ValueError("Name must be at most 100 characters.")

        # Validate range (Req 9.6)
        if amount_min is not None and amount_max is not None:
            if amount_min > amount_max:
                raise ValueError(
                    "amount_min must not be greater than amount_max."
                )

        # Validate amount values are in allowed range
        for amt, label in [
            (amount_exact, "amount_exact"),
            (amount_min, "amount_min"),
            (amount_max, "amount_max"),
        ]:
            if amt is not None:
                if amt < Decimal("0.01") or amt > Decimal("999999999.99"):
                    raise ValueError(
                        f"{label} must be between 0.01 and 999,999,999.99."
                    )

        # Resolve scope if passed as string
        if isinstance(scope, str):
            scope = PlannedExpenseScope(scope)

        expense = PlannedExpense(
            name=name.strip(),
            amount_exact=amount_exact,
            amount_min=amount_min,
            amount_max=amount_max,
            scope=scope,
            account_id=account_id,
            blocking=blocking,
            resolved=False,
            user_id=user_id,
        )

        db.session.add(expense)
        db.session.commit()
        return expense

    # Alias for backward compatibility
    def create_planned_expense(self, user_id, name, scope, **kwargs):
        """Alias for create() — backward compatible interface."""
        return self.create(user_id=user_id, name=name, scope=scope, **kwargs)

    def update(
        self,
        expense: PlannedExpense,
        name: Optional[str] = None,
        amount_exact: Optional[Decimal] = None,
        amount_min: Optional[Decimal] = None,
        amount_max: Optional[Decimal] = None,
        account_id: Optional[int] = None,
        blocking: Optional[bool] = None,
    ) -> PlannedExpense:
        """Edit an existing planned expense.

        Validates: Requirement 9.5, 9.6

        Updates the specified fields and triggers available_balance
        recalculation for affected accounts.

        Args:
            expense: The PlannedExpense instance to update.
            name: New name (if provided).
            amount_exact: New exact amount (if provided, None clears it).
            amount_min: New minimum amount (if provided, None clears it).
            amount_max: New maximum amount (if provided, None clears it).
            account_id: New linked account ID (None to unlink).
            blocking: New blocking flag (if provided).

        Returns:
            The updated PlannedExpense instance.

        Raises:
            ValueError: If validation fails.
        """
        old_account_id = expense.account_id

        # Validate and update name
        if name is not None:
            if not name or len(name.strip()) == 0:
                raise ValueError("Name must not be empty.")
            if len(name) > 100:
                raise ValueError("Name must be at most 100 characters.")
            expense.name = name.strip()

        # Update amounts — assign directly (None means clear)
        expense.amount_exact = amount_exact
        expense.amount_min = amount_min
        expense.amount_max = amount_max

        # Validate amounts in range
        for amt, label in [
            (expense.amount_exact, "amount_exact"),
            (expense.amount_min, "amount_min"),
            (expense.amount_max, "amount_max"),
        ]:
            if amt is not None:
                if amt < Decimal("0.01") or amt > Decimal("999999999.99"):
                    raise ValueError(
                        f"{label} must be between 0.01 and 999,999,999.99."
                    )

        # Validate range after updates (Req 9.6)
        if expense.amount_min is not None and expense.amount_max is not None:
            if expense.amount_min > expense.amount_max:
                raise ValueError(
                    "amount_min must not be greater than amount_max."
                )

        # Update account linkage
        if account_id is not None:
            expense.account_id = account_id
        else:
            expense.account_id = None

        # Update blocking flag
        if blocking is not None:
            expense.blocking = blocking

        db.session.commit()

        # Trigger balance recalculation for affected accounts (Req 9.5)
        self._recalculate_affected_accounts(old_account_id, expense.account_id)

        return expense

    def resolve_via_transaction(
        self,
        expense_id: int,
        transaction_id: int,
        resolved_amount: Decimal,
    ) -> PlannedExpense:
        """Resolve a planned expense by linking it to a transaction.

        Validates: Requirement 9.3

        Sets resolved=True and, for range-based expenses, sets amount_exact
        to the resolved_amount.

        Args:
            expense_id: The planned expense to resolve.
            transaction_id: The transaction that resolves it.
            resolved_amount: The actual amount spent.

        Returns:
            The resolved PlannedExpense.

        Raises:
            ValueError: If expense not found or already resolved.
        """
        expense = db.session.get(PlannedExpense, expense_id)
        if expense is None:
            raise ValueError(f"PlannedExpense with id {expense_id} not found.")

        if expense.resolved:
            raise ValueError("PlannedExpense is already resolved.")

        # Create the link record
        link = TransactionPlannedExpense(
            transaction_id=transaction_id,
            planned_expense_id=expense_id,
            resolved_amount=resolved_amount,
        )
        db.session.add(link)

        # For range-based expenses, set amount_exact to resolved_amount (Req 9.3)
        if expense.is_range:
            expense.amount_exact = resolved_amount
            expense._amount_from_range = True

        expense.resolved = True
        db.session.commit()
        return expense

    def unresolve_on_transaction_delete(self, transaction_id: int) -> list[PlannedExpense]:
        """Unresolve planned expenses linked to a deleted transaction.

        Validates: Requirement 9.4

        Sets resolved=False and clears amount_exact if it was set from
        resolving a range-based expense.

        Args:
            transaction_id: The transaction being deleted.

        Returns:
            List of unresolved PlannedExpense instances.
        """
        links = TransactionPlannedExpense.query.filter_by(
            transaction_id=transaction_id
        ).all()

        unresolved_expenses = []
        for link in links:
            expense = db.session.get(PlannedExpense, link.planned_expense_id)
            if expense is None:
                continue

            expense.resolved = False

            # Clear amount_exact if it was set from resolving a range (Req 9.4)
            if expense._amount_from_range:
                expense.amount_exact = None
                expense._amount_from_range = False

            unresolved_expenses.append(expense)
            db.session.delete(link)

        if unresolved_expenses:
            db.session.commit()

        return unresolved_expenses

    def get_by_id(self, expense_id: int) -> Optional[PlannedExpense]:
        """Get a planned expense by ID.

        Args:
            expense_id: The ID to look up.

        Returns:
            The PlannedExpense or None if not found.
        """
        return db.session.get(PlannedExpense, expense_id)

    # Alias for backward compatibility
    get_planned_expense = get_by_id

    def get_for_user(
        self, user_id: int, include_resolved: bool = True
    ) -> list[PlannedExpense]:
        """Get all planned expenses for a user.

        Args:
            user_id: The user's ID.
            include_resolved: Whether to include resolved expenses.

        Returns:
            List of PlannedExpense instances.
        """
        query = PlannedExpense.query.filter_by(user_id=user_id)
        if not include_resolved:
            query = query.filter_by(resolved=False)
        return query.order_by(PlannedExpense.created_at.desc()).all()

    # Alias for backward compatibility
    def get_user_planned_expenses(self, user_id, include_resolved=False):
        """Alias for get_for_user()."""
        return self.get_for_user(user_id, include_resolved=include_resolved)

    def delete(self, expense: PlannedExpense) -> None:
        """Delete a planned expense.

        Args:
            expense: The PlannedExpense instance to delete.
        """
        account_id = expense.account_id

        # Delete any linked TransactionPlannedExpense records
        TransactionPlannedExpense.query.filter_by(
            planned_expense_id=expense.id
        ).delete()

        db.session.delete(expense)
        db.session.commit()

        # Trigger balance recalculation if account was linked
        if account_id:
            self._recalculate_affected_accounts(account_id, None)

    def delete_planned_expense(self, expense_id: int) -> None:
        """Delete a planned expense by ID.

        Args:
            expense_id: The expense to delete.

        Raises:
            ValueError: If expense not found.
        """
        expense = db.session.get(PlannedExpense, expense_id)
        if expense is None:
            raise ValueError(f"PlannedExpense with id {expense_id} not found.")
        self.delete(expense)

    def _recalculate_affected_accounts(
        self,
        old_account_id: Optional[int],
        new_account_id: Optional[int],
    ) -> None:
        """Trigger balance recalculation for affected accounts.

        Validates: Requirement 9.5
        """
        from app.services.balance_service import BalanceService

        balance_service = BalanceService()

        # Recalculate old account if it changed
        if old_account_id and old_account_id != new_account_id:
            try:
                balance_service.get_available_balance(old_account_id)
            except ValueError:
                pass

        # Recalculate new account
        if new_account_id:
            try:
                balance_service.get_available_balance(new_account_id)
            except ValueError:
                pass
