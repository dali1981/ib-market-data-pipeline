"""Dagster assets for multi-ticker option data pipeline."""

from datetime import date, timedelta
from typing import List, Dict, Any
import logging

import pandas as pd
import dlt
from dagster import asset, AssetExecutionContext, Output, MetadataValue

from ib_connector import IBRuntime
from dlt_ibapi.config import IBConnectionConfig
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
from dagster_options.selection_strategies import select_option_contracts

logger = logging.getLogger(__name__)


# ============================================================================
# Asset 1: Ticker Contracts Resolution
# ============================================================================


@asset(
    name="ticker_contracts",
    group_name="options_pipeline",
    description="Resolve ticker symbols to IB contracts with caching",
    compute_kind="ib_api",
)
def ticker_contracts(context: AssetExecutionContext) -> Output[pd.DataFrame]:
    """
    Resolve ticker symbols to IB contracts.

    Workflow:
    1. Load ticker list from configured source
    2. For each ticker, check contract cache
    3. If not cached, resolve via IB API (match_symbol + contract_details)
    4. Save to cache automatically
    5. Return DataFrame of resolved contracts

    Returns:
        DataFrame with columns: symbol, conid, exchange, currency, sec_type
    """
    config = get_default_config()

    context.log.info("Loading ticker list")
    tickers = load_tickers(config.ticker_source)
    context.log.info(f"Loaded {len(tickers)} tickers: {', '.join(tickers)}")

    # Initialize IB runtime and resolver
    ib_config = IBConnectionConfig()
    runtime = IBRuntime(
        host=ib_config.host,
        port=ib_config.port,
        client_id=ib_config.client_id,
        ready_timeout=ib_config.ready_timeout,
    )

    cache = ContractCache(config.cache_path)
    resolver = ContractResolver(runtime, cache)

    resolved_contracts = []

    try:
        for ticker in tickers:
            context.log.info(f"Resolving contract for {ticker}")

            # Resolve symbol (checks cache first, then IB API)
            contract_data = resolver.resolve_symbol(
                symbol=ticker,
                exchange=config.stock_config.exchange,
                currency=config.stock_config.currency,
                sec_type="STK",
                use_cache=True,
                save_to_cache=True,
            )

            if contract_data:
                resolved_contracts.append(contract_data)
                context.log.info(
                    f"✓ {ticker}: conid={contract_data['conid']}, "
                    f"exchange={contract_data['exchange']}"
                )
            else:
                context.log.warning(f"✗ Failed to resolve {ticker}")

    finally:
        runtime.close()

    if not resolved_contracts:
        raise ValueError("No contracts were successfully resolved")

    # Convert to DataFrame
    df = pd.DataFrame(resolved_contracts)

    context.log.info(
        f"Resolved {len(df)} contracts out of {len(tickers)} tickers"
    )

    return Output(
        value=df,
        metadata={
            "num_tickers": len(tickers),
            "num_resolved": len(df),
            "success_rate": f"{len(df) / len(tickers) * 100:.1f}%",
            "symbols": MetadataValue.md("\n".join([f"- {row['symbol']}" for _, row in df.iterrows()])),
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
    ticker_contracts: pd.DataFrame,
) -> Output[Dict[str, Any]]:
    """
    Fetch historical stock data using DLT with gap detection.

    Workflow:
    1. For each resolved contract
    2. Use backfill_equity_bars DLT resource
    3. Detect and fill gaps in existing data
    4. Store in Parquet format

    Returns:
        Summary statistics dictionary
    """
    config = get_default_config()

    context.log.info(
        f"Fetching stock data for {len(ticker_contracts)} symbols "
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

    for _, contract in ticker_contracts.iterrows():
        symbol = contract["symbol"]

        context.log.info(f"Processing {symbol}")

        # Create DLT resource for this symbol
        resource = backfill_equity_bars(
            symbol=symbol,
            database_path=config.database_path,
            dataset_name=config.stock_dataset,
            cache_path=config.cache_path,
            start_date=config.get_stock_start_date(),
            end_date=config.get_stock_end_date(),
            bar_size=config.stock_config.bar_size,
            what_to_show=config.stock_config.what_to_show,
            use_rth=config.stock_config.use_rth,
        )

        # Run pipeline
        load_info = pipeline.run(resource)

        # Count records
        records = sum(
            pkg.state.get("finished_count", 0)
            for pkg in load_info.load_packages
        )

        total_records += records
        symbols_processed.append(symbol)

        context.log.info(f"✓ {symbol}: {records} bars loaded")

    return Output(
        value={
            "symbols_processed": symbols_processed,
            "total_records": total_records,
        },
        metadata={
            "num_symbols": len(symbols_processed),
            "total_bars": total_records,
            "avg_bars_per_symbol": total_records / len(symbols_processed) if symbols_processed else 0,
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
    ticker_contracts: pd.DataFrame,
) -> Output[Dict[str, Any]]:
    """
    Capture option chain snapshots for each ticker.

    Workflow:
    1. For each resolved contract
    2. Use snapshot_option_chain DLT resource
    3. Fetch available expirations and strikes
    4. Apply DTE filters
    5. Store snapshots in Parquet

    Returns:
        Summary statistics dictionary
    """
    config = get_default_config()
    snapshot_date = config.get_snapshot_date()

    context.log.info(
        f"Capturing option chains for {len(ticker_contracts)} symbols "
        f"(snapshot_date={snapshot_date}, DTE={config.chain_config.min_dte}-{config.chain_config.max_dte})"
    )

    # Create DLT pipeline
    pipeline = dlt.pipeline(
        pipeline_name="option_chain_snapshots",
        destination="filesystem",
        dataset_name=config.chain_dataset,
    )

    chains_captured = []

    for _, contract in ticker_contracts.iterrows():
        symbol = contract["symbol"]

        context.log.info(f"Fetching option chain for {symbol}")

        # Create DLT resource for this symbol
        resource = snapshot_option_chain(
            underlying=symbol,
            snapshot_date=snapshot_date,
            cache_path=config.cache_path,
            min_dte=config.chain_config.min_dte,
            max_dte=config.chain_config.max_dte,
        )

        # Run pipeline
        load_info = pipeline.run(resource)

        # Check if data was loaded
        records = sum(
            pkg.state.get("finished_count", 0)
            for pkg in load_info.load_packages
        )

        if records > 0:
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
    name="selected_option_contracts",
    group_name="options_pipeline",
    description="Select option contracts using multiple delta strategies",
    compute_kind="python",
)
def selected_option_contracts(
    context: AssetExecutionContext,
    ticker_contracts: pd.DataFrame,
    stock_historical_data: Dict[str, Any],
    option_chain_snapshots: Dict[str, Any],
) -> Output[pd.DataFrame]:
    """
    Select option contracts using all enabled delta strategies.

    Workflow:
    1. For each ticker with option chain
    2. Get latest stock price
    3. Load option chain snapshot
    4. Apply all enabled selection strategies:
       - Closest match (simple heuristic)
       - Black-Scholes calculated
       - IB API greeks (if enabled)
    5. Tag contracts with selection method
    6. Return consolidated DataFrame

    Returns:
        DataFrame with columns: underlying, expiry, strike, right, strategy, delta
    """
    config = get_default_config()

    context.log.info("Selecting option contracts using delta strategies")

    # Initialize readers
    stock_reader = EquityBarsReader(config.database_path, config.stock_dataset)
    chain_reader = OptionChainSnapshotReader(config.database_path, config.chain_dataset)

    all_selected_contracts = []

    # Process each symbol that has option chain
    for symbol in option_chain_snapshots["chains_captured"]:
        context.log.info(f"Selecting contracts for {symbol}")

        # Get latest stock price
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

            latest_price = stock_data.iloc[-1]["close"]
            context.log.info(f"{symbol} latest price: ${latest_price:.2f}")

        except Exception as e:
            context.log.error(f"Error getting price for {symbol}: {e}")
            continue

        # Load option chain
        try:
            chain = chain_reader.get_chain_for_date(
                underlying=symbol,
                as_of=config.get_snapshot_date(),
                min_dte=config.chain_config.min_dte,
                max_dte=config.chain_config.max_dte,
            )

            if chain.empty:
                context.log.warning(f"No option chain for {symbol}, skipping")
                continue

        except Exception as e:
            context.log.error(f"Error loading chain for {symbol}: {e}")
            continue

        # Get available expirations and strikes
        expirations = chain_reader.get_available_expirations(
            underlying=symbol,
            as_of=config.get_snapshot_date(),
            min_dte=config.chain_config.min_dte,
            max_dte=config.chain_config.max_dte,
        )

        if not expirations:
            context.log.warning(f"No expirations found for {symbol}")
            continue

        # Process each expiration
        for expiry in expirations[:3]:  # Limit to first 3 expirations
            strikes = chain_reader.get_strikes_for_expiry(
                underlying=symbol,
                as_of=config.get_snapshot_date(),
                expiry=expiry,
            )

            if not strikes:
                continue

            context.log.info(
                f"{symbol} {expiry}: {len(strikes)} strikes available"
            )

            # Apply each enabled strategy
            strategies_to_run = []
            if config.enable_closest_match:
                strategies_to_run.append("closest_match")
            if config.enable_calculated_delta:
                strategies_to_run.append("black_scholes")
            # Note: IB greeks requires live connection, skip for now
            # if config.enable_ib_greeks:
            #     strategies_to_run.append("ib_greeks")

            for strategy in strategies_to_run:
                try:
                    selected = select_option_contracts(
                        strikes=strikes,
                        spot_price=latest_price,
                        expiry=expiry,
                        as_of=config.get_snapshot_date(),
                        config=config.delta_config,
                        strategy=strategy,
                    )

                    for contract in selected:
                        all_selected_contracts.append({
                            "underlying": symbol,
                            "expiry": expiry,
                            "strike": contract["strike"],
                            "right": contract["right"],
                            "strategy": strategy,
                            "delta": contract.get("delta"),
                            "reason": contract["reason"],
                        })

                    context.log.info(
                        f"  {strategy}: selected {len(selected)} contracts"
                    )

                except Exception as e:
                    context.log.error(
                        f"Error in {strategy} for {symbol} {expiry}: {e}"
                    )

    if not all_selected_contracts:
        raise ValueError("No option contracts were selected")

    df = pd.DataFrame(all_selected_contracts)

    context.log.info(
        f"Selected {len(df)} total option contracts "
        f"across {df['underlying'].nunique()} symbols"
    )

    return Output(
        value=df,
        metadata={
            "total_contracts": len(df),
            "num_symbols": df["underlying"].nunique(),
            "strategies_used": list(df["strategy"].unique()),
            "contracts_by_strategy": df["strategy"].value_counts().to_dict(),
            "calls_vs_puts": df["right"].value_counts().to_dict(),
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
    selected_option_contracts: pd.DataFrame,
) -> Output[Dict[str, Any]]:
    """
    Fetch historical data for selected option contracts.

    Workflow:
    1. For each selected contract (underlying, expiry, strike, right)
    2. Use backfill_option_bars logic
    3. Fetch bars for lookback period (default 7 days)
    4. Apply gap detection
    5. Store in Parquet with partitioning

    Returns:
        Summary statistics dictionary
    """
    config = get_default_config()

    context.log.info(
        f"Fetching option data for {len(selected_option_contracts)} contracts "
        f"({config.option_config.lookback_days} days lookback)"
    )

    # Group by underlying for efficient processing
    grouped = selected_option_contracts.groupby("underlying")

    total_records = 0
    contracts_processed = 0

    for underlying, contracts in grouped:
        context.log.info(f"Processing {len(contracts)} contracts for {underlying}")

        # Get spot price (use latest from contracts DataFrame if available)
        # In production, would fetch from stock data
        # For now, estimate from ATM strikes
        atm_contracts = contracts[contracts["delta"].notna()]
        if not atm_contracts.empty:
            spot_price = atm_contracts["strike"].median()
        else:
            spot_price = contracts["strike"].median()

        context.log.info(f"Using spot price ${spot_price:.2f} for {underlying}")

        # Note: The backfill_option_bars resource expects to select contracts internally
        # We'll need to adapt this to work with pre-selected contracts
        # For now, log what would be processed

        for _, contract in contracts.iterrows():
            context.log.info(
                f"  Would fetch: {underlying} {contract['expiry']} "
                f"{contract['strike']}{contract['right']} ({contract['strategy']})"
            )
            contracts_processed += 1

        # TODO: Implement actual data fetching
        # This requires either:
        # 1. Modifying backfill_option_bars to accept pre-selected contracts
        # 2. Manually creating DLT resource for each contract
        # 3. Using lower-level HistoricalService directly

    context.log.info(
        f"Processed {contracts_processed} option contracts"
    )

    return Output(
        value={
            "contracts_processed": contracts_processed,
            "total_records": total_records,
        },
        metadata={
            "num_contracts": contracts_processed,
            "total_bars": total_records,
            "lookback_days": config.option_config.lookback_days,
            "bar_size": config.option_config.bar_size,
        },
    )
