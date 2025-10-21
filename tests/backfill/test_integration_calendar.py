"""
Integration test to verify market calendar works with backfill.

This test demonstrates that the backfill gap detection now correctly
excludes market holidays and doesn't create false gaps.
"""

import pytest
from datetime import date

from dlt_ibapi.backfill.gap_detection import missing_windows, trading_day_range
from dlt_ibapi.backfill.market_calendar import get_market_calendar


class TestBackfillIntegration:
    """Integration tests for backfill with market calendar."""

    def test_july_2025_independence_day_scenario(self):
        """
        Test the original problem: backfill creating gaps for Independence Day.

        Before fix: Gap detection would try to fetch July 4th data
        After fix: Gap detection skips July 4th (market holiday)
        """
        # Simulate having data for all trading days in July 1-10
        # except we're missing July 7-8 (Mon-Tue after the long weekend)
        all_trading_days = trading_day_range(date(2025, 7, 1), date(2025, 7, 10))

        # Remove July 7-8 (actual gap)
        present_dates = set(all_trading_days)
        present_dates.discard(date(2025, 7, 7))
        present_dates.discard(date(2025, 7, 8))

        # Find gaps
        gaps = missing_windows(
            present_dates=present_dates,
            start=date(2025, 7, 1),
            end=date(2025, 7, 10),
            exchange="NYSE"
        )

        # Should find gap for July 7-8 only
        assert len(gaps) == 1
        assert gaps[0] == (date(2025, 7, 7), date(2025, 7, 8))

        # Verify July 4 is NOT in any gap (it's a holiday)
        for gap_start, gap_end in gaps:
            gap_days = trading_day_range(gap_start, gap_end)
            assert date(2025, 7, 4) not in gap_days

    def test_september_2025_original_error_case(self):
        """
        Test the actual error case from the user:
        Sept 22-26, 2025 showing as a gap but getting IB error 2174.

        The issue was that this range likely contained holidays/weekends
        that gap detection didn't account for.
        """
        # Get actual trading days in Sept 22-26 range
        trading_days_in_range = trading_day_range(
            date(2025, 9, 22),
            date(2025, 9, 26),
            exchange="NYSE"
        )

        # If this range has fewer than 5 days, it contains non-trading days
        # (weekends or holidays) which explains the IB error
        print(f"\nTrading days in Sept 22-26, 2025: {len(trading_days_in_range)}")
        print(f"Actual days: {trading_days_in_range}")

        # Sept 22-26, 2025 breakdown:
        # Sept 22 (Mon), 23 (Tue), 24 (Wed), 25 (Thu), 26 (Fri)
        # Should be 5 trading days unless there's a holiday

        # Now simulate backfill scenario: we have data for Sept 1-21
        all_sept = trading_day_range(date(2025, 9, 1), date(2025, 9, 30))
        present_dates = {d for d in all_sept if d < date(2025, 9, 22)}

        # Find gaps for entire month
        gaps = missing_windows(
            present_dates=present_dates,
            start=date(2025, 9, 1),
            end=date(2025, 9, 30),
            exchange="NYSE"
        )

        # Should find gap starting at Sept 22
        assert len(gaps) >= 1

        # First gap should be Sept 22 onwards
        first_gap_start = gaps[0][0]
        assert first_gap_start >= date(2025, 9, 22)

        # Verify gap only contains actual trading days
        for gap_start, gap_end in gaps:
            gap_days = trading_day_range(gap_start, gap_end)
            for day in gap_days:
                # Verify it's a weekday
                assert day.weekday() < 5
                # Verify it's a trading day
                assert day in all_sept

    def test_holiday_week_no_false_gaps(self):
        """
        Test that having complete data for a holiday week shows no gaps.

        This verifies the fix: holidays should NOT create gaps.
        """
        # Christmas week 2025: Dec 22-26
        # Dec 25 (Thu) is Christmas - market closed

        # Get all trading days in this week
        trading_days = trading_day_range(
            date(2025, 12, 22),
            date(2025, 12, 26),
            exchange="NYSE"
        )

        # Simulate having data for all trading days
        present_dates = set(trading_days)

        # Find gaps
        gaps = missing_windows(
            present_dates=present_dates,
            start=date(2025, 12, 22),
            end=date(2025, 12, 26),
            exchange="NYSE"
        )

        # Should have NO gaps - Christmas is not a gap, it's a holiday
        assert gaps == []

    def test_weekend_no_false_gaps(self):
        """
        Test that having complete weekday data shows no gaps despite weekend.

        This verifies: weekends should NOT create gaps.
        """
        # Oct 17-20, 2025 (Fri-Mon, includes weekend)
        trading_days = trading_day_range(date(2025, 10, 17), date(2025, 10, 20))

        # Should only include Fri and Mon (weekend excluded)
        assert len(trading_days) == 2
        assert date(2025, 10, 17) in trading_days  # Friday
        assert date(2025, 10, 20) in trading_days  # Monday
        assert date(2025, 10, 18) not in trading_days  # Saturday
        assert date(2025, 10, 19) not in trading_days  # Sunday

        # Simulate having both trading days
        present_dates = set(trading_days)

        # Find gaps
        gaps = missing_windows(
            present_dates=present_dates,
            start=date(2025, 10, 17),
            end=date(2025, 10, 20),
            exchange="NYSE"
        )

        # Should have NO gaps - weekend is not a gap
        assert gaps == []

    def test_compare_exchanges_nyse_vs_nasdaq(self):
        """
        Test that different exchanges can have different trading days.

        In practice, NYSE and NASDAQ have the same US holidays,
        but this test verifies the exchange parameter works.
        """
        # Get NYSE trading days
        nyse_days = trading_day_range(
            date(2025, 7, 1),
            date(2025, 7, 10),
            exchange="NYSE"
        )

        # Get NASDAQ trading days
        nasdaq_days = trading_day_range(
            date(2025, 7, 1),
            date(2025, 7, 10),
            exchange="NASDAQ"
        )

        # For US markets, they should match
        assert set(nyse_days) == set(nasdaq_days)

        # Both should exclude July 4th
        assert date(2025, 7, 4) not in nyse_days
        assert date(2025, 7, 4) not in nasdaq_days

    def test_market_calendar_caching(self):
        """Test that market calendar instances are cached for performance."""
        from dlt_ibapi.backfill.market_calendar import get_market_calendar

        # Get same calendar twice
        cal1 = get_market_calendar("NYSE")
        cal2 = get_market_calendar("NYSE")

        # Should be same instance (cached)
        assert cal1 is cal2

    def test_full_year_2025_holidays(self):
        """
        Test that all major US holidays in 2025 are correctly identified.
        """
        cal = get_market_calendar("NYSE")

        # Get all 2025 holidays
        holidays = cal.get_market_holidays(2025)

        # Major US market holidays
        expected_holidays = [
            date(2025, 1, 1),   # New Year's Day
            # MLK Day (3rd Monday of Jan)
            # Presidents Day (3rd Monday of Feb)
            # Good Friday (varies)
            # Memorial Day (last Monday of May)
            date(2025, 7, 4),   # Independence Day
            # Labor Day (1st Monday of Sept)
            # Thanksgiving (4th Thursday of Nov)
            date(2025, 12, 25), # Christmas
        ]

        # Verify key holidays are in the list
        for holiday in expected_holidays:
            if holiday.weekday() < 5:  # Only check if it falls on a weekday
                assert holiday in holidays, f"{holiday} should be a market holiday"

        print(f"\n2025 NYSE holidays ({len(holidays)} total):")
        for holiday in sorted(holidays):
            print(f"  - {holiday.strftime('%Y-%m-%d %A')}")
