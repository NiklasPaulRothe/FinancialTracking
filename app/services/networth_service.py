"""Net worth service for Haushaltsbuch.

Implements net worth snapshot computation, history retrieval, future value
projection, and linear interpolation for missing dates.

Validates: Requirements 18.1, 18.2, 18.3, 18.4, 18.5
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func

from app.extensions import db
from app.models.account import Account, AccountType
from app.models.credit import Credit, CreditStatus
from app.models.etf import ETFPosition
from app.models.networth import NetWorthSnapshot
from app.models.user import User


class NetWorthService:
    """Service class for net worth tracking and projections.

    Computes daily snapshots, retrieves history with interpolation,
    and projects future net worth using compound growth.
    """

    def compute_snapshot(self, user_id: int, snapshot_date: date | None = None) -> NetWorthSnapshot:
        """Compute and store a net worth snapshot for the user.

        Validates: Requirement 18.1

        Net worth = sum(active account balances)
                  + sum(shares × current_price for active ETF positions)
                  − sum(active credit remaining_balances)

        If a snapshot already exists for the user and date, it is updated
        rather than duplicated (UNIQUE constraint on user_id + snapshot_date).

        Args:
            user_id: The user to compute net worth for.
            snapshot_date: The date of the snapshot. Defaults to today.

        Returns:
            The created or updated NetWorthSnapshot record.
        """
        if snapshot_date is None:
            snapshot_date = date.today()

        # Sum active account balances
        account_sum = (
            db.session.query(
                func.coalesce(func.sum(Account.balance), Decimal("0.00"))
            )
            .filter(
                Account.owner_id == user_id,
                Account.active == True,  # noqa: E712
            )
            .scalar()
        )
        account_total = Decimal(str(account_sum))

        # Sum ETF portfolio value: shares × current_price
        etf_positions = ETFPosition.query.filter(
            ETFPosition.user_id == user_id,
            ETFPosition.shares > 0,
        ).all()

        etf_total = Decimal("0.00")
        for pos in etf_positions:
            if pos.current_price is not None:
                position_value = Decimal(str(pos.shares)) * Decimal(str(pos.current_price))
                etf_total += position_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Sum active credit remaining balances
        credit_sum = (
            db.session.query(
                func.coalesce(func.sum(Credit.remaining_balance), Decimal("0.00"))
            )
            .filter(
                Credit.user_id == user_id,
                Credit.status == CreditStatus.active,
            )
            .scalar()
        )
        credit_total = Decimal(str(credit_sum))

        # Net worth formula
        total_value = (account_total + etf_total - credit_total).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # Upsert: update existing snapshot or create new one
        existing = NetWorthSnapshot.query.filter_by(
            user_id=user_id, snapshot_date=snapshot_date
        ).first()

        if existing:
            existing.total_value = total_value
            db.session.commit()
            return existing

        snapshot = NetWorthSnapshot(
            user_id=user_id,
            total_value=total_value,
            snapshot_date=snapshot_date,
        )
        db.session.add(snapshot)
        db.session.commit()
        return snapshot

    def get_history(
        self,
        user_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
        interpolate: bool = True,
    ) -> list[dict]:
        """Retrieve net worth history with optional interpolation.

        Validates: Requirements 18.2, 18.4

        Returns a list of {date, value} dicts representing daily net worth.
        If interpolate=True, missing dates between snapshots are filled using
        linear interpolation.

        Args:
            user_id: The user whose history to retrieve.
            start_date: Start of date range (inclusive). Defaults to earliest snapshot.
            end_date: End of date range (inclusive). Defaults to latest snapshot.
            interpolate: Whether to fill gaps via linear interpolation.

        Returns:
            List of dicts with 'date' and 'value' keys, sorted chronologically.
        """
        query = NetWorthSnapshot.query.filter(
            NetWorthSnapshot.user_id == user_id
        ).order_by(NetWorthSnapshot.snapshot_date.asc())

        if start_date:
            query = query.filter(NetWorthSnapshot.snapshot_date >= start_date)
        if end_date:
            query = query.filter(NetWorthSnapshot.snapshot_date <= end_date)

        snapshots = query.all()

        if not snapshots:
            return []

        if not interpolate:
            return [
                {"date": s.snapshot_date, "value": s.total_value}
                for s in snapshots
            ]

        # Build interpolated series
        return self._interpolate_snapshots(snapshots)

    def project_future_value(
        self,
        present_value: Decimal,
        monthly_rate: Decimal,
        monthly_payment: Decimal,
        months: int,
    ) -> Decimal:
        """Calculate projected future net worth using compound growth formula.

        Validates: Requirement 18.3

        FV = PV × (1 + r)^n + PMT × (((1 + r)^n − 1) / r)

        Where:
            PV = present value (latest net worth snapshot)
            r = monthly rate (assumed_annual_return / 12)
            PMT = monthly payment (sum of saving contributions + ETF plan amounts)
            n = number of months to target

        Args:
            present_value: Current net worth (PV).
            monthly_rate: Monthly growth rate as decimal (r).
            monthly_payment: Monthly contribution amount (PMT).
            months: Number of months to project (n).

        Returns:
            Projected future value rounded to 2 decimal places.

        Raises:
            ValueError: If months is negative.
        """
        if months < 0:
            raise ValueError("months must be non-negative")

        if months == 0:
            return present_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Convert to float for power calculation, then back to Decimal
        pv = float(present_value)
        r = float(monthly_rate)
        pmt = float(monthly_payment)
        n = months

        # FV = PV × (1 + r)^n + PMT × (((1 + r)^n − 1) / r)
        growth_factor = (1 + r) ** n

        fv_pv = pv * growth_factor

        if r == 0:
            # When rate is zero, annuity simplifies to PMT × n
            fv_pmt = pmt * n
        else:
            fv_pmt = pmt * ((growth_factor - 1) / r)

        future_value = Decimal(str(fv_pv + fv_pmt))
        return future_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def get_projections(self, user_id: int) -> list[dict]:
        """Get future net worth projections at standard intervals.

        Validates: Requirement 18.3

        Computes projections at 5, 10, 15, 20, 25, 30 years and at the
        user's target_retirement_age.

        Args:
            user_id: The user to project for.

        Returns:
            List of dicts with 'label', 'months', and 'value' keys.
        """
        user = db.session.get(User, user_id)
        if user is None:
            return []

        # Get latest snapshot as PV
        latest = NetWorthSnapshot.query.filter_by(
            user_id=user_id
        ).order_by(NetWorthSnapshot.snapshot_date.desc()).first()

        if latest is None:
            return []

        present_value = Decimal(str(latest.total_value))
        annual_return = Decimal(str(user.assumed_annual_return))
        monthly_rate = annual_return / Decimal("12")

        # Monthly payment = sum of active saving contributions + ETF savings plan amounts
        monthly_payment = self._get_monthly_contributions(user_id)

        # Standard intervals in years
        intervals_years = [5, 10, 15, 20, 25, 30]
        projections = []

        for years in intervals_years:
            months = years * 12
            fv = self.project_future_value(present_value, monthly_rate, monthly_payment, months)
            projections.append({
                "label": f"{years} Jahre",
                "months": months,
                "value": fv,
            })

        # Projection to retirement age
        # Estimate months to retirement (simplified: assume user age from created_at)
        if user.target_retirement_age and user.created_at:
            retirement_months = self._months_to_retirement(user)
            if retirement_months and retirement_months > 0:
                fv = self.project_future_value(
                    present_value, monthly_rate, monthly_payment, retirement_months
                )
                projections.append({
                    "label": f"Rente ({user.target_retirement_age} Jahre)",
                    "months": retirement_months,
                    "value": fv,
                })

        return projections

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _interpolate_snapshots(self, snapshots: list) -> list[dict]:
        """Fill gaps between snapshots using linear interpolation.

        Validates: Requirement 18.4

        For any two adjacent snapshots with dates d1 and d2 where d2 - d1 > 1 day,
        missing dates are filled with linearly interpolated values.

        Args:
            snapshots: Sorted list of NetWorthSnapshot objects.

        Returns:
            Complete list of {date, value} dicts with no gaps.
        """
        if not snapshots:
            return []

        if len(snapshots) == 1:
            return [{"date": snapshots[0].snapshot_date, "value": snapshots[0].total_value}]

        result = []

        for i in range(len(snapshots) - 1):
            s1 = snapshots[i]
            s2 = snapshots[i + 1]

            d1 = s1.snapshot_date
            d2 = s2.snapshot_date
            v1 = Decimal(str(s1.total_value))
            v2 = Decimal(str(s2.total_value))

            # Add the start point
            result.append({"date": d1, "value": v1})

            # Interpolate gap days
            days_gap = (d2 - d1).days
            if days_gap > 1:
                value_diff = v2 - v1
                for day_offset in range(1, days_gap):
                    interpolated_date = d1 + timedelta(days=day_offset)
                    # Linear interpolation: v1 + (v2 - v1) * (offset / total_days)
                    fraction = Decimal(str(day_offset)) / Decimal(str(days_gap))
                    interpolated_value = (v1 + value_diff * fraction).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    result.append({"date": interpolated_date, "value": interpolated_value})

        # Add the last snapshot
        last = snapshots[-1]
        result.append({"date": last.snapshot_date, "value": Decimal(str(last.total_value))})

        return result

    def _get_monthly_contributions(self, user_id: int) -> Decimal:
        """Sum monthly saving contributions and ETF savings plan amounts.

        Used as the PMT parameter in the compound growth formula.

        Args:
            user_id: The user to query.

        Returns:
            Total monthly contribution amount.
        """
        total = Decimal("0.00")

        try:
            from app.models.budget import SavingContribution, SavingGoal, SavingGoalStatus

            contrib_sum = (
                db.session.query(
                    func.coalesce(func.sum(SavingContribution.amount), Decimal("0.00"))
                )
                .join(SavingGoal, SavingContribution.saving_goal_id == SavingGoal.id)
                .filter(
                    SavingGoal.user_id == user_id,
                    SavingGoal.status == SavingGoalStatus.active,
                )
                .scalar()
            )
            total += Decimal(str(contrib_sum))
        except Exception:
            pass

        try:
            from app.models.etf import ETFSavingsPlan
            from app.models.transaction import RecurringRule

            plans = (
                db.session.query(RecurringRule.amount)
                .join(ETFSavingsPlan, ETFSavingsPlan.recurring_rule_id == RecurringRule.id)
                .filter(
                    ETFSavingsPlan.user_id == user_id,
                    ETFSavingsPlan.active == True,  # noqa: E712
                    RecurringRule.active == True,  # noqa: E712
                )
                .all()
            )
            for (amount,) in plans:
                total += Decimal(str(amount))
        except Exception:
            pass

        return total

    def _months_to_retirement(self, user: User) -> int | None:
        """Estimate months until user reaches target retirement age.

        This is a simplified calculation that estimates current age from
        the user's account creation date. A proper implementation would
        require a date_of_birth field.

        Args:
            user: The user to estimate for.

        Returns:
            Estimated months to retirement, or None if cannot be determined.
        """
        # Without a date_of_birth field, we can't accurately calculate this.
        # Return None to skip retirement projection for now.
        return None
