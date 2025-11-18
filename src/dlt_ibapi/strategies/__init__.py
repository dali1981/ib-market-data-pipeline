"""
Example strategy modules demonstrating data pipeline usage.

This package contains simple example strategies that demonstrate how to:
- Query option chain data
- Analyze historical bars
- Calculate basic metrics
- Build data-driven analysis pipelines

These are educational examples - not production trading strategies.
"""

from .example_analysis import (
    OptionMetrics,
    calculate_option_metrics,
    find_liquid_contracts,
    analyze_volume_patterns,
)

__all__ = [
    # Example analysis functions
    "OptionMetrics",
    "calculate_option_metrics",
    "find_liquid_contracts",
    "analyze_volume_patterns",
]
