# Price Realism Analysis - Technical Specifications

## Executive Summary

**Goal**: Verify that the option prices used in calendar spread backtests are realistic and executable by examining actual bid/ask spreads, volume, and price movements around earnings announcements.

**Problem**: Current backtests use `close` prices from hourly bars, which may not reflect actual execution prices due to:
- Wide bid/ask spreads (especially for illiquid options)
- Price gaps at market open after earnings
- Unrealistic fills at "close" price when volume is low

**Solution**: Analyze trades at open and close for the hour containing earnings to understand:
1. How prices react to earnings announcements
2. Whether our assumed entry/exit prices are realistic
3. Impact of bid/ask spreads on actual P&L

---

## Scope

### In Scope
1. **Entry Analysis** (3pm day before earnings):
   - Open/close prices for entry hour (3pm-4pm)
   - Bid/ask spreads at 3pm
   - Volume during entry hour
   - Price movement during hour (volatility)

2. **Exit Analysis** (after earnings):
   - Open/close prices for exit hour
   - PRE_MARKET earnings: 4pm-5pm on earnings day
   - AFTER_HOURS earnings: 10am-11am day after earnings
   - Bid/ask spreads at exit time
   - Volume during exit hour
   - Gap from previous close to open (IV crush visualization)

3. **Spread Impact**:
   - Calculate effective entry/exit costs with bid/ask
   - Worst case: buy at ask, sell at bid
   - Best case: buy at bid, sell at ask (unlikely)
   - Realistic case: mid-price or slightly worse

4. **Volume Analysis**:
   - Identify illiquid contracts (low volume)
   - Flag positions where execution may be difficult
   - Quantify slippage risk

### Out of Scope
- Intraday tick data (not available in hourly bars)
- Market maker quotes (require live data feed)
- Order book depth analysis
- Impact of position size on execution

---

## Data Requirements

### Current Data Available
From `option_bars_backfill` table:
- `datetime`: Hourly bar timestamp
- `open`, `high`, `low`, `close`: OHLC prices
- `volume`: Contracts traded
- `underlying`, `expiry`, `strike`, `right`: Contract identifiers

### Additional Data Needed
**CRITICAL**: Need to verify if IB historical data includes bid/ask:
- `bid`: Bid price at bar close
- `ask`: Ask price at bar close
- `bid_size`, `ask_size`: Optional (nice to have)

**Action Required**:
1. Check if existing backfilled data has bid/ask columns
2. If not, need to re-backfill with `whatToShow='BID_ASK'` or `'TRADES'`
3. Alternative: Use spread estimation based on volume (less accurate)

---

## Analysis Components

### Component 1: Entry Hour Analysis

**Purpose**: Verify 3pm entry price is realistic

**Steps**:
1. For each successful backtest in results_df:
   - Load option bars for entry hour (3pm-4pm day before earnings)
   - Extract: `entry_hour_open`, `entry_hour_close`, `entry_hour_high`, `entry_hour_low`
   - Calculate: `entry_hour_range = high - low` (intraday volatility)
   - Extract: `entry_hour_volume`

2. Calculate metrics:
   - `entry_price_used` = close at 3pm (current backtest assumption)
   - `entry_hour_midpoint` = (high + low) / 2
   - `entry_price_deviation` = abs(entry_price_used - entry_hour_midpoint)
   - `entry_spread_estimate` = (ask - bid) if available, else (high - low) / 4

3. Flag unrealistic entries:
   - `low_volume_entry` = volume < 10 contracts
   - `wide_spread_entry` = spread_estimate / close > 0.05 (>5% spread)

**Output**: DataFrame with columns:
```
symbol, strike, expiry, entry_time,
short_leg_entry_open, short_leg_entry_close, short_leg_entry_volume, short_leg_entry_spread,
long_leg_entry_open, long_leg_entry_close, long_leg_entry_volume, long_leg_entry_spread,
entry_hour_range_short, entry_hour_range_long,
entry_realistic (bool)
```

---

### Component 2: Exit Hour Analysis

**Purpose**: Verify post-earnings exit price is realistic and quantify IV crush

