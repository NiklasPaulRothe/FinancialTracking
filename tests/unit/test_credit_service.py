"""Unit tests for CreditService.

Tests interest accrual, capitalization, repayment allocation, payment split
correction, forecast generation, and credit card payment conversion.

Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.9
"""

import pytest
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from app.models.account import Account
from app.models.credit import (
    Credit,
    CreditPayment,
    CreditForecastCache,
    CreditScope,
    CreditStatus,
)
from app.models.transaction import Transaction, TransactionType, TransactionScope
from app.models.user import User
from app.services.credit_service import CreditService


@pytest.fixture()
def service():
    """Create a CreditService instance."""
    return CreditService()


@pytest.fixture()
def user(db_session):
    """Create a test user."""
    user = User(
        username="testuser",
        email="test@example.com",
        password_hash="fakehash",
        income_day=25,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def account(db_session, user):
    """Create a test spending account."""
    acct = Account(
        name="Checking",
        type="spending",
        scope="personal",
        balance=Decimal("5000.00"),
        active=True,
        visible_to_partner=True,
        owner_id=user.id,
    )
    db_session.add(acct)
    db_session.flush()
    return acct


@pytest.fixture()
def credit_card_account(db_session, user):
    """Create a test credit card account."""
    acct = Account(
        name="Visa",
        type="credit_card",
        scope="personal",
        balance=Decimal("-1000.00"),
        active=True,
        visible_to_partner=True,
        credit_limit=Decimal("5000.00"),
        owner_id=user.id,
    )
    db_session.add(acct)
    db_session.flush()
    return acct


@pytest.fixture()
def credit(db_session, user, account):
    """Create a test credit with 5% yearly rate."""
    c = Credit(
        name="Home Loan",
        principal=Decimal("10000.00"),
        remaining_balance=Decimal("10000.00"),
        accrued_interest=Decimal("0.000000"),
        effective_yearly_rate=Decimal("0.050000"),
        disbursement_date=date(2024, 1, 1),
        interest_capitalization_day=15,
        status=CreditStatus.active,
        scope=CreditScope.personal,
        account_id=account.id,
        user_id=user.id,
    )
    db_session.add(c)
    db_session.flush()
    return c


@pytest.fixture()
def transaction(db_session, user, account):
    """Create a test transaction for repayment."""
    txn = Transaction(
        type=TransactionType.expense,
        amount=Decimal("500.00"),
        date=date(2024, 2, 1),
        scope=TransactionScope.personal,
        account_id=account.id,
        user_id=user.id,
    )
    db_session.add(txn)
    db_session.flush()
    return txn


class TestCreateCredit:
    """Tests for CreditService.create_credit."""

    def test_create_credit_sets_remaining_balance_to_principal(
        self, db_session, service, user, account
    ):
        """Requirement 11.1: remaining_balance equals principal on creation."""
        credit = service.create_credit(
            user=user,
            name="Car Loan",
            principal=Decimal("25000.00"),
            rate=Decimal("0.035000"),
            disbursement_date=date(2024, 3, 1),
            capitalization_day=10,
            account_id=account.id,
            scope=CreditScope.personal,
        )

        assert credit.id is not None
        assert credit.name == "Car Loan"
        assert credit.principal == Decimal("25000.00")
        assert credit.remaining_balance == Decimal("25000.00")
        assert credit.accrued_interest == Decimal("0.000000")
        assert credit.effective_yearly_rate == Decimal("0.035000")
        assert credit.status == CreditStatus.active
        assert credit.user_id == user.id

    def test_create_credit_with_shared_scope(
        self, db_session, service, user, account
    ):
        """Creating a shared credit persists with correct scope."""
        credit = service.create_credit(
            user=user,
            name="Joint Loan",
            principal=Decimal("50000.00"),
            rate=Decimal("0.040000"),
            disbursement_date=date(2024, 1, 15),
            capitalization_day=1,
            account_id=account.id,
            scope=CreditScope.shared,
        )

        assert credit.scope == CreditScope.shared


class TestAccrueDailyInterest:
    """Tests for CreditService.accrue_daily_interest."""

    def test_daily_interest_calculation(self, db_session, service, credit):
        """Requirement 11.2: daily_rate = (1 + rate)^(1/365) - 1."""
        daily_interest = service.accrue_daily_interest(credit)

        # Manual calculation
        one = Decimal("1")
        rate = Decimal("0.050000")
        daily_rate = (one + rate) ** (one / Decimal("365")) - one
        expected = (Decimal("10000.00") * daily_rate).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )

        assert daily_interest == expected
        assert credit.accrued_interest == expected

    def test_multiple_days_accumulate(self, db_session, service, credit):
        """Multiple calls accumulate interest."""
        day1 = service.accrue_daily_interest(credit)
        day2 = service.accrue_daily_interest(credit)

        # Day2 is slightly more because remaining_balance unchanged but accrued grows
        # Both should be based on remaining_balance only
        assert credit.accrued_interest == day1 + day2

    def test_no_interest_on_paid_off_credit(self, db_session, service, credit):
        """Paid-off credits accrue no interest."""
        credit.status = CreditStatus.paid_off
        db_session.flush()

        result = service.accrue_daily_interest(credit)
        assert result == Decimal("0.000000")

    def test_no_interest_with_zero_rate(self, db_session, service, credit):
        """Zero rate yields zero interest."""
        credit.effective_yearly_rate = Decimal("0.000000")
        db_session.flush()

        result = service.accrue_daily_interest(credit)
        assert result == Decimal("0.000000")

    def test_no_interest_with_zero_balance(self, db_session, service, credit):
        """Zero remaining balance yields zero interest."""
        credit.remaining_balance = Decimal("0.00")
        db_session.flush()

        result = service.accrue_daily_interest(credit)
        assert result == Decimal("0.000000")


