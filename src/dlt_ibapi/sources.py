"""DLT sources and resources for Interactive Brokers data."""

import dlt
from typing import Any, Iterator, Optional, List
from datetime import datetime

from ib_connector import (
    IBRuntime,
    ContractDetailsService,
    HistoricalService,
    SecDefService,
    make_stock,
    make_option,
)
from ibapi.contract import Contract

from .config import (
    IBConnectionConfig,
    IBHistoricalConfig,
    IBMarketDataConfig,
    IBOptionChainConfig,
)
from .config_loader import (
    get_connection_config,
    get_historical_config,
    get_market_data_config,
    get_option_chain_config,
)
from .transformers import (
    normalize_bar_data,
    normalize_contract_details,
    normalize_option_params,
)
from .utils.logging import get_logger


def _get_runtime(config: Optional[IBConnectionConfig] = None) -> IBRuntime:
    """
    Create and start an IBRuntime instance.

    If config is None, automatically loads from:
    1. .dlt-ibapi/ib_gateway.yaml (user config)
    2. Environment variables
    3. Package defaults
    """
    cfg = config if config is not None else get_connection_config()
    runtime = IBRuntime(host=cfg.host, port=cfg.port, client_id=cfg.client_id)
    runtime.start(ready_timeout=cfg.ready_timeout)
    return runtime


@dlt.resource(name="historical_bars")
def ib_historical_bars(
    symbol: str,
    exchange: str = "SMART",
    currency: str = "USD",
    sec_type: str = "STK",
    end_date: Optional[str] = None,
    connection_config: Optional[IBConnectionConfig] = None,
    hist_config: Optional[IBHistoricalConfig] = None,
) -> Iterator[dict]:
    """
    DLT resource for fetching historical bar data from IB.

    If connection_config or hist_config are not provided, they will be
    automatically loaded from:
    1. .dlt-ibapi/ib_gateway.yaml (user config)
    2. Environment variables
    3. Package defaults

    Args:
        symbol: Stock symbol (e.g., "AAPL")
        exchange: Exchange (default: "SMART")
        currency: Currency (default: "USD")
        sec_type: Security type (default: "STK")
        end_date: End date for historical data (default: now)
        connection_config: IB connection configuration (optional, auto-loads if None)
        hist_config: Historical data configuration (optional, auto-loads if None)

    Yields:
        Normalized bar data records
    """
    log = get_logger("dlt_ibapi.historical_bars")

    runtime = _get_runtime(connection_config)
    hist_cfg = hist_config if hist_config is not None else get_historical_config()

    try:
        hist_svc = HistoricalService(runtime)
        contract = make_stock(symbol, exch=exchange, curr=currency) if sec_type == "STK" else None

        if not contract:
            raise ValueError(f"Unsupported security type: {sec_type}")

        end_datetime = end_date or ""

        log.info(
            f"IB Request: symbol={symbol}, exchange={exchange}, currency={currency}, "
            f"sec_type={sec_type}, end_date='{end_datetime or 'now'}', "
            f"duration={hist_cfg.duration}, bar_size={hist_cfg.bar_size}, "
            f"what_to_show={hist_cfg.what_to_show}, use_rth={hist_cfg.use_rth}"
        )

        bars = hist_svc.bars(
            contract=contract,
            endDateTime=end_datetime,
            durationStr=hist_cfg.duration,
            barSizeSetting=hist_cfg.bar_size,
            whatToShow=hist_cfg.what_to_show,
            useRTH=1 if hist_cfg.use_rth else 0,
            timeout=hist_cfg.timeout,
        )

        bar_count = 0
        for bar in bars:
            yield normalize_bar_data(bar, symbol, exchange, currency, hist_cfg.bar_size)
            bar_count += 1

        log.info(f"Yielded {bar_count} bars for {symbol}")

    finally:
        runtime.stop()


