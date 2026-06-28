"""PlannedExpense model for Haushaltsbuch.

Defines the PlannedExpense table for tracking future expenses that may or may
not have a fixed amount, and optionally block available balance.

Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
"""

import enum
from datetime import datetime, timezone
from decimal import Decimal

from app.extensions import db


class PlannedExpenseScope(enum.Enum):
    """Planned expense ownership scope."""

    personal = "personal"
    shared = "shared"


class PlannedExpense(db.Model):
    """A future expense that optionally blocks available balance.

    Supports exact amounts, ranges (min/max), or no amount. When blocking is
    True and the expense has a non-null amount, it reduces the linked account's
    available balance until resolved.

    Validates: Requirements 9.1, 9.2
    """

    __tablename__ = "planned_expenses"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    amount_exact = db.Column(db.Numeric(12, 2), nullable=True)
    amount_min = db.Column(db.Numeric(12, 2), nullable=True)
    amount_max = db.Column(db.Numeric(12, 2), nullable=True)
    category_id = db.Column(
        db.Integer, db.ForeignKey("categories.id"), nullable=True
    )
    scope = db.Column(db.Enum(PlannedExpenseScope), nullable=False)
    account_id = db.Column(
        db.Integer, db.ForeignKey("accounts.id"), nullable=True
    )
    blocking = db.Column(db.Boolean, nullable=False, default=True)
    note = db.Column(db.String(255), nullable=True)
    resolved = db.Column(db.Boolean, nullable=False, default=False)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Track whether amount_exact was set from resolving a range
    _amount_from_range = db.Column(
        "amount_from_range", db.Boolean, nullable=False, default=False
    )

    # Relationships
    user = db.relationship(
        "User", backref=db.backref("planned_expenses", lazy="dynamic")
    )
    account = db.relationship(
        "Account", backref=db.backref("planned_expenses", lazy="dynamic")
    )
    category = db.relationship(
        "Category", backref=db.backref("planned_expenses", lazy="dynamic")
    )

    __table_args__ = (
        db.CheckConstraint(
            "amount_exact IS NULL OR (amount_exact >= 0.01 AND amount_exact <= 999999999.99)",
            name="ck_planned_expenses_amount_exact_range",
        ),
        db.CheckConstraint(
            "amount_min IS NULL OR (amount_min >= 0.01 AND amount_min <= 999999999.99)",
            name="ck_planned_expenses_amount_min_range",
        ),
        db.CheckConstraint(
            "amount_max IS NULL OR (amount_max >= 0.01 AND amount_max <= 999999999.99)",
            name="ck_planned_expenses_amount_max_range",
        ),
    )

    @property
    def is_range(self) -> bool:
        """Return True if this expense uses a range (min/max) rather than exact."""
        return self.amount_min is not None or self.amount_max is not None

    @property
    def blocking_amount(self) -> Decimal:
        """Get the amount to deduct from available balance.

        Returns amount_exact if set, otherwise amount_min for ranges.
        Returns 0 if no amounts are set.

        Validates: Requirement 9.2
        """
        if self.amount_exact is not None:
            return self.amount_exact
        if self.amount_min is not None:
            return self.amount_min
        return Decimal("0.00")

    @property
    def display_amount(self) -> str:
        """Human-readable amount string."""
        if self.amount_exact is not None:
            return f"{self.amount_exact:.2f} \u20ac"
        elif self.amount_min is not None and self.amount_max is not None:
            return f"{self.amount_min:.2f} \u2013 {self.amount_max:.2f} \u20ac"
        elif self.amount_min is not None:
            return f"ab {self.amount_min:.2f} \u20ac"
        elif self.amount_max is not None:
            return f"bis {self.amount_max:.2f} \u20ac"
        return "Kein Betrag"

    def __repr__(self) -> str:
        return f"<PlannedExpense {self.id} {self.name!r} resolved={self.resolved}>"
