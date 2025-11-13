"""
Unit tests for earnings_loader module.

Tests earnings calendar loading from JSON files,
including normalization, filtering, and error handling.
"""

import pytest
import json
import tempfile
from pathlib import Path
from datetime import date

from dlt_ibapi.backtest.earnings_loader import (
    EarningsCalendarLoader,
    EarningsEvent,
)


# ===========================
# EarningsEvent Tests
# ===========================


def test_earnings_event_creation():
    """Test basic EarningsEvent creation."""
    event = EarningsEvent(
        symbol="AAPL",
        earnings_date=date(2024, 10, 22),
        earnings_time="AFTER_HOURS",
        company_name="Apple Inc.",
        eps_forecast=0.41,
        fiscal_quarter="Q4 2024",
    )

    assert event.symbol == "AAPL"
    assert event.earnings_date == date(2024, 10, 22)
    assert event.earnings_time == "AFTER_HOURS"
    assert event.company_name == "Apple Inc."
    assert event.eps_forecast == 0.41
    assert event.fiscal_quarter == "Q4 2024"


def test_earnings_event_from_dict_complete():
    """Test EarningsEvent.from_dict() with complete data."""
    data = {
        "symbol": "AAPL",
        "company_name": "Apple Inc.",
        "date": "2024-10-22",
        "time": "after_hours",
        "consensus_eps_forecast": "$0.41",
        "fiscal_quarter_ending": "Sep/2024",
    }

    event = EarningsEvent.from_dict(data)

    assert event is not None
    assert event.symbol == "AAPL"
    assert event.earnings_date == date(2024, 10, 22)
    assert event.earnings_time == "AFTER_HOURS"
    assert event.company_name == "Apple Inc."
    assert event.eps_forecast == 0.41
    assert event.fiscal_quarter == "Sep/2024"


def test_earnings_event_from_dict_minimal():
    """Test EarningsEvent.from_dict() with minimal required fields."""
    data = {
        "symbol": "AAPL",
        "date": "2024-10-22",
    }

    event = EarningsEvent.from_dict(data)

    assert event is not None
    assert event.symbol == "AAPL"
    assert event.earnings_date == date(2024, 10, 22)
    assert event.earnings_time == "UNKNOWN"
    assert event.company_name == ""
    assert event.eps_forecast is None
    assert event.fiscal_quarter is None


def test_earnings_event_from_dict_symbol_normalization():
    """Test symbol normalization (removes special characters)."""
    data = {
        "symbol": "BRK&A",  # Contains '&'
        "date": "2024-10-22",
    }

    event = EarningsEvent.from_dict(data)

    assert event is not None
    assert event.symbol == "BRKA"  # '&' removed


def test_earnings_event_from_dict_time_mapping():
    """Test earnings time standardization."""
    test_cases = [
        ("before_open", "PRE_MARKET"),
        ("after_hours", "AFTER_HOURS"),
        ("", "UNKNOWN"),
        ("other", "UNKNOWN"),
    ]

    for raw_time, expected_time in test_cases:
        data = {
            "symbol": "AAPL",
            "date": "2024-10-22",
            "time": raw_time,
        }

        event = EarningsEvent.from_dict(data)

        assert event is not None
        assert event.earnings_time == expected_time, \
            f"Failed for raw_time={raw_time}"


def test_earnings_event_from_dict_eps_parsing():
    """Test EPS forecast parsing from currency string."""
    test_cases = [
        ("$0.41", 0.41),
        ("$1.23", 1.23),
        ("0.55", 0.55),
        ("", None),
        ("N/A", None),
    ]

    for eps_str, expected_eps in test_cases:
        data = {
            "symbol": "AAPL",
            "date": "2024-10-22",
            "consensus_eps_forecast": eps_str,
        }

        event = EarningsEvent.from_dict(data)

        assert event is not None
        assert event.eps_forecast == expected_eps, \
            f"Failed for eps_str={eps_str}"


def test_earnings_event_from_dict_invalid_date():
    """Test handling of invalid earnings date."""
    data = {
        "symbol": "AAPL",
        "date": "invalid-date",
    }

    event = EarningsEvent.from_dict(data)

    assert event is None  # Should return None for invalid date


def test_earnings_event_from_dict_missing_required():
    """Test handling of missing required fields."""
    # Missing symbol
    assert EarningsEvent.from_dict({"date": "2024-10-22"}) is None

    # Missing date
    assert EarningsEvent.from_dict({"symbol": "AAPL"}) is None

    # Empty dict
    assert EarningsEvent.from_dict({}) is None


