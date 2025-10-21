"""
Tests for gap detection with market calendar integration.

Verifies that missing_windows correctly uses market calendars
to exclude weekends and holidays when identifying gaps.
"""

import pytest
from datetime import date

from dlt_ibapi.backfill.gap_detection import (
    trading_day_range,
    missing_windows,
    business_day_range,
)


class TestTradingDayRange:
    """Test suite for trading_day_range function."""

    def test_excludes_weekends(self):
        """Test that trading_day_range excludes weekends."""
        # Oct 14-20, 2025 (includes weekend Oct 18-19)
        days = trading_day_range(date(2025, 10, 14), date(2025, 10, 20))

        assert len(days) == 5
        assert date(2025, 10, 18) not in days  # Saturday
        assert date(2025, 10, 19) not in days  # Sunday

    def test_excludes_independence_day(self):
        """Test that trading_day_range excludes Independence Day."""
        # July 1-10, 2025 (July 4 is Friday)
        days = trading_day_range(date(2025, 7, 1), date(2025, 7, 10))

        assert date(2025, 7, 4) not in days  # Independence Day
        assert date(2025, 7, 3) in days  # Day before

    def test_excludes_christmas(self):
        """Test that trading_day_range excludes Christmas."""
        # Dec 22-26, 2025
        days = trading_day_range(date(2025, 12, 22), date(2025, 12, 26))

        assert date(2025, 12, 25) not in days  # Christmas

    def test_different_exchanges(self):
        """Test that different exchanges may have different trading days."""
        # Same date range, different exchanges
        nyse_days = trading_day_range(date(2025, 1, 1), date(2025, 1, 10), "NYSE")
        nasdaq_days = trading_day_range(date(2025, 1, 1), date(2025, 1, 10), "NASDAQ")

        # Both should exclude New Year's Day
        assert date(2025, 1, 1) not in nyse_days
        assert date(2025, 1, 1) not in nasdaq_days

        # They should have similar counts (US markets have same holidays)
        assert len(nyse_days) == len(nasdaq_days)


class TestMissingWindowsWithCalendar:
    """Test suite for missing_windows with market calendar."""

    def test_no_gaps_complete_data(self):
        """Test missing_windows returns empty list when data is complete."""
        # All trading days in range
        present_dates = set(trading_day_range(date(2025, 10, 14), date(2025, 10, 20)))

        gaps = missing_windows(present_dates, date(2025, 10, 14), date(2025, 10, 20))

        assert gaps == []

    def test_single_missing_day(self):
        """Test missing_windows identifies single missing trading day."""
        # Oct 14-20, 2025, missing Oct 16 (Thursday)
        all_days = trading_day_range(date(2025, 10, 14), date(2025, 10, 20))
        present_dates = set(all_days)
        present_dates.remove(date(2025, 10, 16))

        gaps = missing_windows(present_dates, date(2025, 10, 14), date(2025, 10, 20))

        assert len(gaps) == 1
        assert gaps[0] == (date(2025, 10, 16), date(2025, 10, 16))

    def test_contiguous_gap(self):
        """Test missing_windows identifies contiguous gap."""
        # Oct 14-20, 2025, missing Oct 15-16 (Wed-Thu)
        all_days = trading_day_range(date(2025, 10, 14), date(2025, 10, 20))
        present_dates = set(all_days)
        present_dates.remove(date(2025, 10, 15))
        present_dates.remove(date(2025, 10, 16))

        gaps = missing_windows(present_dates, date(2025, 10, 14), date(2025, 10, 20))

        assert len(gaps) == 1
        assert gaps[0] == (date(2025, 10, 15), date(2025, 10, 16))

    def test_multiple_gaps(self):
        """Test missing_windows identifies multiple separate gaps."""
        # Oct 14-20, 2025, missing Oct 14 and Oct 16-17
        all_days = trading_day_range(date(2025, 10, 14), date(2025, 10, 20))
        present_dates = set(all_days)
        present_dates.remove(date(2025, 10, 14))  # Tuesday
        present_dates.remove(date(2025, 10, 16))  # Thursday
        present_dates.remove(date(2025, 10, 17))  # Friday

        gaps = missing_windows(present_dates, date(2025, 10, 14), date(2025, 10, 20))

        assert len(gaps) == 2
        assert (date(2025, 10, 14), date(2025, 10, 14)) in gaps
        assert (date(2025, 10, 16), date(2025, 10, 17)) in gaps

    def test_does_not_create_gap_for_weekend(self):
        """Test that weekends do NOT create gaps."""
        # Oct 14-20, 2025, have all weekdays
        all_days = trading_day_range(date(2025, 10, 14), date(2025, 10, 20))
        present_dates = set(all_days)

        gaps = missing_windows(present_dates, date(2025, 10, 14), date(2025, 10, 20))

        # No gaps - weekend is not considered missing data
        assert gaps == []

    def test_does_not_create_gap_for_holiday(self):
        """Test that holidays do NOT create gaps."""
        # July 1-10, 2025 (July 4 is Independence Day)
        # Have all trading days (which excludes July 4)
        all_days = trading_day_range(date(2025, 7, 1), date(2025, 7, 10))
        present_dates = set(all_days)

        gaps = missing_windows(present_dates, date(2025, 7, 1), date(2025, 7, 10))

        # No gaps - July 4 is a holiday, not missing data
        assert gaps == []

    def test_gap_spanning_weekend(self):
        """Test gap that spans across a weekend."""
        # Oct 14-20, 2025, missing Oct 17 (Fri) and Oct 20 (Mon)
        all_days = trading_day_range(date(2025, 10, 14), date(2025, 10, 20))
        present_dates = set(all_days)
        present_dates.remove(date(2025, 10, 17))  # Friday
        present_dates.remove(date(2025, 10, 20))  # Monday

        gaps = missing_windows(present_dates, date(2025, 10, 14), date(2025, 10, 20))

        # Should be two separate gaps (weekend breaks contiguity)
        assert len(gaps) == 2
        assert (date(2025, 10, 17), date(2025, 10, 17)) in gaps
        assert (date(2025, 10, 20), date(2025, 10, 20)) in gaps

    def test_empty_present_dates(self):
        """Test missing_windows when no data is present."""
        # No existing data
        present_dates = set()

        gaps = missing_windows(present_dates, date(2025, 10, 14), date(2025, 10, 20))

        # Oct 14-20 has a weekend (Sat 18, Sun 19), so gaps are split:
        # Gap 1: Oct 14-17 (Tue-Fri)
        # Gap 2: Oct 20 (Mon)
        assert len(gaps) == 2
        assert gaps[0] == (date(2025, 10, 14), date(2025, 10, 17))
        assert gaps[1] == (date(2025, 10, 20), date(2025, 10, 20))

    def test_comparison_with_business_day_range(self):
        """Test that trading_day_range is more accurate than business_day_range."""
        # July 1-10, 2025 (includes July 4 holiday)

        # Old way (business days only - includes holidays)
        business_days = business_day_range(date(2025, 7, 1), date(2025, 7, 10))

        # New way (trading days - excludes holidays)
        trading_days = trading_day_range(date(2025, 7, 1), date(2025, 7, 10))

        # Trading days should have fewer days (excludes July 4)
        assert len(trading_days) < len(business_days)

        # Business days includes July 4 (it's a Friday)
        assert date(2025, 7, 4) in business_days

        # Trading days excludes July 4 (it's a holiday)
        assert date(2025, 7, 4) not in trading_days


