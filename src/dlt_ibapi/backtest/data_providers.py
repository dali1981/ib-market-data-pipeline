"""
Data providers for IB backtesting.

Adapts dlt-ibapi repositories (Parquet readers) to the tools/ backtest framework.

Key adapters:
- IBBacktestDataProvider: Provides market data (equity + options)
- EarningsCalendarProvider: Provides earnings calendar data

NOTE: OptionsChainProvider has been DEPRECATED. The IB API does not provide
historical option chain snapshots. Use OptionBarsReader directly for option pricing.
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta, date
from decimal import Decimal
from dataclasses import dataclass

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dlt_ibapi.repositories import (
    EquityBarsReader,
    OptionBarsReader,
    OptionChainSnapshotReader,
)

# Import tools options models
from tools.options.models import Greeks
from tools.options.pricing import GreeksCalculator
from tools.options.spreads import OptionChain, OptionContract


@dataclass
class BacktestDataRequirements:
    """
    Configuration for backtest data requirements and validation thresholds.

    Used by BacktestDataValidator to determine minimum acceptable data coverage.
    """

    # Equity bars
    equity_bar_size: str = "1 day"
    equity_lookback_days: int = 60  # Need history before earnings for signals

    # Option contract selection
    front_month_dte: Tuple[int, int] = (14, 21)  # DTE range for front month
    back_month_dte: Tuple[int, int] = (35, 50)   # DTE range for back month
    dte_tolerance: int = 7  # Allow ±7 days when finding expiries
    atm_strike_range: int = 5  # Need ±5 strikes around ATM

    # Option bars
    option_bar_size: str = "1 day"
    entry_window_days: int = 7  # Hold spread for 7 days

    # Coverage thresholds
    min_equity_coverage: float = 0.90  # 90% of days must have equity data
    min_option_bars_coverage: float = 0.95  # 95% of option bars must exist

    # Execution
    exchange: str = "NYSE"  # Used for trading day calculations

    def validate(self) -> None:
        """Validate configuration is sensible."""
        if self.front_month_dte[0] >= self.back_month_dte[0]:
            raise ValueError(
                f"front_month_dte[0] ({self.front_month_dte[0]}) must be < "
                f"back_month_dte[0] ({self.back_month_dte[0]})"
            )

        if self.front_month_dte[1] >= self.back_month_dte[1]:
            raise ValueError(
                f"front_month_dte[1] ({self.front_month_dte[1]}) must be < "
                f"back_month_dte[1] ({self.back_month_dte[1]})"
            )

        if not (0.0 < self.min_equity_coverage <= 1.0):
            raise ValueError("min_equity_coverage must be between 0 and 1")

        if not (0.0 < self.min_option_bars_coverage <= 1.0):
            raise ValueError("min_option_bars_coverage must be between 0 and 1")


class IBBacktestDataProvider:
    """
    Adapter: dlt-ibapi repositories → tools/ backtest interface.

    Provides market data for backtesting by reading from Parquet files:
    - Equity bars (underlying prices)
    - Option bars (option OHLCV)
    - Option chain snapshots
    - Greeks calculation

    Example:
        >>> provider = IBBacktestDataProvider("./data")
        >>> spot = provider.get_latest_price("AAPL", datetime.now())
        >>> prices = provider.get_option_prices([...], datetime.now())
        >>> greeks = provider.get_greeks([...], datetime.now())
    """

    def __init__(
        self,
        data_path: str,
        risk_free_rate: float = 0.05,
    ):
        """
        Initialize IB backtest data provider.

        Args:
            data_path: Path to data directory containing Parquet files
            risk_free_rate: Risk-free rate for Greeks calculation
        """
        self.data_path = data_path

        # Initialize readers
        self.equity_reader = EquityBarsReader(data_path, "stocks")
        self.option_bars_reader = OptionBarsReader(data_path, "options")
        self.option_chain_reader = OptionChainSnapshotReader(data_path, "option_chains")

        # Greeks calculator
        self.greeks_calculator = GreeksCalculator(risk_free_rate=risk_free_rate)

    def get_latest_price(self, symbol: str, timestamp: datetime) -> Optional[float]:
        """
        Get underlying spot price at timestamp.

        Args:
            symbol: Underlying symbol
            timestamp: Timestamp

        Returns:
            Spot price or None if not available
        """
        try:
            bars = self.equity_reader.get_bars(
                symbol=symbol,
                bar_size="1 day",
                start_date=timestamp.date(),
                end_date=timestamp.date(),
            )

            if bars.empty:
                return None

            return float(bars.iloc[-1]["close"])

        except Exception:
            return None

    def get_option_prices(
        self,
        instruments: List[str],
        timestamp: datetime,
    ) -> Dict[str, float]:
        """
        Get option mid prices at timestamp.

        Args:
            instruments: List of option identifiers (e.g., "AAPL-250117-150-C")
            timestamp: Timestamp

        Returns:
            Dict mapping instrument → mid price
        """
        prices = {}

        for instrument in instruments:
            try:
                # Parse instrument: "AAPL-250117-150-C"
                parts = instrument.split("-")
                if len(parts) != 4:
                    continue

                underlying, exp_str, strike_str, right = parts

                # Parse expiry (YYMMDD format)
                expiry = datetime.strptime(exp_str, "%y%m%d").date()

                # Parse strike
                strike = float(strike_str)

                # Get option bars
                bars = self.option_bars_reader.get_bars(
                    underlying=underlying,
                    expiry=expiry,
                    strike=strike,
                    right=right,
                    bar_size="1 day",
                    start_date=timestamp.date(),
                    end_date=timestamp.date(),
                )

                if not bars.empty:
                    # Use mid price (average of high and low)
                    mid_price = (bars.iloc[-1]["high"] + bars.iloc[-1]["low"]) / 2.0
                    prices[instrument] = float(mid_price)

            except Exception:
                continue

        return prices

    def get_greeks(
        self,
        instruments: List[str],
        timestamp: datetime,
        risk_free_rate: Optional[float] = None,
    ) -> Dict[str, Greeks]:
        """
        Calculate Greeks for options at timestamp.

        Process:
        1. Get option prices
        2. Get underlying spot prices
        3. Calculate IV from option prices
        4. Calculate Greeks using Black-Scholes

        Args:
            instruments: List of option identifiers
            timestamp: Timestamp
            risk_free_rate: Override default risk-free rate

        Returns:
            Dict mapping instrument → Greeks
        """
        greeks_dict = {}
        r = risk_free_rate if risk_free_rate is not None else 0.05

        for instrument in instruments:
            try:
                # Parse instrument
                parts = instrument.split("-")
                if len(parts) != 4:
                    continue

                underlying, exp_str, strike_str, right = parts

                # Get option price
                option_prices = self.get_option_prices([instrument], timestamp)
                if instrument not in option_prices:
                    continue

                option_price = option_prices[instrument]

                # Get spot price
                spot = self.get_latest_price(underlying, timestamp)
                if spot is None:
                    continue

                # Parse expiry and calculate DTE
                expiry = datetime.strptime(exp_str, "%y%m%d")
                dte = (expiry.date() - timestamp.date()).days

                if dte <= 0:
                    continue

                # Parse strike
                strike = float(strike_str)

                # Calculate Greeks from price
                greeks = self.greeks_calculator.calculate_greeks_from_price(
                    option_price=option_price,
                    spot=spot,
                    strike=strike,
                    dte=dte,
                    option_type=right,
                    risk_free_rate=r,
                )

                greeks_dict[instrument] = greeks

            except Exception:
                continue

        return greeks_dict

    def get_iv_history(
        self,
        symbol: str,
        lookback: int,
        timestamp: datetime,
    ) -> Optional[List[float]]:
        """
        Get historical IV for a symbol.

        Note: This is a simplified implementation. In practice, you'd want
        to track ATM IV over time from option bars.

        Args:
            symbol: Underlying symbol
            lookback: Days of history
            timestamp: Current timestamp

        Returns:
            List of historical IV values or None
        """
        # TODO: Implement IV history tracking
        # For now, return None (strategies will skip IV percentile checks)
        return None


class EarningsCalendarProvider:
    """
    Adapter: EarningsCalendarReader → tools/ interface.

    Provides earnings calendar data for options strategies.

    Example:
        >>> provider = EarningsCalendarProvider(earnings_reader)
        >>> upcoming = provider.get_upcoming_earnings(30, datetime.now())
    """

    def __init__(self, data_path: str):
        """
        Initialize earnings calendar provider.

        Args:
            data_path: Path to earnings calendar data
        """
        self.data_path = data_path

        # Try to import earnings calendar reader
        try:
            # Import from earnings-calendar-dlt package
            from earnings_calendar.api import EarningsCalendarReader

            self.reader = EarningsCalendarReader(data_path)
        except ImportError:
            self.reader = None

    def get_upcoming_earnings(
        self,
        days_ahead: int,
        timestamp: datetime,
    ) -> List[Dict[str, Any]]:
        """
        Get earnings announcements in next N days.

        Args:
            days_ahead: Number of days ahead to search
            timestamp: Current timestamp

        Returns:
            List of earnings events with symbol, date, time
        """
        if self.reader is None:
            return []

        try:
            start_date = timestamp.date()
            end_date = start_date + timedelta(days=days_ahead)

            # Query earnings calendar
            earnings_df = self.reader.get_upcoming_earnings(
                start_date=start_date,
                end_date=end_date,
            )

            if earnings_df.empty:
                return []

            # Convert to list of dicts
            earnings_list = []
            for _, row in earnings_df.iterrows():
                earnings_list.append({
                    "symbol": row["symbol"],
                    "earnings_date": row["earnings_date"],
                    "earnings_time": row.get("earnings_time", "Unknown"),
                    "fiscal_quarter": row.get("fiscal_quarter"),
                    "eps_forecast": row.get("eps_forecast"),
                })

            return earnings_list

        except Exception:
            return []


class OptionsChainProvider:
    """
    DEPRECATED: This class is non-functional due to IB API limitations.

    The IB API does NOT provide historical option chain snapshots. It only provides
    current option chain parameters (expirations and strikes), WITHOUT pricing data
    (bid/ask/volume/open interest).

    For backtesting, you MUST use OptionBarsReader directly to get historical option
    prices for specific contracts.

    This class is kept for backward compatibility but will raise NotImplementedError.

    See: https://interactivebrokers.github.io/tws-api/historical_limitations.html

    Alternative:
        Use IBBacktestDataProvider.option_bars_reader.get_bars() to get historical
        option OHLCV for specific contracts selected via deterministic rules.
    """

    def __init__(self, option_chain_reader: OptionChainSnapshotReader):
        """
        Initialize options chain provider.

        Args:
            option_chain_reader: Option chain snapshot reader

        Warning:
            This provider is DEPRECATED and non-functional.
        """
        self.reader = option_chain_reader
        import warnings
        warnings.warn(
            "OptionsChainProvider is deprecated and non-functional. "
            "IB API does not provide historical option chain snapshots. "
            "Use OptionBarsReader directly for historical option prices.",
            DeprecationWarning,
            stacklevel=2,
        )

    def get_chain(self, symbol: str, timestamp: datetime) -> Optional[OptionChain]:
        """
        DEPRECATED: This method is non-functional.

        Args:
            symbol: Underlying symbol
            timestamp: Timestamp

        Raises:
            NotImplementedError: Always raises - IB API does not provide historical chains

        Note:
            Option chain snapshots collected via dlt-ibapi contain ONLY metadata
            (expirations and strikes), NOT pricing data (bid/ask/volume/OI).

            For backtesting, use OptionBarsReader.get_bars() to get historical
            option OHLCV for specific contracts:

            Example:
                >>> from dlt_ibapi.repositories import OptionBarsReader
                >>> reader = OptionBarsReader("./data", "options")
                >>> bars = reader.get_bars(
                ...     underlying="AAPL",
                ...     expiry=date(2025, 1, 17),
                ...     strike=150.0,
                ...     right="C",
                ...     bar_size="1 day",
                ...     start_date=date(2024, 12, 1),
                ...     end_date=date(2024, 12, 31),
                ... )
        """
        raise NotImplementedError(
            f"OptionsChainProvider.get_chain() is deprecated and non-functional.\n"
            f"\n"
            f"The IB API does NOT provide historical option chain snapshots.\n"
            f"Option chain snapshots only contain metadata (expirations, strikes),\n"
            f"NOT pricing data (bid/ask/volume/open interest).\n"
            f"\n"
            f"For backtesting:\n"
            f"1. Use deterministic option selection rules (ATM strike, DTE range)\n"
            f"2. Use OptionBarsReader.get_bars() to get historical option OHLCV\n"
            f"3. Select options based on available bar data\n"
            f"\n"
            f"See: docs/BACKTEST_QUICKSTART.md for details"
        )