# ===========================
# EarningsCalendarLoader Tests
# ===========================


@pytest.fixture
def sample_earnings_json():
    """Create a sample earnings JSON file (flat array format)."""
    data = [
        {
            "symbol": "AAPL",
            "company_name": "Apple Inc.",
            "date": "2024-10-22",
            "time": "after_hours",
            "consensus_eps_forecast": "$0.41",
            "fiscal_quarter_ending": "Sep/2024",
        },
        {
            "symbol": "MSFT",
            "company_name": "Microsoft Corp",
            "date": "2024-10-23",
            "time": "before_open",
            "consensus_eps_forecast": "$2.99",
            "fiscal_quarter_ending": "Sep/2024",
        },
        {
            "symbol": "GOOGL",
            "company_name": "Alphabet Inc",
            "date": "2024-10-24",
            "time": "after_hours",
            "consensus_eps_forecast": "$1.85",
            "fiscal_quarter_ending": "Sep/2024",
        },
    ]

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(data, f)
        temp_path = f.name

    yield temp_path

    # Cleanup
    Path(temp_path).unlink()


def test_loader_initialization():
    """Test EarningsCalendarLoader initialization."""
    loader = EarningsCalendarLoader()
    assert loader is not None


def test_loader_load_file_json(sample_earnings_json):
    """Test loading earnings from JSON file."""
    loader = EarningsCalendarLoader()
    events = loader.load_file(sample_earnings_json)

    assert len(events) == 3
    assert events[0].symbol == "AAPL"
    assert events[0].earnings_date == date(2024, 10, 22)
    assert events[0].earnings_time == "AFTER_HOURS"

    assert events[1].symbol == "MSFT"
    assert events[1].earnings_date == date(2024, 10, 23)
    assert events[1].earnings_time == "PRE_MARKET"

    assert events[2].symbol == "GOOGL"
    assert events[2].earnings_date == date(2024, 10, 24)


def test_loader_load_file_nonexistent():
    """Test loading from nonexistent file raises error."""
    loader = EarningsCalendarLoader()

    with pytest.raises(FileNotFoundError):
        loader.load_file("/nonexistent/path/earnings.json")


