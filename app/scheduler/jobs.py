"""Scheduler job definitions for Haushaltsbuch.

Implements the daily, weekly, and monthly job sequences with error
isolation and advisory lock protection.

Validates: Requirements 26.1, 26.2, 26.3, 26.4, 26.5, 22.4, 15.3, 16.2
"""

import logging
from datetime import date, datetime, timezone

from flask import Flask

from app.extensions import db
from app.scheduler.lock import acquire_advisory_lock, release_advisory_lock

logger = logging.getLogger(__name__)


def register_jobs(app: Flask) -> None:
    """Register all scheduled jobs with APScheduler.

    Called during application startup to configure the scheduler's
    job triggers. Jobs are only registered if the scheduler is active
    (not in testing mode).

    Args:
        app: The Flask application instance.
    """
    from app.extensions import scheduler

    # Daily job: runs at 02:00 every day
    scheduler.add_job(
        id="daily_scheduler_job",
        func=daily_job,
        trigger="cron",
        hour=2,
        minute=0,
        replace_existing=True,
        kwargs={"app": app},
    )

    # Weekly job: runs at 03:00 every Sunday
    scheduler.add_job(
        id="weekly_audit_purge_job",
        func=weekly_audit_purge_job,
        trigger="cron",
        day_of_week="sun",
        hour=3,
        minute=0,
        replace_existing=True,
        kwargs={"app": app},
    )

    # Monthly job: runs at 04:00 on the 1st of every month
    scheduler.add_job(
        id="monthly_contribution_job",
        func=monthly_contribution_job,
        trigger="cron",
        day=1,
        hour=4,
        minute=0,
        replace_existing=True,
        kwargs={"app": app},
    )

    logger.info("Scheduled jobs registered successfully.")


# =============================================================================
# Daily Job
# =============================================================================


def daily_job(app: Flask) -> None:
    """Execute the daily scheduler job sequence.

    Validates: Requirements 26.1, 26.2, 26.3, 26.4, 26.5

    Sequence:
    1. Recurring rule catch-up
    2. ETF price refresh
    3. Net worth snapshot computation
    4. Credit interest capitalization

    Each task is wrapped in error isolation — if one task fails, it is
    logged and skipped, and the remaining tasks continue (Req 26.4).
    The advisory lock is always released in the finally block (Req 26.5).

    Args:
        app: The Flask application (needed for application context).
    """
    with app.app_context():
        # Acquire advisory lock (Req 26.1, 26.2)
        if not acquire_advisory_lock():
            logger.info("Daily job skipped: could not acquire advisory lock.")
            return

        try:
            logger.info("Daily scheduler job started.")

            # Task 1: Recurring rule catch-up (Req 26.3)
            _run_task("recurring_rule_catchup", _task_recurring_rule_catchup)

            # Task 2: ETF price refresh (Req 26.3)
            _run_task("etf_price_refresh", _task_etf_price_refresh)

            # Task 3: Net worth snapshot (Req 26.3)
            _run_task("networth_snapshot", _task_networth_snapshot)

            # Task 4: Credit interest capitalization — DISABLED
            # Interest is now calculated on-demand before each repayment
            # _run_task("credit_interest_capitalization", _task_credit_interest_capitalization)

            logger.info("Daily scheduler job completed.")
        finally:
            # Always release the lock (Req 26.5)
            release_advisory_lock()


# =============================================================================
# Weekly Job
# =============================================================================


def weekly_audit_purge_job(app: Flask) -> None:
    """Execute the weekly audit log purge job (Sundays).

    Validates: Requirement 22.4

    Removes AuditLog entries older than 6 months (180 days).

    Args:
        app: The Flask application (needed for application context).
    """
    with app.app_context():
        if not acquire_advisory_lock():
            logger.info("Weekly audit purge skipped: could not acquire advisory lock.")
            return

        try:
            logger.info("Weekly audit purge job started.")
            _run_task("audit_log_purge", _task_audit_log_purge)
            logger.info("Weekly audit purge job completed.")
        finally:
            release_advisory_lock()


# =============================================================================
# Monthly Job
# =============================================================================


