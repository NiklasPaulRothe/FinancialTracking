"""Haushaltsbuch Flask application factory."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import Flask, render_template
from flask_login import current_user

from app.config import config_by_name
from app.extensions import db, migrate, login_manager, scheduler, csrf


def create_app(config_name: str = "development") -> Flask:
    """Create and configure the Flask application.

    Args:
        config_name: Configuration profile to load.
            One of 'development', 'testing', or 'production'.

    Returns:
        Configured Flask application instance.
    """
    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Initialize scheduler (start only outside testing)
    if not app.config.get("TESTING"):
        scheduler.init_app(app)
        try:
            scheduler.start()
            # Register scheduled jobs after scheduler is running
            from app.scheduler import register_jobs
            register_jobs(app)
        except Exception:
            # Scheduler start may fail if job store is unavailable (e.g. no DB)
            pass

    # Register blueprints
    from app.blueprints.auth import auth_bp  # noqa: E402
    from app.blueprints.accounts import accounts_bp  # noqa: E402
    from app.blueprints.transactions import transactions_bp  # noqa: E402
    from app.blueprints.recurring import recurring_bp  # noqa: E402
    from app.blueprints.budgets import budgets_bp  # noqa: E402
    from app.blueprints.planned_expenses import planned_expenses_bp  # noqa: E402
    from app.blueprints.saving_goals import saving_goals_bp  # noqa: E402
    from app.blueprints.credits import credits_bp  # noqa: E402
    from app.blueprints.settlements import settlements_bp  # noqa: E402
    from app.blueprints.bav import bav_bp  # noqa: E402
    from app.blueprints.vl import vl_bp  # noqa: E402
    from app.blueprints.etf import etf_bp  # noqa: E402
    from app.blueprints.imports import imports_bp  # noqa: E402
    from app.blueprints.notifications import notifications_bp  # noqa: E402
    from app.blueprints.categories import categories_bp  # noqa: E402
    from app.blueprints.tags import tags_bp  # noqa: E402
    from app.blueprints.reports import reports_bp  # noqa: E402
    from app.blueprints.settings import settings_bp  # noqa: E402
    from app.blueprints.dashboard import dashboard_bp  # noqa: E402

    app.register_blueprint(auth_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(recurring_bp)
    app.register_blueprint(budgets_bp)
    app.register_blueprint(planned_expenses_bp)
    app.register_blueprint(saving_goals_bp)
    app.register_blueprint(credits_bp)
    app.register_blueprint(settlements_bp)
    app.register_blueprint(bav_bp)
    app.register_blueprint(vl_bp)
    app.register_blueprint(etf_bp)
    app.register_blueprint(imports_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(categories_bp)
    app.register_blueprint(tags_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(dashboard_bp)

    # Context processor for global template variables
    @app.context_processor
    def inject_globals():
        """Inject global variables into all templates."""
        context = {"now": lambda: datetime.now(timezone.utc)}
        if current_user.is_authenticated:
            from app.models.notification import Notification

            unread_count = (
                Notification.query
                .filter_by(user_id=current_user.id, read=False)
                .count()
            )
            context["unread_notification_count"] = unread_count
        return context

    # ── Jinja2 custom filters ──────────────────────────────────────────────

    @app.template_filter("format_date")
    def format_date_filter(value, fmt=None):
        """Format a date/datetime using the current user's date_format preference.

        Supported format tokens: DD.MM.YYYY, YYYY-MM-DD, MM/DD/YYYY.
        Falls back to DD.MM.YYYY if no user is authenticated.

        Validates: Requirement 25.3
        """
        if value is None:
            return ""

        if fmt is None:
            if current_user and current_user.is_authenticated:
                fmt = getattr(current_user, "date_format", "DD.MM.YYYY")
            else:
                fmt = "DD.MM.YYYY"

        format_map = {
            "DD.MM.YYYY": "%d.%m.%Y",
            "YYYY-MM-DD": "%Y-%m-%d",
            "MM/DD/YYYY": "%m/%d/%Y",
        }
        strftime_fmt = format_map.get(fmt, "%d.%m.%Y")

        try:
            return value.strftime(strftime_fmt)
        except (AttributeError, ValueError):
            return str(value)

    @app.template_filter("format_currency")
    def format_currency_filter(value, symbol="€", decimal_places=2):
        """Format a number using German locale: period as thousands separator,
        comma as decimal separator, e.g. 1.234,56 €.

        Validates: Requirement 25.4
        """
        if value is None:
            return ""

        try:
            number = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return str(value)

        # Determine sign
        sign = "-" if number < 0 else ""
        number = abs(number)

        # Quantize to specified decimal places
        quantize_str = "0." + "0" * decimal_places
        number = number.quantize(Decimal(quantize_str))

        # Split into integer and decimal parts
        parts = str(number).split(".")
        integer_part = parts[0]
        decimal_part = parts[1] if len(parts) > 1 else "0" * decimal_places

        # Add thousands separators (periods)
        formatted_integer = ""
        for i, digit in enumerate(reversed(integer_part)):
            if i > 0 and i % 3 == 0:
                formatted_integer = "." + formatted_integer
            formatted_integer = digit + formatted_integer

        # Combine with comma as decimal separator
        result = f"{sign}{formatted_integer},{decimal_part}"
        if symbol:
            result = f"{result} {symbol}"
        return result

    @app.template_filter("format_number")
    def format_number_filter(value, decimal_places=2):
        """Format a number using German locale without currency symbol.

        Validates: Requirement 25.4
        """
        return format_currency_filter(value, symbol="", decimal_places=decimal_places)

    # ── Error handlers ─────────────────────────────────────────────────────

    @app.errorhandler(404)
    def page_not_found(e):
        """Render 404 error page."""
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        """Render 500 error page."""
        return render_template("errors/500.html"), 500

    return app
