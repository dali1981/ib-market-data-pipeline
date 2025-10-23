"""Dagster assets for multi-ticker option data pipeline."""

from datetime import date, timedelta
from typing import List, Dict, Any
import logging

import pandas as pd
import dlt
from dagster import asset, AssetExecutionContext, Output, MetadataValue

from ib_connector import IBRuntime, MatchingSymbolService, ContractDetailsService, make_stock, make_option
from dlt_ibapi.config import IBConnectionConfig
from dlt_ibapi.config_loader import get_connection_config
from dlt_ibapi.resolution.contract_cache import ContractCache
from dlt_ibapi.resolution.resolver import ContractResolver
from dlt_ibapi.repositories.equity_bars import EquityBarsReader
from dlt_ibapi.repositories.option_chain import OptionChainSnapshotReader
from dlt_ibapi.repositories.option_bars import OptionBarsReader
from dlt_ibapi.backfill.resources import (
    backfill_equity_bars,
    snapshot_option_chain,
    backfill_option_bars,
)
from dlt_ibapi.backfill.config import OptionBackfillConfig, ContractSelectionMode

from dagster_options.config import get_default_config, OptionsPipelineConfig
from dagster_options.ticker_input import load_tickers
from dagster_options.selection_strategies import select_option_contracts as select_contracts_by_strategy

logger = logging.getLogger(__name__)


# ============================================================================
# Asset 1: Ticker Contracts Resolution
# ============================================================================


@asset(
    name="ticker_contracts",
    group_name="options_pipeline",
    description="Resolve ticker symbols to IB contracts via DLT",
    compute_kind="dlt",
)
def ticker_contracts(context: AssetExecutionContext) -> Output[Dict[str, Any]]:
    """
    Resolve ticker symbols to IB contracts using DLT resource.

    Workflow:
    1. Load ticker list from configured source
    2. Use resolve_contracts_resource DLT resource
    3. Store contracts in Parquet via DLT
    4. Return summary statistics

    Returns:
        Dict with summary info:
        - 'tickers_resolved': List of resolved tickers
        - 'num_tickers': Count of tickers processed
    """
    from dlt_ibapi.backfill.resources import resolve_contracts_resource

    config = get_default_config()

    context.log.info("Loading ticker list")
    tickers = load_tickers(config.ticker_source)
    context.log.info(f"Loaded {len(tickers)} tickers: {', '.join(tickers)}")

    # Create DLT pipeline
    pipeline = dlt.pipeline(
        pipeline_name="contract_resolution",
        destination="filesystem",
        dataset_name="contracts",
    )

    context.log.info(f"Resolving {len(tickers)} tickers via DLT")

    # Use DLT resource from library
    resource = resolve_contracts_resource(
        tickers=tickers,
        cache_path=config.cache_path,
        connection_config=get_connection_config(),
    )

    # Run pipeline
    load_info = pipeline.run(resource)

    context.log.info(f"✓ Contract resolution complete")
    context.log.info(f"Load info: {load_info}")

    return Output(
        value={
            "tickers_resolved": tickers,
            "num_tickers": len(tickers),
        },
        metadata={
            "num_tickers": len(tickers),
            "tickers": ", ".join(tickers),
            "pipeline_name": "contract_resolution",
            "dataset_name": "contracts",
        },
    )


# ============================================================================
# Asset 2: Stock Historical Data
# ============================================================================


