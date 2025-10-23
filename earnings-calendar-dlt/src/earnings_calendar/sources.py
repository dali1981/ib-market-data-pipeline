"""DLT sources and resources for earnings calendar data."""

import dlt
from typing import Iterator, Dict, Any, Optional, List
import logging

from .scraper import NasdaqEarningsScraper
from .transformers import normalize_earnings_record, add_partition_columns
from .config import EarningsScraperConfig, get_default_config

logger = logging.getLogger(__name__)


@dlt.resource(
    name="earnings_calendar",
    write_disposition="replace",  # Daily snapshots
    primary_key="symbol",
)
def earnings_calendar_resource(
    days_ahead: Optional[int] = None,
    date: Optional[str] = None,
    scraper_config: Optional[EarningsScraperConfig] = None,
) -> Iterator[Dict[str, Any]]:
    """
    DLT resource for fetching Nasdaq earnings calendar data.

    This resource fetches earnings calendar data and stores daily snapshots.
    Each snapshot captures the complete state of the earnings calendar for
    that day, enabling historical analysis of estimate changes.

    Args:
        days_ahead: Number of days ahead to fetch (overrides config)
        date: Specific date to fetch (YYYY-MM-DD), or None for range
        scraper_config: Scraper configuration (loads defaults if None)

    Yields:
        Normalized earnings records with partition columns
    """
    # Load config
    if scraper_config is None:
        config = get_default_config()
        scraper_config = config.scraper

    # Override days_ahead if provided
    if days_ahead is not None:
        scraper_config.days_ahead = days_ahead

    logger.info(
        f"Fetching earnings calendar: days_ahead={scraper_config.days_ahead}, "
        f"date={date or 'range'}"
    )

    # Create scraper and fetch data
    scraper = NasdaqEarningsScraper(
        days_ahead=scraper_config.days_ahead,
        use_playwright_fallback=scraper_config.use_playwright_fallback,
        timeout=scraper_config.timeout,
    )

    try:
        raw_records = scraper.fetch(date=date)
        logger.info(f"Scraped {len(raw_records)} raw records")

        # Transform and yield records
        for raw_record in raw_records:
            normalized = normalize_earnings_record(raw_record)
            with_partitions = add_partition_columns(normalized)
            yield with_partitions

        logger.info(f"Yielded {len(raw_records)} normalized records")

    except Exception as e:
        logger.error(f"Error fetching earnings calendar: {e}")
        raise


@dlt.source(name="nasdaq_earnings")
def nasdaq_earnings_source(
    days_ahead: Optional[int] = None,
    date: Optional[str] = None,
    scraper_config: Optional[EarningsScraperConfig] = None,
) -> List[Any]:
    """
    Main DLT source for Nasdaq earnings calendar data.

    This source provides a unified entry point for earnings calendar data,
    making it easy to integrate with pipelines and orchestration tools.

    Args:
        days_ahead: Number of days ahead to fetch
        date: Specific date to fetch (YYYY-MM-DD)
        scraper_config: Scraper configuration

    Returns:
        List of DLT resources
    """
    return [
        earnings_calendar_resource(
            days_ahead=days_ahead,
            date=date,
            scraper_config=scraper_config,
        )
    ]


def create_pipeline(
    pipeline_name: str = "nasdaq_earnings_pipeline",
    destination: str = "filesystem",
    dataset_name: str = "nasdaq_earnings",
    **kwargs,
) -> dlt.Pipeline:
    """
    Create a DLT pipeline for earnings calendar data.

    Args:
        pipeline_name: Name of the pipeline
        destination: Destination type (filesystem, duckdb, etc.)
        dataset_name: Dataset name
        **kwargs: Additional pipeline configuration

    Returns:
        Configured DLT pipeline
    """
    return dlt.pipeline(
        pipeline_name=pipeline_name,
        destination=destination,
        dataset_name=dataset_name,
        **kwargs,
    )


def run_pipeline(
    days_ahead: Optional[int] = None,
    date: Optional[str] = None,
    pipeline_name: str = "nasdaq_earnings_pipeline",
    destination: str = "filesystem",
    dataset_name: str = "nasdaq_earnings",
    **kwargs,
) -> dlt.pipeline.LoadInfo:
    """
    Convenience function to run the earnings calendar pipeline.

    Args:
        days_ahead: Number of days ahead to fetch
        date: Specific date to fetch
        pipeline_name: Name of the pipeline
        destination: Destination type
        dataset_name: Dataset name
        **kwargs: Additional pipeline configuration

    Returns:
        Load info with execution details
    """
    pipeline = create_pipeline(
        pipeline_name=pipeline_name,
        destination=destination,
        dataset_name=dataset_name,
        **kwargs,
    )

    source = nasdaq_earnings_source(days_ahead=days_ahead, date=date)

    logger.info(f"Running pipeline: {pipeline_name} -> {destination}/{dataset_name}")
    load_info = pipeline.run(source)

    logger.info(f"Pipeline completed: {load_info}")
    return load_info
