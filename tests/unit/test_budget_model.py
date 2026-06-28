"""Unit tests for Budget model and BudgetService.

Tests budget creation validation, period boundary calculation,
utilisation computation, and threshold notification logic.

Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models.budget import Budget, BudgetPeriod, BudgetScope
from app.models.category import Category
from app.models.transaction import Transaction, TransactionScope, TransactionType
from app.services.budget_service import BudgetService
from tests.factories import UserFactory, AccountFactory


@pytest.fixture()
def budget_service():
    """Provide a BudgetService instance."""
    return BudgetService()


@pytest.fixture()
def user(db_session):
    """Create a test user with income_day=25."""
    return UserFactory(income_day=25)


@pytest.fixture()
def user_15(db_session):
    """Create a test user with income_day=15."""
    return UserFactory(income_day=15, username="user15", email="user15@example.com")


@pytest.fixture()
def category(db_session, user):
    """Create a test category."""
    cat = Category(name="Groceries", scope="personal", user_id=user.id)
    db_session.add(cat)
    db_session.flush()
    return cat


class TestBudgetModel:
    """Tests for the Budget model definition."""

    def test_budget_creation(self, db_session, user, category):
        """Test creating a Budget record directly."""
        budget = Budget(
            name="Monthly Groceries",
            scope=BudgetScope.personal,
            category_id=category.id,
            amount=Decimal("500.00"),
            period=BudgetPeriod.monthly,
            start_date=date(2024, 1, 25),
            user_id=user.id,
        )
        db_session.add(budget)
        db_session.flush()

        assert budget.id is not None
        assert budget.name == "Monthly Groceries"
        assert budget.scope == BudgetScope.personal
        assert budget.category_id == category.id
        assert budget.amount == Decimal("500.00")
        assert budget.period == BudgetPeriod.monthly
        assert budget.start_date == date(2024, 1, 25)
        assert budget.user_id == user.id
        assert budget.created_at is not None

    def test_budget_without_category(self, db_session, user):
        """Test budget with no category acts as total spending cap."""
        budget = Budget(
            name="Total Spending",
            scope=BudgetScope.personal,
            category_id=None,
            amount=Decimal("2000.00"),
            period=BudgetPeriod.monthly,
            start_date=date(2024, 1, 25),
            user_id=user.id,
        )
        db_session.add(budget)
        db_session.flush()

        assert budget.category_id is None

    def test_budget_repr(self, db_session, user):
        """Test Budget __repr__ method."""
        budget = Budget(
            name="Rent",
            scope=BudgetScope.shared,
            amount=Decimal("1200.00"),
            period=BudgetPeriod.monthly,
            start_date=date(2024, 1, 1),
            user_id=user.id,
        )
        assert repr(budget) == "<Budget 'Rent' (monthly)>"


class TestBudgetServiceCreate:
    """Tests for BudgetService.create_budget."""

    def test_create_budget_success(self, db_session, user, category, budget_service):
        """Test successful budget creation."""
        budget = budget_service.create_budget(
            user=user,
            name="Groceries",
            scope="personal",
            amount=Decimal("500.00"),
            period="monthly",
            start_date=date(2024, 1, 25),
            category_id=category.id,
        )

        assert budget.id is not None
        assert budget.name == "Groceries"
        assert budget.scope == BudgetScope.personal
        assert budget.amount == Decimal("500.00")
        assert budget.period == BudgetPeriod.monthly
        assert budget.user_id == user.id

    def test_create_budget_without_category(self, db_session, user, budget_service):
        """Test creating a total spending cap budget (no category)."""
        budget = budget_service.create_budget(
            user=user,
            name="Total Monthly",
            scope="personal",
            amount=Decimal("3000.00"),
            period="monthly",
            start_date=date(2024, 1, 25),
        )

        assert budget.category_id is None

    def test_create_budget_empty_name_rejected(self, db_session, user, budget_service):
        """Validates: Requirement 6.8 - empty name rejected."""
        with pytest.raises(ValueError, match="name must not be empty"):
            budget_service.create_budget(
                user=user,
                name="",
                scope="personal",
                amount=Decimal("500.00"),
                period="monthly",
                start_date=date(2024, 1, 25),
            )

    def test_create_budget_whitespace_name_rejected(self, db_session, user, budget_service):
        """Validates: Requirement 6.8 - whitespace-only name rejected."""
        with pytest.raises(ValueError, match="name must not be empty"):
            budget_service.create_budget(
                user=user,
                name="   ",
                scope="personal",
                amount=Decimal("500.00"),
                period="monthly",
                start_date=date(2024, 1, 25),
            )

    def test_create_budget_amount_too_low(self, db_session, user, budget_service):
        """Validates: Requirement 6.8 - amount below 0.01 rejected."""
        with pytest.raises(ValueError, match="Budget amount must be between"):
            budget_service.create_budget(
                user=user,
                name="Test",
                scope="personal",
                amount=Decimal("0.001"),
                period="monthly",
                start_date=date(2024, 1, 25),
            )

    def test_create_budget_amount_zero_rejected(self, db_session, user, budget_service):
        """Validates: Requirement 6.8 - zero amount rejected."""
        with pytest.raises(ValueError, match="Budget amount must be between"):
            budget_service.create_budget(
                user=user,
                name="Test",
                scope="personal",
                amount=Decimal("0"),
                period="monthly",
                start_date=date(2024, 1, 25),
            )

    def test_create_budget_shared_scope(self, db_session, user, budget_service):
        """Test creating a shared budget."""
        budget = budget_service.create_budget(
            user=user,
            name="Shared Groceries",
            scope="shared",
            amount=Decimal("800.00"),
            period="monthly",
            start_date=date(2024, 1, 25),
        )

        assert budget.scope == BudgetScope.shared

    def test_create_budget_name_stripped(self, db_session, user, budget_service):
        """Test that budget name is trimmed."""
        budget = budget_service.create_budget(
            user=user,
            name="  Groceries  ",
            scope="personal",
            amount=Decimal("500.00"),
            period="monthly",
            start_date=date(2024, 1, 25),
        )

        assert budget.name == "Groceries"


class TestBudgetServicePeriodBoundaries:
    """Tests for BudgetService.get_period_boundaries."""

    def test_monthly_period_after_income_day(self, db_session, user, budget_service):
        """Validates: Requirement 6.2 - monthly period from income day to day before next."""
        budget = Budget(
            name="Test",
            scope=BudgetScope.personal,
            amount=Decimal("500.00"),
            period=BudgetPeriod.monthly,
            start_date=date(2024, 1, 25),
            user_id=user.id,
        )
        db_session.add(budget)
        db_session.flush()

        # Reference date: Jan 27, 2024 (after income day 25)
        # Income day 25 is a Thursday (banking day)
        start, end = budget_service.get_period_boundaries(
            budget, user, reference_date=date(2024, 1, 27)
        )

        # Period should start on effective income day of January
        assert start == date(2024, 1, 25)
        # Period should end the day before effective income day of February
        # Feb 25, 2024 is Sunday, so effective = Feb 23 (Friday)
        assert end == date(2024, 2, 22)

    def test_monthly_period_before_income_day(self, db_session, user, budget_service):
        """Test monthly period when reference date is before income day."""
        budget = Budget(
            name="Test",
            scope=BudgetScope.personal,
            amount=Decimal("500.00"),
            period=BudgetPeriod.monthly,
            start_date=date(2024, 1, 25),
            user_id=user.id,
        )
        db_session.add(budget)
        db_session.flush()

        # Reference date: Feb 10, 2024 (before income day 25)
        start, end = budget_service.get_period_boundaries(
            budget, user, reference_date=date(2024, 2, 10)
        )

        # Should be in period starting Jan 25
        assert start == date(2024, 1, 25)
        # Ends day before Feb effective income day (Feb 25 is Sunday → Feb 23)
        assert end == date(2024, 2, 22)

    def test_weekly_period(self, db_session, user_15, budget_service):
        """Test weekly period (7-day windows from income day)."""
        budget = Budget(
            name="Weekly",
            scope=BudgetScope.personal,
            amount=Decimal("100.00"),
            period=BudgetPeriod.weekly,
            start_date=date(2024, 1, 15),
            user_id=user_15.id,
        )
        db_session.add(budget)
        db_session.flush()

        # Jan 15, 2024 is a Monday (banking day) → income day
        # Reference: Jan 18 → 3 days into first week
        start, end = budget_service.get_period_boundaries(
            budget, user_15, reference_date=date(2024, 1, 18)
        )

        assert start == date(2024, 1, 15)
        assert end == date(2024, 1, 21)

    def test_weekly_period_second_week(self, db_session, user_15, budget_service):
        """Test weekly period in the second week of the cycle."""
        budget = Budget(
            name="Weekly",
            scope=BudgetScope.personal,
            amount=Decimal("100.00"),
            period=BudgetPeriod.weekly,
            start_date=date(2024, 1, 15),
            user_id=user_15.id,
        )
        db_session.add(budget)
        db_session.flush()

        # Jan 22, 2024 = 7 days after income day → second week
        start, end = budget_service.get_period_boundaries(
            budget, user_15, reference_date=date(2024, 1, 23)
        )

        assert start == date(2024, 1, 22)
        assert end == date(2024, 1, 28)

    def test_yearly_period(self, db_session, user, budget_service):
        """Test yearly period boundaries."""
        budget = Budget(
            name="Yearly",
            scope=BudgetScope.personal,
            amount=Decimal("12000.00"),
            period=BudgetPeriod.yearly,
            start_date=date(2024, 1, 25),
            user_id=user.id,
        )
        db_session.add(budget)
        db_session.flush()

        # Jan 25, 2024 is Thursday (banking day)
        start, end = budget_service.get_period_boundaries(
            budget, user, reference_date=date(2024, 6, 15)
        )

        assert start == date(2024, 1, 25)
        # Ends day before Jan 2025 effective income day
        # Jan 25, 2025 is Saturday → effective = Jan 24 (Friday)
        assert end == date(2025, 1, 23)


class TestBudgetServiceUtilisation:
    """Tests for BudgetService.calculate_utilisation."""

    def test_utilisation_zero_no_expenses(self, db_session, user, category, budget_service):
        """Validates: Requirement 6.3 - no expenses means 0% utilisation."""
        budget = budget_service.create_budget(
            user=user,
            name="Groceries",
            scope="personal",
            amount=Decimal("500.00"),
            period="monthly",
            start_date=date(2024, 1, 25),
            category_id=category.id,
        )

        util = budget_service.calculate_utilisation(
            budget, user, reference_date=date(2024, 2, 1)
        )
        assert util == Decimal("0")

    def test_utilisation_with_matching_expenses(
        self, db_session, user, category, budget_service
    ):
        """Validates: Requirement 6.3 - utilisation = sum expenses / budget amount."""
        account = AccountFactory(owner=user)

        budget = budget_service.create_budget(
            user=user,
            name="Groceries",
            scope="personal",
            amount=Decimal("500.00"),
            period="monthly",
            start_date=date(2024, 1, 25),
            category_id=category.id,
        )

        # Create expense transactions within the period
        # Period for income_day=25: Jan 25 to Feb 22 (Feb 25 is Sun→Feb 23, minus 1 = Feb 22)
        txn1 = Transaction(
            type=TransactionType.expense,
            amount=Decimal("100.00"),
            date=date(2024, 1, 26),
            scope=TransactionScope.personal,
            account_id=account.id,
            category_id=category.id,
            user_id=user.id,
        )
        txn2 = Transaction(
            type=TransactionType.expense,
            amount=Decimal("150.00"),
            date=date(2024, 2, 5),
            scope=TransactionScope.personal,
            account_id=account.id,
            category_id=category.id,
            user_id=user.id,
        )
        db_session.add_all([txn1, txn2])
        db_session.flush()

        util = budget_service.calculate_utilisation(
            budget, user, reference_date=date(2024, 2, 1)
        )

        # 250 / 500 = 0.5
        assert util == Decimal("0.5")

    def test_utilisation_excludes_income(
        self, db_session, user, category, budget_service
    ):
        """Only expense transactions count toward utilisation."""
        account = AccountFactory(owner=user)

        budget = budget_service.create_budget(
            user=user,
            name="Groceries",
            scope="personal",
            amount=Decimal("500.00"),
            period="monthly",
            start_date=date(2024, 1, 25),
            category_id=category.id,
        )

        # Income should NOT count
        txn = Transaction(
            type=TransactionType.income,
            amount=Decimal("3000.00"),
            date=date(2024, 1, 26),
            scope=TransactionScope.personal,
            account_id=account.id,
            category_id=category.id,
            user_id=user.id,
        )
        db_session.add(txn)
        db_session.flush()

        util = budget_service.calculate_utilisation(
            budget, user, reference_date=date(2024, 2, 1)
        )
        assert util == Decimal("0")

    def test_utilisation_no_category_sums_all(
        self, db_session, user, category, budget_service
    ):
        """Validates: Requirement 6.6 - no category = total spending cap."""
        account = AccountFactory(owner=user)

        # Budget with no category
        budget = budget_service.create_budget(
            user=user,
            name="Total Spending",
            scope="personal",
            amount=Decimal("2000.00"),
            period="monthly",
            start_date=date(2024, 1, 25),
        )

        # Create expenses in different categories
        cat2 = Category(name="Transport", scope="personal", user_id=user.id)
        db_session.add(cat2)
        db_session.flush()

        txn1 = Transaction(
            type=TransactionType.expense,
            amount=Decimal("100.00"),
            date=date(2024, 1, 26),
            scope=TransactionScope.personal,
            account_id=account.id,
            category_id=category.id,
            user_id=user.id,
        )
        txn2 = Transaction(
            type=TransactionType.expense,
            amount=Decimal("200.00"),
            date=date(2024, 2, 1),
            scope=TransactionScope.personal,
            account_id=account.id,
            category_id=cat2.id,
            user_id=user.id,
        )
        db_session.add_all([txn1, txn2])
        db_session.flush()

        util = budget_service.calculate_utilisation(
            budget, user, reference_date=date(2024, 2, 1)
        )

        # 300 / 2000 = 0.15
        assert util == Decimal("0.15")

    def test_utilisation_shared_includes_partner(
        self, db_session, user, budget_service
    ):
        """Validates: Requirement 6.7 - shared budget includes both members' expenses."""
        partner = UserFactory(
            income_day=25, username="partner", email="partner@example.com"
        )
        account1 = AccountFactory(owner=user)
        account2 = AccountFactory(owner=partner)

        shared_cat = Category(name="Shared Food", scope="shared", user_id=user.id)
        db_session.add(shared_cat)
        db_session.flush()

        budget = budget_service.create_budget(
            user=user,
            name="Shared Groceries",
            scope="shared",
            amount=Decimal("1000.00"),
            period="monthly",
            start_date=date(2024, 1, 25),
            category_id=shared_cat.id,
        )

        # User's shared expense
        txn1 = Transaction(
            type=TransactionType.expense,
            amount=Decimal("200.00"),
            date=date(2024, 1, 26),
            scope=TransactionScope.shared,
            account_id=account1.id,
            category_id=shared_cat.id,
            user_id=user.id,
        )
        # Partner's shared expense
        txn2 = Transaction(
            type=TransactionType.expense,
            amount=Decimal("300.00"),
            date=date(2024, 2, 1),
            scope=TransactionScope.shared,
            account_id=account2.id,
            category_id=shared_cat.id,
            user_id=partner.id,
        )
        db_session.add_all([txn1, txn2])
        db_session.flush()

        util = budget_service.calculate_utilisation(
            budget, user, reference_date=date(2024, 2, 1)
        )

        # 500 / 1000 = 0.5
        assert util == Decimal("0.5")


