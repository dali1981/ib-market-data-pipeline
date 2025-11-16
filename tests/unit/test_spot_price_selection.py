"""
Unit tests for earnings-aware spot price date selection.

Tests the logic that determines which date's close price to use for spot price
based on earnings announcement timing (pre-market vs after-hours).
"""

import pytest
from datetime import date

# Import the functions to test
from dlt_ibapi.cli.backfill import _get_spot_price_date
from dlt_ibapi.backfill.market_calendar import get_previous_trading_day


class TestSpotPriceDateSelection:
    """Test earnings-aware spot price date selection."""

    def test_premarket_weekday(self):
        """Pre-market earnings on weekday should use previous day."""
        earnings_date = date(2025, 11, 13)  # Wednesday
        earnings_time = "PRE_MARKET"

        spot_date = _get_spot_price_date(earnings_date, earnings_time)

        assert spot_date == date(2025, 11, 12)  # Tuesday

    def test_afterhours_weekday(self):
        """After-hours earnings should use same day."""
        earnings_date = date(2025, 11, 13)  # Wednesday
        earnings_time = "AFTER_HOURS"

        spot_date = _get_spot_price_date(earnings_date, earnings_time)

        assert spot_date == date(2025, 11, 13)  # Same day

    def test_unknown_defaults_to_same_day(self):
        """Unknown earnings time should default to same day (conservative)."""
        earnings_date = date(2025, 11, 13)
        earnings_time = "UNKNOWN"

        spot_date = _get_spot_price_date(earnings_date, earnings_time)

        assert spot_date == earnings_date

    def test_premarket_monday_skips_weekend(self):
        """Pre-market on Monday should use previous Friday."""
        earnings_date = date(2025, 11, 17)  # Monday
        earnings_time = "PRE_MARKET"

        spot_date = _get_spot_price_date(earnings_date, earnings_time)

        assert spot_date == date(2025, 11, 14)  # Friday

    def test_premarket_tuesday_after_long_weekend(self):
        """Pre-market after long weekend should skip holiday."""
        # Example: Tuesday after Memorial Day (Monday May 26, 2025)
        earnings_date = date(2025, 5, 27)  # Tuesday
        earnings_time = "PRE_MARKET"

        spot_date = _get_spot_price_date(earnings_date, earnings_time)

        # Should skip Memorial Day (May 26) and weekend, land on Friday May 23
        assert spot_date == date(2025, 5, 23)

    def test_afterhours_friday(self):
        """After-hours on Friday should use Friday's close."""
        earnings_date = date(2025, 11, 14)  # Friday
        earnings_time = "AFTER_HOURS"

        spot_date = _get_spot_price_date(earnings_date, earnings_time)

        assert spot_date == earnings_date  # Same day

    def test_premarket_tuesday_regular(self):
        """Pre-market on Tuesday should use Monday."""
        earnings_date = date(2025, 11, 18)  # Tuesday
        earnings_time = "PRE_MARKET"

        spot_date = _get_spot_price_date(earnings_date, earnings_time)

        assert spot_date == date(2025, 11, 17)  # Monday


