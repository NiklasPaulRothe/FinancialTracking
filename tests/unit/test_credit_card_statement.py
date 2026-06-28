"""Unit tests for Credit Card statement period handling in TransactionService.

Tests auto-assignment of statement_closing_date, posted=false logic,
mark-as-posted transition, and credit card to mini-credit conversion.

Validates: Requirements 24.1, 24.2, 24.3, 24.4, 24.5, 24.6
"""

import pytest
from datetime import date
from decimal import Decimal

from app.models.account import Account, AccountType, AccountScope
from app.models.transaction import Transaction, TransactionType, TransactionScope
from app.models.user import User
from app.services.transaction_service import TransactionService
from tests.factories import UserFactory, AccountFactory


@pytest.fixture()
def service():
    """Provide a TransactionService instance."""
    return TransactionService()


@pytest.fixture()
def user(db_session):
    """Create a test user."""
    return UserFactory()


@pytest.fixture()
def credit_card_account(db_session, user):
    """Create a credit card account with statement_closing_day=15."""
    account = AccountFactory(
        owner=user,
        type="credit_card",
        scope="personal",
        balance=Decimal("-500.00"),
        credit_limit=Decimal("2000.00"),
        statement_closing_day=15,
        payment_due_day=5,
    )
    db_session.flush()
    return account


@pytest.fixture()
def credit_card_account_day_28(db_session, user):
    """Create a credit card account with statement_closing_day=28."""
    account = AccountFactory(
        owner=user,
        type="credit_card",
        scope="personal",
        balance=Decimal("-200.00"),
        credit_limit=Decimal("3000.00"),
        statement_closing_day=28,
        payment_due_day=10,
    )
    db_session.flush()
    return account


@pytest.fixture()
def shared_credit_card_account(db_session, user):
    """Create a shared credit card account."""
    account = AccountFactory(
        owner=user,
        type="credit_card",
        scope="shared",
        balance=Decimal("-100.00"),
        credit_limit=Decimal("1000.00"),
        statement_closing_day=20,
        payment_due_day=7,
    )
    db_session.flush()
    return account


@pytest.fixture()
def spending_account(db_session, user):
    """Create a spending account with 5000 balance."""
    account = AccountFactory(
        owner=user,
        type="spending",
        scope="personal",
        balance=Decimal("5000.00"),
    )
    db_session.flush()
    return account


class TestAssignStatementClosingDate:
    """Tests for statement_closing_date auto-assignment logic (Req 24.2)."""

    def test_transaction_day_before_closing_day_current_month(self, service):
        """Transaction on day 10, closing day 15 → current month."""
        result = service.assign_statement_closing_date(date(2024, 3, 10), 15)
        assert result == date(2024, 3, 15)

    def test_transaction_day_equals_closing_day_current_month(self, service):
        """Transaction on day 15, closing day 15 → current month."""
        result = service.assign_statement_closing_date(date(2024, 3, 15), 15)
        assert result == date(2024, 3, 15)

    def test_transaction_day_after_closing_day_next_month(self, service):
        """Transaction on day 16, closing day 15 → next month."""
        result = service.assign_statement_closing_date(date(2024, 3, 16), 15)
        assert result == date(2024, 4, 15)

    def test_december_rollover_to_january(self, service):
        """Transaction on day 20, closing day 15 in December → January next year."""
        result = service.assign_statement_closing_date(date(2024, 12, 20), 15)
        assert result == date(2025, 1, 15)

    def test_closing_day_exceeds_month_days_february(self, service):
        """Closing day 28 in Feb (non-leap): effective is 28, day 28 → current month."""
        result = service.assign_statement_closing_date(date(2023, 2, 28), 28)
        assert result == date(2023, 2, 28)

    def test_closing_day_exceeds_month_days_february_leap(self, service):
        """Closing day 28 in Feb (leap year): effective is 28, day 28 → current month."""
        result = service.assign_statement_closing_date(date(2024, 2, 28), 28)
        assert result == date(2024, 2, 28)

    def test_february_day_before_closing_day_28(self, service):
        """Transaction Feb 15, closing day 28 → current month Feb 28."""
        result = service.assign_statement_closing_date(date(2024, 2, 15), 28)
        assert result == date(2024, 2, 28)

    def test_closing_day_1_transaction_day_1(self, service):
        """Transaction on day 1, closing day 1 → current month."""
        result = service.assign_statement_closing_date(date(2024, 5, 1), 1)
        assert result == date(2024, 5, 1)

    def test_closing_day_1_transaction_day_2(self, service):
        """Transaction on day 2, closing day 1 → next month."""
        result = service.assign_statement_closing_date(date(2024, 5, 2), 1)
        assert result == date(2024, 6, 1)

    def test_next_month_closing_day_adjusted_for_short_month(self, service):
        """Transaction Jan 30, closing day 28 → next month Feb 28."""
        # Closing day 28, transaction day 30 > 28, so next month
        result = service.assign_statement_closing_date(date(2024, 1, 30), 28)
        assert result == date(2024, 2, 28)


