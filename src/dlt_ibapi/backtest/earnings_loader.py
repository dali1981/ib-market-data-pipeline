"""
Earnings calendar data loader for Nasdaq scraped earnings files.

Loads earnings events from JSON files in format:
/Users/mohamedali/Desktop/earnings_[date].txt

File format (JSON array):
[
    {
        "time": "Pre-Market" | "After Hours" | "Time Not Supplied",
        "symbol": "TSLA",
        "company_name": "Tesla, Inc",
        "market_cap": "$1,443,162,596,405",
        "fiscal_quarter_ending": "Sep/2025",
        "consensus_eps_forecast": "$0.41",
        "num_estimates": "11",
        "last_year_report_date": "10/23/2024",
        "last_year_eps": "$0.62",
        "date": "2025-10-22",
        "scraped_at": "2025-10-22T15:42:12.459530"
    },
    ...
]
"""

import json
import re
from pathlib import Path
from typing import List, Optional
from datetime import date, datetime
from dataclasses import dataclass

from dlt_ibapi.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class EarningsEvent:
    """
    Earnings event from Nasdaq calendar.

    Attributes:
        symbol: Stock ticker (normalized, no special chars)
        earnings_date: Date of earnings announcement
        earnings_time: When earnings are released (PRE_MARKET, AFTER_HOURS, UNKNOWN)
        company_name: Full company name
        eps_forecast: Consensus EPS forecast (optional)
        fiscal_quarter: Fiscal quarter ending (optional)
    """
    symbol: str
    earnings_date: date
    earnings_time: str  # "PRE_MARKET", "AFTER_HOURS", "UNKNOWN"
    company_name: str
    eps_forecast: Optional[float] = None
    fiscal_quarter: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> Optional["EarningsEvent"]:
        """
        Create EarningsEvent from Nasdaq JSON dict.

        Args:
            data: Raw earnings event dict from JSON

        Returns:
            EarningsEvent or None if parsing fails
        """
        try:
            # Parse symbol (remove special chars, normalize)
            raw_symbol = data.get("symbol", "").strip()
            symbol = cls._normalize_symbol(raw_symbol)

            if not symbol:
                logger.warning(f"Invalid symbol in earnings data: {raw_symbol}")
                return None

            # Parse date
            raw_date = data.get("date", "")
            try:
                earnings_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                logger.warning(f"Invalid date format for {symbol}: {raw_date}")
                return None

            # Parse time (normalize to enum-like values)
            raw_time = data.get("time", "").strip()
            earnings_time = cls._normalize_time(raw_time)

            # Parse EPS forecast (extract numeric value from string like "$0.41")
            eps_forecast = None
            raw_eps = data.get("consensus_eps_forecast", "")
            if raw_eps:
                eps_forecast = cls._parse_currency(raw_eps)

            return cls(
                symbol=symbol,
                earnings_date=earnings_date,
                earnings_time=earnings_time,
                company_name=data.get("company_name", "").strip(),
                eps_forecast=eps_forecast,
                fiscal_quarter=data.get("fiscal_quarter_ending", "").strip() or None,
            )

        except Exception as e:
            logger.error(f"Error parsing earnings event: {e}, data: {data}")
            return None

    @staticmethod
    def _normalize_symbol(raw_symbol: str) -> str:
        """
        Normalize symbol to ticker only.

        Examples:
            "TSLA" → "TSLA"
            "AT&T" → "ATT"  (remove special chars)
            "BRK.B" → "BRK.B"  (keep dots)
            "ABC   " → "ABC"  (strip whitespace)

        Args:
            raw_symbol: Raw symbol from JSON

        Returns:
            Normalized symbol or empty string if invalid
        """
        if not raw_symbol:
            return ""

        # Remove everything except letters, numbers, dots, and hyphens
        symbol = re.sub(r'[^A-Z0-9.\-]', '', raw_symbol.upper())

        # Basic validation
        if len(symbol) < 1 or len(symbol) > 10:
            return ""

        return symbol

    @staticmethod
    def _normalize_time(raw_time: str) -> str:
        """
        Normalize earnings time to standard values.

        Args:
            raw_time: Raw time string from JSON

        Returns:
            "PRE_MARKET", "AFTER_HOURS", or "UNKNOWN"
        """
        time_upper = raw_time.upper()

        if "PRE" in time_upper or "BEFORE" in time_upper:
            return "PRE_MARKET"
        elif "AFTER" in time_upper or "POST" in time_upper:
            return "AFTER_HOURS"
        else:
            return "UNKNOWN"

    @staticmethod
    def _parse_currency(raw_value: str) -> Optional[float]:
        """
        Parse currency string to float.

        Examples:
            "$0.41" → 0.41
            "$1,234.56" → 1234.56
            "-$0.50" → -0.50
            "N/A" → None

        Args:
            raw_value: Raw currency string

        Returns:
            Parsed float or None if invalid
        """
        if not raw_value or raw_value.upper() in ["N/A", "NA", "--"]:
            return None

        try:
            # Remove $ and , characters
            cleaned = raw_value.replace("$", "").replace(",", "").strip()
            return float(cleaned)
        except ValueError:
            return None