**Steps**:
1. For each successful backtest:
   - Identify exit hour based on earnings_time:
     - AFTER_HOURS: 10am-11am day after earnings
     - PRE_MARKET: 4pm-5pm on earnings day
   - Load option bars for exit hour
   - Extract: `exit_hour_open`, `exit_hour_close`, `exit_hour_high`, `exit_hour_low`
   - Extract: `exit_hour_volume`

2. Calculate gap and IV crush:
   - `pre_earnings_close` = close price at 3pm day before
   - `post_earnings_open` = open price at exit hour
   - `gap_amount` = post_earnings_open - pre_earnings_close
   - `gap_pct` = gap_amount / pre_earnings_close * 100
   - `iv_crush_proxy` = (pre_earnings_close - post_earnings_open) / pre_earnings_close

3. Calculate exit realism:
   - `exit_price_used` = close at exit hour
   - `exit_hour_midpoint` = (high + low) / 2
   - `exit_spread_estimate` = (ask - bid) if available

4. Flag unrealistic exits:
   - `low_volume_exit` = volume < 10 contracts
   - `wide_spread_exit` = spread_estimate / close > 0.05

**Output**: DataFrame with columns:
```
symbol, strike, expiry, exit_time, earnings_time,
short_leg_exit_open, short_leg_exit_close, short_leg_exit_volume, short_leg_exit_spread,
long_leg_exit_open, long_leg_exit_close, long_leg_exit_volume, long_leg_exit_spread,
short_leg_gap_pct, long_leg_gap_pct,
iv_crush_differential (short_gap - long_gap),
exit_realistic (bool)
```

---

### Component 3: Adjusted P&L with Spreads

**Purpose**: Calculate realistic P&L accounting for bid/ask spreads

**Steps**:
1. For each backtest, calculate adjusted costs:

   **Entry (buy calendar spread = buy long, sell short)**:
   - `short_leg_entry_realistic` = bid price (we sell at bid)
   - `long_leg_entry_realistic` = ask price (we buy at ask)
   - `entry_cost_realistic` = long_ask - short_bid
   - `entry_slippage` = entry_cost_realistic - entry_cost_original

   **Exit (sell calendar spread = sell long, buy back short)**:
   - `long_leg_exit_realistic` = bid price (we sell at bid)
   - `short_leg_exit_realistic` = ask price (we buy at ask)
   - `spread_value_realistic` = long_bid - short_ask
   - `exit_slippage` = spread_value_realistic - spread_value_original

2. Calculate adjusted P&L:
   - `pnl_realistic` = spread_value_realistic - entry_cost_realistic
   - `pnl_degradation` = pnl_original - pnl_realistic
   - `pnl_degradation_pct` = pnl_degradation / pnl_original * 100

**Output**: DataFrame with columns:
```
symbol, strike,
pnl_original, pnl_realistic, pnl_degradation,
entry_slippage, exit_slippage, total_slippage,
execution_quality (good/acceptable/poor)
```

---

### Component 4: Volume and Liquidity Scoring

**Purpose**: Quantify execution risk based on volume

**Steps**:
1. Calculate volume metrics:
   - `entry_hour_total_volume` = short_volume + long_volume at entry
   - `exit_hour_total_volume` = short_volume + long_volume at exit
   - `min_leg_volume` = min(short_volume, long_volume)

2. Liquidity scoring:
   ```python
   def liquidity_score(volume):
       if volume >= 100: return 'high'
       elif volume >= 50: return 'medium'
       elif volume >= 10: return 'low'
       else: return 'very_low'
   ```

3. Flag illiquid trades:
   - `illiquid_entry` = entry_hour_total_volume < 20
   - `illiquid_exit` = exit_hour_total_volume < 20
   - `execution_risk` = 'high' if illiquid, 'medium' if low volume, 'low' otherwise

**Output**: DataFrame with columns:
```
symbol, strike,
entry_volume_score, exit_volume_score,
min_volume_leg, execution_risk,
tradeable (bool - based on minimum volume threshold)
```

---

## Implementation Plan

### Phase 1: Data Preparation
**Estimated Time**: 1 hour

1. **Check existing data for bid/ask**:
   ```python
   import duckdb
   con = duckdb.connect()
   result = con.execute("""
       SELECT * FROM parquet_scan('./data_delta/options/**/*.parquet', hive_partitioning=true)
       LIMIT 1
   """).df()
   print(result.columns)  # Check if 'bid', 'ask' exist
   ```

