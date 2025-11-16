"""
Strike selection utilities for options strategies.

This module provides functions for selecting option strikes based on
underlying spot price, typically for ATM (at-the-money) strategies.
"""

from typing import Literal


def select_atm_strike(
    spot_price: float,
    rounding_strategy: Literal['half', 'whole', 'five', 'auto'] = 'auto'
) -> float:
    """
    Round spot price to nearest ATM strike.

    Different stocks have different strike increments based on price:
    - Low-priced (< $20): Typically $0.50 or $1.00 increments
    - Mid-priced ($20-$100): Typically $1.00 increments
    - High-priced (> $100): Typically $5.00 increments

    Args:
        spot_price: Current stock price
        rounding_strategy:
            - 'half': Round to nearest $0.50 (low-priced stocks)
            - 'whole': Round to nearest $1 (mid-priced stocks)
            - 'five': Round to nearest $5 (high-priced stocks)
            - 'auto': Auto-select based on spot_price (default)

    Returns:
        ATM strike price

    Examples:
        >>> select_atm_strike(5.17, 'auto')  # Low price
        5.0
        >>> select_atm_strike(52.37, 'auto')  # Mid price
        52.0
        >>> select_atm_strike(225.67, 'auto')  # High price
        225.0
        >>> select_atm_strike(5.37, 'half')  # Force $0.50 increments
        5.5
    """
    if rounding_strategy == 'auto':
        # Auto-select based on price
        if spot_price < 20:
            rounding_strategy = 'whole'  # $1 increments for low prices
        elif spot_price < 100:
            rounding_strategy = 'whole'  # $1 increments for mid prices
        else:
            rounding_strategy = 'five'   # $5 increments for high prices

    if rounding_strategy == 'half':
        # Round to nearest $0.50
        return round(spot_price * 2) / 2
    elif rounding_strategy == 'whole':
        # Round to nearest $1
        return round(spot_price)
    elif rounding_strategy == 'five':
        # Round to nearest $5
        return round(spot_price / 5) * 5
    else:
        raise ValueError(f"Unknown rounding_strategy: {rounding_strategy}")
