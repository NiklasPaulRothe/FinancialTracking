"""Unit tests for ETF service savings plan execution logic.

Validates: Requirements 14.1, 14.2, 14.3, 14.4, 14.5
"""

import pytest
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

from app.extensions import db
from app.models.account import Account
from app.models.etf import (
    ETFPosition,
    ETFSavingsPlan,
    ETFTransaction,
    ETFTransactionType,
)
from app.models.transaction import (
    RecurringRule,
    RecurringFrequency,
    TransactionType,
    TransactionScope,
)
from app.models.user import User
from app.services.etf_service import ETFService, STALE_PRICE_THRESHOLD_DAYS


@pytest.fixture()
def user(db_session):
    """Create a test user."""
    u = User(
        username="etftester",
        email="etf@example.com",
        password_hash="pbkdf2:sha256:600000$salt$fakehash",
        income_day=25,
    )
    db_session.add(u)
    db_session.flush()
    return u


@pytest.fixture()
def account(db_session, user):
    """Create a test spending account with sufficient balance."""
    acct = Account(
        name="ETF Funding Account",
        type="spending",
        scope="personal",
        balance=Decimal("10000.00"),
        active=True,
        visible_to_partner=True,
        owner_id=user.id,
    )
    db_session.add(acct)
    db_session.flush()
    return acct


@pytest.fixture()
def position(db_session, user):
    """Create a test ETF position with a fresh price."""
    pos = ETFPosition(
        ticker="VWCE",
        exchange_suffix="DE",
        name="Vanguard FTSE All-World UCITS ETF",
        shares=Decimal("100.000000"),
        average_buy_price=Decimal("95.000000"),
        current_price=Decimal("100.0000"),
        current_price_updated_at=datetime.now(timezone.utc),
        manual_price_override=False,
        user_id=user.id,
    )
    db_session.add(pos)
    db_session.flush()
    return pos


@pytest.fixture()
def recurring_rule(db_session, user, account):
    """Create a recurring rule linked to the savings plan (monthly, 500€)."""
    rule = RecurringRule(
        name="VWCE Sparplan",
        type=TransactionType.expense,
        frequency=RecurringFrequency.monthly,
        interval=1,
        amount=Decimal("500.00"),
        next_due_date=date(2024, 6, 1),
        active=True,
        scope=TransactionScope.personal,
        account_id=account.id,
        user_id=user.id,
    )
    db_session.add(rule)
    db_session.flush()
    return rule


@pytest.fixture()
def savings_plan(db_session, user, position, recurring_rule, account):
    """Create an active ETF savings plan."""
    plan = ETFSavingsPlan(
        position_id=position.id,
        recurring_rule_id=recurring_rule.id,
        linked_account_id=account.id,
        active=True,
        user_id=user.id,
    )
    db_session.add(plan)
    db_session.flush()
    return plan