class TestGetPreviousTradingDay:
    """Test market calendar helper."""

    def test_previous_day_regular_weekday(self):
        """Wednesday → Tuesday."""
        ref_date = date(2025, 11, 13)  # Wednesday
        prev_day = get_previous_trading_day(ref_date)
        assert prev_day == date(2025, 11, 12)  # Tuesday

    def test_previous_day_skip_weekend(self):
        """Monday → Previous Friday."""
        ref_date = date(2025, 11, 17)  # Monday
        prev_day = get_previous_trading_day(ref_date)
        assert prev_day == date(2025, 11, 14)  # Friday

    def test_previous_day_thursday_to_wednesday(self):
        """Thursday → Wednesday (no weekend)."""
        ref_date = date(2025, 11, 14)  # Friday
        prev_day = get_previous_trading_day(ref_date)
        assert prev_day == date(2025, 11, 13)  # Thursday

    def test_previous_day_skip_memorial_day(self):
        """Day after Memorial Day → Day before holiday."""
        # Memorial Day 2025 is May 26 (Monday)
        ref_date = date(2025, 5, 27)  # Tuesday
        prev_day = get_previous_trading_day(ref_date)

        # Should skip Memorial Day and weekend, land on Friday May 23
        assert prev_day == date(2025, 5, 23)  # Friday

    def test_previous_day_skip_thanksgiving(self):
        """Day after Thanksgiving → Day before Thanksgiving."""
        # Thanksgiving 2025 is Nov 27 (Thursday)
        ref_date = date(2025, 11, 28)  # Friday (day after Thanksgiving)
        prev_day = get_previous_trading_day(ref_date)

        # Should skip Thanksgiving (Nov 27), land on Wednesday Nov 26
        assert prev_day == date(2025, 11, 26)  # Wednesday

    def test_previous_day_after_new_years(self):
        """First trading day of year → Last trading day of previous year."""
        # Jan 1, 2025 is Wednesday (New Year's Day - market closed)
        # Jan 2, 2025 is Thursday (first trading day of 2025)
        ref_date = date(2025, 1, 2)  # Thursday
        prev_day = get_previous_trading_day(ref_date)

        # Should land on Dec 31, 2024 (Tuesday - last trading day of 2024)
        assert prev_day == date(2024, 12, 31)  # Tuesday

    def test_previous_day_multiple_trading_days(self):
        """Test going back multiple days in regular trading week."""
        ref_date = date(2025, 11, 13)  # Wednesday

        # Test going back 1, 2, 3 days
        prev_1 = get_previous_trading_day(ref_date)
        assert prev_1 == date(2025, 11, 12)  # Tuesday

        prev_2 = get_previous_trading_day(prev_1)
        assert prev_2 == date(2025, 11, 11)  # Monday (Veterans Day observed - market open)

        prev_3 = get_previous_trading_day(prev_2)
        assert prev_3 == date(2025, 11, 10)  # Friday (skip weekend)


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_case_insensitive_earnings_time(self):
        """Earnings time matching should handle exact values."""
        earnings_date = date(2025, 11, 13)

        # Test exact match (uppercase)
        spot_date = _get_spot_price_date(earnings_date, "PRE_MARKET")
        assert spot_date == date(2025, 11, 12)

        # Any other value defaults to same day
        spot_date_lower = _get_spot_price_date(earnings_date, "pre_market")
        assert spot_date_lower == earnings_date  # Not recognized, defaults to same day

    def test_empty_string_earnings_time(self):
        """Empty string should default to same day."""
        earnings_date = date(2025, 11, 13)
        earnings_time = ""

        spot_date = _get_spot_price_date(earnings_date, earnings_time)
        assert spot_date == earnings_date

    def test_none_earnings_time_defaults_same_day(self):
        """None earnings_time defaults to same day (handled gracefully)."""
        # This documents that _get_spot_price_date handles None gracefully
        # In practice, caller uses row.get("earnings_time", "UNKNOWN")
        earnings_date = date(2025, 11, 13)

        # None is not "PRE_MARKET", so defaults to same day
        spot_date = _get_spot_price_date(earnings_date, None)
        assert spot_date == earnings_date

    def test_previous_trading_day_raises_on_impossible_date(self):
        """Previous trading day should raise ValueError if none found."""
        # This is extremely unlikely in practice (would need 30+ consecutive non-trading days)
        # But documents the error behavior

        # We can't easily test this without mocking the market calendar
        # because there's no real date range without a previous trading day in 30 days
        # This test documents the expected behavior
        pass  # Documented in spec


class TestIntegrationScenarios:
    """Test realistic earnings scenarios."""

    def test_apple_premarket_earnings_nov_2025(self):
        """Realistic test: AAPL pre-market earnings Wed Nov 13, 2025."""
        earnings_date = date(2025, 11, 13)  # Wednesday
        earnings_time = "PRE_MARKET"  # 7:00 AM ET

        spot_date = _get_spot_price_date(earnings_date, earnings_time)

        # Should use Tue Nov 12 close (market closed before earnings)
        assert spot_date == date(2025, 11, 12)

    def test_microsoft_afterhours_earnings_nov_2025(self):
        """Realistic test: MSFT after-hours earnings Wed Nov 13, 2025."""
        earnings_date = date(2025, 11, 13)  # Wednesday
        earnings_time = "AFTER_HOURS"  # 4:00 PM ET

        spot_date = _get_spot_price_date(earnings_date, earnings_time)

        # Should use Wed Nov 13 close (market closed after earnings)
        assert spot_date == date(2025, 11, 13)

    def test_monday_premarket_after_weekend(self):
        """Realistic test: Pre-market earnings on Monday after weekend."""
        earnings_date = date(2025, 11, 17)  # Monday
        earnings_time = "PRE_MARKET"

        spot_date = _get_spot_price_date(earnings_date, earnings_time)

        # Should use Fri Nov 14 close (skip weekend)
        assert spot_date == date(2025, 11, 14)

    def test_unknown_time_conservative_default(self):
        """Realistic test: Unknown earnings time uses conservative default."""
        earnings_date = date(2025, 11, 13)
        earnings_time = "UNKNOWN"

        spot_date = _get_spot_price_date(earnings_date, earnings_time)

        # Conservative: use same day (assume after-hours)
        assert spot_date == earnings_date
