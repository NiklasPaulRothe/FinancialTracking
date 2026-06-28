"""Unit tests for Transaction and related models.

Validates: Requirements 3.1, 4.1, 9.3
"""

import pytest
from datetime import date, datetime, timezone
from decimal import Decimal

from app.models.transaction import (
    Tag,
    Transaction,
    TransactionSplit,
    TransactionPlannedExpense,
    SharedExpense,
    SharedExpenseShare,
    RecurringRule,
    RecurringRuleSplit,
    TransactionType,
    TransactionScope,
    RecurringFrequency,
    transaction_tags,
)


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestTransactionType:
    """Tests for TransactionType enum."""

    def test_enum_values(self):
        assert TransactionType.income.value == "income"
        assert TransactionType.expense.value == "expense"
        assert TransactionType.transfer.value == "transfer"
        assert TransactionType.credit_card_payment.value == "credit_card_payment"

    def test_enum_count(self):
        assert len(TransactionType) == 4


class TestTransactionScope:
    """Tests for TransactionScope enum."""

    def test_enum_values(self):
        assert TransactionScope.personal.value == "personal"
        assert TransactionScope.shared.value == "shared"

    def test_enum_count(self):
        assert len(TransactionScope) == 2


class TestRecurringFrequency:
    """Tests for RecurringFrequency enum."""

    def test_enum_values(self):
        assert RecurringFrequency.daily.value == "daily"
        assert RecurringFrequency.weekly.value == "weekly"
        assert RecurringFrequency.monthly.value == "monthly"
        assert RecurringFrequency.quarterly.value == "quarterly"
        assert RecurringFrequency.yearly.value == "yearly"

    def test_enum_count(self):
        assert len(RecurringFrequency) == 5


# ---------------------------------------------------------------------------
# Tag model tests
# ---------------------------------------------------------------------------


class TestTagModel:
    """Tests for the Tag model definition."""

    def test_tablename(self):
        assert Tag.__tablename__ == "tags"

    def test_non_nullable_fields(self):
        assert Tag.__table__.c.name.nullable is False
        assert Tag.__table__.c.user_id.nullable is False

    def test_unique_constraint_exists(self):
        """Verify unique constraint on (name, user_id)."""
        found = any(
            getattr(c, "name", None) == "uq_tags_name_user"
            for c in Tag.__table__.constraints
        )
        assert found, "Unique constraint uq_tags_name_user not found"

    def test_repr(self):
        tag = Tag(name="groceries")
        assert repr(tag) == "<Tag 'groceries'>"


# ---------------------------------------------------------------------------
# Transaction model tests
# ---------------------------------------------------------------------------


class TestTransactionModel:
    """Tests for the Transaction model definition."""

    def test_tablename(self):
        assert Transaction.__tablename__ == "transactions"

    def test_non_nullable_fields(self):
        assert Transaction.__table__.c.type.nullable is False
        assert Transaction.__table__.c.amount.nullable is False
        assert Transaction.__table__.c.date.nullable is False
        assert Transaction.__table__.c.scope.nullable is False
        assert Transaction.__table__.c.posted.nullable is False
        assert Transaction.__table__.c.user_id.nullable is False
        assert Transaction.__table__.c.created_at.nullable is False

    def test_nullable_fields(self):
        assert Transaction.__table__.c.description.nullable is True
        assert Transaction.__table__.c.account_id.nullable is True
        assert Transaction.__table__.c.destination_account_id.nullable is True
        assert Transaction.__table__.c.category_id.nullable is True
        assert Transaction.__table__.c.recurring_rule_id.nullable is True
        assert Transaction.__table__.c.statement_closing_date.nullable is True

    def test_default_posted(self):
        assert Transaction.__table__.c.posted.default.arg is True

    def test_amount_check_constraint(self):
        """Verify check constraint on amount range."""
        found = any(
            getattr(c, "name", None) == "ck_transactions_amount_range"
            for c in Transaction.__table__.constraints
        )
        assert found, "Check constraint ck_transactions_amount_range not found"

    def test_repr(self):
        txn = Transaction(
            id=42,
            type=TransactionType.expense,
            amount=Decimal("19.99"),
            date=date(2024, 7, 1),
            scope=TransactionScope.personal,
            user_id=1,
        )
        assert repr(txn) == "<Transaction 42 expense 19.99>"


