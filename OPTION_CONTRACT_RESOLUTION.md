# Option Contract Resolution Implementation

## Overview

Implemented full option contract resolution workflow parallel to the equity contract resolution system. This allows pre-population of option contract cache before running expensive backfill operations, ensuring correct contract matching and reducing IB API calls.

## Changes Made

### 1. Contract Cache Schema Extension

**File**: `src/dlt_ibapi/resolution/contract_cache.py`

Added option-specific fields to the contract cache schema:
- `strike: float64` - Strike price
- `right: string` - "C" or "P" (call/put)
- `last_trade_date: string` - Expiration date (YYYYMMDD format)

Added new method:
- `get_option_contract()` - Query specific option contract by (symbol, expiry, strike, right)

### 2. Contract Resolver Extension

**File**: `src/dlt_ibapi/resolution/resolver.py`

Added new method:
```python
def resolve_option_contract(
    self,
    symbol: str,
    expiry: str,  # YYYYMMDD
    strike: float,
    right: str,  # "C" or "P"
    exchange: str = "SMART",
    currency: str = "USD",
    multiplier: str = "100",
    use_cache: bool = True,
    save_to_cache: bool = True,
    timeout: float = 10.0,
) -> Optional[Dict[str, Any]]:
```

**Workflow**:
1. Check cache first (if `use_cache=True`)
2. Create partial option contract with `make_option()`
3. Call ContractDetails API to get full contract info
4. Parse response (conId, localSymbol, tradingClass, etc.)
5. Save to cache (if `save_to_cache=True`)
6. Return resolved contract dict

### 3. CLI Models Extension

**File**: `src/dlt_ibapi/cli/models.py`

Extended `ResolveContractsParams`:
- `sec_type: str = "STK"` - Support both "STK" and "OPT"
- `snapshot_date: Optional[date]` - Load option contracts from snapshot
- `underlying: Optional[str]` - Filter by underlying symbol

Extended `ContractResolutionInfo`:
- `sec_type: str = "STK"` - Security type indicator
- `strike: Optional[float]` - Strike price (options only)
- `right: Optional[str]` - Call/Put (options only)
- `expiry: Optional[str]` - Expiration date (options only)
- `local_symbol: Optional[str]` - IB local symbol

### 4. Business Logic Extension

**File**: `src/dlt_ibapi/cli/resolve.py`

Added functions:
- `_load_option_contracts_from_snapshot()` - Load contracts from option_chains snapshots
- `_execute_resolve_option_contracts()` - Batch resolve option contracts
- Updated `execute_resolve_contracts()` - Route to equity or option resolver based on `sec_type`

**Option Resolution Workflow**:
1. Load option contracts from snapshot data (expand expirations × strikes × rights)
2. Check cache for already-resolved contracts
3. Resolve new contracts via IB API (with per-contract error handling)
4. Save to cache
5. Return summary (resolved, failed, skipped counts)

### 5. CLI Command Extension

**File**: `src/dlt_ibapi/cli_app.py`

Extended `resolve-contracts` command with new options:
- `--sec-type` - Security type (STK or OPT)
- `--snapshot-date` - Snapshot date for option resolution
- `--underlying` - Filter by underlying symbol

**New Examples**:
```bash
# Resolve option contracts from snapshot
dlt-ibapi resolve-contracts --sec-type OPT --snapshot-date 2025-11-13

# Resolve options for specific underlying
dlt-ibapi resolve-contracts --sec-type OPT --snapshot-date 2025-11-13 --underlying AAPL
```

### 6. Backfill Resource Integration

**File**: `src/dlt_ibapi/backfill/resources.py`

Updated `backfill_option_bars()` to use resolved contracts:

**Before** (lines 372-378):
```python
contract = make_option(
    symbol=underlying,
    last_trade_date=expiry.strftime("%Y%m%d"),
    strike=strike,
    right=right,
    exch="SMART",
)
```

