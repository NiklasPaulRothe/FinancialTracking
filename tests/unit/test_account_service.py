"""Unit tests for AccountService.

Tests CRUD operations, co-owner logic, dependency checks, and visibility filtering.

Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 28.1, 28.2, 28.4
"""

import pytest
from decimal import Decimal

from app.models.account import Account, AccountOwner, AccountType, AccountScope
from app.models.user import User
from app.services.account_service import AccountService
from app.exceptions import DependencyBlocksDeletion


@pytest.fixture()
def service():
    """Create an AccountService instance."""
    return AccountService()


@pytest.fixture()
def user1(db_session):
    """Create first household user."""
    user = User(
        username="alice",
        email="alice@example.com",
        password_hash="fakehash",
        income_day=25,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def user2(db_session):
    """Create second household user (partner)."""
    user = User(
        username="bob",
        email="bob@example.com",
        password_hash="fakehash",
        income_day=15,
    )
    db_session.add(user)
    db_session.flush()
    return user


class TestCreateAccount:
    """Tests for AccountService.create_account."""

    def test_create_spending_account_defaults(self, db_session, service, user1):
        """Creating a spending account sets balance=0, active=True, visible_to_partner=True."""
        account = service.create_account(
            user=user1,
            name="Checking",
            type=AccountType.spending,
            scope=AccountScope.personal,
        )

        assert account.id is not None
        assert account.name == "Checking"
        assert account.type == AccountType.spending
        assert account.scope == AccountScope.personal
        assert account.balance == Decimal("0.0")
        assert account.active is True
        assert account.visible_to_partner is True
        assert account.owner_id == user1.id

    def test_create_credit_card_with_fields(self, db_session, service, user1):
        """Credit card accounts accept credit-specific fields."""
        account = service.create_account(
            user=user1,
            name="Visa",
            type=AccountType.credit_card,
            scope=AccountScope.personal,
            credit_limit=Decimal("5000.00"),
            statement_closing_day=15,
            payment_due_day=28,
        )

        assert account.type == AccountType.credit_card
        assert account.credit_limit == Decimal("5000.00")
        assert account.statement_closing_day == 15
        assert account.payment_due_day == 28

    def test_create_shared_account(self, db_session, service, user1):
        """Shared accounts are created with scope=shared."""
        account = service.create_account(
            user=user1,
            name="Joint",
            type=AccountType.spending,
            scope=AccountScope.shared,
        )

        assert account.scope == AccountScope.shared

    def test_create_account_with_institute(self, db_session, service, user1):
        """Institute field is stored when provided."""
        account = service.create_account(
            user=user1,
            name="Savings",
            type=AccountType.saving,
            scope=AccountScope.personal,
            institute="Deutsche Bank",
        )

        assert account.institute == "Deutsche Bank"

    def test_create_account_visible_to_partner_false(self, db_session, service, user1):
        """visible_to_partner can be set to False on creation."""
        account = service.create_account(
            user=user1,
            name="Secret",
            type=AccountType.spending,
            scope=AccountScope.personal,
            visible_to_partner=False,
        )

        assert account.visible_to_partner is False

    def test_create_account_with_string_type_and_scope(self, db_session, service, user1):
        """String values for type and scope are converted to enums."""
        account = service.create_account(
            user=user1,
            name="Test",
            type="saving",
            scope="shared",
        )

        assert account.type == AccountType.saving
        assert account.scope == AccountScope.shared


class TestEditAccount:
    """Tests for AccountService.edit_account."""

    def test_edit_name(self, db_session, service, user1):
        """Editing account name updates it successfully."""
        account = service.create_account(
            user=user1, name="Old Name", type=AccountType.spending,
            scope=AccountScope.personal,
        )

        updated = service.edit_account(account.id, user1, name="New Name")
        assert updated.name == "New Name"

    def test_edit_institute(self, db_session, service, user1):
        """Editing institute updates it."""
        account = service.create_account(
            user=user1, name="Acct", type=AccountType.spending,
            scope=AccountScope.personal,
        )

        updated = service.edit_account(account.id, user1, institute="Sparkasse")
        assert updated.institute == "Sparkasse"

    def test_edit_visible_to_partner(self, db_session, service, user1):
        """Editing visible_to_partner flag."""
        account = service.create_account(
            user=user1, name="Acct", type=AccountType.spending,
            scope=AccountScope.personal,
        )

        updated = service.edit_account(account.id, user1, visible_to_partner=False)
        assert updated.visible_to_partner is False

    def test_edit_credit_card_fields(self, db_session, service, user1):
        """Credit card accounts allow editing credit-specific fields."""
        account = service.create_account(
            user=user1, name="CC", type=AccountType.credit_card,
            scope=AccountScope.personal, credit_limit=Decimal("1000.00"),
        )

        updated = service.edit_account(
            account.id, user1,
            credit_limit=Decimal("2000.00"),
            statement_closing_day=20,
            payment_due_day=5,
        )

        assert updated.credit_limit == Decimal("2000.00")
        assert updated.statement_closing_day == 20
        assert updated.payment_due_day == 5

    def test_edit_non_credit_card_ignores_credit_fields(self, db_session, service, user1):
        """Non-credit-card accounts ignore credit_limit updates."""
        account = service.create_account(
            user=user1, name="Spending", type=AccountType.spending,
            scope=AccountScope.personal,
        )

        updated = service.edit_account(
            account.id, user1, credit_limit=Decimal("5000.00")
        )

        assert updated.credit_limit is None

    def test_edit_nonexistent_account_raises(self, db_session, service, user1):
        """Editing a non-existent account raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            service.edit_account(99999, user1, name="X")

    def test_edit_account_no_access_raises(self, db_session, service, user1, user2):
        """User without access cannot edit."""
        account = service.create_account(
            user=user1, name="Private", type=AccountType.spending,
            scope=AccountScope.personal,
        )

        with pytest.raises(ValueError, match="does not have access"):
            service.edit_account(account.id, user2, name="Hacked")


class TestDeactivateAccount:
    """Tests for AccountService.deactivate_account."""

    def test_deactivate_sets_active_false(self, db_session, service, user1):
        """Deactivating an account sets active=False."""
        account = service.create_account(
            user=user1, name="Acct", type=AccountType.spending,
            scope=AccountScope.personal,
        )

        deactivated = service.deactivate_account(account.id, user1)
        assert deactivated.active is False

    def test_deactivate_nonexistent_raises(self, db_session, service, user1):
        """Deactivating a non-existent account raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            service.deactivate_account(99999, user1)


class TestDeleteAccount:
    """Tests for AccountService.delete_account."""

    def test_delete_account_no_dependencies(self, db_session, service, user1):
        """Deleting an account with no dependencies succeeds."""
        account = service.create_account(
            user=user1, name="ToDelete", type=AccountType.spending,
            scope=AccountScope.personal,
        )
        account_id = account.id

        service.delete_account(account_id, user1)

        assert db_session.get(Account, account_id) is None

    def test_delete_account_removes_co_owners(self, db_session, service, user1, user2):
        """Deleting an account also removes AccountOwner records."""
        account = service.create_account(
            user=user1, name="Shared", type=AccountType.spending,
            scope=AccountScope.shared,
        )
        service.add_co_owner(account.id, user1, "bob")
        account_id = account.id

        service.delete_account(account_id, user1)

        assert AccountOwner.query.filter_by(account_id=account_id).count() == 0

    def test_delete_nonexistent_raises(self, db_session, service, user1):
        """Deleting a non-existent account raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            service.delete_account(99999, user1)


class TestAddCoOwner:
    """Tests for AccountService.add_co_owner."""

    def test_add_co_owner_success(self, db_session, service, user1, user2):
        """Successfully adding a partner as co-owner."""
        account = service.create_account(
            user=user1, name="Joint", type=AccountType.spending,
            scope=AccountScope.shared,
        )

        co_owner_record = service.add_co_owner(account.id, user1, "bob")

        assert co_owner_record.account_id == account.id
        assert co_owner_record.user_id == user2.id

    def test_add_co_owner_self_raises(self, db_session, service, user1, user2):
        """Cannot add yourself as co-owner."""
        account = service.create_account(
            user=user1, name="Acct", type=AccountType.spending,
            scope=AccountScope.shared,
        )

        with pytest.raises(ValueError, match="Cannot add yourself"):
            service.add_co_owner(account.id, user1, "alice")

    def test_add_co_owner_nonexistent_user_raises(self, db_session, service, user1, user2):
        """Adding a non-existent username raises ValueError."""
        account = service.create_account(
            user=user1, name="Acct", type=AccountType.spending,
            scope=AccountScope.shared,
        )

        with pytest.raises(ValueError, match="does not exist"):
            service.add_co_owner(account.id, user1, "nonexistent")

    def test_add_co_owner_already_co_owner_raises(self, db_session, service, user1, user2):
        """Adding an already existing co-owner raises ValueError."""
        account = service.create_account(
            user=user1, name="Acct", type=AccountType.spending,
            scope=AccountScope.shared,
        )
        service.add_co_owner(account.id, user1, "bob")

        with pytest.raises(ValueError, match="already a co-owner"):
            service.add_co_owner(account.id, user1, "bob")


class TestGetAccountsForUser:
    """Tests for AccountService.get_accounts_for_user."""

    def test_returns_owned_accounts(self, db_session, service, user1):
        """Returns accounts owned by the user."""
        service.create_account(
            user=user1, name="A1", type=AccountType.spending,
            scope=AccountScope.personal,
        )
        service.create_account(
            user=user1, name="A2", type=AccountType.saving,
            scope=AccountScope.personal,
        )

        accounts = service.get_accounts_for_user(user1)
        assert len(accounts) == 2

    def test_returns_co_owned_accounts(self, db_session, service, user1, user2):
        """Returns accounts where user is co-owner."""
        account = service.create_account(
            user=user1, name="Shared", type=AccountType.spending,
            scope=AccountScope.shared,
        )
        service.add_co_owner(account.id, user1, "bob")

        accounts = service.get_accounts_for_user(user2)
        assert len(accounts) == 1
        assert accounts[0].name == "Shared"

    def test_excludes_inactive_by_default(self, db_session, service, user1):
        """Inactive accounts are excluded by default."""
        account = service.create_account(
            user=user1, name="Active", type=AccountType.spending,
            scope=AccountScope.personal,
        )
        inactive = service.create_account(
            user=user1, name="Inactive", type=AccountType.spending,
            scope=AccountScope.personal,
        )
        service.deactivate_account(inactive.id, user1)

        accounts = service.get_accounts_for_user(user1)
        assert len(accounts) == 1
        assert accounts[0].name == "Active"

    def test_includes_inactive_when_requested(self, db_session, service, user1):
        """Inactive accounts included when include_inactive=True."""
        service.create_account(
            user=user1, name="Active", type=AccountType.spending,
            scope=AccountScope.personal,
        )
        inactive = service.create_account(
            user=user1, name="Inactive", type=AccountType.spending,
            scope=AccountScope.personal,
        )
        service.deactivate_account(inactive.id, user1)

        accounts = service.get_accounts_for_user(user1, include_inactive=True)
        assert len(accounts) == 2


class TestGetVisibleAccountsForPartner:
    """Tests for AccountService.get_visible_accounts_for_partner."""

    def test_shared_accounts_always_visible(self, db_session, service, user1, user2):
        """Shared accounts are visible regardless of visible_to_partner flag."""
        service.create_account(
            user=user1, name="Shared", type=AccountType.spending,
            scope=AccountScope.shared, visible_to_partner=False,
        )

        visible = service.get_visible_accounts_for_partner(user1)
        assert len(visible) == 1
        assert visible[0].name == "Shared"

    def test_personal_visible_to_partner_true_shown(self, db_session, service, user1, user2):
        """Personal accounts with visible_to_partner=True are shown."""
        service.create_account(
            user=user1, name="Visible", type=AccountType.spending,
            scope=AccountScope.personal, visible_to_partner=True,
        )

        visible = service.get_visible_accounts_for_partner(user1)
        assert len(visible) == 1
        assert visible[0].name == "Visible"

    def test_personal_visible_to_partner_false_hidden(self, db_session, service, user1, user2):
        """Personal accounts with visible_to_partner=False are hidden from partner."""
        service.create_account(
            user=user1, name="Hidden", type=AccountType.spending,
            scope=AccountScope.personal, visible_to_partner=False,
        )

        visible = service.get_visible_accounts_for_partner(user1)
        assert len(visible) == 0

    def test_inactive_accounts_excluded(self, db_session, service, user1, user2):
        """Inactive accounts are excluded from partner visibility."""
        account = service.create_account(
            user=user1, name="WasActive", type=AccountType.spending,
            scope=AccountScope.shared,
        )
        service.deactivate_account(account.id, user1)

        visible = service.get_visible_accounts_for_partner(user1)
        assert len(visible) == 0

    def test_no_partner_returns_empty(self, db_session, service, user1):
        """If no partner exists, returns empty list."""
        service.create_account(
            user=user1, name="Solo", type=AccountType.spending,
            scope=AccountScope.personal,
        )

        visible = service.get_visible_accounts_for_partner(user1)
        assert len(visible) == 0
