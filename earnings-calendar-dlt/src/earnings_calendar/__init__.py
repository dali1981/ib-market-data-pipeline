"""Earnings calendar scraper with dlt and Dagster integration."""

from .scraper import NasdaqEarningsScraper, fetch_earnings_calendar
from .config import (
    EarningsScraperConfig,
    EarningsDltConfig,
    EarningsCalendarConfig,
    get_default_config,
)
from .sources import (
    earnings_calendar_resource,
    nasdaq_earnings_source,
    create_pipeline,
    run_pipeline,
)
from .api import (
    EarningsCalendarReader,
    get_upcoming_earnings,
    get_earnings_by_ticker,
    get_earnings_by_date,
)

__version__ = "0.1.0"

__all__ = [
    # Scraper
    "NasdaqEarningsScraper",
    "fetch_earnings_calendar",
    # Config
    "EarningsScraperConfig",
    "EarningsDltConfig",
    "EarningsCalendarConfig",
    "get_default_config",
    # DLT sources
    "earnings_calendar_resource",
    "nasdaq_earnings_source",
    "create_pipeline",
    "run_pipeline",
    # Read API
    "EarningsCalendarReader",
    "get_upcoming_earnings",
    "get_earnings_by_ticker",
    "get_earnings_by_date",
]
