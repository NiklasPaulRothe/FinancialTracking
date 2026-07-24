"""Accounts blueprint for Haushaltsbuch.

Provides index, create, edit, and delete routes for account management.
Delegates all business logic to AccountService.

Validates: Requirements 2.1, 2.2, 2.9
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.models.account import AccountType, AccountScope
from app.services.account_service import AccountService
from app.blueprints.accounts.forms import AccountCreateForm, AccountEditForm, CreditCardCreateForm

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
    from flask import session

    # Handle view toggle
    requested_view = request.args.get("view")
    if requested_view in ("personal", "shared"):
        session["accounts_view"] = requested_view
        return redirect(url_for("accounts.index"))

    view_mode = session.get("accounts_view", "personal")

    accounts = account_service.get_accounts_for_user(current_user)

    # Compute available balances for all accounts
    from app.services.balance_service import BalanceService
    balance_service = BalanceService()
    available_balances = {}
    for a in accounts:
        try:
            available_balances[a.id] = balance_service.get_available_balance(a.id)
        except Exception:
            available_balances[a.id] = a.balance

    # Filter by current view
    scope_filter = AccountScope.personal if view_mode == "personal" else AccountScope.shared

    spending = [a for a in accounts if a.scope == scope_filter and a.type == AccountType.spending]
    saving = [a for a in accounts if a.scope == scope_filter and a.type == AccountType.saving]
    reserve = [a for a in accounts if a.scope == scope_filter and a.type == AccountType.reserve]
    credit_cards = [a for a in accounts if a.type == AccountType.credit_card and a.scope == scope_filter]

    return render_template(
        "accounts/index.html",
        view_mode=view_mode,
        spending=spending,
        saving=saving,
        reserve=reserve,
        credit_cards=credit_cards,
        available_balances=available_balances,
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
        if form.starting_balance.data is not None:
            kwargs["starting_balance"] = form.starting_balance.data
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


@accounts_bp.route("/create-credit-card", methods=["GET", "POST"])
@login_required
def create_credit_card():
    """Create a new credit card account with simplified form."""
    form = CreditCardCreateForm()

    if form.validate_on_submit():
        kwargs = {
            "credit_limit": form.credit_limit.data,
            "visible_to_partner": True,
        }
        if form.institute.data:
            kwargs["institute"] = form.institute.data
        if form.starting_balance.data is not None:
            kwargs["starting_balance"] = form.starting_balance.data
        if form.statement_closing_day.data:
            kwargs["statement_closing_day"] = form.statement_closing_day.data
        if form.payment_due_day.data:
            kwargs["payment_due_day"] = form.payment_due_day.data

        account_service.create_account(
            user=current_user,
            name=form.name.data,
            type=AccountType.credit_card,
            scope=AccountScope(form.scope.data),
            **kwargs,
        )
        flash("Kreditkarte erfolgreich erstellt.", "success")
        return redirect(url_for("accounts.index"))

    return render_template("accounts/create_credit_card.html", form=form)


@accounts_bp.route("/detail/<int:id>")
@login_required
def detail(id):
    """Display account details with transaction history."""
    from app.extensions import db
    from app.models.account import Account
    from app.models.transaction import Transaction
    from app.services.balance_service import BalanceService
    from decimal import Decimal

    account = db.session.get(Account, id)
    if account is None:
        flash("Konto nicht gefunden.", "danger")
        return redirect(url_for("accounts.index"))

    # Get all transactions for this account (as source or destination)
    transactions = (
        Transaction.query
        .filter(
            (Transaction.account_id == id) |
            (Transaction.destination_account_id == id)
        )
        .order_by(Transaction.date.desc(), Transaction.created_at.desc())
        .all()
    )

    # For credit cards: separate open (unpaid) and paid transactions
    open_cc_transactions = []
    if account.type == AccountType.credit_card:
        open_cc_transactions = (
            Transaction.query
            .filter(
                Transaction.account_id == id,
                Transaction.paid == False,  # noqa: E712
            )
            .order_by(Transaction.due_date.asc())
            .all()
        )

    # Compute blocked amount breakdown with individual items
    blocked_sections = []
    total_blocked = Decimal("0.00")
    from app.services.balance_service import BalanceService
    from app.models.transaction import RecurringRule, TransactionType, RecurringFrequency
    from app.models.planned_expense import PlannedExpense
    from app.models.budget import SavingContribution
    from app.models.user import User
    from datetime import date

    balance_service = BalanceService()

    if account.type != AccountType.credit_card:
        owner = db.session.get(User, account.owner_id)
        today = date.today()

        try:
            next_income = balance_service.get_next_income_date(owner)

            # Section 1: Recurring expenses AND transfers due in current cycle
            due_rules = (
                RecurringRule.query.filter(
                    RecurringRule.account_id == account.id,
                    RecurringRule.active == True,  # noqa: E712
                    RecurringRule.type.in_([TransactionType.expense, TransactionType.transfer]),
                    RecurringRule.next_due_date >= today,
                    RecurringRule.next_due_date <= next_income,
                ).all()
            )
            if due_rules:
                items = [{"name": r.name, "amount": r.amount, "date": r.next_due_date.strftime("%d.%m.%Y")} for r in due_rules]
                section_total = sum(r.amount for r in due_rules)
                blocked_sections.append({"title": "Daueraufträge (fällig bis nächstes Einkommen)", "items": items, "total": section_total})
                total_blocked += section_total

            # Section 2: Non-monthly recurring reserves (expenses AND transfers)
            reserve_rules = (
                RecurringRule.query.filter(
                    RecurringRule.account_id == account.id,
                    RecurringRule.active == True,  # noqa: E712
                    RecurringRule.type.in_([TransactionType.expense, TransactionType.transfer]),
                    RecurringRule.next_due_date > next_income,
                ).all()
            )
            reserve_items = []
            reserve_total = Decimal("0.00")
            for rule in reserve_rules:
                if rule.frequency == RecurringFrequency.monthly and rule.interval <= 1:
                    continue
                if rule.frequency == RecurringFrequency.daily or rule.frequency == RecurringFrequency.weekly:
                    continue
                if rule.frequency == RecurringFrequency.monthly:
                    total_cycles = rule.interval
                elif rule.frequency == RecurringFrequency.quarterly:
                    total_cycles = 3 * rule.interval
                elif rule.frequency == RecurringFrequency.yearly:
                    total_cycles = 12 * rule.interval
                else:
                    continue
                monthly_reserve = rule.amount / Decimal(str(total_cycles))
                months_remaining = max(0, (rule.next_due_date.year - today.year) * 12 + rule.next_due_date.month - today.month)
                cycles_passed = max(1, total_cycles - months_remaining)
                cycles_passed = min(cycles_passed, total_cycles - 1) if total_cycles > 1 else 1
                reserved = (monthly_reserve * Decimal(str(cycles_passed))).quantize(Decimal("0.01"))
                if reserved > 0:
                    reserve_items.append({"name": rule.name, "amount": reserved, "date": rule.next_due_date.strftime("%d.%m.%Y")})
                    reserve_total += reserved
            if reserve_items:
                blocked_sections.append({"title": "Rückstellungen (nicht-monatliche Daueraufträge)", "items": reserve_items, "total": reserve_total})
                total_blocked += reserve_total

            # Section 3: Blocking planned expenses
            planned = PlannedExpense.query.filter_by(
                account_id=account.id, blocking=True, resolved=False
            ).all()
            planned_items = [{"name": p.name, "amount": p.blocking_amount, "date": ""} for p in planned if p.blocking_amount > 0]
            if planned_items:
                section_total = sum(Decimal(str(i["amount"])) for i in planned_items)
                blocked_sections.append({"title": "Geplante Ausgaben (blockierend)", "items": planned_items, "total": section_total})
                total_blocked += section_total

            # Section 4: Saving contributions
            contributions = SavingContribution.query.filter_by(account_id=account.id).all()
            if contributions:
                contrib_items = [{"name": f"Sparziel: {c.saving_goal.name}", "amount": c.amount, "date": ""} for c in contributions]
                section_total = sum(c.amount for c in contributions)
                blocked_sections.append({"title": "Sparbeiträge", "items": contrib_items, "total": section_total})
                total_blocked += section_total

            # Section 5: Future transactions (not yet applied to balance)
            from app.models.transaction import Transaction
            future_txns = Transaction.query.filter(
                Transaction.account_id == account.id,
                Transaction.date > today,
                Transaction.type.in_([TransactionType.expense, TransactionType.transfer]),
            ).all()
            if future_txns:
                future_items = [{"name": t.description or f"Transaktion {t.date.strftime('%d.%m.%Y')}", "amount": t.amount, "date": t.date.strftime("%d.%m.%Y")} for t in future_txns]
                section_total = sum(t.amount for t in future_txns)
                blocked_sections.append({"title": "Zukünftige Transaktionen", "items": future_items, "total": section_total})
                total_blocked += section_total
        except Exception:
            pass

    # Compute available balance
    available_balance = account.balance
    if account.type != AccountType.credit_card:
        try:
            available_balance = balance_service.get_available_balance(account.id)
        except Exception:
            pass
    else:
        credit_limit = account.credit_limit or Decimal("0.0")
        available_balance = credit_limit + account.balance

    return render_template(
        "accounts/detail.html",
        account=account,
        transactions=transactions,
        open_cc_transactions=open_cc_transactions,
        blocked_sections=blocked_sections,
        total_blocked=total_blocked,
        available_balance=available_balance,
    )


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

    # Pre-populate enum fields with their string values for SelectField matching
    if not form.is_submitted():
        form.type.data = account.type.value
        form.scope.data = account.scope.value

    if form.validate_on_submit():
        updates = {
            "name": form.name.data,
            "type": AccountType(form.type.data),
            "scope": AccountScope(form.scope.data),
            "institute": form.institute.data or None,
            "visible_to_partner": form.visible_to_partner.data,
            "starting_balance": form.starting_balance.data,
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


@accounts_bp.route("/cc-extend/<int:txn_id>", methods=["POST"])
@login_required
def cc_extend(txn_id):
    """Extend the due date of a credit card transaction."""
    from app.extensions import db
    from app.models.transaction import Transaction
    from datetime import timedelta

    txn = db.session.get(Transaction, txn_id)
    if txn is None or txn.user_id != current_user.id:
        flash("Transaktion nicht gefunden.", "danger")
        return redirect(url_for("accounts.index"))

    days = request.form.get("extend_days", type=int)
    if not days or days < 1:
        flash("Bitte eine gültige Anzahl Tage angeben.", "danger")
        return redirect(url_for("accounts.detail", id=txn.account_id))

    if txn.due_date:
        txn.due_date = txn.due_date + timedelta(days=days)
    else:
        txn.due_date = txn.date + timedelta(days=30 + days)

    db.session.commit()
    flash(f"Fälligkeitsdatum um {days} Tage verlängert.", "success")
    return redirect(url_for("accounts.detail", id=txn.account_id))


@accounts_bp.route("/cc-pay/<int:txn_id>", methods=["POST"])
@login_required
def cc_pay(txn_id):
    """Mark a credit card transaction as paid."""
    from app.extensions import db
    from app.models.transaction import Transaction

    txn = db.session.get(Transaction, txn_id)
    if txn is None or txn.user_id != current_user.id:
        flash("Transaktion nicht gefunden.", "danger")
        return redirect(url_for("accounts.index"))

    txn.paid = True
    db.session.commit()
    flash("Zahlung als beglichen markiert.", "success")
    return redirect(url_for("accounts.detail", id=txn.account_id))


@accounts_bp.route("/cc-to-credit/<int:txn_id>", methods=["POST"])
@login_required
def cc_to_credit(txn_id):
    """Convert a credit card transaction to a mini-credit."""
    from app.extensions import db
    from app.models.transaction import Transaction
    from app.models.credit import Credit, CreditStatus, CreditScope
    from decimal import Decimal

    txn = db.session.get(Transaction, txn_id)
    if txn is None or txn.user_id != current_user.id:
        flash("Transaktion nicht gefunden.", "danger")
        return redirect(url_for("accounts.index"))

    # Create a credit from this transaction
    credit = Credit(
        name=f"Kreditkarte: {txn.description or txn.date.strftime('%d.%m.%Y')}",
        principal=txn.amount,
        remaining_balance=txn.amount,
        accrued_interest=Decimal("0.000000"),
        effective_yearly_rate=Decimal("0.000000"),  # User can set later
        disbursement_date=txn.date,
        interest_capitalization_day=1,
        status=CreditStatus.active,
        scope=CreditScope(txn.scope.value),
        account_id=txn.account_id,
        converted_from_credit_card_payment=True,
        linked_transaction_id=txn.id,
        user_id=current_user.id,
    )
    db.session.add(credit)

    # Mark original transaction as paid (debt moved to credit)
    txn.paid = True
    db.session.commit()

    flash(f"Transaktion in Kredit umgewandelt: {credit.name}", "success")
    return redirect(url_for("credits.detail", id=credit.id))
