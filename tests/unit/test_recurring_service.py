"""Unit tests for RecurringService.

Tests due rule processing, catch-up logic, date advancement,
overdraft skip logic, duplicate prevention, and split copying.

Validates: Requirements 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8
"""

import pytest
from datetime import date, timedelta
from decimal import Decimal

from app.extensions import db
from app.models.account import Account, AccountType, AccountScope
from app.models.category import Category
from app.models.transaction import (
    RecurringFrequency,
    RecurringRule,
    RecurringRuleSplit,
    Transaction,
    TransactionSplit,
    TransactionScope,
    TransactionType,
)
from app.models.user import User
from app.services.recurring_service import RecurringService


@pytest.fixture()
def service():
    """Create a RecurringService instance."""
    return RecurringService()


@pytest.fixture()
def user(db_session):
    """Create a test user."""
    u = User(
        username="recurtest",
        email="recurtest@example.com",
        password_hash="pbkdf2:sha256:600000$salt$fakehash",
        income_day=25,
    )
    db_session.add(u)
    db_session.flush()
    return u


@pytest.fixture()
def account(db_session, user):
    """Create a spending account with sufficient balance."""
    acct = Account(
        name="Main Checking",
        type=AccountType.spending,
        scope=AccountScope.personal,
        balance=Decimal("5000.00"),
        active=True,
        owner_id=user.id,
    )
    db_session.add(acct)
    db_session.flush()
    return acct


@pytest.fixture()
def destination_account(db_session, user):
    """Create a destination account for transfers."""
    acct = Account(
        name="Savings",
        type=AccountType.saving,
        scope=AccountScope.personal,
        balance=Decimal("1000.00"),
        active=True,
        owner_id=user.id,
    )
    db_session.add(acct)
    db_session.flush()
    return acct


@pytest.fixture()
def category(db_session, user):
    """Create a test category."""
    cat = Category(
        name="Groceries",
        scope="personal",
        user_id=user.id,
    )
    db_session.add(cat)
    db_session.flush()
    return cat


@pytest.fixture()
def expense_rule(db_session, user, account):
    """Create an active monthly expense recurring rule due today."""
    rule = RecurringRule(
        name="Monthly Rent",
        type=TransactionType.expense,
        frequency=RecurringFrequency.monthly,
        interval=1,
        amount=Decimal("1200.00"),
        next_due_date=date.today(),
        active=True,
        scope=TransactionScope.personal,
        account_id=account.id,
        user_id=user.id,
    )
    db_session.add(rule)
    db_session.flush()
    return rule


