"""Unit tests for Account, AccountOwner, and AccountBalanceSnapshot models.

Validates: Requirements 2.1, 2.3, 27.1
"""

import pytest
from datetime import date, datetime, timezone
from decimal import Decimal

from app.models.account import (
    Account,
    AccountOwner,
    AccountBalanceSnapshot,
    AccountType,
    AccountScope,
    SnapshotSource,
)


class TestAccountType:
    """Tests for AccountType enum."""

    def test_enum_values(self):
        assert AccountType.spending.value == "spending"
        assert AccountType.saving.value == "saving"
        assert AccountType.credit_card.value == "credit_card"

    def test_enum_count(self):
        assert len(AccountType) == 3


class TestAccountScope:
    """Tests for AccountScope enum."""

    def test_enum_values(self):
        assert AccountScope.personal.value == "personal"
        assert AccountScope.shared.value == "shared"

    def test_enum_count(self):
        assert len(AccountScope) == 2


class TestSnapshotSource:
    """Tests for SnapshotSource enum."""

    def test_enum_values(self):
        assert SnapshotSource.automatic.value == "automatic"
        assert SnapshotSource.manual.value == "manual"

    def test_enum_count(self):
        assert len(SnapshotSource) == 2


class TestAccountModel:
    """Tests for the Account model definition."""

    def test_tablename(self):
        assert Account.__tablename__ == "accounts"

    def test_default_balance(self):
        account = Account(
            name="Test", type=AccountType.spending, scope=AccountScope.personal
        )
        assert account.balance is None  # defaults applied on DB insert

    def test_default_active(self):
        account = Account(
            name="Test", type=AccountType.spending, scope=AccountScope.personal
        )
        # Default is set at DB level; Python-side may be None before flush
        # but the column definition has default=True
        assert Account.__table__.c.active.default.arg is True

    def test_default_visible_to_partner(self):
        assert Account.__table__.c.visible_to_partner.default.arg is True

    def test_nullable_fields(self):
        """Credit card fields, institute, max_overdraft should be nullable."""
        assert Account.__table__.c.institute.nullable is True
        assert Account.__table__.c.max_overdraft.nullable is True
        assert Account.__table__.c.credit_limit.nullable is True
        assert Account.__table__.c.statement_closing_day.nullable is True
        assert Account.__table__.c.payment_due_day.nullable is True

    def test_non_nullable_fields(self):
        """Required fields should not be nullable."""
        assert Account.__table__.c.name.nullable is False
        assert Account.__table__.c.balance.nullable is False
        assert Account.__table__.c.active.nullable is False
        assert Account.__table__.c.visible_to_partner.nullable is False
        assert Account.__table__.c.owner_id.nullable is False
        assert Account.__table__.c.created_at.nullable is False

    def test_repr(self):
        account = Account(name="Girokonto", type=AccountType.spending)
        assert repr(account) == "<Account 'Girokonto' (spending)>"


class TestAccountOwnerModel:
    """Tests for the AccountOwner model definition."""

    def test_tablename(self):
        assert AccountOwner.__tablename__ == "account_owners"

    def test_non_nullable_fields(self):
        assert AccountOwner.__table__.c.account_id.nullable is False
        assert AccountOwner.__table__.c.user_id.nullable is False
        assert AccountOwner.__table__.c.created_at.nullable is False

    def test_unique_constraint_exists(self):
        """Verify unique constraint on (account_id, user_id)."""
        constraints = AccountOwner.__table__.constraints
        unique_constraints = [
            c for c in constraints if hasattr(c, "columns") and len(c.columns) == 2
        ]
        # Find the named unique constraint
        found = any(
            getattr(c, "name", None) == "uq_account_owners_account_user"
            for c in constraints
        )
        assert found, "Unique constraint uq_account_owners_account_user not found"

    def test_repr(self):
        ao = AccountOwner(account_id=1, user_id=2)
        assert repr(ao) == "<AccountOwner account_id=1 user_id=2>"


class TestAccountBalanceSnapshotModel:
    """Tests for the AccountBalanceSnapshot model definition."""

    def test_tablename(self):
        assert AccountBalanceSnapshot.__tablename__ == "account_balance_snapshots"

    def test_non_nullable_fields(self):
        assert AccountBalanceSnapshot.__table__.c.account_id.nullable is False
        assert AccountBalanceSnapshot.__table__.c.balance.nullable is False
        assert AccountBalanceSnapshot.__table__.c.snapshot_date.nullable is False
        assert AccountBalanceSnapshot.__table__.c.source.nullable is False
        assert AccountBalanceSnapshot.__table__.c.created_at.nullable is False

    def test_repr(self):
        snap = AccountBalanceSnapshot(
            account_id=1,
            balance=Decimal("1234.56"),
            snapshot_date=date(2024, 6, 15),
        )
        expected = (
            "<AccountBalanceSnapshot account_id=1 balance=1234.56 date=2024-06-15>"
        )
        assert repr(snap) == expected
