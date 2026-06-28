"""Unit tests for VL service.

Validates: Requirements 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 16.8
"""

import pytest
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

from app.extensions import db
from app.models.bav import VL, VLContributionLog
from app.models.etf import ETFPosition, ETFTransaction, ETFTransactionType
from app.models.user import User
from app.services.vl_service import VLService, STALE_PRICE_THRESHOLD_DAYS


@pytest.fixture()
def user(db_session):
    """Create a test user."""
    u = User(
        username="vltester",
        email="vl@example.com",
        password_hash="pbkdf2:sha256:600000$salt$fakehash",
        income_day=25,
        marginal_tax_rate=Decimal("0.4200"),
        social_security_rate=Decimal("0.2050"),
    )
    db_session.add(u)
    db_session.flush()
    return u


@pytest.fixture()
def etf_position(db_session, user):
    """Create a test ETF position with a fresh price."""
    pos = ETFPosition(
        ticker="VWCE",
        exchange_suffix="DE",
        name="Vanguard FTSE All-World UCITS ETF",
        shares=Decimal("50.000000"),
        average_buy_price=Decimal("90.000000"),
        current_price=Decimal("100.0000"),
        current_price_updated_at=datetime.now(timezone.utc),
        manual_price_override=False,
        user_id=user.id,
    )
    db_session.add(pos)
    db_session.flush()
    return pos


@pytest.fixture()
def vl_contract(db_session, user, etf_position):
    """Create an active VL contract linked to an ETF position."""
    contract = VL(
        employer_contribution_monthly=Decimal("40.00"),
        employee_contribution_monthly=Decimal("0.00"),
        total_contribution_monthly=Decimal("40.00"),
        start_date=date(2023, 1, 1),
        lock_up_end_date=date(2030, 1, 1),
        etf_position_id=etf_position.id,
        linked_account_id=None,
        sparzulage_rate=Decimal("0.20"),
        annual_eligible_max=Decimal("400.00"),
        active=True,
        user_id=user.id,
    )
    db_session.add(contract)
    db_session.flush()
    return contract


@pytest.fixture()
def vl_no_etf(db_session, user):
    """Create an active VL contract without an ETF link."""
    contract = VL(
        employer_contribution_monthly=Decimal("40.00"),
        employee_contribution_monthly=Decimal("10.00"),
        total_contribution_monthly=Decimal("50.00"),
        start_date=date(2023, 1, 1),
        lock_up_end_date=date(2030, 6, 15),
        etf_position_id=None,
        linked_account_id=None,
        sparzulage_rate=Decimal("0.20"),
        annual_eligible_max=Decimal("400.00"),
        active=True,
        user_id=user.id,
    )
    db_session.add(contract)
    db_session.flush()
    return contract


@pytest.fixture()
def service():
    """Create a VLService instance."""
    return VLService()


