"""
IV Term Structure Analyzer for Calendar Spread Selection.

Analyzes implied volatility term structure to identify calendar spread opportunities
with maximum IV differential. Adapted from crypto_options project for IB data.

Key Functionality:
- Calculate ATM IV by expiration
- Find expiration pairs with maximum IV differential
- Calculate IV rank (historical percentile)
- Validate IV term structure for spread entry

Example:
    >>> analyzer = IVTermStructureAnalyzer(data_provider)
    >>> term_structure = analyzer.get_iv_term_structure("AEG", timestamp)
    >>> best_pair = analyzer.find_max_iv_differential(term_structure)
    >>> print(f"Best spread: {best_pair['front_expiration']} / {best_pair['back_expiration']}")
"""

from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

from dlt_ibapi.repositories import OptionBarsReader, OptionChainSnapshotReader
from tools.options.pricing import GreeksCalculator


class IVTermStructureAnalyzer:
    """
    Analyze IV term structure for calendar spread expiration selection.

    This analyzer computes ATM implied volatility across different expirations
    and identifies pairs with maximum IV differential. Unlike fixed-DTE strategies,
    this approach dynamically selects expirations based on current term structure.

    Process:
    1. Get available expirations from option chain snapshot
    2. For each expiration, calculate average ATM IV from option bars
    3. Identify front/back expiration pair with max IV differential
    4. Optionally filter by IV rank (historical percentile)

    Example:
        >>> from dlt_ibapi.backtest import IBBacktestDataProvider
        >>> data_provider = IBBacktestDataProvider("./data_delta")
        >>> analyzer = IVTermStructureAnalyzer(data_provider)
        >>>
        >>> # Get IV term structure
        >>> term_structure = analyzer.get_iv_term_structure(
        ...     symbol="AEG",
        ...     timestamp=datetime(2025, 11, 12),
        ...     expirations=[date(2025, 11, 28), date(2025, 12, 19)]
        ... )
        >>>
        >>> # Find best expiration pair
        >>> best_pair = analyzer.find_max_iv_differential(
        ...     term_structure,
        ...     front_dte_range=(14, 21),
        ...     back_dte_range=(35, 50)
        ... )
        >>> print(best_pair)
    """

    def __init__(self, data_provider, risk_free_rate: float = 0.05):
        """
        Initialize IV term structure analyzer.

        Args:
            data_provider: IBBacktestDataProvider instance
            risk_free_rate: Risk-free rate for Greeks calculation
        """
        self.data_provider = data_provider
        self.greeks_calculator = GreeksCalculator(risk_free_rate=risk_free_rate)
        self.option_bars_reader = data_provider.option_bars_reader
        self.equity_reader = data_provider.equity_reader

    def get_iv_term_structure(
        self,
        symbol: str,
        timestamp: datetime,
        expirations: List[date],
        moneyness_min: float = 0.98,
        moneyness_max: float = 1.02,
    ) -> pd.DataFrame:
        """
        Calculate ATM IV for each expiration.

        Process:
        1. Get current spot price
        2. For each expiration:
           a. Find ATM strikes (spot * 0.98 to spot * 1.02)
           b. Read option bars for each ATM strike
           c. Calculate IV from mid price using GreeksCalculator
           d. Average IV across ATM contracts
        3. Return DataFrame with expiration, DTE, and ATM IV

        Args:
            symbol: Underlying symbol (e.g., "AEG")
            timestamp: Current timestamp
            expirations: List of expiration dates to analyze
            moneyness_min: Minimum moneyness for ATM (default: 0.98 = 98%)
            moneyness_max: Maximum moneyness for ATM (default: 1.02 = 102%)

        Returns:
            DataFrame with columns:
            - expiration_date: Expiration date
            - days_to_expiry: Days until expiration
            - atm_iv: Average ATM implied volatility
            - contract_count: Number of ATM contracts
            - iv_std: Standard deviation of IV

        Example:
            >>> term_structure = analyzer.get_iv_term_structure(
            ...     "AEG",
            ...     datetime(2025, 11, 12),
            ...     [date(2025, 11, 28), date(2025, 12, 19)]
            ... )
            >>> print(term_structure)
               expiration_date  days_to_expiry  atm_iv  contract_count  iv_std
            0       2025-11-28              16    0.45               3    0.02
            1       2025-12-19              37    0.52               4    0.03
        """
        # Get spot price
        spot_price = self.data_provider.get_latest_price(symbol, timestamp)
        if spot_price is None:
            return pd.DataFrame(columns=[
                'expiration_date', 'days_to_expiry', 'atm_iv',
                'contract_count', 'iv_std'
            ])

        # Calculate ATM strike range
        atm_strike_min = spot_price * moneyness_min
        atm_strike_max = spot_price * moneyness_max

        results = []

        for expiration in expirations:
            # Calculate DTE
            dte = (expiration - timestamp.date()).days
            if dte <= 0:
                continue  # Skip expired options

            # Get available strikes from option chain snapshot
            snapshot_reader = OptionChainSnapshotReader(
                self.data_provider.data_path, "option_chains"
            )

            try:
                all_strikes = snapshot_reader.get_strikes_for_expiry(
                    underlying=symbol,
                    as_of=timestamp.date(),
                    expiration=expiration,
                )
            except Exception:
                continue  # Skip if snapshot not available

            if not all_strikes:
                continue

            # Filter to ATM strikes
            atm_strikes = [
                k for k in all_strikes
                if atm_strike_min <= k <= atm_strike_max
            ]

            if not atm_strikes:
                continue

            # Calculate IV for each ATM strike (calls and puts)
            ivs = []

            for strike in atm_strikes:
                for right in ["C", "P"]:
                    try:
                        # Get option bars
                        bars = self.option_bars_reader.get_bars(
                            underlying=symbol,
                            expiry=expiration,
                            strike=strike,
                            right=right,
                            bar_size="1 day",
                            start_date=timestamp.date(),
                            end_date=timestamp.date(),
                        )

                        if bars.empty:
                            continue

                        # Use mid price
                        mid_price = (bars.iloc[-1]["high"] + bars.iloc[-1]["low"]) / 2.0

                        if mid_price <= 0:
                            continue

                        # Calculate IV from price
                        greeks = self.greeks_calculator.calculate_greeks_from_price(
                            option_price=mid_price,
                            spot=spot_price,
                            strike=strike,
                            dte=dte,
                            option_type=right,
                            risk_free_rate=0.05,
                        )

                        if greeks and greeks.iv > 0:
                            ivs.append(greeks.iv)

                    except Exception:
                        continue

            if not ivs:
                continue

            # Calculate statistics
            results.append({
                'expiration_date': expiration,
                'days_to_expiry': dte,
                'atm_iv': np.mean(ivs),
                'contract_count': len(ivs),
                'iv_std': np.std(ivs) if len(ivs) > 1 else 0.0,
            })

        if not results:
            return pd.DataFrame(columns=[
                'expiration_date', 'days_to_expiry', 'atm_iv',
                'contract_count', 'iv_std'
            ])

        df = pd.DataFrame(results)
        df = df.sort_values('days_to_expiry')
        return df

    def find_max_iv_differential(
        self,
        term_structure: pd.DataFrame,
        front_dte_range: Tuple[int, int],
        back_dte_range: Tuple[int, int],
        min_iv_diff: float = 0.03,
    ) -> Optional[Dict]:
        """
        Find front/back expiration pair with maximum IV differential.

        Searches all valid front/back pairs within DTE ranges and returns
        the pair with the largest IV spread (back_IV - front_IV).

        Args:
            term_structure: IV term structure from get_iv_term_structure()
            front_dte_range: DTE range for front month (min, max)
            back_dte_range: DTE range for back month (min, max)
            min_iv_diff: Minimum IV differential to consider (default: 0.03 = 3%)

        Returns:
            Dict with:
            - front_expiration: Front month expiration date
            - front_dte: Front month days to expiry
            - front_iv: Front month IV
            - back_expiration: Back month expiration date
            - back_dte: Back month days to expiry
            - back_iv: Back month IV
            - iv_diff: Back IV - Front IV
            - iv_diff_pct: IV differential as percentage

            Returns None if no valid pairs found.

        Example:
            >>> best_pair = analyzer.find_max_iv_differential(
            ...     term_structure,
            ...     front_dte_range=(14, 21),
            ...     back_dte_range=(35, 50),
            ...     min_iv_diff=0.03
            ... )
            >>> if best_pair:
            ...     print(f"Best spread: Front IV={best_pair['front_iv']:.2%}, "
            ...           f"Back IV={best_pair['back_iv']:.2%}, "
            ...           f"Diff={best_pair['iv_diff']:.2%}")
        """
        if len(term_structure) < 2:
            return None

        # Filter front month candidates
        front_candidates = term_structure[
            (term_structure['days_to_expiry'] >= front_dte_range[0]) &
            (term_structure['days_to_expiry'] <= front_dte_range[1])
        ]

        # Filter back month candidates
        back_candidates = term_structure[
            (term_structure['days_to_expiry'] >= back_dte_range[0]) &
            (term_structure['days_to_expiry'] <= back_dte_range[1])
        ]

        if front_candidates.empty or back_candidates.empty:
            return None

        # Find pair with maximum IV differential
        best_pair = None
        max_iv_diff = min_iv_diff  # Minimum threshold

        for _, front in front_candidates.iterrows():
            for _, back in back_candidates.iterrows():
                # Ensure back month is after front month
                if back['days_to_expiry'] <= front['days_to_expiry']:
                    continue

                # Calculate IV differential
                iv_diff = back['atm_iv'] - front['atm_iv']

                # Check if exceeds current maximum
                if iv_diff > max_iv_diff:
                    max_iv_diff = iv_diff
                    best_pair = {
                        'front_expiration': front['expiration_date'],
                        'front_dte': front['days_to_expiry'],
                        'front_iv': front['atm_iv'],
                        'front_contract_count': front['contract_count'],
                        'back_expiration': back['expiration_date'],
                        'back_dte': back['days_to_expiry'],
                        'back_iv': back['atm_iv'],
                        'back_contract_count': back['contract_count'],
                        'iv_diff': iv_diff,
                        'iv_diff_pct': iv_diff / front['atm_iv'] if front['atm_iv'] > 0 else 0,
                    }

        return best_pair

    def calculate_iv_rank(
        self,
        symbol: str,
        current_iv: float,
        lookback_days: int = 252,
        timestamp: datetime = None,
        dte_range: Tuple[int, int] = (14, 60),
    ) -> Optional[float]:
        """
        Calculate IV rank: (current - min) / (max - min) * 100

        IV rank measures where current IV stands in historical range.
        - IV rank = 0: Current IV is at historical minimum
        - IV rank = 50: Current IV is in middle of historical range
        - IV rank = 100: Current IV is at historical maximum

        Process:
        1. Get historical equity bars for lookback period
        2. For each bar date with option data:
           a. Find ATM option prices
           b. Calculate implied IV
        3. Compute IV rank: (current - min) / (max - min) * 100

        Args:
            symbol: Underlying symbol
            current_iv: Current implied volatility
            lookback_days: Days of history to analyze (default: 252 = 1 year)
            timestamp: Current timestamp (default: now)
            dte_range: DTE range for ATM options (default: 14-60)

        Returns:
            IV rank (0-100) or None if insufficient history

        Example:
            >>> iv_rank = analyzer.calculate_iv_rank("AEG", 0.45, lookback_days=252)
            >>> if iv_rank:
            ...     if iv_rank < 30:
            ...         print("IV is cheap (low historical rank)")
            ...     elif iv_rank > 70:
            ...         print("IV is expensive (high historical rank)")
        """
        if timestamp is None:
            timestamp = datetime.now()

        # Get historical equity bars
        start_date = timestamp.date() - timedelta(days=lookback_days)
        end_date = timestamp.date()

        try:
            equity_bars = self.equity_reader.get_bars(
                symbol=symbol,
                bar_size="1 day",
                start_date=start_date,
                end_date=end_date,
            )
        except Exception:
            return None

        if equity_bars.empty or len(equity_bars) < 30:
            return None  # Need at least 30 days of history

        # Calculate IV for each day (expensive, simplified approach)
        historical_ivs = []

        # Sample every N days to reduce computation
        sample_freq = max(1, len(equity_bars) // 50)  # Max 50 samples

        for idx in range(0, len(equity_bars), sample_freq):
            bar = equity_bars.iloc[idx]
            bar_date = bar['date']
            spot_price = bar['close']

            try:
                # Get option chain snapshot near this date
                snapshot_reader = OptionChainSnapshotReader(
                    self.data_provider.data_path, "option_chains"
                )

                expirations = snapshot_reader.get_available_expirations(
                    underlying=symbol,
                    as_of=bar_date,
                    min_dte=dte_range[0],
                    max_dte=dte_range[1],
                )

                if not expirations:
                    continue

                # Use first expiration in range
                expiration = expirations[0]
                dte = (expiration - bar_date).days

                # Find ATM strike
                strikes = snapshot_reader.get_strikes_for_expiry(
                    underlying=symbol,
                    as_of=bar_date,
                    expiration=expiration,
                )

                if not strikes:
                    continue

                atm_strike = min(strikes, key=lambda k: abs(k - spot_price))

                # Get option price
                bars = self.option_bars_reader.get_bars(
                    underlying=symbol,
                    expiry=expiration,
                    strike=atm_strike,
                    right="C",  # Use calls
                    bar_size="1 day",
                    start_date=bar_date,
                    end_date=bar_date,
                )

                if bars.empty:
                    continue

                mid_price = (bars.iloc[-1]["high"] + bars.iloc[-1]["low"]) / 2.0

                if mid_price <= 0:
                    continue

                # Calculate IV
                greeks = self.greeks_calculator.calculate_greeks_from_price(
                    option_price=mid_price,
                    spot=spot_price,
                    strike=atm_strike,
                    dte=dte,
                    option_type="C",
                    risk_free_rate=0.05,
                )

                if greeks and greeks.iv > 0:
                    historical_ivs.append(greeks.iv)

            except Exception:
                continue

        if len(historical_ivs) < 10:
            return None  # Need at least 10 data points

        # Calculate IV rank
        min_iv = min(historical_ivs)
        max_iv = max(historical_ivs)

        if max_iv == min_iv:
            return 50.0  # All IVs equal, return middle

        iv_rank = ((current_iv - min_iv) / (max_iv - min_iv)) * 100.0

        return max(0.0, min(100.0, iv_rank))  # Clamp to 0-100

    def get_simplified_iv_history(
        self,
        symbol: str,
        lookback_days: int,
        timestamp: datetime,
    ) -> List[float]:
        """
        Get simplified historical IV values for strategy IV checks.

        This is a faster alternative to calculate_iv_rank() that returns
        raw IV values instead of computing percentile. Strategies can use
        this to implement custom IV filtering logic.

        Note: This method samples historical data to reduce computation time.

        Args:
            symbol: Underlying symbol
            lookback_days: Days of history
            timestamp: Current timestamp

        Returns:
            List of historical IV values (may be empty if data unavailable)
        """
        if timestamp is None:
            timestamp = datetime.now()

        start_date = timestamp.date() - timedelta(days=lookback_days)
        end_date = timestamp.date()

        try:
            equity_bars = self.equity_reader.get_bars(
                symbol=symbol,
                bar_size="1 day",
                start_date=start_date,
                end_date=end_date,
            )
        except Exception:
            return []

        if equity_bars.empty:
            return []

        # Sample every 5th day to reduce computation
        sampled_bars = equity_bars.iloc[::5]

        historical_ivs = []

        for _, bar in sampled_bars.iterrows():
            bar_date = bar['date']
            spot_price = bar['close']

            try:
                snapshot_reader = OptionChainSnapshotReader(
                    self.data_provider.data_path, "option_chains"
                )

                expirations = snapshot_reader.get_available_expirations(
                    underlying=symbol,
                    as_of=bar_date,
                    min_dte=14,
                    max_dte=60,
                )

                if not expirations:
                    continue

                expiration = expirations[0]
                dte = (expiration - bar_date).days

                strikes = snapshot_reader.get_strikes_for_expiry(
                    underlying=symbol,
                    as_of=bar_date,
                    expiration=expiration,
                )

                if not strikes:
                    continue

                atm_strike = min(strikes, key=lambda k: abs(k - spot_price))

                bars = self.option_bars_reader.get_bars(
                    underlying=symbol,
                    expiry=expiration,
                    strike=atm_strike,
                    right="C",
                    bar_size="1 day",
                    start_date=bar_date,
                    end_date=bar_date,
                )

                if bars.empty:
                    continue

                mid_price = (bars.iloc[-1]["high"] + bars.iloc[-1]["low"]) / 2.0

                if mid_price <= 0:
                    continue

                greeks = self.greeks_calculator.calculate_greeks_from_price(
                    option_price=mid_price,
                    spot=spot_price,
                    strike=atm_strike,
                    dte=dte,
                    option_type="C",
                    risk_free_rate=0.05,
                )

                if greeks and greeks.iv > 0:
                    historical_ivs.append(greeks.iv)

            except Exception:
                continue

        return historical_ivs
