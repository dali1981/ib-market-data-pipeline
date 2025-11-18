"""
Liquidity indicator calculations for option contracts.

This module provides utilities for calculating liquidity metrics that help assess
the tradeability of option contracts. Liquidity indicators include:

- Volume: Total number of contracts traded
- Open Interest: Number of open contracts
- Bid-Ask Spread: Difference between bid and ask prices
- Spread Percentage: Spread as percentage of midpoint
- Volume/OI Ratio: Trading activity relative to open interest
- Liquidity Score: Composite metric combining multiple factors

These metrics help identify options with sufficient liquidity for entering/exiting
positions with minimal slippage.
"""

from dataclasses import dataclass
from typing import Optional, Literal
from datetime import date
import pandas as pd
import numpy as np


@dataclass
class LiquidityMetrics:
    """Liquidity metrics for a single option contract."""

    symbol: str
    expiry: date
    strike: float
    right: Literal['C', 'P']

    # Core liquidity metrics
    avg_volume: float  # Average daily volume
    avg_open_interest: float  # Average open interest
    avg_spread: float  # Average bid-ask spread
    avg_spread_pct: float  # Average spread as % of midpoint
    volume_oi_ratio: float  # Volume / Open Interest ratio

    # Composite score (0-100, higher is better)
    liquidity_score: float

    # Quartile ranking (Q1=worst, Q4=best)
    liquidity_quartile: str

    # Data quality
    days_observed: int  # Number of trading days with data

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'symbol': self.symbol,
            'expiry': self.expiry,
            'strike': self.strike,
            'right': self.right,
            'avg_volume': self.avg_volume,
            'avg_open_interest': self.avg_open_interest,
            'avg_spread': self.avg_spread,
            'avg_spread_pct': self.avg_spread_pct,
            'volume_oi_ratio': self.volume_oi_ratio,
            'liquidity_score': self.liquidity_score,
            'liquidity_quartile': self.liquidity_quartile,
            'days_observed': self.days_observed,
        }