class TestMonthlyContribution:
    """Tests for VL monthly contribution generation (Req 16.2)."""

    def test_generates_log_for_active_contract_with_etf(
        self, db_session, user, vl_contract, etf_position, service
    ):
        """Creates VLContributionLog and ETFTransaction for contract with ETF link."""
        target = date(2024, 3, 1)
        logs, notifications = service.generate_monthly_contributions(
            user, target_month=target
        )

        assert len(logs) == 1
        log = logs[0]
        assert log.vl_id == vl_contract.id
        assert log.month == target
        assert log.amount == Decimal("40.00")
        assert log.etf_transaction_id is not None

    def test_etf_shares_calculated_correctly(
        self, db_session, user, vl_contract, etf_position, service
    ):
        """Shares = total_contribution / current_price rounded to 6 decimals."""
        target = date(2024, 3, 1)
        logs, _ = service.generate_monthly_contributions(user, target_month=target)

        # 40 / 100 = 0.400000
        etf_txn = db.session.get(ETFTransaction, logs[0].etf_transaction_id)
        assert etf_txn.shares_quantity == Decimal("0.400000")
        assert etf_txn.type == ETFTransactionType.buy

    def test_etf_transaction_has_null_linked_account(
        self, db_session, user, vl_contract, etf_position, service
    ):
        """ETF buy has linked_account_id=None (Req 16.4: employer pays directly)."""
        target = date(2024, 3, 1)
        logs, _ = service.generate_monthly_contributions(user, target_month=target)

        etf_txn = db.session.get(ETFTransaction, logs[0].etf_transaction_id)
        assert etf_txn.linked_account_id is None

    def test_position_shares_increased(
        self, db_session, user, vl_contract, etf_position, service
    ):
        """Position shares are increased after VL contribution."""
        initial_shares = etf_position.shares
        target = date(2024, 3, 1)
        service.generate_monthly_contributions(user, target_month=target)

        # 40/100 = 0.4 shares added
        assert etf_position.shares == initial_shares + Decimal("0.400000")

    def test_average_buy_price_recalculated(
        self, db_session, user, vl_contract, etf_position, service
    ):
        """Average buy price is recalculated on VL ETF purchase."""
        initial_shares = etf_position.shares  # 50
        initial_avg = etf_position.average_buy_price  # 90

        target = date(2024, 3, 1)
        service.generate_monthly_contributions(user, target_month=target)

        # New shares: 0.4 @ 100
        # New avg = (50*90 + 0.4*100) / (50+0.4) = (4500+40) / 50.4 = 4540/50.4
        new_shares = Decimal("0.400000")
        expected_avg = (
            (initial_shares * initial_avg) + (new_shares * Decimal("100.0000"))
        ) / (initial_shares + new_shares)
        expected_avg = expected_avg.quantize(Decimal("0.000001"))
        assert etf_position.average_buy_price == expected_avg

    def test_generates_log_without_etf_link(
        self, db_session, user, vl_no_etf, service
    ):
        """Generates contribution log without ETF transaction when no ETF linked."""
        target = date(2024, 3, 1)
        logs, notifications = service.generate_monthly_contributions(
            user, target_month=target
        )

        assert len(logs) == 1
        assert logs[0].etf_transaction_id is None
        assert logs[0].amount == Decimal("50.00")

    def test_notification_on_success(
        self, db_session, user, vl_contract, etf_position, service
    ):
        """Generates a success notification after contribution."""
        target = date(2024, 3, 1)
        _, notifications = service.generate_monthly_contributions(
            user, target_month=target
        )

        assert len(notifications) == 1
        assert notifications[0].notification_type == "vl_contribution_executed"
        assert "40.00" in notifications[0].message


class TestIdempotency:
    """Tests for idempotent monthly log generation (Req 16.2)."""

    def test_skips_if_log_exists(
        self, db_session, user, vl_contract, etf_position, service
    ):
        """Skips contribution if VLContributionLog for month already exists."""
        target = date(2024, 3, 1)

        # First call creates the log
        logs1, _ = service.generate_monthly_contributions(user, target_month=target)
        assert len(logs1) == 1

        # Second call should skip
        logs2, _ = service.generate_monthly_contributions(user, target_month=target)
        assert len(logs2) == 0

    def test_idempotent_no_duplicate_etf_transactions(
        self, db_session, user, vl_contract, etf_position, service
    ):
        """No duplicate ETF transactions are created on repeated calls."""
        target = date(2024, 3, 1)

        service.generate_monthly_contributions(user, target_month=target)
        initial_shares = etf_position.shares

        # Second call — should not change anything
        service.generate_monthly_contributions(user, target_month=target)
        assert etf_position.shares == initial_shares


