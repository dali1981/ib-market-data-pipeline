"""Business logic for contract resolution CLI command.

Handles batch contract resolution with proper error handling and reporting.
"""

import time
import json
from typing import List, Set
from pathlib import Path

from ib_connector import IBRuntime

from dlt_ibapi.config_loader import load_config
from dlt_ibapi.resolution.resolver import ContractResolver
from dlt_ibapi.resolution.contract_cache import ContractCache
from dlt_ibapi.repositories import EarningsCalendarReader, OptionChainSnapshotReader
from dlt_ibapi.utils.logging import get_logger
from dlt_ibapi.cli.models import (
    ResolveContractsParams,
    ResolveContractsResult,
    ContractResolutionInfo,
)

logger = get_logger(__name__)


def _load_symbols_from_earnings_db(
    database_path: Path,
    earnings_date: "date",
) -> List[str]:
    """
    Load symbols from earnings calendar database.

    Args:
        database_path: Path to data directory
        earnings_date: Date to filter earnings

    Returns:
        List of unique symbols
    """
    reader = EarningsCalendarReader(
        database_path=str(database_path),
        dataset_name="earnings",
    )

    df = reader.get_earnings_on_date(earnings_date)
    if df.empty:
        return []

    symbols = df["symbol"].unique().tolist()
    logger.info(f"Loaded {len(symbols)} symbols from earnings on {earnings_date}")
    return symbols


def _load_symbols_from_earnings_file(
    earnings_file: Path,
) -> List[str]:
    """
    Load symbols from earnings JSON file.

    Args:
        earnings_file: Path to earnings JSON file

    Returns:
        List of unique symbols
    """
    with open(earnings_file, "r") as f:
        data = json.load(f)

    # Handle both list and dict formats
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict) and "rows" in data:
        rows = data["rows"]
    else:
        raise ValueError(f"Unexpected JSON format in {earnings_file}")

    symbols = list({row["symbol"] for row in rows if "symbol" in row})
    logger.info(f"Loaded {len(symbols)} symbols from {earnings_file}")
    return symbols


def _load_option_contracts_from_snapshot(
    database_path: Path,
    snapshot_date: "date" = None,
    underlying: str = None,
) -> List[tuple]:
    """
    Load option contracts from snapshot data.

    Args:
        database_path: Path to data directory
        snapshot_date: Snapshot date to load
        underlying: Optional filter by underlying symbol

    Returns:
        List of tuples (symbol, expiry, strike, right)
    """
    reader = OptionChainSnapshotReader(
        database_path=str(database_path),
        dataset_name="option_chains",
    )

    # Determine which underlying symbols to process
    if underlying:
        symbols = [underlying.upper()]
    elif snapshot_date:
        # Get all underlyings from this snapshot date
        # Query all snapshots and filter by date
        table_name = reader._get_table_name()
        query = f"""
            SELECT DISTINCT underlying
            FROM {table_name}
            WHERE date = $snapshot_date_str
        """
        params = {"snapshot_date_str": snapshot_date.isoformat()}
        df = reader._query_with_duckdb(query, params)
        if df.empty:
            logger.warning(f"No snapshots found for date={snapshot_date}")
            return []
        symbols = df["underlying"].tolist()
    else:
        logger.error("Must provide either snapshot_date or underlying")
        return []

    logger.info(f"Processing {len(symbols)} underlying symbols: {', '.join(symbols)}")

    # Expand snapshots into individual contracts
    contracts = []
    for symbol in symbols:
        # Use the snapshot_date directly as as_of
        # (We already filtered symbols by snapshot_date in the query above)
        as_of = snapshot_date

        logger.info(f"Loading {symbol} snapshot from {as_of}")

        # Get expirations and strikes for this snapshot
        expirations = reader.get_available_expirations(
            underlying=symbol,
            as_of=as_of,
        )

        if not expirations:
            logger.warning(f"No expirations found for {symbol} on {as_of}")
            continue

        strikes = reader.get_strikes_for_expiry(
            underlying=symbol,
            as_of=as_of,
            expiry=expirations[0],  # Strikes are shared across expirations
        )

        if not strikes:
            logger.warning(f"No strikes found for {symbol} on {as_of}")
            continue

        # Generate all combinations: expiry × strike × right (C/P)
        for expiry in expirations:
            for strike in strikes:
                for right in ["C", "P"]:
                    contracts.append((symbol, expiry.strftime("%Y%m%d"), strike, right))

    logger.info(f"Loaded {len(contracts)} option contracts from snapshots")
    return contracts


def execute_resolve_contracts(
    params: ResolveContractsParams,
    runtime: "IBRuntime" = None,  # For dependency injection in tests
) -> ResolveContractsResult:
    """
    Execute contract resolution for batch of symbols or option contracts.

    Routes to equity or option resolution based on sec_type parameter.

    Args:
        params: Validated parameters
        runtime: Optional IBRuntime (for testing)

    Returns:
        ResolveContractsResult with success/failure details
    """
    if params.sec_type == "OPT":
        return _execute_resolve_option_contracts(params, runtime)
    else:
        return _execute_resolve_equity_contracts(params, runtime)


