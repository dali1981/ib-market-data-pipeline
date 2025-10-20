"""
Contract selection algorithms for option backfilling.

Provides methods to select option contracts based on:
- K strikes around ATM
- Moneyness ratios (strike/spot)
- Delta targets (using Black-Scholes)
"""

from datetime import date
from typing import List, Tuple, Optional
import math

import pandas as pd
from scipy.stats import norm


def select_k_around_atm(
    strikes: List[float],
    spot_price: float,
    k: int = 5,
) -> List[float]:
    """
    Select k strikes on each side of ATM strike.

    Args:
        strikes: List of available strike prices
        spot_price: Current spot price of underlying
        k: Number of strikes on each side of ATM

    Returns:
        List of selected strikes (up to 2*k + 1 strikes)
    """
    if not strikes:
        return []

    strikes_sorted = sorted(strikes)

    # Find ATM strike (closest to spot)
    atm_idx = min(range(len(strikes_sorted)), key=lambda i: abs(strikes_sorted[i] - spot_price))

    # Select k strikes on each side
    start_idx = max(0, atm_idx - k)
    end_idx = min(len(strikes_sorted), atm_idx + k + 1)

    return strikes_sorted[start_idx:end_idx]


def select_by_moneyness(
    strikes: List[float],
    spot_price: float,
    target_moneyness: List[float],
    tolerance: float = 0.05,
) -> List[float]:
    """
    Select strikes by target moneyness ratios (strike/spot).

    Args:
        strikes: List of available strike prices
        spot_price: Current spot price of underlying
        target_moneyness: Target moneyness ratios (e.g., [0.9, 0.95, 1.0, 1.05, 1.1])
        tolerance: Acceptable deviation from target moneyness

    Returns:
        List of selected strikes
    """
    if not strikes:
        return []

    selected = []

    for target in target_moneyness:
        target_strike = spot_price * target

        # Find closest strike within tolerance
        candidates = [
            s for s in strikes
            if abs(s / spot_price - target) <= tolerance
        ]

        if candidates:
            # Pick closest to target
            best = min(candidates, key=lambda s: abs(s - target_strike))
            if best not in selected:
                selected.append(best)

    return sorted(selected)


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

    Args:
        spot: Current spot price
        strike: Strike price
        time_to_expiry: Time to expiration in years
        risk_free_rate: Risk-free interest rate (annualized)
        volatility: Implied volatility (annualized)

    Returns:
        Put delta (-1 to 0)
    """
    call_delta = black_scholes_call_delta(spot, strike, time_to_expiry, risk_free_rate, volatility)
    return call_delta - 1.0


def select_by_delta(
    strikes: List[float],
    spot_price: float,
    expiry: date,
    as_of: date,
    target_deltas: List[float],
    option_type: str = "C",
    risk_free_rate: float = 0.05,
    volatility: float = 0.30,
    tolerance: float = 0.05,
) -> List[float]:
    """
    Select strikes by target delta values using Black-Scholes.

    Args:
        strikes: List of available strike prices
        spot_price: Current spot price of underlying
        expiry: Option expiration date
        as_of: Current date (for calculating time to expiry)
        target_deltas: Target delta values (e.g., [0.25, 0.50, 0.75] for calls)
        option_type: "C" for calls, "P" for puts
        risk_free_rate: Risk-free rate (annualized, default 0.05 = 5%)
        volatility: Implied volatility estimate (annualized, default 0.30 = 30%)
        tolerance: Acceptable deviation from target delta

    Returns:
        List of selected strikes
    """
    if not strikes:
        return []

    # Calculate time to expiry in years
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
            if best_strike not in selected:
                selected.append(best_strike)

    return sorted(selected)


def filter_contracts_by_selection_mode(
    chain_snapshot: pd.DataFrame,
    spot_price: float,
    as_of: date,
    selection_mode: str,
    k_strikes: int = 5,
    moneyness_levels: Optional[List[float]] = None,
    target_deltas: Optional[List[float]] = None,
    include_calls: bool = True,
    include_puts: bool = True,
    risk_free_rate: float = 0.05,
    volatility: float = 0.30,
) -> List[Tuple[date, float, str]]:
    """
    Filter option contracts from chain snapshot based on selection mode.

    Args:
        chain_snapshot: DataFrame with option chain (from OptionChainSnapshotReader)
        spot_price: Current spot price
        as_of: Snapshot date
        selection_mode: "k_around_atm", "moneyness", "delta", or "all"
        k_strikes: For k_around_atm mode
        moneyness_levels: For moneyness mode
        target_deltas: For delta mode
        include_calls: Include call options
        include_puts: Include put options
        risk_free_rate: For delta calculations
        volatility: For delta calculations

    Returns:
        List of (expiry, strike, right) tuples
    """
    if chain_snapshot.empty:
        return []

    contracts = []

    # Get unique expirations from chain
    for idx, row in chain_snapshot.iterrows():
        expirations = row.get("expirations", [])
        strikes = row.get("strikes", [])

        if not expirations or not strikes:
            continue

        # Process each expiration
        for exp_str in expirations:
            # Parse expiration date
            try:
                from datetime import datetime
                expiry = datetime.strptime(exp_str, "%Y%m%d").date()
            except Exception:
                continue

            # Select strikes based on mode
            if selection_mode == "k_around_atm":
                selected_strikes = select_k_around_atm(strikes, spot_price, k_strikes)

            elif selection_mode == "moneyness":
                if not moneyness_levels:
                    moneyness_levels = [0.9, 0.95, 1.0, 1.05, 1.1]
                selected_strikes = select_by_moneyness(strikes, spot_price, moneyness_levels)

            elif selection_mode == "delta":
                if not target_deltas:
                    target_deltas = [0.25, 0.50, 0.75]

                selected_strikes = []
                if include_calls:
                    call_strikes = select_by_delta(
                        strikes, spot_price, expiry, as_of,
                        target_deltas, "C", risk_free_rate, volatility
                    )
                    selected_strikes.extend(call_strikes)

                if include_puts:
                    # For puts, use negative target deltas
                    put_target_deltas = [-d for d in target_deltas]
                    put_strikes = select_by_delta(
                        strikes, spot_price, expiry, as_of,
                        put_target_deltas, "P", risk_free_rate, volatility
                    )
                    selected_strikes.extend(put_strikes)

                selected_strikes = sorted(set(selected_strikes))

            elif selection_mode == "all":
                selected_strikes = strikes

            else:
                raise ValueError(f"Unknown selection mode: {selection_mode}")

            # Create contract tuples
            for strike in selected_strikes:
                if include_calls:
                    contracts.append((expiry, strike, "C"))
                if include_puts:
                    contracts.append((expiry, strike, "P"))

    return contracts
