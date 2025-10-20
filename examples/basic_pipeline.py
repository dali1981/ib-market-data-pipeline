"""
Basic example: Fetch historical data for AAPL and load to DuckDB.

This example uses the config loader to automatically load settings from:
1. .dlt-ibapi/ib_gateway.yaml (if exists)
2. Environment variables (IB_HOST, IB_PORT, etc.)
3. Default config (shipped with package)

Before running:
1. Initialize config: dlt-ibapi init
2. Edit .dlt-ibapi/ib_gateway.yaml to match your setup
3. Ensure IB Gateway/TWS is running
4. Test connection: dlt-ibapi test-connection
"""

import dlt
import logging
from dlt_ibapi import ib_historical_bars
from dlt_ibapi.config_loader import get_connection_config, get_historical_config

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
    # Load configuration from YAML/env vars/defaults
    # This will use .dlt-ibapi/ib_gateway.yaml if it exists,
    # or fall back to package defaults
    connection_config = get_connection_config()
    hist_config = get_historical_config()

    logger.info(f"Configuration loaded:")
    logger.info(f"  Connection: {connection_config.host}:{connection_config.port}")
    logger.info(f"  Bar size: {hist_config.bar_size}, Duration: {hist_config.duration}")

    # Create pipeline to DuckDB
    pipeline = dlt.pipeline(
        pipeline_name="ib_basic",
        destination="duckdb",
        dataset_name="stocks",
    )
    logger.info(f"Pipeline created: {pipeline.pipeline_name} -> {pipeline.dataset_name}")

    # Fetch AAPL data
    logger.info("Fetching AAPL historical data from IB...")
    data = ib_historical_bars(
        symbol="AAPL",
        exchange="SMART",
        currency="USD",
        connection_config=connection_config,
        hist_config=hist_config,
    )

    # Run pipeline
    logger.info("Running DLT pipeline...")
    info = pipeline.run(data)

    logger.info("Pipeline finished!")

    # Show what was loaded
    if info.has_failed_jobs:
        logger.error("Pipeline had failures:")
        for load_package in info.load_packages:
            for job in load_package.jobs['failed_jobs']:
                logger.error(f"  Failed: {job.file_path}: {job.failed_message}")
    else:
        logger.info("All jobs completed successfully")

        # Get row counts
        for load_package in info.load_packages:
            for job in load_package.jobs['completed_jobs']:
                if 'historical_bars' in job.file_path:
                    logger.info(f"  Loaded table: historical_bars")

    # Query to show results
    import duckdb
    import os

    db_path = f"{pipeline.pipeline_name}.duckdb"
    db_full_path = os.path.abspath(db_path)
    logger.info(f"Database location: {db_full_path}")

    conn = duckdb.connect(db_path)

    result = conn.execute("""
        SELECT COUNT(*) as row_count
        FROM stocks.historical_bars
    """).fetchone()

    logger.info(f"Total rows in database: {result[0]}")

    # Check for duplicates
    duplicates = conn.execute("""
        SELECT timestamp, COUNT(*) as count
        FROM stocks.historical_bars
        GROUP BY timestamp
        HAVING COUNT(*) > 1
        ORDER BY count DESC
        LIMIT 5
    """).fetchall()

    if duplicates:
        logger.warning(f"Found {len(duplicates)} duplicate timestamps!")
        logger.warning(f"Most duplicated: {duplicates[0][0]} appears {duplicates[0][1]} times")
        logger.warning("Tip: Use write_disposition='replace' to avoid duplicates on re-runs")

    if result[0] > 0:
        # Get distinct timestamps
        distinct_count = conn.execute("""
            SELECT COUNT(DISTINCT timestamp) as distinct_count
            FROM stocks.historical_bars
        """).fetchone()

        logger.info(f"Unique timestamps: {distinct_count[0]}")

        sample = conn.execute("""
            SELECT timestamp, open, high, low, close, volume
            FROM stocks.historical_bars
            ORDER BY timestamp DESC
            LIMIT 5
        """).fetchall()

        print("\n" + "="*80)
        print("📈 Latest 5 bars from database:")
        print("="*80)
        print(f"{'Timestamp':<25} {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10} {'Volume':>12}")
        print("-" * 80)
        for row in sample:
            print(f"{str(row[0]):<25} {row[1]:>10.2f} {row[2]:>10.2f} {row[3]:>10.2f} {row[4]:>10.2f} {row[5]:>12,}")
        print("="*80 + "\n")
    else:
        logger.warning("No data was loaded!")

    conn.close()


def main_simple():
    """
    Even simpler: Let the resources auto-load config.

    If you have .dlt-ibapi/ib_gateway.yaml in your project,
    you don't even need to call the config loader explicitly!
    """
    pipeline = dlt.pipeline(
        pipeline_name="ib_basic",
        destination="duckdb",
        dataset_name="stocks",
    )

    # Config is automatically loaded from .dlt-ibapi/ib_gateway.yaml
    data = ib_historical_bars(symbol="AAPL")

    info = pipeline.run(data)
    print(f"✓ Pipeline finished! Dataset: {pipeline.dataset_name}")


if __name__ == "__main__":
    # Run the main example
    main()

    # Uncomment to try the simpler version:
    # main_simple()
