"""Unit tests for TransactionService.set_transaction_splits.

Tests split creation, validation (sum, count, amounts), and replacement logic.

Validates: Requirements 4.1, 4.3, 4.4, 4.5, 4.6
"""

import pytest
from datetime import date
from decimal import Decimal

from app.exceptions import SplitSumMismatchError
from app.extensions import db
from app.models.category import Category
from app.models.transaction import (
    Transaction,
    TransactionSplit,
    TransactionType,
    TransactionScope,
)
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
def categories(db_session, user):
    """Create test categories for splits."""
    cats = []
    for i in range(5):
        cat = Category(
            name=f"Category {i}",
            scope="personal",
            user_id=user.id,
        )
        db_session.add(cat)
        cats.append(cat)
    db_session.flush()
    return cats


@pytest.fixture()
def transfer_transaction(db_session, service, user):
    """Create a transfer transaction with amount 1000."""
    source = AccountFactory(
        owner=user,
        type="spending",
        scope="personal",
        balance=Decimal("5000.00"),
    )
    dest = AccountFactory(
        owner=user,
        type="spending",
        scope="personal",
        balance=Decimal("0.00"),
    )
    db_session.flush()

    data = {
        "type": "transfer",
        "amount": Decimal("1000.00"),
        "date": date(2024, 3, 15),
        "account_id": source.id,
        "destination_account_id": dest.id,
        "scope": "personal",
    }
    txn = service.create_transaction(data, user)
    return txn


@pytest.fixture()
def expense_transaction(db_session, service, user):
    """Create an expense transaction (non-transfer)."""
    account = AccountFactory(
        owner=user,
        type="spending",
        scope="personal",
        balance=Decimal("5000.00"),
    )
    db_session.flush()

    data = {
        "type": "expense",
        "amount": Decimal("500.00"),
        "date": date(2024, 3, 15),
        "account_id": account.id,
        "scope": "personal",
    }
    txn = service.create_transaction(data, user)
    return txn


class TestSetTransactionSplitsValid:
    """Tests for valid split operations."""

    def test_valid_splits_sum_matches(
        self, db_session, service, user, transfer_transaction, categories
    ):
        """Valid splits with sum matching transaction total succeed (Req 4.1, 4.3)."""
        splits_data = [
            {"category_id": categories[0].id, "amount": Decimal("600.00")},
            {"category_id": categories[1].id, "amount": Decimal("400.00")},
        ]

        result = service.set_transaction_splits(
            transfer_transaction.id, splits_data, user
        )

        assert len(result) == 2
        assert result[0].amount == Decimal("600.00")
        assert result[1].amount == Decimal("400.00")
        assert result[0].transaction_id == transfer_transaction.id

    def test_valid_splits_with_description(
        self, db_session, service, user, transfer_transaction, categories
    ):
        """Splits can have optional descriptions (Req 4.1)."""
        splits_data = [
            {
                "category_id": categories[0].id,
                "amount": Decimal("700.00"),
                "description": "Rent portion",
            },
            {
                "category_id": categories[1].id,
                "amount": Decimal("300.00"),
                "description": None,
            },
        ]

        result = service.set_transaction_splits(
            transfer_transaction.id, splits_data, user
        )

        assert result[0].description == "Rent portion"
        assert result[1].description is None

    def test_valid_splits_exactly_20(
        self, db_session, service, user, transfer_transaction, categories
    ):
        """Maximum of 20 splits is accepted (Req 4.1)."""
        # Create enough categories
        extra_cats = []
        for i in range(20):
            cat = Category(
                name=f"Extra Cat {i}",
                scope="personal",
                user_id=user.id,
            )
            db_session.add(cat)
            extra_cats.append(cat)
        db_session.flush()

        # 20 splits of 50.00 each = 1000.00
        splits_data = [
            {"category_id": extra_cats[i].id, "amount": Decimal("50.00")}
            for i in range(20)
        ]

        result = service.set_transaction_splits(
            transfer_transaction.id, splits_data, user
        )

        assert len(result) == 20

    def test_valid_splits_exactly_2(
        self, db_session, service, user, transfer_transaction, categories
    ):
        """Minimum of 2 splits is accepted (Req 4.1)."""
        splits_data = [
            {"category_id": categories[0].id, "amount": Decimal("500.00")},
            {"category_id": categories[1].id, "amount": Decimal("500.00")},
        ]

        result = service.set_transaction_splits(
            transfer_transaction.id, splits_data, user
        )

        assert len(result) == 2


class TestSetTransactionSplitsSumMismatch:
    """Tests for sum mismatch validation."""

    def test_sum_less_than_total_raises_error(
        self, db_session, service, user, transfer_transaction, categories
    ):
        """Sum less than transaction total raises SplitSumMismatchError (Req 4.4)."""
        splits_data = [
            {"category_id": categories[0].id, "amount": Decimal("400.00")},
            {"category_id": categories[1].id, "amount": Decimal("300.00")},
        ]
        # Sum = 700, transaction = 1000

        with pytest.raises(SplitSumMismatchError) as exc_info:
            service.set_transaction_splits(
                transfer_transaction.id, splits_data, user
            )

        assert exc_info.value.transaction_amount == Decimal("1000.00")
        assert exc_info.value.split_sum == Decimal("700.00")
        assert exc_info.value.difference == Decimal("300.00")

    def test_sum_greater_than_total_raises_error(
        self, db_session, service, user, transfer_transaction, categories
    ):
        """Sum greater than transaction total raises SplitSumMismatchError (Req 4.4)."""
        splits_data = [
            {"category_id": categories[0].id, "amount": Decimal("600.00")},
            {"category_id": categories[1].id, "amount": Decimal("500.00")},
        ]
        # Sum = 1100, transaction = 1000

        with pytest.raises(SplitSumMismatchError) as exc_info:
            service.set_transaction_splits(
                transfer_transaction.id, splits_data, user
            )

        assert exc_info.value.transaction_amount == Decimal("1000.00")
        assert exc_info.value.split_sum == Decimal("1100.00")
        assert exc_info.value.difference == Decimal("-100.00")


