"""Notifications blueprint for Haushaltsbuch.

Provides routes for listing notifications and marking them as read.
All routes require authentication.

Validates: Requirements 21.1, 21.2, 21.3
"""

from flask import Blueprint, render_template, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from app.extensions import db
from app.models.notification import Notification

notifications_bp = Blueprint(
    "notifications",
    __name__,
    url_prefix="/notifications",
    template_folder="templates",
)


@notifications_bp.route("/")
@login_required
def index():
    """Display all notifications for the current user.

    Shows the 50 most recent notifications ordered by creation date descending.
    Validates: Requirement 21.2
    """
    notifications = (
        Notification.query
        .filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
        .all()
    )
    return render_template(
        "notifications/index.html",
        notifications=notifications,
    )


@notifications_bp.route("/mark_read/<int:id>", methods=["POST"])
@login_required
def mark_read(id):
    """Mark a single notification as read.

    Validates: Requirement 21.3
    """
    notification = db.session.get(Notification, id)
    if notification is None or notification.user_id != current_user.id:
        flash("Benachrichtigung nicht gefunden.", "danger")
        return redirect(url_for("notifications.index"))

    notification.read = True
    db.session.commit()
    flash("Benachrichtigung als gelesen markiert.", "success")

    # If the notification has a link, redirect there
    if notification.link_url:
        return redirect(notification.link_url)

    return redirect(url_for("notifications.index"))
