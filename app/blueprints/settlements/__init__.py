"""Settlements blueprint for Haushaltsbuch.

Provides index, create, and delete routes for shared expense settlement
between household members.

Validates: Requirements 12.1, 12.2
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.extensions import db
from app.models.transaction import Settlement, SharedExpenseShare, SharedExpense
from app.models.user import User
from app.services.settlement_service import SettlementService
from app.blueprints.settlements.forms import SettlementCreateForm

settlements_bp = Blueprint(
    "settlements",
    __name__,
    url_prefix="/settlements",
    template_folder="templates",
)

_service = SettlementService()


def _get_partner():
    """Get the partner user (the other user in the household)."""
    return User.query.filter(User.id != current_user.id).first()


def _get_outstanding_shared_expenses():
    """Get unsettled SharedExpenseShares for display."""
    return (
        SharedExpenseShare.query
        .join(SharedExpense, SharedExpenseShare.shared_expense_id == SharedExpense.id)
        .filter(SharedExpenseShare.settled == False)  # noqa: E712
        .order_by(SharedExpense.created_at.asc())
        .all()
    )


@settlements_bp.route("/")
@login_required
def index():
    """Display net balance, settlement history, and outstanding shared expenses.

    Validates: Requirement 12.1
    Shows the net settlement balance, a list of past settlements, and
    outstanding unsettled shared expense shares.
    """
    net_balance = _service.get_net_balance(current_user)
    partner = _get_partner()

    # Get all settlements involving current user (both directions)
    settlements = (
        Settlement.query
        .filter(
            db.or_(
                Settlement.from_user_id == current_user.id,
                Settlement.to_user_id == current_user.id,
            )
        )
        .order_by(Settlement.date.desc(), Settlement.created_at.desc())
        .all()
    )

    outstanding_shares = _get_outstanding_shared_expenses()

    return render_template(
        "settlements/index.html",
        net_balance=net_balance,
        partner=partner,
        settlements=settlements,
        outstanding_shares=outstanding_shares,
    )


@settlements_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    """Create a new settlement (from current user to partner).

    Validates: Requirement 12.2
    The from_user is always the current user; to_user is the partner.
    """
    partner = _get_partner()

    if partner is None:
        flash("Kein Partner im Haushalt gefunden.", "danger")
        return redirect(url_for("settlements.index"))

    form = SettlementCreateForm()

    if form.validate_on_submit():
        try:
            _service.create_settlement(
                from_user=current_user,
                to_user=partner,
                amount=form.amount.data,
                settlement_date=form.date.data,
            )
            flash("Ausgleich erfolgreich erstellt.", "success")
            return redirect(url_for("settlements.index"))
        except Exception as e:
            flash(str(e), "danger")

    return render_template(
        "settlements/create.html",
        form=form,
        partner=partner,
    )


@settlements_bp.route("/delete/<int:id>", methods=["POST"])
@login_required
def delete(id):
    """Delete a settlement and reverse all its allocations.

    Validates: Requirement 12.6
    POST-only route. Reverses allocations via SettlementService.
    """
    try:
        _service.delete_settlement(settlement_id=id, user=current_user)
        flash("Ausgleich erfolgreich gelöscht.", "success")
    except ValueError as e:
        flash(str(e), "danger")

    return redirect(url_for("settlements.index"))
