"""
Example: Using configuration files with dlt-ibapi.

This example demonstrates the different ways to configure dlt-ibapi:
1. YAML config file
2. Environment variables
3. Explicit Pydantic models
4. Config loader utilities

Before running:
1. Initialize config: dlt-ibapi init
2. Edit .dlt-ibapi/ib_gateway.yaml to match your setup
3. Ensure IB Gateway/TWS is running
"""

import dlt
from dlt_ibapi import ib_historical_bars, ib_contract_details
from dlt_ibapi.config_loader import (
    get_connection_config,
    get_historical_config,
    load_config,
)


def example_1_yaml_auto_load():
    """
    Example 1: Automatically load config from .dlt-ibapi/ib_gateway.yaml

    This is the simplest approach - just call the resource functions
    and they'll automatically load settings from your config file.
    """
    print("\n=== Example 1: Auto-load from YAML ===")

    # Config is automatically loaded from .dlt-ibapi/ib_gateway.yaml
    data = ib_historical_bars(symbol="AAPL")

    pipeline = dlt.pipeline(
        pipeline_name="ib_yaml_config",
        destination=dlt.destinations.filesystem(bucket_url="data"),
        dataset_name="stocks",
    )

    # This will use connection settings from your YAML file
    info = pipeline.run(data, loader_file_format="parquet")
    print(f"Loaded {info}")


def example_2_config_loader():
    """
    Example 2: Use config loader utilities

    Load configuration objects that merge YAML + env vars,
    then pass them to resources.
    """
    print("\n=== Example 2: Config Loader ===")

    # Load configs (merges YAML, env vars, and defaults)
    conn_config = get_connection_config()
    hist_config = get_historical_config()

    print(f"Connection: {conn_config.host}:{conn_config.port}")
    print(f"Bar size: {hist_config.bar_size}")

    # Use the loaded configs
    data = ib_historical_bars(
        symbol="GOOGL",
        connection_config=conn_config,
        hist_config=hist_config,
    )

    pipeline = dlt.pipeline(
        pipeline_name="ib_loaded_config",
        destination=dlt.destinations.filesystem(bucket_url="data"),
        dataset_name="stocks",
    )

    info = pipeline.run(data, loader_file_format="parquet")
    print(f"Loaded {info}")


def example_3_view_merged_config():
    """
    Example 3: View merged configuration

    See what the final configuration looks like after merging
    all sources (defaults, YAML, env vars).
    """
    print("\n=== Example 3: View Merged Config ===")

    # Load full merged config
    config = load_config()

    print("\nConnection Settings:")
    print(f"  Host: {config.connection.host}")
    print(f"  Port: {config.connection.port}")
    print(f"  Client ID: {config.connection.client_id}")

    print("\nHistorical Settings:")
    print(f"  Duration: {config.historical.duration}")
    print(f"  Bar Size: {config.historical.bar_size}")
    print(f"  What to Show: {config.historical.what_to_show}")
    print(f"  Use RTH: {config.historical.use_rth}")


def example_4_override_with_code():
    """
    Example 4: Override config with code

    Even if you have YAML config, you can override specific
    settings by passing Pydantic models explicitly.
    """
    print("\n=== Example 4: Override with Code ===")

    from dlt_ibapi.config import IBConnectionConfig, IBHistoricalConfig

    # Start with loaded config
    conn_config = get_connection_config()

    # Override specific settings
    conn_config.client_id = 99

    # Create custom historical config
    custom_hist = IBHistoricalConfig(
        duration="1 W",
        bar_size="5 mins",
        what_to_show="MIDPOINT",
        use_rth=False,
    )

    print(f"Using client_id: {conn_config.client_id}")
    print(f"Bar size: {custom_hist.bar_size}")

    data = ib_historical_bars(
        symbol="MSFT",
        connection_config=conn_config,
        hist_config=custom_hist,
    )

    pipeline = dlt.pipeline(
        pipeline_name="ib_override_config",
        destination=dlt.destinations.filesystem(bucket_url="data"),
        dataset_name="stocks",
    )

    info = pipeline.run(data, loader_file_format="parquet")
    print(f"Loaded {info}")


def example_5_multiple_resources():
    """
    Example 5: Multiple resources with shared config

    Load config once and reuse it for multiple resources.
    """
    print("\n=== Example 5: Multiple Resources ===")

    # Load config once
    conn_config = get_connection_config()

    # Use for multiple resources
    symbols = ["AAPL", "GOOGL", "MSFT"]

    # Get contract details
    contracts = ib_contract_details(
        symbols=symbols,
        connection_config=conn_config,
    )

    pipeline = dlt.pipeline(
        pipeline_name="ib_multi_resource",
        destination=dlt.destinations.filesystem(bucket_url="data"),
        dataset_name="market_data",
    )

    info = pipeline.run(contracts, table_name="contracts", loader_file_format="parquet")
    print(f"Loaded contract details for {len(symbols)} symbols")

    # Then get historical data for each
    for symbol in symbols:
        bars = ib_historical_bars(
            symbol=symbol,
            connection_config=conn_config,
        )
        info = pipeline.run(bars, table_name="historical_bars", loader_file_format="parquet")
        print(f"Loaded historical bars for {symbol}")


if __name__ == "__main__":
    import sys

    # You can run specific examples:
    # python config_example.py 3  (runs example 3)

    if len(sys.argv) > 1:
        example_num = int(sys.argv[1])
        examples = {
            1: example_1_yaml_auto_load,
            2: example_2_config_loader,
            3: example_3_view_merged_config,
            4: example_4_override_with_code,
            5: example_5_multiple_resources,
        }

        if example_num in examples:
            examples[example_num]()
        else:
            print(f"Example {example_num} not found")
    else:
        # Run the view config example (safest, doesn't require IB connection)
        example_3_view_merged_config()

        print("\n" + "="*60)
        print("To run other examples:")
        print("  python config_example.py 1  # Auto-load from YAML")
        print("  python config_example.py 2  # Config loader")
        print("  python config_example.py 3  # View merged config")
        print("  python config_example.py 4  # Override with code")
        print("  python config_example.py 5  # Multiple resources")
        print("="*60)
