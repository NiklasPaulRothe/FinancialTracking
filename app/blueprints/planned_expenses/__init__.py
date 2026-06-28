"""Planned Expenses blueprint for Haushaltsbuch.

Provides index, create, edit, and delete routes for planned expense management.
Delegates business logic to PlannedExpenseService.

Validates: Requirements 9.1, 9.5, 9.6
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.extensions import db
from app.models.account import Account
from app.models.planned_expense import PlannedExpense, PlannedExpenseScope
from app.services.planned_expense_service import PlannedExpenseService
from app.blueprints.planned_expenses.forms import (
    PlannedExpenseCreateForm,
    PlannedExpenseEditForm,
)

planned_expenses_bp = Blueprint(
    "planned_expenses",
    __name__,
    url_prefix="/planned-expenses",
    template_folder="templates",
)

_service = PlannedExpenseService()


def _get_user_accounts():
    """Get active accounts for the current user."""
    return Account.query.filter_by(owner_id=current_user.id, active=True).all()


@planned_expenses_bp.route("/")
@login_required
def index():
    """Display all planned expenses for the current user.

    Validates: Requirement 9.1
    Shows planned expenses grouped by unresolved and resolved status.
    """
    expenses = _service.get_for_user(current_user.id)
    unresolved = [e for e in expenses if not e.resolved]
    resolved = [e for e in expenses if e.resolved]

    return render_template(
        "planned_expenses/index.html",
        unresolved=unresolved,
        resolved=resolved,
    )


@planned_expenses_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    """Create a new planned expense.

    Validates: Requirements 9.1, 9.6
    """
    accounts = _get_user_accounts()
    form = PlannedExpenseCreateForm(accounts=accounts)

    if form.validate_on_submit():
        _service.create(
            name=form.name.data,
            scope=PlannedExpenseScope(form.scope.data),
            user_id=current_user.id,
            amount_exact=form.amount_exact.data or None,
            amount_min=form.amount_min.data or None,
            amount_max=form.amount_max.data or None,
            account_id=form.account_id.data or None,
            blocking=form.blocking.data,
        )
        flash("Geplante Ausgabe erfolgreich erstellt.", "success")
        return redirect(url_for("planned_expenses.index"))

    return render_template("planned_expenses/create.html", form=form)


@planned_expenses_bp.route("/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit(id):
    """Edit an existing planned expense.

    Validates: Requirement 9.5
    """
    expense = _service.get_by_id(id)
    if expense is None or expense.user_id != current_user.id:
        flash("Geplante Ausgabe nicht gefunden.", "danger")
        return redirect(url_for("planned_expenses.index"))

    accounts = _get_user_accounts()

    if request.method == "GET":
        form = PlannedExpenseEditForm(
            accounts=accounts,
            data={
                "name": expense.name,
                "amount_exact": expense.amount_exact,
                "amount_min": expense.amount_min,
                "amount_max": expense.amount_max,
                "scope": expense.scope.value,
                "account_id": expense.account_id or 0,
                "blocking": expense.blocking,
            },
        )
    else:
        form = PlannedExpenseEditForm(accounts=accounts)

    if form.validate_on_submit():
        _service.update(
            expense=expense,
            name=form.name.data,
            amount_exact=form.amount_exact.data or None,
            amount_min=form.amount_min.data or None,
            amount_max=form.amount_max.data or None,
            account_id=form.account_id.data or None,
            blocking=form.blocking.data,
        )
        flash("Geplante Ausgabe erfolgreich aktualisiert.", "success")
        return redirect(url_for("planned_expenses.index"))

    return render_template("planned_expenses/edit.html", form=form, expense=expense)


@planned_expenses_bp.route("/delete/<int:id>", methods=["POST"])
@login_required
def delete(id):
    """Delete a planned expense.

    Validates: Requirement 9.1
    """
    expense = _service.get_by_id(id)
    if expense is None or expense.user_id != current_user.id:
        flash("Geplante Ausgabe nicht gefunden.", "danger")
        return redirect(url_for("planned_expenses.index"))

    _service.delete(expense)
    flash("Geplante Ausgabe erfolgreich gelöscht.", "success")
    return redirect(url_for("planned_expenses.index"))
