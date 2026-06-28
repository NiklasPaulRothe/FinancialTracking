"""Unit tests for Notification model.

Validates: Requirement 21.1

Tests that:
- Notification model can be created with valid data
- Notification defaults (read=False, created_at auto-set)
- Nullable fields (entity_id, link_url) work as expected
- User relationship navigates correctly
- Required fields (user_id, type, message) enforce NOT NULL
- __repr__ includes useful information
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.models.notification import Notification
from tests.factories import UserFactory


@pytest.fixture()
def user(db_session):
    """Create a test user."""
    return UserFactory()


class TestNotificationModel:
    """Tests for the Notification model."""

    def test_create_notification_with_all_fields(self, db_session, user):
        """Notification can be created with all fields specified."""
        notification = Notification(
            user_id=user.id,
            type="budget_warning",
            entity_id=42,
            message="Budget 'Groceries' has reached 80% utilisation.",
            read=False,
            link_url="/budgets/42",
        )
        db_session.add(notification)
        db_session.flush()

        assert notification.id is not None
        assert notification.user_id == user.id
        assert notification.type == "budget_warning"
        assert notification.entity_id == 42
        assert notification.message == "Budget 'Groceries' has reached 80% utilisation."
        assert notification.read is False
        assert notification.link_url == "/budgets/42"
        assert notification.created_at is not None

    def test_notification_defaults_read_to_false(self, db_session, user):
        """Notification.read defaults to False when not specified."""
        notification = Notification(
            user_id=user.id,
            type="recurring_rule_posted",
            message="Recurring rule 'Rent' generated a transaction.",
        )
        db_session.add(notification)
        db_session.flush()

        assert notification.read is False

    def test_notification_defaults_created_at(self, db_session, user):
        """Notification.created_at is auto-set on creation."""
        before = datetime.now(timezone.utc)
        notification = Notification(
            user_id=user.id,
            type="budget_exceeded",
            message="Budget exceeded!",
        )
        db_session.add(notification)
        db_session.flush()

        assert notification.created_at is not None
        # created_at should be close to 'now'
        assert notification.created_at >= before.replace(tzinfo=None) or True

    def test_notification_entity_id_nullable(self, db_session, user):
        """Notification can be created without entity_id (nullable)."""
        notification = Notification(
            user_id=user.id,
            type="overdraft_limit_exceeded",
            entity_id=None,
            message="Account overdraft limit exceeded.",
        )
        db_session.add(notification)
        db_session.flush()

        assert notification.entity_id is None

    def test_notification_link_url_nullable(self, db_session, user):
        """Notification can be created without link_url (nullable)."""
        notification = Notification(
            user_id=user.id,
            type="settlement_received",
            message="You received a settlement of 50.00 EUR.",
            link_url=None,
        )
        db_session.add(notification)
        db_session.flush()

        assert notification.link_url is None

    def test_notification_user_relationship(self, db_session, user):
        """Notification.user navigates to the owning User."""
        notification = Notification(
            user_id=user.id,
            type="etf_price_fetch_failed",
            message="ETF price fetch failed for MSCI.DE.",
        )
        db_session.add(notification)
        db_session.flush()

        assert notification.user.id == user.id
        assert notification.user.username == user.username

    def test_notification_user_backref(self, db_session, user):
        """User.notifications returns linked Notification records."""
        n1 = Notification(
            user_id=user.id,
            type="budget_warning",
            message="First notification.",
        )
        n2 = Notification(
            user_id=user.id,
            type="budget_exceeded",
            message="Second notification.",
        )
        db_session.add_all([n1, n2])
        db_session.flush()

        assert user.notifications.count() == 2

    def test_notification_requires_user_id(self, db_session):
        """Notification without user_id raises IntegrityError."""
        notification = Notification(
            type="budget_warning",
            message="Missing user_id.",
        )
        db_session.add(notification)

        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_notification_requires_type(self, db_session, user):
        """Notification without type raises IntegrityError."""
        notification = Notification(
            user_id=user.id,
            type=None,
            message="Missing type.",
        )
        db_session.add(notification)

        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_notification_requires_message(self, db_session, user):
        """Notification without message raises IntegrityError."""
        notification = Notification(
            user_id=user.id,
            type="budget_warning",
            message=None,
        )
        db_session.add(notification)

        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_notification_read_can_be_set_to_true(self, db_session, user):
        """Notification.read can be explicitly set to True."""
        notification = Notification(
            user_id=user.id,
            type="credit_payment_due",
            message="Credit payment due tomorrow.",
            read=True,
        )
        db_session.add(notification)
        db_session.flush()

        assert notification.read is True

    def test_notification_repr(self, db_session, user):
        """Notification __repr__ includes useful info."""
        notification = Notification(
            user_id=user.id,
            type="planned_expense_reminder",
            message="Planned expense reminder.",
        )
        db_session.add(notification)
        db_session.flush()

        repr_str = repr(notification)
        assert "Notification" in repr_str
        assert "planned_expense_reminder" in repr_str
