"""
Example: Complete option bars backfill workflow.

This example demonstrates the full option backfill process:
1. Capture option chain snapshot (if not exists)
2. Select contracts using different modes (ATM, moneyness, delta)
3. Backfill option bars with gap detection
4. Query results using OptionBarsReader
5. Display sample data and statistics

Before running:
1. Ensure IB Gateway/TWS is running
2. Configure connection: dlt-ibapi init
3. Test connection: dlt-ibapi test-connection
"""

import dlt
import logging
from datetime import date, timedelta
from dlt_ibapi import (
    snapshot_option_chain,
    backfill_option_bars,
)
from dlt_ibapi.config_loader import get_connection_config
from dlt_ibapi.repositories import OptionChainSnapshotReader, OptionBarsReader
from dlt_ibapi.backfill import OptionBackfillConfig, ContractSelectionMode

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

# Suppress noisy IB API logs
logging.getLogger('ibapi').setLevel(logging.WARNING)
logging.getLogger('ibx').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def step1_capture_snapshot(pipeline, connection_config, underlying="AAPL"):
    """Step 1: Capture option chain snapshot (prerequisite for backfill)."""
    logger.info("="*80)
    logger.info("STEP 1: Capture Option Chain Snapshot")
    logger.info("="*80)

    today = date.today()

    # Check if snapshot already exists
    # Note: Reader will need Phase 2 updates to work with Parquet
    reader = OptionChainSnapshotReader(
        database_path="data",  # Point to Parquet directory
        dataset_name=pipeline.dataset_name
    )

    snapshots = reader.get_available_snapshots(underlying)

    if today in snapshots:
        logger.info(f"Snapshot for {underlying} on {today} already exists")
        return True

    logger.info(f"Capturing option chain snapshot for {underlying} as of {today}")

    data = snapshot_option_chain(
        underlying=underlying,
        snapshot_date=today,
        connection_config=connection_config,
        min_dte=7,
        max_dte=60,
    )

    info = pipeline.run(data, write_disposition="replace", loader_file_format="parquet")

    if info.has_failed_jobs:
        logger.error("Snapshot capture failed!")
        return False

    logger.info(f"✓ Snapshot captured successfully")

    # Display snapshot info
    chain = reader.get_chain_for_date(underlying, today, min_dte=7, max_dte=60)
    if not chain.empty:
        total_expirations = sum(chain['expiration_count'])
        total_strikes = sum(chain['strike_count'])
        logger.info(f"  - Expirations: {total_expirations}")
        logger.info(f"  - Strikes: {total_strikes}")

    return True


def step2_backfill_atm(pipeline, connection_config, underlying="AAPL", spot_price=150.0):
    """Step 2: Backfill option bars using ATM mode."""
    logger.info("\n" + "="*80)
    logger.info("STEP 2: Backfill Option Bars (K_AROUND_ATM Mode)")
    logger.info("="*80)

    config = OptionBackfillConfig(
        start_date=date.today() - timedelta(days=7),  # Last 7 days
        end_date=date.today(),
        bar_size="1 day",
        what_to_show="TRADES",
        use_rth=True,
        selection_mode=ContractSelectionMode.K_AROUND_ATM,
        k_strikes=3,  # 3 strikes on each side of ATM (7 total per expiry)
        min_dte=7,
        max_dte=60,
        include_calls=True,
        include_puts=True,
    )

    logger.info(f"Configuration:")
    logger.info(f"  - Date range: {config.start_date} to {config.end_date}")
    logger.info(f"  - Bar size: {config.bar_size}")
    logger.info(f"  - Selection mode: {config.selection_mode.value}")
    logger.info(f"  - K strikes: {config.k_strikes} (±{config.k_strikes} around ATM)")
    logger.info(f"  - DTE range: {config.min_dte} to {config.max_dte}")
    logger.info(f"  - Spot price: ${spot_price}")

    data = backfill_option_bars(
        underlying=underlying,
        spot_price=spot_price,
        database_path="data",  # Point to Parquet directory
        dataset_name=pipeline.dataset_name,
        connection_config=connection_config,
        backfill_config=config,
    )

    logger.info("Running backfill...")
    info = pipeline.run(data, write_disposition="append", loader_file_format="parquet")

    if info.has_failed_jobs:
        logger.error("Backfill had failures!")
        return False

    logger.info("✓ Backfill completed successfully")
    return True


