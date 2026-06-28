"""BaV (Betriebliche Altersvorsorge) service for Haushaltsbuch.

Implements monthly contribution log generation and net cost calculation
for employer pension contracts.

Validates: Requirements 15.1, 15.2, 15.3, 15.4, 15.5
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import NamedTuple

from sqlalchemy import select

from app.extensions import db
from app.models.bav import BaV, BaVContributionLog, BaVType
from app.models.user import User


class BaVNetCost(NamedTuple):
    """Net cost breakdown for a bAV contract's employee contribution."""

    gross_contribution: Decimal
    marginal_tax_rate: Decimal
    social_security_rate: Decimal
    net_cost: Decimal


class BaVService:
    """Service for bAV contract management and contribution log generation.

    Validates: Requirements 15.1, 15.2, 15.3, 15.4, 15.5
    """

    # -------------------------------------------------------------------------
    # Net cost calculation
    # -------------------------------------------------------------------------

    def calculate_net_cost(
        self, employee_contribution: Decimal, user: User
    ) -> BaVNetCost:
        """Calculate the net cost of the employee bAV contribution.

        Validates: Requirement 15.2

        Net cost = employee_contribution × (1 − marginal_tax_rate − social_security_rate)

        The marginal_tax_rate and social_security_rate are user-configurable
        decimal values stored in the user's profile settings.

        Args:
            employee_contribution: The monthly employee contribution amount.
            user: The user whose tax/social rates to use.

        Returns:
            BaVNetCost with the breakdown of the calculation.
        """
        tax_rate = Decimal(str(user.marginal_tax_rate))
        social_rate = Decimal(str(user.social_security_rate))

        factor = Decimal("1") - tax_rate - social_rate
        net_cost = (employee_contribution * factor).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        return BaVNetCost(
            gross_contribution=employee_contribution,
            marginal_tax_rate=tax_rate,
            social_security_rate=social_rate,
            net_cost=net_cost,
        )

    # -------------------------------------------------------------------------
    # Monthly log generation
    # -------------------------------------------------------------------------

    def generate_monthly_logs(
        self, user: User, target_month: date | None = None
    ) -> list[BaVContributionLog]:
        """Generate monthly contribution logs for all active bAV contracts.

        Validates: Requirements 15.3, 15.4, 15.5

        For each active bAV contract (start_date on or before the 1st of the
        target month), creates a BaVContributionLog entry. Skips if an entry
        for that contract and month already exists (idempotent).

        No spending account transactions are created — bAV contributions are
        deducted from gross salary before taxes (Req 15.4).

        Args:
            user: The user whose bAV contracts to process.
            target_month: The month to generate logs for (first of month).
                         Defaults to the 1st of the current month.

        Returns:
            List of newly created BaVContributionLog entries.
        """
        if target_month is None:
            today = date.today()
            target_month = date(today.year, today.month, 1)
        else:
            # Normalize to first of month
            target_month = date(target_month.year, target_month.month, 1)

        # Find all active bAV contracts for this user with start_date <= target_month
        contracts = BaV.query.filter(
            BaV.user_id == user.id,
            BaV.active == True,  # noqa: E712
            BaV.start_date <= target_month,
        ).all()

        created_logs: list[BaVContributionLog] = []

        for contract in contracts:
            # Check idempotency: skip if entry for this month already exists
            existing = BaVContributionLog.query.filter(
                BaVContributionLog.bav_id == contract.id,
                BaVContributionLog.month == target_month,
            ).first()

            if existing is not None:
                continue

            # Create the contribution log entry
            log = BaVContributionLog(
                bav_id=contract.id,
                month=target_month,
                employee_amount=contract.employee_contribution_monthly,
                employer_amount=contract.employer_contribution_monthly,
            )
            db.session.add(log)
            created_logs.append(log)

        if created_logs:
            db.session.flush()

        return created_logs

    # -------------------------------------------------------------------------
    # Query helpers
    # -------------------------------------------------------------------------

    def get_total_contributions(self, bav: BaV) -> Decimal:
        """Get the total of all logged contributions for a bAV contract.

        Args:
            bav: The bAV contract.

        Returns:
            Sum of employee + employer amounts across all logged months.
        """
        logs = BaVContributionLog.query.filter(
            BaVContributionLog.bav_id == bav.id
        ).all()

        total = Decimal("0.00")
        for log in logs:
            total += log.employee_amount + log.employer_amount
        return total
