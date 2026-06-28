"""Unit tests for AuditLog model and AuditService.

Tests cover:
- AuditLog model creation and field constraints
- AuditService.log_change for create/update/delete actions
- AuditService.purge_old_entries retention logic
- Append-only constraint (no update/delete via application code)
- Visibility filtering (user sees own + system + shared entries)

Validates: Requirements 22.1, 22.2, 22.3, 22.4, 22.5
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.extensions import db
from app.models.audit import AuditAction, AuditLog
from app.services.audit_service import AuditService
from tests.factories import UserFactory, AccountFactory


class TestAuditLogModel:
    """Tests for AuditLog model creation and field behavior."""

    def test_create_audit_log_entry(self, app, db_session):
        """AuditLog entry can be created with all fields."""
        user = UserFactory()
        db_session.flush()

        entry = AuditLog(
            action=AuditAction.create,
            model="Transaction",
            record_id=42,
            old_values=None,
            new_values={"amount": "100.00", "type": "expense"},
            user_id=user.id,
        )
        db_session.add(entry)
        db_session.flush()

        assert entry.id is not None
        assert entry.action == AuditAction.create
        assert entry.model == "Transaction"
        assert entry.record_id == 42
        assert entry.old_values is None
        assert entry.new_values == {"amount": "100.00", "type": "expense"}
        assert entry.user_id == user.id
        assert entry.created_at is not None

    def test_create_system_audit_log_entry(self, app, db_session):
        """System-generated entries have user_id=None (Req 22.2)."""
        entry = AuditLog(
            action=AuditAction.update,
            model="Credit",
            record_id=7,
            old_values={"accrued_interest": "0.00"},
            new_values={"accrued_interest": "1.23"},
            user_id=None,
        )
        db_session.add(entry)
        db_session.flush()

        assert entry.id is not None
        assert entry.user_id is None

    def test_audit_action_enum_values(self, app, db_session):
        """AuditAction enum has create, update, delete values."""
        assert AuditAction.create.value == "create"
        assert AuditAction.update.value == "update"
        assert AuditAction.delete.value == "delete"

    def test_audit_log_repr(self, app, db_session):
        """AuditLog __repr__ is informative."""
        entry = AuditLog(
            action=AuditAction.delete,
            model="Account",
            record_id=5,
        )
        assert "delete" in repr(entry)
        assert "Account" in repr(entry)
        assert "5" in repr(entry)

    def test_audit_log_stores_jsonb_values(self, app, db_session):
        """old_values and new_values support nested JSON structures."""
        user = UserFactory()
        db_session.flush()

        entry = AuditLog(
            action=AuditAction.update,
            model="Budget",
            record_id=10,
            old_values={"amount": "500.00", "name": "Groceries"},
            new_values={"amount": "600.00", "name": "Groceries"},
            user_id=user.id,
        )
        db_session.add(entry)
        db_session.flush()

        fetched = db_session.get(AuditLog, entry.id)
        assert fetched.old_values["amount"] == "500.00"
        assert fetched.new_values["amount"] == "600.00"


class TestAuditServiceLogChange:
    """Tests for AuditService.log_change method."""

    def test_log_create_action(self, app, db_session):
        """log_change with action='create' appends entry correctly (Req 22.1)."""
        user = UserFactory()
        db_session.flush()

        service = AuditService()
        entry = service.log_change(
            action="create",
            model="Transaction",
            record_id=1,
            old_values=None,
            new_values={"amount": "50.00", "type": "expense"},
            user_id=user.id,
        )

        assert entry.id is not None
        assert entry.action == AuditAction.create
        assert entry.model == "Transaction"
        assert entry.record_id == 1
        assert entry.old_values is None
        assert entry.new_values == {"amount": "50.00", "type": "expense"}
        assert entry.user_id == user.id

    def test_log_update_action(self, app, db_session):
        """log_change with action='update' records old and new values."""
        user = UserFactory()
        db_session.flush()

        service = AuditService()
        entry = service.log_change(
            action="update",
            model="Account",
            record_id=3,
            old_values={"name": "Old Name", "balance": "100.00"},
            new_values={"name": "New Name", "balance": "100.00"},
            user_id=user.id,
        )

        assert entry.action == AuditAction.update
        assert entry.old_values["name"] == "Old Name"
        assert entry.new_values["name"] == "New Name"

    def test_log_delete_action(self, app, db_session):
        """log_change with action='delete' records old values, new_values=None."""
        user = UserFactory()
        db_session.flush()

        service = AuditService()
        entry = service.log_change(
            action="delete",
            model="RecurringRule",
            record_id=99,
            old_values={"name": "Rent", "amount": "1200.00"},
            new_values=None,
            user_id=user.id,
        )

        assert entry.action == AuditAction.delete
        assert entry.old_values == {"name": "Rent", "amount": "1200.00"}
        assert entry.new_values is None

    def test_log_system_action_no_user(self, app, db_session):
        """log_change with user_id=None for system actions (Req 22.2)."""
        service = AuditService()
        entry = service.log_change(
            action="update",
            model="Credit",
            record_id=5,
            old_values={"accrued_interest": "0.0"},
            new_values={"accrued_interest": "0.12345"},
            user_id=None,
        )

        assert entry.user_id is None
        assert entry.action == AuditAction.update

    def test_log_change_invalid_action_raises(self, app, db_session):
        """log_change raises ValueError for invalid action strings."""
        service = AuditService()
        with pytest.raises(ValueError, match="Invalid audit action"):
            service.log_change(
                action="modify",
                model="Transaction",
                record_id=1,
            )

    def test_log_change_assigns_created_at(self, app, db_session):
        """log_change entry gets a created_at timestamp."""
        service = AuditService()
        before = datetime.now(timezone.utc)

        entry = service.log_change(
            action="create",
            model="Budget",
            record_id=2,
            new_values={"name": "Food"},
            user_id=None,
        )

        after = datetime.now(timezone.utc)
        assert before <= entry.created_at.replace(tzinfo=timezone.utc) <= after


class TestAuditServicePurge:
    """Tests for AuditService.purge_old_entries method."""

    def test_purge_removes_old_entries(self, app, db_session):
        """purge_old_entries removes entries older than retention period (Req 22.4)."""
        service = AuditService()

        # Create an old entry (200 days ago)
        old_entry = AuditLog(
            action=AuditAction.create,
            model="Transaction",
            record_id=1,
            new_values={"amount": "10.00"},
            user_id=None,
            created_at=datetime.now(timezone.utc) - timedelta(days=200),
        )
        db_session.add(old_entry)
        db_session.flush()

        # Create a recent entry (10 days ago)
        recent_entry = AuditLog(
            action=AuditAction.update,
            model="Account",
            record_id=2,
            old_values={"name": "A"},
            new_values={"name": "B"},
            user_id=None,
            created_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        db_session.add(recent_entry)
        db_session.flush()

        count = service.purge_old_entries(retention_days=180)

        assert count == 1
        # Old entry removed
        assert db_session.get(AuditLog, old_entry.id) is None
        # Recent entry preserved
        assert db_session.get(AuditLog, recent_entry.id) is not None

    def test_purge_preserves_entries_within_retention(self, app, db_session):
        """purge_old_entries does not remove entries within retention window."""
        service = AuditService()

        entry = AuditLog(
            action=AuditAction.create,
            model="Budget",
            record_id=1,
            new_values={"name": "Test"},
            user_id=None,
            created_at=datetime.now(timezone.utc) - timedelta(days=179),
        )
        db_session.add(entry)
        db_session.flush()

        count = service.purge_old_entries(retention_days=180)

        assert count == 0
        assert db_session.get(AuditLog, entry.id) is not None

    def test_purge_returns_zero_when_nothing_to_purge(self, app, db_session):
        """purge_old_entries returns 0 when no entries are old enough."""
        service = AuditService()
        count = service.purge_old_entries(retention_days=180)
        assert count == 0


class TestAuditServiceVisibility:
    """Tests for AuditService visibility filtering (Req 22.5)."""

    def test_user_sees_own_entries(self, app, db_session):
        """User can see their own audit log entries."""
        user = UserFactory()
        db_session.flush()

        service = AuditService()
        service.log_change(
            action="create",
            model="Transaction",
            record_id=1,
            new_values={"amount": "50.00"},
            user_id=user.id,
        )
        db_session.commit()

        entries = service.get_entries_for_user(user.id)
        assert len(entries) == 1
        assert entries[0].user_id == user.id

    def test_user_sees_system_entries(self, app, db_session):
        """User can see system entries (user_id=None)."""
        user = UserFactory()
        db_session.flush()

        service = AuditService()
        service.log_change(
            action="update",
            model="Credit",
            record_id=1,
            old_values={"accrued_interest": "0.0"},
            new_values={"accrued_interest": "1.0"},
            user_id=None,
        )
        db_session.commit()

        entries = service.get_entries_for_user(user.id)
        assert len(entries) == 1
        assert entries[0].user_id is None

    def test_user_does_not_see_other_user_entries(self, app, db_session):
        """User cannot see entries belonging to another user (Req 22.5)."""
        user_a = UserFactory(username="alice")
        user_b = UserFactory(username="bob")
        db_session.flush()

        service = AuditService()
        service.log_change(
            action="create",
            model="Transaction",
            record_id=1,
            new_values={"amount": "100.00"},
            user_id=user_b.id,
        )
        db_session.commit()

        entries = service.get_entries_for_user(user_a.id)
        assert len(entries) == 0

    def test_filter_by_model(self, app, db_session):
        """get_entries_for_user supports model_filter parameter."""
        user = UserFactory()
        db_session.flush()

        service = AuditService()
        service.log_change(action="create", model="Transaction", record_id=1, user_id=user.id)
        service.log_change(action="create", model="Account", record_id=2, user_id=user.id)
        db_session.commit()

        entries = service.get_entries_for_user(user.id, model_filter="Transaction")
        assert len(entries) == 1
        assert entries[0].model == "Transaction"

    def test_filter_by_action(self, app, db_session):
        """get_entries_for_user supports action_filter parameter."""
        user = UserFactory()
        db_session.flush()

        service = AuditService()
        service.log_change(action="create", model="Transaction", record_id=1, user_id=user.id)
        service.log_change(action="delete", model="Transaction", record_id=2, user_id=user.id)
        db_session.commit()

        entries = service.get_entries_for_user(user.id, action_filter="delete")
        assert len(entries) == 1
        assert entries[0].action == AuditAction.delete

    def test_get_entries_for_record(self, app, db_session):
        """get_entries_for_record returns all entries for a specific record."""
        user = UserFactory()
        db_session.flush()

        service = AuditService()
        service.log_change(
            action="create", model="Transaction", record_id=42,
            new_values={"amount": "10.00"}, user_id=user.id,
        )
        service.log_change(
            action="update", model="Transaction", record_id=42,
            old_values={"amount": "10.00"}, new_values={"amount": "20.00"},
            user_id=user.id,
        )
        service.log_change(
            action="create", model="Transaction", record_id=99,
            new_values={"amount": "5.00"}, user_id=user.id,
        )
        db_session.commit()

        entries = service.get_entries_for_record("Transaction", 42)
        assert len(entries) == 2
        assert all(e.record_id == 42 for e in entries)

    def test_pagination(self, app, db_session):
        """get_entries_for_user respects limit and offset."""
        user = UserFactory()
        db_session.flush()

        service = AuditService()
        for i in range(5):
            service.log_change(
                action="create", model="Transaction", record_id=i,
                user_id=user.id,
            )
        db_session.commit()

        page1 = service.get_entries_for_user(user.id, limit=2, offset=0)
        page2 = service.get_entries_for_user(user.id, limit=2, offset=2)

        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].record_id != page2[0].record_id


class TestAuditLogAppendOnly:
    """Tests ensuring append-only constraint in application code (Req 22.3).

    The AuditService intentionally provides no update or delete methods
    for individual entries. Only purge_old_entries removes rows.
    """

    def test_service_has_no_update_method(self, app, db_session):
        """AuditService does not expose an update method."""
        service = AuditService()
        assert not hasattr(service, "update_entry")
        assert not hasattr(service, "update")

    def test_service_has_no_delete_method(self, app, db_session):
        """AuditService does not expose a delete method for individual entries."""
        service = AuditService()
        assert not hasattr(service, "delete_entry")
        assert not hasattr(service, "delete")

    def test_only_purge_can_remove_entries(self, app, db_session):
        """Only purge_old_entries removes entries (not individual deletion)."""
        service = AuditService()

        entry = service.log_change(
            action="create",
            model="Transaction",
            record_id=1,
            new_values={"test": True},
            user_id=None,
        )
        db_session.commit()

        # Entry is persisted
        assert db_session.get(AuditLog, entry.id) is not None

        # purge_old_entries with 0 retention would remove it
        # but with default 180 days, recent entry stays
        count = service.purge_old_entries(retention_days=180)
        assert count == 0
        assert db_session.get(AuditLog, entry.id) is not None
