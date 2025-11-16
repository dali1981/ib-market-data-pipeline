# Option Data Acquisition Specifications

## Purpose

Document the specifications and rationale for how option bars were acquired for the calendar spread earnings strategy analysis.

---

## Current Data: What We Have

### Acquired Data
From `data_delta/options/option_bars_backfill/`:

**Granularity**: 5-minute bars
**Date Range**: 2025-10-01 to 2025-11-13 (varies by symbol)
**Symbols**: 44 tradable earnings symbols on 2025-11-13
**Contracts per Symbol**:
- k_expirations: Variable (limited to post-earnings expirations)
- k_strikes: 3-5 strikes around ATM

**Bar Fields**:
- `datetime`: Timestamp (5-min intervals)
- `open`, `high`, `low`, `close`: OHLC prices
- `volume`: Contracts traded
- `underlying`, `expiry`, `strike`, `right`: Contract identifiers
- `bar_size`: "5 mins"
- Plus Hive partitions: `date`, `symbol`

### Acquisition Command Used

```bash
dlt-ibapi backfill-options --earnings-date 2025-11-13 \
  --k-expirations 6 \
  --k-strikes 5 \
  --bar-size "5 mins" \
  --start 2025-11-01 \
  --end 2025-11-13 \
  --client-id 2
```

**Why these parameters?**

1. **`--bar-size "5 mins"`**:
   - **Pro**: High granularity captures intraday volatility
   - **Pro**: Can aggregate up to hourly/daily as needed
   - **Pro**: Shows precise entry/exit timing around 3pm and 10am
   - **Con**: Larger data volume
   - **Con**: More API requests to IB
   - **Decision**: Chosen for flexibility and precision

2. **`--k-strikes 5`**:
   - Captures 5 strikes around ATM
   - Provides moneyness range: OTM to ITM
   - Allows analysis of different strike choices
   - Balances coverage vs API request volume

3. **`--k-expirations 6`**:
   - Limits to 6 nearest expirations beyond earnings date
   - Captures near-term (for short leg) and far-term (for long leg)
   - Avoids very long-dated options (low volume, wide spreads)

4. **Date Range (2025-11-01 to 2025-11-13)**:
   - 2 weeks before earnings
   - Captures volatility ramp-up into earnings
   - Includes day before (entry) and day after (exit)

---

## Strategy Implementation: Why Hourly?

### Question Raised
> "We have 5 min data, why is the strategy conducted on an hourly basis?"

### Current Implementation

The **calendar spread backtest** in `notebooks/04` and `06` uses:
- **Entry**: 3pm close (day before earnings)
- **Exit**: 10am or 4pm close (after earnings)
- **Data source**: Hourly bars (`bar_size='1 hour'`)

```python
results_df = run_batch_calendar_spread_backtest(
    earnings_df=tradable_earnings,
    option_reader=option_reader,
    equity_reader=equity_reader,
    option_type='C',
    bar_size='1 hour',  # ← Why hourly when we have 5-min?
    progress=True,
    calculate_iv=False
)
```

### Explanation

**The strategy uses hourly bars because:**

1. **Data availability mismatch**:
   - Some symbols have 5-min bars
   - Some symbols only have hourly bars
   - Some symbols only have daily bars
   - Using hourly as baseline ensures broader coverage

2. **Fallback logic in batch.py**:
   ```python
   # batch.py lines 55-65
   actual_bar_size = bar_size  # Try requested bar_size first

   if contracts.empty:
       contracts = option_reader.get_contracts_for_underlying(
           underlying=underlying,
           bar_size=None  # Fallback to ANY bar_size
       )
       if not contracts.empty:
           actual_bar_size = contracts['bar_size'].iloc[0]  # Use whatever is available
   ```

3. **Historical context**:
   - Strategy was initially developed with hourly data
   - Works reliably across all symbols
   - Not yet updated to leverage 5-min precision

### Opportunity for Improvement

**We should use 5-minute bars when available!**

**Benefits**:
1. **More precise entry/exit timing**:
   - Current: 3:00pm-4:00pm hourly bar close
   - Better: 3:00pm-3:05pm 5-min bar close
   - Captures exact moment better

2. **Better gap analysis**:
   - 5-min bars show intraday price action more clearly
   - Can see if prices gap at open vs drift during hour

3. **Improved volume analysis**:
   - Hourly volume = sum of 12 five-min bars
   - 5-min shows when volume actually traded

