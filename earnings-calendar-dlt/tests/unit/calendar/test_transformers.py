"""Tests for data transformers."""

import pytest
from earnings_calendar.transformers import (
    normalize_earnings_record,
    _normalize_symbol,
    _normalize_date,
    _normalize_earnings_time,
    _normalize_decimal,
    _normalize_market_cap,
    _calculate_surprise_pct,
)


def test_normalize_symbol():
    """Test symbol normalization."""
    assert _normalize_symbol("aapl") == "AAPL"
    assert _normalize_symbol(" GOOGL ") == "GOOGL"
    assert _normalize_symbol(None) == ""
    assert _normalize_symbol("") == ""


def test_normalize_date():
    """Test date normalization."""
    # Already in ISO format
    assert _normalize_date("2025-10-22") == "2025-10-22"

    # Various formats
    assert _normalize_date("10/22/2025") == "2025-10-22"
    assert _normalize_date("Oct 22, 2025") == "2025-10-22"

    # Invalid dates
    assert _normalize_date(None) is None
    assert _normalize_date("invalid") is None


def test_normalize_earnings_time():
    """Test earnings time normalization."""
    assert _normalize_earnings_time("Before Market Open") == "BMO"
    assert _normalize_earnings_time("After Market Close") == "AMC"
    assert _normalize_earnings_time("Time Not Supplied") == "TAS"
    assert _normalize_earnings_time("BEFORE") == "BMO"
    assert _normalize_earnings_time("AFTER") == "AMC"
    assert _normalize_earnings_time(None) is None


def test_normalize_decimal():
    """Test decimal normalization."""
    assert _normalize_decimal(1.5) == 1.5
    assert _normalize_decimal("1.5") == 1.5
    assert _normalize_decimal("$1,234.56") == 1234.56
    assert _normalize_decimal("--") is None
    assert _normalize_decimal("N/A") is None
    assert _normalize_decimal(None) is None


def test_normalize_market_cap():
    """Test market cap normalization."""
    assert _normalize_market_cap("$1.5T") == 1.5e12
    assert _normalize_market_cap("500B") == 500e9
    assert _normalize_market_cap("10.5M") == 10.5e6
    assert _normalize_market_cap("5K") == 5e3
    assert _normalize_market_cap("1000000") == 1000000
    assert _normalize_market_cap(None) is None


def test_calculate_surprise_pct():
    """Test EPS surprise percentage calculation."""
    # Positive surprise
    assert _calculate_surprise_pct(1.5, 1.0) == 50.0

    # Negative surprise
    assert _calculate_surprise_pct(0.8, 1.0) == -20.0

    # Zero forecast
    assert _calculate_surprise_pct(1.0, 0) is None

    # Missing values
    assert _calculate_surprise_pct(None, 1.0) is None
    assert _calculate_surprise_pct(1.0, None) is None


def test_normalize_earnings_record():
    """Test full record normalization."""
    raw_record = {
        "symbol": "aapl",
        "company_name": "Apple Inc.",
        "earnings_date": "2025-10-22",
        "earnings_time": "After Market Close",
        "eps_forecast": "1.50",
        "eps_actual": "1.65",
        "market_cap": "$3.5T",
        "num_estimates": "25",
        "snapshot_date": "2025-10-21",
        "scraped_at": "2025-10-21T12:00:00",
    }

    normalized = normalize_earnings_record(raw_record)

    assert normalized["symbol"] == "AAPL"
    assert normalized["company_name"] == "Apple Inc."
    assert normalized["earnings_date"] == "2025-10-22"
    assert normalized["earnings_time"] == "AMC"
    assert normalized["eps_forecast"] == 1.50
    assert normalized["eps_actual"] == 1.65
    assert normalized["eps_surprise"] is None  # Not in raw
    assert normalized["eps_surprise_pct"] == 10.0  # Calculated
    assert normalized["market_cap"] == 3.5e12
    assert normalized["num_estimates"] == 25
    assert normalized["snapshot_date"] == "2025-10-21"


def test_normalize_earnings_record_with_missing_data():
    """Test normalization with missing data."""
    raw_record = {
        "symbol": "XYZ",
        "company_name": None,
        "earnings_date": None,
        "eps_forecast": None,
    }

    normalized = normalize_earnings_record(raw_record)

    assert normalized["symbol"] == "XYZ"
    assert normalized["company_name"] == ""
    assert normalized["earnings_date"] is None
    assert normalized["eps_forecast"] is None
    assert normalized["eps_surprise_pct"] is None
