"""Unit tests for SharedExpense auto-creation on shared transactions.

Validates: Requirements 3.5, 3.6

Tests that:
- Shared income/expense/credit_card_payment auto-creates SharedExpense + 2 shares
- Shared transfer does NOT create SharedExpense
- Personal transactions don't create SharedExpense
- 50/50 split amounts are correct
"""

import pytest
from datetime import date
from decimal import Decimal

from app.models.transaction import (
    SharedExpense,
    SharedExpenseShare,
    Transaction,
    TransactionType,
    TransactionScope,
)
from app.services.transaction_service import TransactionService
from tests.factories import UserFactory, AccountFactory


@pytest.fixture()
def service():
    """Provide a TransactionService instance."""
    return TransactionService()


@pytest.fixture()
def user(db_session):
    """Create the primary test user."""
    return UserFactory()


@pytest.fixture()
def partner(db_session):
    """Create the household partner user."""
    return UserFactory()


@pytest.fixture()
def shared_account(db_session, user):
    """Create a shared spending account with 5000 balance."""
    account = AccountFactory(
        owner=user,
        type="spending",
        scope="shared",
        balance=Decimal("5000.00"),
    )
    db_session.flush()
    return account


@pytest.fixture()
def personal_account(db_session, user):
    """Create a personal spending account with 2000 balance."""
    account = AccountFactory(
        owner=user,
        type="spending",
        scope="personal",
        balance=Decimal("2000.00"),
    )
    db_session.flush()
    return account


@pytest.fixture()
def destination_account(db_session, user):
    """Create a destination account for transfers."""
    account = AccountFactory(
        owner=user,
        type="spending",
        scope="shared",
        balance=Decimal("1000.00"),
    )
    db_session.flush()
    return account


@pytest.fixture()
def credit_card_account(db_session, user):
    """Create a credit card account."""
    account = AccountFactory(
        owner=user,
        type="credit_card",
        scope="shared",
        balance=Decimal("-800.00"),
    )
    db_session.flush()
    return account


class TestSharedExpenseAutoCreation:
    """Tests for SharedExpense auto-creation on qualifying shared transactions (Req 3.5)."""

    def test_shared_expense_creates_shared_expense_record(
        self, db_session, service, user, partner, shared_account
    ):
        """Shared expense transaction creates a SharedExpense record."""
        data = {
            "type": "expense",
            "amount": Decimal("100.00"),
            "date": date(2024, 3, 15),
            "account_id": shared_account.id,
            "scope": "shared",
        }

        txn = service.create_transaction(data, user)

        shared_expenses = SharedExpense.query.filter_by(transaction_id=txn.id).all()
        assert len(shared_expenses) == 1

    def test_shared_expense_creates_two_shares(
        self, db_session, service, user, partner, shared_account
    ):
        """Shared expense creates two SharedExpenseShare records (one per member)."""
        data = {
            "type": "expense",
            "amount": Decimal("200.00"),
            "date": date(2024, 3, 15),
            "account_id": shared_account.id,
            "scope": "shared",
        }

        txn = service.create_transaction(data, user)

        shared_expense = SharedExpense.query.filter_by(transaction_id=txn.id).first()
        shares = SharedExpenseShare.query.filter_by(
            shared_expense_id=shared_expense.id
        ).all()
        assert len(shares) == 2

    def test_shared_expense_50_50_split(
        self, db_session, service, user, partner, shared_account
    ):
        """Each share gets exactly half the transaction amount."""
        data = {
            "type": "expense",
            "amount": Decimal("100.00"),
            "date": date(2024, 3, 15),
            "account_id": shared_account.id,
            "scope": "shared",
        }

        txn = service.create_transaction(data, user)

        shared_expense = SharedExpense.query.filter_by(transaction_id=txn.id).first()
        shares = SharedExpenseShare.query.filter_by(
            shared_expense_id=shared_expense.id
        ).all()
        for share in shares:
            assert share.amount == Decimal("50.00")

    def test_shared_expense_shares_assigned_to_user_and_partner(
        self, db_session, service, user, partner, shared_account
    ):
        """Shares are assigned to the creating user and the partner."""
        data = {
            "type": "expense",
            "amount": Decimal("80.00"),
            "date": date(2024, 3, 15),
            "account_id": shared_account.id,
            "scope": "shared",
        }

        txn = service.create_transaction(data, user)

        shared_expense = SharedExpense.query.filter_by(transaction_id=txn.id).first()
        shares = SharedExpenseShare.query.filter_by(
            shared_expense_id=shared_expense.id
        ).all()
        share_user_ids = {share.user_id for share in shares}
        assert share_user_ids == {user.id, partner.id}

    def test_shared_income_creates_shared_expense(
        self, db_session, service, user, partner, shared_account
    ):
        """Shared income transaction also creates SharedExpense (Req 3.5)."""
        data = {
            "type": "income",
            "amount": Decimal("3000.00"),
            "date": date(2024, 3, 1),
            "account_id": shared_account.id,
            "scope": "shared",
        }

        txn = service.create_transaction(data, user)

        shared_expenses = SharedExpense.query.filter_by(transaction_id=txn.id).all()
        assert len(shared_expenses) == 1
        shares = SharedExpenseShare.query.filter_by(
            shared_expense_id=shared_expenses[0].id
        ).all()
        assert len(shares) == 2
        for share in shares:
            assert share.amount == Decimal("1500.00")

    def test_shared_credit_card_payment_creates_shared_expense(
        self, db_session, service, user, partner, shared_account, credit_card_account
    ):
        """Shared credit_card_payment creates SharedExpense (Req 3.5)."""
        data = {
            "type": "credit_card_payment",
            "amount": Decimal("400.00"),
            "date": date(2024, 3, 10),
            "account_id": shared_account.id,
            "destination_account_id": credit_card_account.id,
            "scope": "shared",
        }

        txn = service.create_transaction(data, user)

        shared_expenses = SharedExpense.query.filter_by(transaction_id=txn.id).all()
        assert len(shared_expenses) == 1
        shares = SharedExpenseShare.query.filter_by(
            shared_expense_id=shared_expenses[0].id
        ).all()
        assert len(shares) == 2
        for share in shares:
            assert share.amount == Decimal("200.00")

    def test_shared_expense_shares_not_settled_by_default(
        self, db_session, service, user, partner, shared_account
    ):
        """Newly created shares have settled=False and settled_at=None."""
        data = {
            "type": "expense",
            "amount": Decimal("60.00"),
            "date": date(2024, 3, 15),
            "account_id": shared_account.id,
            "scope": "shared",
        }

        txn = service.create_transaction(data, user)

        shared_expense = SharedExpense.query.filter_by(transaction_id=txn.id).first()
        shares = SharedExpenseShare.query.filter_by(
            shared_expense_id=shared_expense.id
        ).all()
        for share in shares:
            assert share.settled is False
            assert share.settled_at is None