@asset(
    name="stock_historical_data",
    group_name="options_pipeline",
    description="Fetch historical daily bars for resolved tickers",
    compute_kind="dlt",
)
def stock_historical_data(
    context: AssetExecutionContext,
    ticker_contracts: Dict[str, Any],
) -> Output[Dict[str, Any]]:
    """
    Fetch historical stock data using DLT with gap detection.

    Workflow:
    1. For each resolved ticker
    2. Use backfill_equity_bars DLT resource
    3. Detect and fill gaps in existing data
    4. Store in Parquet format

    Returns:
        Summary statistics dictionary
    """
    config = get_default_config()

    # Extract tickers from upstream asset
    symbols = ticker_contracts["tickers_resolved"]

    context.log.info(
        f"Fetching stock data for {len(symbols)} symbols "
        f"({config.stock_config.lookback_days} days lookback)"
    )

    # Create DLT pipeline
    pipeline = dlt.pipeline(
        pipeline_name="stock_historical_data",
        destination="filesystem",
        dataset_name=config.stock_dataset,
    )

    total_records = 0
    symbols_processed = []

    # Use client_id 2 for stock data (different from ticker_contracts which uses 1)
    ib_config = get_connection_config()
    stock_ib_config = IBConnectionConfig(
        host=ib_config.host,
        port=ib_config.port,
        client_id=ib_config.client_id + 1,  # client_id 2
        ready_timeout=ib_config.ready_timeout,
    )

    for symbol in symbols:
        context.log.info(f"Processing {symbol}")

        # Create DLT resource for this symbol with custom client_id
        resource = backfill_equity_bars(
            symbol=symbol,
            database_path=config.database_path,
            dataset_name=config.stock_dataset,
            cache_path=config.cache_path,
            connection_config=stock_ib_config,
            start_date=config.get_stock_start_date(),
            end_date=config.get_stock_end_date(),
            bar_size=config.stock_config.bar_size,
            what_to_show=config.stock_config.what_to_show,
            use_rth=config.stock_config.use_rth,
        )

        # Run pipeline
        load_info = pipeline.run(resource)

        # Pipeline ran successfully
        symbols_processed.append(symbol)
        context.log.info(f"✓ {symbol}: data loaded")

    return Output(
        value={
            "symbols_processed": symbols_processed,
        },
        metadata={
            "num_symbols": len(symbols_processed),
            "date_range": f"{config.get_stock_start_date()} to {config.get_stock_end_date()}",
        },
    )


# ============================================================================
# Asset 3: Option Chain Snapshots
# ============================================================================


@asset(
    name="option_chain_snapshots",
    group_name="options_pipeline",
    description="Capture option chain snapshots (expirations + strikes)",
    compute_kind="dlt",
)
def option_chain_snapshots(
    context: AssetExecutionContext,
    ticker_contracts: Dict[str, Any],
) -> Output[Dict[str, Any]]:
    """
    Capture option chain snapshots for each ticker.

    Workflow:
    1. For each resolved ticker
    2. Use snapshot_option_chain DLT resource
    3. Fetch available expirations and strikes
    4. Apply DTE filters
    5. Store snapshots in Parquet

    Returns:
        Summary statistics dictionary
    """
    config = get_default_config()
    snapshot_date = config.get_snapshot_date()

    # Extract tickers from upstream asset
    # Note: We process all tickers; snapshot_option_chain will skip those without options
    symbols = ticker_contracts["tickers_resolved"]

    context.log.info(
        f"Capturing option chains for {len(symbols)} symbols "
        f"(snapshot_date={snapshot_date}, DTE={config.chain_config.min_dte}-{config.chain_config.max_dte})"
    )

    # Use client_id 3 for option chain snapshots (different from ticker_contracts=1, stock_historical_data=2)
    ib_config = get_connection_config()
    chain_ib_config = IBConnectionConfig(
        host=ib_config.host,
        port=ib_config.port,
        client_id=ib_config.client_id + 2,  # client_id 3
        ready_timeout=ib_config.ready_timeout,
    )

    # Create DLT pipeline
    pipeline = dlt.pipeline(
        pipeline_name="option_chain_snapshots",
        destination="filesystem",
        dataset_name=config.chain_dataset,
    )

    chains_captured = []

    for symbol in symbols:
        context.log.info(f"Fetching option chain for {symbol}")

        # Create DLT resource for this symbol
        resource = snapshot_option_chain(
            underlying=symbol,
            snapshot_date=snapshot_date,
            cache_path=config.cache_path,
            connection_config=chain_ib_config,
            min_dte=config.chain_config.min_dte,
            max_dte=config.chain_config.max_dte,
        )

        # Run pipeline
        load_info = pipeline.run(resource)

        # Check if data was loaded (load_info has rows_count or metrics)
        if hasattr(load_info, 'metrics') and load_info.metrics:
            chains_captured.append(symbol)
            context.log.info(f"✓ {symbol}: option chain captured")
        elif load_info:
            # Pipeline ran successfully
            chains_captured.append(symbol)
            context.log.info(f"✓ {symbol}: option chain captured")
        else:
            context.log.warning(f"✗ {symbol}: no option chain data")

    return Output(
        value={
            "chains_captured": chains_captured,
            "snapshot_date": snapshot_date,
        },
        metadata={
            "num_chains": len(chains_captured),
            "snapshot_date": str(snapshot_date),
            "dte_range": f"{config.chain_config.min_dte}-{config.chain_config.max_dte} days",
            "symbols": MetadataValue.md("\n".join([f"- {sym}" for sym in chains_captured])),
        },
    )


