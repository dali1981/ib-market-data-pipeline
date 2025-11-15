#!/usr/bin/env python3
"""
Automated Calendar Spread Data Collector

Orchestrates complete data collection pipeline for calendar spread backtesting:
1. Load earnings symbols
2. Resolve contracts (cache population)
3. Capture option chain snapshots
4. Backfill equity bars (spot prices)
5. Select calendar spread expirations
6. Backfill option bars (front + back legs, parallel)
7. Validate and report

Usage:
    python collect_calendar_spread_data.py 2025-11-13 --workers 5
    python collect_calendar_spread_data.py 2025-11-13 --front-dte 14 25 --back-dte 35 60
"""

from datetime import date, timedelta
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import logging
import sys
import time
from dataclasses import dataclass, asdict
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dlt_ibapi.repositories import (
    EarningsCalendarReader,
    OptionChainSnapshotReader,
    EquityBarsReader,
)
from dlt_ibapi.cli.resolve import execute_resolve_contracts
from dlt_ibapi.cli.snapshot import execute_batch_snapshot_for_earnings
from dlt_ibapi.cli.backfill import execute_backfill_equity, execute_backfill_options
from dlt_ibapi.cli.models import (
    ResolveContractsParams,
    SnapshotParams,
    BackfillEquityParams,
    BackfillOptionsParams,
)


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class CalendarSpreadConfig:
    """Configuration for calendar spread data collection."""
    earnings_date: date
    entry_window_days: Tuple[int, int] = (10, 25)  # Days before earnings
    front_leg_dte: Tuple[int, int] = (14, 25)       # DTE from earnings
    back_leg_dte: Tuple[int, int] = (35, 60)        # DTE from earnings
    k_strikes: int = 3                               # Strikes around ATM
    bar_size: str = "1 day"
    database_path: Path = Path("data")
    max_workers: int = 5                             # Parallel processing
    earnings_dataset: str = "earnings"
    option_chains_dataset: str = "option_chains"
    stocks_dataset: str = "stocks"
    options_dataset: str = "options"


@dataclass
class SpreadExpirations:
    """Selected expirations for calendar spread."""
    symbol: str
    front_expiry: Optional[date]
    back_expiry: Optional[date]
    front_dte: Optional[int]
    back_dte: Optional[int]
    spot_price: Optional[float]
    error: Optional[str] = None

    def is_valid(self) -> bool:
        """Check if both expirations were found."""
        return self.front_expiry is not None and self.back_expiry is not None


# ============================================================================
# Main Collector Class
# ============================================================================