class TestCapitalizeInterest:
    """Tests for CreditService.capitalize_interest."""

    def test_capitalization_adds_accrued_to_balance(
        self, db_session, service, credit
    ):
        """Requirement 11.3: remaining_balance += accrued_interest, then reset."""
        credit.accrued_interest = Decimal("45.123456")
        db_session.flush()

        old_balance = credit.remaining_balance
        service.capitalize_interest(credit)

        expected_balance = old_balance + Decimal("45.12")
        assert credit.remaining_balance == expected_balance
        assert credit.accrued_interest == Decimal("0.000000")

    def test_capitalization_rounds_to_two_decimals(
        self, db_session, service, credit
    ):
        """Capitalized amount rounds to 2 decimal places."""
        credit.accrued_interest = Decimal("12.345678")
        db_session.flush()

        service.capitalize_interest(credit)

        # 12.345678 rounds to 12.35 (ROUND_HALF_UP)
        assert credit.remaining_balance == Decimal("10000.00") + Decimal("12.35")

    def test_no_capitalization_when_zero_accrued(
        self, db_session, service, credit
    ):
        """No change when accrued interest is zero."""
        old_balance = credit.remaining_balance
        service.capitalize_interest(credit)

        assert credit.remaining_balance == old_balance
        assert credit.accrued_interest == Decimal("0.000000")

    def test_no_capitalization_on_paid_off_credit(
        self, db_session, service, credit
    ):
        """Paid-off credits skip capitalization."""
        credit.status = CreditStatus.paid_off
        credit.accrued_interest = Decimal("100.000000")
        db_session.flush()

        service.capitalize_interest(credit)
        # Should remain unchanged
        assert credit.accrued_interest == Decimal("100.000000")