class TestProcessDueRules:
    """Tests for RecurringService.process_due_rules."""

    def test_rule_due_today_generates_transaction(self, db_session, service, user, expense_rule, account):
        """A rule with next_due_date == today generates a transaction.

        Validates: Requirement 5.2
        """
        today = date.today()
        generated, notifications = service.process_due_rules(user, today=today)

        assert len(generated) == 1
        txn = generated[0]
        assert txn.recurring_rule_id == expense_rule.id
        assert txn.amount == Decimal("1200.00")
        assert txn.date == today
        assert txn.type == TransactionType.expense

    def test_rule_due_today_advances_next_due_date(self, db_session, service, user, expense_rule):
        """After processing, next_due_date is advanced to the next month.

        Validates: Requirement 5.3
        """
        today = date.today()
        service.process_due_rules(user, today=today)

        # Monthly rule with interval=1 should advance by 1 month
        from dateutil.relativedelta import relativedelta
        expected_next = today + relativedelta(months=1)
        assert expense_rule.next_due_date == expected_next

    def test_rule_due_today_generates_posted_notification(self, db_session, service, user, expense_rule):
        """Processing generates a recurring_rule_posted notification.

        Validates: Requirement 5.4
        """
        today = date.today()
        _, notifications = service.process_due_rules(user, today=today)

        assert len(notifications) == 1
        notif = notifications[0]
        assert notif.notification_type == "recurring_rule_posted"
        assert notif.rule_id == expense_rule.id

    def test_multiple_missed_dates_generates_all(self, db_session, service, user, account):
        """A rule with multiple missed dates generates transactions for all of them.

        Validates: Requirements 5.2, 5.8
        """
        # Rule that was due 3 days ago (daily, interval=1)
        three_days_ago = date.today() - timedelta(days=3)
        rule = RecurringRule(
            name="Daily Coffee",
            type=TransactionType.expense,
            frequency=RecurringFrequency.daily,
            interval=1,
            amount=Decimal("5.00"),
            next_due_date=three_days_ago,
            active=True,
            scope=TransactionScope.personal,
            account_id=account.id,
            user_id=user.id,
        )
        db_session.add(rule)
        db_session.flush()

        today = date.today()
        generated, notifications = service.process_due_rules(user, today=today)

        # Should generate for: 3 days ago, 2 days ago, 1 day ago, today = 4 transactions
        assert len(generated) == 4
        # Each has the correct date
        dates = sorted(txn.date for txn in generated)
        expected_dates = [three_days_ago + timedelta(days=i) for i in range(4)]
        assert dates == expected_dates

    def test_inactive_rule_not_processed(self, db_session, service, user, account):
        """An inactive rule is not processed even if due.

        Validates: Requirement 5.9 (indirectly)
        """
        rule = RecurringRule(
            name="Inactive Rule",
            type=TransactionType.expense,
            frequency=RecurringFrequency.monthly,
            interval=1,
            amount=Decimal("100.00"),
            next_due_date=date.today() - timedelta(days=5),
            active=False,
            scope=TransactionScope.personal,
            account_id=account.id,
            user_id=user.id,
        )
        db_session.add(rule)
        db_session.flush()

        generated, notifications = service.process_due_rules(user, today=date.today())
        assert len(generated) == 0
        assert len(notifications) == 0

    def test_future_rule_not_processed(self, db_session, service, user, account):
        """A rule with next_due_date in the future is not processed."""
        rule = RecurringRule(
            name="Future Rule",
            type=TransactionType.expense,
            frequency=RecurringFrequency.monthly,
            interval=1,
            amount=Decimal("100.00"),
            next_due_date=date.today() + timedelta(days=5),
            active=True,
            scope=TransactionScope.personal,
            account_id=account.id,
            user_id=user.id,
        )
        db_session.add(rule)
        db_session.flush()

        generated, notifications = service.process_due_rules(user, today=date.today())
        assert len(generated) == 0


class TestOverdraftSkipLogic:
    """Tests for overdraft skip behavior."""

    def test_overdraft_skips_posting_but_advances_date(self, db_session, service, user):
        """If execution would exceed overdraft, skip posting but advance date.

        Validates: Requirement 5.5
        """
        # Account with low balance and strict overdraft limit
        acct = Account(
            name="Low Balance",
            type=AccountType.spending,
            scope=AccountScope.personal,
            balance=Decimal("50.00"),
            max_overdraft=Decimal("10.00"),
            active=True,
            owner_id=user.id,
        )
        db_session.add(acct)
        db_session.flush()

        today = date.today()
        rule = RecurringRule(
            name="Big Expense",
            type=TransactionType.expense,
            frequency=RecurringFrequency.monthly,
            interval=1,
            amount=Decimal("100.00"),  # 100 > 50 + 10 overdraft
            next_due_date=today,
            active=True,
            scope=TransactionScope.personal,
            account_id=acct.id,
            user_id=user.id,
        )
        db_session.add(rule)
        db_session.flush()

        generated, notifications = service.process_due_rules(user, today=today)

        # No transaction generated
        assert len(generated) == 0
        # But date was advanced
        from dateutil.relativedelta import relativedelta
        assert rule.next_due_date == today + relativedelta(months=1)
        # Overdraft notification generated
        assert len(notifications) == 1
        assert notifications[0].notification_type == "overdraft_limit_exceeded"

    def test_overdraft_notification_contains_rule_info(self, db_session, service, user):
        """Overdraft notification includes the rule name and due date.

        Validates: Requirement 5.5
        """
        acct = Account(
            name="Empty Account",
            type=AccountType.spending,
            scope=AccountScope.personal,
            balance=Decimal("0.00"),
            max_overdraft=Decimal("0.00"),
            active=True,
            owner_id=user.id,
        )
        db_session.add(acct)
        db_session.flush()

        today = date.today()
        rule = RecurringRule(
            name="Insurance",
            type=TransactionType.expense,
            frequency=RecurringFrequency.monthly,
            interval=1,
            amount=Decimal("200.00"),
            next_due_date=today,
            active=True,
            scope=TransactionScope.personal,
            account_id=acct.id,
            user_id=user.id,
        )
        db_session.add(rule)
        db_session.flush()

        _, notifications = service.process_due_rules(user, today=today)

        notif = notifications[0]
        assert notif.rule_name == "Insurance"
        assert notif.due_date == today
        assert "overdraft" in notif.message.lower()


