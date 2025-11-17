"""
Strategy modules for options trading.

This package contains reusable strategy components for backtesting
and live trading, including:
- Calendar spreads
- Strike selection
- Entry/exit timing
- Batch backtest runners
- Analysis and visualization
"""

from .calendar_spread import (
    CalendarSpreadPosition,
    CalendarSpreadResult,
    select_calendar_expirations,
    calculate_entry_exit_times,
    get_option_price_at_time,
    backtest_single_calendar_spread,
)
from .strike_selection import select_atm_strike
from .analysis import (
    calculate_strategy_stats,
    format_stats_table,
    create_pnl_distribution_plot,
    create_by_symbol_summary,
    create_strategy_summary_plot,
)
from .earnings_filter import (
    filter_tradable_earnings,
    get_symbols_with_earnings,
)
from .batch import run_batch_calendar_spread_backtest
from .iv_ranking import (
    assign_iv_quartiles,
    rank_and_filter_candidates,
    calculate_selection_statistics,
)
from .display import (
    create_iv_rank_table,
    create_selection_stats_table,
    create_earnings_time_warning,
)

__all__ = [
    # Calendar spread core
    "CalendarSpreadPosition",
    "CalendarSpreadResult",
    "select_calendar_expirations",
    "calculate_entry_exit_times",
    "get_option_price_at_time",
    "backtest_single_calendar_spread",
    # Strike selection
    "select_atm_strike",
    # Analysis and visualization
    "calculate_strategy_stats",
    "format_stats_table",
    "create_pnl_distribution_plot",
    "create_by_symbol_summary",
    "create_strategy_summary_plot",
    # Earnings filtering
    "filter_tradable_earnings",
    "get_symbols_with_earnings",
    # Batch backtesting
    "run_batch_calendar_spread_backtest",
    # IV ranking and selection
    "assign_iv_quartiles",
    "rank_and_filter_candidates",
    "calculate_selection_statistics",
    # Display utilities
    "create_iv_rank_table",
    "create_selection_stats_table",
    "create_earnings_time_warning",
]
