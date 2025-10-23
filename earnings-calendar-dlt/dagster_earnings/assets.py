"""Dagster assets for earnings calendar data."""

import dlt
from dagster import AssetExecutionContext
from dagster_dlt import DagsterDltResource, dlt_assets

from earnings_calendar import nasdaq_earnings_source
from earnings_calendar.config import get_default_config


@dlt_assets(
    dlt_source=nasdaq_earnings_source(),
    dlt_pipeline=dlt.pipeline(
        pipeline_name="nasdaq_earnings_pipeline",
        destination="filesystem",
        dataset_name="nasdaq_earnings",
    ),
    name="nasdaq_earnings",
    group_name="earnings_calendar",
)
def nasdaq_earnings_assets(
    context: AssetExecutionContext, dlt_resource: DagsterDltResource
):
    """
    Dagster assets for Nasdaq earnings calendar data.

    This asset materializes the earnings calendar by scraping data from
    Nasdaq and storing it in Parquet format. Each run creates a daily
    snapshot of the earnings calendar.
    """
    # Load configuration
    config = get_default_config()

    context.log.info(
        f"Materializing earnings calendar: "
        f"days_ahead={config.scraper.days_ahead}, "
        f"destination={config.dlt.destination}"
    )

    # The dlt source will be executed by the Dagster dlt integration
    yield from dlt_resource.load()

    context.log.info("Earnings calendar materialization complete")


# Alternative: Custom implementation without @dlt_assets decorator
# This provides more control over the execution

from dagster import asset, Output, AssetMaterialization, MetadataValue
from earnings_calendar import run_pipeline


@asset(
    name="earnings_calendar_custom",
    group_name="earnings_calendar",
    description="Earnings calendar data from Nasdaq (custom implementation)",
    compute_kind="dlt",
)
def earnings_calendar_custom_asset(context: AssetExecutionContext) -> Output:
    """
    Custom Dagster asset for earnings calendar data.

    This provides more control than the @dlt_assets decorator approach.
    Use this if you need custom logic or metadata handling.
    """
    config = get_default_config()

    context.log.info("Starting earnings calendar pipeline")

    # Run the dlt pipeline
    load_info = run_pipeline(
        days_ahead=config.scraper.days_ahead,
        destination=config.dlt.destination,
        dataset_name=config.dlt.dataset_name,
    )

    # Extract metadata from load_info
    total_records = sum(
        package.state.get("finished_count", 0) for package in load_info.load_packages
    )

    context.log.info(f"Loaded {total_records} records")

    # Return with metadata
    return Output(
        value=None,
        metadata={
            "total_records": total_records,
            "pipeline_name": load_info.pipeline.pipeline_name,
            "dataset_name": config.dlt.dataset_name,
            "destination": config.dlt.destination,
            "load_id": load_info.load_packages[0].load_id if load_info.load_packages else None,
        },
    )
