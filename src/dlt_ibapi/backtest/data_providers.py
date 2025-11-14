"""
Data providers for IB backtesting.

Adapts dlt-ibapi repositories (Parquet readers) to the tools/ backtest framework.

Key adapters:
- IBBacktestDataProvider: Provides market data (equity + options)
- EarningsCalendarProvider: Provides earnings calendar data
- OptionsChainProvider: Provides option chain snapshots (metadata only, no prices)

Note: Option chain snapshots contain metadata (strikes, expirations) but NOT prices.
Prices must be fetched separately from OptionBarsReader.
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
        >>> provider = EarningsCalendarProvider("./data", "earnings")
        >>> upcoming = provider.get_upcoming_earnings(30, datetime.now())
    """

    def __init__(self, database_path: str, dataset_name: str = "earnings"):
        """
        Initialize earnings calendar provider.

        Args:
            database_path: Path to data directory (e.g., "./data")
            dataset_name: Dataset name for earnings data (default: "earnings")
        """
        self.database_path = database_path
        self.dataset_name = dataset_name

        # Import from local repositories
        try:
            from dlt_ibapi.repositories import EarningsCalendarReader

            self.reader = EarningsCalendarReader(database_path, dataset_name)
        except (ImportError, ValueError) as e:
            # ValueError if dataset doesn't exist yet
            self.reader = None

    def get_upcoming_earnings(
        self,
        days_ahead: int,
        timestamp: datetime,
        symbols: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get earnings announcements in next N days.

        Args:
            days_ahead: Number of days ahead to search
            timestamp: Current timestamp
            symbols: Optional list of symbols to filter

        Returns:
            List of earnings events with symbol, date, time
        """
        if self.reader is None:
            return []

        try:
            # Query earnings calendar
            earnings_df = self.reader.get_upcoming_earnings(
                days_ahead=days_ahead,
                from_date=timestamp.date(),
                symbols=symbols,
            )

            if earnings_df.empty:
                return []

            # Convert to list of dicts
            earnings_list = []
            for _, row in earnings_df.iterrows():
                earnings_list.append({
                    "symbol": row["symbol"],
                    "earnings_date": row["earnings_date"],
                    "earnings_time": row.get("earnings_time", "UNKNOWN"),
                    "company_name": row.get("company_name", ""),
                    "fiscal_quarter": row.get("fiscal_quarter"),
                    "eps_forecast": row.get("eps_forecast"),
                })

            return earnings_list

        except Exception:
            return []


class OptionsChainProvider:
    """
    Provides option chain snapshots for backtesting.

    Reads daily-collected option chain snapshots from OptionChainSnapshotReader.
    Snapshots contain metadata about available options (strikes, expirations) but NOT
    prices. Prices come from OptionBarsReader.

    **Data Collection**:
    Snapshots must be collected daily via: `dlt-ibapi snapshot SYMBOL --date YYYY-MM-DD`

    **What Snapshots Contain**:
    - Available strikes for each expiration
    - Available expirations with DTE filtering
    - Option metadata (exchange, trading class)

    **What Snapshots DON'T Contain**:
    - Bid/ask prices (use OptionBarsReader for prices)
    - Volume/open interest (use OptionBarsReader for prices)
    - Implied volatility (calculated from prices)

    **Important**: Snapshots cannot be collected retroactively for expired options.
    Must collect daily to avoid gaps.

    Example:
        >>> from dlt_ibapi.repositories import OptionChainSnapshotReader
        >>> reader = OptionChainSnapshotReader("./data", "option_chains")
        >>> provider = OptionsChainProvider(reader)
        >>> chain = provider.get_chain("AAPL", datetime(2024, 10, 22))
        >>> print(f"Expirations: {len(chain.expirations)}")
    """

    def __init__(self, option_chain_reader: OptionChainSnapshotReader):
        """
        Initialize options chain provider.

        Args:
            option_chain_reader: Reader for option chain snapshots
        """
        self.reader = option_chain_reader

    def get_chain(self, symbol: str, timestamp: datetime) -> Optional[OptionChain]:
        """
        Get option chain with pricing (NOT IMPLEMENTED).

        This method is not implemented because option chain snapshots do NOT contain
        pricing data. Snapshots only contain metadata (available strikes/expirations).

        **Why This Doesn't Work**:
        - Snapshots captured by dlt-ibapi contain metadata only (no prices)
        - Prices must be fetched separately from OptionBarsReader
        - The OptionChain model expects pricing data (bid/ask/IV)

        **Alternative Approach**:
        1. Use OptionChainSnapshotReader to get available expirations/strikes
        2. Use OptionBarsReader to get OHLCV for specific contracts
        3. Calculate Greeks from option bars using GreeksCalculator

        Args:
            symbol: Underlying symbol
            timestamp: Timestamp

        Raises:
            NotImplementedError: Snapshots don't contain pricing data

        Example (correct approach):
            >>> # Get available expirations from snapshot
            >>> reader = self.reader
            >>> expirations = reader.get_available_expirations(
            ...     underlying="AAPL",
            ...     as_of=date(2024, 10, 22),
            ...     min_dte=14,
            ...     max_dte=60,
            ... )
            >>>
            >>> # Get prices from option bars
            >>> option_bars_reader = OptionBarsReader("./data", "options")
            >>> for expiry in expirations:
            ...     strikes = reader.get_strikes_for_expiry("AAPL", date(2024, 10, 22), expiry)
            ...     for strike in strikes:
            ...         bars = option_bars_reader.get_bars(
            ...             underlying="AAPL",
            ...             expiry=expiry,
            ...             strike=strike,
            ...             right="C",
            ...             bar_size="1 day",
            ...             start_date=date(2024, 10, 22),
            ...             end_date=date(2024, 10, 22),
            ...         )
        """
        raise NotImplementedError(
            f"OptionsChainProvider.get_chain() cannot return pricing data.\n"
            f"\n"
            f"Option chain snapshots only contain metadata (strikes, expirations).\n"
            f"Prices must be fetched separately from OptionBarsReader.\n"
            f"\n"
            f"Use this pattern instead:\n"
            f"1. Get expirations: reader.get_available_expirations(symbol, date, min_dte, max_dte)\n"
            f"2. Get strikes: reader.get_strikes_for_expiry(symbol, date, expiry)\n"
            f"3. Get prices: option_bars_reader.get_bars(underlying, expiry, strike, right, ...)\n"
            f"\n"
            f"See OptionsBacktestRunner._get_option_chains() for working example."
        )
