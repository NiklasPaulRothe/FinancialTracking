"""Credits blueprint for Haushaltsbuch.

Provides index, create, detail, and repay routes for credit/loan management.

Validates: Requirements 11.1, 11.4, 11.8
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.extensions import db
from app.models.account import Account
from app.models.credit import Credit, CreditScope, CreditStatus, CreditRepaymentSchedule
from app.services.credit_service import CreditService
from app.blueprints.credits.forms import CreditCreateForm, CreditRepayForm, CreditEditForm

credits_bp = Blueprint(
    "credits",
    __name__,
    url_prefix="/credits",
    template_folder="templates",
)

_service = CreditService()


def _get_user_accounts():
    """Get active accounts for the current user."""
    return Account.query.filter_by(owner_id=current_user.id, active=True).all()


@credits_bp.route("/")
@login_required
def index():
    """Display all credits for the current user.

    Validates: Requirement 11.1
    Shows credits grouped by status with remaining balance and accrued interest.
    """
    credits = _service.get_for_user(current_user.id)
    active_credits = [c for c in credits if c.status == CreditStatus.active]
    paid_off_credits = [c for c in credits if c.status == CreditStatus.paid_off]
    accounts = _get_user_accounts()

    return render_template(
        "credits/index.html",
        active_credits=active_credits,
        paid_off_credits=paid_off_credits,
        accounts=accounts,
    )


@credits_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    """Create a new credit/loan.

    Validates: Requirement 11.1
    """
    accounts = _get_user_accounts()
    form = CreditCreateForm(accounts=accounts)

    if form.validate_on_submit():
        try:
            _service.create(
                name=form.name.data,
                principal=form.principal.data,
                effective_yearly_rate=form.effective_yearly_rate.data,
                disbursement_date=form.disbursement_date.data,
                interest_capitalization_day=form.interest_capitalization_day.data,
                account_id=form.account_id.data,
                scope=CreditScope(form.scope.data),
                user_id=current_user.id,
            )
            flash("Kredit erfolgreich erstellt.", "success")
            return redirect(url_for("credits.index"))
        except ValueError as e:
            flash(str(e), "danger")

    return render_template("credits/create.html", form=form)


@credits_bp.route("/detail/<int:id>")
@login_required
def detail(id):
    """Show credit details with payment history and forecast chart.

    Validates: Requirements 11.4, 11.8
    """
    credit = _service.get_by_id(id)
    if credit is None or credit.user_id != current_user.id:
        flash("Kredit nicht gefunden.", "danger")
        return redirect(url_for("credits.index"))

    forecast = _service.get_forecast(credit)
    repay_form = CreditRepayForm()

    return render_template(
        "credits/detail.html",
        credit=credit,
        forecast=forecast,
        repay_form=repay_form,
    )


@credits_bp.route("/repay/<int:id>", methods=["GET", "POST"])
@login_required
def repay(id):
    """Record a repayment for a credit.

    Validates: Requirements 11.4, 11.5
    Creates a transaction and applies payment to interest then principal.
    """
    credit = _service.get_by_id(id)
    if credit is None or credit.user_id != current_user.id:
        flash("Kredit nicht gefunden.", "danger")
        return redirect(url_for("credits.index"))

    if credit.status == CreditStatus.paid_off:
        flash("Kredit ist bereits vollständig getilgt.", "warning")
        return redirect(url_for("credits.detail", id=id))

    form = CreditRepayForm()

    if form.validate_on_submit():
        try:
            # Create a transaction for the manual repayment
            from app.services.transaction_service import TransactionService
            from app.models.transaction import TransactionScope, TransactionType
            from datetime import date

            txn_service = TransactionService()
            txn = txn_service.create_transaction(
                data={
                    "type": TransactionType.expense,
                    "amount": form.amount.data,
                    "date": date.today(),
                    "account_id": credit.account_id,
                    "scope": TransactionScope(credit.scope.value),
                    "description": f"Kreditrückzahlung: {credit.name}",
                },
                user=current_user,
            )

            # Accrue interest then apply repayment
            _service.accrue_interest_to_date(credit)
            _service.apply_repayment(
                credit=credit,
                amount=form.amount.data,
                transaction=txn,
            )
            flash("Rückzahlung erfolgreich gebucht.", "success")
            return redirect(url_for("credits.detail", id=id))
        except ValueError as e:
            flash(str(e), "danger")

    return render_template("credits/repay.html", credit=credit, form=form)


@credits_bp.route("/correct-balance/<int:id>", methods=["POST"])
@login_required
def correct_balance(id):
    """Manually correct the remaining balance and accrued interest of a credit."""
    from decimal import Decimal

    credit = _service.get_by_id(id)
    if credit is None or credit.user_id != current_user.id:
        flash("Kredit nicht gefunden.", "danger")
        return redirect(url_for("credits.index"))

    new_balance = request.form.get("new_balance", type=float)
    new_interest = request.form.get("new_interest", type=float)

    if new_balance is not None:
        credit.remaining_balance = Decimal(str(new_balance))
    if new_interest is not None:
        credit.accrued_interest = Decimal(str(new_interest))

    db.session.commit()

    # Recalculate forecast
    _service.generate_forecast(credit)

    flash("Kreditbetrag korrigiert.", "success")
    return redirect(url_for("credits.detail", id=id))


@credits_bp.route("/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit(id):
    """Edit credit details."""
    from app.models.credit import CreditScope

    credit = _service.get_by_id(id)
    if credit is None or credit.user_id != current_user.id:
        flash("Kredit nicht gefunden.", "danger")
        return redirect(url_for("credits.index"))

    accounts = _get_user_accounts()
    form = CreditEditForm(accounts=accounts, obj=credit)

    # Pre-populate enum fields on GET
    if not form.is_submitted():
        form.scope.data = credit.scope.value
        form.account_id.data = credit.account_id

    if form.validate_on_submit():
        credit.name = form.name.data
        credit.remaining_balance = form.remaining_balance.data
        credit.effective_yearly_rate = form.effective_yearly_rate.data
        credit.interest_capitalization_day = form.interest_capitalization_day.data
        credit.account_id = form.account_id.data
        credit.scope = CreditScope(form.scope.data)
        db.session.commit()
        flash("Kredit erfolgreich aktualisiert.", "success")
        return redirect(url_for("credits.detail", id=id))

    return render_template("credits/edit.html", form=form, credit=credit)


@credits_bp.route("/setup-recurring/<int:id>", methods=["POST"])
@login_required
def setup_recurring(id):
    """Set up a monthly recurring payment for a credit."""
    from datetime import date
    from decimal import Decimal
    from app.models.transaction import (
        RecurringRule,
        RecurringFrequency,
        TransactionType,
        TransactionScope,
    )

    credit = _service.get_by_id(id)
    if credit is None or credit.user_id != current_user.id:
        flash("Kredit nicht gefunden.", "danger")
        return redirect(url_for("credits.index"))

    payment_amount = request.form.get("payment_amount", type=float)
    account_id = request.form.get("account_id", type=int)
    day_of_month = request.form.get("day_of_month", type=int)

    if not payment_amount or payment_amount <= 0:
        flash("Bitte einen gültigen Betrag eingeben.", "danger")
        return redirect(url_for("credits.index"))

    if not account_id:
        flash("Bitte ein Konto auswählen.", "danger")
        return redirect(url_for("credits.index"))

    if not day_of_month or day_of_month < 1 or day_of_month > 28:
        flash("Tag muss zwischen 1 und 28 liegen.", "danger")
        return redirect(url_for("credits.index"))

    # Calculate next due date
    today = date.today()
    if today.day >= day_of_month:
        # Next month
        if today.month == 12:
            next_due = date(today.year + 1, 1, day_of_month)
        else:
            next_due = date(today.year, today.month + 1, day_of_month)
    else:
        next_due = date(today.year, today.month, day_of_month)

    # Create recurring rule
    rule = RecurringRule(
        name=f"Kreditrate: {credit.name}",
        type=TransactionType.expense,
        frequency=RecurringFrequency.monthly,
        interval=1,
        amount=Decimal(str(payment_amount)),
        next_due_date=next_due,
        active=True,
        scope=TransactionScope(credit.scope.value),
        account_id=account_id,
        user_id=current_user.id,
    )
    db.session.add(rule)
    db.session.flush()

    # Create repayment schedule link
    schedule = CreditRepaymentSchedule(
        credit_id=credit.id,
        recurring_rule_id=rule.id,
        payment_amount=Decimal(str(payment_amount)),
    )
    db.session.add(schedule)
    db.session.commit()

    flash(f"Monatliche Rate von {payment_amount:.2f} € eingerichtet.", "success")
    return redirect(url_for("credits.index"))
