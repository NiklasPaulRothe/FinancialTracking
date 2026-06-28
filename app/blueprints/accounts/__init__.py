"""Accounts blueprint for Haushaltsbuch.

Provides index, create, edit, and delete routes for account management.
Delegates all business logic to AccountService.

Validates: Requirements 2.1, 2.2, 2.9
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.models.account import AccountType, AccountScope
from app.services.account_service import AccountService
from app.blueprints.accounts.forms import AccountCreateForm, AccountEditForm

accounts_bp = Blueprint(
    "accounts", __name__, url_prefix="/accounts", template_folder="templates"
)

account_service = AccountService()


@accounts_bp.route("/")
@login_required
def index():
    """Display accounts grouped by type.

    Validates: Requirement 2.9
    Spending/saving accounts in one section, credit cards in a separate section.
    Each account shows its personal/shared scope label.
    """
    accounts = account_service.get_accounts_for_user(current_user)

    # Group accounts by type
    spending_saving = [
        a for a in accounts if a.type in (AccountType.spending, AccountType.saving)
    ]
    credit_cards = [a for a in accounts if a.type == AccountType.credit_card]

    return render_template(
        "accounts/index.html",
        spending_saving=spending_saving,
        credit_cards=credit_cards,
    )


@accounts_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    """Create a new account.

    Validates: Requirement 2.1
    """
    form = AccountCreateForm()
    if form.validate_on_submit():
        kwargs = {
            "visible_to_partner": form.visible_to_partner.data,
        }
        if form.institute.data:
            kwargs["institute"] = form.institute.data
        if form.max_overdraft.data is not None:
            kwargs["max_overdraft"] = form.max_overdraft.data
        if form.type.data == AccountType.credit_card.value:
            kwargs["credit_limit"] = form.credit_limit.data
            kwargs["statement_closing_day"] = form.statement_closing_day.data
            kwargs["payment_due_day"] = form.payment_due_day.data

        account_service.create_account(
            user=current_user,
            name=form.name.data,
            type=AccountType(form.type.data),
            scope=AccountScope(form.scope.data),
            **kwargs,
        )
        flash("Konto erfolgreich erstellt.", "success")
        return redirect(url_for("accounts.index"))

    return render_template("accounts/create.html", form=form)


@accounts_bp.route("/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit(id):
    """Edit an existing account.

    Validates: Requirement 2.2
    """
    # Fetch the account to pre-populate the form and determine type
    try:
        from app.extensions import db
        from app.models.account import Account

        account = db.session.get(Account, id)
        if account is None:
            flash("Konto nicht gefunden.", "danger")
            return redirect(url_for("accounts.index"))
    except Exception:
        flash("Konto nicht gefunden.", "danger")
        return redirect(url_for("accounts.index"))

    is_credit_card = account.type == AccountType.credit_card
    form = AccountEditForm(obj=account)

    if form.validate_on_submit():
        updates = {
            "name": form.name.data,
            "institute": form.institute.data or None,
            "visible_to_partner": form.visible_to_partner.data,
        }
        if is_credit_card:
            updates["credit_limit"] = form.credit_limit.data
            updates["statement_closing_day"] = form.statement_closing_day.data
            updates["payment_due_day"] = form.payment_due_day.data

        try:
            account_service.edit_account(id, current_user, **updates)
            flash("Konto erfolgreich aktualisiert.", "success")
            return redirect(url_for("accounts.index"))
        except ValueError as e:
            flash(str(e), "danger")

    return render_template(
        "accounts/edit.html",
        form=form,
        account=account,
        is_credit_card=is_credit_card,
    )


@accounts_bp.route("/delete/<int:id>", methods=["POST"])
@login_required
def delete(id):
    """Delete an account after dependency check.

    Validates: Requirements 2.6, 2.7
    """
    try:
        account_service.delete_account(id, current_user)
        flash("Konto erfolgreich gelöscht.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    except Exception as e:
        flash(f"Fehler beim Löschen: {e}", "danger")

    return redirect(url_for("accounts.index"))
