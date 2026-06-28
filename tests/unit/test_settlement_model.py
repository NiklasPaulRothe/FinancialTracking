"""Unit tests for Settlement and SettlementAllocation models.

Validates: Requirements 12.2, 12.7

Tests that:
- Settlement model can be created with valid data
- Settlement CHECK constraint prevents from_user == to_user
- Settlement CHECK constraint enforces amount range (0.01 to 999999999.99)
- SettlementAllocation links a settlement to a SharedExpenseShare
- Relationships between Settlement, SettlementAllocation, and SharedExpenseShare work
"""

import pytest
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.models.transaction import (
    Settlement,
    SettlementAllocation,
    SharedExpense,
    SharedExpenseShare,
    Transaction,
    TransactionType,
    TransactionScope,
)
from tests.factories import UserFactory, AccountFactory


@pytest.fixture()
def user(db_session):
    """Create the primary test user."""
    return UserFactory()


@pytest.fixture()
def partner(db_session):
    """Create the household partner user."""
    return UserFactory()


@pytest.fixture()
def shared_expense_share(db_session, user, partner):
    """Create a SharedExpense with a share for the partner."""
    account = AccountFactory(
        owner=user,
        type="spending",
        scope="shared",
        balance=Decimal("5000.00"),
    )
    db_session.flush()

    txn = Transaction(
        type=TransactionType.expense,
        amount=Decimal("100.00"),
        date=date(2024, 3, 15),
        scope=TransactionScope.shared,
        account_id=account.id,
        user_id=user.id,
        posted=True,
    )
    db_session.add(txn)
    db_session.flush()

    shared_expense = SharedExpense(transaction_id=txn.id)
    db_session.add(shared_expense)
    db_session.flush()

    share = SharedExpenseShare(
        shared_expense_id=shared_expense.id,
        user_id=partner.id,
        amount=Decimal("50.00"),
        settled=False,
    )
    db_session.add(share)
    db_session.flush()

    return share


class TestSettlementModel:
    """Tests for the Settlement model."""

    def test_create_settlement_with_valid_data(self, db_session, user, partner):
        """Settlement can be created with valid amount, date, and different users."""
        settlement = Settlement(
            amount=Decimal("50.00"),
            date=date(2024, 4, 1),
            from_user_id=partner.id,
            to_user_id=user.id,
        )
        db_session.add(settlement)
        db_session.flush()

        assert settlement.id is not None
        assert settlement.amount == Decimal("50.00")
        assert settlement.date == date(2024, 4, 1)
        assert settlement.from_user_id == partner.id
        assert settlement.to_user_id == user.id
        assert settlement.created_at is not None

    def test_settlement_from_user_relationship(self, db_session, user, partner):
        """Settlement.from_user resolves to the correct User."""
        settlement = Settlement(
            amount=Decimal("25.00"),
            date=date(2024, 4, 1),
            from_user_id=partner.id,
            to_user_id=user.id,
        )
        db_session.add(settlement)
        db_session.flush()

        assert settlement.from_user.id == partner.id

    def test_settlement_to_user_relationship(self, db_session, user, partner):
        """Settlement.to_user resolves to the correct User."""
        settlement = Settlement(
            amount=Decimal("25.00"),
            date=date(2024, 4, 1),
            from_user_id=partner.id,
            to_user_id=user.id,
        )
        db_session.add(settlement)
        db_session.flush()

        assert settlement.to_user.id == user.id

    def test_settlement_check_constraint_same_user(self, db_session, user):
        """Settlement with from_user_id == to_user_id violates CHECK constraint (Req 12.7)."""
        settlement = Settlement(
            amount=Decimal("50.00"),
            date=date(2024, 4, 1),
            from_user_id=user.id,
            to_user_id=user.id,
        )
        db_session.add(settlement)

        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_settlement_check_constraint_amount_too_low(self, db_session, user, partner):
        """Settlement with amount < 0.01 violates CHECK constraint."""
        settlement = Settlement(
            amount=Decimal("0.00"),
            date=date(2024, 4, 1),
            from_user_id=partner.id,
            to_user_id=user.id,
        )
        db_session.add(settlement)

        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_settlement_check_constraint_amount_too_high(self, db_session, user, partner):
        """Settlement with amount > 999999999.99 violates CHECK constraint."""
        settlement = Settlement(
            amount=Decimal("9999999999.99"),
            date=date(2024, 4, 1),
            from_user_id=partner.id,
            to_user_id=user.id,
        )
        db_session.add(settlement)

        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_settlement_minimum_valid_amount(self, db_session, user, partner):
        """Settlement with minimum valid amount (0.01) is accepted."""
        settlement = Settlement(
            amount=Decimal("0.01"),
            date=date(2024, 4, 1),
            from_user_id=partner.id,
            to_user_id=user.id,
        )
        db_session.add(settlement)
        db_session.flush()

        assert settlement.amount == Decimal("0.01")

    def test_settlement_maximum_valid_amount(self, db_session, user, partner):
        """Settlement with maximum valid amount (999999999.99) is accepted."""
        settlement = Settlement(
            amount=Decimal("999999999.99"),
            date=date(2024, 4, 1),
            from_user_id=partner.id,
            to_user_id=user.id,
        )
        db_session.add(settlement)
        db_session.flush()

        assert settlement.amount == Decimal("999999999.99")

    def test_settlement_repr(self, db_session, user, partner):
        """Settlement __repr__ includes useful info."""
        settlement = Settlement(
            amount=Decimal("75.00"),
            date=date(2024, 4, 1),
            from_user_id=partner.id,
            to_user_id=user.id,
        )
        db_session.add(settlement)
        db_session.flush()

        repr_str = repr(settlement)
        assert "Settlement" in repr_str
        assert "75.00" in repr_str


