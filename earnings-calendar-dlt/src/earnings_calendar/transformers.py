"""Data transformation and normalization for earnings calendar data."""

from datetime import datetime
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


def normalize_earnings_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a single earnings record.

    Args:
        record: Raw earnings record from scraper

    Returns:
        Normalized record with consistent types and formats
    """
    return {
        # Identifiers
        "symbol": _normalize_symbol(record.get("symbol")),
        "company_name": _normalize_string(record.get("company_name")),
        # Dates
        "earnings_date": _normalize_date(record.get("earnings_date")),
        "earnings_time": _normalize_earnings_time(record.get("earnings_time")),
        "fiscal_quarter": _normalize_string(record.get("fiscal_quarter")),
        # Financial metrics
        "eps_forecast": _normalize_decimal(record.get("eps_forecast")),
        "eps_actual": _normalize_decimal(record.get("eps_actual")),
        "eps_surprise": _normalize_decimal(record.get("eps_surprise")),
        "eps_surprise_pct": _calculate_surprise_pct(
            record.get("eps_actual"), record.get("eps_forecast")
        ),
        "revenue_forecast": _normalize_decimal(record.get("revenue_forecast")),
        "revenue_actual": _normalize_decimal(record.get("revenue_actual")),
        "market_cap": _normalize_market_cap(record.get("market_cap")),
        "num_estimates": _normalize_int(record.get("num_estimates")),
        # Metadata
        "snapshot_date": record.get("snapshot_date"),  # Already in ISO format
        "scraped_at": record.get("scraped_at"),  # Already in ISO format
    }


def _normalize_symbol(symbol: Optional[str]) -> str:
    """Normalize stock symbol."""
    if not symbol:
        return ""
    return symbol.strip().upper()


def _normalize_string(value: Optional[str]) -> str:
    """Normalize string value."""
    if not value:
        return ""
    return value.strip()


def _normalize_date(date_value: Optional[str]) -> Optional[str]:
    """
    Normalize date to ISO format (YYYY-MM-DD).

    Args:
        date_value: Date string in various formats

    Returns:
        ISO formatted date string or None
    """
    if not date_value:
        return None

    date_str = str(date_value).strip()

    # Already in ISO format
    if len(date_str) == 10 and date_str[4] == "-" and date_str[7] == "-":
        return date_str

    # Try common formats
    date_formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d-%b-%Y",
    ]

    for fmt in date_formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.date().isoformat()
        except ValueError:
            continue

    logger.warning(f"Could not parse date: {date_value}")
    return None


def _normalize_earnings_time(time_value: Optional[str]) -> Optional[str]:
    """
    Normalize earnings announcement time.

    Common values: "Before Market Open", "After Market Close", "Time Not Supplied"

    Args:
        time_value: Time string

    Returns:
        Normalized time string: "BMO", "AMC", "TAS", or None
    """
    if not time_value:
        return None

    time_str = str(time_value).strip().upper()

    # Normalize to standard abbreviations
    if "BEFORE" in time_str or "PRE" in time_str or time_str == "BMO":
        return "BMO"  # Before Market Open
    elif "AFTER" in time_str or "POST" in time_str or time_str == "AMC":
        return "AMC"  # After Market Close
    elif "NOT SUPPLIED" in time_str or "TAS" in time_str:
        return "TAS"  # Time Not Supplied
    elif "DURING" in time_str or "INTRADAY" in time_str:
        return "DURING"
    else:
        return time_str[:20]  # Truncate unknown values


def _normalize_decimal(value: Any) -> Optional[float]:
    """
    Normalize decimal value.

    Args:
        value: Value to normalize

    Returns:
        Float value or None
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        # Remove common formatting
        cleaned = value.replace(",", "").replace("$", "").replace("%", "").strip()
        if cleaned in ["--", "N/A", "", "N.A."]:
            return None
        try:
            return float(cleaned)
        except ValueError:
            logger.warning(f"Could not parse decimal: {value}")
            return None

    return None


def _normalize_int(value: Any) -> Optional[int]:
    """
    Normalize integer value.

    Args:
        value: Value to normalize

    Returns:
        Integer value or None
    """
    decimal_val = _normalize_decimal(value)
    if decimal_val is not None:
        return int(decimal_val)
    return None


def _normalize_market_cap(value: Any) -> Optional[float]:
    """
    Normalize market cap value.

    Handles formats like "$1.5T", "500B", "10.5M"

    Args:
        value: Market cap value

    Returns:
        Market cap in dollars or None
    """
    if not value:
        return None

    value_str = str(value).strip().upper().replace("$", "").replace(",", "")

    # Extract numeric part and multiplier
    multipliers = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}

    for suffix, multiplier in multipliers.items():
        if value_str.endswith(suffix):
            try:
                numeric = float(value_str[:-1])
                return numeric * multiplier
            except ValueError:
                logger.warning(f"Could not parse market cap: {value}")
                return None

    # Try parsing as plain number
    try:
        return float(value_str)
    except ValueError:
        logger.warning(f"Could not parse market cap: {value}")
        return None


def _calculate_surprise_pct(actual: Any, forecast: Any) -> Optional[float]:
    """
    Calculate EPS surprise percentage.

    surprise% = ((actual - forecast) / |forecast|) * 100

    Args:
        actual: Actual EPS
        forecast: Forecast EPS

    Returns:
        Surprise percentage or None
    """
    actual_val = _normalize_decimal(actual)
    forecast_val = _normalize_decimal(forecast)

    if actual_val is None or forecast_val is None or forecast_val == 0:
        return None

    return ((actual_val - forecast_val) / abs(forecast_val)) * 100


def add_partition_columns(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add partition columns for efficient querying.

    Args:
        record: Normalized record

    Returns:
        Record with partition columns added
    """
    # Already has snapshot_date, add year/month for partitioning
    if record.get("earnings_date"):
        try:
            dt = datetime.fromisoformat(record["earnings_date"])
            record["earnings_year"] = dt.year
            record["earnings_month"] = dt.month
        except (ValueError, TypeError):
            pass

    if record.get("snapshot_date"):
        try:
            dt = datetime.fromisoformat(record["snapshot_date"])
            record["snapshot_year"] = dt.year
            record["snapshot_month"] = dt.month
        except (ValueError, TypeError):
            pass

    return record
