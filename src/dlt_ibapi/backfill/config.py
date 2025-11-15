"""
Configuration models for backfill operations.

Defines Pydantic models for controlling backfill behavior, contract selection,
and option-specific parameters.
"""

from datetime import date
from enum import Enum
from typing import List, Optional, Union

from pydantic import BaseModel, Field, field_validator


class ContractSelectionMode(str, Enum):
    """Method for selecting option contracts to backfill."""

    K_AROUND_ATM = "k_around_atm"  # Select k strikes on each side of ATM
    MONEYNESS = "moneyness"  # Select by strike/spot ratios
    DELTA = "delta"  # Select by option delta (requires Black-Scholes)
    ALL = "all"  # Select all available strikes


class BackfillConfig(BaseModel):
    """
    Configuration for equity bars backfill.

    Controls date ranges, bar sizes, and data types for historical data requests.
    """

    start_date: date = Field(
        ...,
        description="Start date for backfill (inclusive)"
    )

    end_date: date = Field(
        ...,
        description="End date for backfill (inclusive)"
    )

    bar_size: str = Field(
        default="1 min",
        description="Bar size (e.g., '1 min', '5 mins', '1 hour', '1 day')"
    )

    what_to_show: str = Field(
        default="TRADES",
        description="Data type to show (TRADES, MIDPOINT, BID, ASK, etc.)"
    )

    use_rth: bool = Field(
        default=True,
        description="Use regular trading hours only (True) or include extended hours (False)"
    )

    max_days_per_request: int = Field(
        default=1,
        description="Maximum days to request per IB API call (depends on bar_size)"
    )

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_dates(cls, v):
        """Ensure dates are not in the future."""
        if v > date.today():
            raise ValueError(f"Date {v} cannot be in the future")
        return v

    @field_validator("end_date")
    @classmethod
    def validate_end_after_start(cls, v, info):
        """Ensure end_date >= start_date."""
        if "start_date" in info.data and v < info.data["start_date"]:
            raise ValueError(f"end_date {v} must be >= start_date {info.data['start_date']}")
        return v


class OptionBackfillConfig(BackfillConfig):
    """
    Configuration for option bars backfill.

    Extends BackfillConfig with option-specific parameters for contract selection.
    """

    selection_mode: ContractSelectionMode = Field(
        default=ContractSelectionMode.K_AROUND_ATM,
        description="Method for selecting option contracts"
    )

    # For K_AROUND_ATM mode
    k_strikes: int = Field(
        default=5,
        description="Number of strikes on each side of ATM (for k_around_atm mode)",
        ge=1,
        le=20
    )

    # For MONEYNESS mode
    moneyness_levels: Optional[List[float]] = Field(
        default=None,
        description="Target moneyness ratios (strike/spot) for moneyness mode. Example: [0.9, 0.95, 1.0, 1.05, 1.1]"
    )

    # For DELTA mode
    target_deltas: Optional[List[float]] = Field(
        default=None,
        description="Target delta values for delta mode. Example: [0.25, 0.50, 0.75] for calls"
    )

    # Expiration filters
    min_dte: int = Field(
        default=7,
        description="Minimum days to expiration to include",
        ge=0
    )

    max_dte: int = Field(
        default=60,
        description="Maximum days to expiration to include",
        ge=1
    )

    k_expirations: Optional[int] = Field(
        default=None,
        description="Limit to k closest expirations (soonest to expire). None = use all expirations.",
        ge=1,
        le=20
    )

    # Call/put selection
    include_calls: bool = Field(
        default=True,
        description="Include call options"
    )

    include_puts: bool = Field(
        default=True,
        description="Include put options"
    )

    @field_validator("moneyness_levels")
    @classmethod
    def validate_moneyness(cls, v, info):
        """Validate moneyness levels if provided."""
        if v is None:
            return v
        if info.data.get("selection_mode") == ContractSelectionMode.MONEYNESS and not v:
            raise ValueError("moneyness_levels required when selection_mode=moneyness")
        if any(m <= 0 for m in v):
            raise ValueError("moneyness_levels must be positive")
        return v

    @field_validator("target_deltas")
    @classmethod
    def validate_deltas(cls, v, info):
        """Validate delta targets if provided."""
        if v is None:
            return v
        if info.data.get("selection_mode") == ContractSelectionMode.DELTA and not v:
            raise ValueError("target_deltas required when selection_mode=delta")
        if any(d <= 0 or d >= 1 for d in v):
            raise ValueError("target_deltas must be between 0 and 1")
        return v

    @field_validator("max_dte")
    @classmethod
    def validate_dte_range(cls, v, info):
        """Ensure max_dte > min_dte."""
        if "min_dte" in info.data and v <= info.data["min_dte"]:
            raise ValueError(f"max_dte {v} must be > min_dte {info.data['min_dte']}")
        return v


class OptionChainSnapshotConfig(BaseModel):
    """
    Configuration for option chain snapshot collection.

    Captures full option chain at a specific point in time.
    """

    snapshot_date: date = Field(
        ...,
        description="Date to capture option chain snapshot"
    )

    min_dte: int = Field(
        default=7,
        description="Minimum days to expiration to include",
        ge=0
    )

    max_dte: int = Field(
        default=365,
        description="Maximum days to expiration to include",
        ge=1
    )

    @field_validator("snapshot_date")
    @classmethod
    def validate_snapshot_date(cls, v):
        """Ensure snapshot date is not in the future."""
        if v > date.today():
            raise ValueError(f"snapshot_date {v} cannot be in the future")
        return v
