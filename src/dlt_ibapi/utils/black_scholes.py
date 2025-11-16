"""
Black-Scholes option pricing and implied volatility calculation.

Simple implementation using scipy for Python 3.13+ compatibility.
"""

import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq
from typing import Literal


def black_scholes_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: Literal['call', 'put'] = 'call'
) -> float:
    """
    Calculate Black-Scholes option price.

    Args:
        S: Spot price
        K: Strike price
        T: Time to expiration in years
        r: Risk-free rate (annualized)
        sigma: Volatility (annualized)
        option_type: 'call' or 'put'

    Returns:
        Theoretical option price

    Example:
        >>> price = black_scholes_price(100, 100, 30/365, 0.05, 0.20, 'call')
        >>> print(f"Call price: ${price:.2f}")
    """
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    if option_type == 'call':
        price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:  # put
        price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

    return price


def implied_volatility(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: Literal['call', 'put'] = 'call'
) -> float:
    """
    Calculate implied volatility using Brent's method.

    Args:
        market_price: Observed market price
        S: Spot price
        K: Strike price
        T: Time to expiration in years
        r: Risk-free rate (annualized)
        option_type: 'call' or 'put'

    Returns:
        Implied volatility (annualized)
        Returns 0.0 if calculation fails

    Example:
        >>> iv = implied_volatility(5.5, 100, 100, 30/365, 0.05, 'call')
        >>> print(f"IV: {iv:.2%}")
    """
    if market_price <= 0 or T <= 0:
        return 0.0

    # Check against intrinsic value
    if option_type == 'call':
        intrinsic = max(0, S - K)
    else:
        intrinsic = max(0, K - S)

    if market_price < intrinsic:
        return 0.0

    def objective(sigma):
        if sigma <= 0:
            return 1e10
        return black_scholes_price(S, K, T, r, sigma, option_type) - market_price

    try:
        # Search for IV between 0.01% and 500%
        iv = brentq(objective, 0.0001, 5.0, xtol=1e-6, maxiter=100)
        return iv
    except Exception:
        return 0.0
