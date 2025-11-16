# Calendar Spread Earnings Strategy - Paper Trading Infrastructure

**Version:** 1.0
**Date:** 2025-11-16
**Status:** Planning Phase

---

## Executive Summary

This document specifies the infrastructure for paper trading **calendar spread options strategies** around earnings events. The system will automate signal generation, order execution, position management, and performance tracking using Interactive Brokers Paper Trading accounts.

**Strategy Overview:**
- **Entry**: Day of/before earnings at 3pm (based on earnings timing)
- **Position**: Sell near-term ATM option, Buy far-term ATM option (same strike)
- **Exit**: After earnings IV crush (AFTER_HOURS: next day 10am, PRE_MARKET: same day 4pm)
- **Edge**: Differential IV collapse - short leg loses more IV than long leg
- **Risk**: Limited to net debit paid (defined risk)

**Backtest Performance** (44 symbols, Nov 13 earnings):
- Execution Rate: 52.3% (23/44 trades)
- Win Rate: 60.9%
- Mean P&L: $85.52 per contract
- Best Trade: $1,260 (BAP), Worst: -$25 (CADL)

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Component Specifications](#component-specifications)
3. [Data Models](#data-models)
4. [Implementation Phases](#implementation-phases)
5. [Technical Decisions](#technical-decisions)
6. [Testing Strategy](#testing-strategy)
7. [Deployment & Operations](#deployment--operations)

---

## Architecture Overview

### System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      Paper Trading System                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    │
│  │   Scheduler  │───▶│Signal Engine │───▶│Order Manager │    │
│  │              │    │              │    │              │    │
│  │ - Earnings   │    │ - Scan       │    │ - Place      │    │
│  │   calendar   │    │   earnings   │    │   orders     │    │
│  │ - Market     │    │ - Check data │    │ - Track      │    │
│  │   hours      │    │   available  │    │   fills      │    │
│  │ - Watchlist  │    │ - Calculate  │    │ - Manage     │    │
│  └──────────────┘    │   strikes    │    │   positions  │    │
│                      └──────────────┘    └──────────────┘    │
│                             │                     │           │
│                             ▼                     ▼           │
│                      ┌──────────────┐    ┌──────────────┐    │
│                      │Position Mgr  │    │Risk Manager  │    │
│                      │              │    │              │    │
│                      │ - Track P&L  │    │ - Position   │    │
│                      │ - Calculate  │    │   limits     │    │
│                      │   Greeks     │    │ - Capital    │    │
│                      │ - Exit logic │    │   limits     │    │
│                      └──────────────┘    └──────────────┘    │
│                             │                                 │
│                             ▼                                 │
│  ┌──────────────────────────────────────────────────────┐    │
│  │             Data Layer (Parquet/DuckDB)              │    │
│  │                                                      │    │
│  │ - Option bars (historical + live)                   │    │
│  │ - Equity bars (spot prices)                         │    │
│  │ - Earnings calendar                                 │    │
│  │ - Trade history (fills, P&L)                        │    │
│  │ - Position snapshots                                │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
1. Daily Scan (9am ET)
   ├─ Load earnings calendar
   ├─ Filter symbols with option data
   └─ Generate entry signals → Watchlist

2. Entry Window (3pm ET)
   ├─ Check watchlist for signals
   ├─ Validate data availability
   ├─ Place spread orders
   └─ Track fills → Create positions

3. Monitoring (Every 15min)
   ├─ Update position values
   ├─ Calculate Greeks
   └─ Check exit conditions

4. Exit Window (Time-based)
   ├─ AFTER_HOURS: Next day 10am
   ├─ PRE_MARKET: Same day 4pm
   └─ Close positions → Record P&L
```

---

## Component Specifications

### 1. Signal Generation

**File:** `src/dlt_ibapi/trading/signals.py`

**Class:** `EarningsSignalGenerator`

**Responsibilities:**
- Scan earnings calendar for upcoming events
- Filter to symbols with available option data
- Calculate entry/exit times based on earnings timing
- Validate data quality (spot prices, option chains)

**Key Methods:**

```python
def scan_upcoming_earnings(
    self,
    days_ahead: int = 7,
    from_date: date = None,
) -> List[EarningsSignal]:
    """
    Generate signals for upcoming earnings.

    Workflow:
    1. Load earnings from calendar (days_ahead window)
    2. Filter to symbols with option data (OptionBarsReader)
    3. Calculate entry/exit times based on earnings_time
    4. Verify data availability (option chain, spot)
    5. Return valid signals

    Returns:
        List of EarningsSignal objects ready for trading
    """

def validate_signal(self, signal: EarningsSignal) -> bool:
    """
    Pre-flight checks before placing orders.

    Validates:
    - Option chain has 2+ expirations (for calendar spread)
    - Spot price available (for ATM strike calculation)
    - ATM strike available (±10% tolerance)
    - Sufficient DTE (min_dte <= DTE <= max_dte)

    Returns:
        True if signal is tradable, False otherwise
    """
```

**Configuration:**

```python
@dataclass
class SignalConfig:
    min_dte: int = 7           # Minimum days to expiration
    max_dte: int = 30          # Maximum days to expiration
    atm_tolerance: float = 0.10  # ±10% for strike selection
    min_expirations: int = 2   # Required for calendar spread
```

**Dependencies:**
- `EarningsCalendarReader` (existing)
- `OptionBarsReader` (existing)
- `EquityBarsReader` (existing)
- `filter_tradable_earnings()` from `strategies/batch.py`

---

### 2. Order Execution

**File:** `src/dlt_ibapi/trading/execution.py`

**Class:** `PaperOrderManager`

**Responsibilities:**
- Place spread orders via IB Gateway
- Track order fills
- Handle order failures and retries
- Maintain order history

**Key Methods:**

```python
def open_calendar_spread(
    self,
    signal: EarningsSignal,
    quantity: int = 1,
    option_type: Literal["C", "P"] = "C",
) -> CalendarSpreadPosition:
    """
    Open calendar spread position.

    Workflow:
    1. Resolve contracts (ContractDetailsService)
    2. Get current option prices (MarketDataService)
    3. Calculate ATM strike from spot price
    4. Select expirations:
       - Short leg: Nearest expiration > earnings_date
       - Long leg: Next expiration after short leg
    5. Place spread order (IB COMBO):
       - SELL short_exp ATM option
       - BUY long_exp ATM option
    6. Wait for fills (timeout: 60s)
    7. Create CalendarSpreadPosition object
    8. Save to database

    Args:
        signal: EarningsSignal with entry timing
        quantity: Number of spreads (default 1)
        option_type: "C" for calls, "P" for puts

    Returns:
        CalendarSpreadPosition with fill details

    Raises:
        OrderExecutionError: If fills not received within timeout
        DataAvailabilityError: If option chain incomplete
    """

def close_calendar_spread(
    self,
    position: CalendarSpreadPosition,
    reason: str,
) -> CalendarSpreadPosition:
    """
    Close existing position.

    Workflow:
    1. Get current market prices (bid/ask)
    2. Place closing spread order (reverse of open):
       - BUY short_exp option (close short)
       - SELL long_exp option (close long)
    3. Wait for fills (timeout: 60s)
    4. Calculate realized P&L
    5. Update position (status=CLOSED, exit_datetime, P&L)
    6. Save to database

    Args:
        position: Open position to close
        reason: Exit reason (TARGET, STOP, EXPIRATION, MANUAL)

    Returns:
        Updated position with exit details
    """

def get_current_prices(
    self,
    position: CalendarSpreadPosition,
) -> Tuple[float, float]:
    """
    Get real-time bid/ask for both legs.

    Uses MarketDataService.reqMktData() for live quotes.

    Returns:
        (short_leg_price, long_leg_price) tuple
    """
```

**Order Configuration:**

```python
@dataclass
class OrderConfig:
    order_type: str = "LMT"           # Limit order
    time_in_force: str = "DAY"        # Cancel at market close
    fill_timeout: int = 60            # Seconds to wait for fills
    price_buffer: float = 0.05        # $0.05 buffer from mid-price
    retry_attempts: int = 3           # Max retries on failure
```

**IB API Integration:**
- Uses `ib-connector` services:
  - `ContractDetailsService` for contract resolution
  - `MarketDataService` for live quotes
  - `PlaceOrderService` for order submission
  - `OrderStatusService` for fill tracking

**Order Type: COMBO Spread**
```python
# IB API combo order structure
combo_legs = [
    ComboLeg(
        conId=short_contract.conId,
        ratio=1,
        action="SELL",
        exchange="SMART",
    ),
    ComboLeg(
        conId=long_contract.conId,
        ratio=1,
        action="BUY",
        exchange="SMART",
    ),
]

order = Order(
    action="BUY",  # BUY the spread (net debit)
    totalQuantity=quantity,
    orderType="LMT",
    lmtPrice=spread_limit_price,
    tif="DAY",
)
```

---

### 3. Position Management

**File:** `src/dlt_ibapi/trading/positions.py`

**Class:** `PositionManager`

**Responsibilities:**
- Track open positions
- Update position values using live data
- Calculate P&L and Greeks
- Determine exit conditions
- Manage position lifecycle

**Key Methods:**

```python
def update_position_values(
    self,
    position: CalendarSpreadPosition,
) -> CalendarSpreadPosition:
    """
    Refresh position metrics using latest market data.

    Calculates:
    - Current spread value (long_price - short_price)
    - Unrealized P&L (current_value - net_debit)
    - Greeks (delta, gamma, theta, vega) using BS model
    - IV for each leg (reverse-calculate from option prices)

    Uses:
    - MarketDataService for current option prices
    - EquityBarsReader for current spot price
    - calculate_spread_greeks() for Greeks

    Returns:
        Updated position with current metrics
    """

def check_exit_conditions(
    self,
    position: CalendarSpreadPosition,
    current_time: datetime,
) -> Optional[str]:
    """
    Determine if position should be closed.

    Exit conditions (priority order):
    1. **Scheduled Exit**: Reached exit_datetime (from signal)
       - AFTER_HOURS: Next day 10am
       - PRE_MARKET: Same day 4pm

    2. **Profit Target**: P&L > 100% of entry cost (optional)

    3. **Stop Loss**: P&L < -50% of entry cost (optional)

    4. **Expiration Risk**: Short leg < 3 DTE
       - Avoid pin risk and early assignment

    5. **Delta Risk**: abs(spread_delta) > 0.30
       - Position moved too far from ATM
       - Directional exposure too high

    Returns:
        Exit reason string if should close, None otherwise
    """

def get_active_positions(self) -> List[CalendarSpreadPosition]:
    """
    Load all OPEN positions from database.

    Filters: status = "OPEN"
    Sorted by: entry_datetime DESC
    """

def close_expired_positions(self, current_date: date):
    """
    Force-close positions where short leg expired.

    Safety mechanism to prevent assignment/exercise.
    Runs daily at market open.
    """

def save_position_snapshot(self, position: CalendarSpreadPosition):
    """
    Save current position state to snapshots table.

    Used for:
    - P&L charting over time
    - Performance attribution
    - Audit trail

    Frequency: Every 15 minutes during market hours
    """
```

**P&L Calculation:**

```python
# Spread value = long_leg_price - short_leg_price
current_spread_value = long_leg.current_price - short_leg.current_price

# Unrealized P&L = current_value - entry_cost
unrealized_pnl = current_spread_value - position.net_debit

# Per-contract P&L (IB options = 100 shares)
pnl_per_contract = unrealized_pnl * 100

# Percentage return
pnl_percentage = (unrealized_pnl / position.net_debit) * 100
```

**Exit Condition Configuration:**

```python
@dataclass
class ExitConfig:
    # Primary exit (always enabled)
    use_scheduled_exit: bool = True

    # Optional profit target
    profit_target_enabled: bool = False
    profit_target_pct: float = 100.0  # 100% gain

    # Optional stop loss
    stop_loss_enabled: bool = False
    stop_loss_pct: float = -50.0      # -50% loss

    # Risk controls (always enabled)
    min_dte_threshold: int = 3        # Close if short leg < 3 DTE
    max_delta_threshold: float = 0.30  # Close if abs(delta) > 0.30
```

---

### 4. Greeks Calculation

**File:** `src/dlt_ibapi/trading/greeks.py`

**Purpose:** Calculate Black-Scholes Greeks for risk management

**Key Functions:**

```python
def calculate_option_greeks(
    option: OptionLeg,
    spot_price: float,
    risk_free_rate: float = 0.05,
) -> Dict[str, float]:
    """
    Calculate Greeks using Black-Scholes model.

    Uses existing implementation from:
    - dlt_ibapi.utils.black_scholes.black_scholes_call()
    - dlt_ibapi.utils.black_scholes.black_scholes_put()

    Implementation approach:
    - Analytical formulas for Delta, Vega, Theta
    - Numerical derivatives for Gamma (finite differences)

    Args:
        option: OptionLeg with strike, expiry, IV
        spot_price: Current underlying price
        risk_free_rate: Risk-free rate (default 5%)

    Returns:
        {
            'delta': float,   # ∂V/∂S (price sensitivity)
            'gamma': float,   # ∂²V/∂S² (delta sensitivity)
            'theta': float,   # ∂V/∂t (time decay per day)
            'vega': float,    # ∂V/∂σ (IV sensitivity)
            'rho': float,     # ∂V/∂r (rate sensitivity)
        }
    """

def calculate_spread_greeks(
    position: CalendarSpreadPosition,
    spot_price: float,
) -> Dict[str, float]:
    """
    Calculate net Greeks for calendar spread.

    Formula:
        Spread Greeks = Long Leg Greeks - Short Leg Greeks

    Typical calendar spread characteristics:
    - **Delta ≈ 0**: Delta-neutral at ATM
    - **Gamma < 0**: Short gamma from short leg dominance
    - **Theta > 0**: Positive theta from time decay differential
    - **Vega > 0**: Long vega from long leg dominance

    Returns:
        Net Greeks for the spread position
    """

def reverse_calculate_iv(
    option: OptionLeg,
    market_price: float,
    spot_price: float,
) -> float:
    """
    Calculate implied volatility from market price.

    Uses existing implementation:
    - dlt_ibapi.utils.black_scholes.implied_volatility()

    Used for:
    - Updating option IVs in position snapshots
    - Tracking IV crush after earnings

    Returns:
        Implied volatility (annualized)
    """
```

**Greeks Interpretation for Calendar Spreads:**

| Greek | Expected Sign | Meaning |
|-------|--------------|---------|
| Delta | ~0 (neutral) | Minimal directional exposure at ATM |
| Gamma | Negative | Short gamma risk (delta changes with spot movement) |
| Theta | Positive | Profits from time decay (short leg decays faster) |
| Vega | Positive | Profits from IV collapse (long leg retains more value) |
| Rho | Small | Minimal interest rate sensitivity |

---

### 5. Scheduler

**File:** `src/dlt_ibapi/trading/scheduler.py`

**Class:** `TradingScheduler`

**Responsibilities:**
- Automate signal scanning and order execution
- Monitor positions during market hours
- Execute scheduled exits
- Run daily maintenance tasks

**Key Methods:**

```python
def run_scan_cycle(self):
    """
    Daily earnings scan (run at 9:00 AM ET).

    Workflow:
    1. Scan upcoming earnings (next 7 days)
    2. Filter to tradable signals
    3. Calculate entry/exit times
    4. Save signals to watchlist
    5. Log scan results

    Output:
        Watchlist of signals with scheduled entry times
    """

def run_entry_cycle(self):
    """
    Entry window (run at 3:00 PM ET).

    Workflow:
    1. Load watchlist for signals with entry_time = NOW
    2. Validate pre-flight checks:
       - IB Gateway connected
       - Option data available
       - Spot price available
       - Risk limits OK
    3. For each valid signal:
       - Place spread order
       - Wait for fills (60s timeout)
       - Create position record
    4. Send entry notifications

    Output:
        New CalendarSpreadPosition records
    """

def run_exit_cycle(self):
    """
    Exit window (run hourly during market hours).

    Workflow:
    1. Load active positions
    2. Update position values (prices, Greeks)
    3. Check exit conditions for each position
    4. For positions triggering exit:
       - Close spread
       - Record realized P&L
       - Send exit notification

    Schedules:
    - 10:00 AM ET: AFTER_HOURS positions
    - 4:00 PM ET: PRE_MARKET positions
    - Every hour: Check other exit conditions

    Output:
        Closed positions with realized P&L
    """

def run_monitoring_cycle(self):
    """
    Position monitoring (run every 15 minutes).

    Workflow:
    1. Update all active position metrics
    2. Save position snapshots
    3. Check risk limits:
       - Total exposure
       - Position count
       - Delta limits
    4. Generate alerts if needed
    5. Update dashboard

    Output:
        Position snapshots, risk alerts
    """

def run_daily_maintenance(self):
    """
    Daily maintenance (run at 6:00 AM ET).

    Tasks:
    1. Close expired positions
    2. Clean up old snapshots (>90 days)
    3. Verify IB connection
    4. Backfill missing option data
    5. Generate daily report
    """
```

**Schedule Configuration:**

```python
@dataclass
class ScheduleConfig:
    # Market hours (Eastern Time)
    market_open: time = time(9, 30)
    market_close: time = time(16, 0)

    # Scheduled tasks
    scan_time: time = time(9, 0)          # Before market open
    entry_time: time = time(15, 0)        # 3pm entry window
    exit_after_hours_time: time = time(10, 0)  # 10am next day
    exit_pre_market_time: time = time(16, 0)   # 4pm same day

    # Monitoring intervals
    monitoring_interval: int = 15         # Minutes
    snapshot_interval: int = 15           # Minutes

    # Maintenance
    maintenance_time: time = time(6, 0)   # Before market
```

**Scheduler Implementation:**

Uses `APScheduler` for Python-based scheduling:

```python
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = BlockingScheduler(timezone='America/New_York')

# Daily scan at 9am
scheduler.add_job(
    run_scan_cycle,
    trigger=CronTrigger(hour=9, minute=0),
    id='daily_scan'
)

# Entry window at 3pm
scheduler.add_job(
    run_entry_cycle,
    trigger=CronTrigger(hour=15, minute=0),
    id='entry_window'
)

# Monitoring every 15 minutes during market hours
scheduler.add_job(
    run_monitoring_cycle,
    trigger='interval',
    minutes=15,
    start_date='09:30',
    end_date='16:00',
    id='monitoring'
)

scheduler.start()
```

---

### 6. Risk Management

**File:** `src/dlt_ibapi/trading/risk.py`

**Class:** `RiskManager`

**Responsibilities:**
- Enforce capital limits
- Validate position sizing
- Monitor total exposure
- Prevent over-trading

**Key Methods:**

```python
def check_new_position_allowed(
    self,
    net_debit: float,
    current_positions: List[CalendarSpreadPosition],
) -> Tuple[bool, Optional[str]]:
    """
    Validate if new position can be opened.

    Checks:
    1. Position size: net_debit <= max_position_size
    2. Total exposure: sum(open positions) + net_debit <= max_total_exposure
    3. Position count: len(open positions) < max_positions
    4. Symbol concentration: No more than 2 positions per symbol

    Args:
        net_debit: Entry cost for new position
        current_positions: List of open positions

    Returns:
        (allowed: bool, rejection_reason: Optional[str])

    Example:
        allowed, reason = risk_manager.check_new_position_allowed(
            net_debit=150.0,
            current_positions=active_positions
        )
        if not allowed:
            logger.warning(f"Position rejected: {reason}")
    """

def calculate_position_size(
    self,
    signal: EarningsSignal,
    available_capital: float,
) -> int:
    """
    Determine quantity (number of spreads to trade).

    Approaches:
    1. **Fixed**: Always 1 contract (simple, conservative)
    2. **Fixed %**: X% of available capital
    3. **Kelly Criterion**: Optimal sizing based on edge

    Current implementation: Fixed 1 contract per signal

    Returns:
        Quantity (number of spreads)
    """

def check_position_risk(
    self,
    position: CalendarSpreadPosition,
) -> List[str]:
    """
    Check position-level risk violations.

    Checks:
    - Delta exposure: abs(delta) > max_delta_threshold
    - P&L: unrealized_pnl < stop_loss_threshold
    - DTE: short_leg_dte < min_dte_threshold

    Returns:
        List of risk warnings (empty if OK)
    """

def get_portfolio_metrics(
    self,
    positions: List[CalendarSpreadPosition],
) -> Dict[str, float]:
    """
    Calculate portfolio-level risk metrics.

    Metrics:
    - Total exposure (sum of net debits)
    - Net delta (sum of position deltas)
    - Net theta (sum of position thetas)
    - Net vega (sum of position vegas)
    - Largest position (% of total)

    Returns:
        Dictionary of portfolio metrics
    """
```

**Risk Configuration:**

```python
@dataclass
class RiskConfig:
    # Position limits
    max_position_size: float = 1000.0      # Max $ per position
    max_total_exposure: float = 5000.0     # Max $ across all positions
    max_positions: int = 5                 # Max concurrent positions
    max_positions_per_symbol: int = 2      # Max per underlying

    # Position-level risk
    max_delta_threshold: float = 0.30      # Close if abs(delta) > 0.30
    stop_loss_pct: float = -50.0           # Close if P&L < -50%
    min_dte_threshold: int = 3             # Close if short leg < 3 DTE

    # Portfolio-level risk
    max_net_delta: float = 1.0             # Max portfolio delta
    max_correlation: float = 0.70          # Max correlation between positions
```

---

### 7. Data Storage

**File:** `src/dlt_ibapi/trading/database.py`

**Class:** `PositionDatabase`

**Purpose:** Persist trade history, positions, signals using Parquet

**Storage Structure:**

```
./data/paper_trading/
├── positions/
│   └── *.parquet              # CalendarSpreadPosition records
├── trades/
│   └── *.parquet              # Trade fills
├── signals/
│   └── *.parquet              # EarningsSignal history
└── snapshots/
    └── date=YYYY-MM-DD/       # Position snapshots (Hive partitioned)
        └── *.parquet
```

**Key Methods:**

```python
def save_position(self, position: CalendarSpreadPosition):
    """
    Append new position to positions table.

    Schema: position_id, symbol, earnings_date, earnings_time,
            entry_datetime, exit_datetime, status, strike,
            short_expiry, long_expiry, net_debit, realized_pnl,
            exit_reason, ...

    Write disposition: append
    """

def update_position(self, position: CalendarSpreadPosition):
    """
    Update existing position (overwrite in Parquet).

    Implementation:
    1. Read current positions table
    2. Update matching position_id
    3. Overwrite table

    Note: Parquet is immutable, so this requires full rewrite
    """

def save_trade(self, trade: Trade):
    """
    Record order fill in trades table.

    Schema: trade_id, position_id, timestamp, leg, action,
            symbol, strike, expiry, right, quantity,
            fill_price, commission

    Used for:
    - Audit trail of all fills
    - Commission tracking
    - Fill price analysis
    """

def save_snapshot(self, position: CalendarSpreadPosition):
    """
    Save position state for time-series analysis.

    Schema: snapshot_id, position_id, timestamp,
            short_price, long_price, spread_value, unrealized_pnl,
            delta, gamma, theta, vega,
            short_iv, long_iv

    Partitioning: Hive-style by date (date=YYYY-MM-DD/)
    Frequency: Every 15 minutes during market hours
    Retention: 90 days
    """

def get_active_positions(self) -> List[CalendarSpreadPosition]:
    """
    Query positions with status=OPEN.

    SQL:
        SELECT * FROM positions
        WHERE status = 'OPEN'
        ORDER BY entry_datetime DESC
    """

def get_position_history(
    self,
    position_id: str,
) -> pd.DataFrame:
    """
    Load all snapshots for a position (for P&L chart).

    SQL:
        SELECT * FROM snapshots
        WHERE position_id = '{position_id}'
        ORDER BY timestamp

    Returns:
        DataFrame with time-series of position metrics
    """

def get_closed_positions(
    self,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """
    Query closed positions in date range.

    Used for performance reporting.

    SQL:
        SELECT * FROM positions
        WHERE status = 'CLOSED'
          AND exit_datetime >= '{start_date}'
          AND exit_datetime <= '{end_date}'
        ORDER BY exit_datetime DESC
    """
```

**Parquet Schemas:**

```python
# positions table
POSITION_SCHEMA = pa.schema([
    ('position_id', pa.string()),
    ('symbol', pa.string()),
    ('earnings_date', pa.date32()),
    ('earnings_time', pa.string()),
    ('entry_datetime', pa.timestamp('us')),
    ('exit_datetime', pa.timestamp('us')),
    ('status', pa.string()),  # PENDING, OPEN, CLOSED

    # Spread details
    ('strike', pa.float64()),
    ('option_type', pa.string()),  # C or P
    ('short_expiry', pa.date32()),
    ('long_expiry', pa.date32()),

    # Financials
    ('net_debit', pa.float64()),
    ('unrealized_pnl', pa.float64()),
    ('realized_pnl', pa.float64()),

    # Exit
    ('exit_reason', pa.string()),
])

# trades table
TRADE_SCHEMA = pa.schema([
    ('trade_id', pa.string()),
    ('position_id', pa.string()),
    ('timestamp', pa.timestamp('us')),
    ('leg', pa.string()),      # SHORT or LONG
    ('action', pa.string()),   # OPEN or CLOSE

    # Contract
    ('symbol', pa.string()),
    ('strike', pa.float64()),
    ('expiry', pa.date32()),
    ('right', pa.string()),

    # Fill
    ('quantity', pa.int32()),
    ('fill_price', pa.float64()),
    ('commission', pa.float64()),
])

# snapshots table (partitioned by date)
SNAPSHOT_SCHEMA = pa.schema([
    ('snapshot_id', pa.string()),
    ('position_id', pa.string()),
    ('timestamp', pa.timestamp('us')),
    ('date', pa.date32()),  # Partition column

    # Prices
    ('short_price', pa.float64()),
    ('long_price', pa.float64()),
    ('spread_value', pa.float64()),
    ('unrealized_pnl', pa.float64()),

    # Greeks
    ('delta', pa.float64()),
    ('gamma', pa.float64()),
    ('theta', pa.float64()),
    ('vega', pa.float64()),

    # IVs
    ('short_iv', pa.float64()),
    ('long_iv', pa.float64()),
])
```

---

### 8. Monitoring & Reporting

**File:** `src/dlt_ibapi/trading/reporting.py`

**Class:** `TradingReporter`

**Responsibilities:**
- Generate position summaries
- Calculate performance statistics
- Create P&L charts
- Send alerts

**Key Methods:**

```python
def generate_position_summary(self) -> pd.DataFrame:
    """
    Active positions table for dashboard.

    Columns:
    - Symbol
    - Entry Date/Time
    - DTE (short leg)
    - Strike
    - Entry Cost
    - Current Value
    - P&L ($)
    - P&L (%)
    - Delta
    - Theta
    - Vega
    - Scheduled Exit

    Format: Rich table for CLI display
    """

def generate_performance_stats(
    self,
    start_date: date = None,
    end_date: date = None,
) -> Dict[str, Any]:
    """
    Calculate overall performance metrics.

    Metrics:
    - Total Trades
    - Win Rate (% profitable)
    - Average P&L ($)
    - Best Trade ($)
    - Worst Trade ($)
    - Total P&L ($)
    - Sharpe Ratio (if daily snapshots available)
    - Max Drawdown (%)
    - Profit Factor (gross profit / gross loss)

    Returns:
        Dictionary of performance metrics
    """

def generate_pnl_chart(
    self,
    position_id: str,
    output_path: str = None,
):
    """
    Plot P&L over time for a position.

    Uses position snapshots (15-minute intervals).

    Chart elements:
    - Line plot: Unrealized P&L vs time
    - Annotations: Entry, Exit, Earnings time
    - Shaded regions: Before/After earnings

    Output: matplotlib figure (PNG if output_path provided)
    """

def generate_daily_report(self, report_date: date) -> str:
    """
    Generate daily summary report.

    Sections:
    1. Active Positions (count, total exposure)
    2. Trades Today (entries, exits)
    3. P&L Today (realized + unrealized change)
    4. Upcoming Events (signals scheduled)
    5. Alerts (risk violations, expiring positions)

    Returns:
        Formatted text report (markdown)
    """

def generate_alerts(self) -> List[str]:
    """
    Check conditions and generate alerts.

    Alert triggers:
    - Position approaching scheduled exit (<30 min)
    - Position hitting profit target
    - Position hitting stop loss
    - Short leg < 3 DTE (expiration risk)
    - Delta risk (abs(delta) > 0.30)
    - Missing market data (stale prices)
    - IB Gateway disconnected

    Returns:
        List of alert messages
    """

def export_trades_csv(
    self,
    start_date: date,
    end_date: date,
    output_path: str,
):
    """
    Export trade history to CSV for external analysis.

    Useful for:
    - Tax reporting
    - Broker reconciliation
    - Third-party analytics
    """
```

**Dashboard Format (CLI):**

```
┌─────────────────────────────────────────────────────────────────┐
│                    ACTIVE POSITIONS                             │
├─────────────────────────────────────────────────────────────────┤
│ Symbol │ Entry      │ DTE │ Strike │ P&L ($) │ P&L (%) │ Exit  │
├─────────────────────────────────────────────────────────────────┤
│ TMC    │ 11/13 15:00│  8  │  5.00  │  +5.00  │  +33.3% │ 11/14 │
│ AMAT   │ 11/13 15:00│  8  │ 225.00 │ +118.00 │  +62.1% │ 11/14 │
└─────────────────────────────────────────────────────────────────┘

Portfolio Metrics:
  Total Exposure: $205.00
  Unrealized P&L: +$123.00 (+60.0%)
  Net Delta: +0.05
  Net Theta: +0.15
```

---

### 9. CLI Interface

**File:** `src/dlt_ibapi/cli/paper_trading.py`

**Commands:**

```bash
# Start automated paper trading
dlt-ibapi paper-trade start [--config CONFIG_FILE]

# Stop scheduler
dlt-ibapi paper-trade stop

# Manual signal scan
dlt-ibapi paper-trade scan [--days-ahead DAYS]

# Show active positions
dlt-ibapi paper-trade positions

# Show position details with P&L chart
dlt-ibapi paper-trade show-position POSITION_ID [--chart]

# Close position manually
dlt-ibapi paper-trade close-position POSITION_ID --reason MANUAL

# Show trade history
dlt-ibapi paper-trade history [--days DAYS] [--symbol SYMBOL]

# Performance statistics
dlt-ibapi paper-trade stats [--start-date DATE] [--end-date DATE]

# Daily report
dlt-ibapi paper-trade report [--date DATE]

# Backfill option data for upcoming signal
dlt-ibapi paper-trade prepare-signal SYMBOL --earnings-date DATE

# Export trades to CSV
dlt-ibapi paper-trade export-trades --start DATE --end DATE --output FILE
```

**Configuration File:**

```yaml
# .dlt-ibapi/paper_trading.yaml

# IB Connection (inherits from ib_gateway.yaml)
connection:
  host: 127.0.0.1
  port: 4002  # Paper trading port

# Signal generation
signals:
  days_ahead: 7
  min_dte: 7
  max_dte: 30
  atm_tolerance: 0.10
  option_type: C  # Calls only

# Risk management
risk:
  max_position_size: 1000.0
  max_total_exposure: 5000.0
  max_positions: 5
  max_positions_per_symbol: 2

# Exit conditions
exit:
  use_scheduled_exit: true
  profit_target_enabled: false
  profit_target_pct: 100.0
  stop_loss_enabled: false
  stop_loss_pct: -50.0
  min_dte_threshold: 3
  max_delta_threshold: 0.30

# Scheduler
schedule:
  scan_time: "09:00"
  entry_time: "15:00"
  exit_after_hours_time: "10:00"
  exit_pre_market_time: "16:00"
  monitoring_interval: 15  # minutes
  snapshot_interval: 15    # minutes

# Monitoring
monitoring:
  enable_alerts: true
  alert_email: user@example.com  # Optional
  dashboard_refresh: 60  # seconds
```

---

## Data Models

### CalendarSpreadPosition

```python
@dataclass
class CalendarSpreadPosition:
    """Represents an open or closed calendar spread position."""

    # Identifiers
    position_id: str              # UUID
    symbol: str                   # Underlying symbol

    # Earnings context
    earnings_date: date
    earnings_time: Literal["PRE_MARKET", "AFTER_HOURS", "UNKNOWN"]

    # Entry details
    entry_datetime: datetime
    spot_at_entry: float
    strike: float
    option_type: Literal["C", "P"]

    # Legs
    short_leg: OptionLeg
    long_leg: OptionLeg

    # Financials
    net_debit: float              # Entry cost
    current_value: float          # Current spread value
    unrealized_pnl: float         # Current P&L (open positions)
    realized_pnl: float           # Final P&L (closed positions)
    max_loss: float               # = net_debit (defined risk)

    # Greeks (net spread Greeks)
    delta: float
    gamma: float
    theta: float
    vega: float

    # Status
    status: Literal["PENDING", "OPEN", "CLOSED"]
    exit_datetime: Optional[datetime]
    exit_reason: Optional[str]    # TARGET, STOP, EXPIRATION, MANUAL, SCHEDULED

    # Metadata
    created_at: datetime
    updated_at: datetime
```

### OptionLeg

```python
@dataclass
class OptionLeg:
    """Represents one leg of a spread (short or long)."""

    # Contract details
    contract_id: int              # IB contract ID
    symbol: str
    strike: float
    expiry: date
    right: Literal["C", "P"]

    # Pricing
    entry_price: float
    current_price: float
    current_bid: float
    current_ask: float

    # Greeks (individual leg)
    delta: float
    gamma: float
    theta: float
    vega: float

    # Volatility
    current_iv: float             # Implied volatility

    # Metadata
    last_updated: datetime
```

### EarningsSignal

```python
@dataclass
class EarningsSignal:
    """Trading signal generated from earnings calendar."""

    # Signal ID
    signal_id: str                # UUID

    # Earnings event
    symbol: str
    earnings_date: date
    earnings_time: Literal["PRE_MARKET", "AFTER_HOURS", "UNKNOWN"]
    company_name: str

    # Entry/Exit timing
    entry_datetime: datetime      # When to enter position
    exit_datetime: datetime       # When to exit position

    # Market data availability
    has_option_data: bool
    has_spot_data: bool
    available_strikes: List[float]
    available_expirations: List[date]

    # Rejection (if filtered out)
    is_tradable: bool
    reason_rejected: Optional[str]  # If not tradable

    # Metadata
    created_at: datetime
```

### Trade

```python
@dataclass
class Trade:
    """Record of an order fill."""

    # Identifiers
    trade_id: str                 # UUID
    position_id: str              # Links to CalendarSpreadPosition

    # Timing
    timestamp: datetime

    # Trade details
    leg: Literal["SHORT", "LONG"]
    action: Literal["OPEN", "CLOSE"]

    # Contract
    symbol: str
    strike: float
    expiry: date
    right: Literal["C", "P"]

    # Fill
    quantity: int
    fill_price: float
    commission: float

    # IB order details
    ib_order_id: int
    ib_contract_id: int
```

---

## Implementation Phases

### Phase 1: Core Infrastructure (Foundation)
**Goal:** Build data models and storage layer

**Tasks:**
1. Define Pydantic models (`models.py`)
   - CalendarSpreadPosition
   - OptionLeg
   - EarningsSignal
   - Trade

2. Implement database layer (`database.py`)
   - PositionDatabase class
   - Parquet schemas
   - CRUD operations

3. Extend Greeks calculator (`greeks.py`)
   - calculate_option_greeks()
   - calculate_spread_greeks()
   - Reuse existing black_scholes.py

**Deliverables:**
- `src/dlt_ibapi/trading/models.py`
- `src/dlt_ibapi/trading/database.py`
- `src/dlt_ibapi/trading/greeks.py`
- Unit tests for all components

**Duration:** 2-3 days

---

### Phase 2: Signal & Execution (Entry/Exit)
**Goal:** Enable manual position opening and closing

**Tasks:**
1. Signal generator (`signals.py`)
   - EarningsSignalGenerator class
   - Reuse filter_tradable_earnings() from batch.py
   - Calculate entry/exit times

2. Order manager (`execution.py`)
   - PaperOrderManager class
   - IB API integration (ib-connector)
   - Spread order execution
   - Fill tracking

3. Position manager (`positions.py`)
   - PositionManager class
   - Update position values
   - Check exit conditions
   - P&L calculation

**Deliverables:**
- `src/dlt_ibapi/trading/signals.py`
- `src/dlt_ibapi/trading/execution.py`
- `src/dlt_ibapi/trading/positions.py`
- Integration tests with IB Gateway

**Duration:** 4-5 days

---

### Phase 3: Automation (Live Trading)
**Goal:** Automate signal scanning and order execution

**Tasks:**
1. Risk manager (`risk.py`)
   - RiskManager class
   - Position limits
   - Exposure checks

2. Scheduler (`scheduler.py`)
   - TradingScheduler class
   - APScheduler integration
   - Scan/Entry/Exit/Monitoring cycles

3. CLI interface (`cli/paper_trading.py`)
   - Typer commands
   - start/stop scheduler
   - Manual operations

**Deliverables:**
- `src/dlt_ibapi/trading/risk.py`
- `src/dlt_ibapi/trading/scheduler.py`
- `src/dlt_ibapi/cli/paper_trading.py`
- Configuration file support

**Duration:** 3-4 days

---

### Phase 4: Monitoring (Reporting)
**Goal:** Build reporting and monitoring tools

**Tasks:**
1. Reporter (`reporting.py`)
   - TradingReporter class
   - Position summaries
   - Performance stats
   - P&L charts
   - Alerts

2. Performance analytics
   - Sharpe ratio
   - Max drawdown
   - Win rate analysis

3. Alerting system
   - Risk violations
   - Expiration warnings
   - Data quality issues

**Deliverables:**
- `src/dlt_ibapi/trading/reporting.py`
- Dashboard CLI commands
- Daily report generation
- Alert notifications

**Duration:** 2-3 days

---

**Total Estimated Duration:** 11-15 days

---

## Technical Decisions

### 1. Why Parquet for Trade Storage?

**Decision:** Use Parquet files for position/trade data

**Rationale:**
- ✅ Consistent with existing data architecture (option bars, earnings)
- ✅ Time-series queries via DuckDB
- ✅ Easy backups and portability
- ✅ Schema evolution support
- ✅ Efficient storage with compression

**Alternative Considered:** SQLite
- ❌ Inconsistent with market data storage
- ❌ Less portable across environments
- ✅ Better for ACID transactions (not critical for paper trading)

---

### 2. Why NOT Use DLT for Trade Data?

**Decision:** Direct Parquet writes, not DLT resources

**Rationale:**
- DLT is for **data ingestion** (market data from IB)
- Paper trading is **application state** (transactional)
- Direct writes are simpler for CRUD operations
- DLT adds unnecessary complexity for transactional data

**Use DLT for:**
- Option bars backfill
- Earnings calendar loading
- Historical data ingestion

**Use direct Parquet for:**
- Position records
- Trade fills
- Snapshots

---

### 3. Greeks: Analytical vs IB API?

**Decision:** Use analytical Black-Scholes model

**Rationale:**
- ✅ Instant calculation (no API latency)
- ✅ Deterministic (reproducible results)
- ✅ No additional market data subscription costs
- ✅ Already implemented (`black_scholes.py`)

**IB API Greeks:**
- ❌ Requires market data subscription
- ❌ Slow (network round-trip)
- ❌ May differ from analytical model
- ✅ "Real" Greeks from IB's model (not critical for paper trading)

---

### 4. Order Execution: Individual vs Spread Orders?

**Decision:** Use IB COMBO spread orders

**Rationale:**
- ✅ Atomic execution (both legs fill or neither)
- ✅ Better pricing (market makers compete on spread)
- ✅ Single order to track (simpler fill logic)
- ✅ Professional approach

**Individual leg orders:**
- ❌ Risk: One leg fills, other doesn't (legging risk)
- ❌ Worse pricing (pay bid/ask on each leg)
- ✅ More flexible (can adjust legs independently)

---

### 5. Scheduling: Cron vs APScheduler?

**Decision:** Use APScheduler for Python-based scheduling

**Rationale:**
- ✅ Python-native (integrates with CLI)
- ✅ Programmatic control (start/stop via code)
- ✅ Timezone aware (Eastern Time)
- ✅ No external dependencies

**Cron:**
- ❌ Requires system-level setup
- ❌ Harder to test
- ✅ More robust for production (OS-level)
- ✅ Standard approach for servers

**Hybrid Approach (Future):**
- Development: APScheduler (easy iteration)
- Production: systemd timer or cron (more robust)

---

### 6. Position Sizing: Fixed vs Dynamic?

**Decision:** Start with fixed 1 contract per signal

**Rationale:**
- ✅ Simple and conservative
- ✅ Easy to reason about P&L
- ✅ Predictable capital usage
- ✅ Matches backtest approach

**Future Enhancement:**
- Kelly Criterion (optimal sizing based on edge)
- Fixed % of capital (scales with account size)
- Volatility-adjusted sizing

---

### 7. Exit Strategy: Scheduled vs Discretionary?

**Decision:** Scheduled exits as primary, with optional overrides

**Rationale:**
- ✅ Matches backtest methodology (scheduled exit after IV crush)
- ✅ Disciplined (removes emotion)
- ✅ Consistent across all positions
- ✅ Optional profit targets/stop losses for risk control

**Exit Priority:**
1. **Scheduled** (primary): Exit at predetermined time
2. **Expiration risk**: Close if short leg < 3 DTE
3. **Delta risk**: Close if moved too far from ATM
4. **Stop loss** (optional): Close if P&L < threshold
5. **Profit target** (optional): Close if P&L > threshold

---

## Testing Strategy

### Unit Tests

**Location:** `tests/unit/trading/`

**Coverage:**

```bash
# Data models
test_models.py
  - CalendarSpreadPosition serialization
  - OptionLeg validation
  - EarningsSignal creation

# Signal generation
test_signal_generator.py
  - filter_tradable_earnings logic
  - Entry/exit time calculation
  - Data availability checks

# Position management
test_position_manager.py
  - P&L calculation
  - Greeks calculation
  - Exit condition logic

# Risk management
test_risk_manager.py
  - Position size limits
  - Exposure limits
  - Risk checks

# Greeks
test_greeks.py
  - Black-Scholes calculations
  - Spread Greeks derivation
  - IV reverse calculation
```

**Mocking:**
- Mock IB API responses (ContractDetails, MarketData)
- Mock Parquet readers (OptionBarsReader, EarningsCalendarReader)
- Deterministic datetime (freeze time for tests)

---

### Integration Tests

**Location:** `tests/integration/trading/`

**Requirements:**
- IB Gateway running (Paper Trading port 4002)
- Test account with paper trading enabled

**Coverage:**

```bash
# Order execution
test_order_execution.py
  - Place spread order
  - Wait for fills
  - Handle order rejection

# Position lifecycle
test_position_lifecycle.py
  - Open position → Monitor → Close position
  - Full end-to-end flow

# Fill tracking
test_fill_tracking.py
  - Track partial fills
  - Handle multiple fills
  - Timeout handling

# Market data
test_market_data.py
  - Request option quotes
  - Handle stale data
  - Connection failures
```

**Test Helpers:**
```python
@pytest.fixture
def ib_runtime():
    """IB Gateway connection for integration tests."""
    from ib_connector import IBRuntime
    runtime = IBRuntime(host='127.0.0.1', port=4002)
    runtime.connect()
    yield runtime
    runtime.disconnect()

@pytest.fixture
def test_position_db(tmp_path):
    """Temporary position database for tests."""
    db_path = tmp_path / "paper_trading"
    return PositionDatabase(db_path=str(db_path))
```

---

### Simulation Tests (Backtest Mode)

**Purpose:** Run paper trading logic on historical data without IB

**Implementation:**
```bash
# CLI command
dlt-ibapi paper-trade backtest \
  --start-date 2025-11-01 \
  --end-date 2025-11-15 \
  --symbols TMC AMAT DIS \
  --output backtest_results.csv
```

**Workflow:**
1. Load historical earnings calendar
2. Generate signals using historical data
3. Simulate order execution using historical option prices
4. Calculate P&L using actual market prices
5. Compare to backtest results from notebook 04

**Validation:**
- Backtest P&L should match notebook results
- Signal count should match tradable earnings count
- Entry/exit timing should be consistent

---

## Deployment & Operations

### Environment Setup

**Prerequisites:**
```bash
# IB Gateway Paper Trading
# Port: 4002
# Account: Paper trading account

# Python environment
uv sync
uv add apscheduler tabulate
```

**Configuration:**
```bash
# Initialize config
dlt-ibapi init

# Edit paper trading config
vim .dlt-ibapi/paper_trading.yaml

# Test IB connection
dlt-ibapi test-connection --port 4002
```

---

### Running Paper Trading

**Development Mode:**
```bash
# Start scheduler in foreground
dlt-ibapi paper-trade start

# Logs displayed in terminal
# Ctrl+C to stop
```

**Production Mode:**
```bash
# Run as background service (systemd)
cat > /etc/systemd/system/dlt-paper-trading.service <<EOF
[Unit]
Description=DLT Paper Trading Scheduler
After=network.target

[Service]
Type=simple
User=trader
WorkingDirectory=/home/trader/trading_project/dlt-ibapi
ExecStart=/home/trader/.local/bin/uv run dlt-ibapi paper-trade start
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
sudo systemctl enable dlt-paper-trading
sudo systemctl start dlt-paper-trading

# Check status
sudo systemctl status dlt-paper-trading
```

---

### Monitoring

**Real-time Dashboard:**
```bash
# Watch active positions (refresh every 60s)
watch -n 60 dlt-ibapi paper-trade positions
```

**Daily Reports:**
```bash
# Generate daily report
dlt-ibapi paper-trade report --date 2025-11-16

# Email report (if configured)
dlt-ibapi paper-trade report --date 2025-11-16 --email
```

**Alerts:**
```bash
# Check for alerts
dlt-ibapi paper-trade alerts

# Example output:
# ⚠️ Position TMC_20251113 approaching exit (15 minutes)
# ⚠️ Position AMAT_20251113 delta risk (delta=0.35)
# ✅ No critical alerts
```

---

### Data Backup

**Backup Strategy:**

```bash
# Backup position data (daily)
#!/bin/bash
DATE=$(date +%Y%m%d)
BACKUP_DIR="/backups/paper_trading/$DATE"

mkdir -p "$BACKUP_DIR"
cp -r ./data/paper_trading/* "$BACKUP_DIR/"

# Compress and upload to cloud (optional)
tar -czf "$BACKUP_DIR.tar.gz" "$BACKUP_DIR"
aws s3 cp "$BACKUP_DIR.tar.gz" s3://my-bucket/backups/
```

**Retention:**
- Position data: Indefinite (audit trail)
- Snapshots: 90 days (rolling window)
- Trade logs: Indefinite (tax reporting)

---

### Troubleshooting

**Common Issues:**

1. **IB Gateway Disconnected**
   ```bash
   # Check connection
   dlt-ibapi test-connection --port 4002

   # Restart IB Gateway
   # Scheduler will auto-reconnect
   ```

2. **Missing Option Data**
   ```bash
   # Backfill data for symbol
   dlt-ibapi prepare-signal TMC --earnings-date 2025-11-20
   ```

3. **Position Stuck in PENDING**
   ```bash
   # Check fill status
   dlt-ibapi paper-trade show-position <position_id>

   # Manually close if needed
   dlt-ibapi paper-trade close-position <position_id> --reason MANUAL
   ```

4. **Scheduler Not Running**
   ```bash
   # Check logs
   journalctl -u dlt-paper-trading -f

   # Restart service
   sudo systemctl restart dlt-paper-trading
   ```

---

### Performance Monitoring

**Metrics to Track:**

1. **Execution Quality**
   - Fill rate (% of signals successfully executed)
   - Average slippage (fill price vs mid-price)
   - Order rejection rate

2. **Strategy Performance**
   - Win rate
   - Average P&L per trade
   - Sharpe ratio
   - Max drawdown

3. **System Health**
   - IB connection uptime
   - Data availability rate
   - Alert response time
   - Scheduler reliability

**Dashboard Metrics:**
```bash
dlt-ibapi paper-trade stats --period 30d

# Output:
# ================================================================================
# PAPER TRADING STATISTICS (Last 30 Days)
# ================================================================================
#
# Execution:
#   Signals Generated: 45
#   Trades Executed: 23 (51.1%)
#   Fill Rate: 98.3%
#   Avg Slippage: $0.03
#
# Performance:
#   Total Trades: 23
#   Win Rate: 60.9%
#   Avg P&L: $85.52
#   Total P&L: $1,967.00
#   Sharpe Ratio: 1.45
#   Max Drawdown: -12.3%
#
# System:
#   IB Uptime: 99.2%
#   Data Availability: 97.8%
#   Alerts Triggered: 5
# ================================================================================
```

---

## Appendix

### Dependencies

**New Dependencies to Add:**

```toml
[project.dependencies]
# Existing dependencies...
"apscheduler>=3.10.0"  # Scheduling
"tabulate>=0.9.0"      # CLI tables formatting
```

**Install:**
```bash
uv add apscheduler tabulate
```

---

### File Structure

```
src/dlt_ibapi/trading/
├── __init__.py
├── models.py              # Data models (Pydantic)
├── database.py            # Parquet storage layer
├── greeks.py              # Greeks calculation
├── signals.py             # Signal generation
├── execution.py           # Order execution
├── positions.py           # Position management
├── risk.py                # Risk management
├── scheduler.py           # Scheduler
└── reporting.py           # Monitoring & reporting

src/dlt_ibapi/cli/
└── paper_trading.py       # CLI commands

tests/unit/trading/
├── test_models.py
├── test_signal_generator.py
├── test_position_manager.py
├── test_greeks.py
└── test_risk_manager.py

tests/integration/trading/
├── test_order_execution.py
├── test_fill_tracking.py
└── test_position_lifecycle.py

.dlt-ibapi/
└── paper_trading.yaml     # Configuration

data/paper_trading/
├── positions/
├── trades/
├── signals/
└── snapshots/
```

---

### Configuration Reference

**Full Configuration File:**

```yaml
# .dlt-ibapi/paper_trading.yaml

# IB Gateway connection (inherits from ib_gateway.yaml)
connection:
  host: 127.0.0.1
  port: 4002              # Paper trading port
  client_id: 1
  ready_timeout: 10.0

# Signal generation
signals:
  days_ahead: 7           # Scan next 7 days
  min_dte: 7              # Minimum days to expiration
  max_dte: 30             # Maximum days to expiration
  atm_tolerance: 0.10     # ±10% for ATM strike
  option_type: C          # C=calls, P=puts, BOTH=both

# Order execution
orders:
  order_type: LMT         # Limit order
  time_in_force: DAY      # Cancel at market close
  fill_timeout: 60        # Seconds to wait for fills
  price_buffer: 0.05      # $0.05 buffer from mid-price
  retry_attempts: 3       # Max retries on failure

# Risk management
risk:
  # Position limits
  max_position_size: 1000.0         # Max $ per position
  max_total_exposure: 5000.0        # Max $ total
  max_positions: 5                  # Max concurrent positions
  max_positions_per_symbol: 2       # Max per underlying

  # Position-level risk
  max_delta_threshold: 0.30         # Close if abs(delta) > 0.30
  stop_loss_pct: -50.0              # Close if P&L < -50%
  min_dte_threshold: 3              # Close if short leg < 3 DTE

  # Portfolio-level risk
  max_net_delta: 1.0                # Max portfolio delta
  max_correlation: 0.70             # Max correlation

# Exit conditions
exit:
  use_scheduled_exit: true          # Primary exit method

  # Optional profit target
  profit_target_enabled: false
  profit_target_pct: 100.0          # 100% gain

  # Optional stop loss
  stop_loss_enabled: false
  stop_loss_pct: -50.0              # -50% loss

# Scheduler
schedule:
  timezone: America/New_York

  # Daily tasks
  scan_time: "09:00"                # Daily scan
  maintenance_time: "06:00"         # Daily maintenance

  # Entry/exit windows
  entry_time: "15:00"               # 3pm entry
  exit_after_hours_time: "10:00"   # 10am exit (AFTER_HOURS)
  exit_pre_market_time: "16:00"    # 4pm exit (PRE_MARKET)

  # Monitoring
  monitoring_interval: 15           # Minutes
  snapshot_interval: 15             # Minutes

# Monitoring
monitoring:
  enable_alerts: true
  alert_email: null                 # Optional email
  dashboard_refresh: 60             # Seconds

# Logging
logging:
  level: INFO                       # DEBUG, INFO, WARNING, ERROR
  file: ./logs/paper_trading.log
  max_size: 10MB                    # Rotate at 10MB
  backup_count: 5                   # Keep 5 backups

# Data paths
data:
  database_path: ./data
  datasets:
    stocks: stocks
    options: options
    option_chains: option_chains
    earnings: earnings
  paper_trading_path: ./data/paper_trading
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-11-16 | Initial specification |

---

**End of Specification**