def step3_backfill_moneyness(pipeline, connection_config, underlying="AAPL", spot_price=150.0):
    """Step 3: Backfill using MONEYNESS mode (different contracts)."""
    logger.info("\n" + "="*80)
    logger.info("STEP 3: Backfill Option Bars (MONEYNESS Mode)")
    logger.info("="*80)

    config = OptionBackfillConfig(
        start_date=date.today() - timedelta(days=7),
        end_date=date.today(),
        bar_size="1 day",
        selection_mode=ContractSelectionMode.MONEYNESS,
        moneyness_levels=[0.90, 0.95, 1.0, 1.05, 1.10],  # OTM puts, ATM, OTM calls
        min_dte=7,
        max_dte=60,
        include_calls=True,
        include_puts=True,
    )

    logger.info(f"Configuration:")
    logger.info(f"  - Selection mode: {config.selection_mode.value}")
    logger.info(f"  - Moneyness levels: {config.moneyness_levels}")
    logger.info(f"  - Spot price: ${spot_price}")

    data = backfill_option_bars(
        underlying=underlying,
        spot_price=spot_price,
        database_path="data",  # Point to Parquet directory
        dataset_name=pipeline.dataset_name,
        connection_config=connection_config,
        backfill_config=config,
    )

    logger.info("Running backfill...")
    info = pipeline.run(data, write_disposition="append", loader_file_format="parquet")

    if info.has_failed_jobs:
        logger.error("Backfill had failures!")
        return False

    logger.info("✓ Backfill completed successfully")
    return True


def step4_query_results(pipeline, underlying="AAPL"):
    """Step 4: Query and analyze backfilled data."""
    logger.info("\n" + "="*80)
    logger.info("STEP 4: Query and Analyze Backfilled Data")
    logger.info("="*80)

    # Note: Reader will need Phase 2 updates to work with Parquet
    reader = OptionBarsReader(
        database_path="data",  # Point to Parquet directory
        dataset_name=pipeline.dataset_name
    )

    # Get available contracts
    contracts = reader.get_contracts_for_underlying(
        underlying=underlying,
        bar_size="1 day"
    )

    if contracts.empty:
        logger.warning("No data found!")
        return

    logger.info(f"Total contracts backfilled: {len(contracts)}")

    print("\n" + "="*80)
    print(f"Backfilled Option Contracts for {underlying}")
    print("="*80)

    # Group by expiry
    expirations = contracts.groupby('expiry').agg({
        'strike': 'count',
        'bar_count': 'sum'
    }).reset_index()

    print("\nBy Expiration:")
    print("-" * 60)
    for _, row in expirations.iterrows():
        print(f"  {row['expiry']}: {int(row['strike'])} contracts, {int(row['bar_count'])} bars")

    # Show sample contracts
    print("\nSample Contracts (first 10):")
    print("-" * 60)
    for _, row in contracts.head(10).iterrows():
        print(f"  {row['expiry']} {row['strike']:>7.2f} {row['right']} | "
              f"{int(row['bar_count']):>4} bars | "
              f"{row['first_bar'].date()} to {row['last_bar'].date()}")

    # Get sample bars for one contract
    if not contracts.empty:
        sample = contracts.iloc[0]
        bars = reader.get_bars(
            underlying=underlying,
            expiry=sample['expiry'],
            strike=sample['strike'],
            right=sample['right'],
            bar_size="1 day",
            limit=5
        )

        if not bars.empty:
            print(f"\nSample Bars ({sample['expiry']} {sample['strike']} {sample['right']}):")
            print("-" * 60)
            print(bars[['time', 'open', 'high', 'low', 'close', 'volume']].to_string(index=False))

    print("="*80 + "\n")


def main():
    """Run complete option backfill workflow."""
    # Configuration
    connection_config = get_connection_config()
    logger.info(f"Connection: {connection_config.host}:{connection_config.port}")

    # Symbol configuration
    underlying = "AAPL"
    spot_price = 150.0  # Update this with current spot price

    logger.info(f"Underlying: {underlying} @ ${spot_price}")

    # Create DLT pipeline with filesystem destination (Parquet)
    pipeline = dlt.pipeline(
        pipeline_name="ib_option_chains",
        destination=dlt.destinations.filesystem(bucket_url="data"),
        dataset_name="options",
    )
    logger.info(f"Pipeline: {pipeline.pipeline_name} -> Parquet in ./data/{pipeline.dataset_name}/\n")

    # Run workflow steps
    if not step1_capture_snapshot(pipeline, connection_config, underlying):
        logger.error("Failed at step 1: snapshot capture")
        return

    if not step2_backfill_atm(pipeline, connection_config, underlying, spot_price):
        logger.error("Failed at step 2: ATM backfill")
        return

    # Optional: Run moneyness mode backfill
    # if not step3_backfill_moneyness(pipeline, connection_config, underlying, spot_price):
    #     logger.error("Failed at step 3: moneyness backfill")
    #     return

    step4_query_results(pipeline, underlying)

    logger.info("\n✓ Complete workflow finished successfully!")
    logger.info("\nNext steps:")
    logger.info("  1. Run again to see gap detection (should find no new gaps)")
    logger.info("  2. Uncomment step3 to backfill with moneyness mode")
    logger.info("  3. Try different bar sizes: '1 hour', '30 mins', '1 min'")
    logger.info("  4. Use DELTA mode for more precise strike selection")


if __name__ == "__main__":
    main()
