"""
Earnings filtering utilities for strategy backtests.

This module provides functions to filter earnings events to only those
with available option data for trading.
"""

import pandas as pd
from typing import List

from ..repositories import OptionBarsReader


def filter_tradable_earnings(
    earnings_df: pd.DataFrame,
    option_reader: OptionBarsReader,
    symbol_column: str = 'symbol'
) -> pd.DataFrame:
    """
    Filter earnings DataFrame to symbols with available option data.

    Args:
        earnings_df: DataFrame with earnings events (must have symbol column)
        option_reader: OptionBarsReader instance for querying available data
        symbol_column: Name of symbol column in earnings_df (default 'symbol')

    Returns:
        Filtered DataFrame containing only earnings for symbols with option data

    Example:
        >>> from dlt_ibapi.repositories import EarningsCalendarReader, OptionBarsReader
        >>> earnings_reader = EarningsCalendarReader('./data', 'earnings')
        >>> option_reader = OptionBarsReader('./data_delta', 'options')
        >>>
        >>> all_earnings = earnings_reader.get_upcoming_earnings(days_ahead=30)
        >>> tradable = filter_tradable_earnings(all_earnings, option_reader)
        >>> print(f"Tradable: {len(tradable)}/{len(all_earnings)} earnings")
    """
    if earnings_df.empty:
        return earnings_df

    # Get symbols with option data
    symbols_with_options = option_reader.get_available_symbols()

    # Filter earnings to those symbols
    tradable = earnings_df[
        earnings_df[symbol_column].isin(symbols_with_options)
    ].copy()

    return tradable


def get_symbols_with_earnings(
    earnings_df: pd.DataFrame,
    symbol_column: str = 'symbol'
) -> List[str]:
    """
    Get unique list of symbols from earnings DataFrame.

    Args:
        earnings_df: DataFrame with earnings events
        symbol_column: Name of symbol column (default 'symbol')

    Returns:
        Sorted list of unique symbols

    Example:
        >>> symbols = get_symbols_with_earnings(all_earnings)
        >>> print(f"Symbols: {symbols}")
    """
    if earnings_df.empty:
        return []

    return sorted(earnings_df[symbol_column].unique().tolist())
