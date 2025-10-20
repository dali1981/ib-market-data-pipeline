"""
Contract details example: Fetch detailed contract specifications.

This example demonstrates:
1. Loading config from YAML/env vars
2. Fetching contract details (company info, trading specs, etc.)
3. Querying the loaded data

Before running:
1. Initialize config: dlt-ibapi init
2. Edit .dlt-ibapi/ib_gateway.yaml to match your setup
3. Ensure IB Gateway/TWS is running
"""

import dlt
from dlt_ibapi import ib_contract_details
from dlt_ibapi.config_loader import get_connection_config


def main():
    """Fetch contract details for multiple symbols."""
    symbols = ["AAPL", "GOOGL", "MSFT"]

    # Load connection config from YAML/env vars/defaults
    connection_config = get_connection_config()

    print(f"Using connection: {connection_config.host}:{connection_config.port}")
    print(f"Fetching contract details for: {', '.join(symbols)}")

    pipeline = dlt.pipeline(
        pipeline_name="ib_contracts",
        destination=dlt.destinations.filesystem(bucket_url="data"),
        dataset_name="reference_data",
    )

    contracts = ib_contract_details(
        symbols=symbols,
        exchange="SMART",
        currency="USD",
        connection_config=connection_config,
    )

    info = pipeline.run(contracts, loader_file_format="parquet")

    print(f"\n✓ Pipeline finished! Data in: ./data/{pipeline.dataset_name}/")
    print(f"Contract details loaded to Parquet files")

    # Query the data
    query_contracts(pipeline)


def query_contracts(pipeline):
    """Query and display contract details from Parquet files."""
    import duckdb

    # Query Parquet files with DuckDB in-memory
    conn = duckdb.connect(":memory:")

    result = conn.execute("""
        SELECT
            symbol,
            contract_id,
            long_name,
            primary_exchange,
            category,
            subcategory
        FROM parquet_scan('data/contract_details/**/*.parquet', hive_partitioning=true)
        ORDER BY symbol
    """).fetchdf()

    print("\n" + "="*60)
    print("Contract Details:")
    print("="*60)
    for _, row in result.iterrows():
        print(f"\n{row['symbol']} ({row['long_name']})")
        print(f"  Contract ID: {row['contract_id']}")
        print(f"  Exchange: {row['primary_exchange']}")
        print(f"  Category: {row['category']} - {row['subcategory']}")

    conn.close()


def main_simple():
    """
    Simpler version: Let ib_contract_details auto-load config.

    If you have .dlt-ibapi/ib_gateway.yaml in your project,
    you don't need to explicitly load the config!
    """
    symbols = ["AAPL", "GOOGL", "MSFT"]

    pipeline = dlt.pipeline(
        pipeline_name="ib_contracts",
        destination=dlt.destinations.filesystem(bucket_url="data"),
        dataset_name="reference_data",
    )

    # Config is automatically loaded from .dlt-ibapi/ib_gateway.yaml
    contracts = ib_contract_details(symbols=symbols)

    info = pipeline.run(contracts, loader_file_format="parquet")
    print(f"✓ Loaded contract details for {len(symbols)} symbols!")


if __name__ == "__main__":
    main()

    # Uncomment to try the simpler version:
    # main_simple()
