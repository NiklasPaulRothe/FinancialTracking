"""Audit service for Haushaltsbuch.

Implements append-only audit logging for all financial record mutations
and scheduled purge of entries older than 6 months.

Validates: Requirements 22.1, 22.2, 22.3, 22.4, 22.5
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import or_

from app.extensions import db
from app.models.audit import AuditAction, AuditLog


class AuditService:
    """Append-only audit logging for all financial record mutations.

    This service provides:
    - log_change: append a new entry (Req 22.1, 22.2)
    - purge_old_entries: remove entries older than 6 months (Req 22.4)
    - get_entries_for_user: visibility-filtered retrieval (Req 22.5)
    - get_entries_for_record: history for a specific record

    Application code MUST NOT update or delete AuditLog entries directly.
    Only purge_old_entries (called by the weekly scheduler job) may delete rows.
    """

    def log_change(
        self,
        action: str,
        model: str,
        record_id: int,
        old_values: Optional[dict] = None,
        new_values: Optional[dict] = None,
        user_id: Optional[int] = None,
    ) -> AuditLog:
        """Append an audit log entry for a financial record mutation.

        Validates: Requirements 22.1, 22.2

        Args:
            action: One of 'create', 'update', 'delete'.
            model: Name of the model being modified (e.g. 'Transaction').
            record_id: Primary key of the affected record.
            old_values: Snapshot of fields before the change (None for create).
            new_values: Snapshot of fields after the change (None for delete).
            user_id: The acting user's ID, or None for system-generated actions.

        Returns:
            The newly created AuditLog entry.

        Raises:
            ValueError: If action is not a valid AuditAction value.
        """
        try:
            audit_action = AuditAction(action)
        except ValueError:
            raise ValueError(
                f"Invalid audit action: {action!r}. "
                f"Must be one of: 'create', 'update', 'delete'."
            )

        entry = AuditLog(
            action=audit_action,
            model=model,
            record_id=record_id,
            old_values=old_values,
            new_values=new_values,
            user_id=user_id,
        )

        db.session.add(entry)
        db.session.flush()  # Assign ID immediately without full commit
        return entry

    def purge_old_entries(self, retention_days: int = 180) -> int:
        """Remove audit log entries older than the retention period.

        Validates: Requirement 22.4

        Called by the weekly scheduler job (Sundays). Removes all
        AuditLog entries whose created_at is older than the specified
        retention period (default 6 months = 180 days).

        Args:
            retention_days: Number of days to retain entries (default 180).

        Returns:
            The number of deleted entries.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        count = AuditLog.query.filter(
            AuditLog.created_at < cutoff
        ).delete(synchronize_session="fetch")

        db.session.commit()
        return count

    def get_entries_for_user(
        self,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
        model_filter: Optional[str] = None,
        action_filter: Optional[str] = None,
    ) -> list[AuditLog]:
        """Retrieve audit log entries visible to a specific user.

        Validates: Requirement 22.5

        Visibility rules:
        - User sees own entries (user_id matches).
        - User sees system entries (user_id is null).

        Args:
            user_id: The authenticated user requesting entries.
            limit: Maximum number of entries to return.
            offset: Number of entries to skip for pagination.
            model_filter: Optional filter by model name.
            action_filter: Optional filter by action type.

        Returns:
            List of AuditLog entries ordered by created_at descending.
        """
        query = AuditLog.query.filter(
            or_(
                AuditLog.user_id == user_id,
                AuditLog.user_id.is_(None),
            )
        )

        if model_filter:
            query = query.filter(AuditLog.model == model_filter)

        if action_filter:
            try:
                action_enum = AuditAction(action_filter)
                query = query.filter(AuditLog.action == action_enum)
            except ValueError:
                pass  # Invalid filter value, skip filtering

        return (
            query.order_by(AuditLog.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def get_entries_for_record(
        self,
        model: str,
        record_id: int,
        user_id: Optional[int] = None,
    ) -> list[AuditLog]:
        """Retrieve all audit log entries for a specific record.

        Args:
            model: The model name (e.g. 'Transaction').
            record_id: The record's primary key.
            user_id: If provided, apply visibility filtering.

        Returns:
            List of AuditLog entries for the record, ordered chronologically.
        """
        query = AuditLog.query.filter(
            AuditLog.model == model,
            AuditLog.record_id == record_id,
        )

        if user_id is not None:
            query = query.filter(
                or_(
                    AuditLog.user_id == user_id,
                    AuditLog.user_id.is_(None),
                )
            )

        return query.order_by(AuditLog.created_at.asc()).all()