class TestDuplicatePrevention:
    """Tests for duplicate transaction prevention."""

    def test_no_duplicate_if_transaction_exists(self, db_session, service, user, account, expense_rule):
        """If a transaction linked to this rule already exists for the date, skip it.

        Validates: Requirement 5.6
        """
        today = date.today()

        # Manually create a transaction for this rule and today's date
        existing_txn = Transaction(
            type=TransactionType.expense,
            amount=expense_rule.amount,
            date=today,
            scope=TransactionScope.personal,
            account_id=account.id,
            recurring_rule_id=expense_rule.id,
            posted=True,
            user_id=user.id,
        )
        db_session.add(existing_txn)
        db_session.flush()

        generated, _ = service.process_due_rules(user, today=today)

        # No new transaction created (duplicate prevention)
        assert len(generated) == 0
        # But date was still advanced
        from dateutil.relativedelta import relativedelta
        assert expense_rule.next_due_date == today + relativedelta(months=1)


class TestAdvanceNextDueDate:
    """Tests for RecurringService.advance_next_due_date."""

    def test_daily_advances_by_interval_days(self, db_session, service, user, account):
        """Daily frequency advances by interval days.

        Validates: Requirement 5.3
        """
        rule = RecurringRule(
            name="Daily",
            type=TransactionType.expense,
            frequency=RecurringFrequency.daily,
            interval=2,
            amount=Decimal("10.00"),
            next_due_date=date(2024, 3, 1),
            active=True,
            scope=TransactionScope.personal,
            account_id=account.id,
            user_id=user.id,
        )
        db_session.add(rule)
        db_session.flush()

        new_date = service.advance_next_due_date(rule)
        assert new_date == date(2024, 3, 3)

    def test_weekly_advances_by_interval_weeks(self, db_session, service, user, account):
        """Weekly frequency advances by interval * 7 days.

        Validates: Requirement 5.3
        """
        rule = RecurringRule(
            name="Biweekly",
            type=TransactionType.expense,
            frequency=RecurringFrequency.weekly,
            interval=2,
            amount=Decimal("10.00"),
            next_due_date=date(2024, 3, 1),
            active=True,
            scope=TransactionScope.personal,
            account_id=account.id,
            user_id=user.id,
        )
        db_session.add(rule)
        db_session.flush()

        new_date = service.advance_next_due_date(rule)
        assert new_date == date(2024, 3, 15)

    def test_monthly_advances_by_interval_months(self, db_session, service, user, account):
        """Monthly frequency advances by interval months using relativedelta.

        Validates: Requirement 5.3
        """
        rule = RecurringRule(
            name="Monthly",
            type=TransactionType.expense,
            frequency=RecurringFrequency.monthly,
            interval=1,
            amount=Decimal("10.00"),
            next_due_date=date(2024, 1, 31),
            active=True,
            scope=TransactionScope.personal,
            account_id=account.id,
            user_id=user.id,
        )
        db_session.add(rule)
        db_session.flush()

        new_date = service.advance_next_due_date(rule)
        # Jan 31 + 1 month = Feb 29 (2024 is a leap year)
        assert new_date == date(2024, 2, 29)

    def test_quarterly_advances_by_3_months(self, db_session, service, user, account):
        """Quarterly frequency advances by interval * 3 months.

        Validates: Requirement 5.3
        """
        rule = RecurringRule(
            name="Quarterly",
            type=TransactionType.expense,
            frequency=RecurringFrequency.quarterly,
            interval=1,
            amount=Decimal("10.00"),
            next_due_date=date(2024, 1, 15),
            active=True,
            scope=TransactionScope.personal,
            account_id=account.id,
            user_id=user.id,
        )
        db_session.add(rule)
        db_session.flush()

        new_date = service.advance_next_due_date(rule)
        assert new_date == date(2024, 4, 15)

    def test_yearly_advances_by_interval_years(self, db_session, service, user, account):
        """Yearly frequency advances by interval years.

        Validates: Requirement 5.3
        """
        rule = RecurringRule(
            name="Yearly",
            type=TransactionType.expense,
            frequency=RecurringFrequency.yearly,
            interval=1,
            amount=Decimal("10.00"),
            next_due_date=date(2024, 2, 29),
            active=True,
            scope=TransactionScope.personal,
            account_id=account.id,
            user_id=user.id,
        )
        db_session.add(rule)
        db_session.flush()

        new_date = service.advance_next_due_date(rule)
        # Feb 29 2024 + 1 year -> Feb 28 2025 (not a leap year)
        assert new_date == date(2025, 2, 28)


