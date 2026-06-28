"""Unit tests for the scheduler module.

Tests job sequencing, error isolation, advisory lock behaviour,
and job registration logic.

Validates: Requirements 26.1, 26.2, 26.3, 26.4, 26.5
"""

import logging
from unittest.mock import patch, MagicMock, call

import pytest

from app.scheduler.lock import acquire_advisory_lock, release_advisory_lock
from app.scheduler.jobs import (
    daily_job,
    weekly_audit_purge_job,
    monthly_contribution_job,
    register_jobs,
    _run_task,
)


class TestRunTask:
    """Tests for the _run_task error isolation wrapper."""

    def test_successful_task_does_not_raise(self):
        """A successful task completes without error."""
        called = []

        def task_fn():
            called.append(True)

        _run_task("test_task", task_fn)
        assert called == [True]

    def test_failed_task_logs_and_continues(self, caplog):
        """A failing task is logged and does not propagate the exception.

        Validates: Requirement 26.4
        """
        def failing_task():
            raise RuntimeError("Simulated failure")

        with patch("app.scheduler.jobs.db") as mock_db:
            with caplog.at_level(logging.ERROR):
                _run_task("broken_task", failing_task)

            # Session rollback should have been called
            mock_db.session.rollback.assert_called_once()

        # Error should be logged with task name
        assert "broken_task" in caplog.text
        assert "failed" in caplog.text.lower()

    def test_failed_task_does_not_prevent_subsequent_tasks(self):
        """After a task failure, subsequent tasks still execute.

        Validates: Requirement 26.4
        """
        execution_order = []

        def task_a():
            raise ValueError("Task A fails")

        def task_b():
            execution_order.append("B")

        def task_c():
            execution_order.append("C")

        with patch("app.scheduler.jobs.db"):
            _run_task("task_a", task_a)
            _run_task("task_b", task_b)
            _run_task("task_c", task_c)

        assert execution_order == ["B", "C"]


class TestDailyJob:
    """Tests for the daily scheduler job."""

    @patch("app.scheduler.jobs.release_advisory_lock")
    @patch("app.scheduler.jobs.acquire_advisory_lock")
    @patch("app.scheduler.jobs._task_credit_interest_capitalization")
    @patch("app.scheduler.jobs._task_networth_snapshot")
    @patch("app.scheduler.jobs._task_etf_price_refresh")
    @patch("app.scheduler.jobs._task_recurring_rule_catchup")
    def test_daily_job_executes_all_tasks_in_order(
        self,
        mock_recurring,
        mock_etf,
        mock_networth,
        mock_credit,
        mock_acquire,
        mock_release,
        app,
    ):
        """Daily job executes tasks in the correct fixed sequence.

        Validates: Requirement 26.3
        """
        mock_acquire.return_value = True
        call_order = []

        mock_recurring.side_effect = lambda: call_order.append("recurring")
        mock_etf.side_effect = lambda: call_order.append("etf")
        mock_networth.side_effect = lambda: call_order.append("networth")
        mock_credit.side_effect = lambda: call_order.append("credit")

        daily_job(app)

        assert call_order == ["recurring", "etf", "networth", "credit"]

    @patch("app.scheduler.jobs.release_advisory_lock")
    @patch("app.scheduler.jobs.acquire_advisory_lock")
    @patch("app.scheduler.jobs._task_recurring_rule_catchup")
    def test_daily_job_skipped_when_lock_not_acquired(
        self, mock_recurring, mock_acquire, mock_release, app
    ):
        """Daily job is skipped when the advisory lock cannot be acquired.

        Validates: Requirement 26.2
        """
        mock_acquire.return_value = False

        daily_job(app)

        mock_recurring.assert_not_called()
        mock_release.assert_not_called()

    @patch("app.scheduler.jobs.release_advisory_lock")
    @patch("app.scheduler.jobs.acquire_advisory_lock")
    @patch("app.scheduler.jobs._task_credit_interest_capitalization")
    @patch("app.scheduler.jobs._task_networth_snapshot")
    @patch("app.scheduler.jobs._task_etf_price_refresh")
    @patch("app.scheduler.jobs._task_recurring_rule_catchup")
    def test_daily_job_releases_lock_on_success(
        self,
        mock_recurring,
        mock_etf,
        mock_networth,
        mock_credit,
        mock_acquire,
        mock_release,
        app,
    ):
        """Lock is released after successful execution.

        Validates: Requirement 26.5
        """
        mock_acquire.return_value = True

        daily_job(app)

        mock_release.assert_called_once()

    @patch("app.scheduler.jobs.release_advisory_lock")
    @patch("app.scheduler.jobs.acquire_advisory_lock")
    @patch("app.scheduler.jobs._task_recurring_rule_catchup")
    def test_daily_job_releases_lock_even_on_unhandled_error(
        self, mock_recurring, mock_acquire, mock_release, app
    ):
        """Lock is released in finally block even if an unexpected error occurs.

        Validates: Requirement 26.5
        """
        mock_acquire.return_value = True
        # Simulate an error that escapes the _run_task wrapper
        # (e.g. if _run_task itself raised)
        mock_recurring.side_effect = SystemExit("catastrophic")

        with pytest.raises(SystemExit):
            daily_job(app)

        mock_release.assert_called_once()

    @patch("app.scheduler.jobs.release_advisory_lock")
    @patch("app.scheduler.jobs.acquire_advisory_lock")
    @patch("app.scheduler.jobs._task_credit_interest_capitalization")
    @patch("app.scheduler.jobs._task_networth_snapshot")
    @patch("app.scheduler.jobs._task_etf_price_refresh")
    @patch("app.scheduler.jobs._task_recurring_rule_catchup")
    def test_error_isolation_continues_after_failure(
        self,
        mock_recurring,
        mock_etf,
        mock_networth,
        mock_credit,
        mock_acquire,
        mock_release,
        app,
    ):
        """If one task fails, remaining tasks still execute.

        Validates: Requirement 26.4
        """
        mock_acquire.return_value = True
        mock_etf.side_effect = RuntimeError("ETF refresh failed")
        call_order = []
        mock_recurring.side_effect = lambda: call_order.append("recurring")
        mock_networth.side_effect = lambda: call_order.append("networth")
        mock_credit.side_effect = lambda: call_order.append("credit")

        daily_job(app)

        # recurring was called before the failing etf task
        assert "recurring" in call_order
        # networth and credit should still execute after etf failure
        assert "networth" in call_order
        assert "credit" in call_order


