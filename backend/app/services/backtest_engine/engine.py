"""
Backtesting Engine V3 — Main execution loop.

Hybrid architecture:
  1. Indicators computed vectorized upfront (NumPy)
  2. Bar-by-bar event loop for order execution (event-driven)
  3. Intra-bar tick synthesis for accurate SL/TP fills
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from .bar import Bar
from .data_feed import DataFeed
from .fill_engine import FillEngine, FillResult, TickMode
from .instrument import Instrument, get_instrument
from .order import (
    Order, BracketOrder, OrderBook, OrderType, OrderSide, OrderRole, OrderStatus,
)
from .position import Position, Portfolio
from .position_sizer import SizingMethod
from .strategy import StrategyBase, StrategyContext, TradeRecord

logger = logging.getLogger(__name__)


@dataclass
class EngineConfig:
    """Configuration for the backtesting engine."""
    initial_balance: float = 10_000.0
    spread_points: float = 0.0
    commission: float = 7.0         # Per lot round-trip
    point_value: float = 1.0
    slippage_pct: float = 0.0
    latency_ms: float = 0.0              # Simulated execution latency (ms)
    margin_rate: float = 0.01
    tick_mode: TickMode = TickMode.OHLC_PESSIMISTIC
    max_positions: int = 1
    allow_pyramiding: bool = False
    close_on_opposite: bool = True  # Close existing pos before opening opposite
    close_at_end: bool = True       # Close open positions at end of data

    # Position sizing
    sizing_method: SizingMethod = SizingMethod.RISK_PERCENT
    sizing_params: dict = field(default_factory=lambda: {
        "risk_pct": 1.0,
        "fixed_lot": 0.01,
    })


@dataclass
class BacktestResult:
    """Complete backtest results."""
    trades: list[dict] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    equity_timestamps: list[float] = field(default_factory=list)

    # Summary stats
    total_bars: int = 0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_profit: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    avg_trade: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    sqn: float = 0.0
    expectancy: float = 0.0
    recovery_factor: float = 0.0
    payoff_ratio: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    avg_bars_held: float = 0.0
    initial_balance: float = 0.0
    final_balance: float = 0.0

    # Monthly returns
    monthly_returns: dict = field(default_factory=dict)
    yearly_pnl: dict = field(default_factory=dict)

    # Execution meta
    execution_time_ms: float = 0.0
    engine_version: str = "v3"


class Engine:
    """Main backtesting engine — the event-driven execution loop."""

    def __init__(
        self,
        strategy: StrategyBase,
        data_feed: DataFeed,
        instrument: Instrument,
        config: EngineConfig | None = None,
    ):
        self.strategy = strategy
        self.feed = data_feed
        self.instrument = instrument
        self.config = config or EngineConfig()

        # Core components
        self.portfolio = Portfolio(initial_balance=self.config.initial_balance)
        self.order_book = OrderBook()
        self.fill_engine = FillEngine(
            tick_mode=self.config.tick_mode,
            slippage_pct=self.config.slippage_pct,
            spread_points=self.config.spread_points,
            latency_ms=self.config.latency_ms,
        )

        # Strategy context
        self.ctx = StrategyContext(
            data_feed=self.feed,
            portfolio=self.portfolio,
            instrument=self.instrument,
            sizing_method=self.config.sizing_method,
            sizing_params=self.config.sizing_params,
        )
        self.strategy._set_context(self.ctx)

    def run(self, symbol: str = "") -> BacktestResult:
        """Execute the backtest. Returns complete results."""
        start_time = time.perf_counter()

        sym = symbol or self.feed.primary_symbol
        if not sym:
            return BacktestResult()

        sd = self.feed.get_symbol_data(sym)
        if not sd or sd.count == 0:
            return BacktestResult()

        n = sd.count

        # Initialize strategy
        self.strategy.on_init()

        # ── Main Loop ───────────────────────────────────────────────
        for i in range(n):
            bar = sd.bars[i]

            # Update context
            self.ctx._set_bar(i, bar)

            # 1. Check pending SL/TP/limit orders against intra-bar ticks
            self._process_pending_orders(sym, bar, sd.get_bar(i - 1) if i > 0 else None)

            # 2. Update trailing stops
            self._update_trailing_stops(sym, bar)

            # 3. Let strategy place new orders
            self.strategy.on_bar(bar)

            # 4. Process new orders from strategy
            self._process_new_orders(sym, bar)

            # 5. Snapshot equity
            prices = {sym: bar.close}
            eq = self.portfolio.snapshot(prices)

        # ── Close remaining positions ──────────────────────────────
        if self.config.close_at_end:
            self._close_all_positions(sym, sd.bars[-1] if sd.bars else None)

        # Notify strategy
        self.strategy.on_end()

        # ── Build results ──────────────────────────────────────────
        elapsed = (time.perf_counter() - start_time) * 1000
        return self._build_result(n, elapsed)

    # ── Order Processing ────────────────────────────────────────────

    def _process_pending_orders(
        self, symbol: str, bar: Bar, prev_bar: Optional[Bar],
    ) -> None:
        """Check pending stop/limit orders against intra-bar ticks."""
        pending = self.order_book.get_pending_stops_and_limits(symbol)
        if not pending:
            return

        # Determine position side for pessimistic tick ordering
        pos = self.portfolio.get_position(symbol)
        pos_side = pos.side if pos and not pos.is_flat else None

        fills = self.fill_engine.check_pending_orders(
            pending, bar, prev_bar, self.instrument, pos_side
        )

        for fill in fills:
            if fill.filled:
                self._execute_fill(fill, bar)

    def _process_new_orders(self, symbol: str, bar: Bar) -> None:
        """Process orders submitted by strategy during on_bar()."""
        orders, brackets = self.ctx._drain_orders()

        # Process bracket orders first
        for bracket in brackets:
            # Check position limits
            if not self._can_open_position(symbol, bracket.entry):
                if bracket.entry:
                    bracket.entry.reject("max_positions_reached")
                continue

            # Close opposite position if configured
            if self.config.close_on_opposite and bracket.entry:
                self._maybe_close_opposite(symbol, bracket.entry, bar)

            self.order_book.add_bracket(bracket)

            # Fill entry (market order) immediately
            if bracket.entry and bracket.entry.order_type == OrderType.MARKET:
                fill = self.fill_engine.fill_market_order(
                    bracket.entry, bar, self.instrument
                )
                if fill.filled:
                    self._execute_fill(fill, bar)

        # Process standalone orders
        for order in orders:
            if order.role == OrderRole.EXIT:
                # Exit orders always go through
                if order.order_type == OrderType.MARKET:
                    fill = self.fill_engine.fill_market_order(
                        order, bar, self.instrument
                    )
                    if fill.filled:
                        self._execute_fill(fill, bar)
                else:
                    self.order_book.add_order(order)
            else:
                # Entry orders — check position limits
                if not self._can_open_position(symbol, order):
                    order.reject("max_positions_reached")
                    continue

                if self.config.close_on_opposite:
                    self._maybe_close_opposite(symbol, order, bar)

                if order.order_type == OrderType.MARKET:
                    fill = self.fill_engine.fill_market_order(
                        order, bar, self.instrument
                    )
                    if fill.filled:
                        self._execute_fill(fill, bar)
                else:
                    self.order_book.add_order(order)

    def _execute_fill(self, fill: FillResult, bar: Bar) -> None:
        """Execute a fill: update position, portfolio, notify strategy."""
        order = fill.order
        order.fill(
            price=fill.fill_price,
            quantity=order.quantity,
            bar_index=self.ctx.bar_index,
            timestamp=bar.timestamp,
            commission=fill.commission,
            slippage=fill.slippage,
        )

        pos = self.portfolio.get_or_create_position(
            order.symbol, self.instrument
        )

        if order.role == OrderRole.ENTRY:
            # Opening or adding to position
            direction = "long" if order.is_buy else "short"

            if pos.is_flat:
                pos.side = direction
                pos.entry_bar_index = self.ctx.bar_index
                pos.entry_timestamp = bar.timestamp

            pos.add(order.quantity, fill.fill_price, fill.commission)

            # Record trade open
            sl_price = 0.0
            tp_price = 0.0
            if order.bracket_id:
                bracket = self.order_book.get_bracket(order.bracket_id)
                if bracket:
                    sl_price = bracket.stop_loss.price if bracket.stop_loss else 0
                    tp_price = bracket.take_profit.price if bracket.take_profit else 0
            self.ctx._record_trade_open(
                bracket_id=order.bracket_id or order.id,
                entry_order=order,
                sl=sl_price,
                tp=tp_price,
            )

            # Activate bracket exit orders
            if order.bracket_id:
                self.order_book.activate_bracket_exits(order.bracket_id)

        elif order.role in (OrderRole.STOP_LOSS, OrderRole.TAKE_PROFIT,
                            OrderRole.TRAILING_STOP, OrderRole.EXIT):
            # Closing or reducing position
            pnl = pos.reduce(order.quantity, fill.fill_price, fill.commission)
            self.portfolio.apply_pnl(pnl)

            # Record trade close
            self.ctx._record_trade_close(
                bracket_id=order.bracket_id or order.id,
                exit_order=order,
                pnl=pnl,
            )

            # Cancel sibling orders (OCO)
            self.order_book.on_order_filled(order)

            # Notify strategy
            if pos.is_flat:
                self.strategy.on_position_closed(order.symbol, pnl)

        else:
            # Standalone buy/sell (not entry/exit role)
            if (order.is_buy and pos.is_short) or (order.is_sell and pos.is_long):
                pnl = pos.reduce(order.quantity, fill.fill_price, fill.commission)
                self.portfolio.apply_pnl(pnl)
            else:
                direction = "long" if order.is_buy else "short"
                if pos.is_flat:
                    pos.side = direction
                    pos.entry_bar_index = self.ctx.bar_index
                    pos.entry_timestamp = bar.timestamp
                pos.add(order.quantity, fill.fill_price, fill.commission)

        # Notify strategy
        self.strategy.on_order_filled(order)

    def _update_trailing_stops(self, symbol: str, bar: Bar) -> None:
        """Update trailing stop prices based on current bar."""
        pending = self.order_book.get_pending_stops_and_limits(symbol)
        pos = self.portfolio.get_position(symbol)
        if not pos or pos.is_flat:
            return

        for order in pending:
            if order.role == OrderRole.TRAILING_STOP and order.trail_offset > 0:
                # Use high for long trailing (max favorable), low for short
                if pos.is_long:
                    self.fill_engine.update_trailing_stop(
                        order, bar.high, "long"
                    )
                elif pos.is_short:
                    self.fill_engine.update_trailing_stop(
                        order, bar.low, "short"
                    )

    def _can_open_position(self, symbol: str, order: Optional[Order]) -> bool:
        """Check if a new position is allowed."""
        if not order:
            return False
        pos = self.portfolio.get_position(symbol)
        if pos and not pos.is_flat:
            if not self.config.allow_pyramiding:
                # Check if same direction — if so, block
                is_same = (
                    (pos.is_long and order.is_buy) or
                    (pos.is_short and order.is_sell)
                )
                if is_same:
                    return False
            # Opposite direction is allowed (will close first if configured)
            return True
        return True

    def _maybe_close_opposite(self, symbol: str, order: Order, bar: Bar) -> None:
        """Close opposite position before opening new one."""
        pos = self.portfolio.get_position(symbol)
        if not pos or pos.is_flat:
            return

        is_opposite = (
            (pos.is_long and order.is_sell) or
            (pos.is_short and order.is_buy)
        )
        if is_opposite:
            self._force_close(symbol, bar)

    def _force_close(self, symbol: str, bar: Bar) -> None:
        """Force close all positions and cancel pending orders for a symbol."""
        pos = self.portfolio.get_position(symbol)
        if not pos or pos.is_flat:
            return

        side = OrderSide.SELL if pos.is_long else OrderSide.BUY
        close_order = Order(
            symbol=symbol, side=side, order_type=OrderType.MARKET,
            quantity=pos.quantity, role=OrderRole.EXIT,
            created_bar_index=self.ctx.bar_index, tag="force_close",
        )
        fill = self.fill_engine.fill_market_order(close_order, bar, self.instrument)
        if fill.filled:
            self._execute_fill(fill, bar)

        # Cancel pending orders for this symbol
        self.order_book.cancel_all(symbol)

    def _close_all_positions(self, symbol: str, last_bar: Optional[Bar]) -> None:
        """Close all open positions at end of data."""
        if not last_bar:
            return
        pos = self.portfolio.get_position(symbol)
        if pos and not pos.is_flat:
            self._force_close(symbol, last_bar)

    # ── Results ─────────────────────────────────────────────────────

    def _build_result(self, total_bars: int, elapsed_ms: float) -> BacktestResult:
        """Compute all analytics from trade records."""
        from .analytics import compute_analytics

        trades = self.ctx.trades
        trade_dicts = [t.to_dict() for t in trades]
        equity_curve = self.portfolio.equity_curve

        result = BacktestResult(
            trades=trade_dicts,
            equity_curve=equity_curve,
            total_bars=total_bars,
            initial_balance=self.config.initial_balance,
            final_balance=self.portfolio.balance,
            execution_time_ms=elapsed_ms,
        )

        # Compute analytics
        analytics = compute_analytics(
            trades=trades,
            equity_curve=equity_curve,
            initial_balance=self.config.initial_balance,
        )
        # Copy analytics into result
        for key, value in analytics.items():
            if hasattr(result, key):
                setattr(result, key, value)

        return result


# ── Convenience Runner ──────────────────────────────────────────────

def run_backtest(
    strategy: StrategyBase,
    bars: list[Bar] | list[dict],
    symbol: str = "ASSET",
    indicator_configs: list[dict] | None = None,
    config: EngineConfig | None = None,
    point_value: float = 1.0,
    commission: float = 7.0,
    margin_rate: float = 0.01,
) -> BacktestResult:
    """Convenience function to run a backtest with minimal setup."""
    cfg = config or EngineConfig()
    if point_value != 1.0:
        cfg.point_value = point_value

    instrument = get_instrument(symbol, point_value=cfg.point_value,
                                commission=commission, margin_rate=margin_rate)

    feed = DataFeed()
    feed.add_symbol(symbol, bars, indicator_configs=indicator_configs)

    engine = Engine(strategy=strategy, data_feed=feed,
                    instrument=instrument, config=cfg)
    return engine.run(symbol)