class EarningsCalendarLoader:
    """
    Load earnings calendar data from Nasdaq JSON files.

    Example:
        >>> loader = EarningsCalendarLoader()
        >>> events = loader.load_file("/Users/mohamedali/Desktop/earnings_2024-10-22.txt")
        >>> print(f"Loaded {len(events)} earnings events")
        >>>
        >>> # Filter by date range
        >>> filtered = loader.filter_by_date_range(
        ...     events,
        ...     start_date=date(2024, 10, 1),
        ...     end_date=date(2024, 10, 31),
        ... )
    """

    def load_file(self, file_path: str) -> List[EarningsEvent]:
        """
        Load earnings events from JSON file.

        Args:
            file_path: Path to earnings JSON file

        Returns:
            List of parsed EarningsEvent objects

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file is not valid JSON
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Earnings file not found: {file_path}")

        logger.info(f"Loading earnings from: {file_path}")

        try:
            with open(path, 'r') as f:
                raw_data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in earnings file: {e}")

        if not isinstance(raw_data, list):
            raise ValueError(
                f"Expected JSON array, got {type(raw_data).__name__}. "
                f"File should contain array of earnings events."
            )

        # Parse each event
        events = []
        skipped = 0

        for item in raw_data:
            event = EarningsEvent.from_dict(item)
            if event is not None:
                events.append(event)
            else:
                skipped += 1

        logger.info(
            f"Loaded {len(events)} earnings events "
            f"({skipped} skipped due to parsing errors)"
        )

        return events

    def filter_by_date_range(
        self,
        events: List[EarningsEvent],
        start_date: date,
        end_date: date,
    ) -> List[EarningsEvent]:
        """
        Filter earnings events by date range.

        Args:
            events: List of earnings events
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            Filtered list of events within date range
        """
        filtered = [
            e for e in events
            if start_date <= e.earnings_date <= end_date
        ]

        logger.info(
            f"Filtered to {len(filtered)}/{len(events)} events "
            f"in range {start_date} to {end_date}"
        )

        return filtered

    def filter_by_symbols(
        self,
        events: List[EarningsEvent],
        symbols: List[str],
    ) -> List[EarningsEvent]:
        """
        Filter earnings events by symbol list.

        Args:
            events: List of earnings events
            symbols: List of symbols to keep

        Returns:
            Filtered list of events for specified symbols
        """
        symbols_upper = {s.upper() for s in symbols}

        filtered = [
            e for e in events
            if e.symbol.upper() in symbols_upper
        ]

        logger.info(
            f"Filtered to {len(filtered)}/{len(events)} events "
            f"for {len(symbols)} symbols"
        )

        return filtered

    def filter_by_time(
        self,
        events: List[EarningsEvent],
        allowed_times: List[str],
    ) -> List[EarningsEvent]:
        """
        Filter earnings events by announcement time.

        Args:
            events: List of earnings events
            allowed_times: List of allowed times ("PRE_MARKET", "AFTER_HOURS", "UNKNOWN")

        Returns:
            Filtered list of events
        """
        allowed_set = {t.upper() for t in allowed_times}

        filtered = [
            e for e in events
            if e.earnings_time in allowed_set
        ]

        logger.info(
            f"Filtered to {len(filtered)}/{len(events)} events "
            f"for times: {', '.join(allowed_times)}"
        )

        return filtered

    def get_symbols(self, events: List[EarningsEvent]) -> List[str]:
        """
        Get unique symbols from earnings events.

        Args:
            events: List of earnings events

        Returns:
            Sorted list of unique symbols
        """
        symbols = sorted({e.symbol for e in events})
        logger.debug(f"Found {len(symbols)} unique symbols in {len(events)} events")
        return symbols
