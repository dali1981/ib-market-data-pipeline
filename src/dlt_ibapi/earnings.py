"""
Earnings calendar DLT resources.

Provides DLT resources for loading earnings calendar data from external sources
(Nasdaq JSON files) into Parquet storage for use in backtesting.

Example:
    >>> import dlt    >>> from dlt_ibapi import load_earnings_from_json
    >>>
    >>> # Load earnings from Nasdaq JSON file
    >>> pipeline = dlt.pipeline(
    ...     pipeline_name="earnings_loader",
    ...     destination=dlt.destinations.filesystem(bucket_url="data"),
    ...     dataset_name="earnings",
    ... )
    >>>
    >>> # Load from JSON file
    >>> data = load_earnings_from_json("/path/to/earnings.json")
    >>> info = pipeline.run(data, write_disposition="replace", loader_file_format="parquet")
"""

from typing import Iterator, Optional, List
from pathlib import Path
from datetime import date, datetime

import dlt

from dlt_ibapi.backtest.earnings_loader import EarningsCalendarLoader, EarningsEvent


@dlt.resource(
    name="earnings_calendar",
    write_disposition="replace",  # Replace on each load (snapshot)
    primary_key=["symbol", "earnings_date"],
    columns={
        "symbol": {"data_type": "text"},
        "earnings_date": {"data_type": "date"},
        "date": {"data_type": "date", "partition": True},  # Partition column (same as earnings_date)
        "earnings_time": {"data_type": "text"},
        "company_name": {"data_type": "text"},
        "eps_forecast": {"data_type": "double"},
        "fiscal_quarter": {"data_type": "text"},
    }
)
def load_earnings_from_json(
    json_file: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    symbols: Optional[List[str]] = None,
) -> Iterator[dict]:
    """
    Load earnings calendar from Nasdaq JSON file.

    Reads earnings events from JSON files scraped from Nasdaq and yields them
    as DLT records for storage in Parquet format.

    Args:
        json_file: Path to earnings JSON file (e.g., "/Users/name/Desktop/earnings_2025-11-13.txt")
        start_date: Optional filter for minimum earnings date
        end_date: Optional filter for maximum earnings date
        symbols: Optional list of symbols to filter (e.g., ["AAPL", "MSFT"])

    Yields:
        Earnings event dictionaries ready for DLT ingestion

    Example:
        >>> data = load_earnings_from_json(
        ...     json_file="/Users/mohamedali/Desktop/earnings_2025-11-13.txt",
        ...     start_date=date(2025, 11, 13),
        ...     end_date=date(2025, 12, 31),
        ...     symbols=["AAPL", "MSFT", "GOOGL"],
        ... )
        >>> # Use in pipeline
        >>> pipeline.run(data, loader_file_format="parquet")

    Note:
        - JSON file format: Array of earnings objects from Nasdaq
        - See earnings_loader.py for expected JSON schema
        - write_disposition="replace" means each load replaces previous data
        - Use multiple files for historical snapshots by running pipeline multiple times
    """
    loader = EarningsCalendarLoader()

    # Load events from JSON
    events = loader.load_file(json_file)

    # Apply filters
    if start_date or end_date:
        events = loader.filter_by_date_range(
            events,
            start_date=start_date or date(1970, 1, 1),
            end_date=end_date or date(2100, 12, 31),
        )

    if symbols:
        events = loader.filter_by_symbols(events, symbols)

    # Convert to dicts for DLT
    for event in events:
        yield {
            "symbol": event.symbol,
            "earnings_date": event.earnings_date,
            "date": event.earnings_date,  # Add date field for partitioning
            "earnings_time": event.earnings_time,
            "company_name": event.company_name,
            "eps_forecast": event.eps_forecast,
            "fiscal_quarter": event.fiscal_quarter,
            "loaded_at": datetime.utcnow(),  # Track when data was loaded
        }


@dlt.resource(
    name="earnings_calendar",
    write_disposition="append",
    primary_key=["symbol", "earnings_date", "snapshot_date"],
    columns={
        "snapshot_date": {"data_type": "date"},  # When the snapshot was taken
        "symbol": {"data_type": "text"},
        "earnings_date": {"data_type": "date"},
        "date": {"data_type": "date", "partition": True},  # Partition column (same as earnings_date)
        "earnings_time": {"data_type": "text"},
        "company_name": {"data_type": "text"},
        "eps_forecast": {"data_type": "double"},
        "fiscal_quarter": {"data_type": "text"},
    }
)
def load_earnings_snapshot(
    json_file: str,
    snapshot_date: date,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    symbols: Optional[List[str]] = None,
) -> Iterator[dict]:
    """
    Load earnings calendar as a dated snapshot (for historical tracking).

    Similar to load_earnings_from_json but adds snapshot_date to track when
    the earnings calendar was captured. Use this for historical earnings
    calendar analysis or to see how earnings forecasts change over time.

    Args:
        json_file: Path to earnings JSON file
        snapshot_date: Date when this earnings calendar snapshot was captured
        start_date: Optional filter for minimum earnings date
        end_date: Optional filter for maximum earnings date
        symbols: Optional list of symbols to filter

    Yields:
        Earnings event dictionaries with snapshot_date added

    Example:
        >>> # Load multiple historical snapshots
        >>> for file_date in ["2025-11-01", "2025-11-08", "2025-11-15"]:
        ...     data = load_earnings_snapshot(
        ...         json_file=f"/path/earnings_{file_date}.txt",
        ...         snapshot_date=date.fromisoformat(file_date),
        ...     )
        ...     pipeline.run(data, loader_file_format="parquet")
        >>> # Now you can query: "What earnings were expected on Nov 1 vs Nov 15?"
    """
    loader = EarningsCalendarLoader()

    # Load events from JSON
    events = loader.load_file(json_file)

    # Apply filters
    if start_date or end_date:
        events = loader.filter_by_date_range(
            events,
            start_date=start_date or date(1970, 1, 1),
            end_date=end_date or date(2100, 12, 31),
        )

    if symbols:
        events = loader.filter_by_symbols(events, symbols)

    # Convert to dicts for DLT with snapshot tracking
    for event in events:
        yield {
            "snapshot_date": snapshot_date,  # Track when snapshot was taken
            "symbol": event.symbol,
            "earnings_date": event.earnings_date,
            "date": event.earnings_date,  # Add date field for partitioning
            "earnings_time": event.earnings_time,
            "company_name": event.company_name,
            "eps_forecast": event.eps_forecast,
            "fiscal_quarter": event.fiscal_quarter,
            "loaded_at": datetime.utcnow(),
        }
