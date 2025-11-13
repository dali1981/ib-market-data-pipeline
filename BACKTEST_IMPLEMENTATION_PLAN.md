# Earnings Calendar Spread Backtesting - Implementation Plan

**Date**: 2025-11-13
**Project**: dlt-ibapi + tools integration
**Goal**: Implement options backtesting by extending the existing `tools/` framework

---

## Executive Summary

This plan outlines how to add options backtesting capabilities to `dlt-ibapi` by extending the existing `tools/` backtesting framework rather than creating a new shared library.

**Key Decision**: EXTEND `tools/` instead of creating new library
- ✅ Reuses 11,671 lines of tested infrastructure
- ✅ Leverages Clean Architecture with dependency injection
- ✅ Inherits 34 test files and comprehensive testing infrastructure
- ✅ Gets vectorized execution mode (10-20x faster)
- ✅ Unified equity + options backtesting
- ✅ Saves ~6,000 lines of duplicate code

**Total Estimated Work**: ~6,300 lines over 8.5 days

---

## Architecture Overview

### Current State

```
tools/
├── backtests/          # Main backtest engine (equity-focused)
│   ├── engine.py       # Orchestrator (627 lines)
│   ├── executor.py     # Order execution (144 lines)
│   ├── pipeline.py     # Trading pipeline (151 lines)
│   └── models.py       # Result models (255 lines)
├── strategies/
│   └── base.py         # Strategy ABC (95 lines)
├── portfolio/
│   └── manager.py      # Position tracking (108 lines)
└── trading_cost/       # Transaction cost models (1,309 lines)

crypto_options/
└── strategy/
    ├── backtest.py     # Options backtest engine (~890 lines)
    ├── base.py         # Options-specific models (~500 lines)
    └── calendar_spread.py  # Calendar spread strategy (~700 lines)

dlt-ibapi/
├── repositories/       # Parquet data readers
│   ├── equity_bars.py
│   ├── option_bars.py
│   └── option_chain.py
└── earnings-calendar-dlt/
    └── api.py          # EarningsCalendarReader
```

### Target State

```
tools/
├── options/            # NEW - Options domain models
│   ├── models.py       # Position, Leg, Greeks, Signal
│   ├── pricing.py      # Black-Scholes, IV calculator
│   ├── spreads.py      # Spread construction
│   └── validators.py   # Options validation
├── backtests/          # EXTENDED - Options support
│   ├── engine.py       # (unchanged)
│   ├── executor.py     # + multi-leg execution
│   ├── pipeline.py     # + options strategy path
│   └── models.py       # (unchanged)
├── strategies/
│   ├── base.py         # (unchanged)
│   └── options/        # NEW - Options strategies
│       ├── base.py     # OptionsStrategy ABC
│       ├── calendar_spread.py
│       ├── pre_earnings.py
│       └── iv_based_entry.py
└── portfolio/
    └── manager.py      # EXTENDED - Multi-leg positions

dlt-ibapi/
└── backtest/           # NEW - IB integration
    ├── data_providers.py   # IB → tools adapters
    └── (CLI commands in cli_app.py)
```

---

## Phase 1: Add Options Domain Models to tools/ (~2,000 lines, 2 days)

### 1.1 Create Package Structure

**Location**: `/Users/mohamedali/trading_project/tools/src/tools/options/`

**Files to Create**:
```
options/
├── __init__.py         # Public API exports
├── models.py           # 500 lines - Core data models
├── pricing.py          # 800 lines - Black-Scholes Greeks
├── spreads.py          # 400 lines - Spread construction
└── validators.py       # 300 lines - Validation logic
```

### 1.2 Implementation: options/models.py (500 lines)

**Purpose**: Define options-specific domain models

**Key Classes**:

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Dict, Any, Literal
from enum import Enum

class PositionType(Enum):
    """Types of multi-leg positions."""
    CALENDAR_SPREAD = "calendar_spread"
    VERTICAL_SPREAD = "vertical_spread"
    IRON_CONDOR = "iron_condor"
    BUTTERFLY = "butterfly"
    NAKED_OPTION = "naked_option"

class SignalType(Enum):
    """Options signal types."""
    ENTER_SPREAD = "enter_spread"
    EXIT_POSITION = "exit_position"
    ADJUST_POSITION = "adjust_position"