def monthly_contribution_job(app: Flask) -> None:
    """Execute the monthly bAV/VL contribution log generation.

    Validates: Requirements 15.3, 16.2

    Generates contribution log entries for all active bAV and VL contracts
    on the 1st of each month.

    Args:
        app: The Flask application (needed for application context).
    """
    with app.app_context():
        if not acquire_advisory_lock():
            logger.info("Monthly contribution job skipped: could not acquire advisory lock.")
            return

        try:
            logger.info("Monthly contribution job started.")
            _run_task("bav_contribution_logs", _task_bav_contribution_logs)
            _run_task("vl_contribution_logs", _task_vl_contribution_logs)
            logger.info("Monthly contribution job completed.")
        finally:
            release_advisory_lock()


# =============================================================================
# Error Isolation Wrapper
# =============================================================================


def _run_task(task_name: str, task_fn: callable) -> None:
    """Execute a task with error isolation.

    Validates: Requirement 26.4

    If the task raises an exception, it is logged with the task name and
    error detail, and execution continues with the remaining tasks.

    Args:
        task_name: Human-readable name for logging.
        task_fn: Callable to execute (no arguments).
    """
    try:
        task_fn()
        logger.info("Task '%s' completed successfully.", task_name)
    except Exception:
        logger.exception(
            "Task '%s' failed. Skipping and continuing with remaining tasks.",
            task_name,
        )
        # Rollback any uncommitted changes from the failed task
        db.session.rollback()


# =============================================================================
# Individual Task Implementations
# =============================================================================


def _task_recurring_rule_catchup() -> None:
    """Process recurring rule catch-up for all users.

    Validates: Requirement 5.2, 5.8 (via RecurringService)

    Processes all active recurring rules with next_due_date <= today
    for every user in the system.
    """
    from app.models.user import User
    from app.services.recurring_service import RecurringService

    service = RecurringService()
    users = User.query.all()
    today = date.today()

    for user in users:
        transactions, notifications = service.process_due_rules(user, today)
        if transactions:
            logger.info(
                "Recurring catch-up: generated %d transactions for user %d.",
                len(transactions),
                user.id,
            )


def _task_etf_price_refresh() -> None:
    """Refresh ETF prices for all active positions via Yahoo Finance.

    Validates: Requirement 13.2, 13.3, 13.4

    Fetches closing prices for all active ETF positions using yfinance.
    Logs failures per position without blocking others.
    After 3 consecutive failures, generates a notification.
    """
    from app.models.etf import ETFPosition, ETFPriceHistory
    from app.models.notification import Notification
    from app.services.audit_service import AuditService

    audit_service = AuditService()

    positions = ETFPosition.query.filter(
        ETFPosition.shares > 0,
        ETFPosition.manual_price_override == False,  # noqa: E712
    ).all()

    if not positions:
        logger.info("ETF price refresh: no active positions to update.")
        return

    try:
        import yfinance as yf
    except ImportError:
        logger.error("ETF price refresh: yfinance library not available.")
        return

    now = datetime.now(timezone.utc)
    today = date.today()

    for position in positions:
        try:
            ticker_symbol = f"{position.ticker}.{position.exchange_suffix}"
            ticker = yf.Ticker(ticker_symbol)
            hist = ticker.history(period="1d")

            if hist.empty:
                raise ValueError(f"No price data returned for {ticker_symbol}")

            closing_price = hist["Close"].iloc[-1]

            from decimal import Decimal

            price = Decimal(str(closing_price)).quantize(Decimal("0.0001"))

            # Update position's current price
            position.current_price = price
            position.current_price_updated_at = now
            position.consecutive_fetch_failures = 0

            # Store in price history (upsert by position_id + date)
            existing_history = ETFPriceHistory.query.filter_by(
                position_id=position.id, date=today
            ).first()

            if existing_history:
                existing_history.price = price
            else:
                history_entry = ETFPriceHistory(
                    position_id=position.id,
                    price=price,
                    date=today,
                )
                db.session.add(history_entry)

            db.session.commit()

            logger.info(
                "ETF price refresh: %s updated to %s.",
                ticker_symbol,
                price,
            )

        except Exception as e:
            # Log failure and continue with other positions (Req 13.3)
            db.session.rollback()
            position.consecutive_fetch_failures += 1
            db.session.commit()

            logger.warning(
                "ETF price refresh failed for position %d (%s.%s): %s",
                position.id,
                position.ticker,
                position.exchange_suffix,
                str(e),
            )

            # After 3 consecutive failures, generate notification (Req 13.4)
            if position.consecutive_fetch_failures >= 3:
                notification = Notification(
                    user_id=position.user_id,
                    type="etf_price_fetch_failed",
                    message=(
                        f"ETF-Kurs für '{position.ticker}.{position.exchange_suffix}' "
                        f"konnte seit {position.consecutive_fetch_failures} Tagen "
                        f"nicht aktualisiert werden."
                    ),
                )
                db.session.add(notification)
                db.session.commit()


