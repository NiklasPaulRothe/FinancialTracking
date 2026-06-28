"""Transactions blueprint for Haushaltsbuch.

Provides index, create, edit, and delete routes for transaction management.
Delegates all business logic to TransactionService.

Validates: Requirements 3.1, 3.5, 4.1
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction, TransactionScope, TransactionType
from app.services.transaction_service import TransactionService
from app.blueprints.transactions.forms import TransactionCreateForm, TransactionEditForm

transactions_bp = Blueprint(
    "transactions", __name__, url_prefix="/transactions", template_folder="templates"
)

transaction_service = TransactionService()


def _get_user_accounts():
    """Get active accounts for the current user."""
    return Account.query.filter_by(owner_id=current_user.id, active=True).all()


def _get_user_categories():
    """Get categories for the current user."""
    return Category.query.filter_by(user_id=current_user.id).all()


@transactions_bp.route("/")
@login_required
def index():
    """Display transactions with optional filters.

    Validates: Requirement 3.1
    Supports filtering by type, date range, and account.
    """
    # Get filter parameters
    filter_type = request.args.get("type", "")
    filter_date_from = request.args.get("date_from", "")
    filter_date_to = request.args.get("date_to", "")
    filter_account_id = request.args.get("account_id", "", type=str)

    # Base query: user's transactions ordered by date descending
    query = Transaction.query.filter_by(user_id=current_user.id).order_by(
        Transaction.date.desc(), Transaction.id.desc()
    )

    # Apply filters
    if filter_type:
        try:
            query = query.filter(Transaction.type == TransactionType(filter_type))
        except ValueError:
            pass

    if filter_date_from:
        from datetime import date as date_type

        try:
            parsed = date_type.fromisoformat(filter_date_from)
            query = query.filter(Transaction.date >= parsed)
        except ValueError:
            pass

    if filter_date_to:
        from datetime import date as date_type

        try:
            parsed = date_type.fromisoformat(filter_date_to)
            query = query.filter(Transaction.date <= parsed)
        except ValueError:
            pass

    if filter_account_id:
        try:
            acct_id = int(filter_account_id)
            query = query.filter(
                (Transaction.account_id == acct_id)
                | (Transaction.destination_account_id == acct_id)
            )
        except (ValueError, TypeError):
            pass

    transactions = query.all()
    accounts = _get_user_accounts()

    return render_template(
        "transactions/index.html",
        transactions=transactions,
        accounts=accounts,
        filter_type=filter_type,
        filter_date_from=filter_date_from,
        filter_date_to=filter_date_to,
        filter_account_id=filter_account_id,
    )


@transactions_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    """Create a new transaction.

    Validates: Requirements 3.1, 3.5
    """
    accounts = _get_user_accounts()
    categories = _get_user_categories()
    form = TransactionCreateForm(accounts=accounts, categories=categories)

    if form.validate_on_submit():
        data = {
            "type": form.type.data,
            "amount": form.amount.data,
            "date": form.date.data,
            "account_id": form.account_id.data,
            "scope": TransactionScope(form.scope.data),
            "description": form.description.data or None,
        }
        if form.destination_account_id.data:
            data["destination_account_id"] = form.destination_account_id.data
        if form.category_id.data:
            data["category_id"] = form.category_id.data

        try:
            transaction_service.create_transaction(data, current_user)
            flash("Transaktion erfolgreich erstellt.", "success")
            return redirect(url_for("transactions.index"))
        except ValueError as e:
            flash(str(e), "danger")
        except Exception as e:
            flash(f"Fehler beim Erstellen: {e}", "danger")

    return render_template("transactions/create.html", form=form)


@transactions_bp.route("/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit(id):
    """Edit an existing transaction.

    Validates: Requirement 3.11
    """
    from app.extensions import db

    transaction = db.session.get(Transaction, id)
    if transaction is None or transaction.user_id != current_user.id:
        flash("Transaktion nicht gefunden.", "danger")
        return redirect(url_for("transactions.index"))

    accounts = _get_user_accounts()
    categories = _get_user_categories()

    # Pre-populate the form with existing transaction data
    if request.method == "GET":
        form = TransactionEditForm(
            accounts=accounts,
            categories=categories,
            data={
                "type": transaction.type.value,
                "amount": transaction.amount,
                "date": transaction.date,
                "account_id": transaction.account_id or 0,
                "destination_account_id": transaction.destination_account_id or 0,
                "scope": transaction.scope.value if transaction.scope else TransactionScope.personal.value,
                "category_id": transaction.category_id or 0,
                "description": transaction.description or "",
            },
        )
    else:
        form = TransactionEditForm(accounts=accounts, categories=categories)

    if form.validate_on_submit():
        data = {
            "type": form.type.data,
            "amount": form.amount.data,
            "date": form.date.data,
            "account_id": form.account_id.data,
            "scope": TransactionScope(form.scope.data),
            "description": form.description.data or None,
        }
        if form.destination_account_id.data:
            data["destination_account_id"] = form.destination_account_id.data
        else:
            data["destination_account_id"] = None
        if form.category_id.data:
            data["category_id"] = form.category_id.data
        else:
            data["category_id"] = None

        try:
            transaction_service.update_transaction(id, data, current_user)
            flash("Transaktion erfolgreich aktualisiert.", "success")
            return redirect(url_for("transactions.index"))
        except ValueError as e:
            flash(str(e), "danger")
        except Exception as e:
            flash(f"Fehler beim Aktualisieren: {e}", "danger")

    return render_template(
        "transactions/edit.html", form=form, transaction=transaction
    )


@transactions_bp.route("/delete/<int:id>", methods=["POST"])
@login_required
def delete(id):
    """Delete a transaction after confirmation.

    Validates: Requirement 3.7
    Uses POST-only route for safety.
    """
    try:
        transaction_service.delete_transaction(id, current_user)
        flash("Transaktion erfolgreich gelöscht.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    except Exception as e:
        flash(f"Fehler beim Löschen: {e}", "danger")

    return redirect(url_for("transactions.index"))