@dataclass
class Leg:
    """Single leg of a multi-leg options position."""
    instrument: str  # Format: "AAPL-250117-150-C"
    side: Literal["BUY", "SELL"]
    quantity: Decimal
    entry_price: Decimal
    entry_timestamp: datetime
    commission: Decimal = Decimal("0.0")

    def current_pnl(self, current_price: float) -> float:
        """Calculate P&L for this leg."""
        pnl = (current_price - float(self.entry_price)) * float(self.quantity)
        return pnl if self.side == "BUY" else -pnl

@dataclass
class Greeks:
    """Options Greeks snapshot."""
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float
    iv: float  # Implied volatility
    timestamp: datetime

    def __add__(self, other: "Greeks") -> "Greeks":
        """Add Greeks (for portfolio aggregation)."""
        return Greeks(
            delta=self.delta + other.delta,
            gamma=self.gamma + other.gamma,
            vega=self.vega + other.vega,
            theta=self.theta + other.theta,
            rho=self.rho + other.rho,
            iv=(self.iv + other.iv) / 2,  # Average IV
            timestamp=max(self.timestamp, other.timestamp),
        )

@dataclass
class Position:
    """Multi-leg options position with Greeks tracking."""
    position_id: str
    legs: List[Leg]
    entry_greeks: Greeks
    current_greeks: Optional[Greeks] = None
    expiration: datetime
    position_type: PositionType
    entry_cost: Decimal = Decimal("0.0")
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

        # Calculate entry cost
        self.entry_cost = sum(
            leg.entry_price * leg.quantity + leg.commission
            for leg in self.legs
        )

    def mark_to_market(
        self,
        prices: Dict[str, float],
        greeks: Optional[Dict[str, Greeks]] = None,
    ) -> float:
        """Calculate current P&L."""
        pnl = Decimal("0.0")

        for leg in self.legs:
            if leg.instrument not in prices:
                continue

            current_price = Decimal(str(prices[leg.instrument]))
            leg_pnl = (current_price - leg.entry_price) * leg.quantity

            if leg.side == "SELL":
                leg_pnl = -leg_pnl

            pnl += leg_pnl

        return float(pnl)

    def update_greeks(self, greeks: Dict[str, Greeks]):
        """Update position Greeks from leg Greeks."""
        if not greeks:
            return

        # Aggregate Greeks across legs
        total_greeks = None
        for leg in self.legs:
            if leg.instrument not in greeks:
                continue

            leg_greeks = greeks[leg.instrument]
            multiplier = float(leg.quantity) * (1 if leg.side == "BUY" else -1)

            scaled_greeks = Greeks(
                delta=leg_greeks.delta * multiplier,
                gamma=leg_greeks.gamma * multiplier,
                vega=leg_greeks.vega * multiplier,
                theta=leg_greeks.theta * multiplier,
                rho=leg_greeks.rho * multiplier,
                iv=leg_greeks.iv,
                timestamp=leg_greeks.timestamp,
            )

            if total_greeks is None:
                total_greeks = scaled_greeks
            else:
                total_greeks = total_greeks + scaled_greeks

        self.current_greeks = total_greeks

    def days_to_expiry(self, current_date: datetime) -> int:
        """Calculate days until expiration."""
        return (self.expiration.date() - current_date.date()).days

@dataclass
class Signal:
    """Options strategy signal."""
    signal_type: SignalType
    spread_type: Optional[PositionType]
    legs: List[Leg]
    greeks_filter: Optional[Dict[str, tuple[float, float]]] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
```

**Dependencies**:
- Standard library only (dataclasses, datetime, decimal, typing, enum)

### 1.3 Implementation: options/pricing.py (800 lines)

**Purpose**: Black-Scholes pricing and Greeks calculation

**Key Classes**:

```python
from py_vollib.black_scholes import black_scholes
from py_vollib.black_scholes.greeks import delta, gamma, vega, theta, rho
from py_vollib.black_scholes.implied_volatility import implied_volatility
from scipy.optimize import newton
from .models import Greeks

