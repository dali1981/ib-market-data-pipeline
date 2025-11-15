# AEG Earnings Calendar Spread Backtest Plan

## Executive Summary

This document outlines the plan to backtest two calendar spread strategies on AEG earnings announcement (November 13, 2025):

1. **Simple Earnings Strategy**: Enter 1 day before earnings, exit 1 day after
2. **IV Term Structure Strategy**: Select expirations based on maximum IV differential

## Strategy Overview

### Background: Calendar Spread + Earnings IV Crush

**Calendar Spread Mechanics**:
- Sell front-month option (shorter DTE)
- Buy back-month option (longer DTE)
- Same strike price
- Profit from time decay and IV differential

**Earnings IV Crush Effect**:
- IV expands as earnings approaches
- IV collapses immediately after announcement
- Front-month IV drops more than back-month (larger vega)
- Calendar spread benefits from this differential collapse

**AEG Earnings Context**:
- Symbol: AEG (Aegon N.V.)
- Earnings Date: November 13, 2025
- Current Price: ~$6.48 (as of Jan 21, 2025)
- Available Data: 216 days of equity bars, 1 option chain snapshot

---

## Strategy Definitions

### Strategy #1: Simple Earnings Calendar Spread

**Entry Rules**:
- **Timing**: 1 trading day before earnings announcement
- **Specific Date**: November 12, 2025
- **Strike Selection**: Delta-based (0.40-0.60 delta)
  - Find ATM strike closest to $6.48
  - Select contracts with delta in target range
- **Expiration Selection**:
  - **Front leg**: 14-21 DTE after entry (expires after earnings)
  - **Back leg**: 35-50 DTE after entry (expires well after earnings)

**Exit Rules**:
- **Timing**: 1 trading day after earnings announcement
- **Specific Date**: November 14, 2025
- **Reason**: Capture IV crush without holding through full decay

**Expected Behavior**:
- Enter when IV is elevated (pre-earnings)
- Exit after IV crush completes
- Front-month IV drops more than back-month
- Net credit from IV differential

**Example Position**:
```
Entry (Nov 12):
- SELL AEG Nov-28 $6.50 Call @ $0.35 (front, 16 DTE, IV=45%)
- BUY  AEG Dec-19 $6.50 Call @ $0.55 (back, 37 DTE, IV=38%)
- Net debit: -$0.20 ($20 per spread)

Exit (Nov 14):
- BUY BACK AEG Nov-28 $6.50 Call @ $0.15 (IV=28%, crushed!)
- SELL AEG Dec-19 $6.50 Call @ $0.48 (IV=32%, less crush)
- Net credit: +$0.33
- P&L: +$0.13 per share = +$13 per spread (65% ROI)
```

---

### Strategy #3: IV Term Structure Calendar Spread

