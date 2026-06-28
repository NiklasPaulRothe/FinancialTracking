"""Scheduler package for Haushaltsbuch background jobs.

Provides APScheduler job definitions, PostgreSQL advisory lock for
concurrency control, and the daily/weekly/monthly job sequences.

Validates: Requirements 26.1, 26.2, 26.3, 26.4, 26.5
"""

from app.scheduler.jobs import register_jobs  # noqa: F401

__all__ = ["register_jobs"]
