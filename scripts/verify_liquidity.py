#!/usr/bin/env python3
"""
Standalone script to verify liquidity of SOHU 12.5 and YSG 5.0 strikes
by querying IB API directly for historical option bars.

This bypasses the dlt-ibapi pipeline to prove whether these contracts
actually have market data available from Interactive Brokers.
"""

import sys
from datetime import date, datetime
from ib_connector import IBRuntime, HistoricalService
from ib_connector.contracts import make_option
from dlt_ibapi.config_loader import get_connection_config


def verify_contract_liquidity(
    symbol: str,
    expiry: str,  # YYYYMMDD format
    strike: float,
    right: str,  # "C" or "P"
    bar_size: str = "5 mins",
    start_date: date = date(2025, 11, 10),
    end_date: date = date(2025, 11, 17),
):
    """
    Query IB API directly for option bars to verify if contract has data.

    Returns:
        (bar_count, sample_bars) tuple
    """
    print(f"\n{'='*80}")
    print(f"Verifying: {symbol} {expiry} {strike} {right}")
    print(f"Period: {start_date} to {end_date}")
    print(f"Bar Size: {bar_size}")
    print('='*80)

    # Load IB connection config
    config = get_connection_config()
    print(f"Connecting to IB Gateway: {config.host}:{config.port} (client_id={config.client_id})")

    # Create runtime and connect
    runtime = IBRuntime(
        host=config.host,
        port=config.port,
        client_id=config.client_id + 100,  # Use different client_id to avoid conflicts
    )

    try:
        runtime.start()
        print("✓ Connected to IB Gateway")

        # Create option contract
        contract = make_option(
            symbol=symbol,
            last_trade_date=expiry,
            strike=strike,
            right=right,
            exch="SMART",
        )

        print(f"\nContract: {contract}")

        # Fetch historical bars
        hist_svc = HistoricalService(runtime)

        print(f"\nRequesting historical bars from IB API...")
        print(f"  Duration: {(end_date - start_date).days} days")
        print(f"  Bar size: {bar_size}")

        bars = hist_svc.bars(
            contract=contract,
            endDateTime=datetime.combine(end_date, datetime.max.time()).strftime("%Y%m%d %H:%M:%S US/Eastern"),
            durationStr=f"{(end_date - start_date).days} D",
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=1,
            timeout=30.0,
        )

        bar_count = len(bars)
        print(f"\n{'='*80}")
        print(f"RESULT: IB API returned {bar_count} bars")
        print('='*80)

        if bar_count == 0:
            print("❌ ILLIQUID: No market data available")
            return 0, []

        elif bar_count <= 5:
            print(f"⚠️  VERY ILLIQUID: Only {bar_count} bars in {(end_date - start_date).days} days")
            print("\nAll bars:")
            for i, bar in enumerate(bars, 1):
                # bars are dicts, not objects
                print(f"  {i}. {bar['date']} | O:{bar['open']} H:{bar['high']} L:{bar['low']} C:{bar['close']} V:{bar['volume']}")
            return bar_count, bars

        else:
            print(f"✓ LIQUID: {bar_count} bars available")
            print("\nFirst 5 bars:")
            for i, bar in enumerate(bars[:5], 1):
                print(f"  {i}. {bar['date']} | O:{bar['open']} H:{bar['high']} L:{bar['low']} C:{bar['close']} V:{bar['volume']}")

            print(f"\nLast 5 bars:")
            for i, bar in enumerate(bars[-5:], 1):
                print(f"  {len(bars)-5+i}. {bar['date']} | O:{bar['open']} H:{bar['high']} L:{bar['low']} C:{bar['close']} V:{bar['volume']}")

            return bar_count, bars

    finally:
        runtime.stop()
        print("\n✓ Disconnected from IB Gateway\n")


