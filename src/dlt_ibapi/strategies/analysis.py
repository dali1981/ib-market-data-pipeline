"""
Analysis and visualization utilities for strategy backtests.

This module provides reusable functions for:
- Calculating summary statistics
- Creating visualizations
- Formatting output tables
"""

from typing import Dict, Optional
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.axes


def calculate_strategy_stats(
    results_df: pd.DataFrame,
    pnl_column: str = 'pnl_per_contract'
) -> Dict[str, float]:
    """
    Calculate summary statistics for strategy P&L.

    Args:
        results_df: DataFrame with backtest results
        pnl_column: Column name containing P&L values

    Returns:
        Dictionary with keys: mean, median, std, win_rate, best, worst, count

    Example:
        >>> stats = calculate_strategy_stats(results_df, 'pnl_per_contract')
        >>> print(f"Mean P&L: ${stats['mean']:.2f}")
    """
    if results_df.empty:
        return {
            'count': 0,
            'mean': 0.0,
            'median': 0.0,
            'std': 0.0,
            'win_rate': 0.0,
            'best': 0.0,
            'worst': 0.0,
        }

    pnl = results_df[pnl_column]

    return {
        'count': len(pnl),
        'mean': float(pnl.mean()),
        'median': float(pnl.median()),
        'std': float(pnl.std()),
        'win_rate': float((pnl > 0).mean()),
        'best': float(pnl.max()),
        'worst': float(pnl.min()),
    }


def format_stats_table(
    stats: Dict[str, float],
    title: str = "SUMMARY STATISTICS"
) -> str:
    """
    Format statistics dictionary as pretty-printed table.

    Args:
        stats: Dictionary from calculate_strategy_stats()
        title: Table title (default "SUMMARY STATISTICS")

    Returns:
        Formatted string ready for printing

    Example:
        >>> stats = calculate_strategy_stats(results_df)
        >>> print(format_stats_table(stats))
    """
    lines = [
        "=" * 80,
        title,
        "=" * 80,
        "",
        f"  Count: {stats['count']:.0f} trades",
        f"  Mean P&L: ${stats['mean']:.2f}",
        f"  Median P&L: ${stats['median']:.2f}",
        f"  Std Dev: ${stats['std']:.2f}",
        f"  Win Rate: {stats['win_rate'] * 100:.1f}%",
        f"  Best: ${stats['best']:.2f}",
        f"  Worst: ${stats['worst']:.2f}",
    ]

    return "\n".join(lines)


def create_pnl_distribution_plot(
    results_df: pd.DataFrame,
    pnl_column: str = 'pnl_per_contract',
    title: str = 'P&L Distribution',
    color: str = 'green',
    bins: int = 30,
    ax: Optional[matplotlib.axes.Axes] = None
) -> matplotlib.axes.Axes:
    """
    Create P&L distribution histogram with mean and breakeven lines.

    Args:
        results_df: DataFrame with backtest results
        pnl_column: Column name containing P&L values
        title: Plot title
        color: Histogram color
        bins: Number of bins for histogram
        ax: Existing axes to plot on (optional, creates new if None)

    Returns:
        Matplotlib axes object

    Example:
        >>> fig, ax = plt.subplots(figsize=(10, 6))
        >>> create_pnl_distribution_plot(results_df, ax=ax)
        >>> plt.show()
    """
    if ax is None:
        fig, ax = plt.subplots(figsize=(10, 6))

    if results_df.empty:
        ax.text(0.5, 0.5, 'No data to plot', ha='center', va='center', fontsize=14)
        ax.set_title(title, fontsize=12, fontweight='bold')
        return ax

    pnl = results_df[pnl_column]

    # Histogram
    ax.hist(pnl, bins=bins, alpha=0.7, color=color, edgecolor='black')

    # Breakeven line
    ax.axvline(x=0, color='red', linestyle='--', linewidth=2, label='Breakeven')

    # Mean line
    mean_pnl = pnl.mean()
    ax.axvline(
        x=mean_pnl,
        color='blue',
        linestyle='--',
        linewidth=2,
        label=f'Mean: ${mean_pnl:.2f}'
    )

    ax.set_xlabel('P&L per Contract ($)', fontsize=11, fontweight='bold')
    ax.set_ylabel('Frequency', fontsize=11, fontweight='bold')
    ax.set_title(title, fontsize=12, fontweight='bold')
    ax.legend()
    ax.grid(True, alpha=0.3)

    return ax


