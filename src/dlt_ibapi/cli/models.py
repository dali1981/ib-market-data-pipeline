"""Pydantic models for CLI parameters and results.

All CLI commands use Pydantic models for:
- Type safety and validation
- Serialization (JSON, dict)
- Documentation
- Immutability
- Easy testing

Pattern: Use frozen=True for immutability, Field for validation.
"""

from pydantic import BaseModel, Field, field_validator, ConfigDict
from datetime import date
from pathlib import Path
from typing import Optional, List


# Backfill Equity Models

class BackfillEquityParams(BaseModel):
    """Parameters for equity backfill operation.

    Validates all inputs including date ranges, symbols, bar sizes, etc.
    """
    model_config = ConfigDict(frozen=True)

    symbols: List[str] = Field(..., min_length=1, description="Stock symbols to backfill")
    start_date: date = Field(..., description="Start date for backfill")
    end_date: date = Field(..., description="End date for backfill")
    bar_size: str = Field(
        "1 day",
        pattern="^(1 secs|5 secs|10 secs|15 secs|30 secs|1 min|2 mins|3 mins|5 mins|10 mins|15 mins|20 mins|30 mins|1 hour|2 hours|3 hours|4 hours|8 hours|1 day|1 week|1 month)$",
        description="Bar size for historical data"
    )
    pipeline_name: str = Field(..., min_length=1, description="DLT pipeline name")
    dataset_name: str = Field("stocks", description="Dataset name")
    database_path: Path = Field(default=Path("data"), description="Path to data directory")

    @field_validator('end_date')
    @classmethod
    def validate_date_range(cls, v: date, info) -> date:
        """Ensure end_date is after start_date."""
        if 'start_date' in info.data and v < info.data['start_date']:
            raise ValueError('end_date must be after or equal to start_date')
        return v

    @field_validator('symbols')
    @classmethod
    def validate_symbols(cls, v: List[str]) -> List[str]:
        """Ensure symbols are uppercase and non-empty."""
        return [s.upper().strip() for s in v if s.strip()]


class BackfillEquityResult(BaseModel):
    """Result of equity backfill operation.

    Structured response with success status, metrics, and optional error.
    """
    success: bool = Field(..., description="Whether backfill succeeded")
    symbols_processed: List[str] = Field(default_factory=list, description="Symbols successfully backfilled")
    total_bars: int = Field(default=0, ge=0, description="Total bars fetched")
    gaps_filled: int = Field(default=0, ge=0, description="Number of gap windows filled")
    pipeline_name: str = Field(..., description="DLT pipeline name used")
    output_path: Path = Field(..., description="Path where data was saved")
    duration_seconds: float = Field(..., ge=0, description="Duration of backfill")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    warnings: List[str] = Field(default_factory=list, description="Warning messages")


# Backfill Options Models

class BackfillOptionsParams(BaseModel):
    """Parameters for options backfill operation."""
    model_config = ConfigDict(frozen=True)

    underlying: str = Field(..., min_length=1, description="Underlying symbol")
    spot_price: float = Field(..., gt=0, description="Current spot price")
    start_date: date = Field(..., description="Start date for backfill")
    end_date: date = Field(..., description="End date for backfill")
    bar_size: str = Field(
        "1 day",
        pattern="^(1 min|5 mins|1 hour|1 day)$",
        description="Bar size for historical data"
    )
    selection_mode: str = Field(
        "atm",
        pattern="^(atm|moneyness|delta|all)$",
        description="Contract selection mode"
    )
    k_strikes: int = Field(5, ge=1, le=50, description="Number of strikes around ATM")
    min_dte: int = Field(7, ge=0, description="Minimum days to expiration")
    max_dte: int = Field(60, ge=0, description="Maximum days to expiration")
    pipeline_name: str = Field(..., min_length=1, description="DLT pipeline name")
    dataset_name: str = Field("options", description="Dataset name")
    database_path: Path = Field(default=Path("data"), description="Path to data directory")

    @field_validator('end_date')
    @classmethod
    def validate_date_range(cls, v: date, info) -> date:
        """Ensure end_date is after start_date."""
        if 'start_date' in info.data and v < info.data['start_date']:
            raise ValueError('end_date must be after or equal to start_date')
        return v

    @field_validator('max_dte')
    @classmethod
    def validate_dte_range(cls, v: int, info) -> int:
        """Ensure max_dte is greater than min_dte."""
        if 'min_dte' in info.data and v < info.data['min_dte']:
            raise ValueError('max_dte must be greater than or equal to min_dte')
        return v

    @field_validator('underlying')
    @classmethod
    def validate_underlying(cls, v: str) -> str:
        """Ensure underlying is uppercase."""
        return v.upper().strip()


class BackfillOptionsResult(BaseModel):
    """Result of options backfill operation."""
    success: bool = Field(..., description="Whether backfill succeeded")
    contracts_processed: int = Field(default=0, ge=0, description="Number of option contracts processed")
    total_bars: int = Field(default=0, ge=0, description="Total bars fetched")
    gaps_filled: int = Field(default=0, ge=0, description="Number of gap windows filled")
    pipeline_name: str = Field(..., description="DLT pipeline name used")
    output_path: Path = Field(..., description="Path where data was saved")
    duration_seconds: float = Field(..., ge=0, description="Duration of backfill")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    warnings: List[str] = Field(default_factory=list, description="Warning messages")


