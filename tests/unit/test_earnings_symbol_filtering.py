"""
Unit tests for earnings symbol filtering in options backfill.

Tests the --symbols parameter functionality that filters which symbols
to backfill when using --earnings-date mode.
"""

import pytest
from datetime import date

from dlt_ibapi.cli.models import BackfillOptionsParams


class TestEarningsSymbolsFilter:
    """Test earnings_symbols_filter parameter validation and behavior."""

    def test_filter_with_valid_symbols(self):
        """Filter should accept valid symbol list."""
        params = BackfillOptionsParams(
            earnings_date=date(2025, 11, 13),
            earnings_symbols_filter=["AAPL", "MSFT", "GOOGL"],
            start_date=date(2025, 11, 1),
            end_date=date(2025, 11, 13),
            pipeline_name="test",
        )

        assert params.earnings_symbols_filter == ["AAPL", "MSFT", "GOOGL"]

    def test_filter_uppercases_symbols(self):
        """Filter should uppercase all symbols."""
        params = BackfillOptionsParams(
            earnings_date=date(2025, 11, 13),
            earnings_symbols_filter=["aapl", "MsFt", "googl"],
            start_date=date(2025, 11, 1),
            end_date=date(2025, 11, 13),
            pipeline_name="test",
        )

        assert params.earnings_symbols_filter == ["AAPL", "MSFT", "GOOGL"]

    def test_filter_strips_whitespace(self):
        """Filter should strip whitespace from symbols."""
        params = BackfillOptionsParams(
            earnings_date=date(2025, 11, 13),
            earnings_symbols_filter=["  AAPL  ", " MSFT", "GOOGL "],
            start_date=date(2025, 11, 1),
            end_date=date(2025, 11, 13),
            pipeline_name="test",
        )

        assert params.earnings_symbols_filter == ["AAPL", "MSFT", "GOOGL"]

    def test_filter_removes_empty_strings(self):
        """Filter should remove empty strings."""
        params = BackfillOptionsParams(
            earnings_date=date(2025, 11, 13),
            earnings_symbols_filter=["AAPL", "", "MSFT", "  ", "GOOGL"],
            start_date=date(2025, 11, 1),
            end_date=date(2025, 11, 13),
            pipeline_name="test",
        )

        assert params.earnings_symbols_filter == ["AAPL", "MSFT", "GOOGL"]

    def test_filter_none_is_valid(self):
        """Filter can be None (means all symbols)."""
        params = BackfillOptionsParams(
            earnings_date=date(2025, 11, 13),
            earnings_symbols_filter=None,
            start_date=date(2025, 11, 1),
            end_date=date(2025, 11, 13),
            pipeline_name="test",
        )

        assert params.earnings_symbols_filter is None

    def test_filter_empty_list_becomes_empty(self):
        """Filter with only empty strings becomes empty list."""
        params = BackfillOptionsParams(
            earnings_date=date(2025, 11, 13),
            earnings_symbols_filter=["", "  ", "   "],
            start_date=date(2025, 11, 1),
            end_date=date(2025, 11, 13),
            pipeline_name="test",
        )

        # Empty list after stripping
        assert params.earnings_symbols_filter == []

    def test_filter_single_symbol(self):
        """Filter works with single symbol."""
        params = BackfillOptionsParams(
            earnings_date=date(2025, 11, 13),
            earnings_symbols_filter=["AAPL"],
            start_date=date(2025, 11, 1),
            end_date=date(2025, 11, 13),
            pipeline_name="test",
        )

        assert params.earnings_symbols_filter == ["AAPL"]

    def test_filter_with_duplicate_symbols(self):
        """Filter should preserve duplicates (user responsibility to dedupe)."""
        params = BackfillOptionsParams(
            earnings_date=date(2025, 11, 13),
            earnings_symbols_filter=["AAPL", "MSFT", "AAPL"],
            start_date=date(2025, 11, 1),
            end_date=date(2025, 11, 13),
            pipeline_name="test",
        )

        # Duplicates preserved (could be deduped in business logic if needed)
        assert params.earnings_symbols_filter == ["AAPL", "MSFT", "AAPL"]


