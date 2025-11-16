"""
Reader for option tick-by-tick data.

Provides query API for historical tick data stored in Parquet files.
"""

import pandas as pd
from datetime import datetime, date
from typing import Literal, Optional

from .parquet_reader import ParquetReaderBase


class OptionTicksReader(ParquetReaderBase):
    """
    Reader for querying option tick data from Parquet files.

    Supports both bid/ask ticks and trade ticks with efficient queries
    using Hive partitioning (date/symbol).
    """

    def __init__(self, database_path: str, dataset_name: str = "option_ticks"):
        """
        Initialize OptionTicksReader.

        Args:
            database_path: Path to data directory (e.g., "./data")
            dataset_name: Dataset name (default: "option_ticks")
        """
        super().__init__(database_path, dataset_name)

    def get_ticks(
        self,
        underlying: str,
        expiry: date,
        strike: float,
        right: Literal['C', 'P'],
        start_datetime: datetime,
        end_datetime: datetime,
        tick_type: Literal['bid_ask', 'trades'] = 'bid_ask'
    ) -> pd.DataFrame:
        """
        Get tick data for specific option contract and time window.

        Args:
            underlying: Underlying symbol
            expiry: Option expiration
            strike: Strike price
            right: 'C' or 'P'
            start_datetime: Start time
            end_datetime: End time
            tick_type: 'bid_ask' or 'trades'

        Returns:
            DataFrame with tick data, sorted by tick_time

        Example:
            >>> reader = OptionTicksReader('./data', 'option_ticks')
            >>> ticks = reader.get_ticks(
            ...     underlying='AAPL',
            ...     expiry=date(2025, 11, 21),
            ...     strike=150.0,
            ...     right='C',
            ...     start_datetime=datetime(2025, 11, 12, 15, 50),
            ...     end_datetime=datetime(2025, 11, 12, 16, 0),
            ...     tick_type='bid_ask'
            ... )
            >>> print(f"Got {len(ticks)} ticks")
        """
        table_name = f"option_ticks_{tick_type}"

        query = f"""
            SELECT *
            FROM parquet_scan('{self.data_path}/{table_name}/**/*.parquet',
                            hive_partitioning=true)
            WHERE underlying = '{underlying}'
              AND expiry = '{expiry.isoformat()}'
              AND strike = {strike}
              AND "right" = '{right.upper()}'
              AND tick_time >= '{start_datetime.isoformat()}'
              AND tick_time <= '{end_datetime.isoformat()}'
            ORDER BY tick_time
        """

        return self._execute_query(query)

    def get_spread_at_time(
        self,
        underlying: str,
        expiry: date,
        strike: float,
        right: Literal['C', 'P'],
        target_time: datetime,
        window_seconds: int = 5
    ) -> Optional[float]:
        """
        Get bid/ask spread at specific time (±window).

        Returns average spread within window, or None if no ticks.

        Args:
            underlying: Underlying symbol
            expiry: Option expiration
            strike: Strike price
            right: 'C' or 'P'
            target_time: Target datetime
            window_seconds: Window size in seconds (default: 5)

        Returns:
            Average spread within window, or None if no data

        Example:
            >>> reader = OptionTicksReader('./data')
            >>> spread = reader.get_spread_at_time(
            ...     underlying='AAPL',
            ...     expiry=date(2025, 11, 21),
            ...     strike=150.0,
            ...     right='C',
            ...     target_time=datetime(2025, 11, 12, 15, 55),
            ...     window_seconds=30
            ... )
            >>> if spread:
            ...     print(f"Spread at 3:55pm: ${spread:.4f}")
        """
        start = target_time - pd.Timedelta(seconds=window_seconds)
        end = target_time + pd.Timedelta(seconds=window_seconds)

        ticks = self.get_ticks(
            underlying=underlying,
            expiry=expiry,
            strike=strike,
            right=right,
            start_datetime=start,
            end_datetime=end,
            tick_type='bid_ask'
        )

        if ticks.empty:
            return None

        return ticks['spread'].mean()

    def get_volume_window(
        self,
        underlying: str,
        expiry: date,
        strike: float,
        right: Literal['C', 'P'],
        start_datetime: datetime,
        end_datetime: datetime
    ) -> int:
        """
        Get total trade volume in time window.

        Args:
            underlying: Underlying symbol
            expiry: Option expiration
            strike: Strike price
            right: 'C' or 'P'
            start_datetime: Window start
            end_datetime: Window end

        Returns:
            Sum of trade sizes (number of contracts traded)

        Example:
            >>> reader = OptionTicksReader('./data')
            >>> volume = reader.get_volume_window(
            ...     underlying='AAPL',
            ...     expiry=date(2025, 11, 21),
            ...     strike=150.0,
            ...     right='C',
            ...     start_datetime=datetime(2025, 11, 12, 15, 50),
            ...     end_datetime=datetime(2025, 11, 12, 16, 0)
            ... )
            >>> print(f"Volume in window: {volume} contracts")
        """
        ticks = self.get_ticks(
            underlying=underlying,
            expiry=expiry,
            strike=strike,
            right=right,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            tick_type='trades'
        )

        if ticks.empty:
            return 0

        return int(ticks['size'].sum())

    def get_tick_stats(
        self,
        underlying: str,
        expiry: date,
        strike: float,
        right: Literal['C', 'P'],
        start_datetime: datetime,
        end_datetime: datetime
    ) -> dict:
        """
        Get comprehensive tick statistics for time window.

        Args:
            underlying: Underlying symbol
            expiry: Option expiration
            strike: Strike price
            right: 'C' or 'P'
            start_datetime: Window start
            end_datetime: Window end

        Returns:
            Dictionary with tick statistics including:
            - tick_count: Number of ticks
            - avg_spread: Average spread
            - min_spread: Minimum spread
            - max_spread: Maximum spread
            - avg_spread_pct: Average spread percentage
            - total_volume: Total trade volume

        Example:
            >>> reader = OptionTicksReader('./data')
            >>> stats = reader.get_tick_stats(
            ...     underlying='AAPL',
            ...     expiry=date(2025, 11, 21),
            ...     strike=150.0,
            ...     right='C',
            ...     start_datetime=datetime(2025, 11, 12, 15, 50),
            ...     end_datetime=datetime(2025, 11, 12, 16, 0)
            ... )
            >>> print(f"Avg spread: ${stats['avg_spread']:.4f}")
        """
        bid_ask_ticks = self.get_ticks(
            underlying=underlying,
            expiry=expiry,
            strike=strike,
            right=right,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            tick_type='bid_ask'
        )

        trade_ticks = self.get_ticks(
            underlying=underlying,
            expiry=expiry,
            strike=strike,
            right=right,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            tick_type='trades'
        )

        stats = {
            'tick_count': len(bid_ask_ticks),
            'avg_spread': bid_ask_ticks['spread'].mean() if not bid_ask_ticks.empty else None,
            'min_spread': bid_ask_ticks['spread'].min() if not bid_ask_ticks.empty else None,
            'max_spread': bid_ask_ticks['spread'].max() if not bid_ask_ticks.empty else None,
            'avg_spread_pct': bid_ask_ticks['spread_pct'].mean() if not bid_ask_ticks.empty else None,
            'total_volume': int(trade_ticks['size'].sum()) if not trade_ticks.empty else 0,
            'trade_count': len(trade_ticks)
        }

        return stats

    def get_available_contracts(self, tick_type: Literal['bid_ask', 'trades'] = 'bid_ask') -> pd.DataFrame:
        """
        Get list of available option contracts with tick data.

        Args:
            tick_type: Type of ticks to query

        Returns:
            DataFrame with unique (underlying, expiry, strike, right) combinations

        Example:
            >>> reader = OptionTicksReader('./data')
            >>> contracts = reader.get_available_contracts()
            >>> print(contracts[['underlying', 'expiry', 'strike', 'right']])
        """
        table_name = f"option_ticks_{tick_type}"

        query = f"""
            SELECT DISTINCT
                underlying,
                expiry,
                strike,
                "right"
            FROM parquet_scan('{self.data_path}/{table_name}/**/*.parquet',
                            hive_partitioning=true)
            ORDER BY underlying, expiry, strike, "right"
        """

        return self._execute_query(query)
