"""ETF models for Haushaltsbuch.

Defines ETFPosition, ETFTransaction, ETFPriceHistory, and ETFSavingsPlan tables
with enumerations for ETF transaction types.

Validates: Requirements 13.1, 13.5, 14.1
"""

import enum
from datetime import datetime, timezone
from decimal import Decimal

from app.extensions import db


class ETFTransactionType(enum.Enum):
    """ETF transaction type: buy or sell."""

    buy = "buy"
    sell = "sell"


class ETFPosition(db.Model):
    """An ETF holding in the user's portfolio.

    Tracks shares, average buy price, current market price, and
    whether to use a manual price override.
    """

    __tablename__ = "etf_positions"

    id = db.Column(db.Integer, primary_key=True)
    portfolio_id = db.Column(
        db.Integer, db.ForeignKey("investment_portfolios.id"), nullable=True
    )
    isin = db.Column(db.String(12), nullable=True)
    ticker = db.Column(db.String(10), nullable=False)
    exchange_suffix = db.Column(db.String(10), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    shares = db.Column(
        db.Numeric(12, 6), nullable=False, default=Decimal("0.000000")
    )
    average_buy_price = db.Column(
        db.Numeric(12, 6), nullable=False, default=Decimal("0.000000")
    )
    current_price = db.Column(db.Numeric(12, 4), nullable=True)
    current_price_updated_at = db.Column(db.DateTime, nullable=True)
    manual_price_override = db.Column(
        db.Boolean, nullable=False, default=False
    )
    consecutive_fetch_failures = db.Column(
        db.Integer, nullable=False, default=0
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    portfolio = db.relationship(
        "InvestmentPortfolio", backref=db.backref("positions", lazy="dynamic")
    )
    user = db.relationship(
        "User", backref=db.backref("etf_positions", lazy="dynamic")
    )
    transactions = db.relationship(
        "ETFTransaction",
        back_populates="position",
        cascade="all, delete-orphan",
    )
    price_history = db.relationship(
        "ETFPriceHistory",
        back_populates="position",
        cascade="all, delete-orphan",
    )
    savings_plan = db.relationship(
        "ETFSavingsPlan",
        back_populates="position",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.CheckConstraint(
            "shares >= 0",
            name="ck_etf_positions_shares_non_negative",
        ),
        db.CheckConstraint(
            "average_buy_price >= 0",
            name="ck_etf_positions_avg_price_non_negative",
        ),
    )

    def __repr__(self) -> str:
        return f"<ETFPosition {self.ticker}.{self.exchange_suffix} shares={self.shares}>"


class ETFTransaction(db.Model):
    """A buy or sell transaction for an ETF position."""

    __tablename__ = "etf_transactions"

    id = db.Column(db.Integer, primary_key=True)
    position_id = db.Column(
        db.Integer, db.ForeignKey("etf_positions.id"), nullable=False
    )
    type = db.Column(db.Enum(ETFTransactionType), nullable=False)
    shares_quantity = db.Column(db.Numeric(12, 6), nullable=False)
    price_per_share = db.Column(db.Numeric(12, 6), nullable=False)
    total_amount = db.Column(db.Numeric(12, 2), nullable=False)
    fee = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    note = db.Column(db.String(255), nullable=True)
    linked_account_id = db.Column(
        db.Integer, db.ForeignKey("accounts.id"), nullable=True
    )
    recurring_rule_id = db.Column(
        db.Integer, db.ForeignKey("recurring_rules.id"), nullable=True
    )
    date = db.Column(db.Date, nullable=False)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    position = db.relationship("ETFPosition", back_populates="transactions")
    linked_account = db.relationship(
        "Account", backref=db.backref("etf_transactions", lazy="dynamic")
    )
    recurring_rule = db.relationship(
        "RecurringRule", backref=db.backref("etf_transactions", lazy="dynamic")
    )
    user = db.relationship(
        "User", backref=db.backref("etf_transactions", lazy="dynamic")
    )

    __table_args__ = (
        db.CheckConstraint(
            "shares_quantity > 0",
            name="ck_etf_transactions_shares_positive",
        ),
        db.CheckConstraint(
            "price_per_share > 0",
            name="ck_etf_transactions_price_positive",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ETFTransaction {self.type.value} "
            f"shares={self.shares_quantity} @ {self.price_per_share}>"
        )


class ETFPriceHistory(db.Model):
    """Historical price record for an ETF position."""

    __tablename__ = "etf_price_history"

    id = db.Column(db.Integer, primary_key=True)
    position_id = db.Column(
        db.Integer, db.ForeignKey("etf_positions.id"), nullable=False
    )
    price = db.Column(db.Numeric(12, 4), nullable=False)
    date = db.Column(db.Date, nullable=False)

    # Relationships
    position = db.relationship("ETFPosition", back_populates="price_history")

    __table_args__ = (
        db.UniqueConstraint(
            "position_id", "date", name="uq_etf_price_history_position_date"
        ),
    )

    def __repr__(self) -> str:
        return f"<ETFPriceHistory position_id={self.position_id} date={self.date}>"


class ETFSavingsPlan(db.Model):
    """A recurring ETF purchase plan linked to a position and recurring rule."""

    __tablename__ = "etf_savings_plans"

    id = db.Column(db.Integer, primary_key=True)
    position_id = db.Column(
        db.Integer, db.ForeignKey("etf_positions.id"), nullable=False
    )
    recurring_rule_id = db.Column(
        db.Integer, db.ForeignKey("recurring_rules.id"), nullable=False
    )
    linked_account_id = db.Column(
        db.Integer, db.ForeignKey("accounts.id"), nullable=False
    )
    shares_per_execution = db.Column(db.Numeric(12, 6), nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    position = db.relationship("ETFPosition", back_populates="savings_plan")
    recurring_rule = db.relationship(
        "RecurringRule", backref=db.backref("etf_savings_plan", uselist=False)
    )
    linked_account = db.relationship(
        "Account", backref=db.backref("etf_savings_plans", lazy="dynamic")
    )
    user = db.relationship(
        "User", backref=db.backref("etf_savings_plans", lazy="dynamic")
    )

    def __repr__(self) -> str:
        return (
            f"<ETFSavingsPlan position_id={self.position_id} "
            f"active={self.active}>"
        )
