"""Settings blueprint for Haushaltsbuch.

Provides index (user preferences) and change_password routes.
Implements income_day update with cascading recalculations,
date_format selection, tax rate configuration, and password change.

All routes require @login_required.

Validates: Requirements 25.1, 25.2, 25.3, 25.4, 25.5, 25.6, 25.7
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.extensions import db
from app.blueprints.settings.forms import SettingsForm, ChangePasswordForm
from app.services.balance_service import BalanceService
from app.services.budget_service import BudgetService

settings_bp = Blueprint(
    "settings", __name__, url_prefix="/settings", template_folder="templates"
)

balance_service = BalanceService()
budget_service = BudgetService()


@settings_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    """Display and update user preference settings.

    Implements:
    - income_day update with cascading recalculations (Req 25.1)
    - date_format selection (Req 25.3)
    - marginal_tax_rate / social_security_rate configuration (Req 25.7)
    - assumed_annual_return and target_retirement_age
    - German locale number formatting (Req 25.4)
    """
    form = SettingsForm(obj=current_user)

    if form.validate_on_submit():
        income_day_changed = current_user.income_day != form.income_day.data

        # Update user preferences
        current_user.income_day = form.income_day.data
        current_user.date_format = form.date_format.data
        current_user.marginal_tax_rate = form.marginal_tax_rate.data
        current_user.social_security_rate = form.social_security_rate.data
        current_user.assumed_annual_return = form.assumed_annual_return.data
        current_user.target_retirement_age = form.target_retirement_age.data

        db.session.commit()

        # Cascading recalculations when income_day changes
        if income_day_changed:
            _recalculate_on_income_day_change(current_user)

        flash("Einstellungen erfolgreich gespeichert.", "success")
        return redirect(url_for("settings.index"))

    return render_template("settings/index.html", form=form)


@settings_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    """Change the authenticated user's password.

    Validates: Requirements 25.5, 25.6
    - Verifies current password before allowing change.
    - New password must be at least 8 characters.
    """
    form = ChangePasswordForm()

    if form.validate_on_submit():
        # Verify current password
        if not current_user.check_password(form.current_password.data):
            flash("Das aktuelle Passwort ist falsch.", "danger")
            return render_template("settings/change_password.html", form=form)

        # Update password
        current_user.set_password(form.new_password.data)
        db.session.commit()

        flash("Passwort erfolgreich geändert.", "success")
        return redirect(url_for("settings.index"))

    return render_template("settings/change_password.html", form=form)


def _recalculate_on_income_day_change(user):
    """Trigger cascading recalculations when income_day changes.

    Recalculates:
    - Available balances for all active accounts (Req 25.1)
    - Budget period boundaries for all active budgets (Req 7.4)

    Args:
        user: The User whose income_day was changed.
    """
    from app.models.account import Account

    # Recalculate available balances for all user's active accounts
    active_accounts = Account.query.filter_by(
        owner_id=user.id, active=True
    ).all()

    for account in active_accounts:
        try:
            balance_service.recalculate_account_balance(account.id)
        except Exception:
            # Log but don't fail on individual account recalculation
            pass

    # Budget period boundaries are computed dynamically based on income_day,
    # so they automatically reflect the new value on next access.
    # However, we trigger threshold checks for active budgets to ensure
    # notifications are up-to-date with new boundaries.
    from app.models.budget import Budget

    active_budgets = Budget.query.filter_by(user_id=user.id).all()
    for budget in active_budgets:
        try:
            budget_service.check_thresholds(budget, user)
        except Exception:
            # Log but don't fail on individual budget check
            pass

    db.session.commit()
