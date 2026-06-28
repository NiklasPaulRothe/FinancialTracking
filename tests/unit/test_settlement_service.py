"""Unit tests for SettlementService with FIFO allocation.

Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7

Tests cover:
- Net balance computation between partners
- FIFO settlement allocation (oldest shares first)
- Full coverage (settled=True, settled_at recorded)
- Partial coverage (allocation created, settled stays False)
- Excess settlement (credit for paying user)
- Settlement deletion reverses all allocations
- InvalidSettlementError when from_user == to_user
"""

import pytest
from datetime import date, datetime, timezone
from decimal import Decimal

from app.extensions import db
from app.exceptions import InvalidSettlementError
from app.models.transaction import (
    Settlement,
    SettlementAllocation,
    SharedExpense,
    SharedExpenseShare,
    Transaction,
    TransactionType,
    TransactionScope,
)
from app.services.settlement_service import SettlementService
from tests.factories import UserFactory, AccountFactory


@pytest.fixture()
def service():
    """Provide a SettlementService instance."""
    return SettlementService()


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
    """Create a shared spending account for the user."""
    account = AccountFactory(
        owner=user,
        type="spending",
        scope="shared",
        balance=Decimal("5000.00"),
    )
    db_session.flush()
    return account


def _create_shared_expense_for_user(
    db_session, payer, partner, amount, created_at=None
):
    """Helper to create a SharedExpense with 50/50 split.

    Creates a transaction paid by `payer`, then a SharedExpense with
    two shares (one for each user at 50% of the amount).
    The partner's share represents what the partner owes the payer.
    """
    if created_at is None:
        created_at = datetime.now(timezone.utc)

    # Create the underlying transaction
    txn = Transaction(
        type=TransactionType.expense,
        amount=amount,
        date=date.today(),
        scope=TransactionScope.shared,
        user_id=payer.id,
        created_at=created_at,
    )
    db_session.add(txn)
    db_session.flush()

    # Create the SharedExpense
    shared_expense = SharedExpense(
        transaction_id=txn.id,
        created_at=created_at,
    )
    db_session.add(shared_expense)
    db_session.flush()

    # Create 50/50 shares
    share_amount = amount / 2
    share_payer = SharedExpenseShare(
        shared_expense_id=shared_expense.id,
        user_id=payer.id,
        amount=share_amount,
        settled=False,
    )
    share_partner = SharedExpenseShare(
        shared_expense_id=shared_expense.id,
        user_id=partner.id,
        amount=share_amount,
        settled=False,
    )
    db_session.add(share_payer)
    db_session.add(share_partner)
    db_session.flush()

    return shared_expense, share_payer, share_partner


class TestGetNetBalance:
    """Tests for SettlementService.get_net_balance (Req 12.1)."""

    def test_net_balance_zero_when_no_shared_expenses(
        self, db_session, service, user, partner
    ):
        """Net balance is zero when there are no shared expenses."""
        balance = service.get_net_balance(user)
        assert balance == Decimal("0.00")

    def test_net_balance_positive_when_partner_owes(
        self, db_session, service, user, partner
    ):
        """Net balance is positive when partner owes user money."""
        # User paid a shared expense of 100, partner owes 50
        _create_shared_expense_for_user(
            db_session, payer=user, partner=partner, amount=Decimal("100.00")
        )

        balance = service.get_net_balance(user)
        assert balance == Decimal("50.00")

    def test_net_balance_negative_when_user_owes(
        self, db_session, service, user, partner
    ):
        """Net balance is negative when user owes partner money."""
        # Partner paid a shared expense of 200, user owes 100
        _create_shared_expense_for_user(
            db_session, payer=partner, partner=user, amount=Decimal("200.00")
        )

        balance = service.get_net_balance(user)
        assert balance == Decimal("-100.00")

    def test_net_balance_accounts_for_both_directions(
        self, db_session, service, user, partner
    ):
        """Net balance accounts for expenses in both directions."""
        # User paid 100 (partner owes 50)
        _create_shared_expense_for_user(
            db_session, payer=user, partner=partner, amount=Decimal("100.00")
        )
        # Partner paid 60 (user owes 30)
        _create_shared_expense_for_user(
            db_session, payer=partner, partner=user, amount=Decimal("60.00")
        )

        balance = service.get_net_balance(user)
        # Partner owes 50 to user, user owes 30 to partner => net = 50 - 30 = 20
        assert balance == Decimal("20.00")

    def test_net_balance_no_partner_returns_zero(self, db_session, service, user):
        """Net balance returns zero if there's no partner."""
        balance = service.get_net_balance(user)
        assert balance == Decimal("0.00")


