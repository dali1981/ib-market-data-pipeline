"""
Three delta-based option selection strategies for comparison.

Implements:
1. Closest Match: Find existing strikes closest to target deltas (±0.25, ±0.50, ATM)
2. Black-Scholes Calculated: Calculate deltas using Black-Scholes model
3. IB API Greeks: Use IB's calculated greeks to select by delta
"""

from datetime import date
from typing import List, Dict, Tuple, Optional, Any
import logging
import math

import pandas as pd
from scipy.stats import norm

from ib_connector import IBRuntime, make_option
from dlt_ibapi.resolution.contract_cache import ContractCache
from dlt_ibapi.resolution.resolver import ContractResolver
from dagster_options.config import DeltaSelectionConfig

logger = logging.getLogger(__name__)


# ============================================================================
# Strategy 1: Closest Match to Target Deltas
# ============================================================================


def select_by_closest_match(
    strikes: List[float],
    spot_price: float,
    target_deltas: List[float],
    option_type: str = "C",
) -> List[Tuple[float, str]]:
    """
    Select strikes closest to target delta values using simple heuristics.

    For calls, delta ≈ strikes closer to spot
    For puts, delta ≈ strikes further from spot

    This is a simple approximation that doesn't require calculations.

    Args:
        strikes: Available strike prices
        spot_price: Current underlying price
        target_deltas: Target delta values (e.g., [0.25, 0.50, 0.75])
        option_type: "C" for calls, "P" for puts

    Returns:
        List of (strike, reason) tuples
    """
    if not strikes:
        return []

    strikes_sorted = sorted(strikes)
    selected = []

    # ATM strike (delta ~0.50 for calls, ~-0.50 for puts)
    atm_strike = min(strikes, key=lambda s: abs(s - spot_price))

    for delta_target in target_deltas:
        if option_type == "C":
            # For calls: higher delta = lower strike (deeper ITM)
            # 0.75 delta ≈ 25% below spot
            # 0.50 delta ≈ ATM
            # 0.25 delta ≈ 25% above spot
            target_strike = spot_price * (1 - (delta_target - 0.50) * 0.5)
        else:  # Put
            # For puts: higher absolute delta = higher strike (deeper ITM)
            # -0.75 delta ≈ 25% above spot
            # -0.50 delta ≈ ATM
            # -0.25 delta ≈ 25% below spot
            abs_delta = abs(delta_target)
            target_strike = spot_price * (1 + (abs_delta - 0.50) * 0.5)

        # Find closest strike
        closest = min(strikes_sorted, key=lambda s: abs(s - target_strike))
        reason = f"closest_match_delta_{abs(delta_target):.2f}"
        selected.append((closest, reason))

    return selected


# ============================================================================
# Strategy 2: Black-Scholes Calculated Delta
# ============================================================================


def black_scholes_call_delta(
    spot: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    volatility: float,
) -> float:
    """
    Calculate call option delta using Black-Scholes.

    Args:
        spot: Current spot price
        strike: Strike price
        time_to_expiry: Time to expiration in years
        risk_free_rate: Risk-free interest rate (annualized)
        volatility: Implied volatility (annualized)

    Returns:
        Call delta (0 to 1)
    """
    if time_to_expiry <= 0:
        return 1.0 if spot > strike else 0.0

    d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * volatility ** 2) * time_to_expiry) / (
        volatility * math.sqrt(time_to_expiry)
    )

    return norm.cdf(d1)


def black_scholes_put_delta(
    spot: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    volatility: float,
) -> float:
    """
    Calculate put option delta using Black-Scholes.

    Put delta = Call delta - 1 (ranges from -1 to 0)
    """
    call_delta = black_scholes_call_delta(spot, strike, time_to_expiry, risk_free_rate, volatility)
    return call_delta - 1.0


def select_by_black_scholes(
    strikes: List[float],
    spot_price: float,
    expiry: date,
    as_of: date,
    target_deltas: List[float],
    option_type: str = "C",
    risk_free_rate: float = 0.05,
    volatility: float = 0.30,
    tolerance: float = 0.05,
) -> List[Tuple[float, str, float]]:
    """
    Select strikes by calculating deltas using Black-Scholes model.

    Args:
        strikes: Available strike prices
        spot_price: Current spot price
        expiry: Option expiration date
        as_of: Current date
        target_deltas: Target delta values
        option_type: "C" for calls, "P" for puts
        risk_free_rate: Risk-free rate (default 5%)
        volatility: IV estimate (default 30%)
        tolerance: Delta matching tolerance

    Returns:
        List of (strike, reason, actual_delta) tuples
    """
    if not strikes:
        return []

    # Calculate time to expiry
    days_to_expiry = (expiry - as_of).days
    if days_to_expiry <= 0:
        return []

    time_to_expiry = days_to_expiry / 365.0

    # Calculate delta for each strike
    strike_deltas = []
    for strike in strikes:
        if option_type == "C":
            delta = black_scholes_call_delta(
                spot_price, strike, time_to_expiry, risk_free_rate, volatility
            )
        else:  # Put
            delta = black_scholes_put_delta(
                spot_price, strike, time_to_expiry, risk_free_rate, volatility
            )

        strike_deltas.append((strike, delta))

    # Select strikes closest to target deltas
    selected = []

    for target in target_deltas:
        # Find strikes within tolerance
        candidates = [
            (strike, delta) for strike, delta in strike_deltas
            if abs(delta - target) <= tolerance
        ]

        if candidates:
            # Pick closest to target
            best_strike, best_delta = min(candidates, key=lambda x: abs(x[1] - target))
            reason = f"black_scholes_delta_{abs(target):.2f}"
            selected.append((best_strike, reason, best_delta))
        else:
            logger.warning(
                f"No strikes within tolerance for {option_type} delta={target} "
                f"(expiry={expiry}, spot={spot_price})"
            )

    return selected