class GreeksCalculator:
    """Calculate options Greeks using Black-Scholes model."""

    def calculate_greeks(
        self,
        spot: float,
        strike: float,
        time_to_expiry: float,  # years
        risk_free_rate: float,
        volatility: float,
        option_type: str,  # 'c' or 'p'
    ) -> Greeks:
        """Calculate all Greeks using py_vollib."""
        flag = 'c' if option_type.upper() in ['C', 'CALL'] else 'p'

        # Use py_vollib for Greeks
        d = delta(flag, spot, strike, time_to_expiry, risk_free_rate, volatility)
        g = gamma(flag, spot, strike, time_to_expiry, risk_free_rate, volatility)
        v = vega(flag, spot, strike, time_to_expiry, risk_free_rate, volatility)
        t = theta(flag, spot, strike, time_to_expiry, risk_free_rate, volatility)
        r = rho(flag, spot, strike, time_to_expiry, risk_free_rate, volatility)

        return Greeks(
            delta=d,
            gamma=g,
            vega=v / 100.0,  # py_vollib returns vega per 1% change, we want per 0.01
            theta=t / 365.0,  # py_vollib returns annualized, we want daily
            rho=r / 100.0,    # py_vollib returns per 1% rate change
            iv=volatility,
            timestamp=datetime.now(),
        )

    def implied_volatility_from_price(
        self,
        option_price: float,
        spot: float,
        strike: float,
        dte: int,
        risk_free_rate: float,
        option_type: str,
    ) -> float:
        """Calculate implied volatility from option market price."""
        if option_price <= 0:
            return 0.0

        flag = 'c' if option_type.upper() in ['C', 'CALL'] else 'p'
        time_to_expiry = dte / 365.0

        try:
            iv = implied_volatility(
                price=option_price,
                S=spot,
                K=strike,
                t=time_to_expiry,
                r=risk_free_rate,
                flag=flag,
            )
            return iv
        except Exception as e:
            # If IV calculation fails, return 0
            return 0.0

    def theoretical_price(
        self,
        spot: float,
        strike: float,
        time_to_expiry: float,
        risk_free_rate: float,
        volatility: float,
        option_type: str,
    ) -> float:
        """Calculate theoretical option price."""
        flag = 'c' if option_type.upper() in ['C', 'CALL'] else 'p'

        return black_scholes(
            flag=flag,
            S=spot,
            K=strike,
            t=time_to_expiry,
            r=risk_free_rate,
            sigma=volatility,
        )
```

**Dependencies**:
- py_vollib (Black-Scholes calculations)
- scipy (optimization for IV)

### 1.4 Implementation: options/spreads.py (400 lines)

**Purpose**: Construct multi-leg spreads from option chains

```python
from .models import Signal, Leg, SignalType, PositionType
from typing import List, Dict, Optional, Literal
from datetime import datetime
from decimal import Decimal

@dataclass
class OptionContract:
    """Single option contract from chain."""
    instrument: str
    underlying: str
    expiry: datetime
    strike: float
    right: str  # 'C' or 'P'
    bid: float
    ask: float
    mid: float
    volume: int
    open_interest: int

@dataclass
class OptionChain:
    """Option chain snapshot."""
    underlying: str
    timestamp: datetime
    contracts: List[OptionContract]

    def filter_by_expiry(self, expiry: datetime) -> List[OptionContract]:
        """Get contracts for specific expiration."""
        return [c for c in self.contracts if c.expiry == expiry]

    def filter_by_strike(self, strike: float) -> List[OptionContract]:
        """Get contracts for specific strike."""
        return [c for c in self.contracts if c.strike == strike]