**After** (lines 367-403):
```python
# Resolve contract (uses cache if available)
resolved = resolver.resolve_option_contract(
    symbol=underlying,
    expiry=expiry.strftime("%Y%m%d"),
    strike=strike,
    right=right,
    exchange="SMART",
    currency="USD",
    use_cache=True,
    save_to_cache=True,
)

# Create option contract using resolved details
contract = make_option(
    symbol=underlying,
    last_trade_date=expiry.strftime("%Y%m%d"),
    strike=strike,
    right=right,
    exch=resolved.get("exchange", "SMART"),
)
# Set additional fields from resolved contract
if resolved.get("trading_class"):
    contract.tradingClass = resolved["trading_class"]
if resolved.get("local_symbol"):
    contract.localSymbol = resolved["local_symbol"]
if resolved.get("conid"):
    contract.conId = resolved["conid"]
```

**Benefits**:
- Uses IB-validated contract IDs (conId)
- Includes tradingClass for accurate contract matching
- Includes localSymbol for debugging
- Pre-resolution catches invalid contracts before backfill

## Workflow

### Recommended Usage Pattern

1. **Capture option chain snapshot**:
   ```bash
   dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60
   ```

2. **Pre-resolve option contracts** (new step):
   ```bash
   dlt-ibapi resolve-contracts --sec-type OPT --snapshot-date 2025-11-13 --underlying AAPL
   ```

   This will:
   - Load all option contracts from the snapshot
   - Call ContractDetails API for each contract
   - Cache resolved contracts in `.dlt-ibapi/cache/contracts/`
   - Report success/failure summary

3. **Backfill option bars** (uses cached contracts):
   ```bash
   dlt-ibapi backfill-options AAPL 150.0 --mode atm --k-strikes 3
   ```

   Backfill will:
   - Automatically use cached contracts (no extra API calls)
   - Use correct conId, tradingClass, localSymbol
   - Skip contracts that failed resolution
   - Handle resolution on-demand if not pre-populated

### Storage Locations

- **Contract cache**: `.dlt-ibapi/cache/contracts/`
  - Partitioning: `sec_type=OPT/snapshot=YYYY-MM-DD/*.parquet`
  - Deduplication: By `conid` (IB contract ID)
  - Schema: conid, symbol, strike, right, last_trade_date, trading_class, local_symbol, etc.

- **Option chain snapshots**: `./data/option_chains/option_chain_snapshot/*.parquet`
  - Source data for contract resolution
  - Contains: underlying, expirations, strikes, trading_class, multiplier

- **Option bars**: `./data/options/option_bars_backfill/*.parquet`
  - Historical OHLCV data for resolved contracts
  - Uses contracts from cache

## Error Handling

- **Per-contract error handling**: Failed contracts don't stop batch
- **Graceful fallback**: Backfill resolves on-demand if not pre-populated
- **Clear logging**: Reports resolved/failed/skipped counts
- **Cache-first**: Always checks cache before API call

## Benefits

1. **Pre-validation**: Catch invalid contracts before expensive backfill operations
2. **Reduced API calls**: Cache eliminates repeated ContractDetails requests
3. **Accurate matching**: Uses IB-validated conId, tradingClass, localSymbol
4. **Error tolerance**: Per-contract errors don't block entire batch
5. **Unified workflow**: Single CLI command for both equity and option resolution
6. **Debugging**: localSymbol field helps identify contracts in logs

## Testing

All code compiles successfully:
- ✓ Import tests pass
- ✓ CLI help displays correctly with new options
- ✓ Pydantic models validate correctly
- ✓ Integration with existing backfill workflow

## Future Enhancements

1. Batch API calls to respect IB rate limits more efficiently
2. Add filtering by DTE range in CLI (avoid resolving all contracts)
3. Add dry-run mode to preview contracts before resolution
4. Add cache inspection CLI command (view cached contracts)
5. Add cache expiration/refresh logic for stale contracts
