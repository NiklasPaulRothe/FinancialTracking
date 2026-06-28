"""Settlement service for Haushaltsbuch.

Implements shared expense settlement with FIFO allocation, net balance
computation, and settlement deletion with allocation reversal.

Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5, 12.6
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.exceptions import InvalidSettlementError
from app.models.transaction import (
    Settlement,
    SettlementAllocation,
    SharedExpense,
    SharedExpenseShare,
)
from app.models.user import User
from app.services.audit_service import AuditService


class SettlementService:
    """Service class encapsulating settlement business logic."""

    def __init__(self) -> None:
        self._audit_service = AuditService()

    def get_net_balance(self, user: User) -> Decimal:
        """Compute net settlement balance for the given user.

        Validates: Requirement 12.1

        Net balance = sum of unsettled SharedExpenseShares owed TO this user
                    - sum of unsettled SharedExpenseShares owed BY this user
                    - settlements already made FROM this user
                    + settlements already received BY this user

        The net balance represents how much the partner owes this user.
        A positive value means the partner owes this user money.
        A negative value means this user owes the partner money (credit).

        Args:
            user: The user to compute the net balance for.

        Returns:
            The net settlement balance as a Decimal.
        """
        # Find the partner
        partner = User.query.filter(User.id != user.id).first()
        if partner is None:
            return Decimal("0.00")

        # Sum of unsettled shares where the PARTNER owes (partner's shares
        # on expenses paid by this user). These are shares assigned to the
        # partner for shared expenses where this user paid.
        # The "owed to user" is the partner's unsettled share amounts on
        # transactions paid by this user.
        partner_owes = (
            db.session.query(func.coalesce(func.sum(SharedExpenseShare.amount), Decimal("0.00")))
            .join(SharedExpense, SharedExpenseShare.shared_expense_id == SharedExpense.id)
            .join(
                db.session.query(db.literal(True)).subquery(),
                db.literal(True),
            )
            .filter(
                SharedExpenseShare.user_id == partner.id,
                SharedExpenseShare.settled == False,  # noqa: E712
                SharedExpense.transaction.has(user_id=user.id),
            )
            .scalar()
        ) or Decimal("0.00")

        # Sum of unsettled shares where THIS USER owes (user's shares on
        # expenses paid by the partner).
        user_owes = (
            db.session.query(func.coalesce(func.sum(SharedExpenseShare.amount), Decimal("0.00")))
            .join(SharedExpense, SharedExpenseShare.shared_expense_id == SharedExpense.id)
            .filter(
                SharedExpenseShare.user_id == user.id,
                SharedExpenseShare.settled == False,  # noqa: E712
                SharedExpense.transaction.has(user_id=partner.id),
            )
            .scalar()
        ) or Decimal("0.00")

        # Settlements from user to partner (reduces what partner owes)
        settlements_made = (
            db.session.query(func.coalesce(func.sum(Settlement.amount), Decimal("0.00")))
            .filter(
                Settlement.from_user_id == user.id,
                Settlement.to_user_id == partner.id,
            )
            .scalar()
        ) or Decimal("0.00")

        # Settlements from partner to user (reduces what user owes)
        settlements_received = (
            db.session.query(func.coalesce(func.sum(Settlement.amount), Decimal("0.00")))
            .filter(
                Settlement.from_user_id == partner.id,
                Settlement.to_user_id == user.id,
            )
            .scalar()
        ) or Decimal("0.00")

        # Net: what partner owes user - what user owes partner
        # Adjusted by settlements already made
        net = (partner_owes - settlements_made) - (user_owes - settlements_received)
        return net

    def create_settlement(
        self,
        from_user: User,
        to_user: User,
        amount: Decimal,
        settlement_date: date,
    ) -> Settlement:
        """Create a settlement and auto-allocate using FIFO.

        Validates: Requirements 12.2, 12.3, 12.4, 12.5

        Allocates the settlement amount to outstanding SharedExpenseShares
        belonging to from_user on shared expenses paid by to_user, ordered
        by creation date (oldest first - FIFO).

        Full coverage: if allocation >= share's remaining unsettled amount,
        set settled=True and record settled_at.
        Partial coverage: create allocation for partial amount, settled stays False.
        Excess: if amount exceeds all outstanding shares, excess becomes credit
        (negative net balance for the paying user).

        Args:
            from_user: The user making the payment.
            to_user: The user receiving the payment.
            amount: The settlement amount (must be > 0).
            settlement_date: The date of the settlement.

        Returns:
            The created Settlement instance.

        Raises:
            InvalidSettlementError: If from_user equals to_user.
        """
        if from_user.id == to_user.id:
            raise InvalidSettlementError(user_id=from_user.id)

        # Create the settlement record
        settlement = Settlement(
            amount=amount,
            date=settlement_date,
            from_user_id=from_user.id,
            to_user_id=to_user.id,
        )
        db.session.add(settlement)
        db.session.flush()  # Get the settlement ID

        # FIFO allocation: find outstanding shares for from_user on expenses
        # paid by to_user, ordered by created_at ASC (oldest first)
        outstanding_shares = (
            SharedExpenseShare.query
            .join(SharedExpense, SharedExpenseShare.shared_expense_id == SharedExpense.id)
            .filter(
                SharedExpenseShare.user_id == from_user.id,
                SharedExpenseShare.settled == False,  # noqa: E712
                SharedExpense.transaction.has(user_id=to_user.id),
            )
            .order_by(SharedExpense.created_at.asc(), SharedExpenseShare.id.asc())
            .all()
        )

        remaining_amount = amount

        for share in outstanding_shares:
            if remaining_amount <= Decimal("0.00"):
                break

            # Calculate the remaining unsettled amount for this share
            # (share.amount minus any existing partial allocations)
            existing_allocations_sum = (
                db.session.query(
                    func.coalesce(func.sum(SettlementAllocation.amount), Decimal("0.00"))
                )
                .filter(SettlementAllocation.shared_expense_share_id == share.id)
                .scalar()
            ) or Decimal("0.00")

            remaining_share_amount = share.amount - existing_allocations_sum

            if remaining_share_amount <= Decimal("0.00"):
                continue

            # Determine allocation amount
            allocation_amount = min(remaining_amount, remaining_share_amount)

            # Create the allocation
            allocation = SettlementAllocation(
                settlement_id=settlement.id,
                shared_expense_share_id=share.id,
                amount=allocation_amount,
            )
            db.session.add(allocation)

            remaining_amount -= allocation_amount

            # Check if the share is now fully covered
            total_allocated = existing_allocations_sum + allocation_amount
            if total_allocated >= share.amount:
                # Full coverage: mark as settled
                share.settled = True
                share.settled_at = datetime.now(timezone.utc)

        # If remaining_amount > 0 after all shares are covered, this excess
        # becomes credit for the paying user (recorded implicitly as part of
        # the settlement amount exceeding outstanding shares - Req 12.5)

        # Audit log (Req 22.1)
        self._audit_service.log_change(
            action="create",
            model="Settlement",
            record_id=settlement.id,
            old_values=None,
            new_values={
                "amount": str(settlement.amount),
                "from_user_id": settlement.from_user_id,
                "to_user_id": settlement.to_user_id,
                "date": settlement.date.isoformat(),
            },
            user_id=from_user.id,
        )

        db.session.commit()
        return settlement

    def delete_settlement(self, settlement_id: int, user: User) -> None:
        """Delete a settlement and reverse all its allocations.

        Validates: Requirement 12.6

        Finds all SettlementAllocations for the settlement, reverses them
        (sets affected SharedExpenseShare settled=False, clears settled_at),
        then deletes the Settlement record.

        Args:
            settlement_id: ID of the settlement to delete.
            user: The user requesting deletion (must be from_user or to_user).

        Raises:
            ValueError: If settlement not found or user lacks access.
        """
        settlement = db.session.get(Settlement, settlement_id)
        if settlement is None:
            raise ValueError(f"Settlement with id {settlement_id} not found.")

        # Verify user is involved in this settlement
        if settlement.from_user_id != user.id and settlement.to_user_id != user.id:
            raise ValueError(
                f"User {user.username} does not have access to settlement {settlement_id}."
            )

        # Reverse all allocations
        allocations = SettlementAllocation.query.filter_by(
            settlement_id=settlement.id
        ).all()

        for allocation in allocations:
            share = db.session.get(SharedExpenseShare, allocation.shared_expense_share_id)
            if share is not None:
                # Reset settled status
                share.settled = False
                share.settled_at = None

        # Audit log (Req 22.1)
        self._audit_service.log_change(
            action="delete",
            model="Settlement",
            record_id=settlement.id,
            old_values={
                "amount": str(settlement.amount),
                "from_user_id": settlement.from_user_id,
                "to_user_id": settlement.to_user_id,
                "date": settlement.date.isoformat(),
            },
            new_values=None,
            user_id=user.id,
        )

        # Delete the settlement (cascades to allocations via relationship)
        db.session.delete(settlement)
        db.session.commit()
