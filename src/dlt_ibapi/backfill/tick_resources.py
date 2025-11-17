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
import pytz
from ib_connector import IBRuntime
from ib_connector.contracts import make_option
from ib_connector.services import ContractDetailsService, TickHistoricalService
import logging

from ..config import IBConnectionConfig
from ..transformers import normalize_historical_tick_data

logger = logging.getLogger(__name__)


def _format_ib_datetime(dt: datetime, timezone_str: str) -> str:
    """Format datetime for IB API with timezone."""
    if dt.tzinfo is None:
        tz = pytz.timezone(timezone_str)
        dt = tz.localize(dt)
    return dt.strftime("%Y%m%d %H:%M:%S") + f" {timezone_str}"


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

        # Resolve contract to get ConId
        logger.info(f"Resolving contract: {underlying} ${strike}{right} exp {expiry.strftime('%Y%m%d')}")
        contract_svc = ContractDetailsService(runtime)

        try:
            details_list = contract_svc.fetch(contract)
        except RuntimeError as e:
            logger.error(f"Contract resolution failed: {e}")
            logger.error(f"Contract details: symbol={underlying}, strike={strike}, right={right}, expiry={expiry.strftime('%Y%m%d')}, exchange={exchange}")
            logger.error("Possible causes:")
            logger.error("  1. Contract does not exist (wrong strike/expiry)")
            logger.error("  2. Option has already expired")
            logger.error("  3. Symbol is incorrect or not available")
            raise RuntimeError(
                f"Cannot resolve contract {underlying} ${strike}{right} exp {expiry.strftime('%Y%m%d')}. "
                f"Contract may not exist or has expired. Original error: {e}"
            )

        if not details_list:
            logger.error(f"No contract details found for {underlying} ${strike}{right} exp {expiry.strftime('%Y%m%d')}")
            logger.error(f"Contract: symbol={underlying}, strike={strike}, right={right}, expiry={expiry.strftime('%Y%m%d')}, exchange={exchange}")
            raise RuntimeError(
                f"No contract found for {underlying} ${strike}{right} exp {expiry.strftime('%Y%m%d')}. "
                "Contract may not exist or has expired."
            )

        contract = details_list[0].contract
        logger.info(f"✓ Contract resolved: ConId={contract.conId}, LocalSymbol={contract.localSymbol}")

        # Create tick service
        tick_svc = TickHistoricalService(runtime)

        # Make timezone-aware
        tz = pytz.timezone(timezone)
        if start_datetime.tzinfo is None:
            start_datetime = tz.localize(start_datetime)
        if end_datetime.tzinfo is None:
            end_datetime = tz.localize(end_datetime)

        # Pagination loop - yield ticks as they arrive
        current_start = start_datetime
        total_ticks = 0
        request_count = 0

        while current_start < end_datetime:
            request_count += 1
            start_str = _format_ib_datetime(current_start, timezone)

            logger.info(f"Request #{request_count}: start={current_start}")

            # Make request (IB API requires ONLY startDateTime, not both)
            result = tick_svc.ticks(
                contract=contract,
                startDateTime=start_str,
                endDateTime="",  # Empty = not used
                numberOfTicks=1000,
                whatToShow='BID_ASK',
                useRth=1 if use_rth else 0,
                ignoreSize=False,
                timeout=30.0
            )

            # Extract ticks and done flag
            ticks = result.get('items', result) if isinstance(result, dict) else result
            done = result.get('done', True) if isinstance(result, dict) else True

            logger.info(f"  Received {len(ticks)} ticks")

            # Yield ticks immediately (streaming, no accumulation)
            for tick in ticks:
                yield normalize_historical_tick_data(
                    tick=tick,
                    underlying=underlying,
                    expiry=expiry,
                    strike=strike,
                    right=right,
                    tick_type='BID_ASK'
                )
                total_ticks += 1

            # Update start time for next request
            if ticks:
                last_tick = ticks[-1]
                last_tick_dt = datetime.fromtimestamp(last_tick.time, tz=tz)

                # Check if we've reached the end time
                if last_tick_dt >= end_datetime:
                    logger.info(f"Reached end time: {last_tick_dt}")
                    break

                current_start = last_tick_dt
            else:
                # No ticks received
                logger.info("No more ticks available")
                break

        logger.info(f"Total: {total_ticks} ticks from {request_count} requests")


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

        # Resolve contract to get ConId
        logger.info(f"Resolving contract: {underlying} ${strike}{right} exp {expiry.strftime('%Y%m%d')}")
        contract_svc = ContractDetailsService(runtime)

        try:
            details_list = contract_svc.fetch(contract)
        except RuntimeError as e:
            logger.error(f"Contract resolution failed: {e}")
            logger.error(f"Contract details: symbol={underlying}, strike={strike}, right={right}, expiry={expiry.strftime('%Y%m%d')}, exchange={exchange}")
            logger.error("Possible causes:")
            logger.error("  1. Contract does not exist (wrong strike/expiry)")
            logger.error("  2. Option has already expired")
            logger.error("  3. Symbol is incorrect or not available")
            raise RuntimeError(
                f"Cannot resolve contract {underlying} ${strike}{right} exp {expiry.strftime('%Y%m%d')}. "
                f"Contract may not exist or has expired. Original error: {e}"
            )

        if not details_list:
            logger.error(f"No contract details found for {underlying} ${strike}{right} exp {expiry.strftime('%Y%m%d')}")
            logger.error(f"Contract: symbol={underlying}, strike={strike}, right={right}, expiry={expiry.strftime('%Y%m%d')}, exchange={exchange}")
            raise RuntimeError(
                f"No contract found for {underlying} ${strike}{right} exp {expiry.strftime('%Y%m%d')}. "
                "Contract may not exist or has expired."
            )

        contract = details_list[0].contract
        logger.info(f"✓ Contract resolved: ConId={contract.conId}, LocalSymbol={contract.localSymbol}")

        # Create tick service
        tick_svc = TickHistoricalService(runtime)

        # Make timezone-aware
        tz = pytz.timezone(timezone)
        if start_datetime.tzinfo is None:
            start_datetime = tz.localize(start_datetime)
        if end_datetime.tzinfo is None:
            end_datetime = tz.localize(end_datetime)

        # Pagination loop - yield ticks as they arrive
        current_start = start_datetime
        total_ticks = 0
        request_count = 0

        while current_start < end_datetime:
            request_count += 1
            start_str = _format_ib_datetime(current_start, timezone)

            logger.info(f"Request #{request_count}: start={current_start}")

            # Make request (IB API requires ONLY startDateTime, not both)
            result = tick_svc.ticks(
                contract=contract,
                startDateTime=start_str,
                endDateTime="",  # Empty = not used
                numberOfTicks=1000,
                whatToShow='TRADES',
                useRth=1 if use_rth else 0,
                ignoreSize=False,
                timeout=30.0
            )

            # Extract ticks and done flag
            ticks = result.get('items', result) if isinstance(result, dict) else result
            done = result.get('done', True) if isinstance(result, dict) else True

            logger.info(f"  Received {len(ticks)} ticks")

            # Yield ticks immediately (streaming, no accumulation)
            for tick in ticks:
                yield normalize_historical_tick_data(
                    tick=tick,
                    underlying=underlying,
                    expiry=expiry,
                    strike=strike,
                    right=right,
                    tick_type='TRADES'
                )
                total_ticks += 1

            # Update start time for next request
            if ticks:
                last_tick = ticks[-1]
                last_tick_dt = datetime.fromtimestamp(last_tick.time, tz=tz)

                # Check if we've reached the end time
                if last_tick_dt >= end_datetime:
                    logger.info(f"Reached end time: {last_tick_dt}")
                    break

                current_start = last_tick_dt
            else:
                # No ticks received
                logger.info("No more ticks available")
                break

        logger.info(f"Total: {total_ticks} ticks from {request_count} requests")