# Snapshot Models

class SnapshotParams(BaseModel):
    """Parameters for option chain snapshot operation."""
    model_config = ConfigDict(frozen=True)

    underlying: str = Field(..., min_length=1, description="Underlying symbol")
    snapshot_date: date = Field(..., description="Date to capture snapshot")
    min_dte: int = Field(7, ge=0, description="Minimum days to expiration")
    max_dte: int = Field(365, ge=0, description="Maximum days to expiration")
    pipeline_name: str = Field(..., min_length=1, description="DLT pipeline name")
    dataset_name: str = Field("options", description="Dataset name")
    cache_path: Path = Field(default=Path(".dlt-ibapi/cache"), description="Contract cache path")

    @field_validator('max_dte')
    @classmethod
    def validate_dte_range(cls, v: int, info) -> int:
        """Ensure max_dte is greater than min_dte."""
        if 'min_dte' in info.data and v < info.data['min_dte']:
            raise ValueError('max_dte must be greater than or equal to min_dte')
        return v

    @field_validator('underlying')
    @classmethod
    def validate_underlying(cls, v: str) -> str:
        """Ensure underlying is uppercase."""
        return v.upper().strip()


class SnapshotResult(BaseModel):
    """Result of snapshot operation."""
    success: bool = Field(..., description="Whether snapshot succeeded")
    underlying: str = Field(..., description="Underlying symbol")
    snapshot_date: date = Field(..., description="Date snapshot was taken")
    expirations_count: int = Field(default=0, ge=0, description="Number of expirations captured")
    strikes_count: int = Field(default=0, ge=0, description="Number of strikes captured")
    pipeline_name: str = Field(..., description="DLT pipeline name used")
    duration_seconds: float = Field(..., ge=0, description="Duration of snapshot")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    warnings: List[str] = Field(default_factory=list, description="Warning messages")


# List Snapshots Models

class ListSnapshotsParams(BaseModel):
    """Parameters for list-snapshots operation."""
    model_config = ConfigDict(frozen=True)

    underlying: Optional[str] = Field(default=None, description="Filter by underlying symbol")
    database_path: Path = Field(default=Path("data"), description="Path to data directory")
    dataset_name: str = Field("options", description="Dataset name")
    start_date: Optional[date] = Field(default=None, description="Filter by start date")
    end_date: Optional[date] = Field(default=None, description="Filter by end date")

    @field_validator('end_date')
    @classmethod
    def validate_date_range(cls, v: Optional[date], info) -> Optional[date]:
        """Ensure end_date is after start_date if both provided."""
        if v and 'start_date' in info.data and info.data['start_date'] and v < info.data['start_date']:
            raise ValueError('end_date must be after or equal to start_date')
        return v

    @field_validator('underlying')
    @classmethod
    def validate_underlying(cls, v: Optional[str]) -> Optional[str]:
        """Ensure underlying is uppercase if provided."""
        return v.upper().strip() if v else None


class SnapshotInfo(BaseModel):
    """Information about a single snapshot."""
    underlying: str = Field(..., description="Underlying symbol")
    snapshot_date: date = Field(..., description="Date of snapshot")
    expirations: int = Field(..., ge=0, description="Number of expirations")
    strikes: int = Field(..., ge=0, description="Number of strikes")


class ListSnapshotsResult(BaseModel):
    """Result of list-snapshots operation."""
    success: bool = Field(..., description="Whether operation succeeded")
    snapshots: List[SnapshotInfo] = Field(default_factory=list, description="List of snapshots found")
    total_count: int = Field(default=0, ge=0, description="Total snapshots found")
    duration_seconds: float = Field(..., ge=0, description="Duration of operation")
    error: Optional[str] = Field(default=None, description="Error message if failed")


# Stats Models

class StatsParams(BaseModel):
    """Parameters for stats operation."""
    model_config = ConfigDict(frozen=True)

    database_path: Path = Field(..., description="Path to data directory")
    dataset_name: str = Field(..., min_length=1, description="Dataset name")
    table_name: Optional[str] = Field(default=None, description="Specific table to analyze")

    @field_validator('database_path')
    @classmethod
    def validate_path_exists(cls, v: Path) -> Path:
        """Ensure database path exists."""
        if not v.exists():
            raise ValueError(f'Database path does not exist: {v}')
        return v


class TableStats(BaseModel):
    """Statistics for a single table."""
    table_name: str = Field(..., description="Table name")
    row_count: int = Field(..., ge=0, description="Number of rows")
    columns: List[str] = Field(default_factory=list, description="Column names")
    date_range: Optional[str] = Field(default=None, description="Date range if applicable")
    symbols: Optional[List[str]] = Field(default=None, description="Symbols if applicable")


class StatsResult(BaseModel):
    """Result of stats operation."""
    success: bool = Field(..., description="Whether operation succeeded")
    database_path: Path = Field(..., description="Database path analyzed")
    dataset_name: str = Field(..., description="Dataset name")
    tables: List[TableStats] = Field(default_factory=list, description="Table statistics")
    total_tables: int = Field(default=0, ge=0, description="Total tables found")
    duration_seconds: float = Field(..., ge=0, description="Duration of operation")
    error: Optional[str] = Field(default=None, description="Error message if failed")
