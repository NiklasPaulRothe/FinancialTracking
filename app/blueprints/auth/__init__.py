"""Authentication blueprint for Haushaltsbuch.

Provides login, registration, and logout routes.
Enforces the 2-user household limit on registration.

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.8
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user

from app.extensions import db
from app.models.user import User
from app.exceptions import HouseholdFullError
from app.blueprints.auth.forms import LoginForm, RegistrationForm

auth_bp = Blueprint("auth", __name__, url_prefix="/auth", template_folder="templates")

MAX_HOUSEHOLD_USERS = 2


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Handle user login."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash("Ungültiger Benutzername oder Passwort.", "danger")
            return render_template("auth/login.html", form=form)

        login_user(user, remember=form.remember_me.data)
        next_page = request.args.get("next")
        return redirect(next_page or url_for("dashboard.index"))

    return render_template("auth/login.html", form=form)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Handle new user registration with 2-user household limit."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = RegistrationForm()
    if form.validate_on_submit():
        # Enforce household limit
        user_count = db.session.query(User).count()
        if user_count >= MAX_HOUSEHOLD_USERS:
            raise HouseholdFullError()

        # Check for existing username
        if User.query.filter_by(username=form.username.data).first():
            form.username.errors.append("Dieser Benutzername ist bereits vergeben.")
            return render_template("auth/register.html", form=form)

        # Check for existing email
        if User.query.filter_by(email=form.email.data).first():
            form.email.errors.append("Diese E-Mail-Adresse wird bereits verwendet.")
            return render_template("auth/register.html", form=form)

        user = User(
            username=form.username.data,
            email=form.email.data,
            income_day=form.income_day.data,
        )
        user.set_password(form.password.data)

        db.session.add(user)
        db.session.commit()

        flash("Registrierung erfolgreich. Bitte melden Sie sich an.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    """Log out the current user and redirect to login."""
    logout_user()
    flash("Sie wurden abgemeldet.", "info")
    return redirect(url_for("auth.login"))
