"""Net worth models for Haushaltsbuch.

Defines the NetWorthSnapshot table for tracking total net worth over time.

Validates: Requirements 18.1, 18.2, 18.4
"""

from datetime import datetime, timezone
from decimal import Decimal

from app.extensions import db


class NetWorthSnapshot(db.Model):
    """Point-in-time snapshot of a user's total net worth.

    Computed daily by the scheduler as:
        sum(active account balances)
        + sum(shares × current_price for active ETF positions)
        − sum(active credit remaining_balances)

    The unique constraint on (user_id, snapshot_date) ensures at most one
    snapshot per user per day.
    """

    __tablename__ = "net_worth_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    total_account_balance = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal("0.00"))
    total_etf_value = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal("0.00"))
    total_credit_balance = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal("0.00"))
    total_value = db.Column(db.Numeric(14, 2), nullable=False)
    snapshot_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user = db.relationship(
        "User", backref=db.backref("net_worth_snapshots", lazy="dynamic")
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "snapshot_date", name="uq_net_worth_snapshots_user_date"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<NetWorthSnapshot user_id={self.user_id} "
            f"value={self.total_value} date={self.snapshot_date}>"
        )