# ============================================================================
# Asset 4: Selected Option Contracts
# ============================================================================


@asset(
    name="select_option_contracts",
    group_name="options_pipeline",
    description="Select option contracts using delta strategies via DLT",
    compute_kind="dlt",
)
def select_option_contracts(
    context: AssetExecutionContext,
    ticker_contracts: Dict[str, Any],
    stock_historical_data: Dict[str, Any],
    option_chain_snapshots: Dict[str, Any],
) -> Output[Dict[str, Any]]:
    """
    Select and resolve option contracts using DLT resource.

    Workflow:
    1. Use select_option_contracts_resource from library
    2. Resource reads stock prices and option chains from Parquet
    3. Applies delta strategies (closest_match, black_scholes)
    4. Resolves contracts via IB API
    5. Stores selected contracts in Parquet via DLT

    Returns:
        Dict with summary statistics
    """
    from dlt_ibapi.backfill.resources import select_option_contracts_resource

    config = get_default_config()
    snapshot_date = config.get_snapshot_date()
    symbols = option_chain_snapshots["chains_captured"]

    context.log.info(f"Selecting contracts for {len(symbols)} symbols using DLT")

    # Determine strategies to use
    strategies = []
    if config.enable_closest_match:
        strategies.append("closest_match")
    if config.enable_calculated_delta:
        strategies.append("black_scholes")

    context.log.info(f"Using strategies: {strategies}")

    # Create DLT pipeline
    pipeline = dlt.pipeline(
        pipeline_name="selected_option_contracts",
        destination="filesystem",
        dataset_name="selected_contracts",
    )

    # Use DLT resource from library
    # Use client_id 4 for option contract selection
    ib_config = get_connection_config()
    option_ib_config = IBConnectionConfig(
        host=ib_config.host,
        port=ib_config.port,
        client_id=ib_config.client_id + 3,  # client_id 4
        ready_timeout=ib_config.ready_timeout,
    )

    resource = select_option_contracts_resource(
        symbols=symbols,
        snapshot_date=snapshot_date,
        database_path=config.database_path,
        dataset_name_stocks=config.stock_dataset,
        dataset_name_chains=config.chain_dataset,
        cache_path=config.cache_path,
        connection_config=option_ib_config,
        target_deltas=[
            ("C", delta) for delta in config.delta_config.target_deltas
        ] + [
            ("P", -delta) for delta in config.delta_config.target_deltas
        ],
        strategies=strategies,
        num_expirations=3,
    )

    # Run pipeline
    load_info = pipeline.run(resource)

    context.log.info(f"✓ Contract selection complete")
    context.log.info(f"Load info: {load_info}")

    return Output(
        value={
            "contracts_selected": True,
            "symbols_processed": symbols,
            "snapshot_date": snapshot_date,
        },
        metadata={
            "num_symbols": len(symbols),
            "snapshot_date": str(snapshot_date),
            "strategies_used": strategies,
            "pipeline_name": "selected_option_contracts",
            "dataset_name": "selected_contracts",
        },
    )


# ============================================================================
# Asset 5: Option Historical Data
# ============================================================================


