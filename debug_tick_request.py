#!/usr/bin/env python3
"""
Debug script to test IB tick data request directly.
Helps diagnose timeout/hanging issues.
"""

import sys
from datetime import datetime
from ib_connector import IBRuntime
from ib_connector.contracts import make_option

# Test parameters
SYMBOL = "DIS"
EXPIRY = "20251205"  # Dec 5, 2025
STRIKE = 108.0
RIGHT = "C"
START_TIME = datetime(2025, 11, 14, 15, 0, 0)  # 3:00pm Nov 14
END_TIME = datetime(2025, 11, 14, 15, 5, 0)    # 3:05pm (5 minutes only)

print(f"Testing tick data request for {SYMBOL} ${STRIKE}{RIGHT} exp {EXPIRY}")
print(f"Time window: {START_TIME} to {END_TIME}")
print(f"Timezone: US/Eastern")
print()

try:
    # Connect to IB
    print("Connecting to IB Gateway...")
    with IBRuntime(host="127.0.0.1", port=4002, client_id=1) as runtime:
        print("✓ Connected")

        # Create contract
        print(f"Creating contract for {SYMBOL} {STRIKE}{RIGHT} exp {EXPIRY}...")
        contract = make_option(
            symbol=SYMBOL,
            last_trade_date=EXPIRY,
            strike=STRIKE,
            right=RIGHT,
            exch="SMART",
            curr="USD"
        )
        print(f"✓ Contract created: {contract}")

        # Request ticks with explicit timeout
        print(f"\nRequesting ticks with 30s timeout...")
        print(f"Start: {START_TIME.strftime('%Y%m%d %H:%M:%S')} US/Eastern")
        print(f"End: {END_TIME.strftime('%Y%m%d %H:%M:%S')} US/Eastern")

        ticks = runtime.tick_historical.fetch_historical_ticks(
            contract=contract,
            start_time=START_TIME,
            end_time=END_TIME,
            tick_type='BID_ASK',
            use_rth=True,
            timeout=30.0,
            timezone="US/Eastern"
        )

        print(f"\n✓ Request completed")
        print(f"Ticks received: {len(ticks)}")

        if ticks:
            print(f"\nFirst tick:")
            tick = ticks[0]
            print(f"  Time: {tick.time}")
            print(f"  Bid: ${tick.bid_price} x {tick.bid_size}")
            print(f"  Ask: ${tick.ask_price} x {tick.ask_size}")
        else:
            print("\n⚠️  No ticks returned")
            print("Possible reasons:")
            print("  - No data available for this date/time")
            print("  - Account doesn't have historical tick data permissions")
            print("  - Market was closed")
            print("  - Contract didn't trade during this period")

except KeyboardInterrupt:
    print("\n\n⚠️  Interrupted by user")
    sys.exit(1)
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
