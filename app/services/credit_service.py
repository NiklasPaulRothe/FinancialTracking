"""Credit service for Haushaltsbuch.

Implements credit lifecycle management including creation, daily interest accrual,
interest capitalization, repayment allocation, payment split correction,
forecast cache generation, and credit card payment to mini-credit conversion.

Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.9
"""

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from app.extensions import db
from app.models.credit import (
    Credit,
    CreditPayment,
    CreditForecastCache,
    CreditScope,
    CreditStatus,
)
from app.models.transaction import Transaction
from app.models.user import User
from app.services.audit_service import AuditService


class CreditService:
    """Service class encapsulating all credit/loan business logic."""

    def __init__(self) -> None:
        self._audit_service = AuditService()

    def create_credit(
        self,
        user: User,
        name: str,
        principal: Decimal,
        rate: Decimal,
        disbursement_date: date,
        capitalization_day: int,
        account_id: int,
        scope: CreditScope,
    ) -> Credit:
        """Create a new credit with remaining_balance equal to principal.

        Validates: Requirement 11.1

        Args:
            user: The owning user.
            name: Credit name (max 100 characters).
            principal: Loan principal amount (0.01 to 999,999,999.99).
            rate: Effective yearly rate as decimal (0.0 to 1.0).
            disbursement_date: Date the loan was disbursed.
            capitalization_day: Day of month for interest capitalization (1-28).
            account_id: Linked account ID.
            scope: Credit scope (personal or shared).

        Returns:
            The newly created Credit instance.
        """
        credit = Credit(
            name=name,
            principal=principal,
            remaining_balance=principal,
            accrued_interest=Decimal("0.000000"),
            effective_yearly_rate=rate,
            disbursement_date=disbursement_date,
            interest_capitalization_day=capitalization_day,
            status=CreditStatus.active,
            scope=scope if isinstance(scope, CreditScope) else CreditScope(scope),
            account_id=account_id,
            user_id=user.id,
        )
        db.session.add(credit)
        db.session.flush()

        # Audit log (Req 22.1)
        self._audit_service.log_change(
            action="create",
            model="Credit",
            record_id=credit.id,
            old_values=None,
            new_values={
                "name": credit.name,
                "principal": str(credit.principal),
                "rate": str(credit.effective_yearly_rate),
                "scope": credit.scope.value,
                "account_id": credit.account_id,
            },
            user_id=user.id,
        )

        db.session.commit()
        return credit

    def accrue_daily_interest(self, credit: Credit) -> Decimal:
        """Calculate and add one day's interest to accrued_interest.

        Validates: Requirement 11.2

        Formula: daily_rate = (1 + effective_yearly_rate)^(1/365) - 1
                 daily_interest = remaining_balance * daily_rate

        Args:
            credit: The credit to accrue interest on.

        Returns:
            The daily interest amount accrued.
        """
        if credit.status == CreditStatus.paid_off:
            return Decimal("0.000000")

        if credit.remaining_balance <= 0 or credit.effective_yearly_rate <= 0:
            return Decimal("0.000000")

        # daily_rate = (1 + effective_yearly_rate)^(1/365) - 1
        one = Decimal("1")
        exponent = one / Decimal("365")
        base = one + credit.effective_yearly_rate
        # Use Python's Decimal power for precision
        daily_rate = base ** exponent - one

        daily_interest = credit.remaining_balance * daily_rate
        # Round to 6 decimal places for storage precision
        daily_interest = daily_interest.quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )

        credit.accrued_interest = credit.accrued_interest + daily_interest
        db.session.commit()
        return daily_interest

    def capitalize_interest(self, credit: Credit) -> None:
        """Add accrued interest to remaining_balance and reset accrued to zero.

        Validates: Requirement 11.3

        This is called on the credit's interest_capitalization_day by the scheduler.

        Args:
            credit: The credit to capitalize interest on.
        """
        if credit.status == CreditStatus.paid_off:
            return

        if credit.accrued_interest <= 0:
            return

        # Round to 2 decimal places when adding to balance
        capitalized_amount = credit.accrued_interest.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        credit.remaining_balance = credit.remaining_balance + capitalized_amount
        credit.accrued_interest = Decimal("0.000000")

        # Audit log (Req 22.2 - system-generated action)
        self._audit_service.log_change(
            action="update",
            model="Credit",
            record_id=credit.id,
            old_values={"accrued_interest": str(capitalized_amount)},
            new_values={"remaining_balance": str(credit.remaining_balance), "accrued_interest": "0.000000"},
            user_id=None,
        )

        db.session.commit()

        # Recalculate forecast after capitalization
        self.generate_forecast(credit)

    def apply_repayment(
        self,
        credit: Credit,
        amount: Decimal,
        transaction: Transaction,
    ) -> CreditPayment:
        """Allocate a repayment: interest first, then principal.

        Validates: Requirements 11.4, 11.5, 11.9

        If the repayment exceeds total owed (accrued_interest + remaining_balance),
        the applied amount is capped, remaining_balance is set to zero,
        accrued_interest is set to zero, and status becomes paid_off.

        Args:
            credit: The credit to apply repayment to.
            amount: The repayment amount.
            transaction: The linked transaction record.

        Returns:
            The created CreditPayment record.
        """
        if credit.status == CreditStatus.paid_off:
            raise ValueError("Cannot apply repayment to a paid-off credit.")

        total_owed = credit.accrued_interest.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ) + credit.remaining_balance

        # Cap the applied amount at total owed (overpayment cap)
        applied_amount = min(amount, total_owed)

        # Allocate to interest first
        accrued_rounded = credit.accrued_interest.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        interest_portion = min(applied_amount, accrued_rounded)
        remainder = applied_amount - interest_portion

        # Then allocate remainder to principal
        principal_portion = min(remainder, credit.remaining_balance)

        # Update credit state
        # Reduce accrued_interest by the interest portion paid
        if interest_portion > 0:
            credit.accrued_interest = credit.accrued_interest - interest_portion
            # Clamp to zero to avoid floating point issues
            if credit.accrued_interest < 0:
                credit.accrued_interest = Decimal("0.000000")

        credit.remaining_balance = credit.remaining_balance - principal_portion

        # Check if fully paid off
        if (
            credit.remaining_balance <= 0
            and credit.accrued_interest.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            <= 0
        ):
            credit.remaining_balance = Decimal("0.00")
            credit.accrued_interest = Decimal("0.000000")
            credit.status = CreditStatus.paid_off

        # Create CreditPayment record
        payment = CreditPayment(
            credit_id=credit.id,
            transaction_id=transaction.id,
            total_amount=applied_amount,
            interest_portion=interest_portion,
            principal_portion=principal_portion,
            manual_correction=False,
        )
        db.session.add(payment)

        # Audit log (Req 22.1)
        self._audit_service.log_change(
            action="update",
            model="Credit",
            record_id=credit.id,
            old_values=None,
            new_values={
                "repayment_amount": str(applied_amount),
                "remaining_balance": str(credit.remaining_balance),
                "status": credit.status.value,
            },
            user_id=None,
        )

        db.session.commit()

        # Recalculate forecast after repayment
        if credit.status != CreditStatus.paid_off:
            self.generate_forecast(credit)

        return payment

    def correct_payment_split(
        self,
        payment_id: int,
        interest_portion: Decimal,
        principal_portion: Decimal,
    ) -> CreditPayment:
        """Manually correct the interest/principal split of a CreditPayment.

        Validates: Requirement 11.6

        Recalculates remaining_balance based on the corrected principal portion.

        Args:
            payment_id: ID of the CreditPayment to correct.
            interest_portion: New interest portion amount.
            principal_portion: New principal portion amount.

        Returns:
            The updated CreditPayment record.

        Raises:
            ValueError: If payment not found or split doesn't sum to total.
        """
        payment = db.session.get(CreditPayment, payment_id)
        if payment is None:
            raise ValueError(f"CreditPayment with id {payment_id} not found.")

        # Validate that portions sum to total_amount
        if interest_portion + principal_portion != payment.total_amount:
            raise ValueError(
                f"Interest portion ({interest_portion}) + principal portion "
                f"({principal_portion}) must equal total amount ({payment.total_amount})."
            )

        # Calculate the difference in principal portion to adjust remaining_balance
        old_principal = payment.principal_portion
        principal_diff = principal_portion - old_principal

        # Update the payment record
        payment.interest_portion = interest_portion
        payment.principal_portion = principal_portion
        payment.manual_correction = True

        # Recalculate credit remaining_balance
        credit = payment.credit
        credit.remaining_balance = credit.remaining_balance - principal_diff

        # Ensure remaining_balance doesn't go below zero
        if credit.remaining_balance <= 0:
            credit.remaining_balance = Decimal("0.00")
            credit.accrued_interest = Decimal("0.000000")
            credit.status = CreditStatus.paid_off

        # Audit log (Req 22.1)
        self._audit_service.log_change(
            action="update",
            model="CreditPayment",
            record_id=payment.id,
            old_values={
                "interest_portion": str(old_principal),
                "principal_portion": str(old_principal),
            },
            new_values={
                "interest_portion": str(interest_portion),
                "principal_portion": str(principal_portion),
                "manual_correction": True,
            },
            user_id=None,
        )

        db.session.commit()

        # Recalculate forecast
        if credit.status != CreditStatus.paid_off:
            self.generate_forecast(credit)

        return payment

    def generate_forecast(self, credit: Credit) -> None:
        """Generate CreditForecastCache entries for monthly intervals.

        Validates: Requirement 11.7

        Generates projections from today through projected payoff date,
        capped at 360 months. Assumes current rate and estimates monthly
        payment from recent payment history.

        Args:
            credit: The credit to generate forecast for.
        """
        if credit.status == CreditStatus.paid_off:
            return

        # Clear existing forecast cache
        CreditForecastCache.query.filter_by(credit_id=credit.id).delete()

        # Estimate monthly payment from payment history
        monthly_payment = self._estimate_monthly_payment(credit)
        if monthly_payment <= 0:
            # If no payment history, generate minimal forecast showing current state
            now = datetime.now(timezone.utc)
            entry = CreditForecastCache(
                credit_id=credit.id,
                month_offset=0,
                projected_balance=credit.remaining_balance,
                projected_interest=credit.accrued_interest.quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                ),
                recalculated_at=now,
            )
            db.session.add(entry)
            db.session.commit()
            return

        # Calculate daily rate for projections
        one = Decimal("1")
        exponent = one / Decimal("365")
        base = one + credit.effective_yearly_rate
        daily_rate = base ** exponent - one

        # Project monthly balances
        balance = credit.remaining_balance
        accrued = credit.accrued_interest
        now = datetime.now(timezone.utc)
        max_months = 360

        for month_offset in range(max_months + 1):
            # Record current state
            entry = CreditForecastCache(
                credit_id=credit.id,
                month_offset=month_offset,
                projected_balance=balance.quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                ),
                projected_interest=accrued.quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                ),
                recalculated_at=now,
            )
            db.session.add(entry)

            if balance <= 0:
                break

            # Simulate one month (approximately 30 days of interest accrual)
            for _ in range(30):
                daily_interest = balance * daily_rate
                accrued = accrued + daily_interest

            # Simulate capitalization once per month
            capitalized = accrued.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            balance = balance + capitalized
            accrued = Decimal("0.000000")

            # Simulate monthly payment (interest first, then principal)
            interest_paid = min(monthly_payment, capitalized)
            remainder = monthly_payment - interest_paid
            principal_paid = min(remainder, balance)
            balance = balance - principal_paid

            if balance <= 0:
                balance = Decimal("0.00")
                # Add final entry showing paid off
                final_entry = CreditForecastCache(
                    credit_id=credit.id,
                    month_offset=month_offset + 1,
                    projected_balance=Decimal("0.00"),
                    projected_interest=Decimal("0.00"),
                    recalculated_at=now,
                )
                db.session.add(final_entry)
                break

        db.session.commit()

    def convert_cc_payment_to_credit(
        self, transaction: Transaction, user: User
    ) -> Credit:
        """Convert a credit_card_payment transaction to a mini-credit.

        Validates: Requirement 11.8

        Creates a Credit record with converted_from_credit_card_payment=True,
        linked to the original transaction, and reduces the credit card balance
        by the converted amount.

        Args:
            transaction: The credit_card_payment transaction to convert.
            user: The user performing the conversion.

        Returns:
            The newly created Credit instance.
        """
        from app.models.transaction import TransactionType

        if transaction.type != TransactionType.credit_card_payment:
            raise ValueError(
                "Only credit_card_payment transactions can be converted to credits."
            )

        credit = Credit(
            name=f"CC Payment Credit - {transaction.date.isoformat()}",
            principal=transaction.amount,
            remaining_balance=transaction.amount,
            accrued_interest=Decimal("0.000000"),
            effective_yearly_rate=Decimal("0.000000"),
            disbursement_date=transaction.date,
            interest_capitalization_day=1,
            status=CreditStatus.active,
            scope=CreditScope.personal,
            account_id=transaction.account_id,
            converted_from_credit_card_payment=True,
            linked_transaction_id=transaction.id,
            user_id=user.id,
        )
        db.session.add(credit)
        db.session.flush()

        # Reduce the credit card balance (destination account) by converted amount
        if transaction.destination_account_id:
            dest_account = transaction.destination_account
            if dest_account:
                dest_account.balance = dest_account.balance + transaction.amount

        # Audit log (Req 22.1)
        self._audit_service.log_change(
            action="create",
            model="Credit",
            record_id=credit.id,
            old_values=None,
            new_values={
                "name": credit.name,
                "principal": str(credit.principal),
                "converted_from_credit_card_payment": True,
                "linked_transaction_id": transaction.id,
            },
            user_id=user.id,
        )

        db.session.commit()
        return credit

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _estimate_monthly_payment(self, credit: Credit) -> Decimal:
        """Estimate the average monthly payment from payment history.

        Uses the average of all recorded payments for this credit.
        If no payments exist, returns Decimal("0").

        Args:
            credit: The credit to estimate payments for.

        Returns:
            Estimated monthly payment amount.
        """
        payments = CreditPayment.query.filter_by(credit_id=credit.id).all()
        if not payments:
            return Decimal("0")

        total = sum(p.total_amount for p in payments)
        # Simple average — could be improved with date-range analysis
        avg_payment = total / len(payments)
        return avg_payment.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