def _execute_resolve_equity_contracts(
    params: ResolveContractsParams,
    runtime: "IBRuntime" = None,
) -> ResolveContractsResult:
    """
    Execute contract resolution for equity symbols.

    Workflow:
    1. Load symbols from source (explicit list, earnings DB, or file)
    2. Check cache for already-resolved contracts
    3. Resolve new symbols via IB API (with error handling per symbol)
    4. Save to cache
    5. Return summary

    Args:
        params: Validated parameters
        runtime: Optional IBRuntime (for testing)

    Returns:
        ResolveContractsResult with success/failure details
    """
    start_time = time.time()

    try:
        # Step 1: Load symbols
        symbols = _get_symbols(params)
        if not symbols:
            return ResolveContractsResult(
                success=False,
                total_requested=0,
                cache_path=params.cache_path,
                duration_seconds=time.time() - start_time,
                error="No symbols provided. Use --symbols, --earnings-date, or --earnings-file",
            )

        logger.info(f"Resolving {len(symbols)} symbols: {', '.join(symbols)}")

        # Step 2: Initialize cache and runtime
        cache = ContractCache(base_path=str(params.cache_path))

        # Check which symbols are already cached
        cached_symbols = _get_cached_symbols(cache, symbols, params.sec_type)
        new_symbols = [s for s in symbols if s not in cached_symbols]

        logger.info(f"Found {len(cached_symbols)} symbols in cache, {len(new_symbols)} to resolve")

        resolved: List[ContractResolutionInfo] = []
        failed: dict[str, str] = {}
        skipped: List[str] = list(cached_symbols)

        # Step 3: Resolve new symbols
        if new_symbols:
            # Initialize runtime if not provided (for testing)
            if runtime is None:
                config = load_config()
                conn_cfg = config.connection
                runtime = IBRuntime(
                    host=conn_cfg.host,
                    port=conn_cfg.port,
                    client_id=conn_cfg.client_id,
                )
                runtime.start(ready_timeout=conn_cfg.ready_timeout)
                runtime_started = True
            else:
                runtime_started = False

            try:
                resolver = ContractResolver(
                    runtime=runtime,
                    cache=cache,
                )

                # Resolve each symbol with error handling
                for symbol in new_symbols:
                    try:
                        logger.info(f"Resolving {symbol}...")
                        result = resolver.resolve_symbol(
                            symbol=symbol,
                            exchange=params.exchange,
                            currency=params.currency,
                            sec_type=params.sec_type,
                            use_cache=False,  # We already checked
                            save_to_cache=True,
                            timeout=params.timeout,
                        )

                        if result:
                            resolved.append(
                                ContractResolutionInfo(
                                    symbol=result["symbol"],
                                    conid=result["conid"],
                                    exchange=result.get("primary_exchange") or result.get("exchange"),
                                    currency=result["currency"],
                                    long_name=result.get("long_name"),
                                )
                            )
                            logger.info(f"✓ {symbol} -> conid={result['conid']}")
                        else:
                            failed[symbol] = "No contract details returned from IB API"
                            logger.warning(f"✗ {symbol}: No contract details found")

                    except Exception as e:
                        error_msg = str(e)
                        failed[symbol] = error_msg
                        logger.error(f"✗ {symbol}: {error_msg}")
                        continue  # Continue with next symbol

            finally:
                if runtime_started:
                    runtime.stop()

        # Step 4: Return results
        duration = time.time() - start_time
        success = len(failed) == 0 and len(symbols) > 0

        return ResolveContractsResult(
            success=success,
            total_requested=len(symbols),
            resolved=resolved,
            failed=failed,
            skipped=skipped,
            cache_path=params.cache_path,
            duration_seconds=duration,
        )

    except Exception as e:
        logger.exception("Failed to resolve contracts")
        return ResolveContractsResult(
            success=False,
            total_requested=len(symbols) if 'symbols' in locals() else 0,
            cache_path=params.cache_path,
            duration_seconds=time.time() - start_time,
            error=str(e),
        )


