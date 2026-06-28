"""Unit tests for NetWorthService.

Tests net worth snapshot computation, history retrieval with linear
interpolation, and future value projection.

Validates: Requirements 18.1, 18.2, 18.3, 18.4, 18.5
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.models.account import Account, AccountType, AccountScope
from app.models.credit import Credit, CreditStatus, CreditScope
from app.models.etf import ETFPosition
from app.models.networth import NetWorthSnapshot
from app.models.user import User
from app.services.networth_service import NetWorthService


@pytest.fixture()
def service():
    """Create a NetWorthService instance."""
    return NetWorthService()


@pytest.fixture()
def user(db_session):
    """Create a test user."""
    u = User(
        username="networthuser",
        email="networth@example.com",
        password_hash="pbkdf2:sha256:600000$salt$fakehash",
        income_day=25,
        assumed_annual_return=Decimal("0.0700"),
        target_retirement_age=67,
    )
    db_session.add(u)
    db_session.flush()
    return u


class TestComputeSnapshot:
    """Tests for compute_snapshot method."""

    def test_compute_snapshot_no_assets(self, db_session, user, service):
        """Net worth is 0 when user has no accounts, ETFs, or credits."""
        snapshot = service.compute_snapshot(user.id)

        assert snapshot.total_value == Decimal("0.00")
        assert snapshot.user_id == user.id
        assert snapshot.snapshot_date == date.today()

    def test_compute_snapshot_accounts_only(self, db_session, user, service):
        """Net worth equals sum of active account balances."""
        # Create active accounts
        a1 = Account(
            name="Checking", type=AccountType.spending,
            scope=AccountScope.personal, balance=Decimal("1500.00"),
            active=True, owner_id=user.id,
        )
        a2 = Account(
            name="Savings", type=AccountType.saving,
            scope=AccountScope.personal, balance=Decimal("5000.00"),
            active=True, owner_id=user.id,
        )
        db_session.add_all([a1, a2])
        db_session.flush()

        snapshot = service.compute_snapshot(user.id)

        assert snapshot.total_value == Decimal("6500.00")

    def test_compute_snapshot_excludes_inactive_accounts(self, db_session, user, service):
        """Inactive accounts are excluded from net worth."""
        a1 = Account(
            name="Active", type=AccountType.spending,
            scope=AccountScope.personal, balance=Decimal("1000.00"),
            active=True, owner_id=user.id,
        )
        a2 = Account(
            name="Inactive", type=AccountType.spending,
            scope=AccountScope.personal, balance=Decimal("3000.00"),
            active=False, owner_id=user.id,
        )
        db_session.add_all([a1, a2])
        db_session.flush()

        snapshot = service.compute_snapshot(user.id)

        assert snapshot.total_value == Decimal("1000.00")

    def test_compute_snapshot_with_etf_positions(self, db_session, user, service):
        """ETF portfolio value is included in net worth."""
        a1 = Account(
            name="Checking", type=AccountType.spending,
            scope=AccountScope.personal, balance=Decimal("2000.00"),
            active=True, owner_id=user.id,
        )
        etf = ETFPosition(
            ticker="IWDA", exchange_suffix="AS", name="iShares MSCI World",
            shares=Decimal("10.000000"), average_buy_price=Decimal("75.000000"),
            current_price=Decimal("80.0000"),
            user_id=user.id,
        )
        db_session.add_all([a1, etf])
        db_session.flush()

        snapshot = service.compute_snapshot(user.id)

        # 2000 + (10 × 80) = 2000 + 800 = 2800
        assert snapshot.total_value == Decimal("2800.00")

    def test_compute_snapshot_etf_no_price(self, db_session, user, service):
        """ETF positions without current_price are excluded from calculation."""
        etf = ETFPosition(
            ticker="VTI", exchange_suffix="US", name="Vanguard Total",
            shares=Decimal("5.000000"), average_buy_price=Decimal("200.000000"),
            current_price=None,
            user_id=user.id,
        )
        db_session.add(etf)
        db_session.flush()

        snapshot = service.compute_snapshot(user.id)

        assert snapshot.total_value == Decimal("0.00")

    def test_compute_snapshot_with_credits(self, db_session, user, service):
        """Active credit balances are subtracted from net worth."""
        a1 = Account(
            name="Checking", type=AccountType.spending,
            scope=AccountScope.personal, balance=Decimal("10000.00"),
            active=True, owner_id=user.id,
        )
        credit = Credit(
            name="Car Loan", principal=Decimal("20000.00"),
            remaining_balance=Decimal("15000.00"),
            accrued_interest=Decimal("0.000000"),
            effective_yearly_rate=Decimal("0.035000"),
            disbursement_date=date(2023, 1, 1),
            interest_capitalization_day=1,
            status=CreditStatus.active,
            scope=CreditScope.personal,
            account_id=a1.id,
            user_id=user.id,
        )
        db_session.add_all([a1, credit])
        db_session.flush()

        snapshot = service.compute_snapshot(user.id)

        # 10000 - 15000 = -5000
        assert snapshot.total_value == Decimal("-5000.00")

    def test_compute_snapshot_excludes_paid_off_credits(self, db_session, user, service):
        """Paid-off credits are excluded from net worth."""
        a1 = Account(
            name="Checking", type=AccountType.spending,
            scope=AccountScope.personal, balance=Decimal("5000.00"),
            active=True, owner_id=user.id,
        )
        credit = Credit(
            name="Old Loan", principal=Decimal("10000.00"),
            remaining_balance=Decimal("0.00"),
            accrued_interest=Decimal("0.000000"),
            effective_yearly_rate=Decimal("0.040000"),
            disbursement_date=date(2020, 1, 1),
            interest_capitalization_day=1,
            status=CreditStatus.paid_off,
            scope=CreditScope.personal,
            account_id=a1.id,
            user_id=user.id,
        )
        db_session.add_all([a1, credit])
        db_session.flush()

        snapshot = service.compute_snapshot(user.id)

        assert snapshot.total_value == Decimal("5000.00")

    def test_compute_snapshot_full_formula(self, db_session, user, service):
        """Full net worth formula: accounts + ETF - credits."""
        a1 = Account(
            name="Checking", type=AccountType.spending,
            scope=AccountScope.personal, balance=Decimal("3000.00"),
            active=True, owner_id=user.id,
        )
        etf = ETFPosition(
            ticker="VWCE", exchange_suffix="DE", name="Vanguard FTSE All-World",
            shares=Decimal("20.000000"), average_buy_price=Decimal("100.000000"),
            current_price=Decimal("110.0000"),
            user_id=user.id,
        )
        credit = Credit(
            name="Personal Loan", principal=Decimal("5000.00"),
            remaining_balance=Decimal("4000.00"),
            accrued_interest=Decimal("0.000000"),
            effective_yearly_rate=Decimal("0.050000"),
            disbursement_date=date(2023, 6, 1),
            interest_capitalization_day=15,
            status=CreditStatus.active,
            scope=CreditScope.personal,
            account_id=a1.id,
            user_id=user.id,
        )
        db_session.add_all([a1, etf, credit])
        db_session.flush()

        snapshot = service.compute_snapshot(user.id)

        # 3000 + (20 × 110) - 4000 = 3000 + 2200 - 4000 = 1200
        assert snapshot.total_value == Decimal("1200.00")

    def test_compute_snapshot_upserts_existing(self, db_session, user, service):
        """Computing a snapshot for the same date updates the existing record."""
        today = date.today()

        # First computation
        snapshot1 = service.compute_snapshot(user.id, today)
        assert snapshot1.total_value == Decimal("0.00")

        # Add an account
        a1 = Account(
            name="New Account", type=AccountType.spending,
            scope=AccountScope.personal, balance=Decimal("1000.00"),
            active=True, owner_id=user.id,
        )
        db_session.add(a1)
        db_session.flush()

        # Recompute for the same date
        snapshot2 = service.compute_snapshot(user.id, today)

        assert snapshot2.id == snapshot1.id
        assert snapshot2.total_value == Decimal("1000.00")

    def test_compute_snapshot_custom_date(self, db_session, user, service):
        """Snapshot can be computed for a specific date."""
        custom_date = date(2024, 6, 15)
        snapshot = service.compute_snapshot(user.id, custom_date)

        assert snapshot.snapshot_date == custom_date


class TestGetHistory:
    """Tests for get_history method."""

    def test_get_history_empty(self, db_session, user, service):
        """Returns empty list when no snapshots exist."""
        result = service.get_history(user.id)
        assert result == []

    def test_get_history_single_snapshot(self, db_session, user, service):
        """Returns single entry for one snapshot."""
        snapshot = NetWorthSnapshot(
            user_id=user.id, total_value=Decimal("5000.00"),
            snapshot_date=date(2024, 1, 15),
        )
        db_session.add(snapshot)
        db_session.flush()

        result = service.get_history(user.id)

        assert len(result) == 1
        assert result[0]["date"] == date(2024, 1, 15)
        assert result[0]["value"] == Decimal("5000.00")

    def test_get_history_consecutive_days_no_interpolation(self, db_session, user, service):
        """Consecutive days need no interpolation."""
        s1 = NetWorthSnapshot(
            user_id=user.id, total_value=Decimal("1000.00"),
            snapshot_date=date(2024, 1, 1),
        )
        s2 = NetWorthSnapshot(
            user_id=user.id, total_value=Decimal("1100.00"),
            snapshot_date=date(2024, 1, 2),
        )
        db_session.add_all([s1, s2])
        db_session.flush()

        result = service.get_history(user.id)

        assert len(result) == 2
        assert result[0]["value"] == Decimal("1000.00")
        assert result[1]["value"] == Decimal("1100.00")

    def test_get_history_interpolation(self, db_session, user, service):
        """Missing days are filled with linear interpolation."""
        s1 = NetWorthSnapshot(
            user_id=user.id, total_value=Decimal("1000.00"),
            snapshot_date=date(2024, 1, 1),
        )
        s2 = NetWorthSnapshot(
            user_id=user.id, total_value=Decimal("1300.00"),
            snapshot_date=date(2024, 1, 4),
        )
        db_session.add_all([s1, s2])
        db_session.flush()

        result = service.get_history(user.id)

        # Should have 4 entries: Jan 1, 2, 3, 4
        assert len(result) == 4
        assert result[0] == {"date": date(2024, 1, 1), "value": Decimal("1000.00")}
        assert result[1] == {"date": date(2024, 1, 2), "value": Decimal("1100.00")}
        assert result[2] == {"date": date(2024, 1, 3), "value": Decimal("1200.00")}
        assert result[3] == {"date": date(2024, 1, 4), "value": Decimal("1300.00")}

    def test_get_history_interpolation_multiple_gaps(self, db_session, user, service):
        """Interpolation works across multiple gaps."""
        s1 = NetWorthSnapshot(
            user_id=user.id, total_value=Decimal("100.00"),
            snapshot_date=date(2024, 1, 1),
        )
        s2 = NetWorthSnapshot(
            user_id=user.id, total_value=Decimal("200.00"),
            snapshot_date=date(2024, 1, 3),
        )
        s3 = NetWorthSnapshot(
            user_id=user.id, total_value=Decimal("400.00"),
            snapshot_date=date(2024, 1, 5),
        )
        db_session.add_all([s1, s2, s3])
        db_session.flush()

        result = service.get_history(user.id)

        # Jan 1-5 = 5 entries
        assert len(result) == 5
        assert result[0]["value"] == Decimal("100.00")
        assert result[1]["value"] == Decimal("150.00")  # interpolated
        assert result[2]["value"] == Decimal("200.00")
        assert result[3]["value"] == Decimal("300.00")  # interpolated
        assert result[4]["value"] == Decimal("400.00")

    def test_get_history_no_interpolation_flag(self, db_session, user, service):
        """With interpolate=False, only actual snapshots are returned."""
        s1 = NetWorthSnapshot(
            user_id=user.id, total_value=Decimal("100.00"),
            snapshot_date=date(2024, 1, 1),
        )
        s2 = NetWorthSnapshot(
            user_id=user.id, total_value=Decimal("200.00"),
            snapshot_date=date(2024, 1, 5),
        )
        db_session.add_all([s1, s2])
        db_session.flush()

        result = service.get_history(user.id, interpolate=False)

        assert len(result) == 2

    def test_get_history_date_range_filter(self, db_session, user, service):
        """Date range filters narrow the results."""
        for i in range(10):
            s = NetWorthSnapshot(
                user_id=user.id, total_value=Decimal(str(1000 + i * 100)),
                snapshot_date=date(2024, 1, 1) + timedelta(days=i),
            )
            db_session.add(s)
        db_session.flush()

        result = service.get_history(
            user.id,
            start_date=date(2024, 1, 3),
            end_date=date(2024, 1, 7),
        )

        assert len(result) == 5
        assert result[0]["date"] == date(2024, 1, 3)
        assert result[-1]["date"] == date(2024, 1, 7)


class TestProjectFutureValue:
    """Tests for project_future_value method."""

    def test_zero_months(self, service):
        """Zero months returns present value unchanged."""
        result = service.project_future_value(
            present_value=Decimal("10000.00"),
            monthly_rate=Decimal("0.005833"),
            monthly_payment=Decimal("500.00"),
            months=0,
        )
        assert result == Decimal("10000.00")

    def test_zero_rate_growth(self, service):
        """Zero rate means FV = PV + PMT × n."""
        result = service.project_future_value(
            present_value=Decimal("10000.00"),
            monthly_rate=Decimal("0"),
            monthly_payment=Decimal("500.00"),
            months=12,
        )
        # FV = 10000 + 500 * 12 = 16000
        assert result == Decimal("16000.00")

    def test_zero_payment(self, service):
        """Zero payment means only compound growth on PV."""
        result = service.project_future_value(
            present_value=Decimal("10000.00"),
            monthly_rate=Decimal("0.005"),  # ~6% annual
            monthly_payment=Decimal("0"),
            months=12,
        )
        # FV = 10000 × (1.005)^12 ≈ 10616.78
        expected = Decimal("10616.78")
        assert abs(result - expected) < Decimal("0.01")

    def test_standard_projection(self, service):
        """Standard compound growth with contributions."""
        # PV = 50000, r = 7%/12 ≈ 0.00583, PMT = 1000, n = 60 (5 years)
        monthly_rate = Decimal("0.07") / Decimal("12")
        result = service.project_future_value(
            present_value=Decimal("50000.00"),
            monthly_rate=monthly_rate,
            monthly_payment=Decimal("1000.00"),
            months=60,
        )
        # Should be significantly more than 50000 + 60000 = 110000
        assert result > Decimal("110000.00")
        # Manual calculation: FV ≈ 50000 × 1.4176 + 1000 × 71.59 ≈ 70882 + 71593 ≈ 142475
        assert abs(result - Decimal("142475.52")) < Decimal("100.00")

    def test_negative_months_raises(self, service):
        """Negative months raises ValueError."""
        with pytest.raises(ValueError, match="months must be non-negative"):
            service.project_future_value(
                present_value=Decimal("10000.00"),
                monthly_rate=Decimal("0.005"),
                monthly_payment=Decimal("500.00"),
                months=-1,
            )

    def test_negative_present_value(self, service):
        """Negative PV (net debt) projects correctly."""
        result = service.project_future_value(
            present_value=Decimal("-5000.00"),
            monthly_rate=Decimal("0"),
            monthly_payment=Decimal("1000.00"),
            months=10,
        )
        # FV = -5000 + 1000 × 10 = 5000
        assert result == Decimal("5000.00")


class TestNetWorthModel:
    """Tests for NetWorthSnapshot model."""

    def test_create_snapshot(self, db_session, user):
        """Can create and persist a NetWorthSnapshot."""
        snapshot = NetWorthSnapshot(
            user_id=user.id,
            total_value=Decimal("42000.50"),
            snapshot_date=date(2024, 3, 15),
        )
        db_session.add(snapshot)
        db_session.flush()

        assert snapshot.id is not None
        assert snapshot.user_id == user.id
        assert snapshot.total_value == Decimal("42000.50")
        assert snapshot.snapshot_date == date(2024, 3, 15)

    def test_unique_constraint(self, db_session, user):
        """Cannot create two snapshots for the same user and date."""
        s1 = NetWorthSnapshot(
            user_id=user.id, total_value=Decimal("1000.00"),
            snapshot_date=date(2024, 1, 1),
        )
        db_session.add(s1)
        db_session.flush()

        s2 = NetWorthSnapshot(
            user_id=user.id, total_value=Decimal("2000.00"),
            snapshot_date=date(2024, 1, 1),
        )
        db_session.add(s2)

        with pytest.raises(Exception):
            db_session.flush()

    def test_repr(self, db_session, user):
        """Model repr is readable."""
        snapshot = NetWorthSnapshot(
            user_id=user.id, total_value=Decimal("1234.56"),
            snapshot_date=date(2024, 6, 1),
        )
        assert "user_id=" in repr(snapshot)
        assert "1234.56" in repr(snapshot)
