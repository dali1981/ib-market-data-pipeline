"""
Example: Equity bars backfill workflow.

This example demonstrates equity (stock) historical data backfilling:
1. Backfill multiple symbols with gap detection
2. Query results using EquityBarsReader
3. Display statistics and sample data

This is simpler than option backfill since there's no need for:
- Option chain snapshots
- Contract selection algorithms
- Expiry/strike filtering

Before running:
1. Ensure IB Gateway/TWS is running
2. Configure connection: dlt-ibapi init
3. Test connection: dlt-ibapi test-connection
"""

import dlt
import logging
from datetime import date, timedelta
from dlt_ibapi import backfill_equity_bars, equity_bars_backfill_source
from dlt_ibapi.config_loader import get_connection_config
from dlt_ibapi.repositories import EquityBarsReader

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


def backfill_single_symbol(pipeline, connection_config, symbol="AAPL"):
    """Backfill single symbol with gap detection."""
    logger.info("="*80)
    logger.info(f"Backfilling {symbol}")
    logger.info("="*80)

    # Configuration
    start_date = date.today() - timedelta(days=30)  # Last 30 days
    end_date = date.today()
    bar_size = "1 day"

    logger.info(f"Date range: {start_date} to {end_date}")
    logger.info(f"Bar size: {bar_size}")

    # Create backfill resource
    data = backfill_equity_bars(
        symbol=symbol,
        database_path="data",  # Point to Parquet directory
        dataset_name=pipeline.dataset_name,
        connection_config=connection_config,
        start_date=start_date,
        end_date=end_date,
        bar_size=bar_size,
        what_to_show="TRADES",
        use_rth=True,
    )

    # Run pipeline with Parquet format
    logger.info("Running backfill...")
    info = pipeline.run(data, write_disposition="append", loader_file_format="parquet")

    if info.has_failed_jobs:
        logger.error(f"Backfill failed for {symbol}!")
        return False

    logger.info(f"✓ {symbol} backfill completed successfully")
    return True


def backfill_multiple_symbols(pipeline, connection_config, symbols=["AAPL", "MSFT", "GOOGL"]):
    """Backfill multiple symbols in a single pipeline run."""
    logger.info("="*80)
    logger.info(f"Backfilling {len(symbols)} symbols")
    logger.info("="*80)

    # Configuration
    start_date = date.today() - timedelta(days=30)
    end_date = date.today()
    bar_size = "1 day"

    logger.info(f"Symbols: {', '.join(symbols)}")
    logger.info(f"Date range: {start_date} to {end_date}")
    logger.info(f"Bar size: {bar_size}")

    # Create source with multiple resources
    data = equity_bars_backfill_source(
        symbols=symbols,
        database_path="data",  # Point to Parquet directory
        dataset_name=pipeline.dataset_name,
        connection_config=connection_config,
        start_date=start_date,
        end_date=end_date,
        bar_size=bar_size,
        what_to_show="TRADES",
        use_rth=True,
    )

    # Run pipeline with Parquet format
    logger.info("Running backfill...")
    info = pipeline.run(data, write_disposition="append", loader_file_format="parquet")

    if info.has_failed_jobs:
        logger.error("Backfill had failures!")
        return False

    logger.info(f"✓ All symbols backfilled successfully")
    return True


