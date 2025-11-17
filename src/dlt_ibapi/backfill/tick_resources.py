"""
DLT resources for backfilling tick-by-tick data.

Tick Data Schema (bid_ask):
    tick_time: datetime - Tick timestamp
    bid_price: float - Bid price
    ask_price: float - Ask price
    bid_size: int - Bid size
    ask_size: int - Ask size
    spread: float - ask - bid
    spread_pct: float - spread / midpoint * 100
    midpoint: float - (bid + ask) / 2
    underlying: str - Underlying symbol
    expiry: str - ISO date
    strike: float - Strike price
    right: 'C' | 'P' - Call or Put
    date: str - ISO date (YYYY-MM-DD) [partition]
    symbol: str - Same as underlying [partition]

Tick Data Schema (trades):
    tick_time: datetime - Tick timestamp
    price: float - Trade price
    size: int - Trade size
    exchange: str - Exchange
    special_conditions: str - Special conditions
    underlying: str - Underlying symbol
    expiry: str - ISO date
    strike: float - Strike price
    right: 'C' | 'P' - Call or Put
    date: str - ISO date (YYYY-MM-DD) [partition]
    symbol: str - Same as underlying [partition]
"""

import dlt
from datetime import datetime, date, timedelta
from typing import Iterator, Literal, Optional
from ib_connector import IBRuntime, HistoricalTick
from ib_connector.contracts import make_option
import logging

from ..config import IBConnectionConfig
from ..transformers import normalize_historical_tick_data

logger = logging.getLogger(__name__)


@dlt.resource(
    name="option_ticks_bid_ask",
    write_disposition="append",
    primary_key=["underlying", "expiry", "strike", "right", "tick_time"],
    columns={
        "date": {"partition": True},
        "symbol": {"partition": True},
    }
)
def backfill_option_ticks_bid_ask(
    underlying: str,
    expiry: date,
    strike: float,
    right: Literal['C', 'P'],
    start_datetime: datetime,
    end_datetime: datetime,
    exchange: str = "SMART",
    currency: str = "USD",
    connection_config: Optional[IBConnectionConfig] = None,
    use_rth: bool = True,
    timezone: str = "US/Eastern",
) -> Iterator[dict]:
    """
    Backfill bid/ask tick data for a single option contract.

    Args:
        underlying: Underlying symbol
        expiry: Option expiration date
        strike: Strike price
        right: 'C' for call, 'P' for put
        start_datetime: Start time (local time in specified timezone)
        end_datetime: End time (local time in specified timezone)
        exchange: Exchange (default SMART)
        currency: Currency (default USD)
        connection_config: IB connection config
        use_rth: Use regular trading hours only
        timezone: Timezone for datetime formatting (default US/Eastern)

    Yields:
        Normalized tick dictionaries

    Example:
        >>> from datetime import datetime, date
        >>> import dlt
        >>>
        >>> pipeline = dlt.pipeline(
        ...     pipeline_name="ib_ticks",
        ...     destination=dlt.destinations.filesystem(bucket_url="./data"),
        ...     dataset_name="option_ticks"
        ... )
        >>>
        >>> # Fetch ticks for TMC $5 call around 3:55pm entry
        >>> data = backfill_option_ticks_bid_ask(
        ...     underlying="TMC",
        ...     expiry=date(2025, 11, 21),
        ...     strike=5.0,
        ...     right='C',
        ...     start_datetime=datetime(2025, 11, 12, 15, 50),  # 3:50pm
        ...     end_datetime=datetime(2025, 11, 12, 16, 0),     # 4:00pm
        ... )
        >>>
        >>> info = pipeline.run(data, loader_file_format="parquet")
    """
    config = connection_config or IBConnectionConfig()

    with IBRuntime(
        host=config.host,
        port=config.port,
        client_id=config.client_id
    ) as runtime:
        # Create option contract
        contract = make_option(
            symbol=underlying,
            last_trade_date=expiry.strftime('%Y%m%d'),
            strike=strike,
            right=right,
            exch=exchange,
            curr=currency
        )

        # Fetch ticks
        ticks = runtime.tick_historical.fetch_historical_ticks_range(
            contract=contract,
            start_date=start_datetime,
            end_date=end_datetime,
            tick_type='BID_ASK',
            use_rth=use_rth,
            timezone=timezone
        )

        logger.info(f"Fetched {len(ticks)} ticks for {underlying} ${strike}{right}")
        if ticks:
            first = ticks[0]
            last = ticks[-1]
            logger.info(f"First tick: {first.time}, bid={first.bid_price}, ask={first.ask_price}")
            logger.info(f"Last tick: {last.time}, bid={last.bid_price}, ask={last.ask_price}")

        # Transform and yield
        for tick in ticks:
            yield normalize_historical_tick_data(
                tick=tick,
                underlying=underlying,
                expiry=expiry,
                strike=strike,
                right=right,
                tick_type='BID_ASK'
            )


@dlt.resource(
    name="option_ticks_trades",
    write_disposition="append",
    primary_key=["underlying", "expiry", "strike", "right", "tick_time"],
    columns={
        "date": {"partition": True},
        "symbol": {"partition": True},
    }
)
def backfill_option_ticks_trades(
    underlying: str,
    expiry: date,
    strike: float,
    right: Literal['C', 'P'],
    start_datetime: datetime,
    end_datetime: datetime,
    exchange: str = "SMART",
    currency: str = "USD",
    connection_config: Optional[IBConnectionConfig] = None,
    use_rth: bool = True,
    timezone: str = "US/Eastern",
) -> Iterator[dict]:
    """
    Backfill trade tick data for a single option contract.

    Args:
        underlying: Underlying symbol
        expiry: Option expiration date
        strike: Strike price
        right: 'C' for call, 'P' for put
        start_datetime: Start time (local time in specified timezone)
        end_datetime: End time (local time in specified timezone)
        exchange: Exchange (default SMART)
        currency: Currency (default USD)
        connection_config: IB connection config
        use_rth: Use regular trading hours only
        timezone: Timezone for datetime formatting (default US/Eastern)

    Yields:
        Normalized tick dictionaries

    Similar to backfill_option_ticks_bid_ask but returns trade ticks.
    """
    config = connection_config or IBConnectionConfig()

    with IBRuntime(
        host=config.host,
        port=config.port,
        client_id=config.client_id
    ) as runtime:
        contract = make_option(
            symbol=underlying,
            last_trade_date=expiry.strftime('%Y%m%d'),
            strike=strike,
            right=right,
            exch=exchange,
            curr=currency
        )

        # Fetch ticks
        ticks = runtime.tick_historical.fetch_historical_ticks_range(
            contract=contract,
            start_date=start_datetime,
            end_date=end_datetime,
            tick_type='TRADES',
            use_rth=use_rth,
            timezone=timezone
        )

        logger.info(f"Fetched {len(ticks)} trade ticks for {underlying} ${strike}{right}")
        if ticks:
            first = ticks[0]
            logger.info(f"First tick: {first.time}, price={first.price}, size={first.size}")

        for tick in ticks:
            yield normalize_historical_tick_data(
                tick=tick,
                underlying=underlying,
                expiry=expiry,
                strike=strike,
                right=right,
                tick_type='TRADES'
            )
