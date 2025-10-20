"""
DLT resources for market data backfilling.

These resources write data to DLT destinations with proper schema and deduplication.
"""

import dlt
from typing import Iterator, List, Optional, Tuple
from datetime import date, datetime, timedelta

from ib_connector import IBRuntime, SecDefService, HistoricalService, make_option
from dlt_ibapi.config import IBConnectionConfig, IBHistoricalConfig
from dlt_ibapi.config_loader import get_connection_config, get_historical_config
from dlt_ibapi.resolution import ContractCache, ContractResolver
from dlt_ibapi.backfill.config import OptionChainSnapshotConfig, OptionBackfillConfig
from dlt_ibapi.backfill.gap_detection import missing_windows
from dlt_ibapi.backfill.contract_selection import filter_contracts_by_selection_mode
from dlt_ibapi.repositories import OptionChainSnapshotReader, OptionBarsReader, EquityBarsReader
from dlt_ibapi.transformers import normalize_bar_data
from ib_connector import make_stock


def _get_runtime(config: Optional[IBConnectionConfig] = None) -> IBRuntime:
    """Create and start IBRuntime."""
    cfg = config if config is not None else get_connection_config()
    runtime = IBRuntime(host=cfg.host, port=cfg.port, client_id=cfg.client_id)
    runtime.start(ready_timeout=cfg.ready_timeout)
    return runtime


@dlt.resource(
    name="option_chain_snapshot",
    write_disposition="replace",  # Replace snapshots for same date
    primary_key=["underlying", "as_of", "exchange", "trading_class"],
)
def snapshot_option_chain(
    underlying: str,
    snapshot_date: date,
    cache_path: str = ".dlt-ibapi/cache",
    connection_config: Optional[IBConnectionConfig] = None,
    min_dte: int = 7,
    max_dte: int = 365,
) -> Iterator[dict]:
    """
    DLT resource for capturing option chain snapshots.

    Fetches option chain parameters (expirations, strikes, multiplier, etc.)
    and stores as aggregated snapshot for a specific date.

    Write disposition: replace (overwrites existing snapshot for same date)
    Primary key: [underlying, as_of, exchange, trading_class]

    Args:
        underlying: Underlying symbol (e.g., "AAPL")
        snapshot_date: Date to capture snapshot
        cache_path: Path to contract cache
        connection_config: IB connection config (auto-loads if None)
        min_dte: Minimum days to expiration filter
        max_dte: Maximum days to expiration filter

    Yields:
        Option chain snapshot records
    """
    import logging
    log = logging.getLogger("dlt_ibapi.snapshot_option_chain")

    runtime = _get_runtime(connection_config)
    cache = ContractCache(cache_path)
    resolver = ContractResolver(runtime, cache)

    try:
        # Step 1: Resolve underlying contract
        log.info(f"Resolving contract for {underlying}")
        contract_info = resolver.resolve_symbol(
            symbol=underlying,
            exchange="SMART",
            currency="USD",
            sec_type="STK",
        )

        if not contract_info:
            log.error(f"Could not resolve contract for {underlying}")
            return

        conid = contract_info["conid"]
        log.info(f"Resolved {underlying} to conid={conid}")

        # Step 2: Fetch option chain parameters
        log.info(f"Fetching option chain parameters for {underlying} (conid={conid})")
        secdef_svc = SecDefService(runtime)

        params = secdef_svc.option_params(
            symbol=underlying,
            conid=conid,
            sec_type="STK",
            exchange="",
            timeout=10.0,
        )

        if not params:
            log.warning(f"No option chain parameters found for {underlying}")
            return

        # Step 3: Transform and yield snapshots
        for param in params:
            # Filter expirations by DTE if needed
            expirations = param.get("expirations", [])
            strikes = param.get("strikes", [])

            # Calculate DTE for each expiration and filter
            filtered_expirations = []
            for exp_str in expirations:
                try:
                    # IB expiration format: "YYYYMMDD"
                    exp_date = datetime.strptime(exp_str, "%Y%m%d").date()
                    dte = (exp_date - snapshot_date).days

                    if min_dte <= dte <= max_dte:
                        filtered_expirations.append(exp_str)
                except Exception as e:
                    log.warning(f"Could not parse expiration {exp_str}: {e}")
                    continue

            if not filtered_expirations:
                log.info(f"No expirations in DTE range [{min_dte}, {max_dte}] for {param.get('exchange')}")
                continue

            record = {
                "underlying": underlying.upper(),
                "underlying_conid": conid,
                "exchange": param.get("exchange", ""),
                "trading_class": param.get("tradingClass", ""),
                "multiplier": str(param.get("multiplier", "")) if param.get("multiplier") else None,
                "expirations": filtered_expirations,
                "strikes": strikes,
                "expiration_count": len(filtered_expirations),
                "strike_count": len(strikes),
                "as_of": snapshot_date,
                "captured_at": datetime.utcnow(),
            }

            log.info(
                f"Snapshot: {underlying} {record['exchange']} - "
                f"{len(filtered_expirations)} expirations, {len(strikes)} strikes"
            )

            yield record

    finally:
        runtime.stop()