def main():
    print("\n" + "="*80)
    print("LIQUIDITY VERIFICATION - Direct IB API Query")
    print("="*80)
    print("\nThis script directly queries IB API to verify if contracts have market data,")
    print("bypassing the dlt-ibapi pipeline entirely.")
    print("\nContracts to test:")
    print("  1. SOHU 20251121 12.5 Call (user claims: only 1 bar)")
    print("  2. YSG  20251219 5.0  Call (user claims: missing)")
    print("  3. SOHU 20251121 15.0 Call (control: should be liquid)")
    print("  4. YSG  20251121 10.0 Call (control: should be liquid)")

    test_cases = [
        # (symbol, expiry, strike, right, description)
        ("SOHU", "20251121", 12.5, "C", "SOHU 12.5 Call - User's 'only 1 bar' case"),
        ("YSG", "20251219", 5.0, "C", "YSG 5.0 Call - User's 'missing' case"),
        ("SOHU", "20251121", 15.0, "C", "SOHU 15.0 Call - ATM control (should be liquid)"),
        ("YSG", "20251121", 10.0, "C", "YSG 10.0 Call - Control (should be liquid)"),
    ]

    results = []

    for symbol, expiry, strike, right, description in test_cases:
        print(f"\n{'#'*80}")
        print(f"TEST CASE: {description}")
        print('#'*80)

        try:
            bar_count, bars = verify_contract_liquidity(
                symbol=symbol,
                expiry=expiry,
                strike=strike,
                right=right,
                bar_size="5 mins",
                start_date=date(2025, 11, 10),
                end_date=date(2025, 11, 17),
            )

            results.append({
                'description': description,
                'symbol': symbol,
                'expiry': expiry,
                'strike': strike,
                'right': right,
                'bar_count': bar_count,
                'status': 'LIQUID' if bar_count > 20 else 'ILLIQUID' if bar_count <= 5 else 'LOW_LIQUIDITY',
            })

        except Exception as e:
            print(f"\n❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                'description': description,
                'symbol': symbol,
                'expiry': expiry,
                'strike': strike,
                'right': right,
                'bar_count': 0,
                'status': 'ERROR',
                'error': str(e),
            })

    # Summary
    print("\n" + "="*80)
    print("SUMMARY OF RESULTS")
    print("="*80)
    print(f"\n{'Description':<45} {'Bars':<8} {'Status':<15}")
    print("-"*80)

    for result in results:
        status_emoji = {
            'LIQUID': '✓',
            'LOW_LIQUIDITY': '⚠️',
            'ILLIQUID': '❌',
            'ERROR': '💥',
        }.get(result['status'], '?')

        print(f"{result['description']:<45} {result['bar_count']:<8} {status_emoji} {result['status']:<15}")

    print("\n" + "="*80)
    print("CONCLUSION")
    print("="*80)

    sohu_125 = next(r for r in results if r['strike'] == 12.5 and r['symbol'] == 'SOHU')
    ysg_50 = next(r for r in results if r['strike'] == 5.0 and r['symbol'] == 'YSG')

    print(f"\n1. SOHU 12.5 Call: {sohu_125['bar_count']} bars from IB API")
    if sohu_125['bar_count'] <= 5:
        print("   → CONFIRMED ILLIQUID: IB has minimal/no data for this contract")
        print("   → User's observation of '1 bar' is correct - this contract has no liquidity")
    else:
        print("   → This contract IS liquid - investigate why only 1 bar was saved")

    print(f"\n2. YSG 5.0 Call: {ysg_50['bar_count']} bars from IB API")
    if ysg_50['bar_count'] == 0:
        print("   → CONFIRMED ILLIQUID: IB has no data for this contract")
        print("   → User's claim of 'missing' is partially correct for Nov21 expiry")
        print("   → But Dec19 expiry (tested here) should have data if liquid")
    elif ysg_50['bar_count'] > 20:
        print("   → This contract IS liquid - data exists in IB")
        print("   → Check if it was written to database correctly")
    else:
        print(f"   → LOW LIQUIDITY: Only {ysg_50['bar_count']} bars available")

    print("\n" + "="*80 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
