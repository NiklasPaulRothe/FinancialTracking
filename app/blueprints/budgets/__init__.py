"""Budgets blueprint for Haushaltsbuch.

Provides index, create, edit, and delete routes for budget management.
Delegates all business logic to BudgetService.

Validates: Requirements 6.1, 6.7
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.models.budget import BudgetPeriod, BudgetScope
from app.models.category import Category
from app.services.budget_service import BudgetService
from app.blueprints.budgets.forms import BudgetCreateForm, BudgetEditForm

budgets_bp = Blueprint(
    "budgets", __name__, url_prefix="/budgets", template_folder="templates"
)

budget_service = BudgetService()


@budgets_bp.route("/")
@login_required
def index():
    """Display budgets with utilisation percentage bars.

    Validates: Requirements 6.1, 6.7
    Shows all budgets visible to the user with color-coded progress bars
    indicating spending relative to budget amount.
    """
    budgets = budget_service.get_budgets_for_user(current_user)

    # Calculate utilisation details for each budget
    budget_details = []
    for budget in budgets:
        details = budget_service.get_utilisation_with_details(budget, current_user)
        budget_details.append({
            "budget": budget,
            **details,
        })

    return render_template(
        "budgets/index.html",
        budget_details=budget_details,
    )


@budgets_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    """Create a new budget.

    Validates: Requirements 6.1, 6.8
    """
    categories = Category.query.filter_by(user_id=current_user.id).order_by(Category.name).all()
    form = BudgetCreateForm(categories=categories)

    if form.validate_on_submit():
        try:
            budget_service.create_budget(
                user=current_user,
                name=form.name.data,
                scope=BudgetScope(form.scope.data),
                amount=form.amount.data,
                period=BudgetPeriod(form.period.data),
                start_date=form.start_date.data,
                category_id=form.category_id.data,
            )
            flash("Budget erfolgreich erstellt.", "success")
            return redirect(url_for("budgets.index"))
        except ValueError as e:
            flash(str(e), "danger")

    return render_template("budgets/create.html", form=form)


@budgets_bp.route("/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit(id):
    """Edit an existing budget.

    Validates: Requirement 6.7
    """
    from app.extensions import db
    from app.models.budget import Budget

    budget = db.session.get(Budget, id)
    if budget is None:
        flash("Budget nicht gefunden.", "danger")
        return redirect(url_for("budgets.index"))

    # Access check
    if budget.user_id != current_user.id and budget.scope != BudgetScope.shared:
        flash("Kein Zugriff auf dieses Budget.", "danger")
        return redirect(url_for("budgets.index"))

    categories = Category.query.filter_by(user_id=current_user.id).order_by(Category.name).all()
    form = BudgetEditForm(obj=budget, categories=categories)

    # Set category_id to 0 if None for the form display
    if request.method == "GET" and budget.category_id is None:
        form.category_id.data = 0

    # Set enum values for GET display
    if request.method == "GET":
        form.scope.data = budget.scope.value
        form.period.data = budget.period.value

    if form.validate_on_submit():
        try:
            budget_service.edit_budget(
                budget_id=id,
                user=current_user,
                name=form.name.data,
                scope=form.scope.data,
                category_id=form.category_id.data,
                amount=form.amount.data,
                period=form.period.data,
                start_date=form.start_date.data,
            )
            flash("Budget erfolgreich aktualisiert.", "success")
            return redirect(url_for("budgets.index"))
        except ValueError as e:
            flash(str(e), "danger")

    return render_template("budgets/edit.html", form=form, budget=budget)


@budgets_bp.route("/delete/<int:id>", methods=["POST"])
@login_required
def delete(id):
    """Delete a budget.

    Validates: Requirement 6.7
    """
    try:
        budget_service.delete_budget(id, current_user)
        flash("Budget erfolgreich gelöscht.", "success")
    except ValueError as e:
        flash(str(e), "danger")

    return redirect(url_for("budgets.index"))
