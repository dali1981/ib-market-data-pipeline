"""
Standalone ib-connector example: Use ib-connector directly without DLT.
"""

from ib_connector import (
    IBRuntime,
    ContractDetailsService,
    HistoricalService,
    make_stock,
)


def main():
    # Create and start runtime
    print("Connecting to IB Gateway...")
    runtime = IBRuntime(host="127.0.0.1", port=7497, client_id=1)
    runtime.start()

    try:
        # Example 1: Fetch contract details
        print("\n--- Contract Details ---")
        contract_svc = ContractDetailsService(runtime)
        aapl = make_stock("AAPL", "SMART", "USD")
        details = contract_svc.fetch(aapl, timeout=10.0)

        for detail in details:
            print(f"Symbol: {detail.contract.symbol}")
            print(f"Contract ID: {detail.contract.conId}")
            print(f"Long Name: {detail.longName}")
            print(f"Exchange: {detail.contract.exchange}")
            print(f"Min Tick: {detail.minTick}")

        # Example 2: Fetch historical data
        print("\n--- Historical Bars ---")
        hist_svc = HistoricalService(runtime)
        bars = hist_svc.bars(
            contract=aapl,
            endDateTime="",
            durationStr="1 D",
            barSizeSetting="5 mins",
            whatToShow="TRADES",
            useRTH=1,
        )

        print(f"Retrieved {len(bars)} bars")
        for bar in bars[:5]:  # Show first 5
            print(f"{bar['date']}: "
                  f"O={bar['open']:.2f} H={bar['high']:.2f} "
                  f"L={bar['low']:.2f} C={bar['close']:.2f} "
                  f"V={bar['volume']}")

    finally:
        print("\nDisconnecting...")
        runtime.stop()


if __name__ == "__main__":
    main()
