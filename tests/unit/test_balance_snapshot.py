"""Unit tests for AccountBalanceSnapshot creation.

Tests automatic snapshot creation on transaction operations and manual
balance corrections.

Validates: Requirements 27.1, 27.2, 27.3
"""

import pytest
from datetime import date
from decimal import Decimal

from app.models.account import AccountBalanceSnapshot, SnapshotSource
from app.models.transaction import TransactionType
from app.services.transaction_service import TransactionService
from tests.factories import UserFactory, AccountFactory


@pytest.fixture()
def service():
    """Provide a TransactionService instance."""
    return TransactionService()


@pytest.fixture()
def user(db_session):
    """Create a test user."""
    return UserFactory()


@pytest.fixture()
def spending_account(db_session, user):
    """Create a spending account with 1000 balance."""
    account = AccountFactory(
        owner=user,
        type="spending",
        scope="personal",
        balance=Decimal("1000.00"),
    )
    db_session.flush()
    return account


@pytest.fixture()
def destination_account(db_session, user):
    """Create a destination account for transfers."""
    account = AccountFactory(
        owner=user,
        type="spending",
        scope="personal",
        balance=Decimal("200.00"),
    )
    db_session.flush()
    return account


@pytest.fixture()
def credit_card_account(db_session, user):
    """Create a credit card account with negative balance (debt)."""
    account = AccountFactory(
        owner=user,
        type="credit_card",
        scope="personal",
        balance=Decimal("-500.00"),
    )
    db_session.flush()
    return account