class TestStalePriceCheck:
    """Tests for stale price detection in VL contributions (Req 16.3)."""

    def test_stale_price_skips_contribution(
        self, db_session, user, vl_contract, etf_position, service
    ):
        """When ETF price is >3 days old, contribution is skipped."""
        # Make price 5 days old
        etf_position.current_price_updated_at = datetime(
            2024, 2, 25, 12, 0, 0, tzinfo=timezone.utc
        )
        db_session.flush()

        target = date(2024, 3, 1)
        logs, notifications = service.generate_monthly_contributions(
            user, target_month=target
        )

        assert len(logs) == 0
        assert len(notifications) == 1
        assert notifications[0].notification_type == "vl_price_stale"

    def test_stale_price_notification_message(
        self, db_session, user, vl_contract, etf_position, service
    ):
        """Stale price notification includes relevant info."""
        etf_position.current_price_updated_at = datetime(
            2024, 2, 20, 12, 0, 0, tzinfo=timezone.utc
        )
        db_session.flush()

        target = date(2024, 3, 1)
        _, notifications = service.generate_monthly_contributions(
            user, target_month=target
        )

        assert "stale" in notifications[0].message
        assert "VWCE" in notifications[0].message

    def test_null_price_treated_as_stale(
        self, db_session, user, vl_contract, etf_position, service
    ):
        """When current_price is None, it's treated as stale."""
        etf_position.current_price = None
        etf_position.current_price_updated_at = None
        db_session.flush()

        target = date(2024, 3, 1)
        logs, notifications = service.generate_monthly_contributions(
            user, target_month=target
        )

        assert len(logs) == 0
        assert notifications[0].notification_type == "vl_price_stale"

    def test_exactly_3_days_old_is_not_stale(
        self, db_session, user, vl_contract, etf_position, service
    ):
        """A price exactly 3 days old is NOT stale (threshold is >3 days)."""
        # Set price to exactly 3 days before target
        etf_position.current_price_updated_at = datetime(
            2024, 2, 27, 12, 0, 0, tzinfo=timezone.utc
        )
        db_session.flush()

        target = date(2024, 3, 1)
        logs, _ = service.generate_monthly_contributions(user, target_month=target)

        # 3 days is NOT > 3, so should execute
        assert len(logs) == 1

    def test_skips_inactive_contract(
        self, db_session, user, vl_contract, etf_position, service
    ):
        """Inactive VL contracts are not processed."""
        vl_contract.active = False
        db_session.flush()

        target = date(2024, 3, 1)
        logs, notifications = service.generate_monthly_contributions(
            user, target_month=target
        )

        assert len(logs) == 0
        assert len(notifications) == 0

    def test_skips_future_start_date_contract(self, db_session, user, service):
        """Contracts with start_date after target_month are skipped."""
        future_vl = VL(
            employer_contribution_monthly=Decimal("40.00"),
            employee_contribution_monthly=Decimal("0.00"),
            total_contribution_monthly=Decimal("40.00"),
            start_date=date(2024, 6, 1),
            lock_up_end_date=date(2031, 6, 1),
            etf_position_id=None,
            linked_account_id=None,
            sparzulage_rate=Decimal("0.20"),
            annual_eligible_max=Decimal("400.00"),
            active=True,
            user_id=user.id,
        )
        db_session.add(future_vl)
        db_session.flush()

        target = date(2024, 3, 1)
        logs, _ = service.generate_monthly_contributions(user, target_month=target)
        assert len(logs) == 0


