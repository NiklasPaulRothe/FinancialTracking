"""Notification model for Haushaltsbuch.

Defines the notifications and notification_preferences tables for in-app alerts
and user-configurable notification type preferences.

Validates: Requirements 21.1, 21.6
"""

from datetime import datetime, timezone

from app.extensions import db


class Notification(db.Model):
    """An in-app notification for budget warnings, payment reminders, and system events.

    Attributes:
        id: Primary key.
        user_id: The user receiving the notification.
        type: Notification type (budget_warning, budget_exceeded, credit_payment_due,
              planned_expense_reminder, recurring_rule_posted, settlement_received,
              etf_price_fetch_failed, overdraft_limit_exceeded).
        entity_id: Optional ID of the triggering entity (budget, credit, etc.).
        message: Human-readable notification message (up to 500 chars).
        read: Whether the notification has been read.
        link_url: Optional URL to navigate to when clicked.
        created_at: Timestamp when the notification was created.
    """

    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    type = db.Column(db.String(50), nullable=False, index=True)
    entity_id = db.Column(db.Integer, nullable=True)
    message = db.Column(db.String(500), nullable=False)
    read = db.Column(db.Boolean, nullable=False, default=False)
    link_url = db.Column(db.String(255), nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<Notification {self.type!r} user={self.user_id}>"


class NotificationPreference(db.Model):
    """User preference for a specific notification type.

    Controls whether a given notification type is enabled or disabled for a user.
    If no preference row exists for a notification type, notifications are enabled
    by default.

    Validates: Requirement 21.6
    """

    __tablename__ = "notification_preferences"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    notification_type = db.Column(db.String(50), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user = db.relationship(
        "User", backref=db.backref("notification_preferences", lazy="dynamic")
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "notification_type",
            name="uq_notification_preferences_user_type",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationPreference user_id={self.user_id} "
            f"type={self.notification_type!r} enabled={self.enabled}>"
        )
