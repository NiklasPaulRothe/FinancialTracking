"""Recurring rule processing service for Haushaltsbuch.

Implements due-rule detection, catch-up processing, date advancement,
overdraft skip logic, duplicate prevention, and split copying for
transfer rules.

Validates: Requirements 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import NamedTuple

from dateutil.relativedelta import relativedelta

from app.extensions import db
from app.exceptions import OverdraftLimitExceeded
from app.models.transaction import (
    RecurringFrequency,
    RecurringRule,
    RecurringRuleSplit,
    Transaction,
    TransactionScope,
    TransactionSplit,
    TransactionType,
)
from app.models.user import User
from app.services.transaction_service import TransactionService
from app.services.audit_service import AuditService


class RecurringNotification(NamedTuple):
    """A notification generated during recurring rule processing."""

    rule_id: int
    rule_name: str
    notification_type: str  # "recurring_rule_posted" or "overdraft_limit_exceeded"
    due_date: date
    message: str


class RecurringService:
    """Service for processing recurring rules and generating transactions.

    Validates: Requirements 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8
    """

    def __init__(self) -> None:
        self.transaction_service = TransactionService()
        self._audit_service = AuditService()

    def process_due_rules(
        self, user: User, today: date | None = None
    ) -> tuple[list[Transaction], list[RecurringNotification]]:
        """Process all due recurring rules for a user.

        Validates: Requirements 5.2, 5.4, 5.5, 5.6, 5.8

        Finds all active rules with next_due_date <= today and generates
        transactions for each missed due date in chronological order.
        Processes ALL missed executions without a catch-up limit (Req 5.8).

        Args:
            user: The user whose rules should be processed.
            today: Override for current date (for testing). Defaults to date.today().

        Returns:
            A tuple of (generated_transactions, notifications).
        """
        if today is None:
            today = date.today()

        rules = RecurringRule.query.filter(
            RecurringRule.user_id == user.id,
            RecurringRule.active == True,  # noqa: E712
            RecurringRule.next_due_date <= today,
        ).order_by(RecurringRule.next_due_date.asc()).all()

        generated: list[Transaction] = []
        notifications: list[RecurringNotification] = []

        for rule in rules:
            # Process all missed due dates in chronological order (Req 5.2, 5.8)
            while rule.next_due_date <= today:
                current_due_date = rule.next_due_date

                # Duplicate prevention: check if transaction already exists (Req 5.6)
                if self._transaction_exists_for_date(rule, current_due_date):
                    self.advance_next_due_date(rule)
                    continue

                # Try to create the transaction
                try:
                    txn = self._create_transaction_from_rule(rule, current_due_date, user)
                    generated.append(txn)

                    # Copy splits for transfer rules (Req 5.7)
                    if rule.type == TransactionType.transfer and rule.splits:
                        self._copy_splits_to_transaction(rule, txn)

                    # Generate posted notification (Req 5.4)
                    notifications.append(
                        RecurringNotification(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            notification_type="recurring_rule_posted",
                            due_date=current_due_date,
                            message=(
                                f"Recurring rule '{rule.name}' posted transaction "
                                f"of {rule.amount} on {current_due_date}."
                            ),
                        )
                    )

                except OverdraftLimitExceeded:
                    # Skip posting, still advance date (Req 5.5)
                    notifications.append(
                        RecurringNotification(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            notification_type="overdraft_limit_exceeded",
                            due_date=current_due_date,
                            message=(
                                f"Recurring rule '{rule.name}' skipped on "
                                f"{current_due_date}: would exceed overdraft limit."
                            ),
                        )
                    )

                # Always advance the due date (Req 5.3, 5.5)
                self.advance_next_due_date(rule)

        db.session.commit()
        return generated, notifications

    def advance_next_due_date(self, rule: RecurringRule) -> date:
        """Calculate and set the next occurrence date for a recurring rule.

        Validates: Requirement 5.3

        Advances next_due_date by the configured interval in the unit
        defined by frequency:
        - daily: + (interval) days
        - weekly: + (interval * 7) days
        - monthly: + (interval) months (using relativedelta)
        - quarterly: + (interval * 3) months
        - yearly: + (interval) years

        Args:
            rule: The recurring rule to advance.

        Returns:
            The new next_due_date value.
        """
        current = rule.next_due_date
        interval = rule.interval
        frequency = rule.frequency

        if frequency == RecurringFrequency.daily:
            new_date = current + timedelta(days=interval)
        elif frequency == RecurringFrequency.weekly:
            new_date = current + timedelta(days=interval * 7)
        elif frequency == RecurringFrequency.monthly:
            new_date = current + relativedelta(months=interval)
        elif frequency == RecurringFrequency.quarterly:
            new_date = current + relativedelta(months=interval * 3)
        elif frequency == RecurringFrequency.yearly:
            new_date = current + relativedelta(years=interval)
        else:
            raise ValueError(f"Unknown frequency: {frequency}")

        rule.next_due_date = new_date
        return new_date

    def _transaction_exists_for_date(self, rule: RecurringRule, due_date: date) -> bool:
        """Check if a transaction linked to this rule already exists for the given date.

        Validates: Requirement 5.6

        Args:
            rule: The recurring rule to check.
            due_date: The date to check for duplicates.

        Returns:
            True if a transaction already exists for this rule and date.
        """
        existing = Transaction.query.filter(
            Transaction.recurring_rule_id == rule.id,
            Transaction.date == due_date,
        ).first()
        return existing is not None

    def _create_transaction_from_rule(
        self, rule: RecurringRule, due_date: date, user: User
    ) -> Transaction:
        """Create a Transaction from a RecurringRule for a specific due date.

        Validates: Requirement 5.2

        Uses TransactionService.create_transaction to ensure all balance
        updates, overdraft checks, and snapshot creation happen atomically.

        Args:
            rule: The recurring rule to generate a transaction from.
            due_date: The date to use as the transaction date (original due date).
            user: The user owning the transaction.

        Returns:
            The newly created Transaction instance.

        Raises:
            OverdraftLimitExceeded: If the transaction would exceed overdraft.
        """
        data = {
            "type": rule.type,
            "amount": rule.amount,
            "date": due_date,
            "account_id": rule.account_id,
            "scope": rule.scope,
            "category_id": rule.category_id,
            "recurring_rule_id": rule.id,
            "description": f"Auto: {rule.name}",
            "posted": True,
        }

        # Include destination account for transfers
        if rule.type == TransactionType.transfer and rule.destination_account_id:
            data["destination_account_id"] = rule.destination_account_id

        # Use the transaction service, but avoid the commit since
        # we batch-commit at the end of process_due_rules
        return self._create_transaction_no_commit(data, user)

    def _create_transaction_no_commit(self, data: dict, user: User) -> Transaction:
        """Create a transaction without committing (deferred to process_due_rules).

        Replicates TransactionService.create_transaction logic but skips
        the final commit to allow batch processing.
        """
        amount = Decimal(str(data["amount"]))

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
        db.session.flush()

        # Apply balance impacts (this may raise OverdraftLimitExceeded)
        self.transaction_service._apply_balance_impacts(transaction)

        # Audit log (Req 22.2 - system-generated recurring rule posting)
        self._audit_service.log_change(
            action="create",
            model="Transaction",
            record_id=transaction.id,
            old_values=None,
            new_values={
                "type": transaction.type.value,
                "amount": str(transaction.amount),
                "date": transaction.date.isoformat(),
                "recurring_rule_id": transaction.recurring_rule_id,
            },
            user_id=None,
        )

        return transaction

    def _copy_splits_to_transaction(
        self, rule: RecurringRule, transaction: Transaction
    ) -> None:
        """Copy RecurringRuleSplit records to TransactionSplit records.

        Validates: Requirement 5.7

        Args:
            rule: The recurring rule with split templates.
            transaction: The generated transaction to attach splits to.
        """
        for rule_split in rule.splits:
            txn_split = TransactionSplit(
                transaction_id=transaction.id,
                category_id=rule_split.category_id,
                amount=rule_split.amount,
                description=rule_split.description,
            )
            db.session.add(txn_split)