@asset(
    name="option_historical_data",
    group_name="options_pipeline",
    description="Backfill historical bars for selected option contracts",
    compute_kind="dlt",
)
def option_historical_data(
    context: AssetExecutionContext,
    select_option_contracts: Dict[str, Any],
) -> Output[Dict[str, Any]]:
    """
    Fetch historical data for selected option contracts using DLT.

    Workflow:
    1. Read selected contracts from Parquet
    2. Group by underlying symbol
    3. For each symbol, use backfill_option_bars DLT resource
    4. Detect and fill gaps in existing data
    5. Store in Parquet with partitioning

    Returns:
        Summary statistics dictionary
    """
    from dlt_ibapi.repositories.selected_contracts import SelectedContractsReader
    from dlt_ibapi.repositories.equity_bars import EquityBarsReader
    from dlt_ibapi.backfill.config import OptionBackfillConfig

    config = get_default_config()
    snapshot_date = select_option_contracts["snapshot_date"]

    # Read selected contracts from Parquet
    contracts_reader = SelectedContractsReader(config.database_path, "selected_contracts")
    selected_contracts = contracts_reader.get_all_contracts(snapshot_date=snapshot_date)

    if selected_contracts.empty:
        context.log.warning("No selected contracts found")
        return Output(
            value={"contracts_processed": 0},
            metadata={"num_contracts": 0},
        )

    context.log.info(f"Fetching option data for {len(selected_contracts)} contracts")

    # Read stock prices for spot price
    stock_reader = EquityBarsReader(config.database_path, config.stock_dataset)

    # Create DLT pipeline
    pipeline = dlt.pipeline(
        pipeline_name="option_historical_data",
        destination="filesystem",
        dataset_name=config.option_dataset,
    )

    # Use client_id 5 for option historical data
    ib_config = get_connection_config()
    option_hist_ib_config = IBConnectionConfig(
        host=ib_config.host,
        port=ib_config.port,
        client_id=ib_config.client_id + 4,  # client_id 5
        ready_timeout=ib_config.ready_timeout,
    )

    # Group by underlying
    symbols = selected_contracts["underlying"].unique()
    contracts_processed = 0

    for symbol in symbols:
        context.log.info(f"Processing {symbol}")

        # Get spot price from stock data
        try:
            stock_data = stock_reader.get_bars(
                symbol=symbol,
                bar_size=config.stock_config.bar_size,
                start_date=config.get_stock_end_date() - timedelta(days=5),
                end_date=config.get_stock_end_date(),
            )

            if stock_data.empty:
                context.log.warning(f"No stock data for {symbol}, skipping")
                continue

            spot_price = stock_data.iloc[-1]["close"]
            context.log.info(f"{symbol} spot price: ${spot_price:.2f}")

        except Exception as e:
            context.log.error(f"Error getting price for {symbol}: {e}")
            continue

        # Use backfill_option_bars resource
        resource = backfill_option_bars(
            underlying=symbol,
            spot_price=spot_price,
            database_path=config.database_path,
            dataset_name=config.option_dataset,
            cache_path=config.cache_path,
            connection_config=option_hist_ib_config,
            backfill_config=OptionBackfillConfig(
                start_date=config.get_option_start_date(),
                end_date=config.get_option_end_date(),
                bar_size=config.option_config.bar_size,
                what_to_show=config.option_config.what_to_show,
                use_rth=config.option_config.use_rth,
            ),
        )

        # Run pipeline
        load_info = pipeline.run(resource)

        symbol_contracts = selected_contracts[selected_contracts["underlying"] == symbol]
        contracts_processed += len(symbol_contracts)
        context.log.info(f"✓ {symbol}: {len(symbol_contracts)} contracts processed")

    return Output(
        value={
            "contracts_processed": contracts_processed,
            "symbols_processed": list(symbols),
        },
        metadata={
            "num_contracts": contracts_processed,
            "num_symbols": len(symbols),
            "lookback_days": config.option_config.lookback_days,
            "bar_size": config.option_config.bar_size,
        },
    )