4. **Spread estimation**:
   - high-low range more accurate with 5-min bars
   - Less noise in bid/ask spread estimation

**Trade-offs**:
1. **Complexity**: Need to aggregate if 5-min not available
2. **Consistency**: Mixing 5-min and hourly introduces variance
3. **Implementation**: Requires updating bar selection logic

---

## Recommended Update: Prefer 5-Min Bars

### Proposed Change

Update `run_batch_calendar_spread_backtest()` to:
1. **Try 5-min bars first** (most precise)
2. **Fallback to hourly** if 5-min unavailable
3. **Fallback to daily** as last resort
4. **Document which bar size was used** in results

### Implementation

```python
def run_batch_calendar_spread_backtest(
    earnings_df: pd.DataFrame,
    option_reader: OptionBarsReader,
    equity_reader: EquityBarsReader,
    option_type: Literal['C', 'P'] = 'C',
    bar_size: str = '5 mins',  # ← Changed default from '1 hour' to '5 mins'
    progress: bool = True,
    calculate_iv: bool = False
) -> pd.DataFrame:
```

**Why this works**:
- Existing fallback logic already handles bar_size not found
- Just changes the preference order
- Backward compatible (still works with hourly-only symbols)

### Testing Plan

1. **Rerun notebook 06 with `bar_size='5 mins'`**:
   ```python
   results_df = run_batch_calendar_spread_backtest(
       earnings_df=tradable_earnings,
       option_reader=option_reader,
       equity_reader=equity_reader,
       option_type='C',
       bar_size='5 mins',  # ← Changed
       progress=True,
       calculate_iv=True
   )
   ```

2. **Compare results**:
   - Number of successful backtests (should stay same or increase)
   - P&L values (may differ slightly due to different bar closes)
   - Entry/exit prices (should be more precise)

3. **Check bar_size column in results**:
   ```python
   # After backtest
   print(results_df['actual_bar_size'].value_counts())
   # Expected: mostly '5 mins', some '1 hour', few '1 day'
   ```

---

## Data Quality: 5-Min vs Hourly

### Coverage Analysis Needed

**Question**: Which symbols have 5-min vs hourly data?

**Query to check**:
```python
import duckdb
con = duckdb.connect()

coverage = con.execute("""
    SELECT
        underlying,
        bar_size,
        COUNT(DISTINCT expiry) as num_expirations,
        COUNT(DISTINCT strike) as num_strikes,
        COUNT(*) as total_bars
    FROM parquet_scan('./data_delta/options/option_bars_backfill/**/*.parquet',
                      hive_partitioning=true)
    WHERE underlying IN ('TMC', 'BZH', 'BNTC', 'DIS', 'AMAT')  -- Sample symbols
    GROUP BY underlying, bar_size
    ORDER BY underlying, bar_size
""").df()

print(coverage)
```

**Expected output**:
```
  underlying  bar_size  num_expirations  num_strikes  total_bars
0        TMC    5 mins                2            3       15000
1        BZH    5 mins                2            2       12000
2       BNTC    5 mins                3            2       18000
3        DIS   1 hour                 4            5        8000
4       AMAT   1 hour                 3            5        6000
```

### Why Different Bar Sizes?

**IB Historical Data API limitations**:

1. **5-min bars**: Available for recent, liquid options
   - Typically: expires < 90 days, high volume
   - Our earnings options: mostly qualify

2. **Hourly bars**: Fallback for less liquid or older data
   - Longer expirations (> 60 days)
   - Low volume strikes (far OTM/ITM)

3. **Daily bars**: Last resort
   - Very illiquid options
   - Historical data beyond 6 months

**Our backfill command requested 5-min**, so most symbols should have it.

---

## Price Realism Analysis: Why Examine Entry/Exit Hours?

### Context

Current backtest uses:
- **Entry**: `close` price from 3pm-4pm bar
- **Exit**: `close` price from 10am-11am or 4pm-5pm bar

### Question: Are These Prices Realistic?

**Concern**: `close` price may not be executable due to:
1. **Bid/ask spread**: Close might be mid-price, not executable
2. **Volume**: Low volume = hard to fill at close price
3. **Gaps**: Price may gap at open (especially after earnings)
4. **Timing**: Close is last second of hour, not a market order

### Analysis Needed (Step 7 - Price Realism Validation)

