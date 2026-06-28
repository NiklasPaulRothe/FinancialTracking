"""Notification service for Haushaltsbuch.

Implements centralised notification generation with per-cycle deduplication,
mark_read, and login cleanup logic.

Validates: Requirements 21.1, 21.2, 21.3, 21.4, 21.5, 21.6, 21.7
"""

from datetime import datetime, timezone
from typing import Optional

from app.extensions import db
from app.models.notification import Notification
from app.models.user import User
from app.services.banking_day_service import BankingDayService


# All valid notification types (Req 21.5)
NOTIFICATION_TYPES = frozenset([
    "budget_warning",
    "budget_exceeded",
    "credit_payment_due",
    "planned_expense_reminder",
    "recurring_rule_posted",
    "settlement_received",
    "etf_price_fetch_failed",
    "overdraft_limit_exceeded",
])


class NotificationService:
    """Centralised notification generation with deduplication.

    Provides methods to create notifications (with per-income-cycle
    deduplication), mark notifications as read, and clean up read
    notifications on login.
    """

    def __init__(self) -> None:
        self._banking_day_service = BankingDayService()

    def notify(
        self,
        user_id: int,
        type: str,
        entity_id: Optional[int],
        message: str,
        link_url: Optional[str] = None,
    ) -> Optional[Notification]:
        """Create a notification with per-cycle deduplication check.

        Validates: Requirements 21.1, 21.5, 21.7

        Only one notification per type per triggering entity per income
        cycle period is allowed. If a notification already exists for this
        combination within the current income cycle, no new notification
        is created.

        Args:
            user_id: The user to notify.
            type: Notification type (must be one of NOTIFICATION_TYPES).
            entity_id: Optional ID of the triggering entity.
            message: Human-readable message (max 500 characters).
            link_url: Optional URL to navigate to on click.

        Returns:
            The created Notification, or None if deduplicated (already exists).

        Raises:
            ValueError: If type is not a valid notification type.
        """
        if type not in NOTIFICATION_TYPES:
            raise ValueError(
                f"Invalid notification type: {type!r}. "
                f"Must be one of: {sorted(NOTIFICATION_TYPES)}"
            )

        if len(message) > 500:
            message = message[:500]

        # Per-cycle deduplication (Req 21.7)
        user = db.session.get(User, user_id)
        if user is None:
            raise ValueError(f"User with id {user_id} not found.")

        if self._is_duplicate_in_current_cycle(user, type, entity_id):
            return None

        notification = Notification(
            user_id=user_id,
            type=type,
            entity_id=entity_id,
            message=message,
            read=False,
            link_url=link_url,
        )

        db.session.add(notification)
        db.session.commit()
        return notification

    def mark_read(self, notification_id: int) -> Optional[Notification]:
        """Mark a notification as read.

        Validates: Requirement 21.3

        Args:
            notification_id: The notification to mark as read.

        Returns:
            The updated Notification, or None if not found.
        """
        notification = db.session.get(Notification, notification_id)
        if notification is None:
            return None

        notification.read = True
        db.session.commit()
        return notification

    def cleanup_on_login(self, user: User) -> int:
        """Delete read notifications created before login timestamp.

        Validates: Requirement 21.4

        Called on user login. Permanently deletes all notifications that
        were marked as read before the current login time.

        Args:
            user: The user who just logged in.

        Returns:
            The number of deleted notifications.
        """
        login_time = datetime.now(timezone.utc)

        count = Notification.query.filter(
            Notification.user_id == user.id,
            Notification.read == True,  # noqa: E712
            Notification.created_at < login_time,
        ).delete(synchronize_session="fetch")

        db.session.commit()
        return count

    def get_unread_count(self, user_id: int) -> int:
        """Get the count of unread notifications for a user.

        Validates: Requirement 21.1

        Args:
            user_id: The user to count for.

        Returns:
            The number of unread notifications.
        """
        return Notification.query.filter(
            Notification.user_id == user_id,
            Notification.read == False,  # noqa: E712
        ).count()

    def get_recent_notifications(self, user_id: int, limit: int = 30) -> list[Notification]:
        """Get the most recent notifications for a user.

        Validates: Requirement 21.2

        Returns both read and unread notifications ordered by creation
        date descending, limited to the specified count.

        Args:
            user_id: The user to fetch for.
            limit: Maximum number of notifications to return (default 30).

        Returns:
            List of Notification instances.
        """
        return (
            Notification.query.filter(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
            .all()
        )

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _is_duplicate_in_current_cycle(
        self, user: User, type: str, entity_id: Optional[int]
    ) -> bool:
        """Check if a notification of this type+entity already exists in the current income cycle.

        Validates: Requirement 21.7

        The income cycle period runs from the effective income day of the
        current period to the day before the next effective income day.

        Args:
            user: The user (provides income_day for cycle calculation).
            type: The notification type.
            entity_id: The triggering entity ID.

        Returns:
            True if a duplicate exists, False otherwise.
        """
        from datetime import date, timedelta

        today = date.today()

        # Calculate current income cycle boundaries
        cycle_start = self._get_current_cycle_start(user, today)

        # Query for existing notification of same type+entity within cycle
        query = Notification.query.filter(
            Notification.user_id == user.id,
            Notification.type == type,
            Notification.created_at >= datetime(
                cycle_start.year, cycle_start.month, cycle_start.day,
                tzinfo=timezone.utc
            ),
        )

        if entity_id is not None:
            query = query.filter(Notification.entity_id == entity_id)
        else:
            query = query.filter(Notification.entity_id.is_(None))

        return query.first() is not None

    def _get_current_cycle_start(self, user: User, reference_date) -> 'date':
        """Get the start date of the current income cycle.

        The cycle starts on the effective income day of the current period.
        If today is before this month's effective income day, the cycle
        started on last month's effective income day.

        Args:
            user: The user (provides income_day).
            reference_date: The reference date.

        Returns:
            The start date of the current income cycle.
        """
        from datetime import date

        # Get effective income day for this month
        effective_this_month = self._banking_day_service.get_effective_income_day(
            user.income_day, reference_date.year, reference_date.month
        )

        if reference_date >= effective_this_month:
            return effective_this_month
        else:
            # Cycle started last month
            if reference_date.month == 1:
                prev_year = reference_date.year - 1
                prev_month = 12
            else:
                prev_year = reference_date.year
                prev_month = reference_date.month - 1

            return self._banking_day_service.get_effective_income_day(
                user.income_day, prev_year, prev_month
            )