class TestSparzulageCalculation:
    """Tests for Sparzulage (state bonus) calculation (Req 16.7)."""

    def test_basic_sparzulage_calculation(
        self, db_session, user, vl_contract, etf_position, service
    ):
        """Sparzulage = rate × min(annual_contributions, annual_eligible_max)."""
        # Generate 6 months of contributions (40 × 6 = 240)
        for month_num in range(1, 7):
            service.generate_monthly_contributions(
                user, target_month=date(2024, month_num, 1)
            )

        result = service.calculate_sparzulage(vl_contract, year=2024)

        # annual_contributions = 240, annual_eligible_max = 400
        # eligible = min(240, 400) = 240
        # bonus = 0.20 × 240 = 48.00
        assert result.annual_contributions == Decimal("240.00")
        assert result.eligible_amount == Decimal("240.00")
        assert result.expected_bonus == Decimal("48.00")

    def test_sparzulage_capped_at_annual_max(
        self, db_session, user, vl_contract, etf_position, service
    ):
        """Sparzulage is capped at annual_eligible_max."""
        # Generate 12 months of contributions (40 × 12 = 480 > 400 max)
        for month_num in range(1, 13):
            service.generate_monthly_contributions(
                user, target_month=date(2024, month_num, 1)
            )

        result = service.calculate_sparzulage(vl_contract, year=2024)

        # annual_contributions = 480, annual_eligible_max = 400
        # eligible = min(480, 400) = 400
        # bonus = 0.20 × 400 = 80.00
        assert result.annual_contributions == Decimal("480.00")
        assert result.eligible_amount == Decimal("400.00")
        assert result.expected_bonus == Decimal("80.00")

    def test_sparzulage_zero_when_no_contributions(
        self, db_session, user, vl_contract, service
    ):
        """Sparzulage is zero when no contributions exist for the year."""
        result = service.calculate_sparzulage(vl_contract, year=2024)

        assert result.annual_contributions == Decimal("0.00")
        assert result.eligible_amount == Decimal("0.00")
        assert result.expected_bonus == Decimal("0.00")

    def test_sparzulage_only_counts_target_year(
        self, db_session, user, vl_contract, etf_position, service
    ):
        """Sparzulage only considers contributions from the specified year."""
        # Generate contributions in 2023 and 2024
        service.generate_monthly_contributions(
            user, target_month=date(2023, 12, 1)
        )
        service.generate_monthly_contributions(
            user, target_month=date(2024, 1, 1)
        )

        result = service.calculate_sparzulage(vl_contract, year=2024)

        # Only January 2024 counts (40)
        assert result.annual_contributions == Decimal("40.00")
        assert result.expected_bonus == Decimal("8.00")


class TestLockUpTracking:
    """Tests for VL lock-up period tracking (Req 16.5)."""

    def test_is_locked_returns_true_when_locked(
        self, db_session, vl_contract, service
    ):
        """Returns True when lock_up_end_date is in the future."""
        assert service.is_locked(vl_contract, reference_date=date(2025, 6, 1))

    def test_is_locked_returns_false_when_expired(
        self, db_session, vl_contract, service
    ):
        """Returns False when lock_up_end_date has passed."""
        assert not service.is_locked(vl_contract, reference_date=date(2030, 1, 2))

    def test_is_locked_returns_false_on_exact_date(
        self, db_session, vl_contract, service
    ):
        """Returns False when reference_date equals lock_up_end_date."""
        assert not service.is_locked(vl_contract, reference_date=date(2030, 1, 1))

    def test_remaining_lockup_years_and_months(
        self, db_session, vl_contract, service
    ):
        """Correctly calculates remaining years and months."""
        # From 2025-06-01 to 2030-01-01 = 4 years, 7 months
        years, months = service.get_remaining_lockup(
            vl_contract, reference_date=date(2025, 6, 1)
        )
        assert years == 4
        assert months == 7

    def test_remaining_lockup_zero_when_expired(
        self, db_session, vl_contract, service
    ):
        """Returns (0, 0) when lock-up has expired."""
        years, months = service.get_remaining_lockup(
            vl_contract, reference_date=date(2031, 1, 1)
        )
        assert years == 0
        assert months == 0

    def test_remaining_lockup_with_no_etf(
        self, db_session, vl_no_etf, service
    ):
        """Lock-up tracking works for contracts without ETF link."""
        # vl_no_etf has lock_up_end_date=2030-06-15
        assert service.is_locked(vl_no_etf, reference_date=date(2025, 1, 1))
        years, months = service.get_remaining_lockup(
            vl_no_etf, reference_date=date(2025, 1, 1)
        )
        assert years == 5
        assert months == 5
