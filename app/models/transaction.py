"""Transaction and related models for Haushaltsbuch.

Defines Transaction, TransactionSplit, TransactionPlannedExpense,
TransactionTag, SharedExpense, SharedExpenseShare, RecurringRule,
and RecurringRuleSplit tables with enumerations.

Validates: Requirements 3.1, 4.1, 9.3
"""

import enum
from datetime import datetime, timezone
from decimal import Decimal

from app.extensions import db


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class TransactionType(enum.Enum):
    """Transaction type classification."""

    income = "income"
    expense = "expense"
    transfer = "transfer"
    credit_card_payment = "credit_card_payment"


class TransactionScope(enum.Enum):
    """Transaction ownership scope (personal vs shared)."""

    personal = "personal"
    shared = "shared"


class RecurringFrequency(enum.Enum):
    """Frequency for recurring rules."""

    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    quarterly = "quarterly"
    yearly = "yearly"


# ---------------------------------------------------------------------------
# Tag model (stub — full implementation in a later task)
# ---------------------------------------------------------------------------


class Tag(db.Model):
    """A user-defined tag for categorising transactions.

    Full implementation (unique constraints, service logic) will be added in
    a later task. This stub exists so the TransactionTag relationship resolves.
    """

    __tablename__ = "tags"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(30), nullable=False)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )

    __table_args__ = (
        db.UniqueConstraint("name", "user_id", name="uq_tags_name_user"),
    )

    def __repr__(self) -> str:
        return f"<Tag {self.name!r}>"


# ---------------------------------------------------------------------------
# Association table: TransactionTag
# ---------------------------------------------------------------------------

transaction_tags = db.Table(
    "transaction_tags",
    db.Column(
        "transaction_id",
        db.Integer,
        db.ForeignKey("transactions.id"),
        primary_key=True,
    ),
    db.Column(
        "tag_id",
        db.Integer,
        db.ForeignKey("tags.id"),
        primary_key=True,
    ),
)

recurring_rule_tags = db.Table(
    "recurring_rule_tags",
    db.Column(
        "recurring_rule_id",
        db.Integer,
        db.ForeignKey("recurring_rules.id"),
        primary_key=True,
    ),
    db.Column(
        "tag_id",
        db.Integer,
        db.ForeignKey("tags.id"),
        primary_key=True,
    ),
)


# ---------------------------------------------------------------------------
# Transaction model
# ---------------------------------------------------------------------------