class CalendarSpreadDataCollector:
    """
    Automated data collector for calendar spread backtesting.

    Orchestrates the complete pipeline from earnings calendar to option bars.
    """

    def __init__(self, config: CalendarSpreadConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Initialize readers
        self.earnings_reader = EarningsCalendarReader(
            str(config.database_path), config.earnings_dataset
        )
        self.chain_reader = OptionChainSnapshotReader(
            str(config.database_path), config.option_chains_dataset
        )
        self.equity_reader = EquityBarsReader(
            str(config.database_path), config.stocks_dataset
        )

    def run(self) -> Dict:
        """Execute complete data collection workflow."""
        start_time = time.time()

        results = {
            "earnings_date": str(self.config.earnings_date),
            "total_symbols": 0,
            "successful": 0,
            "failed": 0,
            "errors": [],
            "spread_selections": [],
        }

        try:
            # STEP 1: Load earnings symbols
            self.logger.info(f"STEP 1: Loading earnings for {self.config.earnings_date}")
            symbols = self._load_earnings_symbols()
            results["total_symbols"] = len(symbols)
            self.logger.info(f"  → Found {len(symbols)} symbols with earnings")

            if not symbols:
                results["errors"].append("No symbols found with earnings on specified date")
                return results

            # STEP 2: Resolve contracts
            self.logger.info(f"STEP 2: Resolving contracts for {len(symbols)} symbols")
            resolve_result = self._resolve_contracts(symbols)
            self.logger.info(f"  → {len(resolve_result.resolved)} resolved, {len(resolve_result.failed)} failed")

            # STEP 3: Capture snapshots
            self.logger.info(f"STEP 3: Capturing option chain snapshots")
            snapshot_result = self._capture_snapshots()
            self.logger.info(f"  → {snapshot_result.successful_snapshots} successful")

            # STEP 4: Backfill equity bars
            self.logger.info(f"STEP 4: Backfilling equity bars for spot prices")
            self._backfill_equity_bars(symbols)
            self.logger.info(f"  → Equity bars updated")

            # STEP 5: Select expirations
            self.logger.info(f"STEP 5: Selecting calendar spread expirations")
            spread_selections = self._select_spread_expirations(symbols)
            valid_selections = [s for s in spread_selections if s.is_valid()]
            self.logger.info(
                f"  → {len(valid_selections)} valid selections, "
                f"{len(spread_selections) - len(valid_selections)} skipped"
            )

            # Store selections for reporting
            results["spread_selections"] = [
                asdict(s) for s in spread_selections
            ]

            # STEP 6: Backfill option bars
            self.logger.info(f"STEP 6: Backfilling option bars (front + back legs)")
            backfill_results = self._backfill_option_bars_batch(valid_selections)

            results["successful"] = backfill_results["successful"]
            results["failed"] = backfill_results["failed"]
            results["errors"].extend(backfill_results["errors"])

            # STEP 7: Validation
            self.logger.info(f"STEP 7: Validating data completeness")
            validation = self._validate_data(valid_selections)
            results["validation"] = validation

        except Exception as e:
            self.logger.error(f"Workflow failed: {e}", exc_info=True)
            results["errors"].append(str(e))

        results["duration_seconds"] = time.time() - start_time
        return results

    def _load_earnings_symbols(self) -> List[str]:
        """Load symbols with earnings on specified date."""
        earnings_df = self.earnings_reader.get_earnings_on_date(
            self.config.earnings_date
        )

        if earnings_df.empty:
            return []

        return sorted(earnings_df["symbol"].unique().tolist())

    def _resolve_contracts(self, symbols: List[str]):
        """Pre-populate contract cache."""
        params = ResolveContractsParams(
            earnings_date=self.config.earnings_date,
            database_path=self.config.database_path,
            cache_path=Path(".dlt-ibapi/cache"),
        )

        result = execute_resolve_contracts(params)

        if result.failed:
            self.logger.warning(
                f"Failed to resolve {len(result.failed)} symbols: "
                f"{list(result.failed.keys())[:10]}"
            )

        return result

    def _capture_snapshots(self):
        """Capture option chain snapshots for earnings date."""
        max_dte = max(self.config.back_leg_dte[1], self.config.front_leg_dte[1])

        params = SnapshotParams(
            earnings_date=self.config.earnings_date,
            snapshot_date=date.today(),
            min_dte=0,
            max_dte=max_dte,
            pipeline_name="ib_snapshots",
            dataset_name=self.config.option_chains_dataset,
            earnings_dataset_name=self.config.earnings_dataset,
        )

        result = execute_batch_snapshot_for_earnings(params)

        if result.failed_snapshots > 0:
            self.logger.warning(
                f"{result.failed_snapshots} snapshots failed: "
                f"{', '.join(result.failed_symbols[:10])}"
            )

        return result

    def _backfill_equity_bars(self, symbols: List[str]):
        """Backfill equity bars for spot price lookup."""
        # Calculate date range: entry window start to earnings date
        entry_start = self.config.earnings_date - timedelta(
            days=self.config.entry_window_days[1]
        )

        params = BackfillEquityParams(
            symbols=symbols,
            start_date=entry_start,
            end_date=self.config.earnings_date,
            bar_size=self.config.bar_size,
            pipeline_name="ib_stocks",
            dataset_name=self.config.stocks_dataset,
            database_path=self.config.database_path,
        )

        result = execute_backfill_equity(params)

        if not result.success:
            self.logger.error(f"Equity backfill failed: {result.error}")
            raise RuntimeError(f"Equity backfill failed: {result.error}")

    def _select_spread_expirations(
        self, symbols: List[str]
    ) -> List[SpreadExpirations]:
        """
        Select front and back leg expirations for each symbol.

        Reads snapshot data and finds expirations that match DTE criteria
        relative to earnings_date.
        """
        spread_selections = []

        for symbol in symbols:
            try:
                # Get spot price first
                spot_price = self._get_spot_price(symbol)

                # Get available expirations from snapshot
                expirations = self.chain_reader.get_available_expirations(
                    underlying=symbol,
                    as_of=date.today(),  # Latest snapshot
                )

                if not expirations:
                    spread_selections.append(
                        SpreadExpirations(
                            symbol=symbol,
                            front_expiry=None,
                            back_expiry=None,
                            front_dte=None,
                            back_dte=None,
                            spot_price=spot_price,
                            error="No expirations found in snapshot",
                        )
                    )
                    continue

                # Calculate DTE from earnings_date (NOT snapshot date)
                exp_with_dte = [
                    (exp, (exp - self.config.earnings_date).days)
                    for exp in expirations
                ]

                # Select front leg: First expiry in DTE range
                front_candidates = [
                    (exp, dte) for exp, dte in exp_with_dte
                    if self.config.front_leg_dte[0] <= dte <= self.config.front_leg_dte[1]
                ]

                # Select back leg: First expiry in DTE range
                back_candidates = [
                    (exp, dte) for exp, dte in exp_with_dte
                    if self.config.back_leg_dte[0] <= dte <= self.config.back_leg_dte[1]
                ]

                front_expiry, front_dte = (
                    min(front_candidates, key=lambda x: x[1])
                    if front_candidates else (None, None)
                )

                back_expiry, back_dte = (
                    min(back_candidates, key=lambda x: x[1])
                    if back_candidates else (None, None)
                )

                spread_selections.append(
                    SpreadExpirations(
                        symbol=symbol,
                        front_expiry=front_expiry,
                        back_expiry=back_expiry,
                        front_dte=front_dte,
                        back_dte=back_dte,
                        spot_price=spot_price,
                        error=None if (front_expiry and back_expiry) else "Missing expiration in DTE range",
                    )
                )

            except Exception as e:
                self.logger.error(f"Error selecting expirations for {symbol}: {e}")
                spread_selections.append(
                    SpreadExpirations(
                        symbol=symbol,
                        front_expiry=None,
                        back_expiry=None,
                        front_dte=None,
                        back_dte=None,
                        spot_price=None,
                        error=str(e),
                    )
                )

        return spread_selections

    def _backfill_option_bars_batch(
        self, spread_selections: List[SpreadExpirations]
    ) -> Dict:
        """
        Backfill option bars for all symbols (parallel processing).

        For each symbol:
        1. Get spot price from equity bars
        2. Backfill front leg options (DTE range)
        3. Backfill back leg options (DTE range)
        """
        results = {"successful": 0, "failed": 0, "errors": []}

        self.logger.info(
            f"Processing {len(spread_selections)} symbols with {self.config.max_workers} workers"
        )

        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            futures = {
                executor.submit(self._backfill_single_symbol, selection): selection
                for selection in spread_selections
            }

            for future in as_completed(futures):
                selection = futures[future]
                try:
                    success = future.result()
                    if success:
                        results["successful"] += 1
                        self.logger.info(f"  ✓ {selection.symbol}")
                    else:
                        results["failed"] += 1
                        self.logger.warning(f"  ✗ {selection.symbol} (failed backfill)")
                except Exception as e:
                    self.logger.error(
                        f"  ✗ {selection.symbol}: {e}"
                    )
                    results["failed"] += 1
                    results["errors"].append(f"{selection.symbol}: {str(e)}")

        return results

    def _backfill_single_symbol(self, selection: SpreadExpirations) -> bool:
        """Backfill option bars for a single symbol (front + back legs)."""
        try:
            if selection.spot_price is None:
                self.logger.error(f"No spot price for {selection.symbol}")
                return False

            # Calculate date range for backfill
            entry_start = self.config.earnings_date - timedelta(
                days=self.config.entry_window_days[1]
            )

            # Backfill front leg
            front_params = BackfillOptionsParams(
                underlying=selection.symbol,
                spot_price=selection.spot_price,
                start_date=entry_start,
                end_date=self.config.earnings_date,
                bar_size=self.config.bar_size,
                selection_mode="atm",
                k_strikes=self.config.k_strikes,
                min_dte=self.config.front_leg_dte[0],
                max_dte=self.config.front_leg_dte[1],
                pipeline_name="ib_options",
                dataset_name=self.config.options_dataset,
                database_path=self.config.database_path,
            )

            front_result = execute_backfill_options(front_params)

            if not front_result.success:
                self.logger.error(
                    f"{selection.symbol} front leg failed: {front_result.error}"
                )
                return False

            # Backfill back leg
            back_params = BackfillOptionsParams(
                underlying=selection.symbol,
                spot_price=selection.spot_price,
                start_date=entry_start,
                end_date=self.config.earnings_date,
                bar_size=self.config.bar_size,
                selection_mode="atm",
                k_strikes=self.config.k_strikes,
                min_dte=self.config.back_leg_dte[0],
                max_dte=self.config.back_leg_dte[1],
                pipeline_name="ib_options",
                dataset_name=self.config.options_dataset,
                database_path=self.config.database_path,
            )

            back_result = execute_backfill_options(back_params)

            if not back_result.success:
                self.logger.error(
                    f"{selection.symbol} back leg failed: {back_result.error}"
                )
                return False

            return True

        except Exception as e:
            self.logger.error(f"Error processing {selection.symbol}: {e}")
            return False

    def _get_spot_price(self, symbol: str) -> Optional[float]:
        """Get current spot price from equity bars."""
        try:
            bars = self.equity_reader.get_bars(
                symbol=symbol,
                bar_size=self.config.bar_size,
                start_date=self.config.earnings_date - timedelta(days=7),
                end_date=self.config.earnings_date,
            )

            if bars.empty:
                return None

            # Use last available close price
            return float(bars.iloc[-1]["close"])

        except Exception as e:
            self.logger.debug(f"Error getting spot price for {symbol}: {e}")
            return None

    def _validate_data(self, spread_selections: List[SpreadExpirations]) -> Dict:
        """Validate that all required data was collected."""
        validation = {
            "total_symbols": len(spread_selections),
            "valid_expirations": len([s for s in spread_selections if s.is_valid()]),
            "missing_front": [s.symbol for s in spread_selections if s.front_expiry is None],
            "missing_back": [s.symbol for s in spread_selections if s.back_expiry is None],
            "no_spot_price": [s.symbol for s in spread_selections if s.spot_price is None],
        }

        return validation


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    """CLI entry point for calendar spread data collection."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Automated calendar spread data collection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Collect data for Nov 13 earnings with default settings
  python collect_calendar_spread_data.py 2025-11-13

  # Custom DTE ranges and parallel workers
  python collect_calendar_spread_data.py 2025-11-13 \\
      --front-dte 14 25 \\
      --back-dte 35 60 \\
      --workers 10

  # Custom entry window
  python collect_calendar_spread_data.py 2025-11-13 \\
      --entry-window 10 25
        """
    )

    parser.add_argument(
        "earnings_date",
        type=lambda s: date.fromisoformat(s),
        help="Earnings date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--entry-window",
        type=int,
        nargs=2,
        default=[10, 25],
        metavar=("MIN", "MAX"),
        help="Entry window (days before earnings) [default: 10 25]",
    )
    parser.add_argument(
        "--front-dte",
        type=int,
        nargs=2,
        default=[14, 25],
        metavar=("MIN", "MAX"),
        help="Front leg DTE range from earnings [default: 14 25]",
    )
    parser.add_argument(
        "--back-dte",
        type=int,
        nargs=2,
        default=[35, 60],
        metavar=("MIN", "MAX"),
        help="Back leg DTE range from earnings [default: 35 60]",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Parallel processing workers [default: 5]",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("logs"),
        help="Output directory for logs and results [default: logs]",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging (DEBUG level)",
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ]
    )

    # Create output directory
    args.output.mkdir(parents=True, exist_ok=True)

    # Print banner
    print("=" * 70)
    print("CALENDAR SPREAD DATA COLLECTION")
    print("=" * 70)
    print(f"Earnings Date:    {args.earnings_date}")
    print(f"Entry Window:     {args.entry_window[0]}-{args.entry_window[1]} days before")
    print(f"Front Leg DTE:    {args.front_dte[0]}-{args.front_dte[1]}")
    print(f"Back Leg DTE:     {args.back_dte[0]}-{args.back_dte[1]}")
    print(f"Workers:          {args.workers}")
    print("=" * 70)
    print()

    # Create config
    config = CalendarSpreadConfig(
        earnings_date=args.earnings_date,
        entry_window_days=tuple(args.entry_window),
        front_leg_dte=tuple(args.front_dte),
        back_leg_dte=tuple(args.back_dte),
        max_workers=args.workers,
    )

    # Run collection
    collector = CalendarSpreadDataCollector(config)
    results = collector.run()

    # Save results
    results_file = args.output / f"collection_summary_{args.earnings_date}.json"
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    # Print summary
    print()
    print("=" * 70)
    print("COLLECTION COMPLETE")
    print("=" * 70)
    print(f"Earnings Date:    {results['earnings_date']}")
    print(f"Total Symbols:    {results['total_symbols']}")
    print(f"Successful:       {results['successful']}")
    print(f"Failed:           {results['failed']}")
    print(f"Duration:         {results['duration_seconds']:.1f}s ({results['duration_seconds']/60:.1f}min)")

    if results['errors']:
        print(f"\nErrors ({len(results['errors'])}):")
        for error in results['errors'][:10]:  # Show first 10
            print(f"  • {error}")
        if len(results['errors']) > 10:
            print(f"  ... and {len(results['errors']) - 10} more")

    print(f"\nResults saved: {results_file}")
    print("=" * 70)

    # Exit code
    return 0 if results['failed'] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