class TestApplyRepayment:
    """Tests for CreditService.apply_repayment."""

    def test_repayment_interest_first_then_principal(
        self, db_session, service, credit, transaction
    ):
        """Requirement 11.4: allocate to interest first, then principal."""
        credit.accrued_interest = Decimal("100.000000")
        db_session.flush()

        payment = service.apply_repayment(credit, Decimal("500.00"), transaction)

        assert payment.interest_portion == Decimal("100.00")
        assert payment.principal_portion == Decimal("400.00")
        assert payment.total_amount == Decimal("500.00")
        assert credit.remaining_balance == Decimal("9600.00")
        assert credit.accrued_interest.quantize(Decimal("0.01")) == Decimal("0.00")

    def test_repayment_only_covers_interest(
        self, db_session, service, credit, transaction
    ):
        """Payment smaller than accrued interest only reduces interest."""
        credit.accrued_interest = Decimal("200.000000")
        db_session.flush()

        transaction.amount = Decimal("150.00")
        db_session.flush()

        payment = service.apply_repayment(credit, Decimal("150.00"), transaction)

        assert payment.interest_portion == Decimal("150.00")
        assert payment.principal_portion == Decimal("0.00")
        assert credit.remaining_balance == Decimal("10000.00")

    def test_overpayment_caps_at_total_owed(
        self, db_session, service, credit, transaction
    ):
        """Requirement 11.5: cap at accrued + remaining, set paid_off."""
        credit.remaining_balance = Decimal("100.00")
        credit.accrued_interest = Decimal("10.000000")
        db_session.flush()

        payment = service.apply_repayment(credit, Decimal("500.00"), transaction)

        assert payment.total_amount == Decimal("110.00")
        assert payment.interest_portion == Decimal("10.00")
        assert payment.principal_portion == Decimal("100.00")
        assert credit.remaining_balance == Decimal("0.00")
        assert credit.accrued_interest == Decimal("0.000000")
        assert credit.status == CreditStatus.paid_off

    def test_exact_payoff_sets_paid_off(
        self, db_session, service, credit, transaction
    ):
        """Paying exactly what's owed sets status to paid_off."""
        credit.remaining_balance = Decimal("500.00")
        credit.accrued_interest = Decimal("25.000000")
        db_session.flush()

        payment = service.apply_repayment(credit, Decimal("525.00"), transaction)

        assert credit.status == CreditStatus.paid_off
        assert credit.remaining_balance == Decimal("0.00")

    def test_repayment_no_interest_all_principal(
        self, db_session, service, credit, transaction
    ):
        """With zero accrued interest, entire payment goes to principal."""
        payment = service.apply_repayment(credit, Decimal("500.00"), transaction)

        assert payment.interest_portion == Decimal("0.00")
        assert payment.principal_portion == Decimal("500.00")
        assert credit.remaining_balance == Decimal("9500.00")

    def test_repayment_on_paid_off_raises(
        self, db_session, service, credit, transaction
    ):
        """Cannot repay a paid-off credit."""
        credit.status = CreditStatus.paid_off
        db_session.flush()

        with pytest.raises(ValueError, match="paid-off"):
            service.apply_repayment(credit, Decimal("100.00"), transaction)

    def test_payment_record_created(
        self, db_session, service, credit, transaction
    ):
        """A CreditPayment record is persisted linking credit and transaction."""
        payment = service.apply_repayment(credit, Decimal("300.00"), transaction)

        assert payment.id is not None
        assert payment.credit_id == credit.id
        assert payment.transaction_id == transaction.id
        assert payment.manual_correction is False