class TestSavingsPlanExecution:
    """Tests for ETF savings plan execution logic (Req 14.2)."""

    def test_basic_execution_creates_buy_transaction(
        self, db_session, user, account, position, recurring_rule, savings_plan
    ):
        """When a savings plan fires with fresh price, it creates a buy ETFTransaction."""
        service = ETFService()
        today = date(2024, 6, 1)  # Rule is due today

        generated, notifications = service.process_savings_plans(user, today=today)

        assert len(generated) == 1
        txn = generated[0]
        assert txn.type == ETFTransactionType.buy
        assert txn.position_id == position.id
        assert txn.linked_account_id == account.id

    def test_shares_calculated_correctly(
        self, db_session, user, account, position, recurring_rule, savings_plan
    ):
        """Shares = amount / current_price rounded to 6 decimals (Req 14.2)."""
        service = ETFService()
        today = date(2024, 6, 1)

        # amount=500, current_price=100 => shares = 5.000000
        generated, _ = service.process_savings_plans(user, today=today)

        txn = generated[0]
        expected_shares = Decimal("5.000000")
        assert txn.shares_quantity == expected_shares
        assert txn.price_per_share == Decimal("100.0000")

    def test_shares_rounded_to_6_decimals(
        self, db_session, user, account, position, recurring_rule, savings_plan
    ):
        """Shares are rounded to 6 decimal places (Req 14.2)."""
        # Set a price that produces non-terminating decimals
        position.current_price = Decimal("77.7700")
        db_session.flush()

        service = ETFService()
        today = date(2024, 6, 1)

        generated, _ = service.process_savings_plans(user, today=today)

        txn = generated[0]
        # 500 / 77.77 = 6.429190... => 6.429190 (rounded to 6 decimals)
        assert txn.shares_quantity == Decimal("6.429190")

    def test_account_balance_deducted(
        self, db_session, user, account, position, recurring_rule, savings_plan
    ):
        """The linked account balance is deducted on execution (Req 14.2)."""
        initial_balance = account.balance
        service = ETFService()
        today = date(2024, 6, 1)

        generated, _ = service.process_savings_plans(user, today=today)

        txn = generated[0]
        expected_balance = initial_balance - txn.total_amount
        assert account.balance == expected_balance

    def test_position_shares_increased(
        self, db_session, user, account, position, recurring_rule, savings_plan
    ):
        """Position shares are increased after execution (Req 14.2)."""
        initial_shares = position.shares
        service = ETFService()
        today = date(2024, 6, 1)

        generated, _ = service.process_savings_plans(user, today=today)

        txn = generated[0]
        assert position.shares == initial_shares + txn.shares_quantity

    def test_average_buy_price_recalculated(
        self, db_session, user, account, position, recurring_rule, savings_plan
    ):
        """Average buy price is recalculated on execution (Req 14.2)."""
        initial_shares = position.shares  # 100
        initial_avg = position.average_buy_price  # 95

        service = ETFService()
        today = date(2024, 6, 1)

        generated, _ = service.process_savings_plans(user, today=today)

        # New shares bought: 500/100 = 5
        # New avg = (100*95 + 5*100) / (100+5) = (9500+500)/105 = 10000/105 = 95.238095...
        txn = generated[0]
        new_shares = txn.shares_quantity
        expected_avg = (
            (initial_shares * initial_avg) + (new_shares * position.current_price)
        ) / (initial_shares + new_shares)
        expected_avg = expected_avg.quantize(Decimal("0.000001"))
        assert position.average_buy_price == expected_avg

    def test_recurring_rule_advanced_on_success(
        self, db_session, user, account, position, recurring_rule, savings_plan
    ):
        """Recurring rule next_due_date is advanced after successful execution."""
        service = ETFService()
        today = date(2024, 6, 1)

        service.process_savings_plans(user, today=today)

        # Monthly interval=1, so next_due_date should be July 1
        assert recurring_rule.next_due_date == date(2024, 7, 1)

    def test_notification_generated_on_success(
        self, db_session, user, account, position, recurring_rule, savings_plan
    ):
        """A notification is generated after successful execution."""
        service = ETFService()
        today = date(2024, 6, 1)

        _, notifications = service.process_savings_plans(user, today=today)

        assert len(notifications) == 1
        assert notifications[0].notification_type == "etf_savings_plan_executed"
        assert "VWCE" in notifications[0].message


class TestStalePriceCheck:
    """Tests for stale price detection and pausing (Req 14.3)."""

    def test_stale_price_pauses_execution(
        self, db_session, user, account, position, recurring_rule, savings_plan
    ):
        """When price is >3 days old, execution is paused (Req 14.3)."""
        # Make price 4 days old
        position.current_price_updated_at = datetime(
            2024, 5, 28, 12, 0, 0, tzinfo=timezone.utc
        )
        db_session.flush()

        service = ETFService()
        today = date(2024, 6, 1)

        generated, notifications = service.process_savings_plans(user, today=today)

        assert len(generated) == 0
        assert len(notifications) == 1
        assert notifications[0].notification_type == "etf_price_stale"

    def test_stale_price_does_not_advance_due_date(
        self, db_session, user, account, position, recurring_rule, savings_plan
    ):
        """When price is stale, next_due_date is NOT advanced (Req 14.3)."""
        original_due_date = recurring_rule.next_due_date
        position.current_price_updated_at = datetime(
            2024, 5, 27, 12, 0, 0, tzinfo=timezone.utc
        )
        db_session.flush()

        service = ETFService()
        today = date(2024, 6, 1)

        service.process_savings_plans(user, today=today)

        assert recurring_rule.next_due_date == original_due_date

    def test_null_price_treated_as_stale(
        self, db_session, user, account, position, recurring_rule, savings_plan
    ):
        """When current_price is None, it's treated as stale (Req 14.3)."""
        position.current_price = None
        position.current_price_updated_at = None
        db_session.flush()

        service = ETFService()
        today = date(2024, 6, 1)

        generated, notifications = service.process_savings_plans(user, today=today)

        assert len(generated) == 0
        assert notifications[0].notification_type == "etf_price_stale"

    def test_null_updated_at_treated_as_stale(
        self, db_session, user, account, position, recurring_rule, savings_plan
    ):
        """When current_price_updated_at is None, price is treated as stale."""
        position.current_price_updated_at = None
        db_session.flush()

        service = ETFService()
        today = date(2024, 6, 1)

        generated, notifications = service.process_savings_plans(user, today=today)

        assert len(generated) == 0
        assert notifications[0].notification_type == "etf_price_stale"

    def test_exactly_3_days_old_is_not_stale(
        self, db_session, user, account, position, recurring_rule, savings_plan
    ):
        """A price exactly 3 days old is NOT stale (threshold is >3 days)."""
        # Set price to exactly 3 days before today
        position.current_price_updated_at = datetime(
            2024, 5, 29, 12, 0, 0, tzinfo=timezone.utc
        )
        db_session.flush()

        service = ETFService()
        today = date(2024, 6, 1)

        generated, notifications = service.process_savings_plans(user, today=today)

        # 3 days difference is NOT > 3, so should execute
        assert len(generated) == 1
        assert notifications[0].notification_type == "etf_savings_plan_executed"

    def test_stale_notification_includes_days(
        self, db_session, user, account, position, recurring_rule, savings_plan
    ):
        """Stale price notification includes the number of stale days."""
        position.current_price_updated_at = datetime(
            2024, 5, 25, 12, 0, 0, tzinfo=timezone.utc
        )
        db_session.flush()

        service = ETFService()
        today = date(2024, 6, 1)

        _, notifications = service.process_savings_plans(user, today=today)

        assert "7 days stale" in notifications[0].message


