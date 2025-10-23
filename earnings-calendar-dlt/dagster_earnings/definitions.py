"""Dagster definitions for earnings calendar pipeline."""

from dagster import (
    Definitions,
    define_asset_job,
    AssetSelection,
)
from dagster_dlt import DagsterDltResource

from .assets import nasdaq_earnings_assets, earnings_calendar_custom_asset
from .schedules import (
    daily_earnings_calendar_schedule,
    daily_earnings_calendar_custom_schedule,
    weekday_earnings_calendar_schedule,
)


# Define jobs
nasdaq_earnings_job = define_asset_job(
    name="nasdaq_earnings_job",
    selection=AssetSelection.assets(nasdaq_earnings_assets),
    description="Daily job to refresh Nasdaq earnings calendar data",
)

earnings_calendar_custom_job = define_asset_job(
    name="earnings_calendar_custom_job",
    selection=AssetSelection.assets(earnings_calendar_custom_asset),
    description="Custom job for earnings calendar data with more control",
)

weekday_earnings_calendar_job = define_asset_job(
    name="weekday_earnings_calendar_job",
    selection=AssetSelection.assets(nasdaq_earnings_assets),
    description="Weekday-only earnings calendar refresh",
)


# Bundle everything into Definitions
defs = Definitions(
    assets=[
        nasdaq_earnings_assets,
        earnings_calendar_custom_asset,
    ],
    jobs=[
        nasdaq_earnings_job,
        earnings_calendar_custom_job,
        weekday_earnings_calendar_job,
    ],
    schedules=[
        daily_earnings_calendar_schedule,
        daily_earnings_calendar_custom_schedule,
        weekday_earnings_calendar_schedule,
    ],
    resources={
        "dlt": DagsterDltResource(),
    },
)