class TestCreateSettlement:
    """Tests for SettlementService.create_settlement (Req 12.2)."""

    def test_create_settlement_basic(
        self, db_session, service, user, partner
    ):
        """Creating a settlement persists the record correctly."""
        # Partner paid 100, user owes 50
        _create_shared_expense_for_user(
            db_session, payer=partner, partner=user, amount=Decimal("100.00")
        )

        settlement = service.create_settlement(
            from_user=user,
            to_user=partner,
            amount=Decimal("50.00"),
            settlement_date=date(2024, 3, 15),
        )

        assert settlement.id is not None
        assert settlement.amount == Decimal("50.00")
        assert settlement.date == date(2024, 3, 15)
        assert settlement.from_user_id == user.id
        assert settlement.to_user_id == partner.id

    def test_create_settlement_raises_on_same_user(
        self, db_session, service, user
    ):
        """Creating a settlement where from_user == to_user raises InvalidSettlementError."""
        with pytest.raises(InvalidSettlementError) as exc_info:
            service.create_settlement(
                from_user=user,
                to_user=user,
                amount=Decimal("50.00"),
                settlement_date=date(2024, 3, 15),
            )
        assert exc_info.value.user_id == user.id


class TestFIFOAllocation:
    """Tests for FIFO settlement allocation (Req 12.2, 12.3, 12.4)."""

    def test_fifo_allocates_oldest_share_first(
        self, db_session, service, user, partner
    ):
        """Settlement allocates to oldest outstanding share first."""
        # Create two shared expenses at different times
        # Older expense: partner paid 80 (user's share = 40)
        older_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        _, _, user_share_old = _create_shared_expense_for_user(
            db_session, payer=partner, partner=user,
            amount=Decimal("80.00"), created_at=older_ts,
        )

        # Newer expense: partner paid 100 (user's share = 50)
        newer_ts = datetime(2024, 2, 1, tzinfo=timezone.utc)
        _, _, user_share_new = _create_shared_expense_for_user(
            db_session, payer=partner, partner=user,
            amount=Decimal("100.00"), created_at=newer_ts,
        )

        # User settles 40 (exactly covers the older share)
        settlement = service.create_settlement(
            from_user=user,
            to_user=partner,
            amount=Decimal("40.00"),
            settlement_date=date(2024, 3, 1),
        )

        # Older share should be fully settled
        db_session.refresh(user_share_old)
        assert user_share_old.settled is True
        assert user_share_old.settled_at is not None

        # Newer share should remain unsettled
        db_session.refresh(user_share_new)
        assert user_share_new.settled is False
        assert user_share_new.settled_at is None

    def test_full_coverage_sets_settled_true(
        self, db_session, service, user, partner
    ):
        """Full coverage marks share as settled with settled_at timestamp."""
        # Partner paid 60, user's share = 30
        _, _, user_share = _create_shared_expense_for_user(
            db_session, payer=partner, partner=user, amount=Decimal("60.00")
        )

        service.create_settlement(
            from_user=user,
            to_user=partner,
            amount=Decimal("30.00"),
            settlement_date=date(2024, 3, 15),
        )

        db_session.refresh(user_share)
        assert user_share.settled is True
        assert user_share.settled_at is not None

    def test_partial_coverage_does_not_set_settled(
        self, db_session, service, user, partner
    ):
        """Partial coverage creates allocation but settled stays False."""
        # Partner paid 100, user's share = 50
        _, _, user_share = _create_shared_expense_for_user(
            db_session, payer=partner, partner=user, amount=Decimal("100.00")
        )

        settlement = service.create_settlement(
            from_user=user,
            to_user=partner,
            amount=Decimal("20.00"),
            settlement_date=date(2024, 3, 15),
        )

        db_session.refresh(user_share)
        assert user_share.settled is False
        assert user_share.settled_at is None

        # But an allocation should exist
        allocations = SettlementAllocation.query.filter_by(
            settlement_id=settlement.id
        ).all()
        assert len(allocations) == 1
        assert allocations[0].amount == Decimal("20.00")
        assert allocations[0].shared_expense_share_id == user_share.id

    def test_partial_then_full_coverage(
        self, db_session, service, user, partner
    ):
        """Two partial settlements that together fully cover a share."""
        # Partner paid 100, user's share = 50
        _, _, user_share = _create_shared_expense_for_user(
            db_session, payer=partner, partner=user, amount=Decimal("100.00")
        )

        # First settlement: partial (20 of 50)
        service.create_settlement(
            from_user=user,
            to_user=partner,
            amount=Decimal("20.00"),
            settlement_date=date(2024, 3, 1),
        )

        db_session.refresh(user_share)
        assert user_share.settled is False

        # Second settlement: remaining (30 of 50)
        service.create_settlement(
            from_user=user,
            to_user=partner,
            amount=Decimal("30.00"),
            settlement_date=date(2024, 3, 15),
        )

        db_session.refresh(user_share)
        assert user_share.settled is True
        assert user_share.settled_at is not None

    def test_settlement_spans_multiple_shares(
        self, db_session, service, user, partner
    ):
        """A single settlement can cover multiple shares."""
        # Older: partner paid 40 (user's share = 20)
        older_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        _, _, user_share_1 = _create_shared_expense_for_user(
            db_session, payer=partner, partner=user,
            amount=Decimal("40.00"), created_at=older_ts,
        )

        # Newer: partner paid 60 (user's share = 30)
        newer_ts = datetime(2024, 2, 1, tzinfo=timezone.utc)
        _, _, user_share_2 = _create_shared_expense_for_user(
            db_session, payer=partner, partner=user,
            amount=Decimal("60.00"), created_at=newer_ts,
        )

        # Settle 50 (covers all of share_1=20 and all of share_2=30)
        settlement = service.create_settlement(
            from_user=user,
            to_user=partner,
            amount=Decimal("50.00"),
            settlement_date=date(2024, 3, 15),
        )

        db_session.refresh(user_share_1)
        db_session.refresh(user_share_2)

        # Both should be fully settled
        assert user_share_1.settled is True
        assert user_share_1.settled_at is not None
        assert user_share_2.settled is True
        assert user_share_2.settled_at is not None

        # Two allocations should exist
        allocations = SettlementAllocation.query.filter_by(
            settlement_id=settlement.id
        ).order_by(SettlementAllocation.amount.asc()).all()
        assert len(allocations) == 2

    def test_settlement_partial_on_second_share(
        self, db_session, service, user, partner
    ):
        """Settlement fully covers first share and partially covers second."""
        # Older: partner paid 40 (user's share = 20)
        older_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        _, _, user_share_1 = _create_shared_expense_for_user(
            db_session, payer=partner, partner=user,
            amount=Decimal("40.00"), created_at=older_ts,
        )

        # Newer: partner paid 100 (user's share = 50)
        newer_ts = datetime(2024, 2, 1, tzinfo=timezone.utc)
        _, _, user_share_2 = _create_shared_expense_for_user(
            db_session, payer=partner, partner=user,
            amount=Decimal("100.00"), created_at=newer_ts,
        )

        # Settle 35 (covers share_1=20 fully, share_2=15 partially)
        settlement = service.create_settlement(
            from_user=user,
            to_user=partner,
            amount=Decimal("35.00"),
            settlement_date=date(2024, 3, 15),
        )

        db_session.refresh(user_share_1)
        db_session.refresh(user_share_2)

        assert user_share_1.settled is True
        assert user_share_2.settled is False

        # Check allocation amounts
        allocations = SettlementAllocation.query.filter_by(
            settlement_id=settlement.id
        ).order_by(SettlementAllocation.shared_expense_share_id.asc()).all()
        assert len(allocations) == 2
        alloc_amounts = {a.shared_expense_share_id: a.amount for a in allocations}
        assert alloc_amounts[user_share_1.id] == Decimal("20.00")
        assert alloc_amounts[user_share_2.id] == Decimal("15.00")


