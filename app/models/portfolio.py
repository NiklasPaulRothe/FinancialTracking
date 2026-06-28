"""Investment Portfolio models for Haushaltsbuch.

Defines InvestmentPortfolio and InvestmentPortfolioOwner tables for
grouping ETF positions into named portfolios with scope and projection settings.

Validates: App description InvestmentPortfolio table
"""

from datetime import datetime, timezone
from decimal import Decimal

from app.extensions import db


class InvestmentPortfolio(db.Model):
    """A named collection of ETF positions with projection settings.

    Supports personal and shared scopes. Shared portfolios use the
    InvestmentPortfolioOwner table to link multiple users.
    """

    __tablename__ = "investment_portfolios"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    scope = db.Column(db.String(10), nullable=False)  # 'personal' or 'shared'
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    target_retirement_age = db.Column(db.Integer, nullable=True)
    assumed_annual_return = db.Column(
        db.Numeric(5, 4), nullable=True, default=Decimal("0.07")
    )
    monthly_contribution_target = db.Column(db.Numeric(12, 2), nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user = db.relationship(
        "User", backref=db.backref("investment_portfolios", lazy="dynamic")
    )
    owners = db.relationship(
        "InvestmentPortfolioOwner",
        back_populates="portfolio",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<InvestmentPortfolio {self.name!r} ({self.scope})>"


class InvestmentPortfolioOwner(db.Model):
    """Many-to-many relationship between Users and InvestmentPortfolios.

    Used for shared portfolios where both household members are co-owners.
    """

    __tablename__ = "investment_portfolio_owners"

    id = db.Column(db.Integer, primary_key=True)
    portfolio_id = db.Column(
        db.Integer, db.ForeignKey("investment_portfolios.id"), nullable=False
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    portfolio = db.relationship("InvestmentPortfolio", back_populates="owners")
    user = db.relationship(
        "User", backref=db.backref("portfolio_ownerships", lazy="dynamic")
    )

    __table_args__ = (
        db.UniqueConstraint(
            "portfolio_id", "user_id",
            name="uq_investment_portfolio_owners_portfolio_user",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<InvestmentPortfolioOwner portfolio_id={self.portfolio_id} "
            f"user_id={self.user_id}>"
        )