class SpreadConstructor:
    """Build multi-leg option spreads."""

    def build_calendar_spread(
        self,
        underlying: str,
        spot_price: float,
        option_chain: OptionChain,
        front_dte: int = 14,
        back_dte: int = 42,
        strike_selection: Literal["ATM", "DELTA"] = "ATM",
        target_delta: Optional[float] = None,
        option_type: str = "C",
    ) -> Optional[Signal]:
        """Construct calendar spread (sell front, buy back)."""

        # Find suitable expirations
        front_expiry = self._find_expiry_near_dte(option_chain, front_dte)
        back_expiry = self._find_expiry_near_dte(option_chain, back_dte)

        if not front_expiry or not back_expiry:
            return None

        # Select strike
        if strike_selection == "ATM":
            strike = self._find_atm_strike(option_chain, spot_price, front_expiry)
        else:
            strike = self._find_delta_strike(
                option_chain, spot_price, front_expiry, target_delta
            )

        if not strike:
            return None

        # Find contracts
        front_contract = self._find_contract(
            option_chain, front_expiry, strike, option_type
        )
        back_contract = self._find_contract(
            option_chain, back_expiry, strike, option_type
        )

        if not front_contract or not back_contract:
            return None

        # Build signal
        legs = [
            Leg(
                instrument=front_contract.instrument,
                side="SELL",
                quantity=Decimal("1"),
                entry_price=Decimal(str(front_contract.mid)),
                entry_timestamp=option_chain.timestamp,
            ),
            Leg(
                instrument=back_contract.instrument,
                side="BUY",
                quantity=Decimal("1"),
                entry_price=Decimal(str(back_contract.mid)),
                entry_timestamp=option_chain.timestamp,
            ),
        ]

        return Signal(
            signal_type=SignalType.ENTER_SPREAD,
            spread_type=PositionType.CALENDAR_SPREAD,
            legs=legs,
            metadata={
                "underlying": underlying,
                "spot_price": spot_price,
                "strike": strike,
                "front_dte": (front_expiry - option_chain.timestamp).days,
                "back_dte": (back_expiry - option_chain.timestamp).days,
            },
        )

    def _find_atm_strike(
        self, chain: OptionChain, spot: float, expiry: datetime
    ) -> Optional[float]:
        """Find at-the-money strike."""
        contracts = chain.filter_by_expiry(expiry)
        if not contracts:
            return None

        # Find strike closest to spot
        return min(contracts, key=lambda c: abs(c.strike - spot)).strike

    def _find_expiry_near_dte(
        self, chain: OptionChain, target_dte: int
    ) -> Optional[datetime]:
        """Find expiration closest to target DTE."""
        expiries = list(set(c.expiry for c in chain.contracts))

        if not expiries:
            return None

        # Find expiry closest to target DTE
        return min(
            expiries,
            key=lambda exp: abs((exp - chain.timestamp).days - target_dte)
        )

    def _find_contract(
        self,
        chain: OptionChain,
        expiry: datetime,
        strike: float,
        right: str,
    ) -> Optional[OptionContract]:
        """Find specific contract."""
        for contract in chain.contracts:
            if (contract.expiry == expiry and
                contract.strike == strike and
                contract.right == right):
                return contract
        return None
```

### 1.5 Implementation: options/validators.py (300 lines)

**Purpose**: Validate options positions and constraints

```python
from .models import Position, Greeks
from typing import Dict, Tuple
from datetime import datetime, date

class OptionsValidator:
    """Validation for options-specific constraints."""

    def validate_expiration(
        self,
        position: Position,
        current_date: date,
        buffer_days: int = 2,
    ) -> bool:
        """Check if position is too close to expiration."""
        dte = (position.expiration.date() - current_date).days
        return dte > buffer_days

    def validate_greeks_limits(
        self,
        portfolio_greeks: Greeks,
        limits: Dict[str, Tuple[float, float]],
    ) -> bool:
        """Validate portfolio Greeks within risk limits."""

        greeks_dict = {
            'delta': portfolio_greeks.delta,
            'gamma': portfolio_greeks.gamma,
            'vega': portfolio_greeks.vega,
            'theta': portfolio_greeks.theta,
        }

        for greek_name, value in greeks_dict.items():
            if greek_name in limits:
                min_val, max_val = limits[greek_name]
                if not (min_val <= value <= max_val):
                    return False

        return True

    def validate_position_size(
        self,
        position: Position,
        portfolio_value: float,
        max_position_pct: float = 0.10,
    ) -> bool:
        """Validate position size vs portfolio value."""
        position_cost = float(position.entry_cost)
        max_cost = portfolio_value * max_position_pct

        return position_cost <= max_cost
```

### 1.6 Update tools/pyproject.toml

**Add Dependencies**:

```toml
[project.dependencies]
# ... existing dependencies
py_vollib = "^1.0.1"  # Black-Scholes Greeks calculation
scipy = "^1.11.0"     # Optimization for IV calculation
```

**Testing Dependencies**:

```toml
[project.optional-dependencies]
test = [
    # ... existing test deps
    "pytest-mock>=3.12.0",
]
```

---

## Phase 2: Extend Backtest Core Components (~1,500 lines, 2 days)

### 2.1 Extend portfolio/manager.py (~200 lines)

**Location**: `/Users/mohamedali/trading_project/tools/src/tools/portfolio/manager.py`

**Changes**: Add option positions support alongside equity positions

```python
# ADD to existing PortfolioManager class

