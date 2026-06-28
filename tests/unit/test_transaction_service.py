"""Unit tests for TransactionService.

Tests create, update, and delete operations with atomic balance updates,
overdraft checking, and planned expense unlinking.

Validates: Requirements 3.1, 3.2, 3.3, 3.7, 3.9, 3.10, 3.11, 3.12
"""

import pytest
from datetime import date
from decimal import Decimal

from app.exceptions import OverdraftLimitExceeded
from app.models.account import Account, AccountType, AccountScope
from app.models.transaction import Transaction, TransactionType, TransactionScope
from app.models.user import User
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
def spending_account_with_overdraft(db_session, user):
    """Create a spending account with overdraft limit."""
    account = AccountFactory(
        owner=user,
        type="spending",
        scope="personal",
        balance=Decimal("100.00"),
        max_overdraft=Decimal("200.00"),
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


class TestCreateTransaction:
    """Tests for TransactionService.create_transaction."""

    def test_create_income_adds_to_balance(
        self, db_session, service, user, spending_account
    ):
        """Income transaction increases account balance (Req 3.1)."""
        data = {
            "type": "income",
            "amount": Decimal("500.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }

        txn = service.create_transaction(data, user)

        assert txn.type == TransactionType.income
        assert txn.amount == Decimal("500.00")
        assert spending_account.balance == Decimal("1500.00")

    def test_create_expense_subtracts_from_balance(
        self, db_session, service, user, spending_account
    ):
        """Expense transaction decreases account balance (Req 3.1)."""
        data = {
            "type": "expense",
            "amount": Decimal("300.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }

        txn = service.create_transaction(data, user)

        assert txn.type == TransactionType.expense
        assert spending_account.balance == Decimal("700.00")

    def test_create_transfer_atomic_balance_update(
        self, db_session, service, user, spending_account, destination_account
    ):
        """Transfer deducts from source and adds to destination atomically (Req 3.2)."""
        data = {
            "type": "transfer",
            "amount": Decimal("250.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "destination_account_id": destination_account.id,
            "scope": "personal",
        }

        txn = service.create_transaction(data, user)

        assert txn.type == TransactionType.transfer
        assert spending_account.balance == Decimal("750.00")
        assert destination_account.balance == Decimal("450.00")

    def test_create_credit_card_payment(
        self, db_session, service, user, spending_account, credit_card_account
    ):
        """Credit card payment deducts from spending and reduces CC debt (Req 3.3)."""
        data = {
            "type": "credit_card_payment",
            "amount": Decimal("200.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "destination_account_id": credit_card_account.id,
            "scope": "personal",
        }

        txn = service.create_transaction(data, user)

        assert txn.type == TransactionType.credit_card_payment
        assert spending_account.balance == Decimal("800.00")
        # CC balance goes from -500 to -300 (debt reduced)
        assert credit_card_account.balance == Decimal("-300.00")

    def test_create_transaction_with_description(
        self, db_session, service, user, spending_account
    ):
        """Transaction preserves optional description."""
        data = {
            "type": "expense",
            "amount": Decimal("50.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "scope": "personal",
            "description": "Groceries",
        }

        txn = service.create_transaction(data, user)

        assert txn.description == "Groceries"

    def test_create_transaction_assigns_user(
        self, db_session, service, user, spending_account
    ):
        """Transaction is linked to the creating user."""
        data = {
            "type": "income",
            "amount": Decimal("100.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }

        txn = service.create_transaction(data, user)

        assert txn.user_id == user.id


class TestOverdraftCheck:
    """Tests for overdraft limit enforcement."""

    def test_overdraft_rejected_when_limit_exceeded(
        self, db_session, service, user, spending_account_with_overdraft
    ):
        """Transaction exceeding overdraft limit is rejected (Req 3.9).

        Account balance=100, max_overdraft=200.
        Expense of 400 would result in -300, which is < -200.
        """
        data = {
            "type": "expense",
            "amount": Decimal("400.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account_with_overdraft.id,
            "scope": "personal",
        }

        with pytest.raises(OverdraftLimitExceeded) as exc_info:
            service.create_transaction(data, user)

        assert exc_info.value.account_id == spending_account_with_overdraft.id
        assert exc_info.value.max_overdraft == Decimal("200.00")

    def test_overdraft_allowed_within_limit(
        self, db_session, service, user, spending_account_with_overdraft
    ):
        """Transaction within overdraft limit succeeds (Req 3.9).

        Account balance=100, max_overdraft=200.
        Expense of 250 would result in -150, which is >= -200.
        """
        data = {
            "type": "expense",
            "amount": Decimal("250.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account_with_overdraft.id,
            "scope": "personal",
        }

        txn = service.create_transaction(data, user)

        assert spending_account_with_overdraft.balance == Decimal("-150.00")

    def test_overdraft_at_exact_limit(
        self, db_session, service, user, spending_account_with_overdraft
    ):
        """Transaction exactly at overdraft limit succeeds (Req 3.9).

        Account balance=100, max_overdraft=200.
        Expense of 300 would result in -200, which is == -200 (allowed).
        """
        data = {
            "type": "expense",
            "amount": Decimal("300.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account_with_overdraft.id,
            "scope": "personal",
        }

        txn = service.create_transaction(data, user)

        assert spending_account_with_overdraft.balance == Decimal("-200.00")

    def test_no_overdraft_check_when_max_overdraft_is_none(
        self, db_session, service, user, spending_account
    ):
        """No overdraft check when max_overdraft is None (Req 3.10).

        Account balance=1000, no max_overdraft.
        Expense of 5000 would result in -4000, but is allowed.
        """
        data = {
            "type": "expense",
            "amount": Decimal("5000.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }

        txn = service.create_transaction(data, user)

        assert spending_account.balance == Decimal("-4000.00")

    def test_overdraft_check_on_transfer_source(
        self, db_session, service, user, spending_account_with_overdraft,
        destination_account
    ):
        """Overdraft check applies to source account on transfers (Req 3.9)."""
        data = {
            "type": "transfer",
            "amount": Decimal("400.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account_with_overdraft.id,
            "destination_account_id": destination_account.id,
            "scope": "personal",
        }

        with pytest.raises(OverdraftLimitExceeded):
            service.create_transaction(data, user)


class TestAmountValidation:
    """Tests for transaction amount validation."""

    def test_amount_below_minimum_rejected(
        self, db_session, service, user, spending_account
    ):
        """Amount below 0.01 is rejected (Req 3.12)."""
        data = {
            "type": "income",
            "amount": Decimal("0.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }

        with pytest.raises(ValueError, match="between"):
            service.create_transaction(data, user)

    def test_amount_above_maximum_rejected(
        self, db_session, service, user, spending_account
    ):
        """Amount above 999,999,999.99 is rejected (Req 3.12)."""
        data = {
            "type": "income",
            "amount": Decimal("1000000000.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }

        with pytest.raises(ValueError, match="between"):
            service.create_transaction(data, user)

    def test_minimum_amount_accepted(
        self, db_session, service, user, spending_account
    ):
        """Amount at exactly 0.01 is accepted (Req 3.12)."""
        data = {
            "type": "income",
            "amount": Decimal("0.01"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }

        txn = service.create_transaction(data, user)
        assert txn.amount == Decimal("0.01")

    def test_maximum_amount_accepted(
        self, db_session, service, user, spending_account
    ):
        """Amount at exactly 999,999,999.99 is accepted (Req 3.12)."""
        data = {
            "type": "income",
            "amount": Decimal("999999999.99"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }

        txn = service.create_transaction(data, user)
        assert txn.amount == Decimal("999999999.99")


class TestDeleteTransaction:
    """Tests for TransactionService.delete_transaction."""

    def test_delete_income_reverses_balance(
        self, db_session, service, user, spending_account
    ):
        """Deleting income subtracts from account balance (Req 3.7)."""
        data = {
            "type": "income",
            "amount": Decimal("500.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)
        assert spending_account.balance == Decimal("1500.00")

        service.delete_transaction(txn.id, user)

        assert spending_account.balance == Decimal("1000.00")

    def test_delete_expense_reverses_balance(
        self, db_session, service, user, spending_account
    ):
        """Deleting expense adds back to account balance (Req 3.7)."""
        data = {
            "type": "expense",
            "amount": Decimal("300.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)
        assert spending_account.balance == Decimal("700.00")

        service.delete_transaction(txn.id, user)

        assert spending_account.balance == Decimal("1000.00")

    def test_delete_transfer_reverses_both_accounts(
        self, db_session, service, user, spending_account, destination_account
    ):
        """Deleting transfer reverses both source and destination (Req 3.7)."""
        data = {
            "type": "transfer",
            "amount": Decimal("250.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "destination_account_id": destination_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)

        service.delete_transaction(txn.id, user)

        assert spending_account.balance == Decimal("1000.00")
        assert destination_account.balance == Decimal("200.00")

    def test_delete_credit_card_payment_reverses(
        self, db_session, service, user, spending_account, credit_card_account
    ):
        """Deleting CC payment restores source and re-adds CC debt (Req 3.7)."""
        data = {
            "type": "credit_card_payment",
            "amount": Decimal("200.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "destination_account_id": credit_card_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)

        service.delete_transaction(txn.id, user)

        assert spending_account.balance == Decimal("1000.00")
        assert credit_card_account.balance == Decimal("-500.00")

    def test_delete_removes_transaction_record(
        self, db_session, service, user, spending_account
    ):
        """Deleted transaction no longer exists in database (Req 3.7)."""
        data = {
            "type": "expense",
            "amount": Decimal("50.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)
        txn_id = txn.id

        service.delete_transaction(txn_id, user)

        assert db_session.get(Transaction, txn_id) is None

    def test_delete_nonexistent_transaction_raises(
        self, db_session, service, user
    ):
        """Deleting nonexistent transaction raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            service.delete_transaction(99999, user)

    def test_delete_other_users_transaction_raises(
        self, db_session, service, user, spending_account
    ):
        """Cannot delete another user's transaction."""
        other_user = UserFactory()
        db_session.flush()

        data = {
            "type": "expense",
            "amount": Decimal("50.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)

        with pytest.raises(ValueError, match="does not have access"):
            service.delete_transaction(txn.id, other_user)


class TestUpdateTransaction:
    """Tests for TransactionService.update_transaction."""

    def test_update_amount_reverses_and_reapplies(
        self, db_session, service, user, spending_account
    ):
        """Updating amount reverses old impact and applies new (Req 3.11).

        Start: balance=1000, expense=300 -> balance=700
        Update: expense=500 -> reverse 300 (balance=1000), apply 500 (balance=500)
        """
        data = {
            "type": "expense",
            "amount": Decimal("300.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)
        assert spending_account.balance == Decimal("700.00")

        updated = service.update_transaction(
            txn.id, {"amount": Decimal("500.00")}, user
        )

        assert updated.amount == Decimal("500.00")
        assert spending_account.balance == Decimal("500.00")

    def test_update_type_from_expense_to_income(
        self, db_session, service, user, spending_account
    ):
        """Changing type reverses old and applies new direction (Req 3.11).

        Start: balance=1000, expense=200 -> balance=800
        Update: income=200 -> reverse expense (balance=1000), apply income (balance=1200)
        """
        data = {
            "type": "expense",
            "amount": Decimal("200.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)
        assert spending_account.balance == Decimal("800.00")

        updated = service.update_transaction(
            txn.id, {"type": "income"}, user
        )

        assert updated.type == TransactionType.income
        assert spending_account.balance == Decimal("1200.00")

    def test_update_account_moves_balance_impact(
        self, db_session, service, user, spending_account, destination_account
    ):
        """Changing account moves balance impact to new account (Req 3.11).

        Start: spending=1000, dest=200
        Expense 300 on spending -> spending=700
        Update to destination -> spending restored to 1000, dest=200-300=-100
        """
        data = {
            "type": "expense",
            "amount": Decimal("300.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)
        assert spending_account.balance == Decimal("700.00")

        updated = service.update_transaction(
            txn.id, {"account_id": destination_account.id}, user
        )

        assert spending_account.balance == Decimal("1000.00")
        assert destination_account.balance == Decimal("-100.00")

    def test_update_validates_new_amount(
        self, db_session, service, user, spending_account
    ):
        """Amount validation applies on update (Req 3.12)."""
        data = {
            "type": "expense",
            "amount": Decimal("100.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)

        with pytest.raises(ValueError, match="between"):
            service.update_transaction(
                txn.id, {"amount": Decimal("0.00")}, user
            )

    def test_update_checks_overdraft_on_new_impact(
        self, db_session, service, user, spending_account_with_overdraft
    ):
        """Overdraft check applies to new impacts after update (Req 3.9).

        Account balance=100, max_overdraft=200.
        Create expense 50 -> balance=50
        Update to 400 -> reverse (balance=100), check overdraft for 400:
        100 - 400 = -300 < -200 -> rejected
        """
        data = {
            "type": "expense",
            "amount": Decimal("50.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account_with_overdraft.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)

        with pytest.raises(OverdraftLimitExceeded):
            service.update_transaction(
                txn.id, {"amount": Decimal("400.00")}, user
            )

    def test_update_preserves_unmodified_fields(
        self, db_session, service, user, spending_account
    ):
        """Fields not in data dict remain unchanged (Req 3.11)."""
        data = {
            "type": "expense",
            "amount": Decimal("100.00"),
            "date": date(2024, 1, 15),
            "account_id": spending_account.id,
            "scope": "personal",
            "description": "Original",
        }
        txn = service.create_transaction(data, user)

        updated = service.update_transaction(
            txn.id, {"amount": Decimal("150.00")}, user
        )

        assert updated.description == "Original"
        assert updated.date == date(2024, 1, 15)