class TestSetTransactionSplitsCountValidation:
    """Tests for split count constraints."""

    def test_too_few_splits_raises_error(
        self, db_session, service, user, transfer_transaction, categories
    ):
        """Fewer than 2 splits raises ValueError (Req 4.1)."""
        splits_data = [
            {"category_id": categories[0].id, "amount": Decimal("1000.00")},
        ]

        with pytest.raises(ValueError, match="At least 2"):
            service.set_transaction_splits(
                transfer_transaction.id, splits_data, user
            )

    def test_zero_splits_raises_error(
        self, db_session, service, user, transfer_transaction, categories
    ):
        """Empty splits list raises ValueError (Req 4.1)."""
        with pytest.raises(ValueError, match="At least 2"):
            service.set_transaction_splits(
                transfer_transaction.id, [], user
            )

    def test_too_many_splits_raises_error(
        self, db_session, service, user, transfer_transaction, categories
    ):
        """More than 20 splits raises ValueError (Req 4.1)."""
        # Create 21 categories
        extra_cats = []
        for i in range(21):
            cat = Category(
                name=f"TooMany Cat {i}",
                scope="personal",
                user_id=user.id,
            )
            db_session.add(cat)
            extra_cats.append(cat)
        db_session.flush()

        # 21 splits
        splits_data = [
            {"category_id": extra_cats[i].id, "amount": Decimal("47.62")}
            for i in range(21)
        ]

        with pytest.raises(ValueError, match="At most 20"):
            service.set_transaction_splits(
                transfer_transaction.id, splits_data, user
            )


class TestSetTransactionSplitsAmountValidation:
    """Tests for individual split amount validation."""

    def test_zero_amount_raises_error(
        self, db_session, service, user, transfer_transaction, categories
    ):
        """Split with zero amount raises ValueError (Req 4.1)."""
        splits_data = [
            {"category_id": categories[0].id, "amount": Decimal("1000.00")},
            {"category_id": categories[1].id, "amount": Decimal("0.00")},
        ]

        with pytest.raises(ValueError, match="positive non-zero"):
            service.set_transaction_splits(
                transfer_transaction.id, splits_data, user
            )

    def test_negative_amount_raises_error(
        self, db_session, service, user, transfer_transaction, categories
    ):
        """Split with negative amount raises ValueError (Req 4.1)."""
        splits_data = [
            {"category_id": categories[0].id, "amount": Decimal("1100.00")},
            {"category_id": categories[1].id, "amount": Decimal("-100.00")},
        ]

        with pytest.raises(ValueError, match="positive non-zero"):
            service.set_transaction_splits(
                transfer_transaction.id, splits_data, user
            )


class TestSetTransactionSplitsReplacement:
    """Tests for replacing existing splits."""

    def test_replacing_splits_removes_old_ones(
        self, db_session, service, user, transfer_transaction, categories
    ):
        """Setting new splits replaces all existing ones (Req 4.5)."""
        # First set of splits
        first_splits = [
            {"category_id": categories[0].id, "amount": Decimal("600.00")},
            {"category_id": categories[1].id, "amount": Decimal("400.00")},
        ]
        service.set_transaction_splits(
            transfer_transaction.id, first_splits, user
        )

        # Replace with new splits
        new_splits = [
            {"category_id": categories[2].id, "amount": Decimal("300.00")},
            {"category_id": categories[3].id, "amount": Decimal("500.00")},
            {"category_id": categories[4].id, "amount": Decimal("200.00")},
        ]
        result = service.set_transaction_splits(
            transfer_transaction.id, new_splits, user
        )

        assert len(result) == 3
        # Verify old splits are gone
        remaining = TransactionSplit.query.filter_by(
            transaction_id=transfer_transaction.id
        ).all()
        assert len(remaining) == 3
        amounts = sorted([s.amount for s in remaining])
        assert amounts == [Decimal("200.00"), Decimal("300.00"), Decimal("500.00")]


class TestSetTransactionSplitsTypeRestriction:
    """Tests for transaction type restriction."""

    def test_non_transfer_transaction_rejects_splits(
        self, db_session, service, user, expense_transaction, categories
    ):
        """Expense transaction cannot have splits (Req 4.1)."""
        splits_data = [
            {"category_id": categories[0].id, "amount": Decimal("250.00")},
            {"category_id": categories[1].id, "amount": Decimal("250.00")},
        ]

        with pytest.raises(ValueError, match="transfer"):
            service.set_transaction_splits(
                expense_transaction.id, splits_data, user
            )

    def test_income_transaction_rejects_splits(
        self, db_session, service, user, categories
    ):
        """Income transaction cannot have splits (Req 4.1)."""
        account = AccountFactory(
            owner=user,
            type="spending",
            scope="personal",
            balance=Decimal("0.00"),
        )
        db_session.flush()

        data = {
            "type": "income",
            "amount": Decimal("1000.00"),
            "date": date(2024, 3, 15),
            "account_id": account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)

        splits_data = [
            {"category_id": categories[0].id, "amount": Decimal("500.00")},
            {"category_id": categories[1].id, "amount": Decimal("500.00")},
        ]

        with pytest.raises(ValueError, match="transfer"):
            service.set_transaction_splits(txn.id, splits_data, user)