class TestWeeklyJob:
    """Tests for the weekly audit purge job."""

    @patch("app.scheduler.jobs.release_advisory_lock")
    @patch("app.scheduler.jobs.acquire_advisory_lock")
    @patch("app.scheduler.jobs._task_audit_log_purge")
    def test_weekly_job_calls_audit_purge(
        self, mock_purge, mock_acquire, mock_release, app
    ):
        """Weekly job invokes the audit log purge task.

        Validates: Requirement 22.4
        """
        mock_acquire.return_value = True

        weekly_audit_purge_job(app)

        mock_purge.assert_called_once()
        mock_release.assert_called_once()

    @patch("app.scheduler.jobs.release_advisory_lock")
    @patch("app.scheduler.jobs.acquire_advisory_lock")
    @patch("app.scheduler.jobs._task_audit_log_purge")
    def test_weekly_job_skipped_when_lock_not_acquired(
        self, mock_purge, mock_acquire, mock_release, app
    ):
        """Weekly job is skipped when lock cannot be acquired."""
        mock_acquire.return_value = False

        weekly_audit_purge_job(app)

        mock_purge.assert_not_called()
        mock_release.assert_not_called()


class TestMonthlyJob:
    """Tests for the monthly bAV/VL contribution job."""

    @patch("app.scheduler.jobs.release_advisory_lock")
    @patch("app.scheduler.jobs.acquire_advisory_lock")
    @patch("app.scheduler.jobs._task_vl_contribution_logs")
    @patch("app.scheduler.jobs._task_bav_contribution_logs")
    def test_monthly_job_calls_both_tasks(
        self, mock_bav, mock_vl, mock_acquire, mock_release, app
    ):
        """Monthly job invokes both bAV and VL contribution tasks.

        Validates: Requirements 15.3, 16.2
        """
        mock_acquire.return_value = True

        monthly_contribution_job(app)

        mock_bav.assert_called_once()
        mock_vl.assert_called_once()
        mock_release.assert_called_once()

    @patch("app.scheduler.jobs.release_advisory_lock")
    @patch("app.scheduler.jobs.acquire_advisory_lock")
    @patch("app.scheduler.jobs._task_vl_contribution_logs")
    @patch("app.scheduler.jobs._task_bav_contribution_logs")
    def test_monthly_job_skipped_when_lock_not_acquired(
        self, mock_bav, mock_vl, mock_acquire, mock_release, app
    ):
        """Monthly job is skipped when lock cannot be acquired."""
        mock_acquire.return_value = False

        monthly_contribution_job(app)

        mock_bav.assert_not_called()
        mock_vl.assert_not_called()


class TestRegisterJobs:
    """Tests for job registration."""

    def test_register_jobs_adds_all_jobs(self, app):
        """register_jobs() adds daily, weekly, and monthly jobs."""
        mock_scheduler = MagicMock()

        with patch("app.extensions.scheduler", mock_scheduler):
            register_jobs(app)

        # Should have 3 add_job calls
        assert mock_scheduler.add_job.call_count == 3

        # Verify job IDs
        job_ids = [
            c.kwargs["id"] for c in mock_scheduler.add_job.call_args_list
        ]
        assert "daily_scheduler_job" in job_ids
        assert "weekly_audit_purge_job" in job_ids
        assert "monthly_contribution_job" in job_ids
