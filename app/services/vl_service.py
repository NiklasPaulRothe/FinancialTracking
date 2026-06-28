"""VL (Vermögenswirksame Leistungen) service for Haushaltsbuch.

Implements monthly contribution log generation, ETF buy on linked position,
lock-up tracking, Sparzulage calculation, and stale price checking.

Validates: Requirements 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 16.8
"""

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import NamedTuple

from sqlalchemy import select, extract

from app.extensions import db
from app.models.bav import VL, VLContributionLog
from app.models.etf import ETFPosition, ETFTransaction, ETFTransactionType
from app.models.user import User


# Stale price threshold in days (aligned with ETF service, Req 16.3)
STALE_PRICE_THRESHOLD_DAYS = 3


class VLNotification(NamedTuple):
    """A notification generated during VL processing."""

    vl_id: int
    notification_type: str  # "vl_contribution_executed" or "vl_price_stale"
    message: str


class SparzulageResult(NamedTuple):
    """Result of Sparzulage (state bonus) calculation for a VL contract."""

    annual_contributions: Decimal
    annual_eligible_max: Decimal
    eligible_amount: Decimal
    sparzulage_rate: Decimal
    expected_bonus: Decimal


class VLService:
    """Service for VL contract management and contribution processing.

    Validates: Requirements 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 16.8
    """

    # -------------------------------------------------------------------------
    # Monthly contribution processing
    # -------------------------------------------------------------------------

    def generate_monthly_contributions(
        self, user: User, target_month: date | None = None
    ) -> tuple[list[VLContributionLog], list[VLNotification]]:
        """Generate monthly contribution logs for all active VL contracts.

        Validates: Requirements 16.2, 16.3, 16.4

        For each active VL contract with start_date on or before the target month:
        1. Check idempotency (skip if log for month already exists).
        2. If linked to an ETF position, check for stale price (>3 days old).
           - If stale: skip contribution, generate notification.
        3. If price is fresh (or no ETF link): create VLContributionLog.
        4. If linked to ETF: create buy ETFTransaction with shares =
           total_contribution_monthly / current_price (6 decimal places).
           linked_account_id is set to null (Req 16.4: employer pays directly).

        Args:
            user: The user whose VL contracts to process.
            target_month: The month to generate contributions for (first of month).
                         Defaults to the 1st of the current month.

        Returns:
            Tuple of (created_logs, notifications).
        """
        if target_month is None:
            today = date.today()
            target_month = date(today.year, today.month, 1)
        else:
            # Normalize to first of month
            target_month = date(target_month.year, target_month.month, 1)

        # Find all active VL contracts for this user with start_date <= target_month
        contracts = VL.query.filter(
            VL.user_id == user.id,
            VL.active == True,  # noqa: E712
            VL.start_date <= target_month,
        ).all()

        created_logs: list[VLContributionLog] = []
        notifications: list[VLNotification] = []

        for contract in contracts:
            # Check idempotency: skip if entry for this month already exists
            existing = VLContributionLog.query.filter(
                VLContributionLog.vl_id == contract.id,
                VLContributionLog.month == target_month,
            ).first()

            if existing is not None:
                continue

            etf_transaction: ETFTransaction | None = None

            # If linked to an ETF position, handle price check and buy
            if contract.etf_position_id is not None:
                position = db.session.get(ETFPosition, contract.etf_position_id)

                # Check for stale price (Req 16.3)
                if self._is_price_stale(position, target_month):
                    notifications.append(
                        VLNotification(
                            vl_id=contract.id,
                            notification_type="vl_price_stale",
                            message=(
                                f"VL contribution for contract #{contract.id} "
                                f"skipped: ETF price for "
                                f"'{position.ticker}.{position.exchange_suffix}' "
                                f"is stale (not updated within "
                                f"{STALE_PRICE_THRESHOLD_DAYS} days). "
                                f"Update the price to process the contribution."
                            ),
                        )
                    )
                    continue

                # Price is fresh — create ETF buy transaction
                current_price = position.current_price
                amount = contract.total_contribution_monthly

                # Calculate shares: amount / current_price rounded to 6 decimals
                shares = (amount / current_price).quantize(
                    Decimal("0.000001"), rounding=ROUND_HALF_UP
                )

                total_amount = (shares * current_price).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )

                # Create ETF buy transaction (linked_account_id=None per Req 16.4)
                etf_transaction = ETFTransaction(
                    position_id=position.id,
                    type=ETFTransactionType.buy,
                    shares_quantity=shares,
                    price_per_share=current_price,
                    total_amount=total_amount,
                    linked_account_id=None,
                    date=target_month,
                    user_id=user.id,
                )
                db.session.add(etf_transaction)
                db.session.flush()

                # Update position: increase shares, recalculate average buy price
                existing_shares = position.shares
                old_avg = position.average_buy_price
                if existing_shares + shares > 0:
                    new_avg = (
                        (existing_shares * old_avg) + (shares * current_price)
                    ) / (existing_shares + shares)
                    position.average_buy_price = new_avg.quantize(
                        Decimal("0.000001"), rounding=ROUND_HALF_UP
                    )
                position.shares += shares

            # Create VL contribution log entry
            log = VLContributionLog(
                vl_id=contract.id,
                month=target_month,
                amount=contract.total_contribution_monthly,
                etf_transaction_id=(
                    etf_transaction.id if etf_transaction else None
                ),
            )
            db.session.add(log)
            created_logs.append(log)

            notifications.append(
                VLNotification(
                    vl_id=contract.id,
                    notification_type="vl_contribution_executed",
                    message=(
                        f"VL contribution of {contract.total_contribution_monthly}€ "
                        f"logged for {target_month.strftime('%B %Y')}."
                    ),
                )
            )

        if created_logs:
            db.session.flush()

        return created_logs, notifications

    # -------------------------------------------------------------------------
    # Sparzulage calculation
    # -------------------------------------------------------------------------

    def calculate_sparzulage(
        self, vl: VL, year: int | None = None
    ) -> SparzulageResult:
        """Calculate the expected Arbeitnehmer-Sparzulage for a VL contract.

        Validates: Requirement 16.7

        Sparzulage = sparzulage_rate × min(annual_contributions, annual_eligible_max)

        The annual_contributions are the sum of all VLContributionLog amounts
        for the given calendar year.

        Args:
            vl: The VL contract to calculate for.
            year: The calendar year. Defaults to the current year.

        Returns:
            SparzulageResult with the calculation breakdown.
        """
        if year is None:
            year = date.today().year

        # Sum all contributions for this VL contract in the given year
        year_start = date(year, 1, 1)
        year_end = date(year, 12, 31)

        logs = VLContributionLog.query.filter(
            VLContributionLog.vl_id == vl.id,
            VLContributionLog.month >= year_start,
            VLContributionLog.month <= year_end,
        ).all()

        annual_contributions = sum(
            (log.amount for log in logs), Decimal("0.00")
        )

        # Sparzulage = rate × min(annual_contributions, annual_eligible_max)
        eligible_amount = min(annual_contributions, vl.annual_eligible_max)
        expected_bonus = (vl.sparzulage_rate * eligible_amount).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        return SparzulageResult(
            annual_contributions=annual_contributions,
            annual_eligible_max=vl.annual_eligible_max,
            eligible_amount=eligible_amount,
            sparzulage_rate=vl.sparzulage_rate,
            expected_bonus=expected_bonus,
        )

    # -------------------------------------------------------------------------
    # Lock-up tracking
    # -------------------------------------------------------------------------

    def is_locked(self, vl: VL, reference_date: date | None = None) -> bool:
        """Check if a VL contract is still in its lock-up period.

        Validates: Requirement 16.5

        Args:
            vl: The VL contract to check.
            reference_date: The date to check against. Defaults to today.

        Returns:
            True if the contract's lock_up_end_date is in the future.
        """
        if reference_date is None:
            reference_date = date.today()
        return vl.lock_up_end_date > reference_date

    def get_remaining_lockup(
        self, vl: VL, reference_date: date | None = None
    ) -> tuple[int, int]:
        """Get remaining lock-up duration in years and months.

        Validates: Requirement 16.5

        Args:
            vl: The VL contract.
            reference_date: The date to calculate from. Defaults to today.

        Returns:
            Tuple of (years, months) remaining. Returns (0, 0) if not locked.
        """
        if reference_date is None:
            reference_date = date.today()

        if vl.lock_up_end_date <= reference_date:
            return (0, 0)

        # Calculate difference in months
        total_months = (
            (vl.lock_up_end_date.year - reference_date.year) * 12
            + vl.lock_up_end_date.month - reference_date.month
        )
        # If the day hasn't passed yet in the current month, subtract one
        if vl.lock_up_end_date.day < reference_date.day:
            total_months -= 1

        if total_months < 0:
            total_months = 0

        years = total_months // 12
        months = total_months % 12
        return (years, months)

    # -------------------------------------------------------------------------
    # Stale price check
    # -------------------------------------------------------------------------

    def _is_price_stale(self, position: ETFPosition, reference_date: date) -> bool:
        """Check if a position's current price is stale (>3 days old).

        Validates: Requirement 16.3

        A price is considered stale if:
        - current_price is None (never fetched), OR
        - current_price_updated_at is more than STALE_PRICE_THRESHOLD_DAYS
          days before the reference date.

        Args:
            position: The ETF position to check.
            reference_date: The reference date for staleness calculation.

        Returns:
            True if the price is stale and contribution should be skipped.
        """
        if position.current_price is None:
            return True

        if position.current_price_updated_at is None:
            return True

        # Convert updated_at datetime to date for comparison
        updated_date = position.current_price_updated_at
        if hasattr(updated_date, "date") and callable(updated_date.date):
            updated_date = updated_date.date()

        days_since_update = (reference_date - updated_date).days
        return days_since_update > STALE_PRICE_THRESHOLD_DAYS
