"""Unit tests for BalanceService.

Tests available balance calculation for credit card and spending/saving
accounts, income date utilities, and recalculation triggers.

Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5
"""

import pytest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from app.extensions import db
from app.models.account import Account, AccountType, AccountScope
from app.models.transaction import RecurringRule, TransactionType, RecurringFrequency
from app.models.user import User
from app.services.balance_service import BalanceService


@pytest.fixture()
def service():
    """Create a BalanceService instance."""
    return BalanceService()


@pytest.fixture()
def user(db_session):
    """Create a test user with income_day=25."""
    u = User(
        username="testuser",
        email="test@example.com",
        income_day=25,
    )
    u.set_password("password123")
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture()
def spending_account(db_session, user):
    """Create a spending account with balance 1000."""
    account = Account(
        name="Main Spending",
        type=AccountType.spending,
        scope=AccountScope.personal,
        balance=Decimal("1000.00"),
        active=True,
        owner_id=user.id,
    )
    db_session.add(account)
    db_session.commit()
    return account


@pytest.fixture()
def saving_account(db_session, user):
    """Create a saving account with balance 5000."""
    account = Account(
        name="Savings",
        type=AccountType.saving,
        scope=AccountScope.personal,
        balance=Decimal("5000.00"),
        active=True,
        owner_id=user.id,
    )
    db_session.add(account)
    db_session.commit()
    return account


@pytest.fixture()
def credit_card_account(db_session, user):
    """Create a credit card account with balance -500 and credit_limit 2000."""
    account = Account(
        name="Credit Card",
        type=AccountType.credit_card,
        scope=AccountScope.personal,
        balance=Decimal("-500.00"),
        credit_limit=Decimal("2000.00"),
        active=True,
        owner_id=user.id,
    )
    db_session.add(account)
    db_session.commit()
    return account


class TestCreditCardAvailableBalance:
    """Tests for credit card available balance = credit_limit + balance."""

    def test_credit_card_available_balance(self, service, credit_card_account):
        """Req 8.2: available = credit_limit + balance (negative debt)."""
        result = service.get_available_balance(credit_card_account.id)
        # 2000 + (-500) = 1500
        assert result == Decimal("1500.00")

    def test_credit_card_zero_balance(self, db_session, service, user):
        """Credit card with zero balance has available = credit_limit."""
        account = Account(
            name="CC Zero",
            type=AccountType.credit_card,
            scope=AccountScope.personal,
            balance=Decimal("0.00"),
            credit_limit=Decimal("3000.00"),
            active=True,
            owner_id=user.id,
        )
        db_session.add(account)
        db_session.commit()

        result = service.get_available_balance(account.id)
        assert result == Decimal("3000.00")

    def test_credit_card_no_credit_limit(self, db_session, service, user):
        """Credit card with no credit_limit treats it as 0."""
        account = Account(
            name="CC No Limit",
            type=AccountType.credit_card,
            scope=AccountScope.personal,
            balance=Decimal("-200.00"),
            credit_limit=None,
            active=True,
            owner_id=user.id,
        )
        db_session.add(account)
        db_session.commit()

        result = service.get_available_balance(account.id)
        # 0 + (-200) = -200
        assert result == Decimal("-200.00")