def test_loader_load_file_invalid_json():
    """Test loading invalid JSON raises error."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        f.write("not valid json {")
        temp_path = f.name

    loader = EarningsCalendarLoader()

    with pytest.raises(ValueError):
        loader.load_file(temp_path)

    Path(temp_path).unlink()


def test_loader_load_file_wrong_format():
    """Test loading non-array JSON raises error."""
    data = {"earnings": []}  # Wrong format - not a flat array

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(data, f)
        temp_path = f.name

    loader = EarningsCalendarLoader()

    with pytest.raises(ValueError, match="Expected JSON array"):
        loader.load_file(temp_path)

    Path(temp_path).unlink()


def test_loader_filter_by_date_range(sample_earnings_json):
    """Test filtering events by date range."""
    loader = EarningsCalendarLoader()
    all_events = loader.load_file(sample_earnings_json)

    # Filter for Oct 23-24
    filtered = loader.filter_by_date_range(
        all_events,
        start_date=date(2024, 10, 23),
        end_date=date(2024, 10, 24),
    )

    assert len(filtered) == 2
    assert filtered[0].symbol == "MSFT"
    assert filtered[1].symbol == "GOOGL"


def test_loader_filter_by_date_range_no_matches(sample_earnings_json):
    """Test filtering with no matches returns empty list."""
    loader = EarningsCalendarLoader()
    all_events = loader.load_file(sample_earnings_json)

    # Filter for dates with no events
    filtered = loader.filter_by_date_range(
        all_events,
        start_date=date(2024, 12, 1),
        end_date=date(2024, 12, 31),
    )

    assert len(filtered) == 0


def test_loader_filter_by_symbols(sample_earnings_json):
    """Test filtering events by symbol list."""
    loader = EarningsCalendarLoader()
    all_events = loader.load_file(sample_earnings_json)

    # Filter for AAPL and GOOGL only
    filtered = loader.filter_by_symbols(
        all_events,
        symbols=["AAPL", "GOOGL"],
    )

    assert len(filtered) == 2
    assert filtered[0].symbol == "AAPL"
    assert filtered[1].symbol == "GOOGL"


def test_loader_filter_by_symbols_case_insensitive(sample_earnings_json):
    """Test filtering is case-insensitive."""
    loader = EarningsCalendarLoader()
    all_events = loader.load_file(sample_earnings_json)

    # Filter with lowercase symbols
    filtered = loader.filter_by_symbols(
        all_events,
        symbols=["aapl", "msft"],
    )

    assert len(filtered) == 2
    assert filtered[0].symbol == "AAPL"
    assert filtered[1].symbol == "MSFT"


def test_loader_filter_by_symbols_no_matches(sample_earnings_json):
    """Test filtering with no symbol matches returns empty list."""
    loader = EarningsCalendarLoader()
    all_events = loader.load_file(sample_earnings_json)

    # Filter for symbols not in file
    filtered = loader.filter_by_symbols(
        all_events,
        symbols=["AMZN", "NFLX"],
    )

    assert len(filtered) == 0


def test_loader_chained_filters(sample_earnings_json):
    """Test chaining multiple filters."""
    loader = EarningsCalendarLoader()
    all_events = loader.load_file(sample_earnings_json)

    # Filter by symbols, then by date range
    filtered = loader.filter_by_symbols(
        all_events,
        symbols=["AAPL", "MSFT", "GOOGL"],
    )
    filtered = loader.filter_by_date_range(
        filtered,
        start_date=date(2024, 10, 23),
        end_date=date(2024, 10, 23),
    )

    assert len(filtered) == 1
    assert filtered[0].symbol == "MSFT"


def test_loader_with_invalid_events():
    """Test loader skips invalid events gracefully."""
    # Create file with mix of valid and invalid events
    data = [
        {
            "symbol": "AAPL",
            "date": "2024-10-22",
        },
        {
            "symbol": "INVALID",
            "date": "not-a-date",  # Invalid date
        },
        {
            # Missing required symbol
            "date": "2024-10-23",
        },
        {
            "symbol": "MSFT",
            "date": "2024-10-24",
        },
    ]

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(data, f)
        temp_path = f.name

    loader = EarningsCalendarLoader()
    events = loader.load_file(temp_path)

    # Should only load 2 valid events (AAPL, MSFT)
    assert len(events) == 2
    assert events[0].symbol == "AAPL"
    assert events[1].symbol == "MSFT"

    Path(temp_path).unlink()


# ===========================
# Integration Tests
# ===========================


def test_full_workflow_realistic_data():
    """Test complete workflow with realistic data."""
    # Create realistic earnings file
    data = [
        {
            "symbol": "AAPL",
            "company_name": "Apple Inc.",
            "date": "2024-10-22",
            "time": "after_hours",
            "consensus_eps_forecast": "$0.41",
            "fiscal_quarter_ending": "Sep/2024",
        },
        {
            "symbol": "MSFT",
            "company_name": "Microsoft Corporation",
            "date": "2024-10-23",
            "time": "before_open",
            "consensus_eps_forecast": "$2.99",
            "fiscal_quarter_ending": "Sep/2024",
        },
        {
            "symbol": "GOOGL",
            "company_name": "Alphabet Inc. Class A",
            "date": "2024-10-24",
            "time": "after_hours",
            "consensus_eps_forecast": "$1.85",
        },
        {
            "symbol": "AMZN",
            "company_name": "Amazon.com Inc.",
            "date": "2024-10-25",
            "time": "after_hours",
            "consensus_eps_forecast": "$1.14",
        },
        {
            "symbol": "META",
            "company_name": "Meta Platforms Inc.",
            "date": "2024-10-26",
            "time": "after_hours",
            "consensus_eps_forecast": "$5.21",
        },
    ]

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(data, f)
        temp_path = f.name

    # Workflow: Load → Filter by symbols → Filter by date
    loader = EarningsCalendarLoader()

    # 1. Load all events
    all_events = loader.load_file(temp_path)
    assert len(all_events) == 5

    # 2. Filter for big tech stocks
    tech_events = loader.filter_by_symbols(
        all_events,
        symbols=["AAPL", "MSFT", "AMZN", "GOOGL", "META"],
    )
    assert len(tech_events) == 5  # All events are big tech

    # 3. Filter for specific week (Oct 23-25)
    week_events = loader.filter_by_date_range(
        tech_events,
        start_date=date(2024, 10, 23),
        end_date=date(2024, 10, 25),
    )
    assert len(week_events) == 3
    assert [e.symbol for e in week_events] == ["MSFT", "GOOGL", "AMZN"]

    # 4. Verify event details
    msft_event = week_events[0]
    assert msft_event.earnings_time == "PRE_MARKET"
    assert msft_event.eps_forecast == 2.99
    assert msft_event.company_name == "Microsoft Corporation"

    # Cleanup
    Path(temp_path).unlink()
