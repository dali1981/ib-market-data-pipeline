"""
Unit tests for gap detection utilities.

Tests the business_day_range and missing_windows functions
that power gap-aware backfilling.
"""

import pytest
from datetime import date, timedelta
from dlt_ibapi.backfill.gap_detection import (
    business_day_range,
    missing_windows,
    validate_date_range,
)


class TestBusinessDayRange:
    """Tests for business_day_range function."""

    def test_single_day(self):
        """Test range with single day."""
        start = date(2024, 1, 2)  # Tuesday
        end = date(2024, 1, 2)
        result = business_day_range(start, end)
        assert result == [start]

    def test_weekdays_only(self):
        """Test that weekends are excluded."""
        # Week: Mon 1/1 to Sun 1/7
        start = date(2024, 1, 1)  # Monday
        end = date(2024, 1, 7)    # Sunday
        result = business_day_range(start, end)

        # Should have Mon-Fri (5 days), excluding Sat/Sun
        assert len(result) == 5
        assert date(2024, 1, 1) in result  # Monday
        assert date(2024, 1, 5) in result  # Friday
        assert date(2024, 1, 6) not in result  # Saturday
        assert date(2024, 1, 7) not in result  # Sunday

    def test_start_on_weekend(self):
        """Test when start date is a weekend."""
        start = date(2024, 1, 6)  # Saturday
        end = date(2024, 1, 8)    # Monday
        result = business_day_range(start, end)

        # Should only have Monday
        assert len(result) == 1
        assert date(2024, 1, 8) in result

    def test_multiple_weeks(self):
        """Test range spanning multiple weeks."""
        start = date(2024, 1, 1)  # Monday
        end = date(2024, 1, 12)   # Friday
        result = business_day_range(start, end)

        # 10 business days (2 weeks)
        assert len(result) == 10

    def test_end_before_start_raises(self):
        """Test that end < start raises ValueError."""
        start = date(2024, 1, 10)
        end = date(2024, 1, 5)

        with pytest.raises(ValueError, match="start_date must be <= end_date"):
            business_day_range(start, end)


class TestMissingWindows:
    """Tests for missing_windows function."""

    def test_no_gaps(self):
        """Test when all dates are present."""
        start = date(2024, 1, 1)
        end = date(2024, 1, 5)
        present_dates = set(business_day_range(start, end))

        gaps = missing_windows(present_dates, start, end)
        assert gaps == []

    def test_all_missing(self):
        """Test when no dates are present."""
        start = date(2024, 1, 1)  # Monday
        end = date(2024, 1, 5)    # Friday
        present_dates = set()

        gaps = missing_windows(present_dates, start, end)
        assert len(gaps) == 1
        assert gaps[0] == (start, end)

    def test_single_gap_at_start(self):
        """Test gap at the beginning."""
        start = date(2024, 1, 1)  # Monday
        end = date(2024, 1, 5)    # Friday
        present_dates = {
            date(2024, 1, 4),  # Thursday
            date(2024, 1, 5),  # Friday
        }

        gaps = missing_windows(present_dates, start, end)
        assert len(gaps) == 1
        assert gaps[0] == (date(2024, 1, 1), date(2024, 1, 3))

    def test_single_gap_at_end(self):
        """Test gap at the end."""
        start = date(2024, 1, 1)  # Monday
        end = date(2024, 1, 5)    # Friday
        present_dates = {
            date(2024, 1, 1),  # Monday
            date(2024, 1, 2),  # Tuesday
        }

        gaps = missing_windows(present_dates, start, end)
        assert len(gaps) == 1
        assert gaps[0] == (date(2024, 1, 3), date(2024, 1, 5))

    def test_single_gap_in_middle(self):
        """Test gap in the middle."""
        start = date(2024, 1, 1)  # Monday
        end = date(2024, 1, 5)    # Friday
        present_dates = {
            date(2024, 1, 1),  # Monday
            date(2024, 1, 2),  # Tuesday
            date(2024, 1, 4),  # Thursday
            date(2024, 1, 5),  # Friday
        }

        gaps = missing_windows(present_dates, start, end)
        assert len(gaps) == 1
        assert gaps[0] == (date(2024, 1, 3), date(2024, 1, 3))

    def test_multiple_gaps(self):
        """Test multiple separate gaps."""
        start = date(2024, 1, 1)  # Monday
        end = date(2024, 1, 12)   # Friday (next week)
        present_dates = {
            date(2024, 1, 2),   # Tuesday
            date(2024, 1, 3),   # Wednesday
            date(2024, 1, 8),   # Next Monday
            date(2024, 1, 9),   # Next Tuesday
        }

        gaps = missing_windows(present_dates, start, end)
        assert len(gaps) == 3
        # Gap 1: Monday (1/1)
        assert gaps[0] == (date(2024, 1, 1), date(2024, 1, 1))
        # Gap 2: Thursday-Friday (1/4-1/5)
        assert gaps[1] == (date(2024, 1, 4), date(2024, 1, 5))
        # Gap 3: Wednesday-Friday (1/10-1/12)
        assert gaps[2] == (date(2024, 1, 10), date(2024, 1, 12))

    def test_weekends_ignored(self):
        """Test that weekend gaps are not reported."""
        start = date(2024, 1, 1)  # Monday
        end = date(2024, 1, 8)    # Next Monday
        present_dates = {
            date(2024, 1, 1),  # Monday
            date(2024, 1, 2),  # Tuesday
            date(2024, 1, 3),  # Wednesday
            date(2024, 1, 4),  # Thursday
            date(2024, 1, 5),  # Friday
            date(2024, 1, 8),  # Next Monday
            # Missing: 1/6 (Sat), 1/7 (Sun) - but these are weekends
        }

        gaps = missing_windows(present_dates, start, end)
        # No gaps because weekends don't count
        assert gaps == []

    def test_empty_present_dates(self):
        """Test with empty present dates set."""
        start = date(2024, 1, 1)
        end = date(2024, 1, 5)
        present_dates = set()

        gaps = missing_windows(present_dates, start, end)
        assert len(gaps) == 1
        assert gaps[0] == (start, end)

    def test_dates_outside_range_ignored(self):
        """Test that dates outside range are ignored."""
        start = date(2024, 1, 8)
        end = date(2024, 1, 12)
        present_dates = {
            date(2024, 1, 1),   # Before range
            date(2024, 1, 8),   # In range
            date(2024, 1, 9),   # In range
            date(2024, 1, 20),  # After range
        }

        gaps = missing_windows(present_dates, start, end)
        assert len(gaps) == 1
        # Gap: 1/10-1/12 (missing from range)
        assert gaps[0] == (date(2024, 1, 10), date(2024, 1, 12))