# ---------------------------------------------------------------------------
# TransactionSplit model tests
# ---------------------------------------------------------------------------


class TestTransactionSplitModel:
    """Tests for the TransactionSplit model definition."""

    def test_tablename(self):
        assert TransactionSplit.__tablename__ == "transaction_splits"

    def test_non_nullable_fields(self):
        assert TransactionSplit.__table__.c.transaction_id.nullable is False
        assert TransactionSplit.__table__.c.category_id.nullable is False
        assert TransactionSplit.__table__.c.amount.nullable is False

    def test_nullable_fields(self):
        assert TransactionSplit.__table__.c.description.nullable is True

    def test_amount_positive_check_constraint(self):
        """Verify check constraint: amount > 0."""
        found = any(
            getattr(c, "name", None) == "ck_transaction_splits_amount_positive"
            for c in TransactionSplit.__table__.constraints
        )
        assert found, "Check constraint ck_transaction_splits_amount_positive not found"

    def test_repr(self):
        split = TransactionSplit(id=5, amount=Decimal("10.50"))
        assert repr(split) == "<TransactionSplit 5 amount=10.50>"


# ---------------------------------------------------------------------------
# TransactionPlannedExpense model tests
# ---------------------------------------------------------------------------


class TestTransactionPlannedExpenseModel:
    """Tests for the TransactionPlannedExpense model definition."""

    def test_tablename(self):
        assert TransactionPlannedExpense.__tablename__ == "transaction_planned_expenses"

    def test_non_nullable_fields(self):
        assert TransactionPlannedExpense.__table__.c.transaction_id.nullable is False
        assert TransactionPlannedExpense.__table__.c.planned_expense_id.nullable is False
        assert TransactionPlannedExpense.__table__.c.resolved_amount.nullable is False

    def test_repr(self):
        tpe = TransactionPlannedExpense(transaction_id=1, planned_expense_id=2)
        assert repr(tpe) == (
            "<TransactionPlannedExpense transaction_id=1 planned_expense_id=2>"
        )


# ---------------------------------------------------------------------------
# TransactionTag association table tests
# ---------------------------------------------------------------------------


class TestTransactionTagsTable:
    """Tests for the transaction_tags association table."""

    def test_table_name(self):
        assert transaction_tags.name == "transaction_tags"

    def test_columns(self):
        col_names = [c.name for c in transaction_tags.columns]
        assert "transaction_id" in col_names
        assert "tag_id" in col_names

    def test_composite_primary_key(self):
        """Both columns form the primary key."""
        pk_cols = [c.name for c in transaction_tags.primary_key.columns]
        assert set(pk_cols) == {"transaction_id", "tag_id"}


# ---------------------------------------------------------------------------
# SharedExpense model tests
# ---------------------------------------------------------------------------


class TestSharedExpenseModel:
    """Tests for the SharedExpense model definition."""

    def test_tablename(self):
        assert SharedExpense.__tablename__ == "shared_expenses"

    def test_non_nullable_fields(self):
        assert SharedExpense.__table__.c.transaction_id.nullable is False
        assert SharedExpense.__table__.c.created_at.nullable is False

    def test_repr(self):
        se = SharedExpense(id=3, transaction_id=10)
        assert repr(se) == "<SharedExpense 3 transaction_id=10>"


# ---------------------------------------------------------------------------
# SharedExpenseShare model tests
# ---------------------------------------------------------------------------


