"""
Example strategy analysis demonstrating data pipeline usage.

This module shows how to use dlt-ibapi's data readers to:
- Query option chain snapshots
- Analyze historical bar data
- Calculate basic metrics
- Filter contracts by liquidity

These are educational examples - not production trading strategies.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional
import pandas as pd

from ..repositories import OptionBarsReader, OptionChainSnapshotReader


@dataclass
class OptionMetrics:
    """
    Simple metrics for an option contract.

    Attributes:
        symbol: Underlying symbol
        expiry: Option expiration date
        strike: Strike price
        right: 'C' for call, 'P' for put
        avg_volume: Average daily volume
        avg_spread: Average bid-ask spread (%)
        price_range: Price volatility (high - low)
    """
    symbol: str
    expiry: date
    strike: float
    right: str
    avg_volume: float
    avg_spread: float
    price_range: float


def calculate_option_metrics(
    database_path: str,
    underlying: str,
    expiry: date,
    strike: float,
    right: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    bar_size: str = "5 mins",
) -> Optional[OptionMetrics]:
    """
    Calculate basic metrics for an option contract.

    Example usage demonstrating data reader pattern:

    ```python
    metrics = calculate_option_metrics(
        database_path="./data",
        underlying="AAPL",
        expiry=date(2025, 12, 20),
        strike=180.0,
        right="C",
        start_date=date(2025, 11, 1),
        end_date=date(2025, 11, 15),
    )

    if metrics:
        print(f"Average volume: {metrics.avg_volume}")
        print(f"Average spread: {metrics.avg_spread:.2%}")
    ```

    Args:
        database_path: Path to data directory (e.g., "./data")
        underlying: Underlying symbol (e.g., "AAPL")
        expiry: Option expiration date
        strike: Strike price
        right: "C" for call, "P" for put
        start_date: Start date for analysis (default: 30 days ago)
        end_date: End date for analysis (default: today)
        bar_size: Bar size to query (default: "5 mins")

    Returns:
        OptionMetrics object with calculated metrics, or None if no data found
    """
    # Initialize reader
    reader = OptionBarsReader(database_path=database_path, dataset_name="options")

    # Default date range: last 30 days
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=30)

    # Query bars for this contract
    bars_df = reader.get_bars(
        underlying=underlying,
        expiry=expiry,
        strike=strike,
        right=right,
        bar_size=bar_size,
        start_date=start_date,
        end_date=end_date,
    )

    # Return None if no data
    if bars_df.empty:
        return None

    # Calculate metrics
    avg_volume = bars_df["volume"].mean()

    # Calculate average spread (as percentage of mid-price)
    bars_df["mid_price"] = (bars_df["high"] + bars_df["low"]) / 2
    bars_df["spread_pct"] = (bars_df["high"] - bars_df["low"]) / bars_df["mid_price"]
    avg_spread = bars_df["spread_pct"].mean()

    # Calculate price range (total volatility)
    price_range = bars_df["high"].max() - bars_df["low"].min()

    return OptionMetrics(
        symbol=underlying,
        expiry=expiry,
        strike=strike,
        right=right,
        avg_volume=avg_volume,
        avg_spread=avg_spread,
        price_range=price_range,
    )


def find_liquid_contracts(
    database_path: str,
    underlying: str,
    as_of: date,
    min_volume: float = 100.0,
    max_spread_pct: float = 0.05,
    min_dte: int = 7,
    max_dte: int = 60,
) -> pd.DataFrame:
    """
    Find liquid option contracts based on volume and spread criteria.

    Example usage demonstrating option chain queries:

    ```python
    liquid_options = find_liquid_contracts(
        database_path="./data",
        underlying="AAPL",
        as_of=date(2025, 11, 15),
        min_volume=100,
        max_spread_pct=0.05,  # 5% max spread
        min_dte=7,
        max_dte=60,
    )

    print(f"Found {len(liquid_options)} liquid contracts")
    print(liquid_options[['strike', 'right', 'expiry', 'dte']])
    ```

    Args:
        database_path: Path to data directory
        underlying: Underlying symbol
        as_of: Date for snapshot query
        min_volume: Minimum average daily volume
        max_spread_pct: Maximum bid-ask spread as % of mid-price
        min_dte: Minimum days to expiration
        max_dte: Maximum days to expiration

    Returns:
        DataFrame with liquid contracts and their metrics
    """
    # Initialize readers
    chain_reader = OptionChainSnapshotReader(
        database_path=database_path, dataset_name="option_chains"
    )
    bars_reader = OptionBarsReader(database_path=database_path, dataset_name="options")

    # Get option chain snapshot
    chain_df = chain_reader.get_snapshot(
        underlying=underlying,
        as_of=as_of,
    )

    if chain_df.empty:
        return pd.DataFrame()

    # Filter by DTE
    chain_df["dte"] = (pd.to_datetime(chain_df["expiry"]) - pd.to_datetime(as_of)).dt.days
    chain_df = chain_df[
        (chain_df["dte"] >= min_dte) & (chain_df["dte"] <= max_dte)
    ]

    # Calculate metrics for each contract
    results = []
    for _, contract in chain_df.iterrows():
        metrics = calculate_option_metrics(
            database_path=database_path,
            underlying=underlying,
            expiry=contract["expiry"],
            strike=contract["strike"],
            right=contract["right"],
            end_date=as_of,
            bar_size="5 mins",
        )

        if metrics is None:
            continue

        # Apply liquidity filters
        if metrics.avg_volume >= min_volume and metrics.avg_spread <= max_spread_pct:
            results.append({
                "strike": contract["strike"],
                "right": contract["right"],
                "expiry": contract["expiry"],
                "dte": contract["dte"],
                "avg_volume": metrics.avg_volume,
                "avg_spread_pct": metrics.avg_spread,
            })

    return pd.DataFrame(results)


def analyze_volume_patterns(
    database_path: str,
    underlying: str,
    expiry: date,
    strike: float,
    right: str,
    start_date: date,
    end_date: date,
    bar_size: str = "5 mins",
) -> pd.DataFrame:
    """
    Analyze intraday volume patterns for an option contract.

    Example usage demonstrating time-series analysis:

    ```python
    volume_analysis = analyze_volume_patterns(
        database_path="./data",
        underlying="AAPL",
        expiry=date(2025, 12, 20),
        strike=180.0,
        right="C",
        start_date=date(2025, 11, 1),
        end_date=date(2025, 11, 15),
    )

    # Group by time of day
    hourly = volume_analysis.groupby("hour")["volume"].mean()
    print("Average volume by hour:")
    print(hourly)
    ```

    Args:
        database_path: Path to data directory
        underlying: Underlying symbol
        expiry: Option expiration date
        strike: Strike price
        right: "C" for call, "P" for put
        start_date: Start date for analysis
        end_date: End date for analysis
        bar_size: Bar size to query (default: "5 mins")

    Returns:
        DataFrame with volume analysis by time period
    """
    # Initialize reader
    reader = OptionBarsReader(database_path=database_path, dataset_name="options")

    # Query bars
    bars_df = reader.get_bars(
        underlying=underlying,
        expiry=expiry,
        strike=strike,
        right=right,
        bar_size=bar_size,
        start_date=start_date,
        end_date=end_date,
    )

    if bars_df.empty:
        return pd.DataFrame()

    # Extract time components
    bars_df["time_dt"] = pd.to_datetime(bars_df["time"])
    bars_df["hour"] = bars_df["time_dt"].dt.hour
    bars_df["minute"] = bars_df["time_dt"].dt.minute
    bars_df["date"] = bars_df["time_dt"].dt.date

    # Calculate daily statistics
    daily_stats = bars_df.groupby("date").agg({
        "volume": ["sum", "mean", "max"],
        "close": ["first", "last"],
    })

    daily_stats.columns = ["_".join(col) for col in daily_stats.columns]

    return daily_stats
