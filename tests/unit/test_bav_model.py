"""Unit tests for BaV and VL models.

Validates: Requirements 15.1, 16.1
"""

import pytest
from datetime import date
from decimal import Decimal

from app.models.bav import (
    BaV,
    BaVContributionLog,
    BaVType,
    VL,
    VLContributionLog,
)


class TestBaVTypeEnum:
    """Tests for BaVType enum."""

    def test_enum_values(self):
        assert BaVType.direktversicherung.value == "direktversicherung"
        assert BaVType.pensionskasse.value == "pensionskasse"
        assert BaVType.pensionsfonds.value == "pensionsfonds"
        assert BaVType.direktzusage.value == "direktzusage"
        assert BaVType.unterstuetzungskasse.value == "unterstuetzungskasse"

    def test_enum_count(self):
        assert len(BaVType) == 5


class TestBaVModel:
    """Tests for the BaV model definition."""

    def test_tablename(self):
        assert BaV.__tablename__ == "bavs"

    def test_non_nullable_fields(self):
        """Required fields should not be nullable."""
        table = BaV.__table__
        assert table.c.provider.nullable is False
        assert table.c.type.nullable is False
        assert table.c.start_date.nullable is False
        assert table.c.employee_contribution_monthly.nullable is False
        assert table.c.employer_contribution_monthly.nullable is False
        assert table.c.total_contribution_monthly.nullable is False
        assert table.c.active.nullable is False
        assert table.c.user_id.nullable is False
        assert table.c.created_at.nullable is False

    def test_default_active(self):
        assert BaV.__table__.c.active.default.arg is True

    def test_string_field_lengths(self):
        """Verify column string lengths match design spec."""
        table = BaV.__table__
        assert table.c.provider.type.length == 100

    def test_check_constraint_employee_contribution_range(self):
        """Verify CHECK constraint on employee_contribution_monthly."""
        constraints = BaV.__table__.constraints
        found = any(
            getattr(c, "name", None) == "ck_bavs_employee_contribution_range"
            for c in constraints
        )
        assert found, "CHECK constraint ck_bavs_employee_contribution_range not found"

    def test_check_constraint_employer_contribution_range(self):
        """Verify CHECK constraint on employer_contribution_monthly."""
        constraints = BaV.__table__.constraints
        found = any(
            getattr(c, "name", None) == "ck_bavs_employer_contribution_range"
            for c in constraints
        )
        assert found, "CHECK constraint ck_bavs_employer_contribution_range not found"

    def test_repr(self):
        bav = BaV(provider="Allianz", type=BaVType.direktversicherung)
        assert repr(bav) == "<BaV 'Allianz' (direktversicherung)>"

    def test_repr_pensionskasse(self):
        bav = BaV(provider="DEVK", type=BaVType.pensionskasse)
        assert repr(bav) == "<BaV 'DEVK' (pensionskasse)>"


class TestBaVContributionLogModel:
    """Tests for the BaVContributionLog model definition."""

    def test_tablename(self):
        assert BaVContributionLog.__tablename__ == "bav_contribution_logs"

    def test_non_nullable_fields(self):
        """Required fields should not be nullable."""
        table = BaVContributionLog.__table__
        assert table.c.bav_id.nullable is False
        assert table.c.month.nullable is False
        assert table.c.employee_amount.nullable is False
        assert table.c.employer_amount.nullable is False
        assert table.c.created_at.nullable is False

    def test_unique_constraint_bav_month(self):
        """Verify UNIQUE constraint on (bav_id, month)."""
        constraints = BaVContributionLog.__table__.constraints
        found = any(
            getattr(c, "name", None) == "uq_bav_contribution_logs_bav_month"
            for c in constraints
        )
        assert found, "UNIQUE constraint uq_bav_contribution_logs_bav_month not found"

    def test_repr(self):
        log = BaVContributionLog(bav_id=1, month=date(2024, 6, 1))
        assert repr(log) == "<BaVContributionLog bav_id=1 month=2024-06-01>"


class TestVLModel:
    """Tests for the VL model definition."""

    def test_tablename(self):
        assert VL.__tablename__ == "vls"

    def test_non_nullable_fields(self):
        """Required fields should not be nullable."""
        table = VL.__table__
        assert table.c.employer_contribution_monthly.nullable is False
        assert table.c.employee_contribution_monthly.nullable is False
        assert table.c.total_contribution_monthly.nullable is False
        assert table.c.start_date.nullable is False
        assert table.c.lock_up_end_date.nullable is False
        assert table.c.sparzulage_rate.nullable is False
        assert table.c.annual_eligible_max.nullable is False
        assert table.c.active.nullable is False
        assert table.c.user_id.nullable is False
        assert table.c.created_at.nullable is False

    def test_nullable_fields(self):
        """Optional fields should be nullable."""
        table = VL.__table__
        assert table.c.etf_position_id.nullable is True
        assert table.c.linked_account_id.nullable is True

    def test_default_active(self):
        assert VL.__table__.c.active.default.arg is True

    def test_default_employee_contribution(self):
        assert VL.__table__.c.employee_contribution_monthly.default.arg == Decimal("0.00")

    def test_default_sparzulage_rate(self):
        assert VL.__table__.c.sparzulage_rate.default.arg == Decimal("0.20")

    def test_default_annual_eligible_max(self):
        assert VL.__table__.c.annual_eligible_max.default.arg == Decimal("400.00")

    def test_repr(self):
        vl = VL(total_contribution_monthly=Decimal("40.00"))
        assert repr(vl) == "<VL id=None total=40.00>"

    def test_repr_with_total(self):
        vl = VL(total_contribution_monthly=Decimal("50.00"))
        assert repr(vl) == "<VL id=None total=50.00>"


class TestVLContributionLogModel:
    """Tests for the VLContributionLog model definition."""

    def test_tablename(self):
        assert VLContributionLog.__tablename__ == "vl_contribution_logs"

    def test_non_nullable_fields(self):
        """Required fields should not be nullable."""
        table = VLContributionLog.__table__
        assert table.c.vl_id.nullable is False
        assert table.c.month.nullable is False
        assert table.c.amount.nullable is False
        assert table.c.created_at.nullable is False

    def test_nullable_fields(self):
        """Optional fields should be nullable."""
        table = VLContributionLog.__table__
        assert table.c.etf_transaction_id.nullable is True

    def test_unique_constraint_vl_month(self):
        """Verify UNIQUE constraint on (vl_id, month)."""
        constraints = VLContributionLog.__table__.constraints
        found = any(
            getattr(c, "name", None) == "uq_vl_contribution_logs_vl_month"
            for c in constraints
        )
        assert found, "UNIQUE constraint uq_vl_contribution_logs_vl_month not found"

    def test_repr(self):
        log = VLContributionLog(vl_id=3, month=date(2024, 1, 1))
        assert repr(log) == "<VLContributionLog vl_id=3 month=2024-01-01>"
