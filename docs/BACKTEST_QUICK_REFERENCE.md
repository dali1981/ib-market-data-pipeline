# Backtest Quick Reference

Fast reference for backtesting calendar spreads with `dlt-ibapi`.

## TL;DR - Can I Backtest Calendar Spreads?

**YES ✅** - Everything is ready:
- ✅ Backtest engine exists (`OptionsBacktestRunner`)
- ✅ Calendar spread strategies implemented (generic, pre-earnings, IV-based)
- ✅ Data collection tools work (snapshot, backfill, load-earnings)
- ✅ Greeks calculated automatically from option prices
- ✅ CLI command ready: `dlt-ibapi backtest-earnings-spreads`

---

## Data You Need

| Data | Collection Method | Required For |
|------|-------------------|--------------|
| Earnings Calendar | `load-earnings` | Entry/exit timing |
| Option Chain Snapshots | `snapshot` | Available strikes/expirations |
| Option Bars (OHLCV) | `backfill-options` | Option pricing |
| Equity Bars (OHLCV) | `backfill-equity` | Underlying prices |
| Greeks | Automatic | Calculated from prices |

**Greeks:** NOT stored - calculated on-the-fly from option prices using Black-Scholes.

---

## Quick Start (5 Steps)

### 1. Load Earnings
```bash
dlt-ibapi load-earnings earnings_2025-11-13.json \
  --start-date 2025-11-13 \
  --end-date 2025-12-31
```

### 2. Resolve Contracts
```bash
dlt-ibapi resolve-contracts --earnings-date 2025-11-13
```

### 3. Snapshot Option Chains
```bash
dlt-ibapi snapshot --earnings-date 2025-11-13 \
  --min-dte 7 --max-dte 60
```

### 4. Backfill Equity & Option Bars
```bash
# Equity bars (batch mode - all earnings symbols)
dlt-ibapi backfill-equity --earnings-date 2025-11-13 \
  --start 2025-01-01 --end 2025-11-13

# Option bars (batch mode - auto spot prices, all expirations for vol curve)
dlt-ibapi backfill-options --earnings-date 2025-11-13 \
  --start 2025-01-01 --end 2025-11-13 \
  --mode atm --k-strikes 5 \
  --k-expirations 6  # Optional: limit to 6 closest expirations beyond earnings
```

**What happens:**
- **Equity**: Loads all symbols from earnings calendar, backfills their bars
- **Options**:
  - Loads symbols from earnings calendar
  - Auto-extracts spot prices from equity bars (latest close)
  - Discovers expirations from snapshots
  - Filters to expirations AFTER earnings date
  - Backfills option bars for all valid (symbol, expiration, strike) combinations
  - Use `--k-expirations` to limit number of expirations (optional)

### 5. Run Backtest
```bash
dlt-ibapi backtest-earnings-spreads \
  --strategy iv_based \
  --symbols AAPL MSFT GOOGL \
  --start-date 2024-01-01 \
  --end-date 2024-12-31 \
  --capital 100000
```

---

## Strategy Options

### 1. Generic Calendar
```bash
--strategy generic_calendar
```
- Entry: Anytime (no earnings timing)
- Exit: Profit target or stop loss

### 2. Pre-Earnings Calendar
```bash
--strategy pre_earnings
```
- Entry: 10-25 days before earnings
- Exit: 2 days before announcement

### 3. IV-Based Calendar (Recommended)
```bash
--strategy iv_based
```
- Entry: 10-25 days before + IV filters
  - Requires normal term structure (back IV > front IV)
  - Only enters when IV < median
- Exit: 2 days before announcement

---

## Output Files

```
./backtest_results/
  summary_iv_based_2024-01-01_2024-12-31.json     # Metrics
  equity_curve_iv_based_2024-01-01_2024-12-31.csv # Daily values
  equity_curve_iv_based_2024-01-01_2024-12-31.png # Chart
  trades_iv_based_2024-01-01_2024-12-31.csv       # Trade log
```

---

## Key Metrics

```json
{
  "total_return_pct": 15.0,    // Overall gain/loss
  "win_rate": 66.7,            // % profitable trades
  "profit_factor": 2.14,       // Gross profit / Gross loss
  "max_drawdown_pct": -7.5,    // Largest decline
  "sharpe_ratio": 1.25,        // Risk-adjusted return
  "num_trades": 45             // Total trades
}
```

---

## Troubleshooting

### "No option bars found"
```bash
# Single symbol mode - increase strike range
dlt-ibapi backfill-options AAPL 180.0 \
  --k-strikes 7 \  # Wider range
  --max-dte 75     # Longer expirations

# Earnings batch mode - increase expiration limit
dlt-ibapi backfill-options --earnings-date 2025-11-13 \
  --k-expirations 10 \  # More expirations
  --k-strikes 7         # Wider strike range
```

### "No earnings events found"
```bash
# Check earnings data
dlt-ibapi list-earnings --days-ahead 365

# Reload if needed
dlt-ibapi load-earnings earnings.json
```

### "Validation shows low coverage"
- Missing snapshots: Cannot backfill (must collect real-time)
- Missing option bars: Backfill if still available
- Focus on dates where you have complete data

---

## Best Practices

1. **Start small:** 1 symbol, 1 month
   ```bash
   dlt-ibapi backtest-earnings-spreads \
     --symbols AAPL \
     --start-date 2024-11-01 \
     --end-date 2024-11-30
   ```

2. **Use liquid stocks:** AAPL, MSFT, GOOGL, AMZN, TSLA

3. **Always validate:**
   ```python
   result = runner.run(validate_data=True)  # Pre-flight check
   ```

4. **Collect data regularly:** Daily cron for snapshots + backfills

---

## Python API (Advanced)

```python
from datetime import date
from dlt_ibapi.backtest import IBBacktestDataProvider, OptionsBacktestRunner
from tools.strategies.options import IVBasedCalendarSpreadStrategy, IVBasedConfig

# Initialize
data_provider = IBBacktestDataProvider("./data")
strategy = IVBasedCalendarSpreadStrategy(config, earnings_provider)

# Run
runner = OptionsBacktestRunner(strategy, data_provider, initial_capital=100000)
result = runner.run(
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31),
    validate_data=True,
)

# Analyze
print(f"Return: {result.total_return_pct:.2f}%")
print(f"Win Rate: {result.win_rate:.1f}%")
```

---

## What's Missing (Not Critical)

- ❌ Open Interest (not in IB historical data)
- ❌ Bid/Ask Spreads (uses mid prices)
- ❌ Historical IV Surface (calculated on-demand)

**Workarounds:**
- Use volume as proxy for liquidity
- Add commissions to model slippage ($0.65/contract)
- Greeks calculated from market prices (accurate enough)

---

## Data Volume (Estimates)

For **3 symbols, 12 months:**

- Earnings: 5 MB
- Option Chains: 50 MB
- Option Bars: 500 MB - 2 GB
- Equity Bars: 5 MB

**Total:** ~1-3 GB

---

## Learn More

- **Full Guide:** [CALENDAR_SPREAD_BACKTEST_GUIDE.md](./CALENDAR_SPREAD_BACKTEST_GUIDE.md)
- **Earnings Workflow:** [EARNINGS_SNAPSHOT_WORKFLOW.md](./EARNINGS_SNAPSHOT_WORKFLOW.md)
- **API Reference:** [API_REFERENCE.md](./API_REFERENCE.md)
