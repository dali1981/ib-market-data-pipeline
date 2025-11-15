"""
IB API datetime formatting utilities.

Centralizes datetime string formatting for IB API to handle timezone requirements
and future API changes in one place.
"""

from datetime import date, datetime
from typing import Literal


# Default timezone for IB API requests
# US/Eastern is standard for US equity markets
DEFAULT_IB_TIMEZONE = "US/Eastern"


class IBDateTimeFormatter:
    """
    Centralized formatter for IB API datetime strings.

    IB API requires timezone-aware datetime strings as of recent API versions.
    This class provides a single point of control for datetime formatting.

    Examples:
        >>> formatter = IBDateTimeFormatter()
        >>> formatter.format_end_datetime(date(2025, 11, 14))
        '20251114 23:59:59 US/Eastern'

        >>> formatter.format_end_datetime(date(2025, 11, 14), timezone="UTC")
        '20251114-23:59:59 UTC'
    """

    def __init__(self, default_timezone: str = DEFAULT_IB_TIMEZONE):
        """
        Initialize formatter with default timezone.

        Args:
            default_timezone: Timezone to use by default (e.g., "US/Eastern", "UTC")
        """
        self.default_timezone = default_timezone

    def format_end_datetime(
        self,
        dt: date | datetime,
        timezone: str | None = None,
        format_type: Literal["space", "dash"] = "space"
    ) -> str:
        """
        Format a date/datetime as an IB API endDateTime string with timezone.

        Args:
            dt: Date or datetime to format (time defaults to 23:59:59 for dates)
            timezone: Timezone string (default: self.default_timezone)
            format_type: "space" for "YYYYMMDD HH:MM:SS TZ" or "dash" for "YYYYMMDD-HH:MM:SS TZ"

        Returns:
            Formatted datetime string with timezone

        Examples:
            >>> fmt = IBDateTimeFormatter()
            >>> fmt.format_end_datetime(date(2025, 11, 14))
            '20251114 23:59:59 US/Eastern'

            >>> fmt.format_end_datetime(datetime(2025, 11, 14, 16, 30, 0))
            '20251114 16:30:00 US/Eastern'

            >>> fmt.format_end_datetime(date(2025, 11, 14), timezone="UTC", format_type="dash")
            '20251114-23:59:59 UTC'
        """
        tz = timezone or self.default_timezone

        # Convert date to datetime if needed (use end of day)
        if isinstance(dt, date) and not isinstance(dt, datetime):
            dt = datetime(dt.year, dt.month, dt.day, 23, 59, 59)

        # Format based on type
        separator = " " if format_type == "space" else "-"
        date_part = dt.strftime("%Y%m%d")
        time_part = dt.strftime("%H:%M:%S")

        return f"{date_part}{separator}{time_part} {tz}"

    def format_query_time(
        self,
        dt: date | datetime,
        timezone: str | None = None
    ) -> str:
        """
        Format a date/datetime for IB API query time parameter (always uses dash format).

        This is an alias for format_end_datetime with format_type="dash".
        Some IB API functions prefer the dash format.

        Args:
            dt: Date or datetime to format
            timezone: Timezone string (default: self.default_timezone)

        Returns:
            Formatted datetime string with timezone (dash format)

        Example:
            >>> fmt = IBDateTimeFormatter()
            >>> fmt.format_query_time(date(2025, 11, 14))
            '20251114-23:59:59 US/Eastern'
        """
        return self.format_end_datetime(dt, timezone=timezone, format_type="dash")


# Global singleton instance for convenience
# Can be imported and used directly: from dlt_ibapi.utils.ib_datetime import ib_datetime
ib_datetime = IBDateTimeFormatter()


# Convenience functions that use the global singleton
def format_ib_end_datetime(
    dt: date | datetime,
    timezone: str = DEFAULT_IB_TIMEZONE
) -> str:
    """
    Convenience function to format end datetime with timezone.

    Uses the global IBDateTimeFormatter singleton.

    Args:
        dt: Date or datetime to format
        timezone: Timezone string

    Returns:
        Formatted datetime string with timezone

    Example:
        >>> from dlt_ibapi.utils.ib_datetime import format_ib_end_datetime
        >>> format_ib_end_datetime(date(2025, 11, 14))
        '20251114 23:59:59 US/Eastern'
    """
    return ib_datetime.format_end_datetime(dt, timezone=timezone)


def format_ib_query_time(
    dt: date | datetime,
    timezone: str = DEFAULT_IB_TIMEZONE
) -> str:
    """
    Convenience function to format query time with timezone (dash format).

    Uses the global IBDateTimeFormatter singleton.

    Args:
        dt: Date or datetime to format
        timezone: Timezone string

    Returns:
        Formatted datetime string with timezone (dash format)

    Example:
        >>> from dlt_ibapi.utils.ib_datetime import format_ib_query_time
        >>> format_ib_query_time(date(2025, 11, 14))
        '20251114-23:59:59 US/Eastern'
    """
    return ib_datetime.format_query_time(dt, timezone=timezone)