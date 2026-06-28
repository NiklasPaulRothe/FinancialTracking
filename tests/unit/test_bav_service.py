"""Unit tests for BaV service.

Validates: Requirements 15.1, 15.2, 15.3, 15.4, 15.5
"""

import pytest
from datetime import date, datetime, timezone
from decimal import Decimal

from app.extensions import db
from app.models.bav import BaV, BaVContributionLog, BaVType
from app.models.user import User
from app.services.bav_service import BaVService


@pytest.fixture()
def user(db_session):
    """Create a test user with tax/social rates configured."""
    u = User(
        username="bavtester",
        email="bav@example.com",
        password_hash="pbkdf2:sha256:600000$salt$fakehash",
        income_day=25,
        marginal_tax_rate=Decimal("0.4200"),
        social_security_rate=Decimal("0.2050"),
    )
    db_session.add(u)
    db_session.flush()
    return u


@pytest.fixture()
def bav_contract(db_session, user):
    """Create an active bAV contract."""
    contract = BaV(
        provider="Allianz",
        type=BaVType.direktversicherung,
        start_date=date(2023, 1, 1),
        employee_contribution_monthly=Decimal("200.00"),
        employer_contribution_monthly=Decimal("100.00"),
        total_contribution_monthly=Decimal("300.00"),
        active=True,
        user_id=user.id,
    )
    db_session.add(contract)
    db_session.flush()
    return contract


@pytest.fixture()
def service():
    """Create a BaVService instance."""
    return BaVService()


class TestNetCostCalculation:
    """Tests for bAV net cost calculation (Req 15.2)."""

    def test_basic_net_cost_calculation(self, db_session, user, service):
        """Net cost = employee_contribution × (1 − tax_rate − social_rate)."""
        result = service.calculate_net_cost(Decimal("200.00"), user)

        # 200 × (1 - 0.42 - 0.205) = 200 × 0.375 = 75.00
        assert result.net_cost == Decimal("75.00")
        assert result.gross_contribution == Decimal("200.00")
        assert result.marginal_tax_rate == Decimal("0.4200")
        assert result.social_security_rate == Decimal("0.2050")

    def test_net_cost_with_zero_rates(self, db_session, service):
        """With zero tax and social rates, net cost equals gross contribution."""
        u = User(
            username="zerotax",
            email="zero@example.com",
            password_hash="pbkdf2:sha256:600000$salt$fakehash",
            income_day=1,
            marginal_tax_rate=Decimal("0.0000"),
            social_security_rate=Decimal("0.0000"),
        )
        db_session.add(u)
        db_session.flush()

        result = service.calculate_net_cost(Decimal("500.00"), u)
        assert result.net_cost == Decimal("500.00")

    def test_net_cost_with_high_rates(self, db_session, service):
        """With high tax+social rates, net cost is significantly reduced."""
        u = User(
            username="hightax",
            email="hightax@example.com",
            password_hash="pbkdf2:sha256:600000$salt$fakehash",
            income_day=1,
            marginal_tax_rate=Decimal("0.4500"),
            social_security_rate=Decimal("0.2100"),
        )
        db_session.add(u)
        db_session.flush()

        result = service.calculate_net_cost(Decimal("100.00"), u)
        # 100 × (1 - 0.45 - 0.21) = 100 × 0.34 = 34.00
        assert result.net_cost == Decimal("34.00")

    def test_net_cost_rounds_to_two_decimals(self, db_session, service):
        """Net cost is rounded to 2 decimal places."""
        u = User(
            username="rounding",
            email="rounding@example.com",
            password_hash="pbkdf2:sha256:600000$salt$fakehash",
            income_day=1,
            marginal_tax_rate=Decimal("0.3333"),
            social_security_rate=Decimal("0.1111"),
        )
        db_session.add(u)
        db_session.flush()

        result = service.calculate_net_cost(Decimal("123.45"), u)
        # 123.45 × (1 - 0.3333 - 0.1111) = 123.45 × 0.5556 = 68.5887...
        expected = Decimal("68.59")
        assert result.net_cost == expected


