"""BaV and VL models for Haushaltsbuch.

Defines BaV (Betriebliche Altersvorsorge), BaVContributionLog,
VL (Vermögenswirksame Leistungen), and VLContributionLog tables.

Validates: Requirements 15.1, 16.1
"""

import enum
from datetime import datetime, timezone
from decimal import Decimal

from app.extensions import db


class BaVType(enum.Enum):
    """BaV contract type classification."""

    direktversicherung = "direktversicherung"
    pensionskasse = "pensionskasse"
    pensionsfonds = "pensionsfonds"
    direktzusage = "direktzusage"
    unterstuetzungskasse = "unterstuetzungskasse"


class BaV(db.Model):
    """A betriebliche Altersvorsorge (company pension) contract."""

    __tablename__ = "bavs"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    provider = db.Column(db.String(100), nullable=False)
    contract_number = db.Column(db.String(100), nullable=True)
    type = db.Column(db.Enum(BaVType), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    retirement_date = db.Column(db.Date, nullable=True)
    employee_contribution_monthly = db.Column(db.Numeric(10, 2), nullable=False)
    employer_contribution_monthly = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    total_contribution_monthly = db.Column(db.Numeric(10, 2), nullable=False)
    guaranteed_payout_monthly = db.Column(db.Numeric(10, 2), nullable=True)
    projected_payout_monthly = db.Column(db.Numeric(10, 2), nullable=True)
    current_value = db.Column(db.Numeric(12, 2), nullable=True)
    current_value_updated_at = db.Column(db.Date, nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref=db.backref("bav_contracts", lazy="dynamic"))
    contribution_logs = db.relationship(
        "BaVContributionLog", back_populates="bav", cascade="all, delete-orphan",
        order_by="BaVContributionLog.month.desc()",
    )

    __table_args__ = (
        db.CheckConstraint(
            "employee_contribution_monthly >= 0.01 AND employee_contribution_monthly <= 50000.00",
            name="ck_bavs_employee_contribution_range",
        ),
        db.CheckConstraint(
            "employer_contribution_monthly >= 0.00 AND employer_contribution_monthly <= 50000.00",
            name="ck_bavs_employer_contribution_range",
        ),
    )


    def __repr__(self) -> str:
        return f"<BaV {self.provider!r} ({self.type.value})>"


class BaVContributionLog(db.Model):
    """Monthly contribution log entry for a BaV contract."""

    __tablename__ = "bav_contribution_logs"

    id = db.Column(db.Integer, primary_key=True)
    bav_id = db.Column(db.Integer, db.ForeignKey("bavs.id"), nullable=False)
    month = db.Column(db.Date, nullable=False)
    employee_amount = db.Column(db.Numeric(10, 2), nullable=False)
    employer_amount = db.Column(db.Numeric(10, 2), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    bav = db.relationship("BaV", back_populates="contribution_logs")

    __table_args__ = (
        db.UniqueConstraint("bav_id", "month", name="uq_bav_contribution_logs_bav_month"),
    )

    def __repr__(self) -> str:
        return f"<BaVContributionLog bav_id={self.bav_id} month={self.month}>"


class VL(db.Model):
    """Vermögenswirksame Leistungen (employer wealth-building benefit) contract."""

    __tablename__ = "vls"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    provider = db.Column(db.String(100), nullable=True)
    contract_number = db.Column(db.String(100), nullable=True)
    employer_contribution_monthly = db.Column(db.Numeric(10, 2), nullable=False)
    employee_contribution_monthly = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    total_contribution_monthly = db.Column(db.Numeric(10, 2), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    lock_up_end_date = db.Column(db.Date, nullable=False)
    etf_position_id = db.Column(db.Integer, db.ForeignKey("etf_positions.id"), nullable=True)
    linked_account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=True)
    qualifies_for_sparzulage = db.Column(db.Boolean, nullable=False, default=False)
    sparzulage_rate = db.Column(db.Numeric(5, 4), nullable=False, default=Decimal("0.20"))
    annual_eligible_max = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal("400.00"))
    active = db.Column(db.Boolean, nullable=False, default=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref=db.backref("vl_contracts", lazy="dynamic"))
    etf_position = db.relationship("ETFPosition", backref=db.backref("vl_contracts", lazy="dynamic"))
    linked_account = db.relationship("Account", backref=db.backref("vl_contracts", lazy="dynamic"))
    contribution_logs = db.relationship(
        "VLContributionLog", back_populates="vl", cascade="all, delete-orphan",
        order_by="VLContributionLog.month.desc()",
    )

    def __repr__(self) -> str:
        return f"<VL id={self.id} total={self.total_contribution_monthly}>"


class VLContributionLog(db.Model):
    """Monthly contribution log entry for a VL contract."""

    __tablename__ = "vl_contribution_logs"

    id = db.Column(db.Integer, primary_key=True)
    vl_id = db.Column(db.Integer, db.ForeignKey("vls.id"), nullable=False)
    month = db.Column(db.Date, nullable=False)
    employer_amount = db.Column(db.Numeric(10, 2), nullable=False)
    employee_amount = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    shares_bought = db.Column(db.Numeric(12, 6), nullable=True)
    price_per_share = db.Column(db.Numeric(12, 6), nullable=True)
    note = db.Column(db.String(255), nullable=True)
    etf_transaction_id = db.Column(db.Integer, db.ForeignKey("etf_transactions.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    vl = db.relationship("VL", back_populates="contribution_logs")
    etf_transaction = db.relationship("ETFTransaction", backref=db.backref("vl_contribution_log", uselist=False))

    __table_args__ = (
        db.UniqueConstraint("vl_id", "month", name="uq_vl_contribution_logs_vl_month"),
    )

    def __repr__(self) -> str:
        return f"<VLContributionLog vl_id={self.vl_id} month={self.month}>"
