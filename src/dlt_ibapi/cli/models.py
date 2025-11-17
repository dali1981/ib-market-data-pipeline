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
from datetime import date, datetime
from pathlib import Path
from typing import Optional, List, Dict, Literal, Any


def _get_default_database_path() -> Path:
    """Get default database path from storage config.

    Falls back to 'data' if storage config not available.
    """
    try:
        from delta_lake_storage import get_config
        config = get_config()
        return Path(config.storage.base_path)
    except Exception:
        return Path("data")


# Backfill Equity Models

class BackfillEquityParams(BaseModel):
    """Parameters for equity backfill operation.

    Supports two modes:
    1. Explicit symbols: Provide 'symbols' list
    2. Earnings mode: Provide 'earnings_date' to auto-load symbols from earnings calendar

    Either 'symbols' OR 'earnings_date' must be provided (mutually exclusive).
    """
    model_config = ConfigDict(frozen=True)

    symbols: Optional[List[str]] = Field(default=None, min_length=1, description="Stock symbols to backfill (for explicit mode)")
    earnings_date: Optional[date] = Field(default=None, description="Earnings date to backfill all symbols (for batch mode)")
    earnings_dataset_name: str = Field("earnings", description="Dataset name for earnings data (only used with earnings_date)")
    start_date: date = Field(..., description="Start date for backfill")
    end_date: date = Field(..., description="End date for backfill")
    bar_size: str = Field(
        "1 day",
        pattern="^(1 secs|5 secs|10 secs|15 secs|30 secs|1 min|2 mins|3 mins|5 mins|10 mins|15 mins|20 mins|30 mins|1 hour|2 hours|3 hours|4 hours|8 hours|1 day|1 week|1 month)$",
        description="Bar size for historical data"
    )
    pipeline_name: str = Field(..., min_length=1, description="DLT pipeline name")
    dataset_name: str = Field("stocks", description="Dataset name")
    database_path: Path = Field(default_factory=_get_default_database_path, description="Path to data directory")
    use_delta: bool = Field(default=False, description="Use Delta Lake table format (ACID, time travel)")
    client_id: Optional[int] = Field(
        default=None,
        ge=0,
        description="IB Gateway client ID (overrides config default if provided)"
    )

    @field_validator('end_date')
    @classmethod
    def validate_date_range(cls, v: date, info) -> date:
        """Ensure end_date is after start_date."""
        if 'start_date' in info.data and v < info.data['start_date']:
            raise ValueError('end_date must be after or equal to start_date')
        return v

    @field_validator('symbols')
    @classmethod
    def validate_symbols(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Ensure symbols are uppercase and non-empty."""
        if v is None:
            return None
        return [s.upper().strip() for s in v if s.strip()]

    def model_post_init(self, __context):
        """Validate that exactly one of symbols or earnings_date is provided."""
        if self.symbols and self.earnings_date:
            raise ValueError('Cannot specify both symbols and earnings_date. Use one or the other.')
        if not self.symbols and not self.earnings_date:
            raise ValueError('Must specify either symbols or earnings_date')


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
    """Parameters for options backfill operation.

    Supports two modes:
    1. Single symbol mode: Provide 'underlying' and 'spot_price'
    2. Earnings batch mode: Provide 'earnings_date' (auto-loads symbols, spot prices, expirations)

    Either 'underlying' OR 'earnings_date' must be provided (mutually exclusive).
    """
    model_config = ConfigDict(frozen=True)

    # Mode 1: Single symbol
    underlying: Optional[str] = Field(default=None, min_length=1, description="Underlying symbol (for single mode)")
    spot_price: Optional[float] = Field(default=None, gt=0, description="Current spot price (for single mode)")

    # Mode 2: Earnings batch
    earnings_date: Optional[date] = Field(default=None, description="Earnings date to backfill all symbols (for batch mode)")
    earnings_symbols_filter: Optional[List[str]] = Field(default=None, description="Filter specific symbols in earnings mode (None = all symbols on earnings_date)")
    auto_spot_price: bool = Field(True, description="Auto-extract spot prices from equity bars (used with earnings_date)")
    k_expirations: Optional[int] = Field(default=None, ge=1, le=12, description="Limit to k closest expirations beyond earnings date (None = all)")
    snapshot_date: Optional[date] = Field(default=None, description="Snapshot date to read expirations from (defaults to earnings_date)")
    earnings_dataset_name: str = Field("earnings", description="Dataset name for earnings data")
    option_chains_dataset_name: str = Field("option_chains", description="Dataset name for option chains snapshots")
    stocks_dataset_name: str = Field("stocks", description="Dataset name for equity bars (for spot price extraction)")

    # Common parameters
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
    min_dte: int = Field(7, ge=0, description="Minimum days to expiration (not used in earnings mode)")
    max_dte: int = Field(60, ge=0, description="Maximum days to expiration (not used in earnings mode)")
    pipeline_name: str = Field(..., min_length=1, description="DLT pipeline name")
    dataset_name: str = Field("options", description="Dataset name")
    database_path: Path = Field(default_factory=_get_default_database_path, description="Path to data directory")
    use_delta: bool = Field(default=False, description="Use Delta Lake table format (ACID, time travel)")
    client_id: Optional[int] = Field(
        default=None,
        ge=0,
        description="IB Gateway client ID (overrides config default if provided)"
    )

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
    def validate_underlying(cls, v: Optional[str]) -> Optional[str]:
        """Ensure underlying is uppercase if provided."""
        return v.upper().strip() if v else None

    @field_validator('earnings_symbols_filter')
    @classmethod
    def validate_earnings_symbols_filter(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Ensure symbols in filter are uppercase and non-empty."""
        if v is None:
            return None
        # Uppercase all symbols and filter out empty strings
        return [s.upper().strip() for s in v if s and s.strip()]

    def model_post_init(self, __context):
        """Validate mode-specific requirements."""
        # Check mutual exclusivity
        if self.underlying and self.earnings_date:
            raise ValueError('Cannot specify both underlying and earnings_date. Use one or the other.')
        if not self.underlying and not self.earnings_date:
            raise ValueError('Must specify either underlying or earnings_date')

        # Validate single symbol mode requirements
        if self.underlying and not self.spot_price:
            raise ValueError('spot_price is required when using underlying (single symbol mode)')

        # Validate earnings mode requirements
        if self.earnings_date:
            if self.spot_price is not None:
                raise ValueError('spot_price should not be specified in earnings mode (use auto_spot_price=True)')
            if not self.auto_spot_price:
                raise ValueError('auto_spot_price must be True in earnings mode (cannot manually specify spot prices for batch)')


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
    """Parameters for option chain snapshot operation.

    Supports two modes:
    1. Single symbol snapshot: Provide 'underlying'
    2. Batch earnings snapshot: Provide 'earnings_date'

    Either 'underlying' OR 'earnings_date' must be provided (mutually exclusive).
    """
    model_config = ConfigDict(frozen=True)

    underlying: Optional[str] = Field(default=None, min_length=1, description="Underlying symbol (for single snapshot)")
    earnings_date: Optional[date] = Field(default=None, description="Earnings date to snapshot all symbols (for batch snapshot)")
    earnings_time_filter: Optional[str] = Field(
        default=None,
        pattern="^(PRE_MARKET|AFTER_HOURS|UNKNOWN)$",
        description="Filter symbols by earnings time (only used with earnings_date)"
    )
    snapshot_date: date = Field(..., description="Date to capture snapshot")
    min_dte: int = Field(7, ge=0, description="Minimum days to expiration")
    max_dte: int = Field(365, ge=0, description="Maximum days to expiration")
    pipeline_name: str = Field(..., min_length=1, description="DLT pipeline name")
    dataset_name: str = Field("option_chains", description="Dataset name")
    earnings_dataset_name: str = Field("earnings", description="Dataset name for earnings data")
    database_path: Path = Field(default_factory=_get_default_database_path, description="Path to data directory")
    use_delta: bool = Field(default=False, description="Use Delta Lake table format (ACID, time travel)")
    cache_path: Path = Field(default=Path(".dlt-ibapi/cache"), description="Contract cache path")

    @field_validator('underlying')
    @classmethod
    def validate_underlying(cls, v: Optional[str]) -> Optional[str]:
        """Ensure underlying is uppercase if provided."""
        return v.upper().strip() if v else None

    @field_validator('max_dte')
    @classmethod
    def validate_dte_range(cls, v: int, info) -> int:
        """Ensure max_dte is greater than min_dte."""
        if 'min_dte' in info.data and v < info.data['min_dte']:
            raise ValueError('max_dte must be greater than or equal to min_dte')
        return v

    def model_post_init(self, __context):
        """Validate that exactly one of underlying or earnings_date is provided."""
        if self.underlying and self.earnings_date:
            raise ValueError('Cannot specify both underlying and earnings_date. Use one or the other.')
        if not self.underlying and not self.earnings_date:
            raise ValueError('Must specify either underlying or earnings_date')
        if self.earnings_time_filter and not self.earnings_date:
            raise ValueError('earnings_time_filter can only be used with earnings_date')


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


class BatchSnapshotResult(BaseModel):
    """Result of batch snapshot operation for earnings date.

    Aggregates results from multiple symbol snapshots.
    """
    success: bool = Field(..., description="Whether batch operation succeeded (all or partial success)")
    earnings_date: date = Field(..., description="Earnings date that was queried")
    snapshot_date: date = Field(..., description="Date snapshots were taken")
    total_symbols: int = Field(..., ge=0, description="Total symbols found with earnings")
    successful_snapshots: int = Field(default=0, ge=0, description="Number of successful snapshots")
    failed_snapshots: int = Field(default=0, ge=0, description="Number of failed snapshots")
    failed_symbols: List[str] = Field(default_factory=list, description="Symbols that failed to snapshot")
    pipeline_name: str = Field(..., description="DLT pipeline name used")
    duration_seconds: float = Field(..., ge=0, description="Total duration of batch operation")
    warnings: List[str] = Field(default_factory=list, description="Warning messages from all snapshots")
    individual_results: List[SnapshotResult] = Field(default_factory=list, description="Results for each symbol")


# List Snapshots Models

class ListSnapshotsParams(BaseModel):
    """Parameters for list-snapshots operation."""
    model_config = ConfigDict(frozen=True)

    underlying: Optional[str] = Field(default=None, description="Filter by underlying symbol")
    database_path: Path = Field(default_factory=_get_default_database_path, description="Path to data directory")
    dataset_name: str = Field("option_chains", description="Dataset name")
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


# Resolve Contracts Models

class ResolveContractsParams(BaseModel):
    """Parameters for resolve-contracts operation."""
    model_config = ConfigDict(frozen=True)

    symbols: Optional[List[str]] = Field(default=None, description="Explicit list of symbols to resolve")
    earnings_date: Optional[date] = Field(default=None, description="Load symbols from earnings on this date")
    earnings_file: Optional[Path] = Field(default=None, description="Load symbols from earnings JSON file")
    database_path: Path = Field(default_factory=_get_default_database_path, description="Path to data directory")
    cache_path: Path = Field(default=Path(".dlt-ibapi/cache"), description="Path to contract cache")
    exchange: str = Field(default="SMART", description="Exchange for contract resolution")
    currency: str = Field(default="USD", description="Currency for contract resolution")
    sec_type: str = Field(default="STK", description="Security type (STK or OPT)")
    timeout: float = Field(default=10.0, gt=0, description="Timeout per symbol in seconds")

    # Option-specific parameters (only used when sec_type="OPT")
    snapshot_date: Optional[date] = Field(default=None, description="Load option contracts from snapshot on this date")
    underlying: Optional[str] = Field(default=None, description="Filter by underlying symbol (for options)")

    @field_validator('symbols')
    @classmethod
    def validate_symbols(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Ensure symbols are uppercase and non-empty."""
        if v is None:
            return None
        return [s.upper().strip() for s in v if s.strip()]

    @field_validator('earnings_file')
    @classmethod
    def validate_earnings_file_exists(cls, v: Optional[Path]) -> Optional[Path]:
        """Ensure earnings file exists if provided."""
        if v is not None and not v.exists():
            raise ValueError(f'Earnings file does not exist: {v}')
        return v


class ContractResolutionInfo(BaseModel):
    """Information about a single resolved contract."""
    symbol: str = Field(..., description="Symbol (underlying for options)")
    conid: int = Field(..., description="IB contract ID")
    exchange: str = Field(..., description="Primary exchange")
    currency: str = Field(..., description="Currency")
    sec_type: str = Field(default="STK", description="Security type (STK or OPT)")
    long_name: Optional[str] = Field(default=None, description="Company/contract name")

    # Option-specific fields
    strike: Optional[float] = Field(default=None, description="Strike price (options only)")
    right: Optional[str] = Field(default=None, description="C or P (options only)")
    expiry: Optional[str] = Field(default=None, description="Expiration YYYYMMDD (options only)")
    local_symbol: Optional[str] = Field(default=None, description="Local symbol (e.g., AAPL  251219C00150000)")


class ResolveContractsResult(BaseModel):
    """Result of resolve-contracts operation."""
    success: bool = Field(..., description="Whether operation succeeded")
    total_requested: int = Field(..., ge=0, description="Total symbols requested")
    resolved: List[ContractResolutionInfo] = Field(default_factory=list, description="Successfully resolved contracts")
    failed: Dict[str, str] = Field(default_factory=dict, description="Failed symbols with error messages")
    skipped: List[str] = Field(default_factory=list, description="Symbols skipped (already in cache)")
    cache_path: Path = Field(..., description="Path to contract cache")
    duration_seconds: float = Field(..., ge=0, description="Duration of operation")
    error: Optional[str] = Field(default=None, description="Overall error message if failed")


# Tick Backfill Models

class BackfillTicksParams(BaseModel):
    """Parameters for tick data backfill operation."""
    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., min_length=1, description="Underlying symbol")
    expiry: date = Field(..., description="Option expiration date")
    strike: float = Field(..., gt=0, description="Strike price")
    right: Literal['C', 'P'] = Field(..., description="Option right (C or P)")
    start_datetime: datetime = Field(..., description="Start datetime for tick data")
    end_datetime: datetime = Field(..., description="End datetime for tick data")
    tick_type: Literal['bid_ask', 'trades'] = Field('bid_ask', description="Type of tick data")
    exchange: str = Field('SMART', description="Exchange")
    currency: str = Field('USD', description="Currency")
    use_rth: bool = Field(True, description="Use regular trading hours only")
    timezone: str = Field('US/Eastern', description="Timezone for datetime formatting")
    database_path: Path = Field(default_factory=_get_default_database_path, description="Path to database")
    dataset_name: str = Field('option_ticks', description="Dataset name")
    pipeline_name: str = Field('ib_tick_backfill', description="DLT pipeline name")

    @field_validator('end_datetime')
    @classmethod
    def validate_datetime_range(cls, v: datetime, info) -> datetime:
        """Ensure end_datetime is after start_datetime."""
        start_datetime = info.data.get('start_datetime')
        if start_datetime and v <= start_datetime:
            raise ValueError('end_datetime must be after start_datetime')
        return v


class BackfillTicksResult(BaseModel):
    """Result of tick backfill operation."""
    success: bool = Field(..., description="Whether backfill succeeded")
    symbol: str = Field(..., description="Underlying symbol")
    expiry: str = Field(..., description="Expiration date")
    strike: float = Field(..., description="Strike price")
    right: str = Field(..., description="Option right")
    tick_type: str = Field(..., description="Type of tick data")
    ticks_loaded: int = Field(..., ge=0, description="Number of ticks loaded")
    time_range: str = Field(..., description="Time range of ticks")
    duration_seconds: float = Field(..., ge=0, description="Duration of backfill")
    error: Optional[str] = Field(default=None, description="Error message if failed")

# Strategy Selection Models

class IVRankParams(BaseModel):
    """Parameters for IV ranking operation."""
    model_config = ConfigDict(frozen=True)

    earnings_date: date = Field(..., description="Earnings date to analyze")
    symbols: Optional[List[str]] = Field(default=None, description="Filter specific symbols (optional)")
    earnings_time: Optional[Literal['PRE_MARKET', 'AFTER_HOURS', 'UNKNOWN']] = Field(
        default=None,
        description="Filter by earnings time (optional)"
    )
    option_type: Literal['C', 'P'] = Field('C', description="Option type (C for calls, P for puts)")
    bar_size: str = Field('5 mins', description="Bar size for IV calculation precision")
    entry_hour: int = Field(15, ge=0, le=23, description="Entry hour (e.g., 15 for 3pm)")
    entry_minute: int = Field(0, ge=0, le=59, description="Entry minute")
    top_n: Optional[int] = Field(default=None, ge=1, description="Limit to top N results")
    output_file: Optional[Path] = Field(default=None, description="Save results to CSV file")
    database_path: Path = Field(default_factory=_get_default_database_path, description="Path to database")
    earnings_dataset: str = Field('earnings', description="Earnings dataset name")
    options_dataset: str = Field('options', description="Options dataset name")
    stocks_dataset: str = Field('stocks', description="Stocks dataset name")
    option_chains_dataset: str = Field('option_chains', description="Option chains dataset name")


class IVRankCandidate(BaseModel):
    """Single IV ranking candidate."""
    symbol: str = Field(..., description="Stock symbol")
    earnings_date: date = Field(..., description="Earnings date")
    earnings_time: str = Field(..., description="Earnings time (PRE_MARKET/AFTER_HOURS/UNKNOWN)")
    spot_price: float = Field(..., description="Underlying spot price at entry")
    strike: float = Field(..., description="ATM strike price")
    iv_short_entry: float = Field(..., description="Implied volatility of short leg at entry")
    iv_long_entry: float = Field(..., description="Implied volatility of long leg at entry")
    iv_ratio_entry: float = Field(..., description="IV ratio (short IV / long IV) at entry")
    short_expiry: date = Field(..., description="Short leg expiration date")
    long_expiry: date = Field(..., description="Long leg expiration date")
    entry_cost_per_contract: float = Field(..., description="Entry cost per contract")
    rank: int = Field(..., ge=1, description="Rank (1 = highest IV ratio)")
    iv_ratio_quartile: str = Field(..., description="Quartile (Q1-Q4, Q4 = highest)")


class IVRankResult(BaseModel):
    """Result of IV ranking operation."""
    success: bool = Field(..., description="Whether ranking succeeded")
    earnings_date: date = Field(..., description="Earnings date analyzed")
    total_symbols: int = Field(..., ge=0, description="Total symbols with earnings")
    tradable_symbols: int = Field(..., ge=0, description="Symbols with sufficient option data")
    ranked_candidates: List[IVRankCandidate] = Field(default_factory=list, description="Ranked candidates")
    duration_seconds: float = Field(..., ge=0, description="Duration of operation")
    error: Optional[str] = Field(default=None, description="Error message if failed")


class StrategySelectParams(IVRankParams):
    """Parameters for strategy selection operation (extends IVRankParams)."""

    min_iv_ratio: Optional[float] = Field(default=None, gt=0, description="Minimum IV ratio threshold")
    max_entry_cost: Optional[float] = Field(default=None, gt=0, description="Maximum entry cost per contract")
    min_quartile: Optional[Literal['Q1', 'Q2', 'Q3', 'Q4']] = Field(
        default=None,
        description="Minimum quartile to include"
    )
    profitable_only: bool = Field(False, description="Only include profitable trades (from backtest)")
    top_n: Optional[int] = Field(None, ge=1, description="Limit to top N results (optional)")


class StrategySelectResult(BaseModel):
    """Result of strategy selection operation."""
    success: bool = Field(..., description="Whether selection succeeded")
    earnings_date: date = Field(..., description="Earnings date analyzed")
    total_evaluated: int = Field(..., ge=0, description="Total candidates evaluated")
    selected_count: int = Field(..., ge=0, description="Number of candidates selected")
    selection_criteria: Dict[str, Any] = Field(default_factory=dict, description="Applied selection filters")
    selected_candidates: List[IVRankCandidate] = Field(default_factory=list, description="Selected candidates")
    statistics: Dict[str, float] = Field(
        default_factory=dict,
        description="Summary statistics (mean_iv_ratio, expected_pnl, win_rate, etc.)"
    )
    duration_seconds: float = Field(..., ge=0, description="Duration of operation")
    error: Optional[str] = Field(default=None, description="Error message if failed")