class TestCreateTransactionStatementAssignment:
    """Tests that create_transaction auto-assigns statement_closing_date (Req 24.2)."""

    def test_expense_on_cc_assigns_statement_date(
        self, db_session, service, user, credit_card_account
    ):
        """Expense on credit card auto-assigns statement_closing_date."""
        data = {
            "type": "expense",
            "amount": Decimal("100.00"),
            "date": date(2024, 3, 10),
            "account_id": credit_card_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)
        assert txn.statement_closing_date == date(2024, 3, 15)

    def test_expense_on_cc_after_closing_day(
        self, db_session, service, user, credit_card_account
    ):
        """Expense after closing day goes to next month's statement."""
        data = {
            "type": "expense",
            "amount": Decimal("50.00"),
            "date": date(2024, 3, 20),
            "account_id": credit_card_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)
        assert txn.statement_closing_date == date(2024, 4, 15)

    def test_spending_account_no_statement_date(
        self, db_session, service, user, spending_account
    ):
        """Non-credit-card transactions do not get statement_closing_date."""
        data = {
            "type": "expense",
            "amount": Decimal("50.00"),
            "date": date(2024, 3, 10),
            "account_id": spending_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)
        assert txn.statement_closing_date is None

    def test_cc_without_closing_day_no_statement_date(
        self, db_session, service, user
    ):
        """Credit card without statement_closing_day doesn't assign date."""
        account = AccountFactory(
            owner=user,
            type="credit_card",
            scope="personal",
            balance=Decimal("-100.00"),
            credit_limit=Decimal("1000.00"),
            statement_closing_day=None,
        )
        db_session.flush()
        data = {
            "type": "expense",
            "amount": Decimal("30.00"),
            "date": date(2024, 3, 10),
            "account_id": account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)
        assert txn.statement_closing_date is None


class TestPostedFalseLogic:
    """Tests for posted=false credit card transaction logic (Req 24.3)."""

    def test_pending_transaction_reduces_balance(
        self, db_session, service, user, credit_card_account
    ):
        """Pending CC transaction still reduces balance (affects available credit)."""
        original_balance = credit_card_account.balance
        data = {
            "type": "expense",
            "amount": Decimal("150.00"),
            "date": date(2024, 3, 10),
            "account_id": credit_card_account.id,
            "scope": "personal",
            "posted": False,
        }
        txn = service.create_transaction(data, user)
        assert txn.posted is False
        # Balance should decrease (more debt)
        assert credit_card_account.balance == original_balance - Decimal("150.00")

    def test_pending_transaction_excluded_from_statement_balance(
        self, db_session, service, user, credit_card_account
    ):
        """Pending CC transaction excluded from statement balance."""
        # Create a posted transaction
        data_posted = {
            "type": "expense",
            "amount": Decimal("100.00"),
            "date": date(2024, 3, 10),
            "account_id": credit_card_account.id,
            "scope": "personal",
            "posted": True,
        }
        service.create_transaction(data_posted, user)

        # Create a pending transaction (same period)
        data_pending = {
            "type": "expense",
            "amount": Decimal("50.00"),
            "date": date(2024, 3, 12),
            "account_id": credit_card_account.id,
            "scope": "personal",
            "posted": False,
        }
        service.create_transaction(data_pending, user)

        # Statement balance should only include posted transaction
        stmt_balance = service.get_statement_balance(
            credit_card_account.id, date(2024, 3, 15)
        )
        assert stmt_balance == Decimal("100.00")

    def test_pending_transaction_assigns_statement_date(
        self, db_session, service, user, credit_card_account
    ):
        """Pending CC transaction still gets statement_closing_date assigned."""
        data = {
            "type": "expense",
            "amount": Decimal("75.00"),
            "date": date(2024, 3, 10),
            "account_id": credit_card_account.id,
            "scope": "personal",
            "posted": False,
        }
        txn = service.create_transaction(data, user)
        assert txn.statement_closing_date == date(2024, 3, 15)