from tools.options.models import Position, Greeks
from typing import Dict

class PortfolioManager:
    """Extended to support both equity and options positions."""

    # Existing fields
    cash: float
    equity_positions: Dict[str, float]  # symbol → quantity

    # NEW fields
    option_positions: Dict[str, Position]  # position_id → Position

    def __init__(self, cash: float = 0.0):
        self.cash = cash
        self.equity_positions = {}
        self.option_positions = {}  # NEW

    # MODIFY existing method
    def value(
        self,
        equity_prices: Dict[str, float],
        option_prices: Optional[Dict[str, float]] = None,  # NEW
        option_greeks: Optional[Dict[str, Greeks]] = None,  # NEW
    ) -> float:
        """Calculate total portfolio value (equity + options)."""

        # Equity positions (existing logic)
        equity_value = sum(
            qty * equity_prices.get(sym, 0.0)
            for sym, qty in self.equity_positions.items()
        )

        # Options positions (NEW)
        option_value = 0.0
        if option_prices and self.option_positions:
            for position in self.option_positions.values():
                position_pnl = position.mark_to_market(option_prices, option_greeks)
                option_value += position_pnl

        return self.cash + equity_value + option_value

    # NEW methods
    def update_option_position(self, position: Position):
        """Add or update option position."""
        self.option_positions[position.position_id] = position

    def close_option_position(self, position_id: str) -> Optional[Position]:
        """Close and remove option position."""
        return self.option_positions.pop(position_id, None)

    def portfolio_greeks(self, option_greeks: Dict[str, Greeks]) -> Greeks:
        """Calculate aggregate portfolio Greeks."""
        total_greeks = None

        for position in self.option_positions.values():
            position.update_greeks(option_greeks)

            if position.current_greeks:
                if total_greeks is None:
                    total_greeks = position.current_greeks
                else:
                    total_greeks = total_greeks + position.current_greeks

        # Return zero Greeks if no positions
        if total_greeks is None:
            total_greeks = Greeks(
                delta=0.0, gamma=0.0, vega=0.0,
                theta=0.0, rho=0.0, iv=0.0,
                timestamp=datetime.now(),
            )

        return total_greeks

    def close_expired_positions(self, current_date: date) -> List[Position]:
        """Auto-close positions at or past expiration."""
        expired = []

        for position_id, position in list(self.option_positions.items()):
            if position.expiration.date() <= current_date:
                closed = self.close_option_position(position_id)
                if closed:
                    expired.append(closed)

        return expired
```

### 2.2 Extend backtests/executor.py (~300 lines)

**Location**: `/Users/mohamedali/trading_project/tools/src/tools/backtests/executor.py`

**Changes**: Add multi-leg spread execution

```python
# ADD to existing SimulatedExecutor class

from tools.options.models import Signal, Position, SignalType, PositionType, Greeks
import uuid

