"""Recurring blueprint for Haushaltsbuch.

Provides index, create, edit, and toggle routes for recurring rule management.
Delegates all business logic to RecurringService (when available) or direct model access.

Validates: Requirements 5.1, 5.9, 5.10
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.extensions import db
from app.models.account import Account
from app.models.category import Category
from app.models.transaction import (
    RecurringFrequency,
    RecurringRule,
    Tag,
    TransactionScope,
    TransactionType,
)
from app.blueprints.recurring.forms import RecurringRuleCreateForm, RecurringRuleEditForm

recurring_bp = Blueprint(
    "recurring", __name__, url_prefix="/recurring", template_folder="templates"
)


def _get_user_accounts():
    """Get active accounts for the current user."""
    return Account.query.filter_by(owner_id=current_user.id, active=True).all()


def _get_user_categories():
    """Get categories for the current user."""
    return Category.query.filter_by(user_id=current_user.id).all()


def _get_user_saving_goals():
    """Get active saving goals for the current user."""
    from app.models.budget import SavingGoal, SavingGoalStatus
    return SavingGoal.query.filter_by(user_id=current_user.id, status=SavingGoalStatus.active).all()


def _apply_rule_tags(rule, tags_string, user_id):
    """Parse comma-separated tag names and link them to a recurring rule."""
    tag_names = [t.strip() for t in tags_string.split(",") if t.strip()]
    rule.tags = []
    for name in tag_names:
        name = name[:30]
        tag = Tag.query.filter_by(name=name, user_id=user_id).first()
        if not tag:
            tag = Tag(name=name, user_id=user_id)
            db.session.add(tag)
            db.session.flush()
        rule.tags.append(tag)


@recurring_bp.route("/")
@login_required
def index():
    """Display recurring rules grouped by active/inactive status.

    Validates: Requirement 5.9
    Shows all recurring rules with status, toggle button, and edit link.
    """
    rules = (
        RecurringRule.query.filter_by(user_id=current_user.id)
        .order_by(RecurringRule.active.desc(), RecurringRule.next_due_date.asc())
        .all()
    )

    active_rules = [r for r in rules if r.active]
    inactive_rules = [r for r in rules if not r.active]

    # Split active by scope
    active_personal = [r for r in active_rules if r.scope.value == "personal"]
    active_shared = [r for r in active_rules if r.scope.value == "shared"]

    # Find recurring transfers from personal to shared accounts (show as income in shared box)
    from app.models.account import Account, AccountScope
    incoming_shared_transfers = []
    for r in active_personal:
        if r.type == TransactionType.transfer and r.destination_account_id:
            dest = db.session.get(Account, r.destination_account_id)
            if dest and dest.scope == AccountScope.shared:
                incoming_shared_transfers.append(r)

    # Compute monthly equivalents for sum calculations
    def monthly_amount(rule):
        """Convert rule amount to monthly equivalent based on frequency and interval."""
        from decimal import Decimal
        amount = rule.amount
        freq = rule.frequency.value
        interval = rule.interval

        if freq == "daily":
            return amount * Decimal("30") / Decimal(str(interval))
        elif freq == "weekly":
            return amount * Decimal("4.33") / Decimal(str(interval))
        elif freq == "monthly":
            return amount / Decimal(str(interval))
        elif freq == "quarterly":
            return amount / (Decimal("3") * Decimal(str(interval)))
        elif freq == "yearly":
            return amount / (Decimal("12") * Decimal(str(interval)))
        return amount

    # Build dicts mapping rule id -> monthly amount
    monthly_amounts = {}
    for r in active_rules:
        monthly_amounts[r.id] = float(monthly_amount(r))
    for r in incoming_shared_transfers:
        if r.id not in monthly_amounts:
            monthly_amounts[r.id] = float(monthly_amount(r))

    return render_template(
        "recurring/index.html",
        active_personal=active_personal,
        active_shared=active_shared,
        incoming_shared_transfers=incoming_shared_transfers,
        inactive_rules=inactive_rules,
        monthly_amounts=monthly_amounts,
        TransactionType=TransactionType,
    )


@recurring_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    """Create a new recurring rule.

    Validates: Requirements 5.1, 5.10
    """
    accounts = _get_user_accounts()
    categories = _get_user_categories()
    form = RecurringRuleCreateForm(accounts=accounts, categories=categories, saving_goals=_get_user_saving_goals())

    if form.validate_on_submit():
        rule = RecurringRule(
            name=form.name.data,
            type=TransactionType(form.type.data),
            frequency=RecurringFrequency(form.frequency.data),
            interval=form.interval.data,
            amount=form.amount.data,
            next_due_date=form.next_due_date.data,
            active=True,
            scope=TransactionScope(form.scope.data),
            account_id=form.account_id.data,
            destination_account_id=form.destination_account_id.data,
            category_id=form.category_id.data,
            saving_goal_id=form.saving_goal_id.data if form.saving_goal_id.data else None,
            user_id=current_user.id,
        )
        db.session.add(rule)
        db.session.flush()

        if form.tags.data and form.tags.data.strip():
            _apply_rule_tags(rule, form.tags.data, current_user.id)

        db.session.commit()
        flash("Dauerauftrag erfolgreich erstellt.", "success")
        return redirect(url_for("recurring.index"))

    return render_template("recurring/create.html", form=form)


@recurring_bp.route("/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit(id):
    """Edit an existing recurring rule.

    Validates: Requirements 5.1, 5.10
    """
    rule = db.session.get(RecurringRule, id)
    if rule is None or rule.user_id != current_user.id:
        flash("Dauerauftrag nicht gefunden.", "danger")
        return redirect(url_for("recurring.index"))

    accounts = _get_user_accounts()
    categories = _get_user_categories()

    saving_goals = _get_user_saving_goals()

    if request.method == "GET":
        form = RecurringRuleEditForm(
            accounts=accounts,
            categories=categories,
            saving_goals=saving_goals,
            data={
                "name": rule.name,
                "type": rule.type.value,
                "frequency": rule.frequency.value,
                "interval": rule.interval,
                "amount": rule.amount,
                "next_due_date": rule.next_due_date,
                "account_id": rule.account_id,
                "destination_account_id": rule.destination_account_id or 0,
                "scope": rule.scope.value,
                "category_id": rule.category_id or 0,
                "saving_goal_id": rule.saving_goal_id or 0,
                "tags": ", ".join(t.name for t in rule.tags) if rule.tags else "",
            },
        )
    else:
        form = RecurringRuleEditForm(accounts=accounts, categories=categories, saving_goals=saving_goals)

    if form.validate_on_submit():
        rule.name = form.name.data
        rule.type = TransactionType(form.type.data)
        rule.frequency = RecurringFrequency(form.frequency.data)
        rule.interval = form.interval.data
        rule.amount = form.amount.data
        rule.next_due_date = form.next_due_date.data
        rule.scope = TransactionScope(form.scope.data)
        rule.account_id = form.account_id.data
        rule.destination_account_id = form.destination_account_id.data
        rule.category_id = form.category_id.data
        rule.saving_goal_id = form.saving_goal_id.data if form.saving_goal_id.data else None

        _apply_rule_tags(rule, form.tags.data or "", current_user.id)

        db.session.commit()
        flash("Dauerauftrag erfolgreich aktualisiert.", "success")
        return redirect(url_for("recurring.index"))

    return render_template("recurring/edit.html", form=form, rule=rule)


@recurring_bp.route("/toggle/<int:id>", methods=["POST"])
@login_required
def toggle(id):
    """Toggle a recurring rule's active status.

    Validates: Requirement 5.9
    Flips active from True to False or vice versa.
    """
    rule = db.session.get(RecurringRule, id)
    if rule is None or rule.user_id != current_user.id:
        flash("Dauerauftrag nicht gefunden.", "danger")
        return redirect(url_for("recurring.index"))

    rule.active = not rule.active
    db.session.commit()

    if rule.active:
        flash("Dauerauftrag aktiviert.", "success")
    else:
        flash("Dauerauftrag deaktiviert.", "success")

    return redirect(url_for("recurring.index"))


@recurring_bp.route("/splits/<int:id>", methods=["GET", "POST"])
@login_required
def splits(id):
    """Manage category splits for a recurring transfer rule.

    When the recurring rule fires, these splits are copied to the generated
    transaction as TransactionSplit records (Req 5.7).
    """
    from app.models.transaction import RecurringRuleSplit
    from decimal import Decimal

    rule = db.session.get(RecurringRule, id)
    if rule is None or rule.user_id != current_user.id:
        flash("Dauerauftrag nicht gefunden.", "danger")
        return redirect(url_for("recurring.index"))

    if rule.type != TransactionType.transfer:
        flash("Splits sind nur für Umbuchungen verfügbar.", "warning")
        return redirect(url_for("recurring.index"))

    categories = _get_user_categories()

    if request.method == "POST":
        # Clear existing splits
        RecurringRuleSplit.query.filter_by(recurring_rule_id=rule.id).delete()

        # Parse new splits from form
        split_count = int(request.form.get("split_count", 0))
        total = Decimal("0.00")
        errors = []

        for i in range(split_count):
            cat_id = request.form.get(f"split_category_{i}")
            amount_str = request.form.get(f"split_amount_{i}")
            desc = request.form.get(f"split_desc_{i}", "").strip()

            if not cat_id or not amount_str:
                continue

            try:
                amount = Decimal(amount_str.replace(",", "."))
                if amount <= 0:
                    errors.append(f"Split {i+1}: Betrag muss positiv sein.")
                    continue
            except Exception:
                errors.append(f"Split {i+1}: Ungültiger Betrag.")
                continue

            split = RecurringRuleSplit(
                recurring_rule_id=rule.id,
                category_id=int(cat_id),
                amount=amount,
                description=desc or None,
            )
            db.session.add(split)
            total += amount

        if errors:
            db.session.rollback()
            for err in errors:
                flash(err, "danger")
        elif total != rule.amount:
            db.session.rollback()
            flash(
                f"Summe der Splits ({total:.2f} €) stimmt nicht mit dem Betrag ({rule.amount:.2f} €) überein.",
                "danger",
            )
        else:
            db.session.commit()
            flash("Splits erfolgreich gespeichert.", "success")
            return redirect(url_for("recurring.index"))

    # Load existing splits
    existing_splits = RecurringRuleSplit.query.filter_by(
        recurring_rule_id=rule.id
    ).all()

    return render_template(
        "recurring/splits.html",
        rule=rule,
        categories=categories,
        existing_splits=existing_splits,
    )
