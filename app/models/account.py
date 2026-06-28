"""Account models for Haushaltsbuch.

Defines Account, AccountOwner, and AccountBalanceSnapshot tables with
enumerations for account type, scope, and snapshot source.

Validates: Requirements 2.1, 2.3, 27.1
"""

import enum
from datetime import datetime, timezone
from decimal import Decimal

from app.extensions import db


class AccountType(enum.Enum):
    """Account type classification."""

    spending = "spending"
    saving = "saving"
    credit_card = "credit_card"


class AccountScope(enum.Enum):
    """Account ownership scope."""

    personal = "personal"
    shared = "shared"


class SnapshotSource(enum.Enum):
    """Source of a balance snapshot."""

    automatic = "automatic"
    manual = "manual"


class Account(db.Model):
    """A financial account owned by a user.

    Supports spending, saving, and credit card types with personal or shared scope.
    """

    __tablename__ = "accounts"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    type = db.Column(db.Enum(AccountType), nullable=False)
    scope = db.Column(db.Enum(AccountScope), nullable=False)
    balance = db.Column(
        db.Numeric(12, 2), nullable=False, default=Decimal("0.0")
    )
    active = db.Column(db.Boolean, nullable=False, default=True)
    institute = db.Column(db.String(100), nullable=True)
    visible_to_partner = db.Column(db.Boolean, nullable=False, default=True)
    max_overdraft = db.Column(db.Numeric(12, 2), nullable=True)
    credit_limit = db.Column(db.Numeric(12, 2), nullable=True)
    statement_closing_day = db.Column(db.Integer, nullable=True)
    payment_due_day = db.Column(db.Integer, nullable=True)
    owner_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    owner = db.relationship("User", backref=db.backref("accounts", lazy="dynamic"))
    co_owners = db.relationship(
        "AccountOwner", back_populates="account", cascade="all, delete-orphan"
    )
    balance_snapshots = db.relationship(
        "AccountBalanceSnapshot", back_populates="account", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.CheckConstraint(
            "credit_limit IS NULL OR (credit_limit >= 0.01 AND credit_limit <= 999999999.99)",
            name="ck_accounts_credit_limit_range",
        ),
        db.CheckConstraint(
            "statement_closing_day IS NULL OR (statement_closing_day >= 1 AND statement_closing_day <= 28)",
            name="ck_accounts_statement_closing_day_range",
        ),
        db.CheckConstraint(
            "payment_due_day IS NULL OR (payment_due_day >= 1 AND payment_due_day <= 28)",
            name="ck_accounts_payment_due_day_range",
        ),
    )

    def __repr__(self) -> str:
        return f"<Account {self.name!r} ({self.type.value})>"


class AccountOwner(db.Model):
    """Links a user as co-owner of an account (shared accounts).

    The unique constraint on (account_id, user_id) prevents duplicate ownership.
    """

    __tablename__ = "account_owners"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(
        db.Integer, db.ForeignKey("accounts.id"), nullable=False
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    account = db.relationship("Account", back_populates="co_owners")
    user = db.relationship("User", backref=db.backref("co_owned_accounts", lazy="dynamic"))

    __table_args__ = (
        db.UniqueConstraint("account_id", "user_id", name="uq_account_owners_account_user"),
    )

    def __repr__(self) -> str:
        return f"<AccountOwner account_id={self.account_id} user_id={self.user_id}>"


class AccountBalanceSnapshot(db.Model):
    """Point-in-time snapshot of an account's balance.

    Created automatically on transaction posting or manually via balance corrections.
    """

    __tablename__ = "account_balance_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(
        db.Integer, db.ForeignKey("accounts.id"), nullable=False
    )
    balance = db.Column(db.Numeric(12, 2), nullable=False)
    snapshot_date = db.Column(db.Date, nullable=False)
    source = db.Column(db.Enum(SnapshotSource), nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    account = db.relationship("Account", back_populates="balance_snapshots")

    def __repr__(self) -> str:
        return (
            f"<AccountBalanceSnapshot account_id={self.account_id} "
            f"balance={self.balance} date={self.snapshot_date}>"
        )