@dlt.source(name="option_chain_snapshots")
def option_chain_snapshots_source(
    underlyings: List[str],
    snapshot_date: date,
    cache_path: str = ".dlt-ibapi/cache",
    connection_config: Optional[IBConnectionConfig] = None,
    snapshot_config: Optional[OptionChainSnapshotConfig] = None,
) -> List:
    """
    DLT source for capturing option chain snapshots for multiple underlyings.

    Args:
        underlyings: List of underlying symbols
        snapshot_date: Date to capture snapshot
        cache_path: Path to contract cache
        connection_config: IB connection config (auto-loads if None)
        snapshot_config: Snapshot configuration (DTE filters, etc.)

    Returns:
        List of DLT resources
    """
    cfg = snapshot_config or OptionChainSnapshotConfig(snapshot_date=snapshot_date)

    resources = []
    for underlying in underlyings:
        resources.append(
            snapshot_option_chain(
                underlying=underlying,
                snapshot_date=cfg.snapshot_date,
                cache_path=cache_path,
                connection_config=connection_config,
                min_dte=cfg.min_dte,
                max_dte=cfg.max_dte,
            )
        )

    return resources


@dlt.resource(
    name="option_bars_backfill",
    write_disposition="append",
    primary_key=["underlying", "expiry", "strike", "right", "bar_size", "time"],
)
def backfill_option_bars(
    underlying: str,
    spot_price: float,
    database_path: str,
    dataset_name: str = "options",
    cache_path: str = ".dlt-ibapi/cache",
    connection_config: Optional[IBConnectionConfig] = None,
    backfill_config: Optional[OptionBackfillConfig] = None,
) -> Iterator[dict]:
    """
    DLT resource for backfilling historical option bars with gap detection.

    Workflow:
    1. Query option chain snapshot for available contracts
    2. Select contracts based on selection mode (ATM, moneyness, delta)
    3. For each contract, detect gaps in existing data
    4. Fetch missing bars from IB API
    5. Yield normalized bar data to DLT

    Write disposition: append (deduplicates via primary key)
    Primary key: [underlying, expiry, strike, right, bar_size, time]

    Args:
        underlying: Underlying symbol (e.g., "AAPL")
        spot_price: Current spot price (for contract selection)
        database_path: Path to DLT database (for gap detection)
        dataset_name: DLT dataset name
        cache_path: Path to contract cache
        connection_config: IB connection config (auto-loads if None)
        backfill_config: Backfill configuration

    Yields:
        Normalized option bar records
    """
    import logging
    log = logging.getLogger("dlt_ibapi.backfill_option_bars")

    # Default config
    if backfill_config is None:
        backfill_config = OptionBackfillConfig(
            start_date=date.today() - timedelta(days=30),
            end_date=date.today(),
        )

    runtime = _get_runtime(connection_config)
    cache = ContractCache(cache_path)
    resolver = ContractResolver(runtime, cache)

    # Readers for gap detection
    chain_reader = OptionChainSnapshotReader(database_path, dataset_name)
    bars_reader = OptionBarsReader(database_path, dataset_name)

    try:
        # Step 1: Get option chain snapshot for contract selection
        log.info(f"Loading option chain snapshot for {underlying}")

        # Find most recent snapshot
        snapshots = chain_reader.get_available_snapshots(underlying)
        if not snapshots:
            log.error(f"No option chain snapshots found for {underlying}. Run snapshot_option_chain first.")
            return

        latest_snapshot_date = max(snapshots)
        log.info(f"Using snapshot from {latest_snapshot_date}")

        chain = chain_reader.get_chain_for_date(
            underlying=underlying,
            as_of=latest_snapshot_date,
            min_dte=backfill_config.min_dte,
            max_dte=backfill_config.max_dte,
        )

        if chain.empty:
            log.warning(f"No option chain data found for {underlying}")
            return

        # Step 2: Select contracts based on mode
        log.info(f"Selecting contracts using mode: {backfill_config.selection_mode}")

        contracts = filter_contracts_by_selection_mode(
            chain_snapshot=chain,
            spot_price=spot_price,
            as_of=latest_snapshot_date,
            selection_mode=backfill_config.selection_mode.value,
            k_strikes=backfill_config.k_strikes,
            moneyness_levels=backfill_config.moneyness_levels,
            target_deltas=backfill_config.target_deltas,
            include_calls=backfill_config.include_calls,
            include_puts=backfill_config.include_puts,
        )

        log.info(f"Selected {len(contracts)} contracts for backfill")

        # Step 3: Backfill each contract
        hist_svc = HistoricalService(runtime)

        for idx, (expiry, strike, right) in enumerate(contracts, 1):
            log.info(
                f"[{idx}/{len(contracts)}] Processing {underlying} "
                f"{expiry} {strike} {right}"
            )

            # Check if contract is expired
            if expiry < backfill_config.start_date:
                log.info(f"Skipping expired contract (expiry={expiry})")
                continue

            # Gap detection: find missing dates
            present_dates = bars_reader.get_present_dates_for_contract(
                underlying=underlying,
                expiry=expiry,
                strike=strike,
                right=right,
                bar_size=backfill_config.bar_size,
                start_date=backfill_config.start_date,
                end_date=min(backfill_config.end_date, expiry),
            )

            gaps = missing_windows(
                present_dates=present_dates,
                start=backfill_config.start_date,
                end=min(backfill_config.end_date, expiry),
            )

            if not gaps:
                log.info(f"No gaps found, data complete")
                continue

            log.info(f"Found {len(gaps)} gaps to fill")

            # Fetch bars for each gap
            for gap_start, gap_end in gaps:
                log.info(f"Fetching bars for gap: {gap_start} to {gap_end}")

                # Create option contract
                contract = make_option(
                    symbol=underlying,
                    expiry=expiry.strftime("%Y%m%d"),
                    strike=strike,
                    right=right,
                    exchange="SMART",
                )

                # Fetch historical bars
                try:
                    bars = hist_svc.bars(
                        contract=contract,
                        endDateTime=gap_end.strftime("%Y%m%d 23:59:59"),
                        durationStr=f"{(gap_end - gap_start).days + 1} D",
                        barSizeSetting=backfill_config.bar_size,
                        whatToShow=backfill_config.what_to_show,
                        useRTH=1 if backfill_config.use_rth else 0,
                        timeout=30.0,
                    )

                    bar_count = 0
                    for bar in bars:
                        # Normalize and add contract identifiers
                        record = normalize_bar_data(bar, underlying, "SMART", "USD")
                        record.update({
                            "underlying": underlying.upper(),
                            "expiry": expiry,
                            "strike": strike,
                            "right": right.upper(),
                            "bar_size": backfill_config.bar_size,
                        })

                        yield record
                        bar_count += 1

                    log.info(f"Yielded {bar_count} bars for gap {gap_start} to {gap_end}")

                except Exception as e:
                    log.error(f"Failed to fetch bars for {gap_start} to {gap_end}: {e}")
                    continue

    finally:
        runtime.stop()