class TestTransferRuleSplitCopy:
    """Tests for copying RecurringRuleSplit to TransactionSplit."""

    def test_transfer_rule_copies_splits(
        self, db_session, service, user, account, destination_account, category
    ):
        """Transfer rules copy RecurringRuleSplit records to TransactionSplit.

        Validates: Requirement 5.7
        """
        today = date.today()
        rule = RecurringRule(
            name="Monthly Transfer",
            type=TransactionType.transfer,
            frequency=RecurringFrequency.monthly,
            interval=1,
            amount=Decimal("500.00"),
            next_due_date=today,
            active=True,
            scope=TransactionScope.personal,
            account_id=account.id,
            destination_account_id=destination_account.id,
            user_id=user.id,
        )
        db_session.add(rule)
        db_session.flush()

        # Add splits to the rule
        split1 = RecurringRuleSplit(
            recurring_rule_id=rule.id,
            category_id=category.id,
            amount=Decimal("300.00"),
            description="Rent portion",
        )
        split2 = RecurringRuleSplit(
            recurring_rule_id=rule.id,
            category_id=category.id,
            amount=Decimal("200.00"),
            description="Utilities portion",
        )
        db_session.add_all([split1, split2])
        db_session.flush()

        generated, _ = service.process_due_rules(user, today=today)

        assert len(generated) == 1
        txn = generated[0]

        # Check that splits were copied
        txn_splits = TransactionSplit.query.filter_by(transaction_id=txn.id).all()
        assert len(txn_splits) == 2

        splits_by_desc = {s.description: s for s in txn_splits}
        assert splits_by_desc["Rent portion"].amount == Decimal("300.00")
        assert splits_by_desc["Utilities portion"].amount == Decimal("200.00")
        assert splits_by_desc["Rent portion"].category_id == category.id

    def test_expense_rule_does_not_copy_splits(
        self, db_session, service, user, account, category
    ):
        """Non-transfer rules do not copy splits even if they exist.

        Validates: Requirement 5.7 (transfer-specific behavior)
        """
        today = date.today()
        rule = RecurringRule(
            name="Monthly Expense",
            type=TransactionType.expense,
            frequency=RecurringFrequency.monthly,
            interval=1,
            amount=Decimal("100.00"),
            next_due_date=today,
            active=True,
            scope=TransactionScope.personal,
            account_id=account.id,
            user_id=user.id,
        )
        db_session.add(rule)
        db_session.flush()

        # Add a split to expense rule (shouldn't be copied)
        split = RecurringRuleSplit(
            recurring_rule_id=rule.id,
            category_id=category.id,
            amount=Decimal("100.00"),
            description="Should not appear",
        )
        db_session.add(split)
        db_session.flush()

        generated, _ = service.process_due_rules(user, today=today)

        assert len(generated) == 1
        txn = generated[0]

        # No splits should be copied for expense type
        txn_splits = TransactionSplit.query.filter_by(transaction_id=txn.id).all()
        assert len(txn_splits) == 0
