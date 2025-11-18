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
from dlt_ibapi.backfill.download_planner import DownloadPlanner
from dlt_ibapi.repositories import OptionChainSnapshotReader, OptionBarsReader, EquityBarsReader
from dlt_ibapi.transformers import normalize_bar_data
from dlt_ibapi.utils.logging import get_logger
from dlt_ibapi.utils.ib_datetime import format_ib_end_datetime
from ib_connector import make_stock


def _calculate_timeout(bar_size: str, days_span: int, base_timeout: float = 30.0) -> float:
    """
    Calculate appropriate timeout based on bar size and duration.

    Intraday bars need more time per day due to higher data volume.
    Options data may require extra buffer due to liquidity and HMDS latency.

    Args:
        bar_size: IB bar size string (e.g., "5 mins", "1 hour", "1 day")
        days_span: Number of days in the request
        base_timeout: Base timeout in seconds (default: 30.0)

    Returns:
        Calculated timeout in seconds, capped at 300.0 (5 minutes)

    Examples:
        - Daily bars, 30 days: 30s (base timeout)
        - 5-min bars, 8 days: 30 + (8 × 10) = 110s
        - 1-min bars, 30 days: 30 + (30 × 10) = 300s (capped)
    """
    # Check if intraday bar size
    is_intraday = any(x in bar_size.lower() for x in ["min", "sec", "hour"])

    if is_intraday:
        # For intraday: add ~10 seconds per day to account for data volume
        # More bars = more processing time on IB's side
        timeout = base_timeout + (days_span * 10.0)
    else:
        # For daily/weekly/monthly: base timeout is sufficient
        timeout = base_timeout

    # Cap at 5 minutes to avoid indefinite hangs
    return min(timeout, 300.0)


def _get_runtime(config: Optional[IBConnectionConfig] = None) -> IBRuntime:
    """Create and start IBRuntime."""
    cfg = config if config is not None else get_connection_config()
    runtime = IBRuntime(host=cfg.host, port=cfg.port, client_id=cfg.client_id)
    runtime.start(ready_timeout=cfg.ready_timeout)
    return runtime


