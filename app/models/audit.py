"""Audit Log model for Haushaltsbuch.

Defines the AuditLog table as an append-only immutable record of all
financial data changes. Entries track action type, target model, record ID,
before/after snapshots, the acting user, and a timestamp.

Validates: Requirements 22.1, 22.2, 22.3, 22.5
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import BigInteger

from app.extensions import db


class AuditAction(enum.Enum):
    """Types of actions tracked in the audit log."""

    create = "create"
    update = "update"
    delete = "delete"


class AuditLog(db.Model):
    """Immutable, append-only log of all financial record mutations.

    Application code MUST NOT update or delete AuditLog rows.
    Only the scheduled purge job (weekly, entries > 6 months) may
    remove entries via AuditService.purge_old_entries().

    Visibility rule (Req 22.5): A user sees entries where user_id
    matches their own ID, user_id is null (system actions), or the
    referenced record has scope "shared".
    """

    __tablename__ = "audit_logs"

    id = db.Column(BigInteger, primary_key=True, autoincrement=True)
    action = db.Column(db.Enum(AuditAction), nullable=False)
    model = db.Column(db.String(50), nullable=False)
    record_id = db.Column(db.Integer, nullable=False)
    old_values = db.Column(db.JSON, nullable=True)
    new_values = db.Column(db.JSON, nullable=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=True
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    # Relationships
    user = db.relationship(
        "User",
        backref=db.backref("audit_logs", lazy="dynamic"),
    )

    __table_args__ = (
        db.Index("ix_audit_logs_model_record", "model", "record_id"),
        db.Index("ix_audit_logs_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog {self.action.value} {self.model} "
            f"record_id={self.record_id}>"
        )