class Transaction(db.Model):
    """A financial transaction (income, expense, transfer, or credit card payment).

    Supports split categorisation, tags, planned expense resolution, and
    shared expense tracking.
    """

    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.Enum(TransactionType), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    scope = db.Column(db.Enum(TransactionScope), nullable=False)
    account_id = db.Column(
        db.Integer, db.ForeignKey("accounts.id"), nullable=True
    )
    destination_account_id = db.Column(
        db.Integer, db.ForeignKey("accounts.id"), nullable=True
    )
    category_id = db.Column(
        db.Integer, db.ForeignKey("categories.id"), nullable=True
    )
    recurring_rule_id = db.Column(
        db.Integer, db.ForeignKey("recurring_rules.id"), nullable=True
    )
    posted = db.Column(db.Boolean, nullable=False, default=True)
    statement_closing_date = db.Column(db.Date, nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    paid = db.Column(db.Boolean, nullable=False, default=False)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user = db.relationship("User", backref=db.backref("transactions", lazy="dynamic"))
    account = db.relationship(
        "Account", foreign_keys=[account_id], backref=db.backref("transactions", lazy="dynamic")
    )
    destination_account = db.relationship(
        "Account", foreign_keys=[destination_account_id]
    )
    recurring_rule = db.relationship("RecurringRule", backref=db.backref("transactions", lazy="dynamic"))
    splits = db.relationship(
        "TransactionSplit", back_populates="transaction", cascade="all, delete-orphan"
    )
    planned_expenses = db.relationship(
        "TransactionPlannedExpense", back_populates="transaction", cascade="all, delete-orphan"
    )
    shared_expenses = db.relationship(
        "SharedExpense", back_populates="transaction", cascade="all, delete-orphan"
    )
    # Tags relationship (Tag model defined above)
    tags = db.relationship(
        "Tag", secondary=transaction_tags, backref=db.backref("transactions", lazy="dynamic")
    )

    __table_args__ = (
        db.CheckConstraint(
            "amount >= 0.01 AND amount <= 999999999.99",
            name="ck_transactions_amount_range",
        ),
    )

    def __repr__(self) -> str:
        return f"<Transaction {self.id} {self.type.value} {self.amount}>"


# ---------------------------------------------------------------------------
# TransactionSplit model
# ---------------------------------------------------------------------------


class TransactionSplit(db.Model):
    """A category split within a transaction.

    Allows a single transaction to be distributed across multiple categories.
    The sum of split amounts should equal the transaction amount.
    """

    __tablename__ = "transaction_splits"

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(
        db.Integer, db.ForeignKey("transactions.id"), nullable=False
    )
    category_id = db.Column(
        db.Integer, db.ForeignKey("categories.id"), nullable=False
    )
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    description = db.Column(db.String(255), nullable=True)

    # Relationships
    transaction = db.relationship("Transaction", back_populates="splits")

    __table_args__ = (
        db.CheckConstraint(
            "amount > 0",
            name="ck_transaction_splits_amount_positive",
        ),
    )

    def __repr__(self) -> str:
        return f"<TransactionSplit {self.id} amount={self.amount}>"


# ---------------------------------------------------------------------------
# TransactionPlannedExpense model
# ---------------------------------------------------------------------------


class TransactionPlannedExpense(db.Model):
    """Junction table linking transactions to planned expenses they resolve."""

    __tablename__ = "transaction_planned_expenses"

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(
        db.Integer, db.ForeignKey("transactions.id"), nullable=False
    )
    planned_expense_id = db.Column(
        db.Integer, db.ForeignKey("planned_expenses.id"), nullable=False
    )
    resolved_amount = db.Column(db.Numeric(12, 2), nullable=False)

    # Relationships
    transaction = db.relationship("Transaction", back_populates="planned_expenses")

    def __repr__(self) -> str:
        return (
            f"<TransactionPlannedExpense transaction_id={self.transaction_id} "
            f"planned_expense_id={self.planned_expense_id}>"
        )


# ---------------------------------------------------------------------------
# SharedExpense model
# ---------------------------------------------------------------------------


class SharedExpense(db.Model):
    """Marks a transaction as a shared expense between household members."""

    __tablename__ = "shared_expenses"

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(
        db.Integer, db.ForeignKey("transactions.id"), nullable=False
    )
    paid_by_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    total_amount = db.Column(db.Numeric(12, 2), nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    transaction = db.relationship("Transaction", back_populates="shared_expenses")
    paid_by_user = db.relationship(
        "User", backref=db.backref("shared_expenses_paid", lazy="dynamic")
    )
    shares = db.relationship(
        "SharedExpenseShare", back_populates="shared_expense", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<SharedExpense {self.id} transaction_id={self.transaction_id}>"


# ---------------------------------------------------------------------------
# SharedExpenseShare model
# ---------------------------------------------------------------------------


class SharedExpenseShare(db.Model):
    """Individual user's share of a shared expense."""

    __tablename__ = "shared_expense_shares"

    id = db.Column(db.Integer, primary_key=True)
    shared_expense_id = db.Column(
        db.Integer, db.ForeignKey("shared_expenses.id"), nullable=False
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    share_percentage = db.Column(db.Numeric(5, 4), nullable=False)
    settled = db.Column(db.Boolean, nullable=False, default=False)
    settled_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    shared_expense = db.relationship("SharedExpense", back_populates="shares")
    user = db.relationship("User", backref=db.backref("shared_expense_shares", lazy="dynamic"))

    def __repr__(self) -> str:
        return (
            f"<SharedExpenseShare {self.id} user_id={self.user_id} "
            f"amount={self.amount} settled={self.settled}>"
        )


# ---------------------------------------------------------------------------
# Settlement model
# ---------------------------------------------------------------------------


class Settlement(db.Model):
    """A repayment between household members for shared expense balances.

    Validates: Requirements 12.2, 12.7
    """

    __tablename__ = "settlements"

    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    date = db.Column(db.Date, nullable=False)
    from_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    to_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    from_user = db.relationship(
        "User", foreign_keys=[from_user_id],
        backref=db.backref("settlements_made", lazy="dynamic"),
    )
    to_user = db.relationship(
        "User", foreign_keys=[to_user_id],
        backref=db.backref("settlements_received", lazy="dynamic"),
    )
    allocations = db.relationship(
        "SettlementAllocation", back_populates="settlement", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.CheckConstraint(
            "amount >= 0.01 AND amount <= 999999999.99",
            name="ck_settlements_amount_range",
        ),
        db.CheckConstraint(
            "from_user_id != to_user_id",
            name="ck_settlements_different_users",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Settlement {self.id} amount={self.amount} "
            f"from_user_id={self.from_user_id} to_user_id={self.to_user_id}>"
        )


# ---------------------------------------------------------------------------
# SettlementAllocation model
# ---------------------------------------------------------------------------


class SettlementAllocation(db.Model):
    """Tracks how a settlement amount is allocated to individual SharedExpenseShares.

    Validates: Requirements 12.2, 12.7
    """

    __tablename__ = "settlement_allocations"

    id = db.Column(db.Integer, primary_key=True)
    settlement_id = db.Column(
        db.Integer, db.ForeignKey("settlements.id"), nullable=False
    )
    shared_expense_share_id = db.Column(
        db.Integer, db.ForeignKey("shared_expense_shares.id"), nullable=False
    )
    amount = db.Column(db.Numeric(12, 2), nullable=False)

    # Relationships
    settlement = db.relationship("Settlement", back_populates="allocations")
    shared_expense_share = db.relationship(
        "SharedExpenseShare",
        backref=db.backref("settlement_allocations", lazy="dynamic"),
    )

    def __repr__(self) -> str:
        return (
            f"<SettlementAllocation {self.id} settlement_id={self.settlement_id} "
            f"share_id={self.shared_expense_share_id} amount={self.amount}>"
        )


# ---------------------------------------------------------------------------
# RecurringRule model
# ---------------------------------------------------------------------------


class RecurringRule(db.Model):
    """A rule for generating recurring transactions automatically.

    Defines the pattern (frequency, interval, amount) and tracks the next
    due date for automatic transaction generation.
    """

    __tablename__ = "recurring_rules"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.Enum(TransactionType), nullable=False)
    frequency = db.Column(db.Enum(RecurringFrequency), nullable=False)
    interval = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    next_due_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    scope = db.Column(db.Enum(TransactionScope), nullable=False)
    account_id = db.Column(
        db.Integer, db.ForeignKey("accounts.id"), nullable=True
    )
    destination_account_id = db.Column(
        db.Integer, db.ForeignKey("accounts.id"), nullable=True
    )
    category_id = db.Column(
        db.Integer, db.ForeignKey("categories.id"), nullable=True
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user = db.relationship("User", backref=db.backref("recurring_rules", lazy="dynamic"))
    account = db.relationship(
        "Account", foreign_keys=[account_id], backref=db.backref("recurring_rules", lazy="dynamic")
    )
    destination_account = db.relationship(
        "Account", foreign_keys=[destination_account_id]
    )
    splits = db.relationship(
        "RecurringRuleSplit", back_populates="recurring_rule", cascade="all, delete-orphan"
    )
    tags = db.relationship(
        "Tag", secondary=recurring_rule_tags, backref=db.backref("recurring_rules", lazy="dynamic")
    )

    __table_args__ = (
        db.CheckConstraint(
            "\"interval\" >= 1 AND \"interval\" <= 365",
            name="ck_recurring_rules_interval_range",
        ),
        db.CheckConstraint(
            "amount >= 0.01 AND amount <= 999999999.99",
            name="ck_recurring_rules_amount_range",
        ),
    )

    def __repr__(self) -> str:
        return f"<RecurringRule {self.name!r} ({self.frequency.value})>"


# ---------------------------------------------------------------------------
# RecurringRuleSplit model
# ---------------------------------------------------------------------------


class RecurringRuleSplit(db.Model):
    """A category split template for a recurring rule.

    When a recurring rule generates a transaction, these splits are copied
    to TransactionSplit records.
    """

    __tablename__ = "recurring_rule_splits"

    id = db.Column(db.Integer, primary_key=True)
    recurring_rule_id = db.Column(
        db.Integer, db.ForeignKey("recurring_rules.id"), nullable=False
    )
    category_id = db.Column(
        db.Integer, db.ForeignKey("categories.id"), nullable=False
    )
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    description = db.Column(db.String(255), nullable=True)

    # Relationships
    recurring_rule = db.relationship("RecurringRule", back_populates="splits")

    __table_args__ = (
        db.CheckConstraint(
            "amount > 0",
            name="ck_recurring_rule_splits_amount_positive",
        ),
    )

    def __repr__(self) -> str:
        return f"<RecurringRuleSplit {self.id} amount={self.amount}>"