class TestMutualExclusivity:
    """Test that filter validation respects mode requirements."""

    def test_filter_requires_earnings_date(self):
        """Filter is only valid with earnings_date, not single symbol mode."""
        # This is validated at CLI level, not model level
        # Model allows it, CLI rejects it

        # Valid: earnings_date + filter
        params1 = BackfillOptionsParams(
            earnings_date=date(2025, 11, 13),
            earnings_symbols_filter=["AAPL"],
            start_date=date(2025, 11, 1),
            end_date=date(2025, 11, 13),
            pipeline_name="test",
        )
        assert params1.earnings_symbols_filter == ["AAPL"]

        # Invalid at model level: single symbol mode doesn't use filter
        # (but model doesn't enforce this - CLI does)
        with pytest.raises(ValueError, match="Cannot specify both underlying and earnings_date"):
            BackfillOptionsParams(
                underlying="AAPL",
                spot_price=150.0,
                earnings_date=date(2025, 11, 13),  # Mutually exclusive
                earnings_symbols_filter=["MSFT"],
                start_date=date(2025, 11, 1),
                end_date=date(2025, 11, 13),
                pipeline_name="test",
            )

    def test_filter_with_single_symbol_mode_ignored(self):
        """Filter is allowed in model but should be None in single symbol mode."""
        # Single symbol mode without filter (normal case)
        params = BackfillOptionsParams(
            underlying="AAPL",
            spot_price=150.0,
            start_date=date(2025, 11, 1),
            end_date=date(2025, 11, 13),
            pipeline_name="test",
        )

        # Filter defaults to None
        assert params.earnings_symbols_filter is None


class TestIntegrationScenarios:
    """Test realistic filtering scenarios."""

    def test_filter_subset_of_earnings_symbols(self):
        """Filter only processes requested symbols from earnings data."""
        # This test documents expected behavior
        # Actual filtering logic is in _execute_backfill_options_earnings

        params = BackfillOptionsParams(
            earnings_date=date(2025, 11, 13),
            earnings_symbols_filter=["AAPL", "MSFT"],  # Only want these 2
            start_date=date(2025, 11, 1),
            end_date=date(2025, 11, 13),
            pipeline_name="test",
        )

        assert params.earnings_symbols_filter == ["AAPL", "MSFT"]
        assert params.earnings_date == date(2025, 11, 13)

    def test_filter_all_symbols_explicit(self):
        """Filter can be None to process all symbols (explicit)."""
        params = BackfillOptionsParams(
            earnings_date=date(2025, 11, 13),
            earnings_symbols_filter=None,  # Explicitly all symbols
            start_date=date(2025, 11, 1),
            end_date=date(2025, 11, 13),
            pipeline_name="test",
        )

        assert params.earnings_symbols_filter is None

    def test_filter_case_insensitive_matching(self):
        """Filter matching should be case-insensitive (via uppercase)."""
        # If user passes lowercase, validator uppercases
        params = BackfillOptionsParams(
            earnings_date=date(2025, 11, 13),
            earnings_symbols_filter=["aapl", "msft"],
            start_date=date(2025, 11, 1),
            end_date=date(2025, 11, 13),
            pipeline_name="test",
        )

        # Uppercased for matching against earnings data
        assert params.earnings_symbols_filter == ["AAPL", "MSFT"]

    def test_filter_comma_separated_input(self):
        """Test simulating CLI comma-separated input."""
        # CLI parses "AAPL,MSFT,GOOGL" → ["AAPL", "MSFT", "GOOGL"]
        cli_input = "AAPL,MSFT,GOOGL"
        symbols_list = [s.strip() for s in cli_input.split(",")]

        params = BackfillOptionsParams(
            earnings_date=date(2025, 11, 13),
            earnings_symbols_filter=symbols_list,
            start_date=date(2025, 11, 1),
            end_date=date(2025, 11, 13),
            pipeline_name="test",
        )

        assert params.earnings_symbols_filter == ["AAPL", "MSFT", "GOOGL"]

    def test_filter_with_spaces_in_cli_input(self):
        """Test simulating CLI input with spaces."""
        # CLI: "AAPL, MSFT , GOOGL"
        cli_input = "AAPL, MSFT , GOOGL"
        symbols_list = [s.strip() for s in cli_input.split(",")]

        params = BackfillOptionsParams(
            earnings_date=date(2025, 11, 13),
            earnings_symbols_filter=symbols_list,
            start_date=date(2025, 11, 1),
            end_date=date(2025, 11, 13),
            pipeline_name="test",
        )

        # Validator strips whitespace
        assert params.earnings_symbols_filter == ["AAPL", "MSFT", "GOOGL"]