@dlt.resource(
    name="option_chain_snapshot",
    write_disposition="append",  # Append mode for Parquet (merge doesn't work with filesystem dest)
    primary_key=["underlying", "as_of", "exchange", "trading_class"],
    columns={
        "date": {"partition": True},  # Partition by snapshot date
    }
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

    Write disposition: append (primary key prevents duplicates on query)
    Primary key: [underlying, as_of, exchange, trading_class]

    Note: Duplicates are handled at query time using DISTINCT or GROUP BY.
    For true upsert behavior, use Delta Lake format (--delta flag).

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
    log = get_logger("dlt_ibapi.snapshot_option_chain")

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
            # This is expected for symbols without listed options (small-cap stocks)
            log.debug(f"No option chain parameters found for {underlying} (symbol has no listed options)")
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
                "date": snapshot_date.isoformat(),  # Partition column for Hive partitioning
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
    columns={
        "underlying": {"partition": True},  # Partition by underlying symbol only (optimal for Delta Lake)
    }
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
    log = get_logger("dlt_ibapi.backfill_option_bars")

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
    # Note: Snapshots are in 'option_chains' dataset, bars in 'options' dataset
    chain_reader = OptionChainSnapshotReader(database_path, 'option_chains')
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

        # Populate expirations and strikes from child tables
        # (DLT stores these in separate tables, but filter_contracts_by_selection_mode expects arrays)
        expirations = chain_reader.get_available_expirations(
            underlying=underlying,
            as_of=latest_snapshot_date,
            min_dte=backfill_config.min_dte,
            max_dte=backfill_config.max_dte,
        )
        if not expirations:
            log.warning(f"No expirations found in DTE range [{backfill_config.min_dte}, {backfill_config.max_dte}]")
            return

        # Filter to k closest expirations if requested
        if backfill_config.k_expirations is not None and len(expirations) > backfill_config.k_expirations:
            # Sort by expiration date (ascending = soonest first)
            expirations_sorted = sorted(expirations)
            expirations = expirations_sorted[:backfill_config.k_expirations]
            log.info(
                f"Filtered to {backfill_config.k_expirations} closest expirations "
                f"(out of {len(expirations_sorted)} available)"
            )

        # Get strikes (same for all expirations in IB option chains)
        strikes = chain_reader.get_strikes_for_expiry(
            underlying=underlying,
            as_of=latest_snapshot_date,
            expiry=expirations[0],  # Strikes are shared across expirations
        )

        # Add arrays to first row (filter_contracts expects this schema)
        # Create columns first before setting values
        chain["expirations"] = None
        chain["strikes"] = None
        chain.at[chain.index[0], "expirations"] = [exp.strftime("%Y%m%d") for exp in expirations]
        chain.at[chain.index[0], "strikes"] = strikes

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

        log.info("contracts_selected", count=len(contracts))
        log.debug("selected_contracts", contracts=[(str(e), s, r) for e, s, r in contracts])

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

            # Create download plan: find missing dates and batch optimally
            present_dates = bars_reader.get_present_dates_for_contract(
                underlying=underlying,
                expiry=expiry,
                strike=strike,
                right=right,
                bar_size=backfill_config.bar_size,
                start_date=backfill_config.start_date,
                end_date=min(backfill_config.end_date, expiry),
            )

            # Use DownloadPlanner for intelligent batching
            planner = DownloadPlanner(exchange="SMART", bar_size=backfill_config.bar_size)
            plan = planner.create_plan(
                start_date=backfill_config.start_date,
                end_date=min(backfill_config.end_date, expiry),
                existing_dates=present_dates if present_dates else None,
            )

            if not plan.batches:
                log.info(f"No data needed, already complete")
                continue

            log.info(
                f"Download plan: {plan.total_trading_days} trading days "
                f"in {plan.api_calls_required} API calls"
            )

            # Resolve contract (uses cache if available, saves to cache automatically)
            try:
                resolved = resolver.resolve_option_contract(
                    symbol=underlying,
                    expiry=expiry.strftime("%Y%m%d"),
                    strike=strike,
                    right=right,
                    exchange="SMART",
                    currency="USD",
                    use_cache=True,
                    save_to_cache=True,  # Automatically persists to cache
                )

                if not resolved:
                    log.error(f"No contract details found for {underlying} {expiry} {strike}{right}")
                    log.warning(f"Skipping contract - does not exist in IB system")
                    continue

                log.info(f"Resolved contract: conid={resolved['conid']}, local_symbol={resolved.get('local_symbol')}")

                # Create contract from resolved details
                # Use the resolver's internal method to get the actual Contract object
                from ib_connector import ContractDetailsService
                partial_contract = make_option(
                    symbol=underlying,
                    last_trade_date=expiry.strftime("%Y%m%d"),
                    strike=strike,
                    right=right,
                    exch="SMART",
                )
                contract_svc = ContractDetailsService(runtime)
                details_list = contract_svc.fetch(partial_contract, timeout=10.0)

                if not details_list:
                    log.error(f"ContractDetails returned empty for {underlying} {expiry} {strike}{right}")
                    continue

                # Use the ACTUAL Contract object from ContractDetails (not reconstructed)
                contract = details_list[0].contract

            except Exception as e:
                log.error(f"Failed to resolve contract {underlying} {expiry} {strike}{right}: {e}")
                log.warning(f"Skipping contract due to resolution failure")
                continue

            # Fetch bars for each batch
            for batch_start, batch_end in plan.batches:
                log.info(f"Fetching bars for batch: {batch_start} to {batch_end}")

                # Calculate duration for this batch
                days_span = (batch_end - batch_start).days + 1
                if days_span <= 30:
                    duration_str = f"{days_span} D"
                elif days_span <= 365:
                    if days_span >= 300:
                        duration_str = "1 Y"
                    else:
                        months = max(1, days_span // 30)
                        duration_str = f"{months} M"
                else:
                    years = max(1, days_span // 365)
                    duration_str = f"{years} Y"

                # Fetch historical bars with dynamic timeout
                # Use config override if provided, otherwise calculate based on bar size and duration
                if backfill_config.request_timeout is not None:
                    timeout = backfill_config.request_timeout
                    log.debug("using_config_timeout", timeout=timeout, bar_size=backfill_config.bar_size)
                else:
                    timeout = _calculate_timeout(backfill_config.bar_size, days_span)
                    log.debug("calculated_timeout", timeout=timeout, bar_size=backfill_config.bar_size, days_span=days_span)

                try:
                    bars = hist_svc.bars(
                        contract=contract,
                        endDateTime=format_ib_end_datetime(batch_end),
                        durationStr=duration_str,
                        barSizeSetting=backfill_config.bar_size,
                        whatToShow=backfill_config.what_to_show,
                        useRTH=1 if backfill_config.use_rth else 0,
                        timeout=timeout,
                    )

                    bar_count = 0
                    for bar in bars:
                        # Normalize and add contract identifiers
                        record = normalize_bar_data(bar, underlying, "SMART", "USD", backfill_config.bar_size)
                        record.update({
                            "underlying": underlying.upper(),
                            "expiry": expiry,
                            "strike": strike,
                            "right": right.upper(),
                            "bar_size": backfill_config.bar_size,
                        })

                        log.debug("yielding_bar", time=record.get('time'), open=record.get('open'),
                                 close=record.get('close'), volume=record.get('volume'))
                        yield record
                        bar_count += 1

                    log.info("batch_complete", bars_yielded=bar_count, batch_start=str(batch_start), batch_end=str(batch_end))

                except Exception as e:
                    log.error(f"Failed to fetch bars for {batch_start} to {batch_end}: {e}")
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
    name="historical_bars",
    write_disposition="append",
    primary_key=["symbol", "bar_size", "time"],
    columns={
        "symbol": {"partition": True},  # Partition by symbol only (optimal for Delta Lake)
    }
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
    log = get_logger("dlt_ibapi.backfill_equity_bars")

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

        # Step 2: Create download plan - optimized batching with IB API limits
        log.info(f"Creating download plan for {symbol} from {start_date} to {end_date}")

        present_dates = bars_reader.get_present_dates_for_symbol(
            symbol=symbol,
            bar_size=bar_size,
            start_date=start_date,
            end_date=end_date,
        )

        # Use DownloadPlanner for intelligent batching
        planner = DownloadPlanner(exchange="NYSE", bar_size=bar_size)
        plan = planner.create_plan(
            start_date=start_date,
            end_date=end_date,
            existing_dates=present_dates if present_dates else None,
        )

        if not plan.batches:
            log.info(f"No data needed for {symbol}, already complete")
            return

        log.info(
            f"Download plan for {symbol}: {plan.total_trading_days} trading days "
            f"in {plan.api_calls_required} API calls ({plan.strategy})"
        )

        # Step 3: Fetch bars for each batch
        hist_svc = HistoricalService(runtime)

        for batch_idx, (batch_start, batch_end) in enumerate(plan.batches, 1):
            log.info(
                f"[Batch {batch_idx}/{plan.api_calls_required}] Fetching {symbol} bars "
                f"from {batch_start} to {batch_end}"
            )

            # Create stock contract
            contract = make_stock(symbol, exch="SMART", curr="USD")

            # Calculate duration for this batch
            days_span = (batch_end - batch_start).days + 1

            # Use IB API duration string from planner's limit
            # For most cases, we can use days directly, but respect the limit format
            if days_span <= 30:
                duration_str = f"{days_span} D"
            elif days_span <= 365:
                # Use months or year format for better efficiency
                if days_span >= 300:
                    duration_str = "1 Y"
                else:
                    # Approximate months
                    months = max(1, days_span // 30)
                    duration_str = f"{months} M"
            else:
                # Multi-year (shouldn't happen for daily bars with our batching)
                years = max(1, days_span // 365)
                duration_str = f"{years} Y"

            # Fetch historical bars with dynamic timeout
            timeout = _calculate_timeout(bar_size, days_span)
            log.debug("calculated_timeout", timeout=timeout, bar_size=bar_size, days_span=days_span)

            try:
                bars = hist_svc.bars(
                    contract=contract,
                    endDateTime=format_ib_end_datetime(batch_end),
                    durationStr=duration_str,
                    barSizeSetting=bar_size,
                    whatToShow=what_to_show,
                    useRTH=1 if use_rth else 0,
                    timeout=timeout,
                )

                bar_count = 0
                for bar in bars:
                    # Normalize (bar_size now included in normalize_bar_data)
                    record = normalize_bar_data(bar, symbol, "SMART", "USD", bar_size)
                    record.update({
                        "symbol": symbol.upper(),
                    })

                    yield record
                    bar_count += 1

                if bar_count == 0:
                    log.warning(
                        f"No bars returned for {batch_start} to {batch_end} "
                        f"(market may have been closed - holiday or no trading)"
                    )
                else:
                    log.info(f"Yielded {bar_count} bars for batch {batch_start} to {batch_end}")

            except Exception as e:
                # IB errors come as exceptions with error codes
                # Common codes: 2174 (no data), 162 (HMDS error), 200 (no security def)
                error_str = str(e)

                # Extract IB error code if present
                if "IB error" in error_str and ":" in error_str:
                    # Format: "IB error REQID: CODE message"
                    parts = error_str.split(":")
                    if len(parts) >= 2:
                        code = parts[1].strip().split()[0]
                        log.warning(
                            f"IB API returned error {code} for {batch_start} to {batch_end}. "
                            f"Batch may contain non-trading days (holidays/weekends). "
                            f"Full error: {error_str}"
                        )
                    else:
                        log.error(f"IB error for {batch_start} to {batch_end}: {error_str}")
                else:
                    log.error(f"Failed to fetch bars for {batch_start} to {batch_end}: {error_str}")
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


@dlt.resource(
    name="contract_descriptions",
    write_disposition="merge",
    primary_key=["symbol", "conid"],
)
def resolve_contracts_resource(
    tickers: List[str],
    cache_path: str = ".dlt-ibapi/cache",
    connection_config: Optional[IBConnectionConfig] = None,
) -> Iterator[dict]:
    """
    DLT resource for resolving ticker symbols to IB contracts.

    Uses ContractResolver to resolve symbols and stores both contract
    descriptions (from MatchingSymbol) and details (from ContractDetails).

    Write disposition: merge (deduplication on primary key)
    Primary key: [symbol, conid]

    Args:
        tickers: List of ticker symbols to resolve
        cache_path: Path to contract cache
        connection_config: IB connection config (auto-loads if None)

    Yields:
        Contract description and detail records
    """
    log = get_logger("dlt_ibapi.resolve_contracts")

    runtime = _get_runtime(connection_config)
    cache = ContractCache(cache_path)
    resolver = ContractResolver(runtime, cache)

    try:
        for ticker in tickers:
            log.info(f"Resolving {ticker}")

            try:
                # Resolve using ContractResolver
                contract_info = resolver.resolve_symbol(
                    symbol=ticker,
                    exchange="SMART",
                    currency="USD",
                    sec_type="STK",
                    use_cache=True,
                    save_to_cache=True,
                )

                if not contract_info:
                    log.warning(f"Could not resolve {ticker}")
                    continue

                # Yield contract record
                yield {
                    "symbol": ticker.upper(),
                    "conid": contract_info.get("conid"),
                    "local_symbol": contract_info.get("local_symbol"),
                    "sec_type": contract_info.get("sec_type", "STK"),
                    "exchange": contract_info.get("exchange"),
                    "primary_exchange": contract_info.get("primary_exchange"),
                    "currency": contract_info.get("currency", "USD"),
                    "trading_class": contract_info.get("trading_class"),
                    "long_name": contract_info.get("long_name"),
                    "industry": contract_info.get("industry"),
                    "category": contract_info.get("category"),
                    "subcategory": contract_info.get("subcategory"),
                }

                log.info(f"✓ {ticker}: conid={contract_info.get('conid')}")

            except Exception as e:
                log.error(f"✗ {ticker}: {e}")
                continue

    finally:
        runtime.stop()


@dlt.resource(
    name="selected_option_contracts",
    write_disposition="merge",
    primary_key=["underlying", "expiry", "strike", "right", "strategy"],
    columns={
        "snapshot_date": {"partition": True},
        "underlying": {"partition": True},
    }
)
def select_option_contracts_resource(
    symbols: List[str],
    snapshot_date: date,
    database_path: str,
    dataset_name_stocks: str = "stocks",
    dataset_name_chains: str = "option_chains",
    cache_path: str = ".dlt-ibapi/cache",
    connection_config: Optional[IBConnectionConfig] = None,
    target_deltas: Optional[List[Tuple[str, float]]] = None,
    strategies: Optional[List[str]] = None,
    num_expirations: int = 3,
) -> Iterator[dict]:
    """
    DLT resource for selecting and resolving option contracts using delta strategies.

    Workflow:
    1. Read option chains from Parquet
    2. Read stock prices from Parquet
    3. Apply delta selection strategies
    4. Resolve selected strikes to IB contracts
    5. Yield contract records

    Write disposition: replace (full refresh for each snapshot date)
    Primary key: [underlying, expiry, strike, right, strategy]

    Args:
        symbols: List of underlying symbols
        snapshot_date: Snapshot date used for chains
        database_path: Path to DLT database
        dataset_name_stocks: Dataset name for stock data
        dataset_name_chains: Dataset name for option chains
        cache_path: Path to contract cache
        connection_config: IB connection config
        target_deltas: List of (right, delta) tuples (e.g., [("C", 0.30), ("P", -0.30)])
        strategies: List of strategies to use (default: ["closest_match", "black_scholes"])
        num_expirations: Number of expirations to process per symbol (default: 3)

    Yields:
        Selected option contract records with resolution details
    """
    log = get_logger("dlt_ibapi.select_option_contracts")

    # Default strategies and deltas
    if strategies is None:
        strategies = ["closest_match", "black_scholes"]

    if target_deltas is None:
        # Default to call deltas (0.30, 0.50, 0.70)
        # Puts will be handled by converting to negative in selection logic
        target_deltas = [
            ("C", 0.30),
            ("C", 0.50),
            ("C", 0.70),
            ("P", -0.30),
            ("P", -0.50),
            ("P", -0.70),
        ]

    stock_reader = EquityBarsReader(database_path, dataset_name_stocks)
    chain_reader = OptionChainSnapshotReader(database_path, dataset_name_chains)

    runtime = _get_runtime(connection_config)

    from ib_connector import ContractDetailsService
    details_service = ContractDetailsService(runtime)

    try:
        for symbol in symbols:
            log.info(f"Selecting contracts for {symbol}")

            # Get latest stock price
            try:
                stock_data = stock_reader.get_bars(
                    symbol=symbol,
                    bar_size="1 day",
                    start_date=snapshot_date - timedelta(days=5),
                    end_date=snapshot_date,
                )

                if stock_data.empty:
                    log.warning(f"No stock data for {symbol}, skipping")
                    continue

                spot_price = stock_data.iloc[-1]["close"]
                log.info(f"{symbol} spot price: ${spot_price:.2f}")

            except Exception as e:
                log.error(f"Error getting price for {symbol}: {e}")
                continue

            # Get option chain
            try:
                chain = chain_reader.get_chain_for_date(
                    underlying=symbol,
                    as_of=snapshot_date,
                )

                if chain.empty:
                    log.warning(f"No option chain for {symbol}, skipping")
                    continue

            except Exception as e:
                log.error(f"Error loading chain for {symbol}: {e}")
                continue

            # Get expirations
            expirations = chain_reader.get_available_expirations(
                underlying=symbol,
                as_of=snapshot_date,
            )

            if not expirations:
                log.warning(f"No expirations found for {symbol}")
                continue

            # Process each expiration
            for expiry in expirations[:num_expirations]:
                strikes = chain_reader.get_strikes_for_expiry(
                    underlying=symbol,
                    as_of=snapshot_date,
                    expiry=expiry,
                )

                if not strikes:
                    continue

                log.info(f"{symbol} {expiry}: {len(strikes)} strikes available")

                # Apply each strategy
                for strategy in strategies:
                    try:
                        # Select contracts using strategy
                        # Collect call and put target deltas
                        call_deltas = [d for (right, d) in target_deltas if right == "C"]
                        put_deltas = [d for (right, d) in target_deltas if right == "P"]

                        selected = []

                        # Select calls
                        if call_deltas and strategy == "closest_match":
                            from dlt_ibapi.backfill.contract_selection import select_k_around_atm
                            # Simple: select strikes around ATM
                            k = len(call_deltas)
                            call_strikes = select_k_around_atm(strikes, spot_price, k)
                            for strike in call_strikes:
                                selected.append({
                                    "strike": strike,
                                    "right": "C",
                                    "delta": None,
                                    "reason": f"closest_match_call"
                                })

                        elif call_deltas and strategy == "black_scholes":
                            from dlt_ibapi.backfill.contract_selection import select_by_delta
                            call_strikes = select_by_delta(
                                strikes=strikes,
                                spot_price=spot_price,
                                expiry=expiry,
                                as_of=snapshot_date,
                                target_deltas=call_deltas,
                                option_type="C",
                            )
                            for strike in call_strikes:
                                selected.append({
                                    "strike": strike,
                                    "right": "C",
                                    "delta": None,  # Could calculate if needed
                                    "reason": f"black_scholes_call"
                                })

                        # Select puts
                        if put_deltas and strategy == "closest_match":
                            from dlt_ibapi.backfill.contract_selection import select_k_around_atm
                            k = len(put_deltas)
                            put_strikes = select_k_around_atm(strikes, spot_price, k)
                            for strike in put_strikes:
                                selected.append({
                                    "strike": strike,
                                    "right": "P",
                                    "delta": None,
                                    "reason": f"closest_match_put"
                                })

                        elif put_deltas and strategy == "black_scholes":
                            from dlt_ibapi.backfill.contract_selection import select_by_delta
                            put_strikes = select_by_delta(
                                strikes=strikes,
                                spot_price=spot_price,
                                expiry=expiry,
                                as_of=snapshot_date,
                                target_deltas=[abs(d) for d in put_deltas],  # Use absolute values
                                option_type="P",
                            )
                            for strike in put_strikes:
                                selected.append({
                                    "strike": strike,
                                    "right": "P",
                                    "delta": None,
                                    "reason": f"black_scholes_put"
                                })

                        # Resolve each contract to IB contract details
                        for contract in selected:
                            opt_contract = make_option(
                                symbol=symbol,
                                last_trade_date=expiry.strftime("%Y%m%d"),
                                strike=contract["strike"],
                                right=contract["right"],
                                exch="SMART",
                            )

                            try:
                                details_results = details_service.fetch(opt_contract, timeout=10.0)

                                if details_results:
                                    detail = details_results[0]
                                    yield {
                                        "underlying": symbol.upper(),
                                        "expiry": expiry,
                                        "strike": contract["strike"],
                                        "right": contract["right"],
                                        "conid": detail.contract.conId,
                                        "local_symbol": detail.contract.localSymbol,
                                        "exchange": detail.contract.exchange,
                                        "trading_class": detail.contract.tradingClass,
                                        "multiplier": detail.multiplier,
                                        "strategy": strategy,
                                        "delta": contract.get("delta"),
                                        "reason": contract.get("reason", ""),
                                        "spot_price": spot_price,
                                        "snapshot_date": snapshot_date,
                                    }
                                else:
                                    log.warning(
                                        f"No contract details for {symbol} {expiry} "
                                        f"{contract['strike']}{contract['right']}"
                                    )

                            except Exception as e:
                                log.error(
                                    f"Failed to resolve {symbol} {expiry} "
                                    f"{contract['strike']}{contract['right']}: {e}"
                                )
                                continue

                    except Exception as e:
                        log.error(f"Error selecting contracts with {strategy}: {e}")
                        continue

    finally:
        runtime.stop()
