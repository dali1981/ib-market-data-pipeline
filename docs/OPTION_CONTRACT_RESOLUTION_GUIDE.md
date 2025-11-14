# Option Contract Resolution Guide

## Quick Start

Option contract resolution is now integrated into the `resolve-contracts` CLI command. Use this to pre-populate the contract cache before backfilling option bars.

## Why Resolve Contracts?

Before fetching historical data, IB requires fully-qualified contract specifications including:
- `conId` - IB's unique contract identifier
- `tradingClass` - Distinguishes between standard/weekly/adjusted options
- `localSymbol` - IB's internal symbol (e.g., "AAPL  251219C00150000")

Without these fields, IB may reject the request or return data for the wrong contract.

## Usage

### Step 1: Capture Option Chain Snapshot

First, capture the available option contracts:

```bash
dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60
```

This saves contract metadata (strikes, expirations, tradingClass) to `./data/option_chains/`.

### Step 2: Resolve Option Contracts

Pre-resolve all contracts from the snapshot:

```bash
# Resolve all contracts from a specific snapshot date
dlt-ibapi resolve-contracts --sec-type OPT --snapshot-date 2025-11-13

# Resolve only for specific underlying
dlt-ibapi resolve-contracts --sec-type OPT --snapshot-date 2025-11-13 --underlying AAPL

# Resolve for multiple underlyings (run snapshot first for each)
dlt-ibapi resolve-contracts --sec-type OPT --snapshot-date 2025-11-13 --underlying MSFT
```

This will:
1. Load contracts from the snapshot (expiry × strike × right combinations)
2. Call IB's ContractDetails API for each contract
3. Cache resolved contracts in `.dlt-ibapi/cache/contracts/`
4. Report success/failure summary

**Output Example**:
```
Resolving contracts...

Loaded 120 option contracts from snapshots
Found 0 contracts in cache, 120 to resolve
Resolving AAPL 20251219 150.0C...
✓ AAPL 20251219 150.0C -> conid=12345678
Resolving AAPL 20251219 150.0P...
✓ AAPL 20251219 150.0P -> conid=12345679
...

Contract Resolution Summary
┌─────────────────┬────────┐
│ Metric          │ Value  │
├─────────────────┼────────┤
│ Total Requested │ 120    │
│ Resolved        │ 118    │
│ Failed          │ 2      │
│ Skipped (Cache) │ 0      │
│ Duration        │ 45.2s  │
└─────────────────┴────────┘
```

### Step 3: Backfill Option Bars

Now backfill bars using the cached contracts:

```bash
dlt-ibapi backfill-options AAPL 150.0 --mode atm --k-strikes 3
```

The backfill will:
- Automatically load cached contracts (no extra API calls)
- Use correct conId, tradingClass, localSymbol
- Skip contracts that failed resolution

## CLI Options

### `resolve-contracts` Command

```bash
dlt-ibapi resolve-contracts [OPTIONS] [SYMBOLS]...
```

**Common Options**:
- `--sec-type` - Security type: `STK` (default) or `OPT`
- `--snapshot-date` - Snapshot date (YYYY-MM-DD) [required for OPT]
- `--underlying` - Filter by underlying symbol [optional for OPT]
- `--database-path` - Path to data directory (default: `./data`)
- `--cache-path` - Path to contract cache (default: `.dlt-ibapi/cache`)

**Examples**:

```bash
# Equity resolution (existing functionality)
dlt-ibapi resolve-contracts AAPL MSFT GOOGL
dlt-ibapi resolve-contracts --earnings-date 2025-11-13

# Option resolution (new functionality)
dlt-ibapi resolve-contracts --sec-type OPT --snapshot-date 2025-11-13
dlt-ibapi resolve-contracts --sec-type OPT --snapshot-date 2025-11-13 --underlying AAPL
```

## Cache Structure

Resolved contracts are stored in:
```
.dlt-ibapi/cache/contracts/
  sec_type=STK/
    snapshot=2025-11-13/
      *.parquet
  sec_type=OPT/
    snapshot=2025-11-13/
      *.parquet
```

**Schema**:
- Primary identifiers: `symbol`, `conid`, `sec_type`
- Option-specific: `strike`, `right`, `last_trade_date`
- IB details: `trading_class`, `local_symbol`, `exchange`, `currency`
- Metadata: `long_name`, `multiplier`, `min_tick`

## Error Handling

### Failed Contracts

Some contracts may fail to resolve due to:
- Invalid strike/expiry combinations
- Delisted/expired contracts in snapshot
- IB API errors