class TestMonthlyLogGeneration:
    """Tests for bAV monthly contribution log generation (Req 15.3)."""

    def test_generates_log_for_active_contract(
        self, db_session, user, bav_contract, service
    ):
        """Generates a contribution log for an active contract."""
        target = date(2024, 3, 1)
        logs = service.generate_monthly_logs(user, target_month=target)

        assert len(logs) == 1
        log = logs[0]
        assert log.bav_id == bav_contract.id
        assert log.month == target
        assert log.employee_amount == Decimal("200.00")
        assert log.employer_amount == Decimal("100.00")

    def test_skips_inactive_contract(self, db_session, user, bav_contract, service):
        """Inactive contracts are excluded from log generation (Req 15.5)."""
        bav_contract.active = False
        db_session.flush()

        logs = service.generate_monthly_logs(user, target_month=date(2024, 3, 1))
        assert len(logs) == 0

    def test_skips_contract_with_future_start_date(
        self, db_session, user, service
    ):
        """Contracts with start_date after target_month are skipped."""
        future_contract = BaV(
            provider="Future Corp",
            type=BaVType.pensionskasse,
            start_date=date(2024, 6, 1),
            employee_contribution_monthly=Decimal("150.00"),
            employer_contribution_monthly=Decimal("50.00"),
            total_contribution_monthly=Decimal("200.00"),
            active=True,
            user_id=user.id,
        )
        db_session.add(future_contract)
        db_session.flush()

        logs = service.generate_monthly_logs(user, target_month=date(2024, 3, 1))
        assert len(logs) == 0

    def test_idempotent_skips_existing_log(
        self, db_session, user, bav_contract, service
    ):
        """Skips month if log entry already exists (idempotent)."""
        target = date(2024, 3, 1)

        # Generate first time
        logs1 = service.generate_monthly_logs(user, target_month=target)
        assert len(logs1) == 1

        # Generate again — should skip
        logs2 = service.generate_monthly_logs(user, target_month=target)
        assert len(logs2) == 0

        # Verify only one log exists
        all_logs = BaVContributionLog.query.filter(
            BaVContributionLog.bav_id == bav_contract.id,
            BaVContributionLog.month == target,
        ).all()
        assert len(all_logs) == 1

    def test_generates_for_multiple_contracts(self, db_session, user, bav_contract, service):
        """Generates logs for multiple active contracts."""
        contract2 = BaV(
            provider="Munich Re",
            type=BaVType.pensionsfonds,
            start_date=date(2023, 6, 1),
            employee_contribution_monthly=Decimal("300.00"),
            employer_contribution_monthly=Decimal("200.00"),
            total_contribution_monthly=Decimal("500.00"),
            active=True,
            user_id=user.id,
        )
        db_session.add(contract2)
        db_session.flush()

        logs = service.generate_monthly_logs(user, target_month=date(2024, 3, 1))
        assert len(logs) == 2

    def test_normalizes_target_month_to_first_of_month(
        self, db_session, user, bav_contract, service
    ):
        """Target month is normalized to first of month."""
        # Pass a mid-month date
        logs = service.generate_monthly_logs(user, target_month=date(2024, 3, 15))
        assert len(logs) == 1
        assert logs[0].month == date(2024, 3, 1)

    def test_contract_starting_same_month_included(
        self, db_session, user, service
    ):
        """Contract with start_date equal to target_month is included."""
        contract = BaV(
            provider="Same Month Corp",
            type=BaVType.direktzusage,
            start_date=date(2024, 3, 1),
            employee_contribution_monthly=Decimal("100.00"),
            employer_contribution_monthly=Decimal("0.00"),
            total_contribution_monthly=Decimal("100.00"),
            active=True,
            user_id=user.id,
        )
        db_session.add(contract)
        db_session.flush()

        logs = service.generate_monthly_logs(user, target_month=date(2024, 3, 1))
        assert len(logs) == 1


class TestGetTotalContributions:
    """Tests for total contribution query helper."""

    def test_sums_all_logged_contributions(
        self, db_session, user, bav_contract, service
    ):
        """Total contributions sums all employee + employer amounts."""
        # Generate a few months of logs
        for month_num in range(1, 4):
            service.generate_monthly_logs(
                user, target_month=date(2024, month_num, 1)
            )

        total = service.get_total_contributions(bav_contract)
        # 3 months × (200 + 100) = 900
        assert total == Decimal("900.00")

    def test_returns_zero_with_no_logs(self, db_session, user, bav_contract, service):
        """Returns zero when no contribution logs exist."""
        total = service.get_total_contributions(bav_contract)
        assert total == Decimal("0.00")
