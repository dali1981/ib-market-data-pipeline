"""
Data providers for IB backtesting.

Adapts dlt-ibapi repositories (Parquet readers) to the tools/ backtest framework.

Key adapters:
- IBBacktestDataProvider: Provides market data (equity + options)
- EarningsCalendarProvider: Provides earnings calendar data
- OptionsChainProvider: Provides option chain snapshots
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, date
from decimal import Decimal

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
    Adapter: OptionChainSnapshotReader → tools/ OptionChain interface.

    Provides option chain snapshots for strategy analysis.

    Example:
        >>> provider = OptionsChainProvider(chain_reader)
        >>> chain = provider.get_chain("AAPL", datetime.now())
    """

    def __init__(self, option_chain_reader: OptionChainSnapshotReader):
        """
        Initialize options chain provider.

        Args:
            option_chain_reader: Option chain snapshot reader
        """
        self.reader = option_chain_reader

    def get_chain(self, symbol: str, timestamp: datetime) -> Optional[OptionChain]:
        """
        Get option chain for symbol at timestamp.

        Args:
            symbol: Underlying symbol
            timestamp: Timestamp

        Returns:
            OptionChain or None if not available
        """
        try:
            # Get chain snapshot
            chain_df = self.reader.get_chain(
                underlying=symbol,
                snapshot_date=timestamp.date(),
            )

            if chain_df.empty:
                return None

            # Convert to OptionContract objects
            contracts = []

            for _, row in chain_df.iterrows():
                # Parse expiry
                expiry = row["expiry"]
                if isinstance(expiry, str):
                    expiry = datetime.fromisoformat(expiry)

                # Create instrument identifier
                exp_str = expiry.strftime("%y%m%d")
                instrument = f"{symbol}-{exp_str}-{row['strike']}-{row['right']}"

                contract = OptionContract(
                    instrument=instrument,
                    underlying=symbol,
                    expiry=expiry,
                    strike=float(row["strike"]),
                    right=row["right"],
                    bid=float(row.get("bid", 0.0)),
                    ask=float(row.get("ask", 0.0)),
                    mid=(float(row.get("bid", 0.0)) + float(row.get("ask", 0.0))) / 2.0,
                    volume=int(row.get("volume", 0)),
                    open_interest=int(row.get("open_interest", 0)),
                    last=float(row.get("last", 0.0)) if row.get("last") else None,
                )

                contracts.append(contract)

            # Create OptionChain
            chain = OptionChain(
                underlying=symbol,
                timestamp=timestamp,
                contracts=contracts,
                spot_price=None,  # Will be populated separately
            )

            return chain

        except Exception:
            return None