# ============================================================================
# Strategy 3: IB API Greeks
# ============================================================================


def select_by_ib_greeks(
    runtime: IBRuntime,
    underlying_symbol: str,
    underlying_conid: int,
    strikes: List[float],
    expiry: date,
    target_deltas: List[float],
    option_type: str = "C",
    exchange: str = "SMART",
    tolerance: float = 0.05,
    timeout: float = 30.0,
) -> List[Tuple[float, str, float]]:
    """
    Select strikes using IB's calculated greeks.

    NOTE: This strategy is NOT IMPLEMENTED because:
    - Requires live market data subscription (not snapshot)
    - ib_connector only has SubscriptionService for streaming data
    - Would need significant additional implementation
    - Market data subscriptions are complex and require proper cleanup

    This is a placeholder for future implementation.

    Args:
        runtime: IB runtime connection
        underlying_symbol: Underlying symbol
        underlying_conid: Underlying contract ID
        strikes: Available strike prices
        expiry: Option expiration date
        target_deltas: Target delta values
        option_type: "C" for calls, "P" for puts
        exchange: Exchange (default "SMART")
        tolerance: Delta matching tolerance
        timeout: Timeout for market data requests

    Returns:
        Empty list (not implemented)
    """
    logger.warning(
        "IB Greeks strategy is not implemented. "
        "Use 'closest_match' or 'black_scholes' instead."
    )
    return []


# ============================================================================
# Unified Selection Interface
# ============================================================================


def select_option_contracts(
    strikes: List[float],
    spot_price: float,
    expiry: date,
    as_of: date,
    config: DeltaSelectionConfig,
    strategy: str,
    runtime: Optional[IBRuntime] = None,
    underlying_symbol: Optional[str] = None,
    underlying_conid: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Select option contracts using specified strategy.

    Args:
        strikes: Available strike prices
        spot_price: Current spot price
        expiry: Option expiration date
        as_of: Current date
        config: Delta selection configuration
        strategy: "closest_match", "black_scholes", or "ib_greeks"
        runtime: IB runtime (required for ib_greeks)
        underlying_symbol: Underlying symbol (required for ib_greeks)
        underlying_conid: Underlying conid (required for ib_greeks)

    Returns:
        List of contract dictionaries with keys:
        - strike: Strike price
        - right: "C" or "P"
        - strategy: Selection strategy name
        - reason: Selection reason
        - delta: Calculated/actual delta (if available)
    """
    contracts = []

    # Process calls
    if config.include_calls:
        if strategy == "closest_match":
            call_strikes = select_by_closest_match(
                strikes, spot_price, config.target_deltas, "C"
            )
            for strike, reason in call_strikes:
                contracts.append({
                    "strike": strike,
                    "right": "C",
                    "strategy": strategy,
                    "reason": reason,
                    "delta": None,
                })

        elif strategy == "black_scholes":
            call_strikes = select_by_black_scholes(
                strikes, spot_price, expiry, as_of,
                config.target_deltas, "C",
                config.risk_free_rate, config.implied_volatility,
                config.delta_tolerance,
            )
            for strike, reason, delta in call_strikes:
                contracts.append({
                    "strike": strike,
                    "right": "C",
                    "strategy": strategy,
                    "reason": reason,
                    "delta": delta,
                })

        elif strategy == "ib_greeks":
            if not runtime or not underlying_symbol or not underlying_conid:
                raise ValueError("runtime, underlying_symbol, and underlying_conid required for ib_greeks")

            call_strikes = select_by_ib_greeks(
                runtime, underlying_symbol, underlying_conid,
                strikes, expiry, config.target_deltas, "C",
                tolerance=config.delta_tolerance,
            )
            for strike, reason, delta in call_strikes:
                contracts.append({
                    "strike": strike,
                    "right": "C",
                    "strategy": strategy,
                    "reason": reason,
                    "delta": delta,
                })

    # Process puts
    if config.include_puts:
        # Convert to negative deltas for puts
        put_target_deltas = [-d for d in config.target_deltas]

        if strategy == "closest_match":
            put_strikes = select_by_closest_match(
                strikes, spot_price, put_target_deltas, "P"
            )
            for strike, reason in put_strikes:
                contracts.append({
                    "strike": strike,
                    "right": "P",
                    "strategy": strategy,
                    "reason": reason,
                    "delta": None,
                })

        elif strategy == "black_scholes":
            put_strikes = select_by_black_scholes(
                strikes, spot_price, expiry, as_of,
                put_target_deltas, "P",
                config.risk_free_rate, config.implied_volatility,
                config.delta_tolerance,
            )
            for strike, reason, delta in put_strikes:
                contracts.append({
                    "strike": strike,
                    "right": "P",
                    "strategy": strategy,
                    "reason": reason,
                    "delta": delta,
                })

        elif strategy == "ib_greeks":
            if not runtime or not underlying_symbol or not underlying_conid:
                raise ValueError("runtime, underlying_symbol, and underlying_conid required for ib_greeks")

            put_strikes = select_by_ib_greeks(
                runtime, underlying_symbol, underlying_conid,
                strikes, expiry, put_target_deltas, "P",
                tolerance=config.delta_tolerance,
            )
            for strike, reason, delta in put_strikes:
                contracts.append({
                    "strike": strike,
                    "right": "P",
                    "strategy": strategy,
                    "reason": reason,
                    "delta": delta,
                })

    return contracts