class TestExcessSettlement:
    """Tests for settlement excess handling (Req 12.5)."""

    def test_excess_settlement_no_error(
        self, db_session, service, user, partner
    ):
        """Excess settlement amount is recorded without error."""
        # Partner paid 40, user's share = 20
        _create_shared_expense_for_user(
            db_session, payer=partner, partner=user, amount=Decimal("40.00")
        )

        # Settle 50 (20 allocated, 30 excess)
        settlement = service.create_settlement(
            from_user=user,
            to_user=partner,
            amount=Decimal("50.00"),
            settlement_date=date(2024, 3, 15),
        )

        assert settlement.amount == Decimal("50.00")
        # Only one allocation (for the 20 share)
        allocations = SettlementAllocation.query.filter_by(
            settlement_id=settlement.id
        ).all()
        assert len(allocations) == 1
        assert allocations[0].amount == Decimal("20.00")

    def test_excess_with_no_outstanding_shares(
        self, db_session, service, user, partner
    ):
        """Settlement with no outstanding shares creates no allocations."""
        settlement = service.create_settlement(
            from_user=user,
            to_user=partner,
            amount=Decimal("100.00"),
            settlement_date=date(2024, 3, 15),
        )

        assert settlement.amount == Decimal("100.00")
        allocations = SettlementAllocation.query.filter_by(
            settlement_id=settlement.id
        ).all()
        assert len(allocations) == 0