@dlt.resource(name="market_data_snapshot")
def ib_market_data_snapshot(
    symbols: List[str],
    exchange: str = "SMART",
    currency: str = "USD",
    connection_config: Optional[IBConnectionConfig] = None,
    market_config: Optional[IBMarketDataConfig] = None,
) -> Iterator[dict]:
    """
    DLT resource for fetching market data snapshots.

    If connection_config or market_config are not provided, they will be
    automatically loaded from config files/env vars.

    Args:
        symbols: List of stock symbols
        exchange: Exchange (default: "SMART")
        currency: Currency (default: "USD")
        connection_config: IB connection configuration (optional, auto-loads if None)
        market_config: Market data configuration (optional, auto-loads if None)

    Yields:
        Market data snapshot records
    """
    runtime = _get_runtime(connection_config)
    market_cfg = market_config if market_config is not None else get_market_data_config()

    try:
        # For snapshots, we use ContractDetailsService to get basic info
        # Real-time snapshot would require SubscriptionService with snapshot=True
        contract_svc = ContractDetailsService(runtime)

        for symbol in symbols:
            contract = make_stock(symbol, exch=exchange, curr=currency)
            details = contract_svc.fetch(contract, timeout=market_cfg.timeout)

            for detail in details:
                yield {
                    "symbol": symbol,
                    "exchange": exchange,
                    "currency": currency,
                    "contract_id": detail.contract.conId,
                    "local_symbol": detail.contract.localSymbol,
                    "long_name": detail.longName,
                    "timestamp": datetime.utcnow().isoformat(),
                }

    finally:
        runtime.stop()


@dlt.resource(name="option_chain")
def ib_option_chain(
    symbol: str,
    conid: int,
    sec_type: str = "STK",
    exchange: str = "",
    connection_config: Optional[IBConnectionConfig] = None,
    option_config: Optional[IBOptionChainConfig] = None,
) -> Iterator[dict]:
    """
    DLT resource for fetching option chain parameters.

    If connection_config or option_config are not provided, they will be
    automatically loaded from config files/env vars.

    Args:
        symbol: Underlying symbol
        conid: Contract ID of underlying
        sec_type: Security type (default: "STK")
        exchange: Exchange (default: "")
        connection_config: IB connection configuration (optional, auto-loads if None)
        option_config: Option chain configuration (optional, auto-loads if None)

    Yields:
        Option chain parameter records
    """
    runtime = _get_runtime(connection_config)
    opt_cfg = option_config if option_config is not None else get_option_chain_config()

    try:
        secdef_svc = SecDefService(runtime)

        params = secdef_svc.option_params(
            symbol=symbol,
            conid=conid,
            sec_type=sec_type,
            exchange=opt_cfg.exchange,
            timeout=opt_cfg.timeout,
        )

        for param in params:
            yield normalize_option_params(param, symbol, conid)

    finally:
        runtime.stop()


@dlt.resource(name="contract_details")
def ib_contract_details(
    symbols: List[str],
    exchange: str = "SMART",
    currency: str = "USD",
    sec_type: str = "STK",
    connection_config: Optional[IBConnectionConfig] = None,
) -> Iterator[dict]:
    """
    DLT resource for fetching detailed contract information.

    If connection_config is not provided, it will be automatically loaded
    from config files/env vars.

    Args:
        symbols: List of symbols to fetch
        exchange: Exchange (default: "SMART")
        currency: Currency (default: "USD")
        sec_type: Security type (default: "STK")
        connection_config: IB connection configuration (optional, auto-loads if None)

    Yields:
        Contract detail records
    """
    runtime = _get_runtime(connection_config)

    try:
        contract_svc = ContractDetailsService(runtime)

        for symbol in symbols:
            contract = make_stock(symbol, exch=exchange, curr=currency) if sec_type == "STK" else None
            if not contract:
                continue

            details = contract_svc.fetch(contract, timeout=10.0)

            for detail in details:
                yield normalize_contract_details(detail, symbol)

    finally:
        runtime.stop()


@dlt.source(name="ib_source")
def ib_source(
    symbols: List[str],
    include_historical: bool = True,
    include_contract_details: bool = True,
    include_option_chain: bool = False,
    connection_config: Optional[IBConnectionConfig] = None,
) -> List[Any]:
    """
    Main DLT source for Interactive Brokers data.

    Combines multiple resources based on configuration.

    If connection_config is not provided, it will be automatically loaded
    from config files/env vars and shared across all resources.

    Args:
        symbols: List of symbols to fetch
        include_historical: Include historical bars
        include_contract_details: Include contract details
        include_option_chain: Include option chain data
        connection_config: IB connection configuration (optional, auto-loads if None)

    Returns:
        List of DLT resources
    """
    # Load config once if not provided (will be reused by resources)
    cfg = connection_config if connection_config is not None else get_connection_config()

    resources = []

    if include_contract_details:
        resources.append(ib_contract_details(symbols, connection_config=cfg))

    if include_historical:
        for symbol in symbols:
            resources.append(
                ib_historical_bars(symbol, connection_config=cfg)
            )

    return resources