**For Entry (3pm-4pm hour)**:
```python
# Load 5-min bars for 3pm-4pm window
bars_3pm_to_4pm = option_reader.get_bars(
    underlying='TMC',
    expiry=date(2025, 11, 21),
    strike=5.0,
    right='C',
    bar_size='5 mins',
    start_date=date(2025, 11, 12),
    end_date=date(2025, 11, 12)
)

# Filter to 3pm-4pm
entry_window = bars_3pm_to_4pm[
    (bars_3pm_to_4pm['datetime'] >= '2025-11-12 15:00') &
    (bars_3pm_to_4pm['datetime'] < '2025-11-12 16:00')
]

# Analyze
print(entry_window[['datetime', 'open', 'close', 'high', 'low', 'volume']])
```

**Expected insights**:
- Did price move during hour? (compare first bar open to last bar close)
- What was total volume during hour?
- Estimate spread: (high - low) across 12 five-min bars
- Is 3pm hourly close representative of achievable price?

**For Exit (10am-11am or 4pm-5pm hour)**:
```python
# Similar analysis for exit window
# Key question: How much did price gap from 3pm day before?

pre_earnings_close = entry_window.iloc[-1]['close']  # 3pm close day before
post_earnings_open = exit_window.iloc[0]['open']     # 10am open after earnings

gap_pct = (post_earnings_open - pre_earnings_close) / pre_earnings_close * 100
print(f"Gap: {gap_pct:.2f}%")  # This is IV crush!
```

---

## CLI Command Specification: validate-prices

### Command Signature

```bash
dlt-ibapi validate-prices [OPTIONS]
```

### Parameters

**Required (one of)**:
- `--symbols SYMBOL [SYMBOL ...]`: List of symbols to analyze
  ```bash
  dlt-ibapi validate-prices --symbols TMC BZH BNTC
  ```

- `--date YYYY-MM-DD`: Analyze all symbols with earnings on this date
  ```bash
  dlt-ibapi validate-prices --date 2025-11-13
  ```

**Optional**:
- `--bar-size TEXT`: Bar size to use (default: "5 mins")
  ```bash
  dlt-ibapi validate-prices --date 2025-11-13 --bar-size "5 mins"
  ```

- `--output PATH`: Output CSV file (default: stdout or price_realism_YYYYMMDD.csv)
  ```bash
  dlt-ibapi validate-prices --date 2025-11-13 --output ./reports/realism.csv
  ```

- `--database-path PATH`: Path to data directory (default: "./data_delta")
- `--dataset-options TEXT`: Options dataset name (default: "options")
- `--dataset-stocks TEXT`: Stocks dataset name (default: "stocks")
- `--dataset-earnings TEXT`: Earnings dataset name (default: "earnings")

- `--spread-assumption TEXT`: Spread calculation method (default: "conservative")
  - `conservative`: (high - low) / 4 or 5% of close
  - `tight`: (high - low) / 8 or 2% of close
  - `actual`: Use bid/ask columns if available

### Examples

**Example 1**: Analyze specific symbols
```bash
dlt-ibapi validate-prices \
  --symbols TMC BZH BNTC DIS AMAT \
  --bar-size "5 mins" \
  --output tmb_price_analysis.csv
```

**Example 2**: Analyze all symbols from earnings date
```bash
dlt-ibapi validate-prices \
  --date 2025-11-13 \
  --spread-assumption conservative \
  --output ./reports/2025-11-13_realism.csv
```

**Example 3**: Quick check on single symbol
```bash
dlt-ibapi validate-prices --symbols TMC
# Outputs to stdout (can pipe to other commands)
```

### Output Format

**CSV columns**:
```
symbol,strike,option_type,short_expiry,long_expiry,
entry_time,entry_bar_size,
short_entry_open,short_entry_close,short_entry_volume,short_entry_spread_est,
long_entry_open,long_entry_close,long_entry_volume,long_entry_spread_est,
exit_time,exit_bar_size,
short_exit_open,short_exit_close,short_exit_volume,short_exit_spread_est,
long_exit_open,long_exit_close,long_exit_volume,long_exit_spread_est,
short_gap_pct,long_gap_pct,iv_crush_differential,
pnl_original,pnl_conservative,pnl_realistic,pnl_degradation_pct,
entry_realistic,exit_realistic,tradeable,liquidity_score,execution_risk
```

