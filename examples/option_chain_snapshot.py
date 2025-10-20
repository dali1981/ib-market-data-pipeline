"""
Example: Capture option chain snapshot for AAPL.

This example demonstrates:
1. Capturing complete option chain parameters (strikes, expirations)
2. Storing as daily snapshots in DLT destination
3. Querying snapshots using OptionChainSnapshotReader

Before running:
1. Ensure IB Gateway/TWS is running
2. Configure connection: dlt-ibapi init
3. Test connection: dlt-ibapi test-connection
"""

import dlt
import logging
from datetime import date
from dlt_ibapi import snapshot_option_chain
from dlt_ibapi.config_loader import get_connection_config
from dlt_ibapi.repositories import OptionChainSnapshotReader

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


def main():
    # Configuration
    connection_config = get_connection_config()
    logger.info(f"Connection: {connection_config.host}:{connection_config.port}")

    # Create DLT pipeline
    pipeline = dlt.pipeline(
        pipeline_name="ib_option_chains",
        destination="duckdb",
        dataset_name="options",
    )
    logger.info(f"Pipeline: {pipeline.pipeline_name} -> {pipeline.dataset_name}")

    # Capture option chain snapshot for today
    today = date.today()
    logger.info(f"Capturing option chain snapshot for AAPL as of {today}")

    data = snapshot_option_chain(
        underlying="AAPL",
        snapshot_date=today,
        connection_config=connection_config,
        min_dte=7,  # At least 7 days to expiration
        max_dte=60,  # At most 60 days to expiration
    )

    # Run pipeline
    logger.info("Running DLT pipeline...")
    info = pipeline.run(data, write_disposition="replace")

    if info.has_failed_jobs:
        logger.error("Pipeline had failures")
        return

    logger.info("Pipeline completed successfully!")

    # Query results using reader
    reader = OptionChainSnapshotReader(
        database_path=f"{pipeline.pipeline_name}.duckdb",
        dataset_name=pipeline.dataset_name
    )

    # Get available snapshots
    snapshots = reader.get_available_snapshots("AAPL")
    logger.info(f"Available snapshots for AAPL: {sorted(snapshots)}")

    # Get chain for today
    chain = reader.get_chain_for_date(
        underlying="AAPL",
        as_of=today,
        min_dte=7,
        max_dte=60
    )

    if not chain.empty:
        logger.info(f"Option chain snapshot contains {len(chain)} parameter sets")
        print("\n" + "="*80)
        print(f"Option Chain Snapshot for AAPL ({today})")
        print("="*80)
        for idx, row in chain.iterrows():
            print(f"\nExchange: {row['exchange']}")
            print(f"Trading Class: {row['trading_class']}")
            print(f"Multiplier: {row['multiplier']}")
            print(f"Expirations ({row['expiration_count']}): {row['expirations'][:5]}...")
            print(f"Strikes ({row['strike_count']}): {row['strikes'][:10]}...")
        print("="*80 + "\n")

        # Get expirations
        expirations = reader.get_available_expirations(
            underlying="AAPL",
            as_of=today,
            min_dte=7,
            max_dte=60
        )
        logger.info(f"Available expirations: {expirations[:5]}...")

    else:
        logger.warning("No option chain data found!")


if __name__ == "__main__":
    main()
