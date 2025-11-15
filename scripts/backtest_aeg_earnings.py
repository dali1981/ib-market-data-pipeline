#!/usr/bin/env python3
"""
Backtest AEG Earnings Calendar Spread Strategies.

Compares two calendar spread approaches for AEG earnings (November 13, 2025):
1. Simple: Fixed DTE ranges, 1 day before → 1 day after earnings
2. IV Term Structure: Max IV differential expirations, same timing

Usage:
    # First: Ensure IB Gateway is running and option bars are backfilled
    dlt-ibapi backfill-options AEG 6.48 --mode atm --k-strikes 5 \
        --min-dte 7 --max-dte 60 --start 2025-01-06 --end 2025-11-14

    # Then run backtest
    uv run python scripts/backtest_aeg_earnings.py

    # Optional: Use different data path
    uv run python scripts/backtest_aeg_earnings.py --data-path ./data_delta

Output:
    - Strategy comparison metrics (P&L, drawdown, win rate)
    - IV capture analysis (front vs back IV changes)
    - Detailed trade logs
"""

import sys
from pathlib import Path
from datetime import date, datetime
import pandas as pd

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dlt_ibapi.backtest import (
    IBBacktestDataProvider,
    IVTermStructureAnalyzer,
    OptionsBacktestRunner,
)
from tools.strategies.options import (
    SimpleEarningsCalendarSpreadStrategy,
    SimpleEarningsConfig,
)
from tools.strategies.options.iv_term_calendar import (
    IVTermStructureCalendarSpreadStrategy,
    IVTermCalendarConfig,
)


def print_header(title: str):
    """Print formatted header."""
    print("\n" + "=" * 80)
    print(title.center(80))
    print("=" * 80 + "\n")


def print_strategy_config(name: str, config):
    """Print strategy configuration."""
    print(f"\n{name} Configuration:")
    print(f"  Symbols: {config.underlying_symbols}")
    print(f"  Entry: {config.entry_days_before} day(s) before earnings")
    print(f"  Exit: {config.exit_days_after} day(s) after earnings")
    print(f"  Front DTE: {config.front_dte_range[0]}-{config.front_dte_range[1]} days")
    print(f"  Back DTE: {config.back_dte_range[0]}-{config.back_dte_range[1]} days")
    print(f"  Target Delta: {config.target_delta[0]:.2f}-{config.target_delta[1]:.2f}")
    print(f"  Option Type: {'Calls' if config.option_type == 'C' else 'Puts'}")

    if hasattr(config, 'min_iv_diff'):
        print(f"  Min IV Diff: {config.min_iv_diff:.1%}")
        print(f"  IV Rank Filter: {config.use_iv_rank_filter}")


def print_results(name: str, result):
    """Print backtest results."""
    print(f"\n{name} Results:")
    print(f"  Total P&L: ${result.total_pnl:,.2f}")
    print(f"  Max Drawdown: ${result.max_drawdown:,.2f}")
    print(f"  Win Rate: {result.win_rate:.1%}")
    print(f"  Total Trades: {result.num_trades}")
    print(f"  Avg P&L per Trade: ${result.avg_pnl_per_trade:,.2f}")

    if result.num_trades > 0:
        print(f"\n  Trade Details:")
        for i, trade in enumerate(result.trades, 1):
            print(f"    Trade {i}:")
            print(f"      Entry: {trade.entry_date}")
            print(f"      Exit: {trade.exit_date}")
            print(f"      P&L: ${trade.pnl:,.2f}")
            print(f"      Entry Cost: ${trade.entry_cost:,.2f}")
            print(f"      Exit Value: ${trade.exit_value:,.2f}")

            if 'front_iv' in trade.metadata:
                print(f"      Front IV: {trade.metadata['front_iv']:.2%} → "
                      f"{trade.metadata.get('exit_front_iv', 0.0):.2%}")
                print(f"      Back IV: {trade.metadata['back_iv']:.2%} → "
                      f"{trade.metadata.get('exit_back_iv', 0.0):.2%}")


def compare_results(simple_result, iv_result):
    """Compare results from both strategies."""
    print_header("STRATEGY COMPARISON")

    print(f"{'Metric':<30} {'Simple':>15} {'IV Term':>15} {'Difference':>15}")
    print("-" * 80)

    # P&L comparison
    pnl_diff = iv_result.total_pnl - simple_result.total_pnl
    pnl_diff_pct = (pnl_diff / simple_result.total_pnl * 100) if simple_result.total_pnl != 0 else 0
    print(f"{'Total P&L':<30} ${simple_result.total_pnl:>14,.2f} "
          f"${iv_result.total_pnl:>14,.2f} "
          f"${pnl_diff:>14,.2f} ({pnl_diff_pct:+.1f}%)")

    # Drawdown comparison
    dd_diff = iv_result.max_drawdown - simple_result.max_drawdown
    print(f"{'Max Drawdown':<30} ${simple_result.max_drawdown:>14,.2f} "
          f"${iv_result.max_drawdown:>14,.2f} "
          f"${dd_diff:>14,.2f}")

    # Win rate comparison
    wr_diff = iv_result.win_rate - simple_result.win_rate
    print(f"{'Win Rate':<30} {simple_result.win_rate:>14.1%} "
          f"{iv_result.win_rate:>14.1%} "
          f"{wr_diff:>14.1%}")

    # Avg P&L comparison
    avg_diff = iv_result.avg_pnl_per_trade - simple_result.avg_pnl_per_trade
    print(f"{'Avg P&L per Trade':<30} ${simple_result.avg_pnl_per_trade:>14,.2f} "
          f"${iv_result.avg_pnl_per_trade:>14,.2f} "
          f"${avg_diff:>14,.2f}")

    print("\n" + "=" * 80)

    # Conclusion
    if pnl_diff > 0:
        print(f"\n✓ IV Term Structure strategy outperformed by ${pnl_diff:,.2f} ({pnl_diff_pct:+.1f}%)")
    elif pnl_diff < 0:
        print(f"\n✗ Simple strategy outperformed by ${-pnl_diff:,.2f} ({-pnl_diff_pct:+.1f}%)")
    else:
        print("\n= Both strategies performed equally")