class TestSharedTransferNoSharedExpense:
    """Tests that shared transfers do NOT create SharedExpense (Req 3.6)."""

    def test_shared_transfer_does_not_create_shared_expense(
        self, db_session, service, user, partner, shared_account, destination_account
    ):
        """Shared transfer skips SharedExpense creation (Req 3.6)."""
        data = {
            "type": "transfer",
            "amount": Decimal("500.00"),
            "date": date(2024, 3, 15),
            "account_id": shared_account.id,
            "destination_account_id": destination_account.id,
            "scope": "shared",
        }

        txn = service.create_transaction(data, user)

        shared_expenses = SharedExpense.query.filter_by(transaction_id=txn.id).all()
        assert len(shared_expenses) == 0


class TestPersonalTransactionNoSharedExpense:
    """Tests that personal transactions do NOT create SharedExpense."""

    def test_personal_expense_no_shared_expense(
        self, db_session, service, user, partner, personal_account
    ):
        """Personal expense does not create SharedExpense."""
        data = {
            "type": "expense",
            "amount": Decimal("75.00"),
            "date": date(2024, 3, 15),
            "account_id": personal_account.id,
            "scope": "personal",
        }

        txn = service.create_transaction(data, user)

        shared_expenses = SharedExpense.query.filter_by(transaction_id=txn.id).all()
        assert len(shared_expenses) == 0

    def test_personal_income_no_shared_expense(
        self, db_session, service, user, partner, personal_account
    ):
        """Personal income does not create SharedExpense."""
        data = {
            "type": "income",
            "amount": Decimal("2000.00"),
            "date": date(2024, 3, 1),
            "account_id": personal_account.id,
            "scope": "personal",
        }

        txn = service.create_transaction(data, user)

        shared_expenses = SharedExpense.query.filter_by(transaction_id=txn.id).all()
        assert len(shared_expenses) == 0

    def test_personal_transfer_no_shared_expense(
        self, db_session, service, user, partner, personal_account, destination_account
    ):
        """Personal transfer does not create SharedExpense."""
        data = {
            "type": "transfer",
            "amount": Decimal("300.00"),
            "date": date(2024, 3, 15),
            "account_id": personal_account.id,
            "destination_account_id": destination_account.id,
            "scope": "personal",
        }

        txn = service.create_transaction(data, user)

        shared_expenses = SharedExpense.query.filter_by(transaction_id=txn.id).all()
        assert len(shared_expenses) == 0