class TestDeleteSettlement:
    """Tests for settlement deletion with allocation reversal (Req 12.6)."""

    def test_delete_settlement_reverses_allocations(
        self, db_session, service, user, partner
    ):
        """Deleting a settlement reverses all its allocations."""
        # Partner paid 60, user's share = 30
        _, _, user_share = _create_shared_expense_for_user(
            db_session, payer=partner, partner=user, amount=Decimal("60.00")
        )

        # Create settlement that fully covers the share
        settlement = service.create_settlement(
            from_user=user,
            to_user=partner,
            amount=Decimal("30.00"),
            settlement_date=date(2024, 3, 15),
        )

        db_session.refresh(user_share)
        assert user_share.settled is True

        # Delete the settlement
        service.delete_settlement(settlement.id, user)

        db_session.refresh(user_share)
        assert user_share.settled is False
        assert user_share.settled_at is None

    def test_delete_settlement_removes_settlement_record(
        self, db_session, service, user, partner
    ):
        """Deleting a settlement removes the Settlement record."""
        _create_shared_expense_for_user(
            db_session, payer=partner, partner=user, amount=Decimal("60.00")
        )

        settlement = service.create_settlement(
            from_user=user,
            to_user=partner,
            amount=Decimal("30.00"),
            settlement_date=date(2024, 3, 15),
        )
        settlement_id = settlement.id

        service.delete_settlement(settlement_id, user)

        assert db.session.get(Settlement, settlement_id) is None

    def test_delete_settlement_removes_allocations(
        self, db_session, service, user, partner
    ):
        """Deleting a settlement removes all SettlementAllocation records."""
        _create_shared_expense_for_user(
            db_session, payer=partner, partner=user, amount=Decimal("60.00")
        )

        settlement = service.create_settlement(
            from_user=user,
            to_user=partner,
            amount=Decimal("30.00"),
            settlement_date=date(2024, 3, 15),
        )
        settlement_id = settlement.id

        service.delete_settlement(settlement_id, user)

        allocations = SettlementAllocation.query.filter_by(
            settlement_id=settlement_id
        ).all()
        assert len(allocations) == 0

    def test_delete_settlement_not_found_raises(
        self, db_session, service, user
    ):
        """Deleting a non-existent settlement raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            service.delete_settlement(9999, user)

    def test_delete_settlement_unauthorized_raises(
        self, db_session, service, user, partner
    ):
        """Deleting a settlement by a non-involved user raises ValueError."""
        _create_shared_expense_for_user(
            db_session, payer=partner, partner=user, amount=Decimal("60.00")
        )

        settlement = service.create_settlement(
            from_user=user,
            to_user=partner,
            amount=Decimal("30.00"),
            settlement_date=date(2024, 3, 15),
        )

        # Create a third user (not involved)
        other_user = UserFactory()
        db_session.flush()

        with pytest.raises(ValueError, match="does not have access"):
            service.delete_settlement(settlement.id, other_user)

    def test_delete_settlement_by_to_user(
        self, db_session, service, user, partner
    ):
        """The to_user can also delete a settlement."""
        _create_shared_expense_for_user(
            db_session, payer=partner, partner=user, amount=Decimal("60.00")
        )

        settlement = service.create_settlement(
            from_user=user,
            to_user=partner,
            amount=Decimal("30.00"),
            settlement_date=date(2024, 3, 15),
        )
        settlement_id = settlement.id

        # Partner (to_user) deletes the settlement
        service.delete_settlement(settlement_id, partner)

        assert db.session.get(Settlement, settlement_id) is None
