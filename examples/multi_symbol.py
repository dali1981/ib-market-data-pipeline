"""
Multi-symbol example: Fetch data for multiple stocks.

This example demonstrates:
1. Loading config from YAML/env vars
2. Using ib_source to fetch multiple data types
3. Loading historical bars and contract details for multiple symbols

Before running:
1. Initialize config: dlt-ibapi init
2. Edit .dlt-ibapi/ib_gateway.yaml to match your setup
3. Ensure IB Gateway/TWS is running
"""

import dlt
from dlt_ibapi import ib_source
from dlt_ibapi.config_loader import get_connection_config


def main():
    """Fetch historical and contract data for multiple symbols."""
    symbols = ["AAPL", "GOOGL", "MSFT", "TSLA", "NVDA"]

    # Load connection config from YAML/env vars/defaults
    connection_config = get_connection_config()

    print(f"Using connection: {connection_config.host}:{connection_config.port}")
    print(f"Fetching data for {len(symbols)} symbols: {', '.join(symbols)}")

    # Create pipeline
    pipeline = dlt.pipeline(
        pipeline_name="ib_multi_symbol",
        destination="duckdb",
        dataset_name="market_data",
    )

    # Use ib_source to fetch both historical bars and contract details
    source = ib_source(
        symbols=symbols,
        include_historical=True,
        include_contract_details=True,
        connection_config=connection_config,
    )

    info = pipeline.run(source)

    print(f"\n✓ Pipeline finished!")
    print(f"Tables created: {list(pipeline.default_schema.tables.keys())}")


def main_simple():
    """
    Simpler version: Let ib_source auto-load config.

    If you have .dlt-ibapi/ib_gateway.yaml, you don't need
    to explicitly load the config!
    """
    symbols = ["AAPL", "GOOGL", "MSFT"]

    pipeline = dlt.pipeline(
        pipeline_name="ib_multi_symbol",
        destination="duckdb",
        dataset_name="market_data",
    )

    # Config is automatically loaded from .dlt-ibapi/ib_gateway.yaml
    source = ib_source(
        symbols=symbols,
        include_historical=True,
        include_contract_details=True,
    )

    info = pipeline.run(source)
    print(f"✓ Loaded data for {len(symbols)} symbols!")


if __name__ == "__main__":
    main()

    # Uncomment to try the simpler version:
    # main_simple()