class TestBudgetServiceThresholds:
    """Tests for BudgetService.check_thresholds."""

    def test_no_notifications_below_80(self, db_session, user, category, budget_service):
        """No notifications when utilisation is below 80%."""
        account = AccountFactory(owner=user)

        budget = budget_service.create_budget(
            user=user,
            name="Groceries",
            scope="personal",
            amount=Decimal("500.00"),
            period="monthly",
            start_date=date(2024, 1, 25),
            category_id=category.id,
        )

        # Create expense at 50% utilisation
        txn = Transaction(
            type=TransactionType.expense,
            amount=Decimal("250.00"),
            date=date(2024, 1, 26),
            scope=TransactionScope.personal,
            account_id=account.id,
            category_id=category.id,
            user_id=user.id,
        )
        db_session.add(txn)
        db_session.flush()

        notifications = budget_service.check_thresholds(
            budget, user, reference_date=date(2024, 2, 1)
        )
        assert notifications == []

    def test_warning_at_80_percent(self, db_session, user, category, budget_service):
        """Validates: Requirement 6.4 - budget_warning at 80%."""
        account = AccountFactory(owner=user)

        budget = budget_service.create_budget(
            user=user,
            name="Groceries",
            scope="personal",
            amount=Decimal("500.00"),
            period="monthly",
            start_date=date(2024, 1, 25),
            category_id=category.id,
        )

        # Create expense at exactly 80%
        txn = Transaction(
            type=TransactionType.expense,
            amount=Decimal("400.00"),
            date=date(2024, 1, 26),
            scope=TransactionScope.personal,
            account_id=account.id,
            category_id=category.id,
            user_id=user.id,
        )
        db_session.add(txn)
        db_session.flush()

        notifications = budget_service.check_thresholds(
            budget, user, reference_date=date(2024, 2, 1)
        )
        assert "budget_warning" in notifications
        assert "budget_exceeded" not in notifications

    def test_exceeded_at_100_percent(self, db_session, user, category, budget_service):
        """Validates: Requirement 6.5 - budget_exceeded at 100%."""
        account = AccountFactory(owner=user)

        budget = budget_service.create_budget(
            user=user,
            name="Groceries",
            scope="personal",
            amount=Decimal("500.00"),
            period="monthly",
            start_date=date(2024, 1, 25),
            category_id=category.id,
        )

        # Create expense at 100%
        txn = Transaction(
            type=TransactionType.expense,
            amount=Decimal("500.00"),
            date=date(2024, 1, 26),
            scope=TransactionScope.personal,
            account_id=account.id,
            category_id=category.id,
            user_id=user.id,
        )
        db_session.add(txn)
        db_session.flush()

        notifications = budget_service.check_thresholds(
            budget, user, reference_date=date(2024, 2, 1)
        )
        assert "budget_warning" in notifications
        assert "budget_exceeded" in notifications

    def test_both_notifications_at_over_100(
        self, db_session, user, category, budget_service
    ):
        """Both warning and exceeded generated when over 100%."""
        account = AccountFactory(owner=user)

        budget = budget_service.create_budget(
            user=user,
            name="Groceries",
            scope="personal",
            amount=Decimal("500.00"),
            period="monthly",
            start_date=date(2024, 1, 25),
            category_id=category.id,
        )

        # Create expense at 120%
        txn = Transaction(
            type=TransactionType.expense,
            amount=Decimal("600.00"),
            date=date(2024, 1, 26),
            scope=TransactionScope.personal,
            account_id=account.id,
            category_id=category.id,
            user_id=user.id,
        )
        db_session.add(txn)
        db_session.flush()

        notifications = budget_service.check_thresholds(
            budget, user, reference_date=date(2024, 2, 1)
        )
        assert "budget_warning" in notifications
        assert "budget_exceeded" in notifications