class TestRealWorldScenarios:
    """Test real-world backfill scenarios."""

    def test_september_2025_labor_day(self):
        """Test gap detection for September 2025 (includes Labor Day)."""
        # Sept 1-10, 2025 (Labor Day is Sept 1, Monday)

        # Get actual trading days
        trading_days = trading_day_range(date(2025, 9, 1), date(2025, 9, 10))

        # Labor Day should be excluded
        assert date(2025, 9, 1) not in trading_days

        # Sept 2 (Tuesday) should be first trading day
        assert date(2025, 9, 2) in trading_days

        # Simulate having some data but missing Sept 22-26 range
        # This was the actual error case from the user
        all_sept_days = trading_day_range(date(2025, 9, 1), date(2025, 9, 30))
        present_dates = set(all_sept_days)

        # Remove Sept 22-26 trading days
        gap_days = trading_day_range(date(2025, 9, 22), date(2025, 9, 26))
        for day in gap_days:
            present_dates.discard(day)

        # Find gaps
        gaps = missing_windows(present_dates, date(2025, 9, 1), date(2025, 9, 30))

        # Should identify the actual gap
        assert len(gaps) >= 1

        # Gap should be in Sept 22-26 range
        for gap_start, gap_end in gaps:
            if gap_start >= date(2025, 9, 22) and gap_end <= date(2025, 9, 26):
                # Found the gap - should only include trading days
                gap_span = trading_day_range(gap_start, gap_end)
                assert all(day.weekday() < 5 for day in gap_span)  # No weekends
                break
        else:
            pytest.fail("Expected gap in Sept 22-26 not found")

    def test_thanksgiving_week_2025(self):
        """Test gap detection for Thanksgiving week 2025."""
        # Nov 24-28, 2025 (Thanksgiving is Nov 27, Thursday)

        trading_days = trading_day_range(date(2025, 11, 24), date(2025, 11, 28))

        # Nov 27 (Thanksgiving) should be excluded
        assert date(2025, 11, 27) not in trading_days

        # Nov 28 (Friday after Thanksgiving) might be early close but still trading
        # (This depends on the exchange calendar rules)

    def test_christmas_week_2025(self):
        """Test gap detection for Christmas week 2025."""
        # Dec 22-26, 2025 (Christmas is Dec 25, Thursday)

        trading_days = trading_day_range(date(2025, 12, 22), date(2025, 12, 26))

        # Dec 25 (Christmas) should be excluded
        assert date(2025, 12, 25) not in trading_days

        # Dec 24 (Wed) and Dec 26 (Fri) may or may not be trading days
        # depending on how the holiday falls