2. **If bid/ask missing**:
   - Document assumption: estimate spread as `(high - low) / 4`
   - Or: Use conservative spread estimate of 5% of close price
   - Or: Re-backfill subset with BID_ASK data (time-intensive)

3. **Create helper function**:
   ```python
   def get_option_bar_details(
       option_reader,
       underlying, expiry, strike, right, bar_size,
       target_time
   ):
       """Get OHLC, volume, bid/ask for specific bar."""
       # Implementation
       return {
           'open': ...,
           'high': ...,
           'low': ...,
           'close': ...,
           'volume': ...,
           'bid': ...,  # or None
           'ask': ...,  # or None
       }
   ```

---

### Phase 2: Entry Analysis Implementation
**Estimated Time**: 2 hours

1. **Create entry analysis function**:
   ```python
   def analyze_entry_hour(
       results_df: pd.DataFrame,
       option_reader: OptionBarsReader,
       equity_reader: EquityBarsReader
   ) -> pd.DataFrame:
       """
       For each backtest, analyze entry hour (3pm-4pm day before earnings).

       Returns: DataFrame with entry hour details
       """
       entry_analysis = []

       for idx, row in results_df.iterrows():
           # Get entry time from backtest
           entry_time = row['entry_time']  # datetime at 3pm

           # Load short leg entry bar
           short_bar = get_option_bar_details(
               option_reader,
               underlying=row['symbol'],
               expiry=row['short_expiry'],
               strike=row['strike'],
               right=row['option_type'],
               bar_size='1 hour',
               target_time=entry_time
           )

           # Load long leg entry bar
           long_bar = get_option_bar_details(...)

           # Calculate metrics
           entry_analysis.append({
               'symbol': row['symbol'],
               'strike': row['strike'],
               'entry_time': entry_time,
               'short_leg_entry_open': short_bar['open'],
               'short_leg_entry_close': short_bar['close'],
               'short_leg_entry_volume': short_bar['volume'],
               'short_leg_entry_spread': short_bar.get('ask', short_bar['high']) - short_bar.get('bid', short_bar['low']),
               # ... similar for long leg
               'entry_realistic': short_bar['volume'] >= 10 and long_bar['volume'] >= 10
           })

       return pd.DataFrame(entry_analysis)
   ```

2. **Test with sample data**:
   - Run on TMC, BZH, BNTC (known working backtests)
   - Verify bar loading works
   - Check output format

---

### Phase 3: Exit Analysis Implementation
**Estimated Time**: 2 hours

1. **Create exit analysis function**:
   ```python
   def analyze_exit_hour(
       results_df: pd.DataFrame,
       option_reader: OptionBarsReader
   ) -> pd.DataFrame:
       """
       For each backtest, analyze exit hour after earnings.

       Returns: DataFrame with exit hour details and IV crush metrics
       """
       exit_analysis = []

       for idx, row in results_df.iterrows():
           exit_time = row['exit_time']
           entry_time = row['entry_time']

           # Get pre-earnings close (3pm day before)
           short_entry_bar = get_option_bar_details(...)
           long_entry_bar = get_option_bar_details(...)

           # Get post-earnings open/close (exit hour)
           short_exit_bar = get_option_bar_details(...)
           long_exit_bar = get_option_bar_details(...)

           # Calculate gaps
           short_gap_pct = (short_exit_bar['open'] - short_entry_bar['close']) / short_entry_bar['close'] * 100
           long_gap_pct = (long_exit_bar['open'] - long_entry_bar['close']) / long_entry_bar['close'] * 100

           exit_analysis.append({
               'symbol': row['symbol'],
               'strike': row['strike'],
               'exit_time': exit_time,
               'short_leg_gap_pct': short_gap_pct,
               'long_leg_gap_pct': long_gap_pct,
               'iv_crush_differential': short_gap_pct - long_gap_pct,  # Key metric!
               # ... volume, spreads
           })

       return pd.DataFrame(exit_analysis)
   ```

2. **Visualization**:
   - Scatter plot: short_gap_pct vs long_gap_pct
   - Histogram: iv_crush_differential distribution
   - Identify: Which leg decays more (should be short)

