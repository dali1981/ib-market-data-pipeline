"""IV ranking and filtering utilities for calendar spread selection.

Provides functions to rank and filter calendar spread candidates based on
IV ratio analysis from backtest results.
"""

from typing import Optional, Literal
import pandas as pd


def assign_iv_quartiles(df: pd.DataFrame) -> pd.DataFrame:
    """
    Assign quartile labels based on iv_ratio_entry.

    Quartiles are labeled Q1 (lowest) to Q4 (highest IV ratios).
    Q4 represents the top 25% of IV ratios, which historically show
    the best performance.

    Args:
        df: DataFrame with 'iv_ratio_entry' column

    Returns:
        DataFrame with added 'iv_ratio_quartile' column

    Example:
        >>> results_df = assign_iv_quartiles(backtest_results)
        >>> top_quartile = results_df[results_df['iv_ratio_quartile'] == 'Q4']
    """
    if df.empty or 'iv_ratio_entry' not in df.columns:
        df['iv_ratio_quartile'] = None
        return df

    df = df.copy()
    df['iv_ratio_quartile'] = pd.qcut(
        df['iv_ratio_entry'],
        q=4,
        labels=['Q1', 'Q2', 'Q3', 'Q4'],
        duplicates='drop'  # Handle case where values are identical
    )

    return df


def rank_and_filter_candidates(
    results_df: pd.DataFrame,
    min_iv_ratio: Optional[float] = None,
    max_entry_cost: Optional[float] = None,
    min_quartile: Optional[Literal['Q1', 'Q2', 'Q3', 'Q4']] = None,
    profitable_only: bool = False,
    top_n: Optional[int] = None,
) -> pd.DataFrame:
    """
    Filter and rank calendar spread candidates by IV metrics.

    Applies various filters and ranks remaining candidates by IV ratio
    in descending order (highest IV ratio = rank 1).

    Args:
        results_df: DataFrame from run_batch_calendar_spread_backtest()
        min_iv_ratio: Minimum IV ratio threshold (e.g., 1.5 for top performers)
        max_entry_cost: Maximum entry cost per contract (e.g., 200)
        min_quartile: Minimum quartile to include (Q1, Q2, Q3, or Q4)
        profitable_only: If True, only include profitable trades
        top_n: Limit to top N candidates

    Returns:
        Filtered and ranked DataFrame with 'rank' column added

    Example:
        >>> # Get top 10 candidates with IV ratio > 1.5
        >>> filtered = rank_and_filter_candidates(
        ...     results_df,
        ...     min_iv_ratio=1.5,
        ...     top_n=10
        ... )
    """
    if results_df.empty:
        return results_df

    df = results_df.copy()

    # Apply filters
    if min_iv_ratio is not None:
        df = df[df['iv_ratio_entry'] >= min_iv_ratio]

    if max_entry_cost is not None and 'entry_cost_per_contract' in df.columns:
        df = df[df['entry_cost_per_contract'] <= max_entry_cost]

    if profitable_only and 'pnl_per_contract' in df.columns:
        df = df[df['pnl_per_contract'] > 0]

    if min_quartile is not None and 'iv_ratio_quartile' in df.columns:
        quartile_order = {'Q1': 1, 'Q2': 2, 'Q3': 3, 'Q4': 4}
        min_value = quartile_order[min_quartile]
        df = df[df['iv_ratio_quartile'].map(quartile_order) >= min_value]

    # Sort by IV ratio descending (highest first)
    df = df.sort_values('iv_ratio_entry', ascending=False)

    # Reset index and add rank column
    df = df.reset_index(drop=True)
    df['rank'] = range(1, len(df) + 1)

    # Limit to top N
    if top_n is not None and top_n > 0:
        df = df.head(top_n)

    return df


def calculate_selection_statistics(df: pd.DataFrame) -> dict:
    """
    Calculate summary statistics for selected candidates.

    Args:
        df: Filtered DataFrame from rank_and_filter_candidates()

    Returns:
        Dictionary with summary statistics

    Example:
        >>> stats = calculate_selection_statistics(filtered_df)
        >>> print(f"Mean IV ratio: {stats['mean_iv_ratio']:.3f}")
    """
    if df.empty:
        return {
            'count': 0,
            'mean_iv_ratio': 0.0,
            'median_iv_ratio': 0.0,
            'mean_entry_cost': 0.0,
            'expected_pnl': 0.0,
            'win_rate': 0.0,
        }

    stats = {
        'count': len(df),
        'mean_iv_ratio': float(df['iv_ratio_entry'].mean()),
        'median_iv_ratio': float(df['iv_ratio_entry'].median()),
    }

    if 'entry_cost_per_contract' in df.columns:
        stats['mean_entry_cost'] = float(df['entry_cost_per_contract'].mean())

    if 'pnl_per_contract' in df.columns:
        stats['expected_pnl'] = float(df['pnl_per_contract'].mean())
        winning_trades = (df['pnl_per_contract'] > 0).sum()
        stats['win_rate'] = float(winning_trades / len(df) * 100) if len(df) > 0 else 0.0

    return stats
