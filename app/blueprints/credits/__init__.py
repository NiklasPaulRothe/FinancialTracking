"""Credits blueprint for Haushaltsbuch.

Provides index, create, detail, and repay routes for credit/loan management.

Validates: Requirements 11.1, 11.4, 11.8
"""

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user

from app.models.account import Account
from app.models.credit import CreditScope, CreditStatus
from app.services.credit_service import CreditService
from app.blueprints.credits.forms import CreditCreateForm, CreditRepayForm

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

    return render_template(
        "credits/index.html",
        active_credits=active_credits,
        paid_off_credits=paid_off_credits,
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
            _service.apply_repayment(
                credit=credit,
                amount=form.amount.data,
                user_id=current_user.id,
            )
            flash("Rückzahlung erfolgreich gebucht.", "success")
            return redirect(url_for("credits.detail", id=id))
        except ValueError as e:
            flash(str(e), "danger")

    return render_template("credits/repay.html", credit=credit, form=form)