---

### Phase 4: Adjusted P&L Calculation
**Estimated Time**: 1.5 hours

1. **Create adjusted P&L function**:
   ```python
   def calculate_adjusted_pnl(
       results_df: pd.DataFrame,
       entry_analysis: pd.DataFrame,
       exit_analysis: pd.DataFrame,
       spread_assumption: str = 'conservative'  # 'conservative', 'realistic', 'optimistic'
   ) -> pd.DataFrame:
       """
       Calculate P&L accounting for bid/ask spreads.

       spread_assumption:
       - 'conservative': buy at ask, sell at bid (worst case)
       - 'realistic': use mid-price or estimated spread
       - 'optimistic': use close price (current backtest)
       """
       adjusted = []

       for idx, row in results_df.iterrows():
           entry_data = entry_analysis[entry_analysis['symbol'] == row['symbol']].iloc[0]
           exit_data = exit_analysis[exit_analysis['symbol'] == row['symbol']].iloc[0]

           if spread_assumption == 'conservative':
               # Entry: buy long at ask, sell short at bid
               long_entry = entry_data['long_leg_entry_close'] + entry_data['long_leg_entry_spread']/2
               short_entry = entry_data['short_leg_entry_close'] - entry_data['short_leg_entry_spread']/2
               entry_cost = long_entry - short_entry

               # Exit: sell long at bid, buy short at ask
               long_exit = exit_data['long_leg_exit_close'] - exit_data['long_leg_exit_spread']/2
               short_exit = exit_data['short_leg_exit_close'] + exit_data['short_leg_exit_spread']/2
               spread_value = long_exit - short_exit

           pnl_adjusted = spread_value - entry_cost
           pnl_degradation = row['pnl_per_contract'] - (pnl_adjusted * 100)

           adjusted.append({
               'symbol': row['symbol'],
               'pnl_original': row['pnl_per_contract'],
               'pnl_adjusted': pnl_adjusted * 100,
               'pnl_degradation': pnl_degradation,
               'pnl_degradation_pct': pnl_degradation / row['pnl_per_contract'] * 100 if row['pnl_per_contract'] != 0 else 0
           })

       return pd.DataFrame(adjusted)
   ```

---

### Phase 5: Reporting and Visualization
**Estimated Time**: 2 hours

1. **Create comprehensive report**:
   ```python
   def generate_price_realism_report(
       results_df,
       entry_analysis,
       exit_analysis,
       adjusted_pnl
   ):
       """
       Generate summary statistics and visualizations.
       """
       report = {
           'summary_stats': {
               'total_backtests': len(results_df),
               'realistic_entries': (entry_analysis['entry_realistic']).sum(),
               'realistic_exits': (exit_analysis['exit_realistic']).sum(),
               'tradeable_count': ...,
               'avg_pnl_degradation': adjusted_pnl['pnl_degradation'].mean(),
               'median_entry_volume': entry_analysis['short_leg_entry_volume'].median(),
               'median_exit_volume': exit_analysis['short_leg_exit_volume'].median(),
           },
           'volume_breakdown': {
               'high_liquidity': ...,
               'medium_liquidity': ...,
               'low_liquidity': ...,
               'very_low_liquidity': ...
           },
           'spread_impact': {
               'avg_entry_spread_pct': ...,
               'avg_exit_spread_pct': ...,
               'max_spread_encountered': ...
           }
       }

       return report
   ```

2. **Visualizations to create**:
   - Entry volume distribution (histogram)
   - Exit volume distribution (histogram)
   - Gap analysis (short vs long) scatter plot
   - P&L degradation by volume quartile (box plot)
   - IV crush differential distribution (histogram)
   - Entry/exit spread impact on P&L (scatter)

---

## Notebook Structure

### Notebook: `07_price_realism_analysis.ipynb`

**Sections**:

1. **Introduction**
   - Why price realism matters
   - Assumptions in current backtest
   - What we're validating

2. **Setup and Data Loading**
   - Load results from notebook 06
   - Initialize readers
   - Load option bars for analysis

3. **Entry Hour Analysis**
   - Implementation
   - Results table
   - Volume/spread statistics
   - Flags for unrealistic entries