class TestResumeOnPriceRefresh:
    """Tests for resumption after price refresh without catch-up (Req 14.4)."""

    def test_no_retroactive_catchup_after_price_refresh(
        self, db_session, user, account, position, recurring_rule, savings_plan
    ):
        """After price refresh, only the current due date is processed (Req 14.4).

        Even if multiple due dates were missed during the stale period,
        only ONE execution happens on resume.
        """
        # Rule was due June 1, but price was stale. Now it's June 15 and
        # price was just refreshed. The rule still shows June 1 as next_due_date.
        recurring_rule.next_due_date = date(2024, 6, 1)
        position.current_price_updated_at = datetime(
            2024, 6, 14, 12, 0, 0, tzinfo=timezone.utc
        )
        db_session.flush()

        service = ETFService()
        today = date(2024, 6, 15)

        generated, _ = service.process_savings_plans(user, today=today)

        # Only ONE transaction created (not retroactive catch-up for July etc)
        assert len(generated) == 1
        # The rule's next_due_date is advanced by one period
        assert recurring_rule.next_due_date == date(2024, 7, 1)


class TestDeactivation:
    """Tests for savings plan deactivation (Req 14.5)."""

    def test_inactive_plan_not_processed(
        self, db_session, user, account, position, recurring_rule, savings_plan
    ):
        """Deactivated savings plans are skipped (Req 14.5)."""
        savings_plan.active = False
        db_session.flush()

        service = ETFService()
        today = date(2024, 6, 1)

        generated, notifications = service.process_savings_plans(user, today=today)

        assert len(generated) == 0
        assert len(notifications) == 0

    def test_inactive_plan_preserves_recurring_rule(
        self, db_session, user, account, position, recurring_rule, savings_plan
    ):
        """Deactivating a plan preserves the recurring rule (Req 14.5)."""
        savings_plan.active = False
        db_session.flush()

        service = ETFService()
        today = date(2024, 6, 1)

        service.process_savings_plans(user, today=today)

        # Recurring rule remains active and unchanged
        assert recurring_rule.active is True
        assert recurring_rule.next_due_date == date(2024, 6, 1)

    def test_inactive_recurring_rule_skips_plan(
        self, db_session, user, account, position, recurring_rule, savings_plan
    ):
        """If the underlying recurring rule is inactive, plan is not processed."""
        recurring_rule.active = False
        db_session.flush()

        service = ETFService()
        today = date(2024, 6, 1)

        generated, notifications = service.process_savings_plans(user, today=today)

        assert len(generated) == 0
        assert len(notifications) == 0


class TestRuleNotYetDue:
    """Tests for rules that are not yet due."""

    def test_rule_not_due_skips_execution(
        self, db_session, user, account, position, recurring_rule, savings_plan
    ):
        """If next_due_date is in the future, no execution happens."""
        recurring_rule.next_due_date = date(2024, 7, 1)
        db_session.flush()

        service = ETFService()
        today = date(2024, 6, 15)

        generated, notifications = service.process_savings_plans(user, today=today)

        assert len(generated) == 0
        assert len(notifications) == 0
