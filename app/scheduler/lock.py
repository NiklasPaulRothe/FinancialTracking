"""PostgreSQL advisory lock for scheduler concurrency control.

Ensures only one instance of the scheduler job runs at a time,
even across multiple worker processes.

Validates: Requirements 26.1, 26.2, 26.5
"""

import logging

from sqlalchemy import text

from app.extensions import db

logger = logging.getLogger(__name__)

# Fixed lock ID for the daily scheduler job.
# Advisory locks use a 64-bit integer key; we pick an arbitrary constant.
SCHEDULER_LOCK_ID = 8675309


def acquire_advisory_lock(lock_id: int = SCHEDULER_LOCK_ID, timeout_ms: int = 1000) -> bool:
    """Attempt to acquire a PostgreSQL advisory lock with a timeout.

    Validates: Requirements 26.1, 26.2

    Uses pg_try_advisory_lock after setting a statement timeout so that
    the attempt is abandoned if the lock cannot be acquired within the
    specified timeout window.

    Args:
        lock_id: The advisory lock identifier (default: SCHEDULER_LOCK_ID).
        timeout_ms: Maximum time in milliseconds to wait (default: 1000ms = 1s).

    Returns:
        True if the lock was acquired, False otherwise.
    """
    try:
        # Set a statement timeout for this transaction
        db.session.execute(
            text(f"SET LOCAL lock_timeout = '{timeout_ms}ms'")
        )
        result = db.session.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": lock_id},
        )
        acquired = result.scalar()
        return bool(acquired)
    except Exception:
        # If the lock cannot be acquired (timeout or other error), return False
        logger.info(
            "Could not acquire advisory lock %d within %dms, skipping execution.",
            lock_id,
            timeout_ms,
        )
        return False


def release_advisory_lock(lock_id: int = SCHEDULER_LOCK_ID) -> None:
    """Release a previously acquired PostgreSQL advisory lock.

    Validates: Requirement 26.5

    Must be called in a finally block to ensure the lock is always
    released, even if an error occurs during job execution.

    Args:
        lock_id: The advisory lock identifier to release.
    """
    try:
        db.session.execute(
            text("SELECT pg_advisory_unlock(:lock_id)"),
            {"lock_id": lock_id},
        )
        db.session.commit()
    except Exception:
        logger.warning(
            "Failed to release advisory lock %d. "
            "It will be released when the session ends.",
            lock_id,
            exc_info=True,
        )