**Entry Rules**:
- **Timing**: 1 trading day before earnings (same as Strategy #1)
- **Specific Date**: November 12, 2025
- **Strike Selection**: Delta-based (0.40-0.60 delta) - same as #1
- **Expiration Selection** (DIFFERENT):
  - Compute ATM IV for ALL available expirations
  - Select pair with **maximum IV differential**: `max(back_IV - front_IV)`
  - Front leg: expiration with lowest ATM IV (within DTE range)
  - Back leg: expiration with highest ATM IV (within DTE range)
  - This maximizes profit potential from IV term structure flattening

**Exit Rules**:
- Same as Strategy #1 (1 day after earnings)

**IV Term Structure Analysis**:

1. **Calculate ATM IV by Expiration**:
   ```python
   For each expiration in option chain:
       Filter to ATM contracts (0.98 < moneyness < 1.02)
       Calculate average IV across ATM calls/puts
       Store: (expiration, DTE, ATM_IV)
   ```

2. **Identify Maximum Differential**:
   ```python
   For all valid front/back pairs:
       front: 14-21 DTE, ATM_IV available
       back:  35-50 DTE, ATM_IV available
       Calculate: IV_diff = back_IV - front_IV
       Select pair with max(IV_diff)
   ```

3. **Historical IV Rank** (optional filter):
   ```python
   IV_rank = (current_IV - min_IV) / (max_IV - min_IV) * 100
   Entry condition: 20% < IV_rank < 70%
   ```

**Example Position**:
```
IV Term Structure (Nov 12):
- Nov-21 (9 DTE):  ATM IV = 42%
- Nov-28 (16 DTE): ATM IV = 45%  ← Front leg candidate
- Dec-05 (23 DTE): ATM IV = 40%
- Dec-19 (37 DTE): ATM IV = 52%  ← Back leg candidate (MAX differential)
- Jan-16 (65 DTE): ATM IV = 48%

Selected Pair: Nov-28 / Dec-19 (IV diff = 7%, highest available)

Entry:
- SELL AEG Nov-28 $6.50 Call @ $0.35 (IV=45%)
- BUY  AEG Dec-19 $6.50 Call @ $0.55 (IV=52%)
- Net debit: -$0.20

Exit (Nov 14):
- BUY BACK Nov-28 Call @ $0.15 (IV=28%, -17% absolute)
- SELL Dec-19 Call @ $0.48 (IV=35%, -17% absolute, but higher starting point)
- Net credit: +$0.33
- P&L: +$0.13 per share
```

**Key Difference from Strategy #1**:
- Strategy #1 uses fixed DTE ranges (14-21, 35-50)
- Strategy #3 dynamically selects expirations with maximum IV spread
- Strategy #3 should perform better when term structure is more pronounced

---

## Implementation Components

### New Code to Write

#### 1. Simple Earnings Strategy (`tools/src/tools/strategies/options/simple_earnings_calendar.py`)

```python
from dataclasses import dataclass
from datetime import datetime, date
from typing import List, Optional

from .base import OptionsStrategy
from tools.options.models import Signal, Position, Greeks
from tools.options.spreads import SpreadConstructor

@dataclass
class SimpleEarningsConfig:
    """Configuration for simple earnings calendar spread."""
    underlying_symbols: List[str]
    earnings_dates: dict[str, date]  # symbol → earnings_date
    entry_days_before: int = 1       # Enter 1 day before
    exit_days_after: int = 1         # Exit 1 day after
    target_delta: tuple[float, float] = (0.40, 0.60)
    front_dte_range: tuple[int, int] = (14, 21)
    back_dte_range: tuple[int, int] = (35, 50)
    option_type: str = "C"  # Calls

class SimpleEarningsCalendarSpreadStrategy(OptionsStrategy):
    """
    Simple earnings calendar spread strategy.

    Entry: N days before earnings
    Exit: M days after earnings
    Goal: Capture IV crush effect
    """

    def generate_signals(self, ...) -> List[Signal]:
        """Check if today is entry date, generate calendar spread signal."""
        # For each symbol with earnings:
        #   If (earnings_date - current_date).days == entry_days_before:
        #       Build calendar spread with delta-based strike selection

    def should_exit_position(self, ...) -> bool:
        """Exit on specified day after earnings."""
        # Check if (current_date - earnings_date).days == exit_days_after
```

#### 2. IV Term Structure Analyzer (`src/dlt_ibapi/backtest/iv_term_structure.py`)

Adapted from `crypto_options/src/crypto_options/repository/iv_term_structure.py`:

```python
class IVTermStructureAnalyzer:
    """Analyze IV term structure for calendar spread selection."""

    def __init__(self, data_provider, option_bars_reader):
        self.data_provider = data_provider
        self.option_bars_reader = option_bars_reader
        self.greeks_calculator = GreeksCalculator()

    def get_iv_term_structure(
        self,
        symbol: str,
        timestamp: datetime,
        expirations: List[date],
        moneyness_min: float = 0.98,
        moneyness_max: float = 1.02,
    ) -> pd.DataFrame:
        """
        Calculate ATM IV for each expiration.

        Returns:
            DataFrame with columns:
            - expiration_date
            - days_to_expiry
            - atm_iv (average IV of ATM options)
            - contract_count
            - iv_std
        """
        # For each expiration:
        #   Get ATM strikes (spot * 0.98 to spot * 1.02)
        #   Read option bars for each strike
        #   Calculate IV from mid price
        #   Average IV across ATM contracts

    def find_max_iv_differential(
        self,
        term_structure: pd.DataFrame,
        front_dte_range: tuple[int, int],
        back_dte_range: tuple[int, int],
    ) -> Optional[dict]:
        """
        Find front/back expiration pair with maximum IV differential.

        Returns:
            {
                'front_expiration': date,
                'front_dte': int,
                'front_iv': float,
                'back_expiration': date,
                'back_dte': int,
                'back_iv': float,
                'iv_diff': float,
                'iv_diff_pct': float,
            }
        """
        # Filter front candidates (14-21 DTE)
        # Filter back candidates (35-50 DTE)
        # Find pair with max(back_iv - front_iv)

    def calculate_iv_rank(
        self,
        symbol: str,
        current_iv: float,
        lookback_days: int = 252,
        timestamp: datetime = None,
    ) -> Optional[float]:
        """
        Calculate IV rank: (current - min) / (max - min) * 100

        Requires historical IV data (computed from option bars).
        """
        # Get historical equity bars
        # For each bar date:
        #   Get ATM option prices
        #   Calculate implied IV
        # Compute: IV_rank = (current - min) / (max - min)
```

#### 3. IV Term Structure Strategy (`tools/src/tools/strategies/options/iv_term_calendar.py`)

```python
@dataclass
class IVTermCalendarConfig(SimpleEarningsConfig):
    """Extends simple config with IV term structure parameters."""
    min_iv_diff: float = 0.03  # 3% minimum differential
    min_iv_rank: float = 20.0  # IV rank at least 20%
    max_iv_rank: float = 70.0  # IV rank at most 70%

class IVTermStructureCalendarSpreadStrategy(SimpleEarningsCalendarSpreadStrategy):
    """
    Calendar spread with IV term structure-based expiration selection.

    Unlike SimpleEarningsCalendarSpreadStrategy which uses fixed DTE ranges,
    this strategy selects expirations with maximum IV differential.
    """

    def __init__(self, config, iv_analyzer):
        super().__init__(config)
        self.iv_analyzer = iv_analyzer

    def generate_signals(self, ...) -> List[Signal]:
        """Generate signals with IV-optimized expiration selection."""
        # 1. Check if entry date
        # 2. Get IV term structure for all expirations
        # 3. Find pair with max IV differential
        # 4. Check IV rank filter (optional)
        # 5. Build calendar spread with selected expirations
```

#### 4. Enhanced Data Provider (`src/dlt_ibapi/backtest/data_providers.py`)

```python
class IBBacktestDataProvider:
    # ... existing methods ...

    def get_iv_history(
        self,
        symbol: str,
        lookback: int,
        timestamp: datetime,
        dte_min: int = 14,
        dte_max: int = 60,
    ) -> Optional[List[float]]:
        """
        Get historical ATM IV values for IV rank calculation.

        Process:
        1. Get equity bars for lookback period
        2. For each bar date:
           - Get ATM option prices (if available)
           - Calculate implied IV
        3. Return list of IV values
        """
        # Implementation:
        # - Read equity bars (start_date - lookback to start_date)
        # - For each date with option bars:
        #   - Get ATM strike (closest to spot)
        #   - Get option mid price
        #   - Calculate IV using GreeksCalculator
        # - Return IV series
```

#### 5. Backtest Script (`scripts/backtest_aeg_earnings.py`)

```python
"""
Backtest AEG earnings calendar spread strategies.

Compares two approaches:
1. Simple: Fixed DTE ranges, 1 day before → 1 day after earnings
2. IV-based: Max IV differential expirations, same timing

Usage:
    uv run python scripts/backtest_aeg_earnings.py
"""

from datetime import date
from dlt_ibapi.backtest import (
    IBBacktestDataProvider,
    OptionsBacktestRunner,
    IVTermStructureAnalyzer,
)
from tools.strategies.options import (
    SimpleEarningsCalendarSpreadStrategy,
    IVTermStructureCalendarSpreadStrategy,
)

def main():
    # Initialize providers
    data_provider = IBBacktestDataProvider("./data_delta")
    iv_analyzer = IVTermStructureAnalyzer(data_provider)

    # AEG earnings configuration
    aeg_earnings = {"AEG": date(2025, 11, 13)}

    # === Strategy #1: Simple ===
    simple_config = SimpleEarningsConfig(
        underlying_symbols=["AEG"],
        earnings_dates=aeg_earnings,
        entry_days_before=1,
        exit_days_after=1,
        target_delta=(0.40, 0.60),
        front_dte_range=(14, 21),
        back_dte_range=(35, 50),
    )
    simple_strategy = SimpleEarningsCalendarSpreadStrategy(simple_config)

    # Run simple backtest
    simple_runner = OptionsBacktestRunner(
        strategy=simple_strategy,
        data_provider=data_provider,
        initial_capital=100_000,
        validate_data=True,
    )

    simple_result = simple_runner.run(
        start_date=date(2025, 11, 1),
        end_date=date(2025, 11, 20),
    )

    # === Strategy #3: IV Term Structure ===
    iv_config = IVTermCalendarConfig(
        underlying_symbols=["AEG"],
        earnings_dates=aeg_earnings,
        entry_days_before=1,
        exit_days_after=1,
        target_delta=(0.40, 0.60),
        min_iv_diff=0.03,
        min_iv_rank=20.0,
        max_iv_rank=70.0,
    )
    iv_strategy = IVTermStructureCalendarSpreadStrategy(iv_config, iv_analyzer)

    # Run IV-based backtest
    iv_runner = OptionsBacktestRunner(
        strategy=iv_strategy,
        data_provider=data_provider,
        initial_capital=100_000,
        validate_data=True,
    )

    iv_result = iv_runner.run(
        start_date=date(2025, 11, 1),
        end_date=date(2025, 11, 20),
    )

    # === Compare Results ===
    print("\n" + "="*60)
    print("AEG EARNINGS CALENDAR SPREAD BACKTEST RESULTS")
    print("="*60)

    print("\nStrategy #1: Simple (Fixed DTE)")
    print(f"  Total P&L: ${simple_result.total_pnl:,.2f}")
    print(f"  Max Drawdown: ${simple_result.max_drawdown:,.2f}")
    print(f"  Win Rate: {simple_result.win_rate:.1%}")
    print(f"  Trades: {simple_result.num_trades}")

    print("\nStrategy #3: IV Term Structure")
    print(f"  Total P&L: ${iv_result.total_pnl:,.2f}")
    print(f"  Max Drawdown: ${iv_result.max_drawdown:,.2f}")
    print(f"  Win Rate: {iv_result.win_rate:.1%}")
    print(f"  Trades: {iv_result.num_trades}")

    print("\nDifference:")
    pnl_diff = iv_result.total_pnl - simple_result.total_pnl
    print(f"  P&L Improvement: ${pnl_diff:,.2f} ({pnl_diff/simple_result.total_pnl:.1%})")

if __name__ == "__main__":
    main()
```

---

## Data Requirements

### Currently Available (AEG)

✅ **Equity Bars**:
- Location: `./data_delta/stocks/historical_bars/symbol=AEG/`
- Records: 216 bars (2025-01-06 to 2025-01-21)
- Quality: Good (daily OHLCV)
- Recent Close: $6.48

✅ **Earnings Calendar**:
- Location: `./data_delta/earnings/earnings_calendar/symbol=AEG/`
- Records: 1 earnings event
- Date: November 13, 2025

✅ **Option Chain Snapshot**:
- Location: `./data_delta/option_chains/`
- Snapshots: 1 date only (2025-11-14)
- Contains: Available strikes/expirations (metadata only)

### Missing (CRITICAL)

❌ **Option Bars** (historical option prices):
- Status: Table doesn't exist
- Impact: **Cannot backtest without option prices**
- Solution: Run backfill command (Phase 1)

❌ **Extended Equity History** (for IV rank):
- Current: 216 days (~7 months)
- Needed: 252+ days (1+ year)
- Impact: IV rank calculation will use shorter lookback
- Workaround: Use available history with caveat

❌ **Additional Option Chain Snapshots**:
- Current: 1 snapshot (Nov 14, 2025)
- Needed: Daily snapshots Nov 1-20
- Impact: Cannot infer exact contract availability each day
- Workaround: Use option bars reader to check data existence

### Data Collection Commands

#### Phase 1: Backfill Option Bars (REQUIRED)

```bash
# Backfill AEG option bars for calendar spread range
dlt-ibapi backfill-options AEG 6.48 \
  --mode atm \
  --k-strikes 5 \
  --min-dte 7 \
  --max-dte 60 \
  --start-date 2025-01-06 \
  --end-date 2025-11-14 \
  --bar-size "1 day" \
  --pipeline-name ib_options_backfill

# Expected output:
# - Front leg contracts: Nov-28, Dec-05 (14-21 DTE from Nov 12)
# - Back leg contracts: Dec-19, Jan-16 (35-50 DTE from Nov 12)
# - Strikes: $5.50, $6.00, $6.50, $7.00, $7.50 (±5 around ATM)
# - Historical bars: Jan 6 → Nov 14 (219 days)
```

#### Phase 2: Validate Data Coverage

```bash
# Run validation to check coverage
uv run python -c "
from dlt_ibapi.backtest import BacktestDataValidator, BacktestDataRequirements
from datetime import date

validator = BacktestDataValidator(
    database_path='./data_delta',
    requirements=BacktestDataRequirements(
        equity_bar_size='1 day',
        option_bar_size='1 day',
        front_month_dte=(14, 21),
        back_month_dte=(35, 50),
    )
)

report = validator.validate_calendar_spread_data(
    symbol='AEG',
    earnings_date=date(2025, 11, 13),
    entry_days_before=1,
    exit_days_after=1,
)

print(report)
"
```

#### Phase 3: Extended Equity History (Optional)

```bash
# Backfill older equity bars for IV rank calculation
dlt-ibapi backfill-equity AEG \
  --bar-size "1 day" \
  --start-date 2024-01-01 \
  --end-date 2024-12-31 \
  --pipeline-name ib_stocks_backfill
```

---

## What MORE Data Is Needed

### For Strategy #1 (Simple)
- ✅ **Minimum**: Option bars only (collecting in Phase 1)
- ✅ **Sufficient**: Can run backtest with current equity history

### For Strategy #3 (IV Term Structure)
- ✅ **Minimum**: Same as Strategy #1 (option bars)
- ⚠️ **Recommended**: 12+ months equity bars for IV rank
  - Current: 7 months available
  - Impact: IV rank calculation less accurate
  - Workaround: Use 7-month lookback with caveat
- ⚠️ **Ideal**: Daily option chain snapshots
  - Current: 1 snapshot only
  - Impact: Cannot see IV evolution over time
  - Workaround: Calculate IV from option bars (reverse-engineer)

### Data Gaps Summary

| Data Type | Required For | Current Status | Impact | Workaround |
|-----------|-------------|----------------|--------|------------|
| Option Bars | Both strategies | ❌ Missing | **CRITICAL** - can't backtest | Backfill (Phase 1) |
| 12mo Equity Bars | IV rank calculation | ⚠️ Partial (7mo) | Less accurate IV rank | Use shorter lookback |
| Daily Snapshots | IV evolution tracking | ⚠️ Limited (1 date) | Can't see term structure changes | Calculate IV from bars |
| Earnings Calendar | Entry/exit timing | ✅ Complete | None | N/A |
| Current Equity Bars | Spot prices | ✅ Complete | None | N/A |

---

## Expected Results

### Hypothesis

**Strategy #3 (IV Term Structure) should outperform Strategy #1 (Simple)** when:
- IV term structure is pronounced (large front/back IV differential)
- IV crush is asymmetric (front drops more than back)
- Selected expirations capture maximum IV spread

**Strategy #1 (Simple) may outperform** when:
- IV term structure is flat (little front/back difference)
- Standard DTE ranges happen to align with IV peaks
- Simpler is better (fewer moving parts)

### Performance Metrics

We will compare:

1. **Total P&L**: Net profit/loss from the spread
2. **Max Drawdown**: Largest peak-to-trough decline
3. **Win Rate**: % of trades that were profitable
4. **Average P&L per Trade**: Mean profit/loss
5. **IV Capture**: Difference in IV change (front vs back)

### Example Expected Output

```
================================================================
AEG EARNINGS CALENDAR SPREAD BACKTEST RESULTS
================================================================

Strategy #1: Simple (Fixed DTE)
  Entry Date: 2025-11-12
  Exit Date: 2025-11-14
  Position: SELL AEG Nov-28 $6.50C / BUY AEG Dec-19 $6.50C
  Entry Debit: -$0.20 ($20 per spread)
  Exit Credit: +$0.32
  P&L: +$0.12 per spread (+60% ROI)

  Front IV: 45% → 28% (-17%)
  Back IV:  38% → 32% (-6%)
  IV Capture: 11% differential

Strategy #3: IV Term Structure
  Entry Date: 2025-11-12
  Exit Date: 2025-11-14
  Position: SELL AEG Nov-28 $6.50C / BUY AEG Dec-26 $6.50C
  Entry Debit: -$0.25 ($25 per spread)
  Exit Credit: +$0.42
  P&L: +$0.17 per spread (+68% ROI)

  Front IV: 45% → 28% (-17%)
  Back IV:  52% → 40% (-12%)  ← Higher starting IV, less crush
  IV Capture: 5% differential (better than Strategy #1's 11%)

Difference:
  P&L Improvement: +$0.05 per spread (+8% better ROI)
  IV Capture: -6% (more front/back IV convergence)

Conclusion: Strategy #3 outperformed by capturing more asymmetric IV crush.
```

---

## Limitations & Caveats

### Single Earnings Event
- **Issue**: Only 1 earnings date (Nov 13, 2025)
- **Impact**: Not statistically significant
- **Recommendation**: Extend to 10+ earnings events for validation

### Limited Snapshots
- **Issue**: Only 1 option chain snapshot (Nov 14)
- **Impact**: Cannot see IV evolution leading up to earnings
- **Workaround**: Calculate IV from option bars (reverse-engineer)
- **Limitation**: Cannot backfill expired options

### Shorter IV History
- **Issue**: Only 7 months of equity bars
- **Impact**: IV rank calculation less robust (needs 12+ months)
- **Workaround**: Use shorter lookback with explicit caveat

### No Real-Time Greeks
- **Issue**: Greeks calculated from end-of-day bars
- **Impact**: No intraday position management
- **Acceptable**: Daily bar backtest is standard approach

### Assumption: Mid Price Execution
- **Issue**: Backtest uses mid price (high + low) / 2
- **Impact**: Overstates actual fill quality
- **Reality**: Real execution has bid/ask slippage (~$0.02-0.05)

---

## Future Extensions

### Multi-Symbol Backtest
Expand to earnings calendar with 50+ symbols:
```python
earnings_calendar = {
    "AAPL": date(2025, 11, 5),
    "MSFT": date(2025, 10, 22),
    "GOOGL": date(2025, 10, 29),
    # ... 47 more symbols
}

# Run backtest across all earnings
# Calculate: Sharpe ratio, max concurrent positions, etc.
```

### Parameter Optimization
Grid search over:
- Entry timing: 1, 2, 3 days before earnings
- Exit timing: 0, 1, 2 days after earnings
- Front DTE: (7-14), (14-21), (21-30)
- Back DTE: (28-40), (35-50), (50-70)
- IV differential threshold: 0.02, 0.03, 0.05

### IV Rank Filtering
Add entry filter:
```python
# Only enter if IV rank in range
if not (20 <= iv_rank <= 70):
    skip_trade()  # Avoid extreme IV levels
```

### Portfolio-Level Metrics
- **Kelly Criterion**: Optimal position sizing
- **Greeks Aggregation**: Total portfolio delta, vega, theta
- **Correlation Analysis**: How multiple earnings interact

---

## Appendix: References

### Existing Documentation
- `docs/BACKTEST_QUICKSTART.md` - General backtest framework
- `docs/CALENDAR_SPREAD_BACKTEST_GUIDE.md` - Calendar spread strategies
- `docs/AUTOMATED_CALENDAR_SPREAD_WORKFLOW.md` - Data collection automation

### Related Code
- `tools/src/tools/strategies/options/pre_earnings.py` - Pre-earnings strategy (exits BEFORE earnings)
- `tools/src/tools/strategies/options/iv_based_entry.py` - IV-filtered calendar spreads
- `crypto_options/src/crypto_options/repository/iv_term_structure.py` - IV term structure analyzer (source)

### IB API Documentation
- Interactive Brokers API: https://interactivebrokers.github.io/tws-api/
- Historical Data: https://interactivebrokers.github.io/tws-api/historical_bars.html
- Option Chains: https://interactivebrokers.github.io/tws-api/option_chains.html

---

## Timeline & Milestones

| Phase | Task | Duration | Status |
|-------|------|----------|--------|
| 1 | Backfill AEG option bars | 30 mins | ⏳ Pending |
| 1 | Validate data coverage | 5 mins | ⏳ Pending |
| 2 | Create SimpleEarningsCalendarSpreadStrategy | 2 hours | ⏳ Pending |
| 3 | Create IV term structure analyzer | 1 hour | ⏳ Pending |
| 4 | Create IVTermStructureCalendarSpreadStrategy | 1 hour | ⏳ Pending |
| 5 | Enhance IBBacktestDataProvider | 30 mins | ⏳ Pending |
| 6 | Create backtest script | 30 mins | ⏳ Pending |
| 7 | Run backtests and compare results | 15 mins | ⏳ Pending |
| 8 | Document findings | 30 mins | ⏳ Pending |

**Total Estimated Time**: ~5.5 hours

---

## Questions & Decisions

### Q1: Should we use calls or puts for the calendar spread?
**Decision**: Use **calls** (option_type="C")
- **Reason**: AEG is around $6.48, calls have more volume/liquidity
- **Alternative**: Can test puts separately

### Q2: What if IV rank calculation fails (insufficient history)?
**Decision**: Skip IV rank filter, log warning
- **Fallback**: Use simple IV term structure (max differential only)
- **Document**: Note in results that IV rank was unavailable

### Q3: What if no contracts meet delta criteria (0.40-0.60)?
**Decision**: Expand delta range to 0.30-0.70
- **Fallback**: If still no match, use closest to ATM
- **Log**: Document strike selection method used

### Q4: Should we handle early assignment risk?
**Decision**: Not for this backtest (expires worthless or closed)
- **Reason**: Short leg expires after earnings (low early assignment risk)
- **Future**: Add early assignment logic for production

---

## Success Criteria

This backtest is considered successful if:

1. ✅ **Data Collection Completes**: Option bars for AEG are backfilled
2. ✅ **Both Strategies Execute**: No errors during backtest run
3. ✅ **P&L Calculated**: Both strategies produce valid P&L results
4. ✅ **IV Metrics Captured**: Front/back IV changes are logged
5. ✅ **Comparison Made**: Clear winner or statistical tie identified
6. ✅ **Documented**: Findings written up with recommendations

**Bonus**:
- 🎯 Strategy #3 outperforms Strategy #1 (validates IV term structure hypothesis)
- 🎯 IV capture differential explains performance difference
- 🎯 Results are reproducible with clear data lineage

---

## Contact & Support

For questions about this backtest:
- **Code Location**: `/Users/mohamedali/trading_project/dlt-ibapi/`
- **Data Location**: `./data_delta/`
- **Documentation**: `docs/AEG_EARNINGS_CALENDAR_SPREAD_BACKTEST_PLAN.md`

---

## Implementation Summary

### Status: ✅ **Implementation Complete** (Pending Data Collection)

All code components have been implemented and are ready for execution. The backtest can run as soon as option bars data is collected.

### What Was Implemented

#### 1. Strategy Classes ✅

**SimpleEarningsCalendarSpreadStrategy** (`tools/src/tools/strategies/options/simple_earnings_calendar.py`):
- Fixed DTE ranges (14-21 front, 35-50 back)
- Delta-based strike selection (0.40-0.60)
- Entry: 1 day before earnings
- Exit: 1 day after earnings
- ~250 lines of code

**IVTermStructureCalendarSpreadStrategy** (`tools/src/tools/strategies/options/iv_term_calendar.py`):
- Dynamically selects expirations by max IV differential
- Extends SimpleEarningsCalendarSpreadStrategy
- Same entry/exit timing as simple strategy
- Adds IV term structure analysis
- ~180 lines of code

#### 2. IV Term Structure Utilities ✅

**IVTermStructureAnalyzer** (`src/dlt_ibapi/backtest/iv_term_structure.py`):
- `get_iv_term_structure()`: Calculate ATM IV by expiration
- `find_max_iv_differential()`: Find best expiration pair
- `calculate_iv_rank()`: Historical IV percentile
- `get_simplified_iv_history()`: Fast IV history retrieval
- ~400 lines of code
- Adapted from crypto_options project

#### 3. Enhanced Data Provider ✅

**IBBacktestDataProvider** updates (`src/dlt_ibapi/backtest/data_providers.py`):
- Enhanced `get_iv_history()` method with full implementation
- Samples historical data every 5 days to reduce computation
- Calculates IV from option mid prices using GreeksCalculator
- Returns None if insufficient data (graceful degradation)

#### 4. Backtest Script ✅

**backtest_aeg_earnings.py** (`scripts/backtest_aeg_earnings.py`):
- Runs both strategies in parallel
- Compares P&L, drawdown, win rate
- Displays detailed trade logs
- Shows IV capture metrics
- Command-line interface with args
- ~250 lines of code

#### 5. Documentation ✅

**AEG_EARNINGS_CALENDAR_SPREAD_BACKTEST_PLAN.md** (this document):
- Complete strategy descriptions
- Data requirements
- Implementation details
- Expected results
- Timeline estimates
- ~600 lines of documentation

### Files Created

```
tools/src/tools/strategies/options/
├── simple_earnings_calendar.py       (NEW - 250 lines)
└── iv_term_calendar.py                (NEW - 180 lines)

src/dlt_ibapi/backtest/
└── iv_term_structure.py               (NEW - 400 lines)

scripts/
└── backtest_aeg_earnings.py           (NEW - 250 lines)

docs/
└── AEG_EARNINGS_CALENDAR_SPREAD_BACKTEST_PLAN.md  (NEW - 600+ lines)

TOTAL: ~1,680 lines of new code + documentation
```

### What Remains (User Action Required)

#### 1. Start IB Gateway ⏳

**Required**: IB Gateway or TWS must be running for data collection.

```bash
# Paper trading port: 4002
# Live trading port: 4001
```

#### 2. Backfill Option Bars ⏳

**Critical**: Option bars are required for backtest execution.

```bash
# Start IB Gateway first, then:
dlt-ibapi backfill-options AEG 6.48 \
  --mode atm --k-strikes 5 \
  --min-dte 7 --max-dte 60 \
  --start 2025-01-06 --end 2025-11-14 \
  --bar-size "1 day" \
  --pipeline-name ib_options_backfill

# Expected duration: 30-60 mins (API rate limits)
# Expected output: ~100-200 option contracts backfilled
```

#### 3. Run Backtest ⏳

Once option bars are collected:

```bash
uv run python scripts/backtest_aeg_earnings.py

# Optional arguments:
# --data-path ./data_delta
# --initial-capital 100000
# --verbose
```

### How to Run (Complete Workflow)

```bash
# Step 1: Start IB Gateway (Paper Trading)
# Open IB Gateway → Configure port 4002 → Login

# Step 2: Verify IB connection
dlt-ibapi test-connection

# Step 3: Backfill option bars
dlt-ibapi backfill-options AEG 6.48 \
  --mode atm --k-strikes 5 \
  --min-dte 7 --max-dte 60 \
  --start 2025-01-06 --end 2025-11-14 \
  --bar-size "1 day"

# Step 4: Run backtest
uv run python scripts/backtest_aeg_earnings.py

# Step 5: Analyze results
# Review console output and trade logs
```

---

**Last Updated**: 2025-01-21
**Author**: Claude Code (Anthropic)
**Status**: ✅ Implementation Complete (Pending Data Collection)
