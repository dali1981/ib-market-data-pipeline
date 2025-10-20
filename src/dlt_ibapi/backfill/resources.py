"""
DLT resources for market data backfilling.

These resources write data to DLT destinations with proper schema and deduplication.
"""

import dlt
from typing import Iterator, List, Optional
from datetime import date, datetime

from ib_connector import IBRuntime, SecDefService
from dlt_ibapi.config import IBConnectionConfig
from dlt_ibapi.config_loader import get_connection_config
from dlt_ibapi.resolution import ContractCache, ContractResolver
from dlt_ibapi.backfill.config import OptionChainSnapshotConfig


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
