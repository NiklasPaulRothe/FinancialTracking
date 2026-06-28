"""Banking day service for Haushaltsbuch.

Implements effective income day calculation adjusted for German weekends
and public holidays.

Validates: Requirements 7.1, 7.2, 7.3
"""

import calendar
from datetime import date, timedelta

import holidays


class BankingDayService:
    """Service for computing banking-day-adjusted income dates.

    Uses the ``holidays`` library with country code DE (Germany) to determine
    nationwide public holidays and adjusts income days that fall on weekends
    or holidays to the last banking day on or before the nominal date.
    """

    def __init__(self) -> None:
        self._holiday_cache: dict[int, holidays.Germany] = {}

    def _get_holidays_for_year(self, year: int) -> holidays.Germany:
        """Return (cached) German holiday calendar for a given year."""
        if year not in self._holiday_cache:
            self._holiday_cache[year] = holidays.Germany(years=year)
        return self._holiday_cache[year]

    def is_banking_day(self, d: date) -> bool:
        """Check if a date is a German banking day.

        A banking day is a weekday (Monday–Friday) that is not a German
        public holiday.

        Args:
            d: The date to check.

        Returns:
            True if the date is a banking day, False otherwise.
        """
        # Saturday = 5, Sunday = 6
        if d.weekday() >= 5:
            return False
        german_holidays = self._get_holidays_for_year(d.year)
        return d not in german_holidays

    def last_banking_day_on_or_before(self, d: date) -> date:
        """Find the last banking day on or before the given date.

        Walks backwards from the given date until a banking day is found.

        Args:
            d: The starting date.

        Returns:
            The last banking day <= d.
        """
        while not self.is_banking_day(d):
            d -= timedelta(days=1)
        return d

    def get_effective_income_day(self, nominal_day: int, year: int, month: int) -> date:
        """Compute the effective income day for a given month/year.

        Validates: Requirements 7.1, 7.2

        1. Clamp nominal_day to the last day of the month (Req 7.2).
        2. Adjust backwards to the last banking day on or before that date (Req 7.1).

        Args:
            nominal_day: The configured income day (1–31).
            year: The calendar year.
            month: The calendar month (1–12).

        Returns:
            The effective income date (a banking day).
        """
        # Clamp nominal day to last day of month
        last_day_of_month = calendar.monthrange(year, month)[1]
        actual_day = min(nominal_day, last_day_of_month)

        nominal_date = date(year, month, actual_day)
        return self.last_banking_day_on_or_before(nominal_date)