def _task_networth_snapshot() -> None:
    """Compute net worth snapshots for all users.

    Validates: Requirement 18.1

    Called after ETF price refresh to ensure snapshots use the latest
    available prices.
    """
    from app.models.user import User
    from app.services.networth_service import NetWorthService

    service = NetWorthService()
    users = User.query.all()
    today = date.today()

    for user in users:
        service.compute_snapshot(user.id, today)
        logger.info("Net worth snapshot computed for user %d.", user.id)


def _task_credit_interest_capitalization() -> None:
    """Capitalize accrued interest on credits where today matches capitalization day.

    Validates: Requirement 11.3

    For each active credit whose interest_capitalization_day matches today's
    day-of-month, capitalizes accrued interest (adds to remaining_balance,
    resets accrued_interest to zero).
    """
    from app.models.credit import Credit, CreditStatus
    from app.services.credit_service import CreditService

    service = CreditService()
    today = date.today()

    # Find all active credits where today is the capitalization day
    credits = Credit.query.filter(
        Credit.status == CreditStatus.active,
        Credit.interest_capitalization_day == today.day,
    ).all()

    for credit in credits:
        try:
            service.capitalize_interest(credit)
            logger.info(
                "Interest capitalized for credit %d (%s).",
                credit.id,
                credit.name,
            )
        except Exception:
            logger.exception(
                "Failed to capitalize interest for credit %d (%s).",
                credit.id,
                credit.name,
            )


def _task_audit_log_purge() -> None:
    """Purge audit log entries older than 6 months.

    Validates: Requirement 22.4

    Removes all AuditLog entries with created_at older than 180 days.
    """
    from app.services.audit_service import AuditService

    service = AuditService()
    deleted_count = service.purge_old_entries(retention_days=180)
    logger.info("Audit log purge: removed %d entries older than 6 months.", deleted_count)


def _task_bav_contribution_logs() -> None:
    """Generate monthly bAV contribution logs for all users.

    Validates: Requirement 15.3

    Creates BaVContributionLog entries for each active bAV contract.
    Idempotent — skips contracts that already have an entry for the
    current month.
    """
    from app.models.user import User
    from app.services.bav_service import BaVService

    service = BaVService()
    users = User.query.all()
    today = date.today()
    target_month = date(today.year, today.month, 1)

    for user in users:
        logs = service.generate_monthly_logs(user, target_month)
        if logs:
            db.session.commit()
            logger.info(
                "bAV contribution logs: generated %d entries for user %d.",
                len(logs),
                user.id,
            )


def _task_vl_contribution_logs() -> None:
    """Generate monthly VL contribution logs for all users.

    Validates: Requirement 16.2

    Creates VLContributionLog entries for each active VL contract.
    If linked to an ETF position with fresh prices, creates ETF buy
    transactions. Idempotent — skips contracts that already have an
    entry for the current month.
    """
    from app.models.user import User
    from app.services.vl_service import VLService

    service = VLService()
    users = User.query.all()
    today = date.today()
    target_month = date(today.year, today.month, 1)

    for user in users:
        logs, notifications = service.generate_monthly_contributions(user, target_month)
        if logs:
            db.session.commit()
            logger.info(
                "VL contribution logs: generated %d entries for user %d.",
                len(logs),
                user.id,
            )
        # Log any stale price notifications
        for notif in notifications:
            if notif.notification_type == "vl_price_stale":
                logger.warning("VL notification: %s", notif.message)
