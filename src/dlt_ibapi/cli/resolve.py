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
from dlt_ibapi.repositories import EarningsCalendarReader
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


def execute_resolve_contracts(
    params: ResolveContractsParams,
    runtime: "IBRuntime" = None,  # For dependency injection in tests
) -> ResolveContractsResult:
    """
    Execute contract resolution for batch of symbols.

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