def _execute_resolve_option_contracts(
    params: ResolveContractsParams,
    runtime: "IBRuntime" = None,
) -> ResolveContractsResult:
    """
    Execute contract resolution for option contracts.

    Workflow:
    1. Load option contracts from snapshot data
    2. Check cache for already-resolved contracts
    3. Resolve new contracts via IB API (with error handling per contract)
    4. Save to cache
    5. Return summary

    Args:
        params: Validated parameters
        runtime: Optional IBRuntime (for testing)

    Returns:
        ResolveContractsResult with success/failure details
    """
    start_time = time.time()

    try:
        # Step 1: Load option contracts from snapshots
        if not params.snapshot_date and not params.underlying:
            return ResolveContractsResult(
                success=False,
                total_requested=0,
                cache_path=params.cache_path,
                duration_seconds=time.time() - start_time,
                error="For option resolution, provide --snapshot-date and/or --underlying",
            )

        contracts = _load_option_contracts_from_snapshot(
            database_path=params.database_path,
            snapshot_date=params.snapshot_date,
            underlying=params.underlying,
        )

        if not contracts:
            return ResolveContractsResult(
                success=False,
                total_requested=0,
                cache_path=params.cache_path,
                duration_seconds=time.time() - start_time,
                error="No option contracts found in snapshots",
            )

        logger.info(f"Resolving {len(contracts)} option contracts")

        # Step 2: Initialize cache and runtime
        cache = ContractCache(base_path=str(params.cache_path))

        # Check which contracts are already cached
        cached_contracts = []
        new_contracts = []

        for symbol, expiry, strike, right in contracts:
            cached = cache.get_option_contract(symbol, expiry, strike, right)
            if cached:
                cached_contracts.append((symbol, expiry, strike, right))
            else:
                new_contracts.append((symbol, expiry, strike, right))

        logger.info(f"Found {len(cached_contracts)} contracts in cache, {len(new_contracts)} to resolve")

        resolved: List[ContractResolutionInfo] = []
        failed: dict[str, str] = {}
        skipped: List[str] = [f"{s} {e} {st}{r}" for s, e, st, r in cached_contracts]

        # Step 3: Resolve new contracts
        if new_contracts:
            # Initialize runtime if not provided (for testing)
            if runtime is None:
                config = load_config()
                conn_cfg = config.connection
                runtime = IBRuntime(
                    host=conn_cfg.host,
                    port=conn_cfg.port,
                    client_id=conn_cfg.client_id,
                )
                runtime.start(ready_timeout=conn_cfg.ready_timeout)
                runtime_started = True
            else:
                runtime_started = False

            try:
                resolver = ContractResolver(
                    runtime=runtime,
                    cache=cache,
                )

                # Resolve each contract with error handling
                for symbol, expiry, strike, right in new_contracts:
                    contract_id = f"{symbol} {expiry} {strike}{right}"
                    try:
                        logger.info(f"Resolving {contract_id}...")
                        result = resolver.resolve_option_contract(
                            symbol=symbol,
                            expiry=expiry,
                            strike=strike,
                            right=right,
                            exchange=params.exchange,
                            currency=params.currency,
                            use_cache=False,  # We already checked
                            save_to_cache=True,
                            timeout=params.timeout,
                        )

                        if result:
                            resolved.append(
                                ContractResolutionInfo(
                                    symbol=result["symbol"],
                                    conid=result["conid"],
                                    exchange=result.get("primary_exchange") or result.get("exchange"),
                                    currency=result["currency"],
                                    sec_type="OPT",
                                    long_name=result.get("long_name"),
                                    strike=result.get("strike"),
                                    right=result.get("right"),
                                    expiry=result.get("last_trade_date"),
                                    local_symbol=result.get("local_symbol"),
                                )
                            )
                            logger.info(f"✓ {contract_id} -> conid={result['conid']}")
                        else:
                            failed[contract_id] = "No contract details returned from IB API"
                            logger.warning(f"✗ {contract_id}: No contract details found")

                    except Exception as e:
                        error_msg = str(e)
                        failed[contract_id] = error_msg
                        logger.error(f"✗ {contract_id}: {error_msg}")
                        continue  # Continue with next contract

            finally:
                if runtime_started:
                    runtime.stop()

        # Step 4: Return results
        duration = time.time() - start_time
        success = len(failed) == 0 and len(contracts) > 0

        return ResolveContractsResult(
            success=success,
            total_requested=len(contracts),
            resolved=resolved,
            failed=failed,
            skipped=skipped,
            cache_path=params.cache_path,
            duration_seconds=duration,
        )

    except Exception as e:
        logger.exception("Failed to resolve option contracts")
        return ResolveContractsResult(
            success=False,
            total_requested=len(contracts) if 'contracts' in locals() else 0,
            cache_path=params.cache_path,
            duration_seconds=time.time() - start_time,
            error=str(e),
        )


def _get_symbols(params: ResolveContractsParams) -> List[str]:
    """Get symbols from all sources."""
    symbols: Set[str] = set()

    if params.symbols:
        symbols.update(params.symbols)

    if params.earnings_date:
        earnings_symbols = _load_symbols_from_earnings_db(
            params.database_path,
            params.earnings_date,
        )
        symbols.update(earnings_symbols)

    if params.earnings_file:
        file_symbols = _load_symbols_from_earnings_file(params.earnings_file)
        symbols.update(file_symbols)

    return sorted(symbols)


def _get_cached_symbols(cache: ContractCache, symbols: List[str], sec_type: str) -> Set[str]:
    """Check which symbols are already in cache."""
    cached = set()
    for symbol in symbols:
        df = cache.get_contracts_by_symbol(symbol, sec_type=sec_type)
        if not df.empty:
            cached.add(symbol)
    return cached