@dlt.source(name="option_bars_backfill_source")
def option_bars_backfill_source(
    underlying: str,
    spot_price: float,
    database_path: str,
    dataset_name: str = "options",
    cache_path: str = ".dlt-ibapi/cache",
    connection_config: Optional[IBConnectionConfig] = None,
    backfill_config: Optional[OptionBackfillConfig] = None,
) -> List:
    """
    DLT source wrapper for backfill_option_bars resource.

    Args:
        underlying: Underlying symbol
        spot_price: Current spot price
        database_path: Path to DLT database
        dataset_name: DLT dataset name
        cache_path: Path to contract cache
        connection_config: IB connection config
        backfill_config: Backfill configuration

    Returns:
        List containing backfill_option_bars resource
    """
    return [
        backfill_option_bars(
            underlying=underlying,
            spot_price=spot_price,
            database_path=database_path,
            dataset_name=dataset_name,
            cache_path=cache_path,
            connection_config=connection_config,
            backfill_config=backfill_config,
        )
    ]


@dlt.resource(
    name="equity_bars_backfill",
    write_disposition="append",
    primary_key=["symbol", "bar_size", "time"],
)
def backfill_equity_bars(
    symbol: str,
    database_path: str,
    dataset_name: str = "stocks",
    cache_path: str = ".dlt-ibapi/cache",
    connection_config: Optional[IBConnectionConfig] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    bar_size: str = "1 day",
    what_to_show: str = "TRADES",
    use_rth: bool = True,
) -> Iterator[dict]:
    """
    DLT resource for backfilling historical equity bars with gap detection.

    Workflow:
    1. Resolve symbol to IB Contract
    2. Detect gaps in existing data using EquityBarsReader
    3. Fetch missing bars from IB API for each gap
    4. Yield normalized bar data to DLT

    Write disposition: append (deduplicates via primary key)
    Primary key: [symbol, bar_size, time]

    Args:
        symbol: Stock symbol (e.g., "AAPL")
        database_path: Path to DLT database (for gap detection)
        dataset_name: DLT dataset name
        cache_path: Path to contract cache
        connection_config: IB connection config (auto-loads if None)
        start_date: Backfill start date (default: 30 days ago)
        end_date: Backfill end date (default: today)
        bar_size: IB bar size (e.g., "1 min", "1 hour", "1 day")
        what_to_show: Data type ("TRADES", "MIDPOINT", "BID", "ASK")
        use_rth: Regular trading hours only

    Yields:
        Normalized equity bar records
    """
    import logging
    log = logging.getLogger("dlt_ibapi.backfill_equity_bars")

    # Default date range
    if start_date is None:
        start_date = date.today() - timedelta(days=30)
    if end_date is None:
        end_date = date.today()

    runtime = _get_runtime(connection_config)
    cache = ContractCache(cache_path)
    resolver = ContractResolver(runtime, cache)

    # Reader for gap detection
    bars_reader = EquityBarsReader(database_path, dataset_name)

    try:
        # Step 1: Resolve symbol to IB Contract
        log.info(f"Resolving contract for {symbol}")
        contract_info = resolver.resolve_symbol(
            symbol=symbol,
            exchange="SMART",
            currency="USD",
            sec_type="STK",
        )

        if not contract_info:
            log.error(f"Could not resolve contract for {symbol}")
            return

        log.info(f"Resolved {symbol} to conid={contract_info['conid']}")

        # Step 2: Gap detection - find missing dates
        log.info(f"Checking coverage for {symbol} from {start_date} to {end_date}")

        present_dates = bars_reader.get_present_dates_for_symbol(
            symbol=symbol,
            bar_size=bar_size,
            start_date=start_date,
            end_date=end_date,
        )

        gaps = missing_windows(
            present_dates=present_dates,
            start=start_date,
            end=end_date,
        )

        if not gaps:
            log.info(f"No gaps found for {symbol}, data complete")
            return

        log.info(f"Found {len(gaps)} gaps to fill for {symbol}")

        # Step 3: Fetch bars for each gap
        hist_svc = HistoricalService(runtime)

        for gap_idx, (gap_start, gap_end) in enumerate(gaps, 1):
            log.info(
                f"[Gap {gap_idx}/{len(gaps)}] Fetching {symbol} bars "
                f"from {gap_start} to {gap_end}"
            )

            # Create stock contract
            contract = make_stock(
                symbol=symbol,
                exchange="SMART",
                currency="USD",
            )

            # Fetch historical bars
            try:
                bars = hist_svc.bars(
                    contract=contract,
                    endDateTime=gap_end.strftime("%Y%m%d 23:59:59"),
                    durationStr=f"{(gap_end - gap_start).days + 1} D",
                    barSizeSetting=bar_size,
                    whatToShow=what_to_show,
                    useRTH=1 if use_rth else 0,
                    timeout=30.0,
                )

                bar_count = 0
                for bar in bars:
                    # Normalize and add symbol + bar_size
                    record = normalize_bar_data(bar, symbol, "SMART", "USD")
                    record.update({
                        "symbol": symbol.upper(),
                        "bar_size": bar_size,
                    })

                    yield record
                    bar_count += 1

                log.info(f"Yielded {bar_count} bars for gap {gap_start} to {gap_end}")

            except Exception as e:
                log.error(f"Failed to fetch bars for {gap_start} to {gap_end}: {e}")
                continue

    finally:
        runtime.stop()


@dlt.source(name="equity_bars_backfill_source")
def equity_bars_backfill_source(
    symbols: List[str],
    database_path: str,
    dataset_name: str = "stocks",
    cache_path: str = ".dlt-ibapi/cache",
    connection_config: Optional[IBConnectionConfig] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    bar_size: str = "1 day",
    what_to_show: str = "TRADES",
    use_rth: bool = True,
) -> List:
    """
    DLT source for backfilling multiple equity symbols.

    Args:
        symbols: List of stock symbols
        database_path: Path to DLT database
        dataset_name: DLT dataset name
        cache_path: Path to contract cache
        connection_config: IB connection config
        start_date: Backfill start date
        end_date: Backfill end date
        bar_size: IB bar size
        what_to_show: Data type
        use_rth: Regular trading hours only

    Returns:
        List of backfill_equity_bars resources
    """
    resources = []
    for symbol in symbols:
        resources.append(
            backfill_equity_bars(
                symbol=symbol,
                database_path=database_path,
                dataset_name=dataset_name,
                cache_path=cache_path,
                connection_config=connection_config,
                start_date=start_date,
                end_date=end_date,
                bar_size=bar_size,
                what_to_show=what_to_show,
                use_rth=use_rth,
            )
        )

    return resources
