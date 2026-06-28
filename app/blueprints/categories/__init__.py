"""Categories blueprint for Haushaltsbuch.

Provides CRUD routes for managing transaction categories.
All routes require authentication.

Validates: Requirements 20.1, 20.6
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.extensions import db
from app.models.category import Category
from app.models.transaction import Transaction, TransactionSplit

categories_bp = Blueprint(
    "categories",
    __name__,
    url_prefix="/categories",
    template_folder="templates",
)


@categories_bp.route("/")
@login_required
def index():
    """Display all categories for the current user.

    Validates: Requirement 20.1
    """
    categories = (
        Category.query
        .filter_by(user_id=current_user.id)
        .order_by(Category.scope, Category.name)
        .all()
    )
    return render_template(
        "categories/index.html",
        categories=categories,
    )


@categories_bp.route("/create", methods=["POST"])
@login_required
def create():
    """Create a new category.

    Validates: Requirement 20.1
    """
    name = request.form.get("name", "").strip()
    scope = request.form.get("scope", "personal")
    icon = request.form.get("icon", "").strip() or None

    if not name:
        flash("Kategoriename darf nicht leer sein.", "danger")
        return redirect(url_for("categories.index"))

    if len(name) > 50:
        flash("Kategoriename darf maximal 50 Zeichen lang sein.", "danger")
        return redirect(url_for("categories.index"))

    if scope not in ("personal", "shared"):
        flash("Ungültiger Bereich.", "danger")
        return redirect(url_for("categories.index"))

    # Check uniqueness
    existing = Category.query.filter_by(
        name=name, user_id=current_user.id, scope=scope
    ).first()
    if existing:
        flash("Eine Kategorie mit diesem Namen existiert bereits.", "danger")
        return redirect(url_for("categories.index"))

    category = Category(
        name=name,
        scope=scope,
        icon=icon,
        user_id=current_user.id,
    )
    db.session.add(category)
    db.session.commit()
    flash("Kategorie erfolgreich erstellt.", "success")
    return redirect(url_for("categories.index"))


@categories_bp.route("/delete/<int:id>", methods=["POST"])
@login_required
def delete(id):
    """Delete a category.

    Sets category_id to null on all transactions that used this category.
    Validates: Requirement 20.6
    """
    category = db.session.get(Category, id)
    if category is None or category.user_id != current_user.id:
        flash("Kategorie nicht gefunden.", "danger")
        return redirect(url_for("categories.index"))

    # Nullify category references on transactions
    Transaction.query.filter_by(category_id=id).update({"category_id": None})
    TransactionSplit.query.filter_by(category_id=id).update({"category_id": None})

    db.session.delete(category)
    db.session.commit()
    flash("Kategorie erfolgreich gelöscht.", "success")
    return redirect(url_for("categories.index"))