class TestSpendingAccountAvailableBalance:
    """Tests for spending/saving account available balance."""

    def test_no_deductions_returns_balance(self, service, spending_account):
        """Spending account with no obligations → available = balance."""
        result = service.get_available_balance(spending_account.id)
        assert result == Decimal("1000.00")

    def test_saving_account_no_deductions(self, service, saving_account):
        """Saving account with no obligations → available = balance."""
        result = service.get_available_balance(saving_account.id)
        assert result == Decimal("5000.00")

    def test_recurring_expenses_deducted(
        self, db_session, service, spending_account, user
    ):
        """Active recurring expense rules due before next income are deducted."""
        # Create a recurring expense due tomorrow (always before next income)
        tomorrow = date.today()
        from datetime import timedelta

        tomorrow = date.today() + timedelta(days=1)

        rule = RecurringRule(
            name="Rent",
            type=TransactionType.expense,
            frequency=RecurringFrequency.monthly,
            interval=1,
            amount=Decimal("800.00"),
            next_due_date=tomorrow,
            active=True,
            scope=spending_account.scope,
            account_id=spending_account.id,
            user_id=user.id,
        )
        db_session.add(rule)
        db_session.commit()

        result = service.get_available_balance(spending_account.id)
        # 1000 - 800 = 200
        assert result == Decimal("200.00")

    def test_inactive_recurring_rules_not_deducted(
        self, db_session, service, spending_account, user
    ):
        """Inactive recurring rules are not included in the deduction."""
        from datetime import timedelta

        rule = RecurringRule(
            name="Cancelled Sub",
            type=TransactionType.expense,
            frequency=RecurringFrequency.monthly,
            interval=1,
            amount=Decimal("50.00"),
            next_due_date=date.today() + timedelta(days=1),
            active=False,
            scope=spending_account.scope,
            account_id=spending_account.id,
            user_id=user.id,
        )
        db_session.add(rule)
        db_session.commit()

        result = service.get_available_balance(spending_account.id)
        assert result == Decimal("1000.00")

    def test_income_rules_not_deducted(
        self, db_session, service, spending_account, user
    ):
        """Recurring income rules are NOT deducted from available balance."""
        from datetime import timedelta

        rule = RecurringRule(
            name="Salary",
            type=TransactionType.income,
            frequency=RecurringFrequency.monthly,
            interval=1,
            amount=Decimal("3000.00"),
            next_due_date=date.today() + timedelta(days=1),
            active=True,
            scope=spending_account.scope,
            account_id=spending_account.id,
            user_id=user.id,
        )
        db_session.add(rule)
        db_session.commit()

        result = service.get_available_balance(spending_account.id)
        assert result == Decimal("1000.00")

    def test_negative_available_balance_not_clamped(
        self, db_session, service, spending_account, user
    ):
        """Req 8.5: Negative available balance is returned as-is."""
        from datetime import timedelta

        # Expense larger than balance
        rule = RecurringRule(
            name="Big Expense",
            type=TransactionType.expense,
            frequency=RecurringFrequency.monthly,
            interval=1,
            amount=Decimal("1500.00"),
            next_due_date=date.today() + timedelta(days=1),
            active=True,
            scope=spending_account.scope,
            account_id=spending_account.id,
            user_id=user.id,
        )
        db_session.add(rule)
        db_session.commit()

        result = service.get_available_balance(spending_account.id)
        # 1000 - 1500 = -500
        assert result == Decimal("-500.00")


class TestGetNextIncomeDate:
    """Tests for get_next_income_date."""

    def test_returns_date_object(self, service, user):
        """get_next_income_date returns a date instance."""
        result = service.get_next_income_date(user)
        assert isinstance(result, date)

    def test_income_day_uses_banking_day_service(self, service, user):
        """get_next_income_date uses BankingDayService for adjustment."""
        result = service.get_next_income_date(user)
        # The result should be a banking day (not weekend, not holiday)
        banking_service = service._banking_day_service
        assert banking_service.is_banking_day(result)

    def test_future_income_day_this_month(self, service, user):
        """If income day hasn't passed yet this month, return this month."""
        today = date.today()
        # Patch today to be early in the month so income_day=25 is in the future
        with patch("app.services.balance_service.date") as mock_date:
            mock_date.today.return_value = date(2024, 3, 1)
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            # Re-create service to pick up mock
            svc = BalanceService()
            result = svc.get_next_income_date(user)
            # Should be in March 2024 (income_day=25, March 25 2024 is Monday)
            assert result.month == 3
            assert result.year == 2024

    def test_past_income_day_returns_next_month(self, service, user):
        """If income day has passed this month, return next month's."""
        with patch("app.services.balance_service.date") as mock_date:
            mock_date.today.return_value = date(2024, 3, 26)
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            svc = BalanceService()
            result = svc.get_next_income_date(user)
            # Should be in April 2024
            assert result.month == 4
            assert result.year == 2024


class TestGetEffectiveIncomeDay:
    """Tests for get_effective_income_day."""

    def test_delegates_to_banking_day_service(self, service, user):
        """get_effective_income_day delegates to BankingDayService."""
        result = service.get_effective_income_day(user, 2024, 3)
        # March 25, 2024 is a Monday — it should be returned as-is
        expected = service._banking_day_service.get_effective_income_day(25, 2024, 3)
        assert result == expected

    def test_adjusts_weekend_to_friday(self, service, user):
        """Income day on a weekend is adjusted to the previous banking day."""
        # User income_day=25, January 2025: 25th is a Saturday
        result = service.get_effective_income_day(user, 2025, 1)
        # Should be Friday Jan 24, 2025
        assert result == date(2025, 1, 24)


class TestAccountNotFound:
    """Tests for error handling when account doesn't exist."""

    def test_get_available_balance_raises_for_missing_account(self, service, db_session):
        """Raises ValueError for non-existent account."""
        with pytest.raises(ValueError, match="not found"):
            service.get_available_balance(99999)
