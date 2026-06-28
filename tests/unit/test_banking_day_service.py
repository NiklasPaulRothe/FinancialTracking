"""Unit tests for BankingDayService.

Tests effective income day calculation with German banking day adjustments,
including weekends, public holidays, month overflow, and combined scenarios.

Validates: Requirements 7.1, 7.2, 7.3
"""

import pytest
from datetime import date

from app.services.banking_day_service import BankingDayService


@pytest.fixture()
def service():
    """Create a BankingDayService instance."""
    return BankingDayService()


class TestIsBankingDay:
    """Tests for BankingDayService.is_banking_day."""

    def test_weekday_not_holiday_is_banking_day(self, service):
        """A regular weekday (not a holiday) is a banking day."""
        # 2024-03-04 is a Monday, not a holiday
        assert service.is_banking_day(date(2024, 3, 4)) is True

    def test_saturday_is_not_banking_day(self, service):
        """Saturday is not a banking day."""
        # 2024-03-02 is a Saturday
        assert service.is_banking_day(date(2024, 3, 2)) is False

    def test_sunday_is_not_banking_day(self, service):
        """Sunday is not a banking day."""
        # 2024-03-03 is a Sunday
        assert service.is_banking_day(date(2024, 3, 3)) is False

    def test_german_holiday_is_not_banking_day(self, service):
        """A German public holiday (Christmas Day) is not a banking day."""
        # Dec 25 is always a holiday in Germany (1. Weihnachtstag)
        assert service.is_banking_day(date(2024, 12, 25)) is False

    def test_new_years_day_is_not_banking_day(self, service):
        """New Year's Day (Jan 1) is not a banking day."""
        assert service.is_banking_day(date(2025, 1, 1)) is False

    def test_good_friday_is_not_banking_day(self, service):
        """Good Friday (Karfreitag) is not a banking day."""
        # 2024 Good Friday is March 29
        assert service.is_banking_day(date(2024, 3, 29)) is False


class TestLastBankingDayOnOrBefore:
    """Tests for BankingDayService.last_banking_day_on_or_before."""

    def test_banking_day_returns_same_day(self, service):
        """If the date is already a banking day, return it unchanged."""
        # 2024-03-04 is Monday
        assert service.last_banking_day_on_or_before(date(2024, 3, 4)) == date(2024, 3, 4)

    def test_saturday_returns_friday(self, service):
        """Saturday returns the preceding Friday."""
        # 2024-03-02 is Saturday → 2024-03-01 is Friday
        assert service.last_banking_day_on_or_before(date(2024, 3, 2)) == date(2024, 3, 1)

    def test_sunday_returns_friday(self, service):
        """Sunday returns the preceding Friday."""
        # 2024-03-03 is Sunday → 2024-03-01 is Friday
        assert service.last_banking_day_on_or_before(date(2024, 3, 3)) == date(2024, 3, 1)

    def test_holiday_on_weekday_returns_previous_day(self, service):
        """A holiday falling on a weekday returns the previous banking day."""
        # 2024-12-25 is Wednesday (Christmas), 2024-12-24 is Tuesday
        # Dec 24 is not a nationwide holiday in Germany, so it should be a banking day
        result = service.last_banking_day_on_or_before(date(2024, 12, 25))
        assert result == date(2024, 12, 24)

    def test_consecutive_holidays_and_weekend(self, service):
        """Multiple non-banking days in a row are handled correctly."""
        # 2024-12-25 Wed (Christmas), 2024-12-26 Thu (2. Weihnachtstag)
        # Both are holidays; last banking day before them is Dec 24 (Tuesday)
        result = service.last_banking_day_on_or_before(date(2024, 12, 26))
        assert result == date(2024, 12, 24)


class TestGetEffectiveIncomeDay:
    """Tests for BankingDayService.get_effective_income_day."""

    def test_weekend_adjustment_saturday(self, service):
        """Income day on Saturday returns the preceding Friday.

        Validates: Requirement 7.1
        """
        # 2024-03-02 is Saturday, nominal_day=2
        result = service.get_effective_income_day(2, 2024, 3)
        assert result == date(2024, 3, 1)  # Friday

    def test_weekend_adjustment_sunday(self, service):
        """Income day on Sunday returns the preceding Friday.

        Validates: Requirement 7.1
        """
        # 2024-03-03 is Sunday, nominal_day=3
        result = service.get_effective_income_day(3, 2024, 3)
        assert result == date(2024, 3, 1)  # Friday

    def test_holiday_adjustment(self, service):
        """Income day on German holiday adjusts backwards.

        Validates: Requirement 7.1
        """
        # Dec 25, 2024 is Christmas (Wednesday)
        result = service.get_effective_income_day(25, 2024, 12)
        assert result == date(2024, 12, 24)  # Tuesday

    def test_month_overflow_february_non_leap(self, service):
        """Nominal day 31 in February (non-leap) uses Feb 28.

        Validates: Requirement 7.2
        """
        # 2023 is not a leap year, Feb has 28 days
        # Feb 28, 2023 is a Tuesday → banking day
        result = service.get_effective_income_day(31, 2023, 2)
        assert result == date(2023, 2, 28)

    def test_month_overflow_february_leap(self, service):
        """Nominal day 31 in February (leap year) uses Feb 29.

        Validates: Requirement 7.2
        """
        # 2024 is a leap year, Feb has 29 days
        # Feb 29, 2024 is a Thursday → banking day
        result = service.get_effective_income_day(31, 2024, 2)
        assert result == date(2024, 2, 29)

    def test_month_overflow_30_day_month(self, service):
        """Nominal day 31 in April (30 days) uses April 30.

        Validates: Requirement 7.2
        """
        # 2024-04-30 is Tuesday → banking day
        result = service.get_effective_income_day(31, 2024, 4)
        assert result == date(2024, 4, 30)

    def test_banking_day_stays(self, service):
        """Income day already on a banking day returns as-is.

        Validates: Requirement 7.1
        """
        # 2024-03-15 is Friday → banking day
        result = service.get_effective_income_day(15, 2024, 3)
        assert result == date(2024, 3, 15)

    def test_combined_weekend_plus_holiday(self, service):
        """Good Friday followed by weekend adjusts to Thursday.

        Validates: Requirement 7.1
        """
        # 2024 Good Friday is March 29 (Friday) → not banking day
        # March 28 (Thursday) is a regular weekday → banking day
        result = service.get_effective_income_day(29, 2024, 3)
        assert result == date(2024, 3, 28)

    def test_easter_monday_adjustment(self, service):
        """Easter Monday (Ostermontag) adjusts to previous Thursday.

        Validates: Requirement 7.1
        """
        # 2024 Easter Monday is April 1
        # March 31 is Sunday, March 30 is Saturday, March 29 is Good Friday
        # March 28 (Thursday) is the last banking day
        result = service.get_effective_income_day(1, 2024, 4)
        assert result == date(2024, 3, 28)

    def test_new_years_day_adjustment(self, service):
        """Jan 1 (Neujahrstag) adjusts to last banking day of previous December.

        Validates: Requirement 7.1
        """
        # 2025-01-01 is Wednesday (New Year's Day)
        # 2024-12-31 is Tuesday → check if it's a banking day
        # Dec 31 is not a German public holiday nationwide → should be banking day
        result = service.get_effective_income_day(1, 2025, 1)
        assert result == date(2024, 12, 31)
