"""Unit tests for ETF models (ETFPosition, ETFTransaction, ETFPriceHistory, ETFSavingsPlan).

Validates: Requirements 13.1, 13.5, 14.1
"""

import pytest
from decimal import Decimal

from app.models.etf import (
    ETFPosition,
    ETFTransaction,
    ETFPriceHistory,
    ETFSavingsPlan,
    ETFTransactionType,
)


class TestETFTransactionType:
    """Tests for ETFTransactionType enum."""

    def test_enum_values(self):
        assert ETFTransactionType.buy.value == "buy"
        assert ETFTransactionType.sell.value == "sell"

    def test_enum_count(self):
        assert len(ETFTransactionType) == 2


class TestETFPositionModel:
    """Tests for the ETFPosition model definition."""

    def test_tablename(self):
        assert ETFPosition.__tablename__ == "etf_positions"

    def test_non_nullable_fields(self):
        """Required fields should not be nullable."""
        table = ETFPosition.__table__
        assert table.c.ticker.nullable is False
        assert table.c.exchange_suffix.nullable is False
        assert table.c.name.nullable is False
        assert table.c.shares.nullable is False
        assert table.c.average_buy_price.nullable is False
        assert table.c.manual_price_override.nullable is False
        assert table.c.user_id.nullable is False
        assert table.c.created_at.nullable is False

    def test_nullable_fields(self):
        """Optional fields should be nullable."""
        table = ETFPosition.__table__
        assert table.c.current_price.nullable is True
        assert table.c.current_price_updated_at.nullable is True

    def test_default_shares(self):
        assert ETFPosition.__table__.c.shares.default.arg == Decimal("0.000000")

    def test_default_manual_price_override(self):
        assert ETFPosition.__table__.c.manual_price_override.default.arg is False

    def test_check_constraint_shares_non_negative(self):
        """Verify CHECK constraint on shares (>= 0)."""
        constraints = ETFPosition.__table__.constraints
        found = any(
            getattr(c, "name", None) == "ck_etf_positions_shares_non_negative"
            for c in constraints
        )
        assert found, "CHECK constraint ck_etf_positions_shares_non_negative not found"

    def test_check_constraint_avg_buy_price_positive(self):
        """Verify CHECK constraint on average_buy_price (> 0)."""
        constraints = ETFPosition.__table__.constraints
        found = any(
            getattr(c, "name", None) == "ck_etf_positions_avg_buy_price_positive"
            for c in constraints
        )
        assert found, "CHECK constraint ck_etf_positions_avg_buy_price_positive not found"

    def test_repr(self):
        position = ETFPosition(ticker="VWCE", shares=Decimal("10.500000"))
        assert repr(position) == "<ETFPosition 'VWCE' shares=10.500000>"

    def test_string_field_lengths(self):
        """Verify column string lengths match design spec."""
        table = ETFPosition.__table__
        assert table.c.ticker.type.length == 10
        assert table.c.exchange_suffix.type.length == 10
        assert table.c.name.type.length == 200


class TestETFTransactionModel:
    """Tests for the ETFTransaction model definition."""

    def test_tablename(self):
        assert ETFTransaction.__tablename__ == "etf_transactions"

    def test_non_nullable_fields(self):
        """Required fields should not be nullable."""
        table = ETFTransaction.__table__
        assert table.c.position_id.nullable is False
        assert table.c.type.nullable is False
        assert table.c.shares_quantity.nullable is False
        assert table.c.price_per_share.nullable is False
        assert table.c.total_amount.nullable is False
        assert table.c.date.nullable is False
        assert table.c.user_id.nullable is False
        assert table.c.created_at.nullable is False

    def test_nullable_fields(self):
        """Optional fields should be nullable."""
        table = ETFTransaction.__table__
        assert table.c.linked_account_id.nullable is True

    def test_check_constraint_shares_positive(self):
        """Verify CHECK constraint on shares_quantity (> 0)."""
        constraints = ETFTransaction.__table__.constraints
        found = any(
            getattr(c, "name", None) == "ck_etf_transactions_shares_positive"
            for c in constraints
        )
        assert found, "CHECK constraint ck_etf_transactions_shares_positive not found"

    def test_check_constraint_price_positive(self):
        """Verify CHECK constraint on price_per_share (> 0)."""
        constraints = ETFTransaction.__table__.constraints
        found = any(
            getattr(c, "name", None) == "ck_etf_transactions_price_positive"
            for c in constraints
        )
        assert found, "CHECK constraint ck_etf_transactions_price_positive not found"

    def test_repr(self):
        txn = ETFTransaction(
            type=ETFTransactionType.buy,
            shares_quantity=Decimal("5.000000"),
            price_per_share=Decimal("98.123456"),
        )
        assert repr(txn) == "<ETFTransaction buy shares=5.000000 @ 98.123456>"

    def test_repr_sell(self):
        txn = ETFTransaction(
            type=ETFTransactionType.sell,
            shares_quantity=Decimal("2.500000"),
            price_per_share=Decimal("105.000000"),
        )
        assert repr(txn) == "<ETFTransaction sell shares=2.500000 @ 105.000000>"


class TestETFPriceHistoryModel:
    """Tests for the ETFPriceHistory model definition."""

    def test_tablename(self):
        assert ETFPriceHistory.__tablename__ == "etf_price_history"

    def test_non_nullable_fields(self):
        """Required fields should not be nullable."""
        table = ETFPriceHistory.__table__
        assert table.c.position_id.nullable is False
        assert table.c.price.nullable is False
        assert table.c.date.nullable is False

    def test_unique_constraint_position_date(self):
        """Verify UNIQUE constraint on (position_id, date)."""
        constraints = ETFPriceHistory.__table__.constraints
        found = any(
            getattr(c, "name", None) == "uq_etf_price_history_position_date"
            for c in constraints
        )
        assert found, "UNIQUE constraint uq_etf_price_history_position_date not found"

    def test_repr(self):
        from datetime import date

        history = ETFPriceHistory(
            position_id=1, price=Decimal("99.1234"), date=date(2024, 6, 15)
        )
        assert repr(history) == (
            "<ETFPriceHistory position_id=1 price=99.1234 date=2024-06-15>"
        )


class TestETFSavingsPlanModel:
    """Tests for the ETFSavingsPlan model definition."""

    def test_tablename(self):
        assert ETFSavingsPlan.__tablename__ == "etf_savings_plans"

    def test_non_nullable_fields(self):
        """Required fields should not be nullable."""
        table = ETFSavingsPlan.__table__
        assert table.c.position_id.nullable is False
        assert table.c.recurring_rule_id.nullable is False
        assert table.c.linked_account_id.nullable is False
        assert table.c.active.nullable is False
        assert table.c.user_id.nullable is False
        assert table.c.created_at.nullable is False

    def test_default_active(self):
        assert ETFSavingsPlan.__table__.c.active.default.arg is True

    def test_repr(self):
        plan = ETFSavingsPlan(position_id=3, active=True)
        assert repr(plan) == "<ETFSavingsPlan position_id=3 active=True>"

    def test_repr_inactive(self):
        plan = ETFSavingsPlan(position_id=7, active=False)
        assert repr(plan) == "<ETFSavingsPlan position_id=7 active=False>"