def main():
    """Run AEG earnings calendar spread backtest."""
    import argparse

    parser = argparse.ArgumentParser(description="Backtest AEG earnings calendar spreads")
    parser.add_argument(
        "--data-path",
        default="./data_delta",
        help="Path to data directory (default: ./data_delta)"
    )
    parser.add_argument(
        "--initial-capital",
        type=float,
        default=100_000,
        help="Initial capital (default: 100000)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output"
    )
    args = parser.parse_args()

    print_header("AEG EARNINGS CALENDAR SPREAD BACKTEST")

    print(f"Data Path: {args.data_path}")
    print(f"Initial Capital: ${args.initial_capital:,.2f}")
    print(f"Backtest Period: November 1-20, 2025")
    print(f"Earnings Date: November 13, 2025")

    # ========================================================================
    # Initialize Providers
    # ========================================================================

    print("\n[1/5] Initializing data providers...")
    data_provider = IBBacktestDataProvider(args.data_path)
    iv_analyzer = IVTermStructureAnalyzer(data_provider)

    # ========================================================================
    # Configure AEG Earnings
    # ========================================================================

    aeg_earnings = {"AEG": date(2025, 11, 13)}

    # ========================================================================
    # Strategy #1: Simple Earnings Calendar Spread
    # ========================================================================

    print("\n[2/5] Configuring Strategy #1: Simple Earnings Calendar")

    simple_config = SimpleEarningsConfig(
        underlying_symbols=["AEG"],
        earnings_dates=aeg_earnings,
        entry_days_before=1,  # Enter Nov 12
        exit_days_after=1,    # Exit Nov 14
        target_delta=(0.40, 0.60),
        front_dte_range=(14, 21),
        back_dte_range=(35, 50),
        option_type="C",  # Calls
    )

    print_strategy_config("Strategy #1", simple_config)

    simple_strategy = SimpleEarningsCalendarSpreadStrategy(simple_config)

    # ========================================================================
    # Strategy #3: IV Term Structure Calendar Spread
    # ========================================================================

    print("\n[3/5] Configuring Strategy #3: IV Term Structure Calendar")

    iv_config = IVTermCalendarConfig(
        underlying_symbols=["AEG"],
        earnings_dates=aeg_earnings,
        entry_days_before=1,
        exit_days_after=1,
        target_delta=(0.40, 0.60),
        front_dte_range=(14, 21),  # Search boundaries
        back_dte_range=(35, 50),   # Search boundaries
        min_iv_diff=0.03,  # 3% minimum differential
        use_iv_rank_filter=False,  # Disabled (insufficient history)
        option_type="C",
    )

    print_strategy_config("Strategy #3", iv_config)

    iv_strategy = IVTermStructureCalendarSpreadStrategy(iv_config, iv_analyzer)

    # ========================================================================
    # Run Backtests
    # ========================================================================

    print("\n[4/5] Running backtests...")

    # Strategy #1: Simple
    print("\n  Running Strategy #1 (Simple)...")
    simple_runner = OptionsBacktestRunner(
        strategy=simple_strategy,
        data_provider=data_provider,
        initial_capital=args.initial_capital,
        validate_data=True,
    )

    simple_result = simple_runner.run(
        start_date=date(2025, 11, 1),
        end_date=date(2025, 11, 20),
    )

    # Strategy #3: IV Term Structure
    print("\n  Running Strategy #3 (IV Term Structure)...")
    iv_runner = OptionsBacktestRunner(
        strategy=iv_strategy,
        data_provider=data_provider,
        initial_capital=args.initial_capital,
        validate_data=True,
    )

    iv_result = iv_runner.run(
        start_date=date(2025, 11, 1),
        end_date=date(2025, 11, 20),
    )

    # ========================================================================
    # Display Results
    # ========================================================================

    print("\n[5/5] Analyzing results...")

    print_header("INDIVIDUAL STRATEGY RESULTS")

    print_results("Strategy #1: Simple Earnings Calendar", simple_result)
    print_results("Strategy #3: IV Term Structure Calendar", iv_result)

    # Compare strategies
    compare_results(simple_result, iv_result)

    # ========================================================================
    # Recommendations
    # ========================================================================

    print_header("RECOMMENDATIONS")

    print("Data Quality:")
    print("  ✓ Backtest completed successfully")
    print("  ⚠ Limited to 1 earnings event (statistical significance requires 10+ events)")
    print("  ⚠ Only 1 option chain snapshot (ideal: daily snapshots for term structure evolution)")

    print("\nNext Steps:")
    print("  1. Collect option bars for more symbols (expand universe)")
    print("  2. Implement daily snapshot collection (for future earnings)")
    print("  3. Backfill 12+ months equity history (for IV rank filtering)")
    print("  4. Run multi-symbol backtest with 50+ earnings events")
    print("  5. Optimize parameters (entry/exit timing, DTE ranges)")

    print("\nTo extend this analysis:")
    print("  - Add more symbols to earnings_dates dict")
    print("  - Test different entry/exit timings (2-3 days before/after)")
    print("  - Enable IV rank filtering (when sufficient history available)")
    print("  - Compare calls vs puts performance")

    print("\n" + "=" * 80)
    print("Backtest complete! See docs/AEG_EARNINGS_CALENDAR_SPREAD_BACKTEST_PLAN.md")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