class TestSharedExpenseShareModel:
    """Tests for the SharedExpenseShare model definition."""

    def test_tablename(self):
        assert SharedExpenseShare.__tablename__ == "shared_expense_shares"

    def test_non_nullable_fields(self):
        assert SharedExpenseShare.__table__.c.shared_expense_id.nullable is False
        assert SharedExpenseShare.__table__.c.user_id.nullable is False
        assert SharedExpenseShare.__table__.c.amount.nullable is False
        assert SharedExpenseShare.__table__.c.settled.nullable is False

    def test_nullable_fields(self):
        assert SharedExpenseShare.__table__.c.settled_at.nullable is True

    def test_default_settled(self):
        assert SharedExpenseShare.__table__.c.settled.default.arg is False

    def test_repr(self):
        share = SharedExpenseShare(
            id=7, user_id=2, amount=Decimal("25.00"), settled=False
        )
        assert repr(share) == (
            "<SharedExpenseShare 7 user_id=2 amount=25.00 settled=False>"
        )


# ---------------------------------------------------------------------------
# RecurringRule model tests
# ---------------------------------------------------------------------------


class TestRecurringRuleModel:
    """Tests for the RecurringRule model definition."""

    def test_tablename(self):
        assert RecurringRule.__tablename__ == "recurring_rules"

    def test_non_nullable_fields(self):
        assert RecurringRule.__table__.c.name.nullable is False
        assert RecurringRule.__table__.c.type.nullable is False
        assert RecurringRule.__table__.c.frequency.nullable is False
        assert RecurringRule.__table__.c.interval.nullable is False
        assert RecurringRule.__table__.c.amount.nullable is False
        assert RecurringRule.__table__.c.next_due_date.nullable is False
        assert RecurringRule.__table__.c.active.nullable is False
        assert RecurringRule.__table__.c.scope.nullable is False
        assert RecurringRule.__table__.c.account_id.nullable is False
        assert RecurringRule.__table__.c.user_id.nullable is False
        assert RecurringRule.__table__.c.created_at.nullable is False

    def test_nullable_fields(self):
        assert RecurringRule.__table__.c.destination_account_id.nullable is True
        assert RecurringRule.__table__.c.category_id.nullable is True

    def test_default_active(self):
        assert RecurringRule.__table__.c.active.default.arg is True

    def test_interval_check_constraint(self):
        """Verify check constraint on interval range (1-365)."""
        found = any(
            getattr(c, "name", None) == "ck_recurring_rules_interval_range"
            for c in RecurringRule.__table__.constraints
        )
        assert found, "Check constraint ck_recurring_rules_interval_range not found"

    def test_amount_check_constraint(self):
        """Verify check constraint on amount range."""
        found = any(
            getattr(c, "name", None) == "ck_recurring_rules_amount_range"
            for c in RecurringRule.__table__.constraints
        )
        assert found, "Check constraint ck_recurring_rules_amount_range not found"

    def test_repr(self):
        rule = RecurringRule(name="Rent", frequency=RecurringFrequency.monthly)
        assert repr(rule) == "<RecurringRule 'Rent' (monthly)>"


# ---------------------------------------------------------------------------
# RecurringRuleSplit model tests
# ---------------------------------------------------------------------------


class TestRecurringRuleSplitModel:
    """Tests for the RecurringRuleSplit model definition."""

    def test_tablename(self):
        assert RecurringRuleSplit.__tablename__ == "recurring_rule_splits"

    def test_non_nullable_fields(self):
        assert RecurringRuleSplit.__table__.c.recurring_rule_id.nullable is False
        assert RecurringRuleSplit.__table__.c.category_id.nullable is False
        assert RecurringRuleSplit.__table__.c.amount.nullable is False

    def test_nullable_fields(self):
        assert RecurringRuleSplit.__table__.c.description.nullable is True

    def test_amount_positive_check_constraint(self):
        """Verify check constraint: amount > 0."""
        found = any(
            getattr(c, "name", None) == "ck_recurring_rule_splits_amount_positive"
            for c in RecurringRuleSplit.__table__.constraints
        )
        assert found, "Check constraint ck_recurring_rule_splits_amount_positive not found"

    def test_repr(self):
        split = RecurringRuleSplit(id=3, amount=Decimal("50.00"))
        assert repr(split) == "<RecurringRuleSplit 3 amount=50.00>"