class SimulatedExecutor:
    """Extended to execute multi-leg spread orders."""

    # ADD new method
    def execute_spread_order(
        self,
        signal: Signal,
        portfolio: PortfolioManager,
        option_prices: Dict[str, float],
        option_greeks: Dict[str, Greeks],
        timestamp: datetime,
        commission_per_contract: float = 0.65,
    ) -> Optional[Position]:
        """Execute multi-leg spread atomically (all-or-nothing)."""

        # 1. Check all legs can be filled
        total_debit = Decimal("0.0")

        for leg in signal.legs:
            price = option_prices.get(leg.instrument)
            if price is None:
                return None  # Cannot fill - missing price

            # Calculate leg cost (positive for buy, negative for sell)
            leg_cost = leg.entry_price * leg.quantity
            commission = Decimal(str(commission_per_contract)) * leg.quantity

            if leg.side == "BUY":
                total_debit += leg_cost + commission
            else:  # SELL
                total_debit -= leg_cost - commission  # Receive credit, pay commission

        # 2. Check sufficient capital (if net debit)
        if total_debit > 0 and Decimal(str(portfolio.cash)) < total_debit:
            return None  # Insufficient capital

        # 3. Execute all legs atomically
        position = Position(
            position_id=f"pos_{uuid.uuid4().hex[:8]}",
            legs=signal.legs,
            entry_greeks=self._calculate_position_greeks(signal.legs, option_greeks),
            expiration=self._get_earliest_expiration(signal.legs),
            position_type=signal.spread_type,
            metadata=signal.metadata.copy() if signal.metadata else {},
        )

        # Update cash
        portfolio.cash -= float(total_debit)

        # Add position
        portfolio.update_option_position(position)

        return position

    def _calculate_position_greeks(
        self,
        legs: List[Leg],
        option_greeks: Dict[str, Greeks],
    ) -> Greeks:
        """Calculate net Greeks for position."""
        total_greeks = None

        for leg in legs:
            if leg.instrument not in option_greeks:
                continue

            leg_greeks = option_greeks[leg.instrument]
            multiplier = float(leg.quantity) * (1 if leg.side == "BUY" else -1)

            scaled_greeks = Greeks(
                delta=leg_greeks.delta * multiplier,
                gamma=leg_greeks.gamma * multiplier,
                vega=leg_greeks.vega * multiplier,
                theta=leg_greeks.theta * multiplier,
                rho=leg_greeks.rho * multiplier,
                iv=leg_greeks.iv,
                timestamp=leg_greeks.timestamp,
            )

            if total_greeks is None:
                total_greeks = scaled_greeks
            else:
                total_greeks = total_greeks + scaled_greeks

        return total_greeks or Greeks(
            delta=0, gamma=0, vega=0, theta=0, rho=0, iv=0,
            timestamp=datetime.now()
        )

    def _get_earliest_expiration(self, legs: List[Leg]) -> datetime:
        """Get earliest expiration from legs."""
        # Parse expiration from instrument name: "AAPL-250117-150-C"
        # Format: SYMBOL-YYMMDD-STRIKE-RIGHT

        expirations = []
        for leg in legs:
            parts = leg.instrument.split('-')
            if len(parts) >= 2:
                exp_str = parts[1]  # YYMMDD
                expiry = datetime.strptime(exp_str, "%y%m%d")
                expirations.append(expiry)

        return min(expirations) if expirations else datetime.now()
```

### 2.3 Extend backtests/pipeline.py (~200 lines)

**Location**: `/Users/mohamedali/trading_project/tools/src/tools/backtests/pipeline.py`

**Changes**: Add options strategy execution path

```python
# MODIFY execute_at method

def execute_at(
    self,
    timestamp: datetime,
    portfolio: PortfolioManager,
    equity_prices: Dict[str, float],
    data_provider: Any,
    interval: str,
    lookback_bars: int,
    # NEW parameters
    option_prices: Optional[Dict[str, float]] = None,
    option_greeks: Optional[Dict[str, Greeks]] = None,
    option_chain_provider: Optional[Any] = None,
) -> List[Union[Order, Signal]]:
    """Execute strategy pipeline at timestamp."""

    # Check if this is an options strategy
    if hasattr(self.strategy, 'is_options_strategy') and self.strategy.is_options_strategy:
        # NEW: Options strategy path
        signals = self.strategy.generate_signals(
            data_provider=data_provider,
            option_chain_provider=option_chain_provider,
            current_greeks=option_greeks or {},
            portfolio_greeks=portfolio.portfolio_greeks(option_greeks or {}),
            timestamp=timestamp,
            lookback_bars=lookback_bars,
        )
        return signals  # List[Signal]

    else:
        # Existing: Equity factor strategy path
        result = self.strategy.generate_signals(
            data_provider=data_provider,
            lookback_bars=lookback_bars,
            interval=interval,
        )

        weights = self.constructor.construct_portfolio(result)
        constrained = self.sizer.apply_constraints(
            weights, equity_prices, portfolio.cash
        )
        orders = self.generator.generate_orders(
            constrained, portfolio, equity_prices, portfolio.cash
        )

        return orders  # List[Order]
```

### 2.4 Create strategies/options/base.py (~300 lines)

**Location**: `/Users/mohamedali/trading_project/tools/src/tools/strategies/options/base.py`

**Purpose**: Abstract base class for options strategies

```python
from abc import ABC, abstractmethod
from tools.options.models import Signal, Position, Greeks
from typing import List, Dict, Any, Optional
from datetime import datetime