**Example output**:
```csv
symbol,strike,option_type,short_expiry,long_expiry,entry_time,short_entry_close,short_entry_volume,short_gap_pct,long_gap_pct,iv_crush_differential,pnl_original,pnl_conservative,tradeable
TMC,5.0,C,2025-11-21,2025-11-28,2025-11-12 15:00,0.75,150,-15.2,-8.3,-6.9,5.0,2.5,True
BZH,22.0,C,2025-11-21,2025-12-19,2025-11-12 15:00,1.25,45,-12.1,-7.8,-4.3,40.0,28.0,True
BNTC,15.0,C,2025-12-19,2026-01-16,2025-11-12 15:00,3.50,8,-18.5,-14.2,-4.3,0.0,-15.0,False
```

### Business Logic

```python
def validate_prices(
    symbols: List[str],
    date: Optional[date],
    bar_size: str = '5 mins',
    database_path: str = './data_delta',
    spread_assumption: str = 'conservative'
) -> pd.DataFrame:
    """
    Validate price realism for calendar spread backtests.

    Steps:
    1. Load successful backtests for symbols/date
    2. For each position:
       a. Load entry hour bars (3pm-4pm day before)
       b. Load exit hour bars (10am-11am or 4pm-5pm after earnings)
       c. Extract OHLCV for both legs (short + long)
       d. Calculate spreads, gaps, volumes
       e. Estimate adjusted P&L with spreads
       f. Score liquidity and execution risk
    3. Return DataFrame with all metrics
    """
    # Implementation follows SPECS_PRICE_REALISM_ANALYSIS.md
    pass
```

---

## Integration with Existing Workflow

### Current Workflow (Steps 1-6)
1. Load earnings calendar
2. Resolve equity contracts
3. Capture option snapshots
4. Backfill equity bars
5. Resolve option contracts
6. Backfill option bars ← **We are here**

### New Step 7 (Price Realism Validation)

**Inputs**:
- Successful backtest results (from notebook 06 or similar)
- Option bars data (from Step 6)
- Equity bars data (from Step 4)
- Earnings calendar (from Step 1)

**Process**:
1. Run calendar spread backtest (notebook 06)
2. Export successful backtests to CSV or use in-memory DataFrame
3. Run `validate-prices` CLI:
   ```bash
   dlt-ibapi validate-prices --date 2025-11-13 --output validation.csv
   ```
4. Load validation results into notebook for analysis

**Outputs**:
- CSV report with realism metrics
- Filtered tradeable subset
- Adjusted P&L estimates

---

## Next Steps

### Immediate Actions

1. **✅ DONE**: Document current data acquisition (this file)
2. **✅ DONE**: Document specs for price realism analysis
3. **⚠️ TODO**: Test 5-min bars in backtest (change `bar_size='5 mins'`)
4. **⚠️ TODO**: Compare 5-min vs hourly backtest results
5. **⚠️ TODO**: Implement `validate-prices` CLI command
6. **⚠️ TODO**: Create notebook 07 with price realism analysis
7. **⚠️ TODO**: Update strategy to prefer 5-min bars by default

### Future Enhancements

1. **Bid/ask data**: Investigate if IB provides bid/ask in historical bars
   - Check existing parquet columns
   - If not, consider requesting via `whatToShow='BID_ASK'`

2. **Tick data**: For ultra-precise analysis
   - IB provides tick-by-tick data (requires separate API calls)
   - Very granular but much larger dataset

3. **Real-time validation**: Run price realism check during backfill
   - Flag illiquid contracts immediately
   - Skip backfill for known bad contracts

---

## Summary

### What We Have
- **5-minute option bars** for 44 earnings symbols
- High-quality data with OHLCV
- Flexible aggregation (can create hourly/daily from 5-min)

### Why Strategy Uses Hourly
- **Historical reason**: Initially developed with hourly data
- **Compatibility**: Works across all symbols (some only have hourly)
- **Not optimal**: Should prefer 5-min when available

### Action Items
1. Update backtest to use 5-min bars by default
2. Implement price realism validation CLI
3. Analyze entry/exit hour price movements
4. Calculate adjusted P&L with spread costs
5. Identify tradeable subset based on volume/spread criteria

### Key Insight
**We have better data (5-min) than we're currently using (hourly)**. The strategy should leverage this for more precise entry/exit timing and better spread/volume analysis.
