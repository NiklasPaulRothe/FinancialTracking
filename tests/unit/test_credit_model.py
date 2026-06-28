"""Unit tests for Credit, CreditPayment, and CreditForecastCache models.

Validates: Requirements 11.1, 11.4, 11.7
"""

import pytest
from datetime import date, datetime, timezone
from decimal import Decimal

from app.models.credit import (
    Credit,
    CreditPayment,
    CreditForecastCache,
    CreditStatus,
    CreditScope,
)


class TestCreditStatus:
    """Tests for CreditStatus enum."""

    def test_enum_values(self):
        assert CreditStatus.active.value == "active"
        assert CreditStatus.paid_off.value == "paid_off"

    def test_enum_count(self):
        assert len(CreditStatus) == 2


class TestCreditScope:
    """Tests for CreditScope enum."""

    def test_enum_values(self):
        assert CreditScope.personal.value == "personal"
        assert CreditScope.shared.value == "shared"

    def test_enum_count(self):
        assert len(CreditScope) == 2


class TestCreditModel:
    """Tests for the Credit model definition."""

    def test_tablename(self):
        assert Credit.__tablename__ == "credits"

    def test_non_nullable_fields(self):
        """Required fields should not be nullable."""
        table = Credit.__table__
        assert table.c.name.nullable is False
        assert table.c.principal.nullable is False
        assert table.c.remaining_balance.nullable is False
        assert table.c.accrued_interest.nullable is False
        assert table.c.effective_yearly_rate.nullable is False
        assert table.c.disbursement_date.nullable is False
        assert table.c.interest_capitalization_day.nullable is False
        assert table.c.status.nullable is False
        assert table.c.scope.nullable is False
        assert table.c.account_id.nullable is False
        assert table.c.user_id.nullable is False
        assert table.c.created_at.nullable is False
        assert table.c.converted_from_credit_card_payment.nullable is False

    def test_nullable_fields(self):
        """Optional fields should be nullable."""
        table = Credit.__table__
        assert table.c.linked_transaction_id.nullable is True

    def test_default_accrued_interest(self):
        assert Credit.__table__.c.accrued_interest.default.arg == Decimal("0.000000")

    def test_default_status(self):
        assert Credit.__table__.c.status.default.arg is CreditStatus.active

    def test_default_converted_from_credit_card(self):
        assert Credit.__table__.c.converted_from_credit_card_payment.default.arg is False

    def test_check_constraint_principal_range(self):
        """Verify CHECK constraint on principal (0.01 to 999999999.99)."""
        constraints = Credit.__table__.constraints
        found = any(
            getattr(c, "name", None) == "ck_credits_principal_range"
            for c in constraints
        )
        assert found, "CHECK constraint ck_credits_principal_range not found"

    def test_check_constraint_rate_range(self):
        """Verify CHECK constraint on effective_yearly_rate (0.0 to 1.0)."""
        constraints = Credit.__table__.constraints
        found = any(
            getattr(c, "name", None) == "ck_credits_rate_range"
            for c in constraints
        )
        assert found, "CHECK constraint ck_credits_rate_range not found"

    def test_check_constraint_capitalization_day_range(self):
        """Verify CHECK constraint on interest_capitalization_day (1 to 28)."""
        constraints = Credit.__table__.constraints
        found = any(
            getattr(c, "name", None) == "ck_credits_capitalization_day_range"
            for c in constraints
        )
        assert found, "CHECK constraint ck_credits_capitalization_day_range not found"

    def test_repr(self):
        credit = Credit(name="Autokredit", status=CreditStatus.active)
        assert repr(credit) == "<Credit 'Autokredit' (active)>"

    def test_repr_paid_off(self):
        credit = Credit(name="Studienkredit", status=CreditStatus.paid_off)
        assert repr(credit) == "<Credit 'Studienkredit' (paid_off)>"


class TestCreditPaymentModel:
    """Tests for the CreditPayment model definition."""

    def test_tablename(self):
        assert CreditPayment.__tablename__ == "credit_payments"

    def test_non_nullable_fields(self):
        """Required fields should not be nullable."""
        table = CreditPayment.__table__
        assert table.c.credit_id.nullable is False
        assert table.c.transaction_id.nullable is False
        assert table.c.total_amount.nullable is False
        assert table.c.interest_portion.nullable is False
        assert table.c.principal_portion.nullable is False
        assert table.c.manual_correction.nullable is False
        assert table.c.created_at.nullable is False

    def test_default_manual_correction(self):
        assert CreditPayment.__table__.c.manual_correction.default.arg is False

    def test_repr(self):
        payment = CreditPayment(credit_id=5, total_amount=Decimal("500.00"))
        assert repr(payment) == "<CreditPayment credit_id=5 total=500.00>"


class TestCreditForecastCacheModel:
    """Tests for the CreditForecastCache model definition."""

    def test_tablename(self):
        assert CreditForecastCache.__tablename__ == "credit_forecast_cache"

    def test_non_nullable_fields(self):
        """Required fields should not be nullable."""
        table = CreditForecastCache.__table__
        assert table.c.credit_id.nullable is False
        assert table.c.month_offset.nullable is False
        assert table.c.projected_balance.nullable is False
        assert table.c.projected_interest.nullable is False
        assert table.c.recalculated_at.nullable is False

    def test_repr(self):
        cache = CreditForecastCache(credit_id=3, month_offset=6)
        assert repr(cache) == "<CreditForecastCache credit_id=3 month_offset=6>"
