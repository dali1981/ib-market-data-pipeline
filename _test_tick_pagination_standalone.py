#!/usr/bin/env python3
"""
Standalone test for tick pagination logic.

Tests the pagination algorithm:
1. Make request for start_time to end_time
2. If done=True with ticks: finish
3. If done=False: make ANOTHER request from last_tick_time to end_time
4. Repeat until done=True
"""

from datetime import datetime
import pytz
from ib_connector import IBRuntime
from ib_connector.contracts import make_stock
from ib_connector.services import ContractDetailsService, TickHistoricalService
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def format_ib_datetime(dt: datetime, timezone_str: str) -> str:
    """Format datetime for IB API.

    IB API requires format: "yyyymmdd HH:MM:SS timezone"
    Timezone should be in format like "US/Eastern" or "America/New_York"
    """
    # Ensure datetime is timezone-aware
    if dt.tzinfo is None:
        tz = pytz.timezone(timezone_str)
        dt = tz.localize(dt)
    # Use timezone name directly (like "US/Eastern"), not abbreviation
    return dt.strftime("%Y%m%d %H:%M:%S") + f" {timezone_str}"


def main():
    """Test tick pagination with AAPL stock."""

    logger.info("=" * 80)
    logger.info("Testing Tick Pagination - Standalone")
    logger.info("=" * 80)

    # Test parameters - simplified to use stock (AAPL) for easier testing
    symbol = "AAPL"
    timezone_str = "US/Eastern"

    # Test with TRADES per user request
    tick_type = "TRADES"

    # Use VERY RECENT date - try yesterday or Friday (Nov 15 was Friday)
    # Historical tick data may only be available for very recent periods
    # Make timezone-aware from the start
    tz = pytz.timezone(timezone_str)
    start_time = tz.localize(datetime(2025, 11, 14, 10, 0))  # Mid-morning
    end_time = tz.localize(datetime(2025, 11, 14, 10, 30))   # 30 minutes of data

    logger.info(f"Symbol: {symbol}")
    logger.info(f"Tick type: {tick_type}")
    logger.info(f"Time window: {start_time} to {end_time} {timezone_str}")
    logger.info("")

    with IBRuntime(host="127.0.0.1", port=4002, client_id=1) as runtime:
        # Create stock contract
        contract = make_stock(
            symbol=symbol,
            exch="SMART",
            curr="USD"
        )

        # Resolve contract to get ConId
        logger.info("Resolving contract...")
        contract_svc = ContractDetailsService(runtime)
        details_list = contract_svc.fetch(contract)
        if not details_list:
            logger.error("No contract details found!")
            return

        # Use the resolved contract from details
        contract = details_list[0].contract
        logger.info(f"Contract resolved: ConId={contract.conId}, Symbol={contract.symbol}")
        logger.info("")

        logger.info("Starting pagination loop...")
        logger.info("")

        # Create tick historical service
        tick_svc = TickHistoricalService(runtime)

        # Pagination loop
        # IB API requires EITHER startDateTime OR endDateTime, not both!
        # We'll use startDateTime and paginate forward
        all_ticks = []
        current_start = start_time
        request_count = 0

        while current_start < end_time:
            request_count += 1

            # Format times for IB API
            # IMPORTANT: Only provide startDateTime, NOT endDateTime!
            start_str = format_ib_datetime(current_start, timezone_str)

            logger.info(f"Request #{request_count}:")
            logger.info(f"  Start: {start_str}")
            logger.info(f"  End:   (not specified - using numberOfTicks limit)")

            # Make request (returns {'items': [...], 'done': bool})
            # Pass empty string for endDateTime per IB API requirement
            result = tick_svc.ticks(
                contract=contract,
                startDateTime=start_str,
                endDateTime="",  # Empty = not used
                numberOfTicks=1000,
                whatToShow=tick_type,
                useRth=1,
                ignoreSize=False,
                timeout=30.0
            )

            # Extract ticks and done flag
            ticks = result.get('items', result) if isinstance(result, dict) else result
            done = result.get('done', True) if isinstance(result, dict) else True

            logger.info(f"  Received: {len(ticks)} ticks, done={done}")

            # Accumulate ticks
            all_ticks.extend(ticks)

            # Always update start time to last tick time for next request
            if ticks:
                last_tick = ticks[-1]
                last_tick_dt = datetime.fromtimestamp(last_tick.time, tz=pytz.timezone(timezone_str))

                logger.info(f"  Last tick time: {last_tick_dt}")

                # Check if we've reached the end time
                if last_tick_dt >= end_time:
                    logger.info(f"  ✓ Reached end time: {last_tick_dt} >= {end_time}")
                    logger.info(f"  Done! Total requests: {request_count}")
                    break

                # Update start time for next request to continue from last tick
                current_start = last_tick_dt
                logger.info(f"  Continuing from: {current_start}")
            else:
                # No ticks received - stop
                logger.info("  No ticks received - stopping")
                break

            logger.info("")

        logger.info("")
        logger.info("=" * 80)
        logger.info("Results:")
        logger.info("=" * 80)
        logger.info(f"Total requests: {request_count}")
        logger.info(f"Total ticks fetched: {len(all_ticks)}")

        if all_ticks:
            first_tick = all_ticks[0]
            last_tick = all_ticks[-1]

            # Convert Unix timestamps to datetime
            first_dt = datetime.fromtimestamp(first_tick.time, tz=pytz.timezone(timezone_str))
            last_dt = datetime.fromtimestamp(last_tick.time, tz=pytz.timezone(timezone_str))

            logger.info(f"First tick: {first_dt} (unix={first_tick.time}), price={first_tick.price}, size={first_tick.size}")
            logger.info(f"Last tick:  {last_dt} (unix={last_tick.time}), price={last_tick.price}, size={last_tick.size}")

            # Show a few samples
            logger.info("")
            logger.info("Sample ticks:")
            for i in [0, len(all_ticks)//4, len(all_ticks)//2, len(all_ticks)*3//4, -1]:
                tick = all_ticks[i]
                tick_dt = datetime.fromtimestamp(tick.time, tz=pytz.timezone(timezone_str))
                logger.info(f"  [{i if i >= 0 else len(all_ticks)+i}]: {tick_dt} (unix={tick.time}), price={tick.price}, size={tick.size}")
            logger.info("")
            logger.info("Time range coverage:")
            logger.info(f"  Requested: {start_time} to {end_time}")
            logger.info(f"  Received:  {first_dt} to {last_dt}")
            duration = (last_dt - first_dt).total_seconds() / 60
            logger.info(f"  Duration:  {duration:.2f} minutes")
        else:
            logger.warning("No ticks received!")

        logger.info("=" * 80)
        logger.info("Test complete")
        logger.info("=" * 80)


if __name__ == "__main__":
    main()