def create_by_symbol_summary(
    results_df: pd.DataFrame,
    pnl_column: str = 'pnl_per_contract',
    group_by: str = 'symbol'
) -> pd.DataFrame:
    """
    Create summary table grouped by symbol (or other column).

    Args:
        results_df: DataFrame with backtest results
        pnl_column: Column name containing P&L values
        group_by: Column to group by (default 'symbol')

    Returns:
        DataFrame with aggregated statistics including entry cost and returns

    Example:
        >>> by_symbol = create_by_symbol_summary(results_df)
        >>> print(by_symbol)
    """
    if results_df.empty:
        return pd.DataFrame()

    # Build aggregation dictionary
    agg_dict = {
        pnl_column: ['count', 'mean', 'median', 'std']
    }

    # Add entry cost if available
    if 'entry_cost_per_contract' in results_df.columns:
        agg_dict['entry_cost_per_contract'] = 'mean'

    # Add P&L percentage if available
    if 'pnl_pct' in results_df.columns:
        agg_dict['pnl_pct'] = 'mean'

    summary = results_df.groupby(group_by).agg(agg_dict).round(2)

    # Flatten column names
    new_cols = []
    for col in summary.columns:
        if isinstance(col, tuple):
            if col[1] == 'count':
                new_cols.append('Count')
            elif col[1] == 'mean' and col[0] == pnl_column:
                new_cols.append('Mean P&L')
            elif col[1] == 'median':
                new_cols.append('Median P&L')
            elif col[1] == 'std':
                new_cols.append('Std Dev')
            elif col[1] == 'mean' and col[0] == 'entry_cost_per_contract':
                new_cols.append('Entry Cost')
            elif col[1] == 'mean' and col[0] == 'pnl_pct':
                new_cols.append('Return %')
        else:
            new_cols.append(col)

    summary.columns = new_cols
    summary = summary.sort_values('Mean P&L', ascending=False)

    return summary


def create_strategy_summary_plot(
    results_df: pd.DataFrame,
    pnl_column: str = 'pnl_per_contract',
    group_by: Optional[str] = None,
    figsize: tuple = (14, 6)
) -> plt.Figure:
    """
    Create comprehensive strategy summary with distribution + by-group analysis.

    Args:
        results_df: DataFrame with backtest results
        pnl_column: Column name containing P&L values
        group_by: Optional column to group by (e.g., 'symbol')
        figsize: Figure size (width, height)

    Returns:
        Matplotlib figure object

    Example:
        >>> fig = create_strategy_summary_plot(results_df, group_by='symbol')
        >>> plt.show()
    """
    if group_by and group_by in results_df.columns:
        # Two panels: distribution + by-group
        fig, axes = plt.subplots(1, 2, figsize=figsize)

        # Panel 1: Distribution
        create_pnl_distribution_plot(
            results_df,
            pnl_column=pnl_column,
            title='P&L Distribution (All Trades)',
            ax=axes[0]
        )

        # Panel 2: By-group bar chart
        by_group = create_by_symbol_summary(results_df, pnl_column, group_by)

        if not by_group.empty:
            by_group['Mean P&L'].plot(
                kind='bar',
                ax=axes[1],
                color='steelblue',
                edgecolor='black',
                alpha=0.7
            )
            axes[1].axhline(y=0, color='red', linestyle='--', linewidth=1)
            axes[1].set_xlabel(group_by.title(), fontsize=11, fontweight='bold')
            axes[1].set_ylabel('Mean P&L ($)', fontsize=11, fontweight='bold')
            axes[1].set_title(f'Mean P&L by {group_by.title()}', fontsize=12, fontweight='bold')
            axes[1].grid(True, alpha=0.3, axis='y')
            axes[1].tick_params(axis='x', rotation=45)

        plt.tight_layout()
    else:
        # Single panel: distribution only
        fig, ax = plt.subplots(figsize=(10, 6))
        create_pnl_distribution_plot(
            results_df,
            pnl_column=pnl_column,
            title='P&L Distribution',
            ax=ax
        )
        plt.tight_layout()

    return fig
