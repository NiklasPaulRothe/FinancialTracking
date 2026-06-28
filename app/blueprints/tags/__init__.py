"""Tags blueprint for Haushaltsbuch.

Provides CRUD routes for managing transaction tags.
All routes require authentication.

Validates: Requirements 20.1, 20.6
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.extensions import db
from app.models.transaction import Tag, transaction_tags

tags_bp = Blueprint(
    "tags",
    __name__,
    url_prefix="/tags",
    template_folder="templates",
)


@tags_bp.route("/")
@login_required
def index():
    """Display all tags for the current user.

    Validates: Requirement 20.1
    """
    tags = (
        Tag.query
        .filter_by(user_id=current_user.id)
        .order_by(Tag.name)
        .all()
    )
    return render_template(
        "tags/index.html",
        tags=tags,
    )


@tags_bp.route("/create", methods=["POST"])
@login_required
def create():
    """Create a new tag.

    Validates: Requirement 20.1
    """
    name = request.form.get("name", "").strip()

    if not name:
        flash("Tag-Name darf nicht leer sein.", "danger")
        return redirect(url_for("tags.index"))

    if len(name) > 30:
        flash("Tag-Name darf maximal 30 Zeichen lang sein.", "danger")
        return redirect(url_for("tags.index"))

    # Check uniqueness
    existing = Tag.query.filter_by(
        name=name, user_id=current_user.id
    ).first()
    if existing:
        flash("Ein Tag mit diesem Namen existiert bereits.", "danger")
        return redirect(url_for("tags.index"))

    tag = Tag(
        name=name,
        user_id=current_user.id,
    )
    db.session.add(tag)
    db.session.commit()
    flash("Tag erfolgreich erstellt.", "success")
    return redirect(url_for("tags.index"))


@tags_bp.route("/delete/<int:id>", methods=["POST"])
@login_required
def delete(id):
    """Delete a tag.

    Removes the tag and all associations to transactions.
    Validates: Requirement 20.6
    """
    tag = db.session.get(Tag, id)
    if tag is None or tag.user_id != current_user.id:
        flash("Tag nicht gefunden.", "danger")
        return redirect(url_for("tags.index"))

    # Remove all transaction-tag associations
    db.session.execute(
        transaction_tags.delete().where(transaction_tags.c.tag_id == id)
    )

    db.session.delete(tag)
    db.session.commit()
    flash("Tag erfolgreich gelöscht.", "success")
    return redirect(url_for("tags.index"))