class TestValidateDateRange:
    """Tests for validate_date_range function."""

    def test_valid_range(self):
        """Test valid date range."""
        start = date(2024, 1, 1)
        end = date(2024, 12, 31)
        # Should not raise
        validate_date_range(start, end)

    def test_same_date(self):
        """Test when start equals end."""
        start = date(2024, 1, 1)
        end = date(2024, 1, 1)
        # Should not raise
        validate_date_range(start, end)

    def test_end_before_start(self):
        """Test that end < start raises ValueError."""
        start = date(2024, 12, 31)
        end = date(2024, 1, 1)

        with pytest.raises(ValueError, match="start_date must be <= end_date"):
            validate_date_range(start, end)


class TestGapDetectionIntegration:
    """Integration tests combining business_day_range and missing_windows."""

    def test_realistic_scenario(self):
        """Test realistic backfill scenario."""
        # Scenario: We want to backfill 2 weeks of data
        # We already have some data with gaps
        start = date(2024, 1, 1)  # Monday
        end = date(2024, 1, 12)   # Friday (2 weeks)

        # Simulate existing data (partial coverage)
        existing_data = {
            date(2024, 1, 1),  # Monday week 1
            date(2024, 1, 2),  # Tuesday week 1
            date(2024, 1, 3),  # Wednesday week 1
            # Missing: 1/4, 1/5 (Thu, Fri week 1)
            date(2024, 1, 8),  # Monday week 2
            # Missing: 1/9, 1/10, 1/11, 1/12 (Tue-Fri week 2)
        }

        gaps = missing_windows(existing_data, start, end)

        # Should identify 2 gaps
        assert len(gaps) == 2
        assert gaps[0] == (date(2024, 1, 4), date(2024, 1, 5))
        assert gaps[1] == (date(2024, 1, 9), date(2024, 1, 12))

    def test_idempotent_backfill(self):
        """Test that complete coverage results in no gaps."""
        start = date(2024, 1, 1)
        end = date(2024, 1, 12)

        # Generate all business days
        all_business_days = set(business_day_range(start, end))

        # No gaps when all days present
        gaps = missing_windows(all_business_days, start, end)
        assert gaps == []

    def test_single_day_gap(self):
        """Test detection of single missing day."""
        start = date(2024, 1, 1)  # Monday
        end = date(2024, 1, 5)    # Friday

        # Missing only Wednesday
        present = {
            date(2024, 1, 1),  # Monday
            date(2024, 1, 2),  # Tuesday
            # Missing 1/3 (Wednesday)
            date(2024, 1, 4),  # Thursday
            date(2024, 1, 5),  # Friday
        }

        gaps = missing_windows(present, start, end)
        assert len(gaps) == 1
        assert gaps[0] == (date(2024, 1, 3), date(2024, 1, 3))


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_leap_year_february(self):
        """Test handling of leap year February."""
        start = date(2024, 2, 26)  # Monday
        end = date(2024, 2, 29)    # Thursday (leap day)

        business_days = business_day_range(start, end)
        # Should have Mon-Thu (4 days)
        assert len(business_days) == 4
        assert date(2024, 2, 29) in business_days

    def test_year_boundary(self):
        """Test range crossing year boundary."""
        start = date(2023, 12, 28)  # Thursday
        end = date(2024, 1, 3)      # Wednesday

        business_days = business_day_range(start, end)
        # Thu 12/28, Fri 12/29, Mon 1/1, Tue 1/2, Wed 1/3 = 5 days
        assert len(business_days) == 5
        assert date(2023, 12, 30) not in business_days  # Saturday
        assert date(2023, 12, 31) not in business_days  # Sunday

    def test_very_long_range(self):
        """Test with a year-long range."""
        start = date(2024, 1, 1)
        end = date(2024, 12, 31)

        business_days = business_day_range(start, end)
        # 2024 is leap year, expect ~261 business days
        assert 260 <= len(business_days) <= 262

    def test_present_dates_not_modified(self):
        """Test that present_dates set is not modified."""
        start = date(2024, 1, 1)
        end = date(2024, 1, 5)
        present_dates = {date(2024, 1, 1), date(2024, 1, 2)}
        original = present_dates.copy()

        missing_windows(present_dates, start, end)

        # Original set should be unchanged
        assert present_dates == original