class TestSettlementAllocationModel:
    """Tests for the SettlementAllocation model."""

    def test_create_settlement_allocation(
        self, db_session, user, partner, shared_expense_share
    ):
        """SettlementAllocation links a settlement to a SharedExpenseShare."""
        settlement = Settlement(
            amount=Decimal("50.00"),
            date=date(2024, 4, 1),
            from_user_id=partner.id,
            to_user_id=user.id,
        )
        db_session.add(settlement)
        db_session.flush()

        allocation = SettlementAllocation(
            settlement_id=settlement.id,
            shared_expense_share_id=shared_expense_share.id,
            amount=Decimal("50.00"),
        )
        db_session.add(allocation)
        db_session.flush()

        assert allocation.id is not None
        assert allocation.settlement_id == settlement.id
        assert allocation.shared_expense_share_id == shared_expense_share.id
        assert allocation.amount == Decimal("50.00")

    def test_settlement_allocation_relationship_to_settlement(
        self, db_session, user, partner, shared_expense_share
    ):
        """SettlementAllocation.settlement navigates to the parent Settlement."""
        settlement = Settlement(
            amount=Decimal("50.00"),
            date=date(2024, 4, 1),
            from_user_id=partner.id,
            to_user_id=user.id,
        )
        db_session.add(settlement)
        db_session.flush()

        allocation = SettlementAllocation(
            settlement_id=settlement.id,
            shared_expense_share_id=shared_expense_share.id,
            amount=Decimal("50.00"),
        )
        db_session.add(allocation)
        db_session.flush()

        assert allocation.settlement.id == settlement.id

    def test_settlement_allocation_relationship_to_share(
        self, db_session, user, partner, shared_expense_share
    ):
        """SettlementAllocation.shared_expense_share navigates to the share."""
        settlement = Settlement(
            amount=Decimal("50.00"),
            date=date(2024, 4, 1),
            from_user_id=partner.id,
            to_user_id=user.id,
        )
        db_session.add(settlement)
        db_session.flush()

        allocation = SettlementAllocation(
            settlement_id=settlement.id,
            shared_expense_share_id=shared_expense_share.id,
            amount=Decimal("50.00"),
        )
        db_session.add(allocation)
        db_session.flush()

        assert allocation.shared_expense_share.id == shared_expense_share.id

    def test_settlement_allocations_cascade_on_delete(
        self, db_session, user, partner, shared_expense_share
    ):
        """Deleting a settlement cascades and deletes its allocations."""
        settlement = Settlement(
            amount=Decimal("50.00"),
            date=date(2024, 4, 1),
            from_user_id=partner.id,
            to_user_id=user.id,
        )
        db_session.add(settlement)
        db_session.flush()

        allocation = SettlementAllocation(
            settlement_id=settlement.id,
            shared_expense_share_id=shared_expense_share.id,
            amount=Decimal("25.00"),
        )
        db_session.add(allocation)
        db_session.flush()

        allocation_id = allocation.id
        db_session.delete(settlement)
        db_session.flush()

        result = SettlementAllocation.query.get(allocation_id)
        assert result is None

    def test_settlement_allocations_list_from_settlement(
        self, db_session, user, partner, shared_expense_share
    ):
        """Settlement.allocations returns linked SettlementAllocation records."""
        settlement = Settlement(
            amount=Decimal("50.00"),
            date=date(2024, 4, 1),
            from_user_id=partner.id,
            to_user_id=user.id,
        )
        db_session.add(settlement)
        db_session.flush()

        allocation = SettlementAllocation(
            settlement_id=settlement.id,
            shared_expense_share_id=shared_expense_share.id,
            amount=Decimal("50.00"),
        )
        db_session.add(allocation)
        db_session.flush()

        assert len(settlement.allocations) == 1
        assert settlement.allocations[0].id == allocation.id

    def test_settlement_allocation_repr(
        self, db_session, user, partner, shared_expense_share
    ):
        """SettlementAllocation __repr__ includes useful info."""
        settlement = Settlement(
            amount=Decimal("50.00"),
            date=date(2024, 4, 1),
            from_user_id=partner.id,
            to_user_id=user.id,
        )
        db_session.add(settlement)
        db_session.flush()

        allocation = SettlementAllocation(
            settlement_id=settlement.id,
            shared_expense_share_id=shared_expense_share.id,
            amount=Decimal("30.00"),
        )
        db_session.add(allocation)
        db_session.flush()

        repr_str = repr(allocation)
        assert "SettlementAllocation" in repr_str
        assert "30.00" in repr_str