class TestAutomaticSnapshotOnCreate:
    """Tests for automatic snapshot creation when transactions are created (Req 27.1)."""

    def test_income_creates_snapshot(
        self, db_session, service, user, spending_account
    ):
        """Creating an income transaction creates a snapshot for the account."""
        data = {
            "type": "income",
            "amount": Decimal("500.00"),
            "date": date(2024, 3, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }

        service.create_transaction(data, user)

        snapshots = AccountBalanceSnapshot.query.filter_by(
            account_id=spending_account.id
        ).all()
        assert len(snapshots) == 1
        assert snapshots[0].balance == Decimal("1500.00")
        assert snapshots[0].snapshot_date == date(2024, 3, 15)
        assert snapshots[0].source == SnapshotSource.automatic

    def test_expense_creates_snapshot(
        self, db_session, service, user, spending_account
    ):
        """Creating an expense transaction creates a snapshot for the account."""
        data = {
            "type": "expense",
            "amount": Decimal("300.00"),
            "date": date(2024, 3, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }

        service.create_transaction(data, user)

        snapshots = AccountBalanceSnapshot.query.filter_by(
            account_id=spending_account.id
        ).all()
        assert len(snapshots) == 1
        assert snapshots[0].balance == Decimal("700.00")
        assert snapshots[0].source == SnapshotSource.automatic

    def test_transfer_creates_snapshots_for_both_accounts(
        self, db_session, service, user, spending_account, destination_account
    ):
        """Creating a transfer creates snapshots for both source and destination."""
        data = {
            "type": "transfer",
            "amount": Decimal("250.00"),
            "date": date(2024, 3, 15),
            "account_id": spending_account.id,
            "destination_account_id": destination_account.id,
            "scope": "personal",
        }

        service.create_transaction(data, user)

        source_snapshots = AccountBalanceSnapshot.query.filter_by(
            account_id=spending_account.id
        ).all()
        dest_snapshots = AccountBalanceSnapshot.query.filter_by(
            account_id=destination_account.id
        ).all()

        assert len(source_snapshots) == 1
        assert source_snapshots[0].balance == Decimal("750.00")
        assert len(dest_snapshots) == 1
        assert dest_snapshots[0].balance == Decimal("450.00")

    def test_credit_card_payment_creates_snapshots_for_both_accounts(
        self, db_session, service, user, spending_account, credit_card_account
    ):
        """Creating a credit card payment creates snapshots for both accounts."""
        data = {
            "type": "credit_card_payment",
            "amount": Decimal("200.00"),
            "date": date(2024, 3, 15),
            "account_id": spending_account.id,
            "destination_account_id": credit_card_account.id,
            "scope": "personal",
        }

        service.create_transaction(data, user)

        source_snapshots = AccountBalanceSnapshot.query.filter_by(
            account_id=spending_account.id
        ).all()
        dest_snapshots = AccountBalanceSnapshot.query.filter_by(
            account_id=credit_card_account.id
        ).all()

        assert len(source_snapshots) == 1
        assert source_snapshots[0].balance == Decimal("800.00")
        assert len(dest_snapshots) == 1
        assert dest_snapshots[0].balance == Decimal("-300.00")


class TestSnapshotOnDelete:
    """Tests for snapshot creation when transactions are deleted (Req 27.1)."""

    def test_delete_transaction_creates_snapshot(
        self, db_session, service, user, spending_account
    ):
        """Deleting a transaction creates a snapshot reflecting the restored balance."""
        data = {
            "type": "expense",
            "amount": Decimal("300.00"),
            "date": date(2024, 3, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)

        # After create: 1 snapshot with balance=700
        service.delete_transaction(txn.id, user)

        # After delete: 2 snapshots total (create + delete reversal)
        snapshots = AccountBalanceSnapshot.query.filter_by(
            account_id=spending_account.id
        ).order_by(AccountBalanceSnapshot.created_at).all()
        assert len(snapshots) == 2
        assert snapshots[1].balance == Decimal("1000.00")
        assert snapshots[1].source == SnapshotSource.automatic


class TestSnapshotOnUpdate:
    """Tests for snapshot creation when transactions are updated (Req 27.1)."""

    def test_update_transaction_creates_snapshot(
        self, db_session, service, user, spending_account
    ):
        """Updating a transaction creates a snapshot with the new balance."""
        data = {
            "type": "expense",
            "amount": Decimal("300.00"),
            "date": date(2024, 3, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)

        service.update_transaction(txn.id, {"amount": Decimal("500.00")}, user)

        # After update: 2 snapshots (create + update)
        snapshots = AccountBalanceSnapshot.query.filter_by(
            account_id=spending_account.id
        ).order_by(AccountBalanceSnapshot.created_at).all()
        assert len(snapshots) == 2
        # After update: 1000 - 500 = 500
        assert snapshots[1].balance == Decimal("500.00")
        assert snapshots[1].source == SnapshotSource.automatic


class TestChronologicalOrder:
    """Tests for chronological ordering of multiple snapshots on same day (Req 27.2)."""

    def test_multiple_transactions_same_day_have_ordered_snapshots(
        self, db_session, service, user, spending_account
    ):
        """Multiple transactions on the same day produce snapshots with distinct timestamps."""
        txn_date = date(2024, 3, 15)

        # Create three transactions on the same day
        for amount in [Decimal("100.00"), Decimal("200.00"), Decimal("50.00")]:
            data = {
                "type": "expense",
                "amount": amount,
                "date": txn_date,
                "account_id": spending_account.id,
                "scope": "personal",
            }
            service.create_transaction(data, user)

        snapshots = AccountBalanceSnapshot.query.filter_by(
            account_id=spending_account.id
        ).order_by(AccountBalanceSnapshot.created_at).all()

        assert len(snapshots) == 3
        # Verify chronological order: each created_at >= previous
        for i in range(1, len(snapshots)):
            assert snapshots[i].created_at >= snapshots[i - 1].created_at

        # Verify running balances: 1000-100=900, 900-200=700, 700-50=650
        assert snapshots[0].balance == Decimal("900.00")
        assert snapshots[1].balance == Decimal("700.00")
        assert snapshots[2].balance == Decimal("650.00")

        # All on the same snapshot_date
        for s in snapshots:
            assert s.snapshot_date == txn_date


class TestManualBalanceCorrection:
    """Tests for manual balance correction (Req 27.3)."""

    def test_manual_correction_updates_balance_and_creates_snapshot(
        self, db_session, service, user, spending_account
    ):
        """Manual correction updates account balance and creates a manual snapshot."""
        new_balance = Decimal("1234.56")

        snapshot = service.create_manual_balance_correction(
            account_id=spending_account.id,
            new_balance=new_balance,
            user=user,
        )

        assert spending_account.balance == new_balance
        assert snapshot.balance == new_balance
        assert snapshot.source == SnapshotSource.manual
        assert snapshot.account_id == spending_account.id

    def test_manual_correction_snapshot_uses_today_date(
        self, db_session, service, user, spending_account
    ):
        """Manual correction snapshot uses today's date."""
        from datetime import datetime, timezone

        snapshot = service.create_manual_balance_correction(
            account_id=spending_account.id,
            new_balance=Decimal("999.99"),
            user=user,
        )

        today = datetime.now(timezone.utc).date()
        assert snapshot.snapshot_date == today

    def test_manual_correction_nonexistent_account_raises(
        self, db_session, service, user
    ):
        """Manual correction on nonexistent account raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            service.create_manual_balance_correction(
                account_id=99999,
                new_balance=Decimal("100.00"),
                user=user,
            )