class OptionsStrategy(ABC):
    """Base class for options strategies."""

    is_options_strategy = True  # Flag for pipeline

    @abstractmethod
    def generate_signals(
        self,
        data_provider: Any,
        option_chain_provider: Any,
        current_greeks: Dict[str, Greeks],
        portfolio_greeks: Greeks,
        timestamp: datetime,
        lookback_bars: int = 252,
    ) -> List[Signal]:
        """
        Generate options signals (spreads to enter).

        Args:
            data_provider: Provides market data (prices, bars)
            option_chain_provider: Provides option chains
            current_greeks: Current Greeks for all options
            portfolio_greeks: Aggregated portfolio Greeks
            timestamp: Current backtest timestamp
            lookback_bars: Historical data lookback

        Returns:
            List of signals (spreads to enter)
        """
        pass

    @abstractmethod
    def should_exit_position(
        self,
        position: Position,
        current_greeks: Greeks,
        pnl: float,
        timestamp: datetime,
    ) -> bool:
        """
        Determine if a position should be closed.

        Args:
            position: The position to evaluate
            current_greeks: Current Greeks for the position
            pnl: Current profit/loss
            timestamp: Current timestamp

        Returns:
            True if position should be closed
        """
        pass

    def generate_exit_signals(
        self,
        portfolio_positions: Dict[str, Position],
        option_prices: Dict[str, float],
        option_greeks: Dict[str, Greeks],
        timestamp: datetime,
    ) -> List[str]:
        """
        Generate exit signals for existing positions.

        Args:
            portfolio_positions: Current positions
            option_prices: Current option prices
            option_greeks: Current option Greeks
            timestamp: Current timestamp

        Returns:
            List of position IDs to close
        """
        positions_to_close = []

        for position_id, position in portfolio_positions.items():
            # Calculate current P&L
            pnl = position.mark_to_market(option_prices, option_greeks)

            # Update position Greeks
            position.update_greeks(option_greeks)

            # Check exit criteria
            if self.should_exit_position(
                position=position,
                current_greeks=position.current_greeks,
                pnl=pnl,
                timestamp=timestamp,
            ):
                positions_to_close.append(position_id)

        return positions_to_close
