"""
Tests for market calendar service.

Verifies that the MarketCalendar correctly identifies trading days,
excludes weekends and holidays, and handles various edge cases.
"""

import pytest
from datetime import date, timedelta

from dlt_ibapi.backfill.market_calendar import MarketCalendar, get_market_calendar


class TestMarketCalendar:
    """Test suite for MarketCalendar class."""

    def test_init_valid_exchange(self):
        """Test initialization with valid exchange code."""
        cal = MarketCalendar("NYSE")
        assert cal.exchange == "NYSE"
        assert cal.calendar is not None

    def test_init_invalid_exchange(self):
        """Test initialization with invalid exchange code raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported exchange"):
            MarketCalendar("INVALID_EXCHANGE")

    def test_get_available_exchanges(self):
        """Test that get_available_exchanges returns a list of exchange codes."""
        exchanges = MarketCalendar.get_available_exchanges()
        assert isinstance(exchanges, list)
        assert len(exchanges) > 0
        assert "NYSE" in exchanges
        assert "NASDAQ" in exchanges

    def test_get_trading_days_excludes_weekends(self):
        """Test that get_trading_days excludes weekends."""
        cal = MarketCalendar("NYSE")

        # Week of Oct 14-20, 2025 (has weekend Oct 18-19)
        trading_days = cal.get_trading_days(
            date(2025, 10, 14),
            date(2025, 10, 20)
        )

        # Should have 5 weekdays
        assert len(trading_days) == 5

        # Verify no Saturdays or Sundays
        for day in trading_days:
            assert day.weekday() < 5  # Monday=0, Friday=4

    def test_get_trading_days_excludes_independence_day(self):
        """Test that July 4th (Independence Day) is excluded."""
        cal = MarketCalendar("NYSE")

        # July 1-10, 2025 (July 4th is Friday)
        trading_days = cal.get_trading_days(
            date(2025, 7, 1),
            date(2025, 7, 10)
        )

        # July 4th should not be in trading days
        assert date(2025, 7, 4) not in trading_days

        # July 3rd should be a trading day
        assert date(2025, 7, 3) in trading_days

    def test_get_trading_days_excludes_christmas(self):
        """Test that Christmas is excluded."""
        cal = MarketCalendar("NYSE")

        # Dec 22-26, 2025 (Christmas is Thursday, Dec 25)
        trading_days = cal.get_trading_days(
            date(2025, 12, 22),
            date(2025, 12, 26)
        )

        # Dec 25 should not be in trading days
        assert date(2025, 12, 25) not in trading_days

    def test_get_trading_days_new_years(self):
        """Test that New Year's Day is excluded."""
        cal = MarketCalendar("NYSE")

        # Dec 30, 2024 - Jan 3, 2025 (Jan 1 is Wednesday)
        trading_days = cal.get_trading_days(
            date(2024, 12, 30),
            date(2025, 1, 3)
        )

        # Jan 1, 2025 should not be in trading days
        assert date(2025, 1, 1) not in trading_days

    def test_is_trading_day_weekday(self):
        """Test is_trading_day returns True for normal weekday."""
        cal = MarketCalendar("NYSE")

        # Oct 15, 2025 is a Wednesday
        assert cal.is_trading_day(date(2025, 10, 15)) is True

    def test_is_trading_day_weekend(self):
        """Test is_trading_day returns False for weekend."""
        cal = MarketCalendar("NYSE")

        # Oct 18, 2025 is a Saturday
        assert cal.is_trading_day(date(2025, 10, 18)) is False

        # Oct 19, 2025 is a Sunday
        assert cal.is_trading_day(date(2025, 10, 19)) is False

    def test_is_trading_day_holiday(self):
        """Test is_trading_day returns False for holiday."""
        cal = MarketCalendar("NYSE")

        # July 4, 2025 is Independence Day (Friday)
        assert cal.is_trading_day(date(2025, 7, 4)) is False

    def test_get_next_trading_day_simple(self):
        """Test get_next_trading_day for simple case."""
        cal = MarketCalendar("NYSE")

        # Wednesday -> Thursday
        next_day = cal.get_next_trading_day(date(2025, 10, 15))
        assert next_day == date(2025, 10, 16)

    def test_get_next_trading_day_skip_weekend(self):
        """Test get_next_trading_day skips weekend."""
        cal = MarketCalendar("NYSE")

        # Friday -> Monday (skip weekend)
        next_day = cal.get_next_trading_day(date(2025, 10, 17))
        assert next_day == date(2025, 10, 20)

    def test_get_next_trading_day_skip_holiday(self):
        """Test get_next_trading_day skips holiday."""
        cal = MarketCalendar("NYSE")

        # Thursday before July 4 -> Monday after (skip Friday holiday + weekend)
        next_day = cal.get_next_trading_day(date(2025, 7, 3))
        assert next_day == date(2025, 7, 7)

    def test_get_previous_trading_day_simple(self):
        """Test get_previous_trading_day for simple case."""
        cal = MarketCalendar("NYSE")

        # Thursday -> Wednesday
        prev_day = cal.get_previous_trading_day(date(2025, 10, 16))
        assert prev_day == date(2025, 10, 15)

    def test_get_previous_trading_day_skip_weekend(self):
        """Test get_previous_trading_day skips weekend."""
        cal = MarketCalendar("NYSE")

        # Monday -> Friday (skip weekend)
        prev_day = cal.get_previous_trading_day(date(2025, 10, 20))
        assert prev_day == date(2025, 10, 17)

    def test_count_trading_days(self):
        """Test count_trading_days returns correct count."""
        cal = MarketCalendar("NYSE")

        # Oct 14-20, 2025 (1 week with weekend)
        count = cal.count_trading_days(
            date(2025, 10, 14),
            date(2025, 10, 20)
        )

        # Should be 5 trading days
        assert count == 5

    def test_get_market_holidays_returns_list(self):
        """Test get_market_holidays returns a list for given year."""
        cal = MarketCalendar("NYSE")

        holidays = cal.get_market_holidays(2025)

        assert isinstance(holidays, list)
        assert len(holidays) > 0

        # Verify Independence Day is in the list
        assert date(2025, 7, 4) in holidays

        # Verify Christmas is in the list
        assert date(2025, 12, 25) in holidays

    def test_get_cached_calendar(self):
        """Test that get_market_calendar returns cached instance."""
        cal1 = get_market_calendar("NYSE")
        cal2 = get_market_calendar("NYSE")

        # Should be the same instance (cached)
        assert cal1 is cal2

    def test_different_exchanges_different_instances(self):
        """Test that different exchanges return different instances."""
        cal_nyse = get_market_calendar("NYSE")
        cal_nasdaq = get_market_calendar("NASDAQ")

        # Should be different instances
        assert cal_nyse is not cal_nasdaq
        assert cal_nyse.exchange == "NYSE"
        assert cal_nasdaq.exchange == "NASDAQ"

    def test_repr(self):
        """Test __repr__ returns meaningful string."""
        cal = MarketCalendar("NYSE")
        repr_str = repr(cal)

        assert "MarketCalendar" in repr_str
        assert "NYSE" in repr_str

    def test_empty_date_range(self):
        """Test get_trading_days with empty date range."""
        cal = MarketCalendar("NYSE")

        # Same day
        trading_days = cal.get_trading_days(
            date(2025, 10, 15),
            date(2025, 10, 15)
        )

        # Should have exactly 1 day if it's a trading day
        assert len(trading_days) == 1
        assert trading_days[0] == date(2025, 10, 15)

    def test_weekend_only_range(self):
        """Test get_trading_days with weekend-only range."""
        cal = MarketCalendar("NYSE")

        # Saturday-Sunday only
        trading_days = cal.get_trading_days(
            date(2025, 10, 18),
            date(2025, 10, 19)
        )

        # Should have 0 trading days
        assert len(trading_days) == 0

    def test_year_boundary(self):
        """Test get_trading_days across year boundary."""
        cal = MarketCalendar("NYSE")

        # Dec 29, 2024 (Mon) - Jan 3, 2025 (Fri)
        # Excludes: Dec 31 (Tue, maybe early close), Jan 1 (Wed, holiday)
        trading_days = cal.get_trading_days(
            date(2024, 12, 29),
            date(2025, 1, 3)
        )

        # Verify Jan 1 is excluded
        assert date(2025, 1, 1) not in trading_days

        # All should be valid dates
        for day in trading_days:
            assert isinstance(day, date)
