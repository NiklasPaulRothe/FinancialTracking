"""Credit models for Haushaltsbuch.

Defines Credit, CreditPayment, and CreditForecastCache tables with
enumerations for credit status and scope.

Validates: Requirements 11.1, 11.4, 11.7
"""

import enum
from datetime import datetime, timezone
from decimal import Decimal

from app.extensions import db


class CreditStatus(enum.Enum):
    """Credit lifecycle status."""

    active = "active"
    paid_off = "paid_off"


class CreditScope(enum.Enum):
    """Credit ownership scope."""

    personal = "personal"
    shared = "shared"


class Credit(db.Model):
    """A credit/loan tracked by the user.

    Supports personal and shared scopes with interest tracking
    and optional conversion from credit card payments.
    """

    __tablename__ = "credits"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    principal = db.Column(db.Numeric(12, 2), nullable=False)
    remaining_balance = db.Column(db.Numeric(12, 2), nullable=False)
    accrued_interest = db.Column(
        db.Numeric(12, 6), nullable=False, default=Decimal("0.000000")
    )
    effective_yearly_rate = db.Column(db.Numeric(7, 6), nullable=False)
    disbursement_date = db.Column(db.Date, nullable=False)
    interest_capitalization_day = db.Column(db.Integer, nullable=False)
    status = db.Column(
        db.Enum(CreditStatus), nullable=False, default=CreditStatus.active
    )
    scope = db.Column(db.Enum(CreditScope), nullable=False)
    account_id = db.Column(
        db.Integer, db.ForeignKey("accounts.id"), nullable=False
    )
    converted_from_credit_card_payment = db.Column(
        db.Boolean, nullable=False, default=False
    )
    fixed_interest_amount = db.Column(
        db.Numeric(12, 2), nullable=True
    )
    linked_transaction_id = db.Column(
        db.Integer, db.ForeignKey("transactions.id"), nullable=True
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    account = db.relationship("Account", backref=db.backref("credits", lazy="dynamic"))
    linked_transaction = db.relationship("Transaction", foreign_keys=[linked_transaction_id])
    user = db.relationship("User", backref=db.backref("credits", lazy="dynamic"))
    payments = db.relationship(
        "CreditPayment", back_populates="credit", cascade="all, delete-orphan"
    )
    forecast_cache = db.relationship(
        "CreditForecastCache", back_populates="credit", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.CheckConstraint(
            "principal >= 0.01 AND principal <= 999999999.99",
            name="ck_credits_principal_range",
        ),
        db.CheckConstraint(
            "effective_yearly_rate >= 0.0 AND effective_yearly_rate <= 1.0",
            name="ck_credits_rate_range",
        ),
        db.CheckConstraint(
            "interest_capitalization_day >= 1 AND interest_capitalization_day <= 28",
            name="ck_credits_capitalization_day_range",
        ),
    )

    def __repr__(self) -> str:
        return f"<Credit {self.name!r} ({self.status.value})>"

    @property
    def uses_fixed_interest(self) -> bool:
        """Return True if this credit uses a fixed interest amount instead of a rate."""
        return self.fixed_interest_amount is not None

    @property
    def total_owed(self) -> Decimal:
        """Total amount owed: remaining_balance + interest (fixed or accrued)."""
        if self.uses_fixed_interest:
            return self.remaining_balance + self.fixed_interest_amount
        return self.remaining_balance + self.accrued_interest


class CreditPayment(db.Model):
    """A payment made towards a credit.

    Links a transaction to a credit with breakdown of interest vs principal portions.
    """

    __tablename__ = "credit_payments"

    id = db.Column(db.Integer, primary_key=True)
    credit_id = db.Column(
        db.Integer, db.ForeignKey("credits.id"), nullable=False
    )
    transaction_id = db.Column(
        db.Integer, db.ForeignKey("transactions.id"), nullable=False
    )
    total_amount = db.Column(db.Numeric(12, 2), nullable=False)
    interest_portion = db.Column(db.Numeric(12, 2), nullable=False)
    principal_portion = db.Column(db.Numeric(12, 2), nullable=False)
    manual_correction = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    credit = db.relationship("Credit", back_populates="payments")
    transaction = db.relationship("Transaction", backref=db.backref("credit_payment", uselist=False))

    def __repr__(self) -> str:
        return (
            f"<CreditPayment credit_id={self.credit_id} "
            f"total={self.total_amount}>"
        )


class CreditForecastCache(db.Model):
    """Cached projection of future credit balance and interest.

    Pre-computed for performance; recalculated when credit terms change.
    """

    __tablename__ = "credit_forecast_cache"

    id = db.Column(db.Integer, primary_key=True)
    credit_id = db.Column(
        db.Integer, db.ForeignKey("credits.id"), nullable=False
    )
    month_offset = db.Column(db.Integer, nullable=False)
    projected_balance = db.Column(db.Numeric(12, 2), nullable=False)
    projected_interest = db.Column(db.Numeric(12, 2), nullable=False)
    recalculated_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    credit = db.relationship("Credit", back_populates="forecast_cache")

    def __repr__(self) -> str:
        return (
            f"<CreditForecastCache credit_id={self.credit_id} "
            f"month_offset={self.month_offset}>"
        )


class CreditRepaymentSchedule(db.Model):
    """Defines the recurring repayment rule for a credit.

    Links a credit to a recurring rule for automated repayment transaction
    generation via the existing APScheduler mechanism.
    """

    __tablename__ = "credit_repayment_schedules"

    id = db.Column(db.Integer, primary_key=True)
    credit_id = db.Column(
        db.Integer, db.ForeignKey("credits.id"), nullable=False
    )
    recurring_rule_id = db.Column(
        db.Integer, db.ForeignKey("recurring_rules.id"), nullable=False
    )
    payment_amount = db.Column(db.Numeric(12, 2), nullable=False)
    note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    credit = db.relationship(
        "Credit", backref=db.backref("repayment_schedule", uselist=False)
    )
    recurring_rule = db.relationship(
        "RecurringRule", backref=db.backref("credit_repayment_schedule", uselist=False)
    )

    __table_args__ = (
        db.CheckConstraint(
            "payment_amount >= 0.01 AND payment_amount <= 999999999.99",
            name="ck_credit_repayment_schedules_amount_range",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CreditRepaymentSchedule credit_id={self.credit_id} "
            f"amount={self.payment_amount}>"
        )
