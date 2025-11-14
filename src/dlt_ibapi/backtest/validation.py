"""
Comprehensive data validation for earnings calendar backtesting.

Validates data availability BEFORE starting backtest to ensure:
- Earnings data is valid and parseable
- Equity bars exist with sufficient coverage
- Option contracts are available for target DTE ranges
- Option bars exist for both legs of calendar spreads

Provides detailed validation reports to explain why events are skipped.
"""

from typing import List, Dict, Set, Optional, Tuple
from datetime import date, timedelta
from dataclasses import dataclass, field
import json
from pathlib import Path

from dlt_ibapi.repositories import (
    EquityBarsReader,
    OptionBarsReader,
    OptionChainSnapshotReader,
)
from dlt_ibapi.backfill.gap_detection import trading_day_range
from dlt_ibapi.backtest.earnings_loader import EarningsEvent
from dlt_ibapi.backtest.data_providers import BacktestDataRequirements
from dlt_ibapi.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class DataCoverageReport:
    """Report on data coverage for a symbol."""
    symbol: str
    available: bool
    coverage: float  # 0.0-1.0
    missing_dates: List[date]
    date_range: Tuple[Optional[date], Optional[date]]
    total_expected_days: int
    total_actual_days: int


@dataclass
class OptionContractInfo:
    """Information about an option contract for backtesting."""
    symbol: str
    expiry: date
    strike: float
    right: str  # "C" or "P"
    dte_at_entry: int
    instrument: str  # "AAPL-250117-150-C"


@dataclass
class OptionCoverageReport:
    """Report on option availability for an earnings event."""
    symbol: str
    earnings_date: date
    spot_price: Optional[float]
    front_month: Optional[OptionContractInfo]
    back_month: Optional[OptionContractInfo]
    has_both_legs: bool
    reason_if_missing: str = ""


@dataclass
class BarsCoverageReport:
    """Report on option bars coverage for a specific contract."""
    contract: OptionContractInfo
    available: bool
    coverage: float  # 0.0-1.0
    missing_dates: List[date]
    first_bar: Optional[date]
    last_bar: Optional[date]
    total_expected_days: int
    total_actual_days: int


@dataclass
class SnapshotCoverageReport:
    """Report on option chain snapshot availability for an earnings date."""
    symbol: str
    date: date
    available: bool
    expiration_count: int = 0
    reason: Optional[str] = None


@dataclass
class ValidationSummary:
    """
    Summary of validation results.

    Categorizes earnings events and provides statistics.
    """
    total_events: int
    valid_events: int
    partial_events: int
    invalid_events: int

    valid_symbols: Set[str] = field(default_factory=set)
    invalid_symbols: Dict[str, str] = field(default_factory=dict)  # symbol -> reason

    skip_reasons: Dict[str, int] = field(default_factory=dict)  # reason -> count

    equity_coverage_avg: float = 0.0
    option_coverage_avg: float = 0.0

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "total_events": self.total_events,
            "valid_events": self.valid_events,
            "partial_events": self.partial_events,
            "invalid_events": self.invalid_events,
            "valid_symbols": sorted(self.valid_symbols),
            "invalid_symbols": self.invalid_symbols,
            "skip_reasons": self.skip_reasons,
            "equity_coverage_avg": self.equity_coverage_avg,
            "option_coverage_avg": self.option_coverage_avg,
        }