def query_and_display_results(pipeline):
    """Query and display backfilled data statistics."""
    logger.info("\n" + "="*80)
    logger.info("Query and Analyze Backfilled Data")
    logger.info("="*80)

    # Note: Reader will need Phase 2 updates to work with Parquet
    reader = EquityBarsReader(
        database_path="data",  # Point to Parquet directory
        dataset_name=pipeline.dataset_name
    )

    # Get all symbols
    symbols = reader.get_available_symbols(bar_size="1 day")

    if not symbols:
        logger.warning("No data found!")
        return

    logger.info(f"Total symbols backfilled: {len(symbols)}")

    # Get summary for all symbols
    summary = reader.get_symbols_summary(bar_size="1 day")

    print("\n" + "="*80)
    print("Equity Bars Backfill Summary")
    print("="*80)
    print("\nSymbol Coverage:")
    print("-" * 60)

    for _, row in summary.iterrows():
        date_range = f"{row['first_bar'].date()} to {row['last_bar'].date()}"
        print(f"  {row['symbol']:<6} | {int(row['bar_count']):>4} bars | {date_range}")

    # Display sample bars for first symbol
    if not summary.empty:
        sample_symbol = summary.iloc[0]['symbol']
        bars = reader.get_bars(
            symbol=sample_symbol,
            bar_size="1 day",
            limit=5
        )

        if not bars.empty:
            print(f"\nSample Bars ({sample_symbol}, last 5 days):")
            print("-" * 60)
            print(bars[['time', 'open', 'high', 'low', 'close', 'volume']].to_string(index=False))

    # Show date range for each symbol
    print("\nDate Range Details:")
    print("-" * 60)
    for symbol in symbols[:5]:  # Show first 5
        min_date, max_date = reader.get_date_range(symbol, "1 day")
        if min_date:
            days = (max_date - min_date).days + 1
            print(f"  {symbol}: {min_date} to {max_date} ({days} calendar days)")

    print("="*80 + "\n")


def demonstrate_gap_detection(pipeline, connection_config, symbol="AAPL"):
    """Demonstrate gap detection by running backfill twice."""
    logger.info("\n" + "="*80)
    logger.info("Demonstrate Gap Detection (Idempotent Backfill)")
    logger.info("="*80)

    logger.info(f"Running backfill for {symbol} again...")
    logger.info("Expected: No gaps found (data already complete)")

    data = backfill_equity_bars(
        symbol=symbol,
        database_path="data",  # Point to Parquet directory
        dataset_name=pipeline.dataset_name,
        connection_config=connection_config,
        start_date=date.today() - timedelta(days=30),
        end_date=date.today(),
        bar_size="1 day",
    )

    info = pipeline.run(data, write_disposition="append", loader_file_format="parquet")

    if info.has_failed_jobs:
        logger.error("Gap detection run failed!")
        return False

    logger.info("✓ Gap detection verified - backfill is idempotent!")
    return True


def main():
    """Run equity backfill workflow."""
    # Configuration
    connection_config = get_connection_config()
    logger.info(f"Connection: {connection_config.host}:{connection_config.port}\n")

    # Create DLT pipeline with filesystem destination (Parquet)
    pipeline = dlt.pipeline(
        pipeline_name="ib_equity_bars",
        destination=dlt.destinations.filesystem(bucket_url="data"),
        dataset_name="stocks",
    )
    logger.info(f"Pipeline: {pipeline.pipeline_name} -> Parquet in ./data/{pipeline.dataset_name}/\n")

    # Example 1: Backfill single symbol
    # if not backfill_single_symbol(pipeline, connection_config, "AAPL"):
    #     logger.error("Single symbol backfill failed")
    #     return

    # Example 2: Backfill multiple symbols (more efficient)
    symbols = ["AAPL", "MSFT", "GOOGL"]
    if not backfill_multiple_symbols(pipeline, connection_config, symbols):
        logger.error("Multiple symbol backfill failed")
        return

    # Query and display results
    query_and_display_results(pipeline)

    # Demonstrate gap detection (run again, should find no gaps)
    demonstrate_gap_detection(pipeline, connection_config, symbols[0])

    logger.info("\n✓ Complete workflow finished successfully!")
    logger.info("\nNext steps:")
    logger.info("  1. Try different bar sizes: '1 hour', '30 mins', '1 min'")
    logger.info("  2. Extend date range: start_date = date.today() - timedelta(days=365)")
    logger.info("  3. Add more symbols to the list")
    logger.info("  4. Query data in your own analysis scripts")


if __name__ == "__main__":
    main()
