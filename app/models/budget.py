"""Budget model for Haushaltsbuch.

Defines the Budget table with spending limit tracking per category or total,
scoped to personal or shared, with configurable period aligned to income_day.

Validates: Requirements 6.1, 6.2, 6.6, 6.7, 6.8
"""

import enum
from datetime import datetime, timezone

from app.extensions import db


class BudgetScope(enum.Enum):
    """Budget ownership scope."""

    personal = "personal"
    shared = "shared"


class BudgetPeriod(enum.Enum):
    """Budget period type for utilisation calculation."""

    weekly = "weekly"
    monthly = "monthly"
    quarterly = "quarterly"
    yearly = "yearly"


class Budget(db.Model):
    """A spending limit tied to a category or overall, tracked per income cycle period.

    When category_id is NULL, the budget acts as a total spending cap for all
    expense-type transactions within the configured scope (Req 6.6).

    Shared budgets include expenses from both household members (Req 6.7).
    """

    __tablename__ = "budgets"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    scope = db.Column(db.Enum(BudgetScope), nullable=False)
    category_id = db.Column(
        db.Integer, db.ForeignKey("categories.id"), nullable=True
    )
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    period = db.Column(db.Enum(BudgetPeriod), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    reference_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=True
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user = db.relationship(
        "User", foreign_keys=[user_id], backref=db.backref("budgets", lazy="dynamic")
    )
    reference_user = db.relationship("User", foreign_keys=[reference_user_id])
    category = db.relationship("Category", backref=db.backref("budgets", lazy="dynamic"))

    __table_args__ = (
        db.CheckConstraint(
            "amount >= 0.01 AND amount <= 999999999.99",
            name="ck_budgets_amount_range",
        ),
    )

    def __repr__(self) -> str:
        return f"<Budget {self.name!r} ({self.period.value})>"


# ---------------------------------------------------------------------------
# Saving Goal Enumerations
# ---------------------------------------------------------------------------


class SavingGoalScope(enum.Enum):
    """Saving goal ownership scope."""

    personal = "personal"
    shared = "shared"


class SavingGoalStatus(enum.Enum):
    """Saving goal lifecycle status."""

    active = "active"
    completed = "completed"
    cancelled = "cancelled"


# ---------------------------------------------------------------------------
# Saving Goal and Contribution Models
# ---------------------------------------------------------------------------


class SavingGoal(db.Model):
    """A saving goal with optional target amount.

    Users can create saving goals with contributions that block amounts
    from account available balances. Goals can be open-ended (no target)
    or have a specific target amount to track progress.

    Validates: Requirement 10.1
    """

    __tablename__ = "saving_goals"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    target_amount = db.Column(db.Numeric(12, 2), nullable=True)
    scope = db.Column(db.Enum(SavingGoalScope), nullable=False)
    status = db.Column(
        db.Enum(SavingGoalStatus), nullable=False, default=SavingGoalStatus.active
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user = db.relationship(
        "User", backref=db.backref("saving_goals", lazy="dynamic")
    )
    contributions = db.relationship(
        "SavingContribution",
        back_populates="saving_goal",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.CheckConstraint(
            "target_amount IS NULL OR (target_amount >= 0.01 AND target_amount <= 999999999.99)",
            name="ck_saving_goals_target_amount_range",
        ),
    )

    def __repr__(self) -> str:
        return f"<SavingGoal {self.name!r} ({self.status.value})>"


class SavingContribution(db.Model):
    """A contribution to a saving goal from a specific account.

    Each contribution blocks its amount from the linked account's
    available balance until the goal is completed or cancelled.

    Validates: Requirement 10.2
    """

    __tablename__ = "saving_contributions"

    id = db.Column(db.Integer, primary_key=True)
    saving_goal_id = db.Column(
        db.Integer, db.ForeignKey("saving_goals.id"), nullable=False
    )
    account_id = db.Column(
        db.Integer, db.ForeignKey("accounts.id"), nullable=False
    )
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    note = db.Column(db.String(255), nullable=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    saving_goal = db.relationship("SavingGoal", back_populates="contributions")
    account = db.relationship(
        "Account", backref=db.backref("saving_contributions", lazy="dynamic")
    )
    user = db.relationship(
        "User", backref=db.backref("saving_contributions", lazy="dynamic")
    )

    __table_args__ = (
        db.CheckConstraint(
            "amount >= 0.01 AND amount <= 999999999.99",
            name="ck_saving_contributions_amount_range",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SavingContribution goal_id={self.saving_goal_id} "
            f"account_id={self.account_id} amount={self.amount}>"
        )