class TestCorrectPaymentSplit:
    """Tests for CreditService.correct_payment_split."""

    def test_correct_split_updates_balance(
        self, db_session, service, credit, transaction
    ):
        """Requirement 11.6: manual correction recalculates remaining_balance."""
        # First create a payment
        credit.accrued_interest = Decimal("50.000000")
        db_session.flush()
        payment = service.apply_repayment(credit, Decimal("200.00"), transaction)

        # Original: interest=50, principal=150
        assert payment.interest_portion == Decimal("50.00")
        assert payment.principal_portion == Decimal("150.00")
        assert credit.remaining_balance == Decimal("9850.00")

        # Correct: more went to interest than thought
        corrected = service.correct_payment_split(
            payment_id=payment.id,
            interest_portion=Decimal("80.00"),
            principal_portion=Decimal("120.00"),
        )

        assert corrected.interest_portion == Decimal("80.00")
        assert corrected.principal_portion == Decimal("120.00")
        assert corrected.manual_correction is True
        # Balance should increase by difference (150 - 120 = 30 less principal paid)
        assert credit.remaining_balance == Decimal("9880.00")

    def test_correct_split_invalid_sum_raises(
        self, db_session, service, credit, transaction
    ):
        """Portions must sum to total_amount."""
        payment = service.apply_repayment(credit, Decimal("200.00"), transaction)

        with pytest.raises(ValueError, match="must equal total amount"):
            service.correct_payment_split(
                payment_id=payment.id,
                interest_portion=Decimal("100.00"),
                principal_portion=Decimal("150.00"),
            )

    def test_correct_split_nonexistent_payment_raises(self, db_session, service):
        """Non-existent payment ID raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            service.correct_payment_split(
                payment_id=99999,
                interest_portion=Decimal("50.00"),
                principal_portion=Decimal("50.00"),
            )


class TestGenerateForecast:
    """Tests for CreditService.generate_forecast."""

    def test_forecast_with_no_payments_creates_single_entry(
        self, db_session, service, credit
    ):
        """No payment history creates minimal forecast (current state only)."""
        service.generate_forecast(credit)

        entries = CreditForecastCache.query.filter_by(
            credit_id=credit.id
        ).all()
        assert len(entries) == 1
        assert entries[0].month_offset == 0
        assert entries[0].projected_balance == credit.remaining_balance

    def test_forecast_with_payment_history_creates_entries(
        self, db_session, service, credit, transaction
    ):
        """With payment history, forecast generates multiple monthly entries."""
        # Create a payment to establish history
        service.apply_repayment(credit, Decimal("500.00"), transaction)

        # Re-generate forecast
        service.generate_forecast(credit)

        entries = CreditForecastCache.query.filter_by(
            credit_id=credit.id
        ).order_by(CreditForecastCache.month_offset).all()

        assert len(entries) > 1
        assert entries[0].month_offset == 0
        # Balance should decrease over time
        assert entries[-1].projected_balance <= entries[0].projected_balance

    def test_forecast_capped_at_360_months(
        self, db_session, service, credit, transaction
    ):
        """Forecast never exceeds 360 months."""
        # Use a tiny payment to make payoff far in the future
        transaction.amount = Decimal("1.00")
        db_session.flush()

        payment = CreditPayment(
            credit_id=credit.id,
            transaction_id=transaction.id,
            total_amount=Decimal("1.00"),
            interest_portion=Decimal("0.50"),
            principal_portion=Decimal("0.50"),
            manual_correction=False,
        )
        db_session.add(payment)
        db_session.flush()

        service.generate_forecast(credit)

        entries = CreditForecastCache.query.filter_by(
            credit_id=credit.id
        ).all()
        max_offset = max(e.month_offset for e in entries)
        assert max_offset <= 361  # 0 to 360 inclusive + possible final entry

    def test_forecast_skipped_for_paid_off(
        self, db_session, service, credit
    ):
        """Paid-off credits get no forecast entries."""
        credit.status = CreditStatus.paid_off
        db_session.flush()

        service.generate_forecast(credit)

        entries = CreditForecastCache.query.filter_by(
            credit_id=credit.id
        ).all()
        assert len(entries) == 0


class TestConvertCCPaymentToCredit:
    """Tests for CreditService.convert_cc_payment_to_credit."""

    def test_convert_creates_credit_with_correct_fields(
        self, db_session, service, user, account, credit_card_account
    ):
        """Requirement 11.8: creates Credit with converted flag and link."""
        txn = Transaction(
            type=TransactionType.credit_card_payment,
            amount=Decimal("200.00"),
            date=date(2024, 3, 15),
            scope=TransactionScope.personal,
            account_id=account.id,
            destination_account_id=credit_card_account.id,
            user_id=user.id,
        )
        db_session.add(txn)
        db_session.flush()

        new_credit = service.convert_cc_payment_to_credit(txn, user)

        assert new_credit.id is not None
        assert new_credit.principal == Decimal("200.00")
        assert new_credit.remaining_balance == Decimal("200.00")
        assert new_credit.converted_from_credit_card_payment is True
        assert new_credit.linked_transaction_id == txn.id
        assert new_credit.status == CreditStatus.active

    def test_convert_reduces_credit_card_balance(
        self, db_session, service, user, account, credit_card_account
    ):
        """Converting reduces the credit card debt."""
        old_balance = credit_card_account.balance  # -1000.00
        txn = Transaction(
            type=TransactionType.credit_card_payment,
            amount=Decimal("200.00"),
            date=date(2024, 3, 15),
            scope=TransactionScope.personal,
            account_id=account.id,
            destination_account_id=credit_card_account.id,
            user_id=user.id,
        )
        db_session.add(txn)
        db_session.flush()

        service.convert_cc_payment_to_credit(txn, user)

        # Credit card balance should increase (reduce debt)
        assert credit_card_account.balance == old_balance + Decimal("200.00")

    def test_convert_non_cc_payment_raises(
        self, db_session, service, user, transaction
    ):
        """Only credit_card_payment type can be converted."""
        with pytest.raises(ValueError, match="credit_card_payment"):
            service.convert_cc_payment_to_credit(transaction, user)