```

---

## Phase 3: Implement Earnings Calendar Spread Strategies (~1,500 lines, 2 days)

### 3.1 CalendarSpreadStrategy (500 lines)

**Location**: `/Users/mohamedali/trading_project/tools/src/tools/strategies/options/calendar_spread.py`

See detailed implementation in plan above.

### 3.2 PreEarningsCalendarSpreadStrategy (500 lines)

**Location**: `/Users/mohamedali/trading_project/tools/src/tools/strategies/options/pre_earnings.py`

See detailed implementation in plan above.

### 3.3 IVBasedCalendarSpreadStrategy (500 lines)

**Location**: `/Users/mohamedali/trading_project/tools/src/tools/strategies/options/iv_based_entry.py`

See detailed implementation in plan above.

---

## Phase 4: IB Integration in dlt-ibapi (~500 lines, 1 day)

### 4.1 Create Data Providers (300 lines)

**Location**: `/Users/mohamedali/trading_project/dlt-ibapi/src/dlt_ibapi/backtest/data_providers.py`

See detailed implementation in plan above.

### 4.2 Add CLI Commands (200 lines)

**Location**: `/Users/mohamedali/trading_project/dlt-ibapi/src/dlt_ibapi/cli_app.py`

See detailed implementation in plan above.

---

## Phase 5: Testing (~500 lines, 1 day)

### 5.1 Unit Tests (300 lines)

**Files**:
- `tools/tests/options/test_models.py`
- `tools/tests/options/test_greeks.py`
- `tools/tests/options/test_spreads.py`
- `tools/tests/portfolio/test_manager_options.py`

### 5.2 Integration Tests (200 lines)

**Files**:
- `dlt-ibapi/tests/integration/test_ib_data_provider.py`
- `dlt-ibapi/tests/integration/test_backtest_e2e.py`

---

## Phase 6: Documentation (~300 lines, 0.5 days)

### 6.1 Notebook Example

**Location**: `dlt-ibapi/notebooks/03_backtest_earnings_spreads.ipynb`

### 6.2 Documentation

**Location**: `dlt-ibapi/docs/BACKTEST_GUIDE.md`

---

## Implementation Checklist

- [ ] Phase 1.1: Create tools/options/ package structure
- [ ] Phase 1.2: Implement options/models.py
- [ ] Phase 1.3: Implement options/pricing.py
- [ ] Phase 1.4: Implement options/spreads.py
- [ ] Phase 1.5: Implement options/validators.py
- [ ] Phase 1.6: Add py_vollib dependency
- [ ] Phase 2.1: Extend portfolio/manager.py
- [ ] Phase 2.2: Extend backtests/executor.py
- [ ] Phase 2.3: Extend backtests/pipeline.py
- [ ] Phase 2.4: Create strategies/options/base.py
- [ ] Phase 3.1: Implement CalendarSpreadStrategy
- [ ] Phase 3.2: Implement PreEarningsCalendarSpreadStrategy
- [ ] Phase 3.3: Implement IVBasedCalendarSpreadStrategy
- [ ] Phase 4.1: Create IB data providers
- [ ] Phase 4.2: Add backtest CLI commands
- [ ] Phase 5.1: Write unit tests
- [ ] Phase 5.2: Write integration tests
- [ ] Phase 6.1: Create notebook example
- [ ] Phase 6.2: Write documentation

---

## Dependencies

### tools/ New Dependencies

```toml
py_vollib = "^1.0.1"  # Black-Scholes Greeks
scipy = "^1.11.0"     # Optimization for IV
```

### dlt-ibapi New Dependencies

```toml
tools = {path = "../tools", develop = true}
```

---

## Success Criteria

1. **Functionality**:
   - ✅ Can backtest calendar spreads around earnings
   - ✅ Three strategy variants working (generic, pre-earnings, IV-based)
   - ✅ Greeks calculated accurately
   - ✅ Multi-leg execution working
   - ✅ Position tracking with P&L

2. **Testing**:
   - ✅ Unit tests passing for Greeks calculations
   - ✅ Integration tests passing for end-to-end backtest
   - ✅ Test coverage > 80%

3. **Performance**:
   - ✅ Backtest runs without errors
   - ✅ Results match expectations (reasonable Sharpe, drawdown)
   - ✅ Greeks calculations efficient (< 1ms per option)

4. **Documentation**:
   - ✅ API documented with docstrings
   - ✅ User guide complete
   - ✅ Notebook example working

---

## Risk Mitigation

**Risk 1: Breaking existing tools/ functionality**
- Mitigation: All changes are additive (new modules, optional parameters)
- Mitigation: Run existing tools/ tests after each phase

**Risk 2: Greeks calculation accuracy**
- Mitigation: Validate against known Black-Scholes values
- Mitigation: Cross-check with py_vollib examples

**Risk 3: Integration complexity**
- Mitigation: Start with simple test cases
- Mitigation: Incremental integration (one strategy at a time)

**Risk 4: Performance issues**
- Mitigation: Profile Greeks calculations
- Mitigation: Cache IV calculations where possible

---

## Post-Implementation

### Future Enhancements

1. **Additional Strategies**:
   - Iron condors
   - Butterflies
   - Delta-neutral portfolios

2. **Advanced Features**:
   - Greeks P&L attribution
   - IV surface modeling
   - Optimization framework (parameter sweep)

3. **Live Trading**:
   - Extend tools/ live trading for options
   - Real-time Greeks updates
   - Position monitoring

### Refactoring Opportunities

1. **crypto_options Migration**:
   - Port crypto_options strategies to tools/
   - Deprecate crypto_options/strategy/backtest.py
   - Use unified testing infrastructure

2. **Performance Optimization**:
   - Vectorize Greeks calculations
   - Parallel option pricing
   - Caching strategies

---

## Timeline Estimate

**Total: 8.5 days**

- Phase 1: 2 days (Options models)
- Phase 2: 2 days (Extend backtest core)
- Phase 3: 2 days (Implement strategies)
- Phase 4: 1 day (IB integration)
- Phase 5: 1 day (Testing)
- Phase 6: 0.5 days (Documentation)

---

## Notes

- This plan prioritizes code reuse over greenfield development
- All changes to tools/ are backward compatible
- The architecture supports future expansion (more strategies, more instruments)
- Testing is integrated throughout (not bolted on at the end)

---

**Last Updated**: 2025-11-13
**Status**: Ready for Implementation
