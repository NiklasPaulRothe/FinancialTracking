"""Saving Goals blueprint for Haushaltsbuch.

Provides index, create, detail, add/remove contribution, complete, and cancel
routes for saving goal management.

Validates: Requirements 10.1, 10.2, 10.5, 10.6
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.extensions import db
from app.models.account import Account
from app.models.budget import SavingContribution, SavingGoal, SavingGoalScope, SavingGoalStatus
from app.services.saving_goal_service import SavingGoalService
from app.blueprints.saving_goals.forms import (
    SavingGoalCreateForm,
    SavingContributionForm,
)

saving_goals_bp = Blueprint(
    "saving_goals",
    __name__,
    url_prefix="/saving-goals",
    template_folder="templates",
)

_service = SavingGoalService()


def _get_user_accounts():
    """Get active accounts for the current user."""
    return Account.query.filter_by(owner_id=current_user.id, active=True).all()


@saving_goals_bp.route("/")
@login_required
def index():
    """Display all saving goals for the current user.

    Validates: Requirement 10.1
    Shows saving goals as progress cards grouped by status.
    """
    goals = _service.get_for_user(current_user.id)
    active_goals = [g for g in goals if g.status == SavingGoalStatus.active]
    completed_goals = [g for g in goals if g.status == SavingGoalStatus.completed]
    cancelled_goals = [g for g in goals if g.status == SavingGoalStatus.cancelled]
    accounts = _get_user_accounts()

    return render_template(
        "saving_goals/index.html",
        active_goals=active_goals,
        completed_goals=completed_goals,
        cancelled_goals=cancelled_goals,
        accounts=accounts,
    )


@saving_goals_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    """Create a new saving goal.

    Validates: Requirement 10.1
    """
    form = SavingGoalCreateForm()

    if form.validate_on_submit():
        _service.create(
            name=form.name.data,
            scope=SavingGoalScope(form.scope.data),
            user_id=current_user.id,
            target_amount=form.target_amount.data or None,
        )
        flash("Sparziel erfolgreich erstellt.", "success")
        return redirect(url_for("saving_goals.index"))

    return render_template("saving_goals/create.html", form=form)


@saving_goals_bp.route("/detail/<int:id>")
@login_required
def detail(id):
    """Show saving goal details with contributions.

    Validates: Requirements 10.3, 10.4
    """
    goal = _service.get_by_id(id)
    if goal is None or goal.user_id != current_user.id:
        flash("Sparziel nicht gefunden.", "danger")
        return redirect(url_for("saving_goals.index"))

    accounts = _get_user_accounts()
    contribution_form = SavingContributionForm(accounts=accounts)

    return render_template(
        "saving_goals/detail.html",
        goal=goal,
        contribution_form=contribution_form,
    )


@saving_goals_bp.route("/add_contribution/<int:id>", methods=["POST"])
@login_required
def add_contribution(id):
    """Add a contribution to a saving goal.

    Validates: Requirement 10.2
    """
    goal = _service.get_by_id(id)
    if goal is None or goal.user_id != current_user.id:
        flash("Sparziel nicht gefunden.", "danger")
        return redirect(url_for("saving_goals.index"))

    if goal.status != SavingGoalStatus.active:
        flash("Beiträge können nur zu aktiven Sparzielen hinzugefügt werden.", "warning")
        return redirect(url_for("saving_goals.detail", id=id))

    accounts = _get_user_accounts()
    form = SavingContributionForm(accounts=accounts)

    if form.validate_on_submit():
        _service.add_contribution(
            goal=goal,
            account_id=form.account_id.data,
            amount=form.amount.data,
        )
        flash("Beitrag erfolgreich hinzugefügt.", "success")
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{error}", "danger")

    return redirect(url_for("saving_goals.detail", id=id))


@saving_goals_bp.route("/remove_contribution/<int:id>", methods=["POST"])
@login_required
def remove_contribution(id):
    """Remove a contribution from a saving goal.

    Validates: Requirement 10.6
    """
    contribution = _service.get_contribution_by_id(id)
    if contribution is None:
        flash("Beitrag nicht gefunden.", "danger")
        return redirect(url_for("saving_goals.index"))

    goal = _service.get_by_id(contribution.saving_goal_id)
    if goal is None or goal.user_id != current_user.id:
        flash("Sparziel nicht gefunden.", "danger")
        return redirect(url_for("saving_goals.index"))

    goal_id = goal.id
    _service.remove_contribution(contribution)
    flash("Beitrag erfolgreich entfernt.", "success")
    return redirect(url_for("saving_goals.detail", id=goal_id))


@saving_goals_bp.route("/complete/<int:id>", methods=["POST"])
@login_required
def complete(id):
    """Mark a saving goal as completed.

    Validates: Requirement 10.5
    Releases all contribution amounts from account available_balance calculations.
    """
    goal = _service.get_by_id(id)
    if goal is None or goal.user_id != current_user.id:
        flash("Sparziel nicht gefunden.", "danger")
        return redirect(url_for("saving_goals.index"))

    if goal.status != SavingGoalStatus.active:
        flash("Nur aktive Sparziele können abgeschlossen werden.", "warning")
        return redirect(url_for("saving_goals.detail", id=id))

    _service.complete(goal)
    flash("Sparziel als abgeschlossen markiert. Beiträge wurden freigegeben.", "success")
    return redirect(url_for("saving_goals.index"))


@saving_goals_bp.route("/cancel/<int:id>", methods=["POST"])
@login_required
def cancel(id):
    """Cancel a saving goal.

    Validates: Requirement 10.5
    Releases all contribution amounts from account available_balance calculations.
    """
    goal = _service.get_by_id(id)
    if goal is None or goal.user_id != current_user.id:
        flash("Sparziel nicht gefunden.", "danger")
        return redirect(url_for("saving_goals.index"))

    if goal.status != SavingGoalStatus.active:
        flash("Nur aktive Sparziele können abgebrochen werden.", "warning")
        return redirect(url_for("saving_goals.detail", id=id))

    _service.cancel(goal)
    flash("Sparziel abgebrochen. Beiträge wurden freigegeben.", "success")
    return redirect(url_for("saving_goals.index"))
