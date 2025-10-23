"""Dagster definitions for the options pipeline."""

from dagster import (
    Definitions,
    define_asset_job,
    AssetSelection,
    RunRequest,
    ScheduleDefinition,
)

from dagster_options.assets import (
    ticker_contracts,
    stock_historical_data,
    option_chain_snapshots,
    selected_option_contracts,
    option_historical_data,
)


# ============================================================================
# Jobs
# ============================================================================


# On-demand job that runs the entire pipeline
process_tickers_job = define_asset_job(
    name="process_tickers_job",
    description="Process ticker list through contract resolution, data fetching, and option selection",
    selection=AssetSelection.all(),
)


# Partial job: only resolve contracts
resolve_contracts_job = define_asset_job(
    name="resolve_contracts_job",
    description="Resolve ticker symbols to IB contracts",
    selection=AssetSelection.assets(ticker_contracts),
)


# Partial job: fetch stock and option chain data
fetch_market_data_job = define_asset_job(
    name="fetch_market_data_job",
    description="Fetch stock historical data and option chain snapshots",
    selection=AssetSelection.assets(
        ticker_contracts,
        stock_historical_data,
        option_chain_snapshots,
    ),
)


# Partial job: select contracts only
select_contracts_job = define_asset_job(
    name="select_contracts_job",
    description="Select option contracts using delta strategies",
    selection=AssetSelection.assets(
        ticker_contracts,
        stock_historical_data,
        option_chain_snapshots,
        selected_option_contracts,
    ),
)


# Full job: complete pipeline
full_pipeline_job = define_asset_job(
    name="full_pipeline_job",
    description="Run complete pipeline from ticker resolution to option data backfill",
    selection=AssetSelection.all(),
)


# ============================================================================
# Schedules (Optional - currently disabled as per requirements)
# ============================================================================


# Example schedule (commented out as pipeline is on-demand only)
# daily_options_schedule = ScheduleDefinition(
#     job=full_pipeline_job,
#     cron_schedule="0 18 * * 1-5",  # 6 PM weekdays
#     name="daily_options_schedule",
#     description="Run options pipeline daily after market close",
# )


# ============================================================================
# Dagster Definitions
# ============================================================================


defs = Definitions(
    assets=[
        ticker_contracts,
        stock_historical_data,
        option_chain_snapshots,
        selected_option_contracts,
        option_historical_data,
    ],
    jobs=[
        process_tickers_job,
        resolve_contracts_job,
        fetch_market_data_job,
        select_contracts_job,
        full_pipeline_job,
    ],
    # schedules=[],  # No schedules (on-demand only)
)