4. **Exit Hour Analysis**
   - Implementation
   - Results table
   - IV crush visualization (gap analysis)
   - Volume/spread statistics

5. **Adjusted P&L Calculation**
   - Conservative vs optimistic scenarios
   - P&L degradation analysis
   - Impact by liquidity tier

6. **Findings and Recommendations**
   - Which backtests are tradeable?
   - Expected P&L after adjustments
   - Minimum volume/spread criteria
   - Strategy refinements

---

## Success Criteria

### Validation Checks
- [ ] All 26 successful backtests analyzed
- [ ] Entry hour data loaded for all positions (short + long legs)
- [ ] Exit hour data loaded for all positions
- [ ] Volume data available for all bars
- [ ] Spread estimates calculated (real or estimated)

### Analysis Completeness
- [ ] Entry realism flags generated
- [ ] Exit realism flags generated
- [ ] Adjusted P&L calculated for 3 scenarios (conservative/realistic/optimistic)
- [ ] IV crush differential quantified
- [ ] Liquidity scoring applied

### Reporting
- [ ] Summary statistics table created
- [ ] 6+ visualizations generated
- [ ] Tradeable subset identified (realistic execution)
- [ ] Recommendations documented

---

## Key Metrics to Track

### Entry Metrics
- `entry_hour_volume_total`: Sum of short + long leg volumes
- `entry_spread_pct`: Estimated spread as % of close
- `entry_price_realistic`: Boolean flag

### Exit Metrics
- `exit_hour_volume_total`: Sum of short + long leg volumes
- `exit_spread_pct`: Estimated spread as % of close
- `short_leg_gap_pct`: (exit_open - entry_close) / entry_close
- `long_leg_gap_pct`: (exit_open - entry_close) / entry_close
- `iv_crush_differential`: short_gap - long_gap (should be negative)

### P&L Adjustment
- `pnl_original`: Current backtest P&L
- `pnl_conservative`: P&L with worst-case spreads
- `pnl_realistic`: P&L with mid-price execution
- `pnl_degradation_pct`: % loss due to spreads
- `tradeable`: Boolean (volume > threshold AND spread < threshold)

---

## Dependencies

### Python Libraries
- `pandas`: Data manipulation
- `duckdb`: Option bars queries
- `matplotlib`, `seaborn`: Visualizations
- `dlt_ibapi.repositories`: OptionBarsReader, EquityBarsReader

### Data Requirements
- Successful backtests from notebook 06 (26 positions)
- Hourly option bars with OHLCV (+ bid/ask if available)
- Earnings times (PRE_MARKET vs AFTER_HOURS) from EarningsCalendarReader

---

## Risks and Mitigations

### Risk 1: Missing Bid/Ask Data
**Impact**: Can't calculate precise spreads
**Mitigation**: Use conservative estimates (high-low range / 4) or assume 5% spread

### Risk 2: Missing Volume Data
**Impact**: Can't assess liquidity
**Mitigation**: Flag as "unknown liquidity risk" and exclude from tradeable subset

### Risk 3: Hourly Bars Don't Capture Exact Entry/Exit
**Impact**: May miss precise open/close at 3pm or 10am
**Mitigation**: Use closest available bar, document timestamp uncertainty

### Risk 4: Low Sample Size (26 backtests)
**Impact**: Statistics may not be robust
**Mitigation**: Present findings as "preliminary" and recommend expanding dataset

---

## Expected Outcomes

1. **Validation of Current Approach**:
   - X% of backtests have realistic entry prices
   - Y% have realistic exit prices
   - Z% are tradeable (both entry and exit realistic)

2. **Adjusted Performance Metrics**:
   - Mean P&L: $77 → $? (conservative)
   - Win rate: 57.7% → ?%
   - Median P&L: $2.50 → $?

3. **Liquidity Insights**:
   - Distribution of volume at entry/exit
   - Correlation between volume and P&L reliability
   - Minimum volume threshold for tradeable positions

4. **IV Crush Quantification**:
   - Average gap in short leg: X%
   - Average gap in long leg: Y%
   - Differential (edge from calendar spread): Z%

5. **Strategy Refinements**:
   - Filter criteria: min volume, max spread
   - Expected slippage per trade
   - Revised backtest assumptions