class TestMarkAsPosted:
    """Tests for mark_as_posted transition (Req 24.4)."""

    def test_mark_pending_as_posted(
        self, db_session, service, user, credit_card_account
    ):
        """Mark a pending transaction as posted."""
        data = {
            "type": "expense",
            "amount": Decimal("200.00"),
            "date": date(2024, 3, 10),
            "account_id": credit_card_account.id,
            "scope": "personal",
            "posted": False,
        }
        txn = service.create_transaction(data, user)
        assert txn.posted is False

        result = service.mark_as_posted(txn.id, user)
        assert result.posted is True

    def test_mark_posted_includes_in_statement_balance(
        self, db_session, service, user, credit_card_account
    ):
        """After marking as posted, transaction is included in statement balance."""
        data = {
            "type": "expense",
            "amount": Decimal("200.00"),
            "date": date(2024, 3, 10),
            "account_id": credit_card_account.id,
            "scope": "personal",
            "posted": False,
        }
        txn = service.create_transaction(data, user)

        # Statement balance should be 0 initially
        stmt_balance = service.get_statement_balance(
            credit_card_account.id, date(2024, 3, 15)
        )
        assert stmt_balance == Decimal("0")

        # Mark as posted
        service.mark_as_posted(txn.id, user)

        # Now included in statement balance
        stmt_balance = service.get_statement_balance(
            credit_card_account.id, date(2024, 3, 15)
        )
        assert stmt_balance == Decimal("200.00")

    def test_mark_already_posted_raises(
        self, db_session, service, user, credit_card_account
    ):
        """Marking an already-posted transaction raises ValueError."""
        data = {
            "type": "expense",
            "amount": Decimal("100.00"),
            "date": date(2024, 3, 10),
            "account_id": credit_card_account.id,
            "scope": "personal",
            "posted": True,
        }
        txn = service.create_transaction(data, user)

        with pytest.raises(ValueError, match="already posted"):
            service.mark_as_posted(txn.id, user)


class TestConvertCcToMiniCredit:
    """Tests for credit card to mini-credit conversion (Req 24.5, 24.6)."""

    def test_convert_full_amount(
        self, db_session, service, user, credit_card_account
    ):
        """Convert full transaction amount to mini-credit."""
        data = {
            "type": "expense",
            "amount": Decimal("300.00"),
            "date": date(2024, 3, 10),
            "account_id": credit_card_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)
        original_balance = credit_card_account.balance

        credit = service.convert_cc_to_mini_credit(txn.id, Decimal("300.00"), user)

        assert credit.principal == Decimal("300.00")
        assert credit.remaining_balance == Decimal("300.00")
        assert credit.converted_from_credit_card_payment is True
        assert credit.linked_transaction_id == txn.id
        # Balance should increase (less debt) by the converted amount
        assert credit_card_account.balance == original_balance + Decimal("300.00")

    def test_convert_partial_amount(
        self, db_session, service, user, credit_card_account
    ):
        """Convert partial transaction amount to mini-credit."""
        data = {
            "type": "expense",
            "amount": Decimal("500.00"),
            "date": date(2024, 3, 10),
            "account_id": credit_card_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)
        original_balance = credit_card_account.balance

        credit = service.convert_cc_to_mini_credit(txn.id, Decimal("200.00"), user)

        assert credit.principal == Decimal("200.00")
        assert credit_card_account.balance == original_balance + Decimal("200.00")

    def test_convert_exceeds_amount_raises(
        self, db_session, service, user, credit_card_account
    ):
        """Converting more than transaction amount raises ValueError."""
        data = {
            "type": "expense",
            "amount": Decimal("100.00"),
            "date": date(2024, 3, 10),
            "account_id": credit_card_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)

        with pytest.raises(ValueError, match="must not exceed"):
            service.convert_cc_to_mini_credit(txn.id, Decimal("150.00"), user)

    def test_convert_non_cc_account_raises(
        self, db_session, service, user, spending_account
    ):
        """Converting a transaction on a non-CC account raises ValueError."""
        data = {
            "type": "expense",
            "amount": Decimal("50.00"),
            "date": date(2024, 3, 10),
            "account_id": spending_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)

        with pytest.raises(ValueError, match="credit card"):
            service.convert_cc_to_mini_credit(txn.id, Decimal("50.00"), user)

    def test_convert_shared_cc_sets_shared_scope(
        self, db_session, service, user, shared_credit_card_account
    ):
        """Conversion from shared CC sets scope to shared on the credit."""
        data = {
            "type": "expense",
            "amount": Decimal("100.00"),
            "date": date(2024, 3, 10),
            "account_id": shared_credit_card_account.id,
            "scope": "shared",
        }
        txn = service.create_transaction(data, user)

        credit = service.convert_cc_to_mini_credit(txn.id, Decimal("100.00"), user)

        from app.models.credit import CreditScope
        assert credit.scope == CreditScope.shared

    def test_convert_minimum_amount(
        self, db_session, service, user, credit_card_account
    ):
        """Converting the minimum amount (0.01) succeeds."""
        data = {
            "type": "expense",
            "amount": Decimal("100.00"),
            "date": date(2024, 3, 10),
            "account_id": credit_card_account.id,
            "scope": "personal",
        }
        txn = service.create_transaction(data, user)

        credit = service.convert_cc_to_mini_credit(txn.id, Decimal("0.01"), user)
        assert credit.principal == Decimal("0.01")