class BacktestDataValidator:
    """
    Validates data availability for earnings calendar backtests.

    Six-phase validation:
    1. Earnings data validation
    2. Equity data coverage
    3. Option chain snapshot availability (NEW)
    4. Option contracts availability
    5. Option bars coverage
    6. Generate comprehensive report

    Example:
        >>> validator = BacktestDataValidator(
        ...     equity_reader,
        ...     option_bars_reader,
        ...     option_chain_reader,
        ... )
        >>> requirements = BacktestDataRequirements()
        >>> report = validator.validate_all(earnings_events, requirements)
        >>> print(f"Valid: {report.valid_events}/{report.total_events}")
    """

    def __init__(
        self,
        equity_reader: EquityBarsReader,
        option_bars_reader: OptionBarsReader,
        option_chain_reader: OptionChainSnapshotReader,
    ):
        """
        Initialize validator.

        Args:
            equity_reader: Reader for equity bars
            option_bars_reader: Reader for option bars
            option_chain_reader: Reader for option chain snapshots
        """
        self.equity_reader = equity_reader
        self.option_bars_reader = option_bars_reader
        self.option_chain_reader = option_chain_reader

    def validate_all(
        self,
        earnings_events: List[EarningsEvent],
        requirements: BacktestDataRequirements,
    ) -> ValidationSummary:
        """
        Run complete validation on all earnings events.

        Args:
            earnings_events: List of earnings to validate
            requirements: Data requirements configuration

        Returns:
            ValidationSummary with categorized events
        """
        logger.info(f"Validating data for {len(earnings_events)} earnings events")

        # Validate requirements
        requirements.validate()

        valid_events = []
        partial_events = []
        invalid_events = []

        valid_symbols = set()
        invalid_symbols = {}
        skip_reasons = {}

        equity_coverages = []
        option_coverages = []

        for event in earnings_events:
            # Phase 2: Equity coverage
            equity_report = self.validate_equity_coverage(
                event=event,
                requirements=requirements,
            )

            if not equity_report.available:
                invalid_events.append(event)
                invalid_symbols[event.symbol] = "No equity data"
                reason = "missing_equity_data"
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                continue

            if equity_report.coverage < requirements.min_equity_coverage:
                invalid_events.append(event)
                invalid_symbols[event.symbol] = (
                    f"Insufficient equity coverage ({equity_report.coverage:.1%})"
                )
                reason = "low_equity_coverage"
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                continue

            equity_coverages.append(equity_report.coverage)

            # Phase 2.5: Option chain snapshot
            snapshot_report = self.validate_option_chain_snapshot(
                event=event,
                requirements=requirements,
            )

            if not snapshot_report.available:
                invalid_events.append(event)
                invalid_symbols[event.symbol] = snapshot_report.reason or "No option chain snapshot"
                reason = "missing_option_chain_snapshot"
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                continue

            # Phase 3: Option contracts
            option_report = self.validate_option_contracts(
                event=event,
                spot_price=equity_report.spot_price or 0.0,
                requirements=requirements,
            )

            if not option_report.has_both_legs:
                invalid_events.append(event)
                invalid_symbols[event.symbol] = option_report.reason_if_missing
                reason = "missing_option_contracts"
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                continue

            # Phase 4: Option bars coverage
            front_bars_report = self.validate_option_bars_coverage(
                contract=option_report.front_month,
                entry_date=event.earnings_date,
                requirements=requirements,
            )

            back_bars_report = self.validate_option_bars_coverage(
                contract=option_report.back_month,
                entry_date=event.earnings_date,
                requirements=requirements,
            )

            if not front_bars_report.available or not back_bars_report.available:
                invalid_events.append(event)
                invalid_symbols[event.symbol] = "Missing option bars"
                reason = "missing_option_bars"
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                continue

            # Check coverage thresholds
            min_coverage = min(front_bars_report.coverage, back_bars_report.coverage)
            option_coverages.append(min_coverage)

            if min_coverage < requirements.min_option_bars_coverage:
                # Partial event (has data but below threshold)
                partial_events.append(event)
                invalid_symbols[event.symbol] = (
                    f"Low option bars coverage ({min_coverage:.1%})"
                )
                reason = "low_option_bars_coverage"
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                continue

            # Valid event!
            valid_events.append(event)
            valid_symbols.add(event.symbol)

        # Calculate averages
        equity_avg = sum(equity_coverages) / len(equity_coverages) if equity_coverages else 0.0
        option_avg = sum(option_coverages) / len(option_coverages) if option_coverages else 0.0

        summary = ValidationSummary(
            total_events=len(earnings_events),
            valid_events=len(valid_events),
            partial_events=len(partial_events),
            invalid_events=len(invalid_events),
            valid_symbols=valid_symbols,
            invalid_symbols=invalid_symbols,
            skip_reasons=skip_reasons,
            equity_coverage_avg=equity_avg,
            option_coverage_avg=option_avg,
        )

        logger.info(
            f"Validation complete: {summary.valid_events} valid, "
            f"{summary.invalid_events} invalid "
            f"({summary.valid_events/summary.total_events*100:.1f}% valid)"
        )

        return summary

    def validate_equity_coverage(
        self,
        event: EarningsEvent,
        requirements: BacktestDataRequirements,
    ) -> 'EquityCoverageReport':
        """
        Validate equity data coverage for an earnings event.

        Checks:
        - Symbol exists in database
        - Data available from (earnings_date - lookback) to earnings_date
        - Coverage meets minimum threshold

        Args:
            event: Earnings event
            requirements: Data requirements

        Returns:
            EquityCoverageReport
        """
        symbol = event.symbol
        earnings_date = event.earnings_date
        lookback_start = earnings_date - timedelta(days=requirements.equity_lookback_days)

        try:
            # Get present dates
            present_dates = self.equity_reader.get_present_dates_for_symbol(
                symbol=symbol,
                bar_size=requirements.equity_bar_size,
                start_date=lookback_start,
                end_date=earnings_date,
            )

            if not present_dates:
                return EquityCoverageReport(
                    symbol=symbol,
                    available=False,
                    coverage=0.0,
                    missing_dates=[],
                    date_range=(None, None),
                    total_expected_days=0,
                    total_actual_days=0,
                    spot_price=None,
                )

            # Get expected trading days
            expected_days = set(trading_day_range(
                lookback_start,
                earnings_date,
                exchange=requirements.exchange,
            ))

            # Calculate coverage
            missing_dates = sorted(expected_days - present_dates)
            coverage = len(present_dates & expected_days) / len(expected_days) if expected_days else 0.0

            # Get spot price at earnings date (or nearest)
            spot_price = None
            try:
                bars = self.equity_reader.get_bars(
                    symbol=symbol,
                    bar_size=requirements.equity_bar_size,
                    start_date=earnings_date,
                    end_date=earnings_date,
                )
                if not bars.empty:
                    spot_price = float(bars.iloc[-1]["close"])
            except Exception:
                pass

            return EquityCoverageReport(
                symbol=symbol,
                available=True,
                coverage=coverage,
                missing_dates=missing_dates,
                date_range=(min(present_dates), max(present_dates)),
                total_expected_days=len(expected_days),
                total_actual_days=len(present_dates & expected_days),
                spot_price=spot_price,
            )

        except Exception as e:
            logger.error(f"Error validating equity coverage for {symbol}: {e}")
            return EquityCoverageReport(
                symbol=symbol,
                available=False,
                coverage=0.0,
                missing_dates=[],
                date_range=(None, None),
                total_expected_days=0,
                total_actual_days=0,
                spot_price=None,
            )

    def validate_option_chain_snapshot(
        self,
        event: EarningsEvent,
        requirements: BacktestDataRequirements,
    ) -> SnapshotCoverageReport:
        """
        Validate option chain snapshot exists for earnings date.

        Checks if daily snapshot was captured for the earnings date.
        Snapshot must contain available expirations.

        Args:
            event: Earnings event to validate
            requirements: Data requirements configuration

        Returns:
            SnapshotCoverageReport with availability status and details
        """
        symbol = event.symbol
        earnings_date = event.earnings_date

        logger.debug(f"Validating option chain snapshot for {symbol} on {earnings_date}")

        # Check if snapshot exists for this date
        try:
            available_snapshots = self.option_chain_reader.get_available_snapshots(symbol)

            if earnings_date not in available_snapshots:
                logger.debug(
                    f"No snapshot for {symbol} on {earnings_date}. "
                    f"Available: {len(available_snapshots)} dates total"
                )
                return SnapshotCoverageReport(
                    symbol=symbol,
                    date=earnings_date,
                    available=False,
                    reason="No option chain snapshot captured for this date",
                )

            # Check if snapshot has expirations
            expirations = self.option_chain_reader.get_available_expirations(
                underlying=symbol,
                as_of=earnings_date,
            )

            if not expirations:
                logger.debug(
                    f"Snapshot for {symbol} on {earnings_date} has no expirations"
                )
                return SnapshotCoverageReport(
                    symbol=symbol,
                    date=earnings_date,
                    available=False,
                    reason="Snapshot exists but contains no expirations",
                )

            logger.debug(
                f"Snapshot OK for {symbol} on {earnings_date}: "
                f"{len(expirations)} expirations available"
            )

            return SnapshotCoverageReport(
                symbol=symbol,
                date=earnings_date,
                available=True,
                expiration_count=len(expirations),
            )

        except Exception as e:
            logger.warning(
                f"Error checking snapshot for {symbol} on {earnings_date}: {e}"
            )
            return SnapshotCoverageReport(
                symbol=symbol,
                date=earnings_date,
                available=False,
                reason=f"Error reading snapshot: {str(e)}",
            )

    def validate_option_contracts(
        self,
        event: EarningsEvent,
        spot_price: float,
        requirements: BacktestDataRequirements,
    ) -> OptionCoverageReport:
        """
        Validate option contracts exist for earnings event.

        Determines which option contracts to use for calendar spread based on:
        - Front month: DTE in range front_month_dte
        - Back month: DTE in range back_month_dte
        - ATM strike (nearest to spot)

        Args:
            event: Earnings event
            spot_price: Spot price at earnings date
            requirements: Data requirements

        Returns:
            OptionCoverageReport
        """
        symbol = event.symbol
        earnings_date = event.earnings_date

        try:
            # Get available expirations
            available_expirations = self.option_bars_reader.get_available_expirations(
                underlying=symbol,
                bar_size=requirements.option_bar_size,
            )

            if not available_expirations:
                return OptionCoverageReport(
                    symbol=symbol,
                    earnings_date=earnings_date,
                    spot_price=spot_price,
                    front_month=None,
                    back_month=None,
                    has_both_legs=False,
                    reason_if_missing="No option expirations available",
                )

            # Find front month expiry
            front_expiry = self._find_expiry_in_dte_range(
                earnings_date=earnings_date,
                available_expirations=available_expirations,
                dte_min=requirements.front_month_dte[0],
                dte_max=requirements.front_month_dte[1],
                tolerance=requirements.dte_tolerance,
            )

            # Find back month expiry
            back_expiry = self._find_expiry_in_dte_range(
                earnings_date=earnings_date,
                available_expirations=available_expirations,
                dte_min=requirements.back_month_dte[0],
                dte_max=requirements.back_month_dte[1],
                tolerance=requirements.dte_tolerance,
            )

            if not front_expiry:
                return OptionCoverageReport(
                    symbol=symbol,
                    earnings_date=earnings_date,
                    spot_price=spot_price,
                    front_month=None,
                    back_month=None,
                    has_both_legs=False,
                    reason_if_missing=(
                        f"No front month expiry in DTE range "
                        f"{requirements.front_month_dte}"
                    ),
                )

            if not back_expiry:
                return OptionCoverageReport(
                    symbol=symbol,
                    earnings_date=earnings_date,
                    spot_price=spot_price,
                    front_month=None,
                    back_month=None,
                    has_both_legs=False,
                    reason_if_missing=(
                        f"No back month expiry in DTE range "
                        f"{requirements.back_month_dte}"
                    ),
                )

            # Calculate ATM strike (round to nearest 5)
            atm_strike = round(spot_price / 5.0) * 5.0

            # Create contract info
            front_dte = (front_expiry - earnings_date).days
            back_dte = (back_expiry - earnings_date).days

            front_contract = OptionContractInfo(
                symbol=symbol,
                expiry=front_expiry,
                strike=atm_strike,
                right="C",  # Assume calls for now
                dte_at_entry=front_dte,
                instrument=f"{symbol}-{front_expiry:%y%m%d}-{atm_strike}-C",
            )

            back_contract = OptionContractInfo(
                symbol=symbol,
                expiry=back_expiry,
                strike=atm_strike,
                right="C",
                dte_at_entry=back_dte,
                instrument=f"{symbol}-{back_expiry:%y%m%d}-{atm_strike}-C",
            )

            return OptionCoverageReport(
                symbol=symbol,
                earnings_date=earnings_date,
                spot_price=spot_price,
                front_month=front_contract,
                back_month=back_contract,
                has_both_legs=True,
                reason_if_missing="",
            )

        except Exception as e:
            logger.error(f"Error validating option contracts for {symbol}: {e}")
            return OptionCoverageReport(
                symbol=symbol,
                earnings_date=earnings_date,
                spot_price=spot_price,
                front_month=None,
                back_month=None,
                has_both_legs=False,
                reason_if_missing=f"Error: {str(e)}",
            )

    def validate_option_bars_coverage(
        self,
        contract: Optional[OptionContractInfo],
        entry_date: date,
        requirements: BacktestDataRequirements,
    ) -> BarsCoverageReport:
        """
        Validate option bars exist for a contract.

        Args:
            contract: Option contract info
            entry_date: Entry date (earnings date)
            requirements: Data requirements

        Returns:
            BarsCoverageReport
        """
        if contract is None:
            return BarsCoverageReport(
                contract=None,
                available=False,
                coverage=0.0,
                missing_dates=[],
                first_bar=None,
                last_bar=None,
                total_expected_days=0,
                total_actual_days=0,
            )

        try:
            exit_date = entry_date + timedelta(days=requirements.entry_window_days)

            # Get present dates for this contract
            present_dates = self.option_bars_reader.get_present_dates_for_contract(
                underlying=contract.symbol,
                expiry=contract.expiry,
                strike=contract.strike,
                right=contract.right,
                bar_size=requirements.option_bar_size,
                start_date=entry_date,
                end_date=exit_date,
            )

            if not present_dates:
                return BarsCoverageReport(
                    contract=contract,
                    available=False,
                    coverage=0.0,
                    missing_dates=[],
                    first_bar=None,
                    last_bar=None,
                    total_expected_days=0,
                    total_actual_days=0,
                )

            # Calculate expected days
            expected_days = set(trading_day_range(
                entry_date,
                exit_date,
                exchange=requirements.exchange,
            ))

            # Calculate coverage
            missing_dates = sorted(expected_days - present_dates)
            coverage = len(present_dates & expected_days) / len(expected_days) if expected_days else 0.0

            return BarsCoverageReport(
                contract=contract,
                available=True,
                coverage=coverage,
                missing_dates=missing_dates,
                first_bar=min(present_dates) if present_dates else None,
                last_bar=max(present_dates) if present_dates else None,
                total_expected_days=len(expected_days),
                total_actual_days=len(present_dates & expected_days),
            )

        except Exception as e:
            logger.error(f"Error validating option bars for {contract.instrument}: {e}")
            return BarsCoverageReport(
                contract=contract,
                available=False,
                coverage=0.0,
                missing_dates=[],
                first_bar=None,
                last_bar=None,
                total_expected_days=0,
                total_actual_days=0,
            )

    def _find_expiry_in_dte_range(
        self,
        earnings_date: date,
        available_expirations: List[date],
        dte_min: int,
        dte_max: int,
        tolerance: int = 7,
    ) -> Optional[date]:
        """
        Find expiration in DTE range.

        Args:
            earnings_date: Earnings date
            available_expirations: Available expirations
            dte_min: Minimum DTE
            dte_max: Maximum DTE
            tolerance: Allow ±tolerance days

        Returns:
            Expiration date or None
        """
        candidates = []

        for exp in available_expirations:
            dte = (exp - earnings_date).days

            # Check if in range (with tolerance)
            if (dte_min - tolerance) <= dte <= (dte_max + tolerance):
                candidates.append((abs(dte - (dte_min + dte_max) / 2), exp))

        if not candidates:
            return None

        # Return closest to midpoint of range
        candidates.sort()
        return candidates[0][1]

    def save_validation_report(
        self,
        summary: ValidationSummary,
        output_path: str,
    ):
        """
        Save validation summary to JSON file.

        Args:
            summary: Validation summary
            output_path: Output file path
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'w') as f:
            json.dump(summary.to_dict(), f, indent=2)

        logger.info(f"Validation report saved to: {output_path}")


@dataclass
class EquityCoverageReport(DataCoverageReport):
    """Equity data coverage report with spot price."""
    spot_price: Optional[float] = None
