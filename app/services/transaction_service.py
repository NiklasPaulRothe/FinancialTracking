"""Transaction service for Haushaltsbuch.

Implements create, update, and delete operations with atomic balance updates
using SELECT FOR UPDATE row locking for financial correctness.

Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.9, 3.10, 3.11, 3.12, 4.1-4.5, 24.1-24.6, 27.1, 27.2, 27.3
"""

import calendar
from datetime import date as date_type, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.extensions import db
from app.exceptions import OverdraftLimitExceeded, SplitSumMismatchError
from app.models.account import Account, AccountBalanceSnapshot, AccountScope, AccountType, SnapshotSource
from app.models.transaction import (
    SharedExpense,
    SharedExpenseShare,
    Transaction,
    TransactionPlannedExpense,
    TransactionScope,
    TransactionSplit,
    TransactionType,
)
from app.models.user import User
from app.services.audit_service import AuditService


# Amount validation bounds (Requirement 3.12)
MIN_AMOUNT = Decimal("0.01")
MAX_AMOUNT = Decimal("999999999.99")


class TransactionService:
    """Service class encapsulating transaction business logic with atomic balance updates."""

    def __init__(self) -> None:
        self._audit_service = AuditService()

    def create_transaction(self, data: dict, user: User) -> Transaction:
        """Create a transaction and update balances atomically.

        Validates: Requirements 3.1, 3.2, 3.3, 3.9, 3.10, 3.12

        Args:
            data: Dict with keys: type, amount, date, account_id, scope,
                  and optionally: destination_account_id, category_id,
                  description, recurring_rule_id, posted.
            user: The user creating the transaction.

        Returns:
            The newly created Transaction instance.

        Raises:
            ValueError: If amount is out of range or required fields missing.
            OverdraftLimitExceeded: If transaction would exceed overdraft limit.
        """
        amount = Decimal(str(data["amount"]))
        self._validate_amount(amount)

        txn_type = data["type"]
        if isinstance(txn_type, str):
            txn_type = TransactionType(txn_type)

        transaction = Transaction(
            type=txn_type,
            amount=amount,
            date=data["date"],
            description=data.get("description"),
            scope=data["scope"],
            account_id=data.get("account_id"),
            destination_account_id=data.get("destination_account_id"),
            category_id=data.get("category_id"),
            recurring_rule_id=data.get("recurring_rule_id"),
            posted=data.get("posted", True),
            user_id=user.id,
        )

        db.session.add(transaction)
        db.session.flush()  # Assign ID before balance updates

        # Auto-assign statement_closing_date for credit card transactions (Req 24.2)
        self._assign_statement_closing_date(transaction)

        # Auto-assign due_date for credit card transactions without statement cycle
        self._assign_due_date(transaction)

        # Apply balance impacts
        self._apply_balance_impacts(transaction)

        # Create balance snapshots for affected accounts (Req 27.1)
        self._create_balance_snapshots_for_transaction(transaction)

        # Auto-create SharedExpense for qualifying shared transactions (Req 3.5, 3.6)
        self._maybe_create_shared_expense(transaction, user)

        # Audit log (Req 22.1)
        self._audit_service.log_change(
            action="create",
            model="Transaction",
            record_id=transaction.id,
            old_values=None,
            new_values={
                "type": transaction.type.value,
                "amount": str(transaction.amount),
                "date": transaction.date.isoformat(),
                "account_id": transaction.account_id,
                "scope": transaction.scope.value if transaction.scope else None,
            },
            user_id=user.id,
        )

        db.session.commit()
        return transaction

    def delete_transaction(self, transaction_id: int, user: User) -> None:
        """Reverse balance impacts, unlink planned expenses, and delete transaction.

        Validates: Requirement 3.7

        Args:
            transaction_id: ID of the transaction to delete.
            user: The user requesting deletion.

        Raises:
            ValueError: If transaction not found or user lacks access.
        """
        transaction = self._get_transaction_for_user(transaction_id, user)

        # Reverse balance impacts (opposite of create)
        self._reverse_balance_impacts(transaction)

        # Create balance snapshots for affected accounts after reversal (Req 27.1)
        self._create_balance_snapshots_for_transaction(transaction)

        # Unlink planned expenses: set resolved=False on linked PlannedExpenses
        self._unlink_planned_expenses(transaction)

        # Audit log (Req 22.1)
        self._audit_service.log_change(
            action="delete",
            model="Transaction",
            record_id=transaction.id,
            old_values={
                "type": transaction.type.value,
                "amount": str(transaction.amount),
                "date": transaction.date.isoformat(),
                "account_id": transaction.account_id,
                "scope": transaction.scope.value if transaction.scope else None,
            },
            new_values=None,
            user_id=user.id,
        )

        # Delete the transaction (cascades to splits, shared expenses)
        db.session.delete(transaction)
        db.session.commit()

    def update_transaction(
        self, transaction_id: int, data: dict, user: User
    ) -> Transaction:
        """Reverse old impacts, apply new impacts, update transaction fields.

        Validates: Requirement 3.11

        Args:
            transaction_id: ID of the transaction to update.
            data: Dict with updated fields (type, amount, date, account_id,
                  destination_account_id, category_id, description, scope).
            user: The user requesting the update.

        Returns:
            The updated Transaction instance.

        Raises:
            ValueError: If transaction not found, user lacks access, or amount invalid.
            OverdraftLimitExceeded: If new impacts would exceed overdraft limit.
        """
        transaction = self._get_transaction_for_user(transaction_id, user)

        # Validate new amount if provided
        if "amount" in data:
            new_amount = Decimal(str(data["amount"]))
            self._validate_amount(new_amount)

        # Capture old values for audit log before modification
        old_values = {
            "type": transaction.type.value,
            "amount": str(transaction.amount),
            "date": transaction.date.isoformat(),
            "account_id": transaction.account_id,
            "scope": transaction.scope.value if transaction.scope else None,
        }

        # Step 1: Reverse old balance impacts
        self._reverse_balance_impacts(transaction)

        # Step 2: Update transaction fields
        updatable_fields = {
            "type", "amount", "date", "description", "scope",
            "account_id", "destination_account_id", "category_id",
        }
        for field in updatable_fields:
            if field in data:
                value = data[field]
                if field == "type" and isinstance(value, str):
                    value = TransactionType(value)
                if field == "amount":
                    value = Decimal(str(value))
                setattr(transaction, field, value)

        db.session.flush()

        # Step 3: Apply new balance impacts
        self._apply_balance_impacts(transaction)

        # Create balance snapshots for affected accounts after update (Req 27.1)
        self._create_balance_snapshots_for_transaction(transaction)

        # Audit log (Req 22.1)
        self._audit_service.log_change(
            action="update",
            model="Transaction",
            record_id=transaction.id,
            old_values=old_values,
            new_values={
                "type": transaction.type.value,
                "amount": str(transaction.amount),
                "date": transaction.date.isoformat(),
                "account_id": transaction.account_id,
                "scope": transaction.scope.value if transaction.scope else None,
            },
            user_id=user.id,
        )

        db.session.commit()
        return transaction

    # -------------------------------------------------------------------------
    # Transaction split management
    # -------------------------------------------------------------------------

    # Splits constraints (Requirement 4.1)
    MIN_SPLITS = 2
    MAX_SPLITS = 20

    def set_transaction_splits(
        self, transaction_id: int, splits: list[dict], user: User
    ) -> list[TransactionSplit]:
        """Set splits on a transfer transaction, replacing any existing splits.

        Validates: Requirements 4.1, 4.3, 4.4, 4.5

        Each split dict: {category_id: int, amount: Decimal, description: str|None}

        Validates:
        - Transaction is type transfer
        - 2-20 splits
        - Each amount > 0
        - Sum of amounts == transaction.amount
        - Description max 255 characters (if provided)

        Args:
            transaction_id: ID of the transfer transaction.
            splits: List of split dicts with category_id, amount, optional description.
            user: The user performing the action.

        Returns:
            List of newly created TransactionSplit instances.

        Raises:
            ValueError: If transaction not transfer type, count invalid, or amounts invalid.
            SplitSumMismatchError: If sum of split amounts != transaction amount.
        """
        transaction = self._get_transaction_for_user(transaction_id, user)

        # Only transfer transactions can have splits (Req 4.1)
        if transaction.type != TransactionType.transfer:
            raise ValueError(
                "Splits can only be added to transfer transactions."
            )

        # Validate split count (Req 4.1: 2-20 splits)
        split_count = len(splits)
        if split_count < self.MIN_SPLITS:
            raise ValueError(
                f"At least {self.MIN_SPLITS} splits are required. "
                f"Got: {split_count}"
            )
        if split_count > self.MAX_SPLITS:
            raise ValueError(
                f"At most {self.MAX_SPLITS} splits are allowed. "
                f"Got: {split_count}"
            )

        # Validate individual split amounts and descriptions
        split_sum = Decimal("0")
        for split_data in splits:
            amount = Decimal(str(split_data["amount"]))
            if amount <= 0:
                raise ValueError(
                    "Each split amount must be a positive non-zero value. "
                    f"Got: {amount}"
                )
            description = split_data.get("description")
            if description is not None and len(description) > 255:
                raise ValueError(
                    "Split description must be at most 255 characters. "
                    f"Got: {len(description)}"
                )
            split_sum += amount

        # Validate sum equals transaction total (Req 4.3, 4.4)
        if split_sum != transaction.amount:
            raise SplitSumMismatchError(
                transaction_amount=transaction.amount,
                split_sum=split_sum,
            )

        # Replace existing splits (Req 4.5)
        for existing_split in list(transaction.splits):
            db.session.delete(existing_split)
        db.session.flush()

        # Create new splits
        new_splits = []
        for split_data in splits:
            split = TransactionSplit(
                transaction_id=transaction.id,
                category_id=split_data["category_id"],
                amount=Decimal(str(split_data["amount"])),
                description=split_data.get("description"),
            )
            db.session.add(split)
            new_splits.append(split)

        db.session.commit()
        return new_splits

    # -------------------------------------------------------------------------
    # Balance impact methods
    # -------------------------------------------------------------------------

    def _apply_balance_impacts(self, transaction: Transaction) -> None:
        """Apply balance changes for a transaction (create direction).

        For income: account.balance += amount
        For expense: account.balance -= amount
        For transfer: source.balance -= amount, destination.balance += amount
        For credit_card_payment: source.balance -= amount, destination.balance += amount
        """
        txn_type = transaction.type
        amount = transaction.amount

        if txn_type == TransactionType.income:
            account = self._lock_account(transaction.account_id)
            account.balance += amount

        elif txn_type == TransactionType.expense:
            account = self._lock_account(transaction.account_id)
            self._check_overdraft(account, amount)
            account.balance -= amount

        elif txn_type == TransactionType.transfer:
            source = self._lock_account(transaction.account_id)
            destination = self._lock_account(transaction.destination_account_id)
            self._check_overdraft(source, amount)
            source.balance -= amount
            destination.balance += amount

        elif txn_type == TransactionType.credit_card_payment:
            source = self._lock_account(transaction.account_id)
            destination = self._lock_account(transaction.destination_account_id)
            self._check_overdraft(source, amount)
            source.balance -= amount
            destination.balance += amount

    def _reverse_balance_impacts(self, transaction: Transaction) -> None:
        """Reverse balance changes for a transaction (delete direction).

        For income: account.balance -= amount
        For expense: account.balance += amount
        For transfer: source.balance += amount, destination.balance -= amount
        For credit_card_payment: source.balance += amount, destination.balance -= amount
        """
        txn_type = transaction.type
        amount = transaction.amount

        if txn_type == TransactionType.income:
            account = self._lock_account(transaction.account_id)
            account.balance -= amount

        elif txn_type == TransactionType.expense:
            account = self._lock_account(transaction.account_id)
            account.balance += amount

        elif txn_type == TransactionType.transfer:
            source = self._lock_account(transaction.account_id)
            destination = self._lock_account(transaction.destination_account_id)
            source.balance += amount
            destination.balance -= amount

        elif txn_type == TransactionType.credit_card_payment:
            source = self._lock_account(transaction.account_id)
            destination = self._lock_account(transaction.destination_account_id)
            source.balance += amount
            destination.balance -= amount

    # -------------------------------------------------------------------------
    # Overdraft check
    # -------------------------------------------------------------------------

    def _check_overdraft(self, account: Account, deduction_amount: Decimal) -> None:
        """Check if a deduction would exceed the account's overdraft limit.

        Validates: Requirements 3.9, 3.10

        If max_overdraft is None, no check is performed (Req 3.10).
        If resulting balance < -max_overdraft, raises OverdraftLimitExceeded (Req 3.9).
        """
        if account.max_overdraft is None:
            return

        resulting_balance = account.balance - deduction_amount
        if resulting_balance < -account.max_overdraft:
            raise OverdraftLimitExceeded(
                account_id=account.id,
                current_balance=account.balance,
                transaction_amount=deduction_amount,
                max_overdraft=account.max_overdraft,
            )

    # -------------------------------------------------------------------------
    # Planned expense unlinking
    # -------------------------------------------------------------------------

    def _unlink_planned_expenses(self, transaction: Transaction) -> None:
        """Unlink resolved planned expenses and delete junction records.

        Sets resolved=False on any PlannedExpense linked via TransactionPlannedExpense,
        then deletes the TransactionPlannedExpense records.
        """
        linked_records = TransactionPlannedExpense.query.filter_by(
            transaction_id=transaction.id
        ).all()

        for record in linked_records:
            try:
                from app.models.planned_expense import PlannedExpense

                planned = db.session.get(PlannedExpense, record.planned_expense_id)
                if planned is not None:
                    planned.resolved = False
            except (ImportError, Exception):
                # PlannedExpense model not yet implemented; skip
                pass

            db.session.delete(record)

    # -------------------------------------------------------------------------
    # Shared expense auto-creation
    # -------------------------------------------------------------------------

    # Transaction types that trigger SharedExpense creation (Req 3.5)
    _SHARED_EXPENSE_TYPES = frozenset({
        TransactionType.income,
        TransactionType.expense,
        TransactionType.credit_card_payment,
    })

    def _maybe_create_shared_expense(self, transaction: Transaction, user: User) -> None:
        """Auto-create SharedExpense with 50/50 split for qualifying shared transactions.

        Validates: Requirements 3.5, 3.6

        Creates a SharedExpense record and two SharedExpenseShare records (one per
        household member) when scope is 'shared' and type is income, expense, or
        credit_card_payment. Shared transfers are explicitly excluded (Req 3.6).
        """
        # Resolve scope to enum if passed as string
        scope = transaction.scope
        if isinstance(scope, str):
            scope = TransactionScope(scope)

        if scope != TransactionScope.shared:
            return

        if transaction.type not in self._SHARED_EXPENSE_TYPES:
            return

        # Calculate 50/50 split
        half_amount = transaction.amount / 2

        # Create the SharedExpense record
        shared_expense = SharedExpense(transaction_id=transaction.id)
        db.session.add(shared_expense)
        db.session.flush()  # Assign ID for foreign key references

        # Find the household partner (the other user)
        partner = User.query.filter(User.id != user.id).first()

        # Create share for the creating user
        user_share = SharedExpenseShare(
            shared_expense_id=shared_expense.id,
            user_id=user.id,
            amount=half_amount,
        )
        db.session.add(user_share)

        # Create share for the partner (if exists)
        if partner is not None:
            partner_share = SharedExpenseShare(
                shared_expense_id=shared_expense.id,
                user_id=partner.id,
                amount=half_amount,
            )
            db.session.add(partner_share)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _lock_account(self, account_id: int) -> Account:
        """Lock an account row with SELECT FOR UPDATE and return it.

        Args:
            account_id: The account ID to lock.

        Returns:
            The locked Account instance.

        Raises:
            ValueError: If account not found.
        """
        stmt = select(Account).where(Account.id == account_id).with_for_update()
        result = db.session.execute(stmt)
        account = result.scalar_one_or_none()
        if account is None:
            raise ValueError(f"Account with id {account_id} not found.")
        return account

    def _validate_amount(self, amount: Decimal) -> None:
        """Validate transaction amount is within allowed bounds.

        Validates: Requirement 3.12

        Raises:
            ValueError: If amount is outside [0.01, 999999999.99].
        """
        if amount < MIN_AMOUNT or amount > MAX_AMOUNT:
            raise ValueError(
                f"Transaction amount must be between {MIN_AMOUNT} and "
                f"{MAX_AMOUNT}. Got: {amount}"
            )

    def _get_transaction_for_user(
        self, transaction_id: int, user: User
    ) -> Transaction:
        """Retrieve a transaction ensuring the user has access.

        Args:
            transaction_id: The transaction ID.
            user: The requesting user.

        Returns:
            The Transaction instance.

        Raises:
            ValueError: If transaction not found or user lacks access.
        """
        transaction = db.session.get(Transaction, transaction_id)
        if transaction is None:
            raise ValueError(
                f"Transaction with id {transaction_id} not found."
            )

        if transaction.user_id != user.id:
            raise ValueError(
                f"User {user.username} does not have access to "
                f"transaction {transaction_id}."
            )

        return transaction

    # -------------------------------------------------------------------------
    # Balance snapshot methods (Requirements 27.1, 27.2, 27.3)
    # -------------------------------------------------------------------------

    def _create_balance_snapshots_for_transaction(
        self, transaction: Transaction
    ) -> None:
        """Create AccountBalanceSnapshot(s) for all accounts affected by a transaction.

        Validates: Requirements 27.1, 27.3

        For income/expense: creates one snapshot for the source account.
        For transfer/credit_card_payment: creates snapshots for both source and destination.

        Each snapshot captures the current balance of the account at this moment,
        using the transaction date as the snapshot_date. Multiple snapshots on the
        same day are distinguished by their created_at timestamp (Req 27.2).
        """
        txn_type = transaction.type
        snapshot_date = transaction.date

        if txn_type in (TransactionType.income, TransactionType.expense):
            account = db.session.get(Account, transaction.account_id)
            self._create_balance_snapshot(
                account_id=account.id,
                balance=account.balance,
                snapshot_date=snapshot_date,
                source=SnapshotSource.automatic,
            )
        elif txn_type in (TransactionType.transfer, TransactionType.credit_card_payment):
            source = db.session.get(Account, transaction.account_id)
            destination = db.session.get(Account, transaction.destination_account_id)
            self._create_balance_snapshot(
                account_id=source.id,
                balance=source.balance,
                snapshot_date=snapshot_date,
                source=SnapshotSource.automatic,
            )
            self._create_balance_snapshot(
                account_id=destination.id,
                balance=destination.balance,
                snapshot_date=snapshot_date,
                source=SnapshotSource.automatic,
            )

    def _create_balance_snapshot(
        self,
        account_id: int,
        balance: Decimal,
        snapshot_date: date_type,
        source: SnapshotSource,
    ) -> AccountBalanceSnapshot:
        """Create a single AccountBalanceSnapshot record.

        Args:
            account_id: The account to snapshot.
            balance: The balance value to record.
            snapshot_date: The date for the snapshot.
            source: Whether this is automatic or manual.

        Returns:
            The newly created AccountBalanceSnapshot instance.
        """
        snapshot = AccountBalanceSnapshot(
            account_id=account_id,
            balance=balance,
            snapshot_date=snapshot_date,
            source=source,
            created_at=datetime.now(timezone.utc),
        )
        db.session.add(snapshot)
        return snapshot

    def create_manual_balance_correction(
        self, account_id: int, new_balance: Decimal, user: User
    ) -> AccountBalanceSnapshot:
        """Apply a manual balance correction to an account.

        Validates: Requirement 27.2

        Updates the account's balance to the provided value and creates
        an AccountBalanceSnapshot with source='manual' and today's date.

        Args:
            account_id: The account to correct.
            new_balance: The corrected balance value.
            user: The user performing the correction.

        Returns:
            The created AccountBalanceSnapshot with source='manual'.

        Raises:
            ValueError: If account not found.
        """
        account = self._lock_account(account_id)
        old_balance = account.balance
        account.balance = new_balance

        today = datetime.now(timezone.utc).date()
        snapshot = self._create_balance_snapshot(
            account_id=account.id,
            balance=new_balance,
            snapshot_date=today,
            source=SnapshotSource.manual,
        )

        # Audit log (Req 22.1)
        self._audit_service.log_change(
            action="update",
            model="Account",
            record_id=account.id,
            old_values={"balance": str(old_balance)},
            new_values={"balance": str(new_balance)},
            user_id=user.id,
        )

        db.session.commit()
        return snapshot

    # -------------------------------------------------------------------------
    # Credit Card Statement Period Handling
    # -------------------------------------------------------------------------

    def assign_statement_closing_date(
        self, transaction_date: date_type, closing_day: int
    ) -> date_type:
        """Calculate the statement closing date for a credit card transaction.

        Validates: Requirement 24.2

        Logic:
        - Determine effective closing day: min(closing_day, last day of month).
        - If transaction day <= effective closing day: statement belongs to
          current month (closing date = year/month/effective_closing_day).
        - Otherwise: statement belongs to next month (closing date = next
          month's effective closing day, handling year rollover).

        Args:
            transaction_date: The date of the transaction.
            closing_day: The account's statement_closing_day (1-28).

        Returns:
            The computed statement_closing_date.
        """
        year = transaction_date.year
        month = transaction_date.month
        day = transaction_date.day

        # Effective closing day is min(closing_day, last day of current month)
        last_day_of_month = calendar.monthrange(year, month)[1]
        effective_closing_day = min(closing_day, last_day_of_month)

        if day <= effective_closing_day:
            # Transaction belongs to current month's statement period
            return date_type(year, month, effective_closing_day)
        else:
            # Transaction belongs to next month's statement period
            if month == 12:
                next_year = year + 1
                next_month = 1
            else:
                next_year = year
                next_month = month + 1
            next_last_day = calendar.monthrange(next_year, next_month)[1]
            next_effective_closing_day = min(closing_day, next_last_day)
            return date_type(next_year, next_month, next_effective_closing_day)

    def _assign_statement_closing_date(self, transaction: Transaction) -> None:
        """Auto-assign statement_closing_date on credit card transactions.

        Validates: Requirement 24.2

        Only applies if the transaction's account is of type credit_card
        and the account has a statement_closing_day configured.
        """
        if transaction.account_id is None:
            return

        account = db.session.get(Account, transaction.account_id)
        if account is None:
            return

        if account.type != AccountType.credit_card:
            return

        if account.statement_closing_day is None:
            return

        transaction.statement_closing_date = self.assign_statement_closing_date(
            transaction.date, account.statement_closing_day
        )

    def _assign_due_date(self, transaction: Transaction) -> None:
        """Auto-assign due_date for credit card transactions without statement cycle.

        If the transaction is on a credit card that has no statement_closing_day,
        set due_date to 30 days after the transaction date.
        """
        from datetime import timedelta

        if transaction.account_id is None:
            return

        account = db.session.get(Account, transaction.account_id)
        if account is None:
            return

        if account.type != AccountType.credit_card:
            return

        # Only set due_date if no statement cycle is configured
        if account.statement_closing_day is not None:
            return

        # Default: due 30 days after transaction
        transaction.due_date = transaction.date + timedelta(days=30)
        transaction.paid = False

    def mark_as_posted(self, transaction_id: int, user: User) -> Transaction:
        """Mark a pending credit card transaction as posted.

        Validates: Requirement 24.4

        Sets posted=True on the transaction. The transaction is then included
        in the statement balance for its assigned period.

        Args:
            transaction_id: ID of the transaction to mark as posted.
            user: The user performing the action.

        Returns:
            The updated Transaction instance.

        Raises:
            ValueError: If transaction not found, user lacks access,
                        or transaction is already posted.
        """
        transaction = self._get_transaction_for_user(transaction_id, user)

        if transaction.posted:
            raise ValueError("Transaction is already posted.")

        transaction.posted = True
        db.session.commit()
        return transaction

    def convert_cc_to_mini_credit(
        self,
        transaction_id: int,
        converted_amount: Decimal,
        user: User,
    ):
        """Convert a credit card transaction to a mini-credit.

        Validates: Requirements 24.5, 24.6

        Creates a Credit record linked to the original transaction with
        converted_from_credit_card_payment=True, reduces the credit card
        balance (debt) by the converted amount, and sets scope matching
        the card's scope.

        Args:
            transaction_id: ID of the credit card transaction to convert.
            converted_amount: Amount to convert (0.01 to transaction amount).
            user: The user performing the conversion.

        Returns:
            The newly created Credit instance.

        Raises:
            ValueError: If transaction not found, not a credit card transaction,
                        or converted_amount exceeds transaction amount.
        """
        from app.models.credit import Credit, CreditScope, CreditStatus

        transaction = self._get_transaction_for_user(transaction_id, user)

        # Validate transaction is on a credit card account
        account = db.session.get(Account, transaction.account_id)
        if account is None or account.type != AccountType.credit_card:
            raise ValueError(
                "Only transactions on credit card accounts can be converted to mini-credits."
            )

        # Validate converted amount
        converted_amount = Decimal(str(converted_amount))
        if converted_amount < Decimal("0.01"):
            raise ValueError("Converted amount must be at least 0.01.")
        if converted_amount > transaction.amount:
            raise ValueError(
                "Converted amount must not exceed the transaction amount."
            )

        # Map account scope to credit scope
        scope = (
            CreditScope.shared
            if account.scope == AccountScope.shared
            else CreditScope.personal
        )

        # Create the Credit record
        credit = Credit(
            name=f"CC Mini-Credit - {transaction.date.isoformat()}",
            principal=converted_amount,
            remaining_balance=converted_amount,
            accrued_interest=Decimal("0.000000"),
            effective_yearly_rate=Decimal("0.000000"),
            disbursement_date=transaction.date,
            interest_capitalization_day=1,
            status=CreditStatus.active,
            scope=scope,
            account_id=transaction.account_id,
            converted_from_credit_card_payment=True,
            linked_transaction_id=transaction.id,
            user_id=user.id,
        )
        db.session.add(credit)

        # Reduce the credit card balance (debt) by the converted amount
        # Balance is negative, so adding makes it less negative
        account.balance = account.balance + converted_amount

        db.session.commit()
        return credit

    def get_statement_balance(
        self, account_id: int, statement_closing_date: date_type
    ) -> Decimal:
        """Calculate statement balance for a credit card account for a given period.

        Validates: Requirements 24.3, 24.4

        Only includes transactions where posted=True and
        statement_closing_date matches the given date.

        Args:
            account_id: The credit card account ID.
            statement_closing_date: The statement period closing date.

        Returns:
            The sum of amounts for posted transactions in the period.
        """
        result = (
            db.session.query(db.func.coalesce(db.func.sum(Transaction.amount), 0))
            .filter(
                Transaction.account_id == account_id,
                Transaction.statement_closing_date == statement_closing_date,
                Transaction.posted == True,  # noqa: E712
            )
            .scalar()
        )
        return Decimal(str(result))