def calculate_liquidity_metrics(
    bars_df: pd.DataFrame,
    min_days: int = 5,
) -> Optional[LiquidityMetrics]:
    """
    Calculate liquidity metrics from option bar data.

    Args:
        bars_df: DataFrame with option bars (must have columns: volume, open_interest, high, low)
        min_days: Minimum number of days required for calculation (default: 5)

    Returns:
        LiquidityMetrics object, or None if insufficient data

    Example:
        >>> from dlt_ibapi.repositories import OptionBarsReader
        >>> reader = OptionBarsReader('./data', 'options')
        >>> bars = reader.get_bars(
        ...     underlying='AAPL',
        ...     expiry=date(2025, 11, 21),
        ...     strike=150.0,
        ...     right='C',
        ...     bar_size='1 day',
        ...     start_date=date(2025, 11, 1),
        ...     end_date=date(2025, 11, 15),
        ... )
        >>> metrics = calculate_liquidity_metrics(bars)
        >>> print(f"Liquidity score: {metrics.liquidity_score:.1f}/100")
    """
    if bars_df.empty or len(bars_df) < min_days:
        return None

    # Ensure required columns exist
    required_cols = ['volume', 'open_interest', 'high', 'low']
    missing_cols = [col for col in required_cols if col not in bars_df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    # Calculate average metrics
    avg_volume = float(bars_df['volume'].mean())
    avg_open_interest = float(bars_df['open_interest'].mean())

    # Calculate spread metrics
    bars_df['spread'] = bars_df['high'] - bars_df['low']
    bars_df['midpoint'] = (bars_df['high'] + bars_df['low']) / 2
    bars_df['spread_pct'] = (bars_df['spread'] / bars_df['midpoint']) * 100

    avg_spread = float(bars_df['spread'].mean())
    avg_spread_pct = float(bars_df['spread_pct'].mean())

    # Calculate volume/OI ratio (trading activity)
    volume_oi_ratio = (avg_volume / avg_open_interest) if avg_open_interest > 0 else 0.0

    # Extract contract details (assume all rows have same contract)
    first_row = bars_df.iloc[0]
    symbol = first_row['underlying']
    expiry = first_row['expiry'] if isinstance(first_row['expiry'], date) else pd.to_datetime(first_row['expiry']).date()
    strike = float(first_row['strike'])
    right = first_row['right']

    days_observed = len(bars_df)

    # Calculate composite liquidity score (0-100, higher is better)
    # This is a weighted combination of normalized metrics
    liquidity_score = _calculate_liquidity_score(
        avg_volume=avg_volume,
        avg_open_interest=avg_open_interest,
        avg_spread_pct=avg_spread_pct,
        volume_oi_ratio=volume_oi_ratio,
    )

    # Assign quartile (will be done later in batch processing)
    liquidity_quartile = 'N/A'

    return LiquidityMetrics(
        symbol=symbol,
        expiry=expiry,
        strike=strike,
        right=right,
        avg_volume=avg_volume,
        avg_open_interest=avg_open_interest,
        avg_spread=avg_spread,
        avg_spread_pct=avg_spread_pct,
        volume_oi_ratio=volume_oi_ratio,
        liquidity_score=liquidity_score,
        liquidity_quartile=liquidity_quartile,
        days_observed=days_observed,
    )


def _calculate_liquidity_score(
    avg_volume: float,
    avg_open_interest: float,
    avg_spread_pct: float,
    volume_oi_ratio: float,
    volume_weight: float = 0.3,
    oi_weight: float = 0.3,
    spread_weight: float = 0.3,
    ratio_weight: float = 0.1,
) -> float:
    """
    Calculate composite liquidity score using normalized metrics.

    Score ranges from 0 (illiquid) to 100 (highly liquid).

    Components:
    - Volume: Higher is better (30% weight)
    - Open Interest: Higher is better (30% weight)
    - Spread %: Lower is better (30% weight, inverted)
    - Volume/OI Ratio: Moderate is best (10% weight)

    Args:
        avg_volume: Average daily volume
        avg_open_interest: Average open interest
        avg_spread_pct: Average spread percentage
        volume_oi_ratio: Volume/OI ratio
        volume_weight: Weight for volume component
        oi_weight: Weight for OI component
        spread_weight: Weight for spread component
        ratio_weight: Weight for ratio component

    Returns:
        Liquidity score (0-100)
    """
    # Normalize volume (log scale, typical range: 1-10000)
    volume_score = min(100, np.log10(max(1, avg_volume)) / np.log10(10000) * 100)

    # Normalize open interest (log scale, typical range: 1-100000)
    oi_score = min(100, np.log10(max(1, avg_open_interest)) / np.log10(100000) * 100)

    # Normalize spread % (inverted - lower is better, typical range: 0.5-20%)
    spread_score = max(0, 100 - (avg_spread_pct / 20 * 100))

    # Normalize volume/OI ratio (optimal range: 0.1-0.5)
    # Too low = stale, too high = speculative
    if volume_oi_ratio < 0.1:
        ratio_score = volume_oi_ratio / 0.1 * 50
    elif volume_oi_ratio <= 0.5:
        ratio_score = 50 + (volume_oi_ratio - 0.1) / 0.4 * 50
    else:
        # Penalty for very high ratios
        ratio_score = max(0, 100 - (volume_oi_ratio - 0.5) * 50)

    # Weighted average
    total_score = (
        volume_score * volume_weight +
        oi_score * oi_weight +
        spread_score * spread_weight +
        ratio_score * ratio_weight
    )

    return round(total_score, 2)


def assign_liquidity_quartiles(metrics_df: pd.DataFrame) -> pd.DataFrame:
    """
    Assign quartile rankings based on liquidity scores.

    Args:
        metrics_df: DataFrame with liquidity_score column

    Returns:
        DataFrame with liquidity_quartile column added (Q1, Q2, Q3, Q4)

    Example:
        >>> metrics_df = pd.DataFrame([...])  # Multiple contracts
        >>> metrics_df = assign_liquidity_quartiles(metrics_df)
        >>> print(metrics_df[['symbol', 'liquidity_score', 'liquidity_quartile']])
    """
    if metrics_df.empty:
        return metrics_df

    # Calculate quartiles
    quartiles = metrics_df['liquidity_score'].quantile([0.25, 0.5, 0.75])

    def get_quartile(score: float) -> str:
        if score <= quartiles[0.25]:
            return 'Q1'  # Lowest liquidity
        elif score <= quartiles[0.5]:
            return 'Q2'
        elif score <= quartiles[0.75]:
            return 'Q3'
        else:
            return 'Q4'  # Highest liquidity

    metrics_df['liquidity_quartile'] = metrics_df['liquidity_score'].apply(get_quartile)

    return metrics_df


def filter_by_liquidity(
    metrics_df: pd.DataFrame,
    min_score: Optional[float] = None,
    min_quartile: Optional[Literal['Q1', 'Q2', 'Q3', 'Q4']] = None,
    min_volume: Optional[float] = None,
    min_open_interest: Optional[float] = None,
    max_spread_pct: Optional[float] = None,
) -> pd.DataFrame:
    """
    Filter option contracts by liquidity criteria.

    Args:
        metrics_df: DataFrame with liquidity metrics
        min_score: Minimum liquidity score (0-100)
        min_quartile: Minimum quartile ('Q1', 'Q2', 'Q3', 'Q4')
        min_volume: Minimum average volume
        min_open_interest: Minimum average open interest
        max_spread_pct: Maximum spread percentage

    Returns:
        Filtered DataFrame

    Example:
        >>> # Get only highly liquid options
        >>> liquid_options = filter_by_liquidity(
        ...     metrics_df,
        ...     min_score=70,
        ...     min_quartile='Q4',
        ...     min_volume=100,
        ...     max_spread_pct=5.0,
        ... )
    """
    filtered = metrics_df.copy()

    if min_score is not None:
        filtered = filtered[filtered['liquidity_score'] >= min_score]

    if min_quartile is not None:
        quartile_order = {'Q1': 1, 'Q2': 2, 'Q3': 3, 'Q4': 4}
        min_q_value = quartile_order[min_quartile]
        filtered = filtered[
            filtered['liquidity_quartile'].map(quartile_order) >= min_q_value
        ]

    if min_volume is not None:
        filtered = filtered[filtered['avg_volume'] >= min_volume]

    if min_open_interest is not None:
        filtered = filtered[filtered['avg_open_interest'] >= min_open_interest]

    if max_spread_pct is not None:
        filtered = filtered[filtered['avg_spread_pct'] <= max_spread_pct]

    return filtered


def calculate_batch_liquidity(
    option_bars_reader,
    contracts: pd.DataFrame,
    bar_size: str = '1 day',
    lookback_days: int = 20,
    min_days: int = 5,
) -> pd.DataFrame:
    """
    Calculate liquidity metrics for multiple option contracts.

    Args:
        option_bars_reader: OptionBarsReader instance
        contracts: DataFrame with columns: underlying, expiry, strike, right
        bar_size: Bar size for data ('1 day', '5 mins', etc.)
        lookback_days: Number of days to look back for data
        min_days: Minimum days required for calculation

    Returns:
        DataFrame with liquidity metrics for each contract

    Example:
        >>> from dlt_ibapi.repositories import OptionBarsReader
        >>> reader = OptionBarsReader('./data', 'options')
        >>> contracts = pd.DataFrame([
        ...     {'underlying': 'AAPL', 'expiry': date(2025, 11, 21), 'strike': 150.0, 'right': 'C'},
        ...     {'underlying': 'AAPL', 'expiry': date(2025, 11, 21), 'strike': 155.0, 'right': 'C'},
        ... ])
        >>> liquidity_df = calculate_batch_liquidity(reader, contracts)
        >>> print(liquidity_df[['symbol', 'strike', 'liquidity_score', 'liquidity_quartile']])
    """
    from datetime import datetime, timedelta

    metrics_list = []

    for _, contract in contracts.iterrows():
        try:
            # Calculate date range
            end_date = datetime.now().date()
            start_date = end_date - timedelta(days=lookback_days)

            # Get bars for contract
            bars = option_bars_reader.get_bars(
                underlying=contract['underlying'],
                expiry=contract['expiry'],
                strike=contract['strike'],
                right=contract['right'],
                bar_size=bar_size,
                start_date=start_date,
                end_date=end_date,
            )

            # Calculate metrics
            metrics = calculate_liquidity_metrics(bars, min_days=min_days)

            if metrics:
                metrics_list.append(metrics.to_dict())

        except Exception as e:
            # Log error but continue processing
            print(f"Error calculating liquidity for {contract['underlying']} "
                  f"{contract['strike']}{contract['right']}: {e}")
            continue

    if not metrics_list:
        return pd.DataFrame()

    # Convert to DataFrame
    metrics_df = pd.DataFrame(metrics_list)

    # Assign quartiles
    metrics_df = assign_liquidity_quartiles(metrics_df)

    return metrics_df