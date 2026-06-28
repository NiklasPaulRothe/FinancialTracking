"""ETF service for Haushaltsbuch.

Implements ETF position management, price fetching, buy/sell transaction
recording, and savings plan execution logic.

Validates: Requirements 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8,
           13.9, 13.10, 14.1, 14.2, 14.3, 14.4, 14.5
"""

from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import NamedTuple

from sqlalchemy import select

from app.extensions import db
from app.exceptions import InsufficientShares, StalePriceError
from app.models.account import Account
from app.models.etf import (
    ETFPosition,
    ETFSavingsPlan,
    ETFTransaction,
    ETFTransactionType,
)
from app.models.transaction import RecurringRule
from app.models.user import User
from app.services.recurring_service import RecurringService


# Stale price threshold in days (Requirement 14.3)
STALE_PRICE_THRESHOLD_DAYS = 3


class SavingsPlanNotification(NamedTuple):
    """A notification generated during savings plan processing."""

    plan_id: int
    position_id: int
    notification_type: str  # "etf_savings_plan_executed" or "etf_price_stale"
    message: str


class ETFService:
    """Service for ETF position management and savings plan execution.

    Validates: Requirements 13.1-13.10, 14.1-14.5
    """

    def __init__(self) -> None:
        self.recurring_service = RecurringService()

    # -------------------------------------------------------------------------
    # Buy / Sell operations
    # -------------------------------------------------------------------------

    def record_buy(
        self,
        position_id: int,
        shares_quantity: Decimal,
        price_per_share: Decimal,
        user: User,
        linked_account_id: int | None = None,
        transaction_date: date | None = None,
    ) -> ETFTransaction:
        """Record a buy transaction for an ETF position.

        Validates: Requirements 13.5, 13.8

        Increases shares on the position and recalculates average_buy_price as:
        ((existing_shares * old_avg) + (new_shares * price_per_share)) /
        (existing_shares + new_shares)

        If linked_account_id is provided, deducts total_amount from that account.

        Args:
            position_id: The ETF position to buy into.
            shares_quantity: Number of shares purchased.
            price_per_share: Price per share for this transaction.
            user: The user making the purchase.
            linked_account_id: Optional account to deduct from.
            transaction_date: Date of the transaction. Defaults to today.

        Returns:
            The newly created ETFTransaction.
        """
        if transaction_date is None:
            transaction_date = date.today()

        position = db.session.get(ETFPosition, position_id)
        if position is None:
            raise ValueError(f"ETF position with id {position_id} not found.")

        total_amount = (shares_quantity * price_per_share).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # Recalculate weighted average buy price (Req 13.5)
        existing_shares = position.shares
        old_avg = position.average_buy_price
        new_avg = (
            (existing_shares * old_avg) + (shares_quantity * price_per_share)
        ) / (existing_shares + shares_quantity)
        position.average_buy_price = new_avg.quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )
        position.shares += shares_quantity

        # Deduct from linked account if provided (Req 13.8)
        if linked_account_id is not None:
            account = self._lock_account(linked_account_id)
            account.balance -= total_amount

        # Create the ETF transaction record
        etf_txn = ETFTransaction(
            position_id=position_id,
            type=ETFTransactionType.buy,
            shares_quantity=shares_quantity,
            price_per_share=price_per_share,
            total_amount=total_amount,
            linked_account_id=linked_account_id,
            date=transaction_date,
            user_id=user.id,
        )
        db.session.add(etf_txn)
        db.session.flush()

        return etf_txn

    def record_sell(
        self,
        position_id: int,
        shares_quantity: Decimal,
        price_per_share: Decimal,
        user: User,
        linked_account_id: int | None = None,
        transaction_date: date | None = None,
    ) -> ETFTransaction:
        """Record a sell transaction for an ETF position.

        Validates: Requirements 13.6, 13.7, 13.9

        Decreases shares on the position using average cost method (does NOT
        change average_buy_price). Rejects if shares_quantity > position.shares.

        If linked_account_id is provided, adds total_amount to that account.

        Args:
            position_id: The ETF position to sell from.
            shares_quantity: Number of shares to sell.
            price_per_share: Price per share for this sale.
            user: The user making the sale.
            linked_account_id: Optional account to credit proceeds to.
            transaction_date: Date of the transaction. Defaults to today.

        Returns:
            The newly created ETFTransaction.

        Raises:
            InsufficientShares: If selling more than available.
        """
        if transaction_date is None:
            transaction_date = date.today()

        position = db.session.get(ETFPosition, position_id)
        if position is None:
            raise ValueError(f"ETF position with id {position_id} not found.")

        # Check sufficient shares (Req 13.7)
        if shares_quantity > position.shares:
            raise InsufficientShares(
                position_id=position_id,
                available_shares=position.shares,
                requested_shares=shares_quantity,
            )

        total_amount = (shares_quantity * price_per_share).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # Decrease shares, keep average_buy_price unchanged (Req 13.6)
        position.shares -= shares_quantity

        # Credit to linked account if provided (Req 13.9)
        if linked_account_id is not None:
            account = self._lock_account(linked_account_id)
            account.balance += total_amount

        # Create the ETF transaction record
        etf_txn = ETFTransaction(
            position_id=position_id,
            type=ETFTransactionType.sell,
            shares_quantity=shares_quantity,
            price_per_share=price_per_share,
            total_amount=total_amount,
            linked_account_id=linked_account_id,
            date=transaction_date,
            user_id=user.id,
        )
        db.session.add(etf_txn)
        db.session.flush()

        return etf_txn

    # -------------------------------------------------------------------------
    # Savings Plan Execution
    # -------------------------------------------------------------------------

    def process_savings_plans(
        self, user: User, today: date | None = None
    ) -> tuple[list[ETFTransaction], list[SavingsPlanNotification]]:
        """Process all due ETF savings plans for a user.

        Validates: Requirements 14.2, 14.3, 14.4, 14.5

        For each active savings plan whose recurring rule is due:
        1. Check if position's current_price is stale (>3 days old).
           - If stale: pause execution, do NOT advance recurring rule's
             next_due_date, generate notification.
        2. If price is fresh: calculate shares = amount / current_price
           (rounded to 6 decimals), create buy ETFTransaction, deduct from
           linked account, then advance the recurring rule's next_due_date.

        Deactivating a savings plan (active=False) stops future executions
        but preserves the recurring rule (Req 14.5).

        On price refresh, the savings plan resumes on the NEXT scheduled
        date without retroactive catch-up (Req 14.4).

        Args:
            user: The user whose savings plans should be processed.
            today: Override for current date (for testing). Defaults to date.today().

        Returns:
            A tuple of (generated_etf_transactions, notifications).
        """
        if today is None:
            today = date.today()

        # Find active savings plans for this user
        plans = ETFSavingsPlan.query.filter(
            ETFSavingsPlan.user_id == user.id,
            ETFSavingsPlan.active == True,  # noqa: E712
        ).all()

        generated: list[ETFTransaction] = []
        notifications: list[SavingsPlanNotification] = []

        for plan in plans:
            rule = plan.recurring_rule
            position = plan.position

            # Skip if the recurring rule itself is inactive (Req 14.5)
            if not rule.active:
                continue

            # Only process if the rule is due (next_due_date <= today)
            if rule.next_due_date > today:
                continue

            # Check for stale price (Req 14.3)
            if self._is_price_stale(position, today):
                days_stale = self._days_since_price_update(position, today)
                # Pause: do NOT advance next_due_date
                notifications.append(
                    SavingsPlanNotification(
                        plan_id=plan.id,
                        position_id=position.id,
                        notification_type="etf_price_stale",
                        message=(
                            f"ETF savings plan for '{position.name}' "
                            f"({position.ticker}.{position.exchange_suffix}) paused: "
                            f"price is {days_stale} days stale (threshold: "
                            f"{STALE_PRICE_THRESHOLD_DAYS} days). "
                            f"Update the price to resume execution."
                        ),
                    )
                )
                continue

            # Price is fresh — execute the savings plan purchase
            # Process only the current due date (no catch-up for missed dates)
            # This ensures Req 14.4: resume on NEXT scheduled date only
            amount = rule.amount
            current_price = position.current_price

            # Calculate shares: amount / current_price rounded to 6 decimals (Req 14.2)
            shares = (amount / current_price).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP
            )

            total_amount = (shares * current_price).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            # Deduct from linked account
            account = self._lock_account(plan.linked_account_id)
            account.balance -= total_amount

            # Create the ETF buy transaction (Req 14.2)
            etf_txn = ETFTransaction(
                position_id=position.id,
                type=ETFTransactionType.buy,
                shares_quantity=shares,
                price_per_share=current_price,
                total_amount=total_amount,
                linked_account_id=plan.linked_account_id,
                date=today,
                user_id=user.id,
            )
            db.session.add(etf_txn)
            db.session.flush()

            # Update position: increase shares, recalculate average buy price
            existing_shares = position.shares
            old_avg = position.average_buy_price
            new_avg = (
                (existing_shares * old_avg) + (shares * current_price)
            ) / (existing_shares + shares)
            position.average_buy_price = new_avg.quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP
            )
            position.shares += shares

            generated.append(etf_txn)

            # Advance the recurring rule's next_due_date (only on success)
            self.recurring_service.advance_next_due_date(rule)

            notifications.append(
                SavingsPlanNotification(
                    plan_id=plan.id,
                    position_id=position.id,
                    notification_type="etf_savings_plan_executed",
                    message=(
                        f"ETF savings plan executed: purchased {shares} shares "
                        f"of {position.ticker}.{position.exchange_suffix} "
                        f"at {current_price} per share (total: {total_amount})."
                    ),
                )
            )

        db.session.commit()
        return generated, notifications

    def _is_price_stale(self, position: ETFPosition, today: date) -> bool:
        """Check if a position's current price is stale (>3 days old).

        Validates: Requirement 14.3

        A price is considered stale if:
        - current_price is None (never fetched), OR
        - current_price_updated_at is more than STALE_PRICE_THRESHOLD_DAYS
          days before today.

        Args:
            position: The ETF position to check.
            today: The reference date for staleness calculation.

        Returns:
            True if the price is stale and execution should be paused.
        """
        if position.current_price is None:
            return True

        if position.current_price_updated_at is None:
            return True

        # Convert updated_at datetime to date for comparison
        updated_date = position.current_price_updated_at
        if hasattr(updated_date, "date"):
            updated_date = updated_date.date()

        days_since_update = (today - updated_date).days
        return days_since_update > STALE_PRICE_THRESHOLD_DAYS

    def _days_since_price_update(self, position: ETFPosition, today: date) -> int:
        """Calculate the number of days since the last price update.

        Args:
            position: The ETF position to check.
            today: The reference date.

        Returns:
            Number of days since the last update, or -1 if never updated.
        """
        if position.current_price_updated_at is None:
            return -1

        updated_date = position.current_price_updated_at
        if hasattr(updated_date, "date"):
            updated_date = updated_date.date()

        return (today - updated_date).days

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
