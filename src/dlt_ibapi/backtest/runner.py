"""
Options backtest runner for earnings calendar spread strategies.

Provides a simplified backtest execution engine optimized for options:
- Multi-leg spread execution
- Greeks tracking and monitoring
- Position expiration handling
- Performance metrics calculation
"""

from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, date, timedelta
from decimal import Decimal
import polars as pl

from tools.portfolio import PortfolioManager
from tools.backtests.executor import SimulatedExecutor
from tools.options.models import Position, Greeks, Signal
from tools.strategies.options.base import OptionsStrategy

from dlt_ibapi.backtest.validation import BacktestDataValidator
from dlt_ibapi.backtest.earnings_loader import EarningsEvent
from dlt_ibapi.backtest.data_providers import BacktestDataRequirements, EarningsCalendarProvider
from dlt_ibapi.utils.logging import get_logger

logger = get_logger(__name__)


class OptionsBacktestResult:
    """
    Results from an options backtest.

    Attributes:
        equity_curve: DataFrame with portfolio value over time
        trades: List of executed trades
        final_value: Final portfolio value
        total_return: Total return (decimal)
        total_return_pct: Total return (percentage)
        num_trades: Number of trades executed
        winning_trades: Number of winning trades
        losing_trades: Number of losing trades
        avg_win: Average winning trade P&L
        avg_loss: Average losing trade P&L
        max_drawdown: Maximum drawdown (decimal)
        max_drawdown_pct: Maximum drawdown (percentage)
    """

    def __init__(
        self,
        equity_curve: pl.DataFrame,
        trades: List[Dict[str, Any]],
        initial_capital: float,
        final_value: float,
    ):
        self.equity_curve = equity_curve
        self.trades = trades
        self.initial_capital = initial_capital
        self.final_value = final_value

        # Calculate metrics
        self.total_return = final_value - initial_capital
        self.total_return_pct = (self.total_return / initial_capital) * 100

        # Trade statistics
        self.num_trades = len(trades)
        winning = [t for t in trades if t.get('pnl', 0) > 0]
        losing = [t for t in trades if t.get('pnl', 0) < 0]

        self.winning_trades = len(winning)
        self.losing_trades = len(losing)
        self.avg_win = sum(t['pnl'] for t in winning) / len(winning) if winning else 0
        self.avg_loss = sum(t['pnl'] for t in losing) / len(losing) if losing else 0

        # Drawdown
        self._calculate_drawdown()

    def _calculate_drawdown(self):
        """Calculate maximum drawdown from equity curve."""
        if self.equity_curve.is_empty():
            self.max_drawdown = 0.0
            self.max_drawdown_pct = 0.0
            return

        values = self.equity_curve['portfolio_value'].to_list()
        peak = values[0]
        max_dd = 0.0

        for value in values:
            if value > peak:
                peak = value
            dd = peak - value
            if dd > max_dd:
                max_dd = dd

        self.max_drawdown = max_dd
        self.max_drawdown_pct = (max_dd / peak * 100) if peak > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert results to dictionary for export."""
        return {
            'initial_capital': self.initial_capital,
            'final_value': self.final_value,
            'total_return': self.total_return,
            'total_return_pct': self.total_return_pct,
            'num_trades': self.num_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': (self.winning_trades / self.num_trades * 100) if self.num_trades > 0 else 0,
            'avg_win': self.avg_win,
            'avg_loss': self.avg_loss,
            'profit_factor': abs(self.avg_win / self.avg_loss) if self.avg_loss != 0 else 0,
            'max_drawdown': self.max_drawdown,
            'max_drawdown_pct': self.max_drawdown_pct,
        }


class OptionsBacktestRunner:
    """
    Options backtest runner for earnings calendar spread strategies.

    Uses daily-collected option chain snapshots combined with option bars
    to backtest multi-leg option strategies.

    **Data Requirements**:
    1. **Option Chain Snapshots**: Daily snapshots of available options (metadata)
       - Collected via: `dlt-ibapi snapshot SYMBOL --date YYYY-MM-DD`
       - Stored in: `data/option_chains/*.parquet`
       - Contains: Available strikes, expirations (no prices)

    2. **Option Bars**: OHLCV data for specific contracts
       - Collected via: `dlt-ibapi backfill-options SYMBOL ...`
       - Must be collected BEFORE expiration
       - Contains: open, high, low, close, volume

    3. **Equity Bars**: Underlying spot prices
       - Collected via: `dlt-ibapi backfill-equity SYMBOL`
       - Contains: spot price, volume

    **Validation**: Runner validates data availability before execution.
    Dates without complete data are automatically skipped with clear logging.

    Example:
        >>> from dlt_ibapi.backtest import (
        ...     IBBacktestDataProvider,
        ...     EarningsCalendarProvider,
        ...     OptionsChainProvider,
        ...     OptionsBacktestRunner,
        ... )
        >>> from tools.strategies.options import IVBasedCalendarSpreadStrategy
        >>>
        >>> # Initialize data providers
        >>> data_provider = IBBacktestDataProvider("./data")
        >>> chain_provider = OptionsChainProvider(data_provider.option_chain_reader)
        >>> earnings_provider = EarningsCalendarProvider("./data/earnings")
        >>>
        >>> # Create strategy
        >>> strategy = IVBasedCalendarSpreadStrategy(config)
        >>>
        >>> # Run backtest with validation
        >>> runner = OptionsBacktestRunner(
        ...     strategy=strategy,
        ...     data_provider=data_provider,
        ...     option_chain_provider=chain_provider,
        ...     initial_capital=100000,
        ...     earnings_calendar_provider=earnings_provider,
        ... )
        >>> result = runner.run(
        ...     start_date=date(2024, 1, 1),
        ...     end_date=date(2024, 12, 31),
        ...     validate_data=True,  # Pre-flight validation
        ... )
        >>> print(f"Return: {result.total_return_pct:.2f}%")
    """

    def __init__(
        self,
        strategy: OptionsStrategy,
        data_provider: "IBBacktestDataProvider",
        option_chain_provider: "OptionsChainProvider",
        initial_capital: float,
        commission_per_contract: float = 0.65,
        earnings_calendar_provider: Optional[EarningsCalendarProvider] = None,
    ):
        """
        Initialize options backtest runner.

        Args:
            strategy: Options strategy to backtest
            data_provider: Data provider for market data
            option_chain_provider: Provider for option chains
            initial_capital: Starting capital
            commission_per_contract: Commission per option contract
            earnings_calendar_provider: Optional provider for earnings calendar data
                (used for pre-flight validation of earnings-based strategies)
        """
        self.strategy = strategy
        self.data_provider = data_provider
        self.option_chain_provider = option_chain_provider
        self.initial_capital = initial_capital
        self.commission_per_contract = commission_per_contract
        self.earnings_calendar_provider = earnings_calendar_provider

        # Get symbols from strategy config
        self.symbols = strategy.config.underlying_symbols

        # Initialize components
        self.portfolio = PortfolioManager(
            initial_cash=initial_capital,
            symbols=self.symbols,
        )
        self.executor = SimulatedExecutor(
            cost_bps=0.0,  # Options use per-contract fees
            trade_recorder=None,
        )

        # Recording
        self.equity_curve_data = []
        self.trades = []

    def run(
        self,
        start_date: date,
        end_date: date,
        earnings_events: Optional[List[EarningsEvent]] = None,
        validate_data: bool = True,
    ) -> OptionsBacktestResult:
        """
        Run options backtest.

        Args:
            start_date: Backtest start date
            end_date: Backtest end date
            earnings_events: Optional list of earnings events to validate
                (if not provided and earnings_calendar_provider is available,
                events will be loaded automatically)
            validate_data: Whether to run pre-flight data validation
                (recommended for earnings-based strategies)

        Returns:
            OptionsBacktestResult with performance metrics

        Raises:
            ValueError: If validation is enabled and no valid events exist
        """
        logger.info(
            f"Starting options backtest: {start_date} → {end_date} "
            f"({len(self.symbols)} symbols, ${self.initial_capital:,.0f} capital)"
        )

        # Generate trading days (business days only)
        current_date = start_date
        trading_days = []

        while current_date <= end_date:
            # Skip weekends
            if current_date.weekday() < 5:  # Monday=0, Friday=4
                trading_days.append(current_date)
            current_date += timedelta(days=1)

        logger.info(f"Backtest will run over {len(trading_days)} trading days")

        # Pre-flight validation (if enabled and earnings events available)
        if validate_data and (earnings_events or self.earnings_calendar_provider):
            self._run_validation(earnings_events, start_date, end_date)

        # Main backtest loop
        for current_date in trading_days:
            timestamp = datetime.combine(current_date, datetime.min.time())
            self._execute_day(timestamp)

        # Create results
        equity_df = pl.DataFrame(self.equity_curve_data)

        result = OptionsBacktestResult(
            equity_curve=equity_df,
            trades=self.trades,
            initial_capital=self.initial_capital,
            final_value=self.portfolio.cash,
        )

        logger.info(
            f"Backtest complete: {result.num_trades} trades, "
            f"{result.total_return_pct:.2f}% return"
        )

        return result

    def _run_validation(
        self,
        earnings_events: Optional[List[EarningsEvent]],
        start_date: date,
        end_date: date,
    ):
        """
        Run pre-flight data validation for earnings-based backtest.

        Validates that all required data is available:
        - Equity bars with sufficient coverage
        - Option chain snapshots for earnings dates
        - Option contracts for target DTE ranges
        - Option bars for all required contracts

        Args:
            earnings_events: List of earnings events to validate (if None, loads from provider)
            start_date: Backtest start date
            end_date: Backtest end date

        Raises:
            ValueError: If no valid events exist with complete data
        """
        logger.info("=" * 60)
        logger.info("Running pre-flight data validation...")
        logger.info("=" * 60)

        # Get earnings events
        if earnings_events is None:
            if self.earnings_calendar_provider is None:
                logger.warning("No earnings events provided and no earnings calendar provider available")
                return

            # Load earnings events from provider
            earnings_events = self.earnings_calendar_provider.get_upcoming_earnings(
                days_ahead=(end_date - start_date).days,
                timestamp=datetime.combine(start_date, datetime.min.time()),
            )

            if not earnings_events:
                logger.warning(f"No earnings events found in date range {start_date} to {end_date}")
                return

            # Convert to EarningsEvent objects if needed
            earnings_events_typed = []
            for event in earnings_events:
                if isinstance(event, EarningsEvent):
                    earnings_events_typed.append(event)
                elif isinstance(event, dict):
                    # Convert dict to EarningsEvent
                    earnings_events_typed.append(EarningsEvent(
                        symbol=event["symbol"],
                        earnings_date=event["earnings_date"],
                        earnings_time=event.get("earnings_time", "UNKNOWN"),
                        company_name=event.get("company_name", ""),
                        eps_forecast=event.get("eps_forecast"),
                        fiscal_quarter=event.get("fiscal_quarter"),
                    ))
            earnings_events = earnings_events_typed

        # Filter events by symbols (only validate symbols we're trading)
        events_to_validate = [e for e in earnings_events if e.symbol in self.symbols]

        if not events_to_validate:
            logger.warning(
                f"No earnings events found for tracked symbols: {', '.join(self.symbols)}"
            )
            return

        logger.info(f"Validating {len(events_to_validate)} earnings events for {len(self.symbols)} symbols")

        # Create requirements from strategy config
        requirements = BacktestDataRequirements()

        # Override with strategy config if available
        if hasattr(self.strategy.config, 'front_month_dte'):
            requirements.front_month_dte = self.strategy.config.front_month_dte
        if hasattr(self.strategy.config, 'back_month_dte'):
            requirements.back_month_dte = self.strategy.config.back_month_dte
        if hasattr(self.strategy.config, 'min_dte'):
            requirements.front_month_dte = (self.strategy.config.min_dte, requirements.front_month_dte[1])
        if hasattr(self.strategy.config, 'max_dte'):
            requirements.back_month_dte = (requirements.back_month_dte[0], self.strategy.config.max_dte)

        # Initialize validator
        validator = BacktestDataValidator(
            equity_reader=self.data_provider.equity_reader,
            option_bars_reader=self.data_provider.option_bars_reader,
            option_chain_reader=self.data_provider.option_chain_reader,
        )

        # Run validation
        validation_result = validator.validate_all(
            earnings_events=events_to_validate,
            requirements=requirements,
        )

        # Log results
        logger.info("-" * 60)
        logger.info(f"Validation Results:")
        logger.info(f"  Total events:     {validation_result.total_events}")
        logger.info(f"  Valid events:     {validation_result.valid_events}")
        logger.info(f"  Invalid events:   {validation_result.invalid_events}")
        logger.info(f"  Success rate:     {validation_result.valid_events / validation_result.total_events * 100:.1f}%")
        logger.info("-" * 60)

        if validation_result.invalid_symbols:
            logger.warning("Symbols with missing data:")
            for symbol, reason in validation_result.invalid_symbols.items():
                logger.warning(f"  {symbol}: {reason}")

        if validation_result.skip_reasons:
            logger.warning("Reasons for skipping events:")
            for reason, count in validation_result.skip_reasons.items():
                logger.warning(f"  {reason}: {count} events")

        # Raise error if no valid events
        if validation_result.valid_events == 0:
            raise ValueError(
                f"No valid earnings events with complete data found.\n"
                f"Validated {validation_result.total_events} events, all failed validation.\n"
                f"Common issues:\n"
                f"  1. Missing option chain snapshots (run: dlt-ibapi snapshot SYMBOL --date YYYY-MM-DD)\n"
                f"  2. Missing equity bars (run: dlt-ibapi backfill-equity SYMBOL)\n"
                f"  3. Missing option bars (run: dlt-ibapi backfill-options SYMBOL ...)\n"
                f"Check validation warnings above for specific issues."
            )

        logger.info(f"✓ Validation passed: {validation_result.valid_events} events have complete data")
        logger.info("=" * 60)

    def _execute_day(self, timestamp: datetime):
        """
        Execute backtest logic for a single trading day.

        Steps:
        1. Get market data (spot prices, option chains, Greeks)
        2. Check for position expirations
        3. Check for position exits
        4. Generate new entry signals
        5. Execute entry signals
        6. Record portfolio snapshot
        """
        current_date = timestamp.date()

        # 1. Get market data
        spot_prices = self._get_spot_prices(timestamp)
        option_chains = self._get_option_chains(timestamp)

        # Skip if no data available
        if not spot_prices or not option_chains:
            return

        # 2. Handle expirations
        self._handle_expirations(current_date)

        # 3. Check for exits
        option_prices = {}
        option_greeks = {}

        # Get prices and Greeks for all open positions
        for position_id, position in list(self.portfolio.option_positions.items()):
            for leg in position.legs:
                # Get option price
                price = self.data_provider.get_option_prices(
                    [leg.instrument], timestamp
                ).get(leg.instrument)

                if price is not None:
                    option_prices[leg.instrument] = price

                # Get Greeks
                greeks = self.data_provider.get_greeks(
                    [leg.instrument], timestamp
                ).get(leg.instrument)

                if greeks is not None:
                    option_greeks[leg.instrument] = greeks

            # Update position Greeks
            position.update_greeks(option_greeks)

            # Calculate P&L
            pnl = position.mark_to_market(option_prices, option_greeks)

            # Check if should exit
            if position.current_greeks:
                should_exit = self.strategy.should_exit_position(
                    position=position,
                    current_greeks=position.current_greeks,
                    pnl=pnl,
                    timestamp=timestamp,
                )

                if should_exit:
                    self._close_position(position, option_prices, timestamp, "strategy_exit")

        # 4. Generate new signals
        portfolio_greeks = self.portfolio.portfolio_greeks(option_greeks)

        try:
            signals = self.strategy.generate_signals(
                data_provider=self.data_provider,
                option_chain_provider=self.option_chain_provider,
                current_greeks=option_greeks,
                portfolio_greeks=portfolio_greeks,
                timestamp=timestamp,
                lookback_bars=252,
            )
        except Exception as e:
            logger.warning(f"Strategy failed at {timestamp}: {e}")
            signals = []

        # 5. Execute entry signals
        for signal in signals:
            self._execute_signal(signal, option_prices, option_greeks, timestamp)

        # 6. Record snapshot
        total_value = self.portfolio.cash

        # Add unrealized P&L from open positions
        for position in self.portfolio.option_positions.values():
            total_value += position.mark_to_market(option_prices, option_greeks)

        self.equity_curve_data.append({
            'timestamp': timestamp,
            'portfolio_value': total_value,
            'cash': self.portfolio.cash,
            'num_positions': len(self.portfolio.option_positions),
        })

    def _get_spot_prices(self, timestamp: datetime) -> Dict[str, float]:
        """Get spot prices for all symbols."""
        prices = {}
        for symbol in self.symbols:
            price = self.data_provider.get_latest_price(symbol, timestamp)
            if price is not None:
                prices[symbol] = price
        return prices

    def _get_option_chains(self, timestamp: datetime) -> Dict[str, Any]:
        """
        Get option chain snapshots for current date.

        Reads daily-collected snapshots from OptionChainSnapshotReader.
        Returns metadata about available options (strikes, expirations) for each symbol.

        Args:
            timestamp: Current backtest timestamp

        Returns:
            Dict mapping symbol -> chain data:
                {
                    "AAPL": {
                        "expirations": [date(2024, 11, 15), date(2024, 12, 20), ...],
                        "snapshot_date": date(2024, 10, 22),
                        "underlying": "AAPL",
                    },
                    ...
                }

            Returns empty dict if no snapshots available for any symbol.
        """
        current_date = timestamp.date()
        chains = {}

        # Get option chain reader from data provider
        option_chain_reader = self.data_provider.option_chain_reader

        for symbol in self.symbols:
            try:
                # Check if snapshot exists for this date
                available_snapshots = option_chain_reader.get_available_snapshots(symbol)

                if current_date not in available_snapshots:
                    logger.debug(
                        f"No option chain snapshot for {symbol} on {current_date}. "
                        f"Available dates: {len(available_snapshots)} total"
                    )
                    continue

                # Get available expirations from snapshot (filtered by strategy DTE)
                min_dte = getattr(self.strategy.config, 'min_dte', 7)
                max_dte = getattr(self.strategy.config, 'max_dte', 90)

                expirations = option_chain_reader.get_available_expirations(
                    underlying=symbol,
                    as_of=current_date,
                    min_dte=min_dte,
                    max_dte=max_dte,
                )

                if not expirations:
                    logger.debug(
                        f"Snapshot for {symbol} on {current_date} has no expirations "
                        f"in DTE range [{min_dte}, {max_dte}]"
                    )
                    continue

                chains[symbol] = {
                    "expirations": expirations,
                    "snapshot_date": current_date,
                    "underlying": symbol,
                }

                logger.debug(
                    f"Loaded snapshot for {symbol} on {current_date}: "
                    f"{len(expirations)} expirations available"
                )

            except Exception as e:
                logger.warning(
                    f"Error loading option chain snapshot for {symbol} on {current_date}: {e}"
                )
                continue

        if not chains:
            logger.debug(f"No option chain snapshots available for any symbol on {current_date}")

        return chains

    def _handle_expirations(self, current_date: date):
        """Close expired positions."""
        expired_positions = []

        for position_id, position in self.portfolio.option_positions.items():
            if position.expiration.date() <= current_date:
                expired_positions.append(position_id)

        for position_id in expired_positions:
            position = self.portfolio.option_positions[position_id]
            # Assume worthless expiration (conservative)
            self._record_trade(position, 0.0, current_date, "expiration")
            del self.portfolio.option_positions[position_id]
            logger.debug(f"Position {position_id} expired")

    def _execute_signal(
        self,
        signal: Signal,
        option_prices: Dict[str, float],
        option_greeks: Dict[str, Greeks],
        timestamp: datetime,
    ):
        """Execute a spread signal."""
        position = self.executor.execute_spread_order(
            signal=signal,
            portfolio=self.portfolio,
            option_prices=option_prices,
            option_greeks=option_greeks,
            timestamp=timestamp,
            commission_per_contract=self.commission_per_contract,
        )

        if position:
            logger.debug(
                f"Opened {signal.position_type.value} for {signal.metadata.get('underlying', 'UNKNOWN')} "
                f"(cost: ${abs(float(position.entry_cost)):,.2f})"
            )

    def _close_position(
        self,
        position: Position,
        option_prices: Dict[str, float],
        timestamp: datetime,
        exit_reason: str,
    ):
        """Close a position and record trade."""
        # Calculate final P&L
        pnl = position.mark_to_market(option_prices)

        # Return capital to portfolio
        self.portfolio.cash += float(position.entry_cost) + pnl

        # Record trade
        self._record_trade(position, pnl, timestamp.date(), exit_reason)

        # Remove from portfolio
        del self.portfolio.option_positions[position.position_id]

        logger.debug(
            f"Closed {position.position_id} ({exit_reason}): "
            f"P&L ${pnl:,.2f}"
        )

    def _record_trade(
        self,
        position: Position,
        pnl: float,
        exit_date: date,
        exit_reason: str,
    ):
        """Record completed trade."""
        trade = {
            'position_id': position.position_id,
            'position_type': position.position_type.value,
            'entry_date': position.legs[0].entry_timestamp.date(),
            'exit_date': exit_date,
            'exit_reason': exit_reason,
            'entry_cost': float(position.entry_cost),
            'pnl': pnl,
            'return_pct': (pnl / abs(float(position.entry_cost)) * 100) if position.entry_cost != 0 else 0,
            'num_legs': len(position.legs),
            'underlying': position.metadata.get('underlying', 'UNKNOWN'),
        }

        self.trades.append(trade)
