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
from dlt_ibapi import ib_historical_bars
from dlt_ibapi.config_loader import get_connection_config, get_historical_config


def main():
    # Load configuration from YAML/env vars/defaults
    # This will use .dlt-ibapi/ib_gateway.yaml if it exists,
    # or fall back to package defaults
    connection_config = get_connection_config()
    hist_config = get_historical_config()

    print(f"Using connection: {connection_config.host}:{connection_config.port}")
    print(f"Bar size: {hist_config.bar_size}, Duration: {hist_config.duration}")

    # Create pipeline to DuckDB
    pipeline = dlt.pipeline(
        pipeline_name="ib_basic",
        destination="duckdb",
        dataset_name="stocks",
    )

    # Fetch AAPL data
    print("\nFetching AAPL historical data...")
    data = ib_historical_bars(
        symbol="AAPL",
        exchange="SMART",
        currency="USD",
        connection_config=connection_config,
        hist_config=hist_config,
    )

    # Run pipeline
    info = pipeline.run(data)

    print(f"\n✓ Pipeline finished!")
    print(f"Dataset: {pipeline.dataset_name}")
    print(f"Tables: {list(pipeline.default_schema.tables.keys())}")


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