**The command handles this gracefully**:
- Logs error message for failed contract
- Continues with next contract (doesn't stop batch)
- Reports failed contracts in summary

**Example Failed Contract**:
```
Resolving AAPL 20251219 999.0C...
✗ AAPL 20251219 999.0C: No security definition found
```

### Backfill with Missing Contracts

If you skip pre-resolution, backfill will still work:
- Resolves contracts on-demand during backfill
- Slower (adds API overhead to backfill operation)
- Same error handling (logs and continues)

**Recommendation**: Always pre-resolve for large batches.

## Performance

### API Rate Limits

IB's ContractDetails API allows:
- **50 calls/second** for ContractDetails
- Built-in rate limiting in resolver

### Resolution Speed

Approximate times (depends on IB Gateway responsiveness):
- **1 contract**: ~0.2-0.5 seconds
- **100 contracts**: ~20-50 seconds
- **1000 contracts**: ~3-8 minutes

### Optimization Tips

1. **Filter by underlying**: Use `--underlying` to resolve only needed symbols
2. **Cache reuse**: Cache persists across runs - only new contracts are resolved
3. **Batch by date**: Run resolution separately for each snapshot date

## Troubleshooting

### "No option contracts found in snapshots"

**Cause**: No snapshot exists for the specified date/underlying.

**Solution**:
```bash
# Check available snapshots
dlt-ibapi list-snapshots

# Capture snapshot first
dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60
```

### "For option resolution, provide --snapshot-date and/or --underlying"

**Cause**: Missing required parameters for option resolution.

**Solution**:
```bash
# Must specify at least one of these for --sec-type OPT
dlt-ibapi resolve-contracts --sec-type OPT --snapshot-date 2025-11-13
dlt-ibapi resolve-contracts --sec-type OPT --underlying AAPL
```

### "No security definition found for..."

**Cause**: IB doesn't recognize the contract (invalid strike, wrong expiry format, etc.).

**Solution**:
- Check snapshot data for correct strikes/expirations
- Verify underlying symbol is correct
- Check IB Gateway/TWS connection
- Contract may be delisted or expired

### Cache Not Being Used

**Cause**: Cache path mismatch or corrupted cache.

**Solution**:
```bash
# Verify cache location
ls -la .dlt-ibapi/cache/contracts/

# Check cache contents
uv run python -c "
from dlt_ibapi.resolution.contract_cache import ContractCache
cache = ContractCache('.dlt-ibapi/cache')
df = cache.load(sec_type='OPT')
print(df.to_pandas())
"

# Clear cache if needed (will force re-resolution)
rm -rf .dlt-ibapi/cache/contracts/sec_type=OPT/
```

## Integration with Existing Workflows

### Earnings-Driven Workflow

```bash
# 1. Load earnings calendar
dlt-ibapi load-earnings earnings.json

# 2. Resolve equity symbols
dlt-ibapi resolve-contracts --earnings-date 2025-11-13

# 3. Capture option snapshots (uses cached equity contracts)
dlt-ibapi snapshot --earnings-date 2025-11-13 --min-dte 7 --max-dte 60

# 4. Resolve option contracts
dlt-ibapi resolve-contracts --sec-type OPT --snapshot-date 2025-11-13

# 5. Backfill option bars (uses cached option contracts)
dlt-ibapi backfill-options --earnings-date 2025-11-13 --mode atm --k-strikes 5
```

### Manual Symbol Workflow

```bash
# 1. Capture snapshot
dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60

# 2. Resolve option contracts
dlt-ibapi resolve-contracts --sec-type OPT --snapshot-date $(date +%Y-%m-%d) --underlying AAPL

# 3. Backfill option bars
dlt-ibapi backfill-options AAPL 150.0 --mode atm --k-strikes 3
```

## Advanced Usage

### Inspect Cached Contracts

```python
from dlt_ibapi.resolution.contract_cache import ContractCache

cache = ContractCache(".dlt-ibapi/cache")

# Get all option contracts
df = cache.load(sec_type="OPT")
print(df.to_pandas())

# Get contracts for specific symbol
df = cache.load(symbol="AAPL", sec_type="OPT")
print(df.to_pandas())

# Get specific option contract
contract = cache.get_option_contract(
    symbol="AAPL",
    expiry="20251219",
    strike=150.0,
    right="C",
)
print(contract)
```

### Programmatic Resolution

```python
from ib_connector import IBRuntime
from dlt_ibapi.resolution.resolver import ContractResolver
from dlt_ibapi.resolution.contract_cache import ContractCache

# Initialize
runtime = IBRuntime(host="127.0.0.1", port=4002, client_id=1)
runtime.start(ready_timeout=10.0)

cache = ContractCache(".dlt-ibapi/cache")
resolver = ContractResolver(runtime, cache)

# Resolve option contract
result = resolver.resolve_option_contract(
    symbol="AAPL",
    expiry="20251219",
    strike=150.0,
    right="C",
    exchange="SMART",
    currency="USD",
    use_cache=True,
    save_to_cache=True,
)

print(f"Resolved: conId={result['conid']}, localSymbol={result['local_symbol']}")

runtime.stop()
```

## See Also

- [Backfill Guide](BACKFILL_GUIDE.md) - Complete backfill workflow
- [Earnings Guide](EARNINGS_GUIDE.md) - Earnings-driven workflows
- [API Reference](API_REFERENCE.md) - Programmatic API usage
