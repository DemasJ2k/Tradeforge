"""
V2 Backtesting Engine — Main Event-Loop Runner.

Orchestrates the full backtest lifecycle:
  1. Set up data, portfolio, risk, strategy
  2. Feed bars into the event queue
  3. Pop events in priority order, dispatch to handlers
  4. Collect results

Supports:
  - Multi-symbol bar synchronisation
  - Warm-up period enforcement
  - Bracket / OCO / OTO linked orders
  - Exclusive mode (auto-close on entry flip)
  - Equity snapshots per bar
  - Max-drawdown halt
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from app.services.backtest.v2.engine.events import (
    BarEvent,
    CancelEvent,
    Event,
    EventType,
    FillEvent,
    OrderEvent,
    TickEvent,
    TimerEvent,
    timestamp_ns_from_unix,
)
from app.services.backtest.v2.engine.event_queue import EventQueue
from app.services.backtest.v2.engine.order import (
    Fill,
    Order,
    OrderBook,
    OrderSide,
    OrderStatus,
    OrderType,
)
from app.services.backtest.v2.engine.position import PositionBook
from app.services.backtest.v2.engine.portfolio import Portfolio
from app.services.backtest.v2.engine.data_handler import DataHandler, BarData
from app.services.backtest.v2.engine.risk_manager import RiskManager, RiskConfig
from app.services.backtest.v2.engine.strategy_base import StrategyBase, StrategyContext
from app.services.backtest.v2.execution.tick_engine import (
    TickEngine, TickEngineConfig, TickMode, TickFillResult,
)
from app.services.backtest.v2.execution.fill_model import (
    FillModel, FillContext, CompositeFillModel,
    make_default_fill_model, make_realistic_fill_model,
)
from app.services.backtest.v2.analytics.tearsheet import (
    build_tearsheet, TearsheetConfig, TearsheetResult,
)
from app.services.backtest.v2.engine.position_sizer import (
    PositionSizer, SizingConfig, SizingMethod,
)

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# Run Configuration
# ────────────────────────────────────────────────────────────────────

class SlippageMode(str, Enum):
    """Controls how fill slippage is modelled."""
    NONE = "none"                 # Zero slippage — spread only
    FIXED = "fixed"               # Fixed points (from slippage_pct × price)
    REALISTIC = "realistic"       # ATR-scaled slippage + volume impact


# System ATR period used internally for the fill model when the strategy
# does not include its own ATR indicator.
_SYSTEM_ATR_PERIOD: int = 14
# Rolling window length used to compute average volume.
_AVG_VOLUME_WINDOW: int = 20


@dataclass
class RunConfig:
    """Configuration for a single backtest run."""
    initial_cash: float = 10_000.0
    commission_per_lot: float = 0.0       # Fixed commission per lot traded
    commission_pct: float = 0.0           # Percentage commission (0.001 = 0.1%)
    spread: float = 0.0                   # Half-spread applied to fills
    slippage_pct: float = 0.0             # Random slippage as fraction of price
    point_values: dict[str, float] = field(default_factory=dict)  # {symbol: pv}
    margin_rates: dict[str, float] = field(default_factory=dict)  # {symbol: rate}
    risk: RiskConfig = field(default_factory=RiskConfig)
    # Slippage mode (Phase 1A)
    slippage_mode: SlippageMode = SlippageMode.REALISTIC
    # Realistic-mode tunables (used when slippage_mode == REALISTIC)
    atr_slip_pct: float = 0.10            # Fraction of ATR used as slippage
    min_slip_pts: float = 0.0             # Floor slippage in price points
    max_slip_pts: float = 0.0             # Cap slippage in price points (0 = none)
    impact_coeff: float = 0.1             # Volume-impact coefficient
    max_impact_pct: float = 0.01          # Volume-impact cap as fraction of price
    # SL/TP fill priority
    pessimistic_sl_tp: bool = True        # When SL+TP both trigger in same bar, fill SL first
    # Tick engine configuration (Phase 2)
    tick_mode: TickMode = TickMode.OHLC_FIVE
    tick_engine_config: TickEngineConfig | None = None
    fill_model: FillModel | None = None   # Custom fill model (overrides spread/slippage_pct)
    # Analytics (Phase 3)
    tearsheet: TearsheetConfig | None = None  # None = use defaults; pass config to customise
    bars_per_day: float = 1.0                 # For annualisation (e.g. 6*24=144 for M10)
    # Position sizing (Phase 1D)
    sizing: SizingConfig = field(default_factory=SizingConfig)
    # Rust / fast-path (Phase 5)
    use_fast_core: bool = False               # When True, use Rust/fallback FastRunner
    warm_up_bars: int = 0                     # Warm-up bars for fast core


# ────────────────────────────────────────────────────────────────────
# Run Result
# ────────────────────────────────────────────────────────────────────

@dataclass
class RunResult:
    """Result bundle returned by Runner.run()."""
    equity_curve: list[dict]       # [{bar_index, timestamp, equity, cash, drawdown_pct}]
    closed_trades: list[dict]      # ClosedTrade.to_dict() for each
    open_positions: list[dict]     # Open positions at end
    stats: dict[str, Any]          # Summary statistics (30+ metrics from tearsheet)
    bars_processed: int = 0
    elapsed_seconds: float = 0.0
    halted: bool = False
    halt_reason: str = ""
    tearsheet: dict | None = None  # Full tearsheet (metrics + MC + benchmark + rolling)


# ────────────────────────────────────────────────────────────────────
# Runner
# ────────────────────────────────────────────────────────────────────

class Runner:
    """
    Main event-loop engine.

    Usage:
        data = DataHandler()
        data.add_symbol("XAUUSD", bars, indicators_config)
        strategy = MyStrategy(params={...})
        config = RunConfig(initial_cash=10000, spread=0.5)

        runner = Runner(data_handler=data, strategy=strategy, config=config)
        result = runner.run()
    """

    def __init__(
        self,
        data_handler: DataHandler,
        strategy: StrategyBase,
        config: RunConfig | None = None,
    ):
        self.config = config or RunConfig()
        self.data_handler = data_handler

        # Core components
        self.queue = EventQueue()
        self.order_book = OrderBook()

        # Build portfolio with proper margin rate
        default_margin_rate = 0.01
        if self.config.margin_rates:
            # Use the first configured rate as default, or 0.01
            default_margin_rate = next(iter(self.config.margin_rates.values()), 0.01)

        self.portfolio = Portfolio(
            initial_cash=self.config.initial_cash,
            margin_rate=default_margin_rate,
            point_values=self.config.point_values or None,
            commission_per_lot=self.config.commission_per_lot,
            spread_points=self.config.spread,
        )
        self.position_book = self.portfolio.position_book

        # Set per-symbol margin rates
        for sym, rate in self.config.margin_rates.items():
            self.portfolio.margin_model.set_rate(sym, rate)

        self.risk_manager = RiskManager(
            config=self.config.risk,
            portfolio=self.portfolio,
            order_book=self.order_book,
        )

        # Position sizer (Phase 1D)
        self.position_sizer = PositionSizer(self.config.sizing)

        # Strategy context
        self.ctx = StrategyContext()
        self.ctx._data_handler = self.data_handler
        self.ctx._portfolio = self.portfolio
        self.ctx._position_sizer = self.position_sizer
        self.strategy = strategy

        # ── Tick Engine (Phase 2) ───────────────────────────────────
        # Build tick engine config from RunConfig if not explicitly provided
        tick_cfg = self.config.tick_engine_config
        if tick_cfg is None:
            tick_cfg = TickEngineConfig(
                mode=self.config.tick_mode,
                default_spread=self.config.spread,
            )
        # Build or use custom fill model based on slippage_mode
        fill_model = self.config.fill_model
        if fill_model is None:
            fill_model = self._build_fill_model()
        self.tick_engine = TickEngine(fill_model=fill_model, config=tick_cfg)

        # State
        self._current_bar_index: int = 0
        self._warm_up_bars: int = 0
        self._last_prices: dict[str, float] = {}
        self._prev_bars: dict[str, BarEvent] = {}  # For gap detection
        self._bars_processed: int = 0

        # ── System ATR & rolling average volume per symbol ──────────
        # Pre-computed during __init__ so _get_atr / _get_avg_volume
        # can do O(1) lookups during the event loop.
        self._system_atr: dict[str, list[float]] = {}
        self._avg_volume: dict[str, list[float]] = {}
        self._precompute_atr_and_volume()

    # ── Fill Model & ATR/Volume Helpers ───────────────────────────

    def _build_fill_model(self) -> CompositeFillModel:
        """Build fill model chain based on ``config.slippage_mode``."""
        from app.services.backtest.v2.execution.fill_model import (
            SpreadModel, FixedSlippage, VolatilitySlippage,
            VolumeImpact, CompositeFillModel,
        )
        mode = self.config.slippage_mode

        if mode == SlippageMode.NONE:
            # Spread only — no slippage at all
            return CompositeFillModel([SpreadModel()])

        if mode == SlippageMode.FIXED:
            # Backward-compat: constant slippage from slippage_pct × price
            # The actual points are computed in _execute_fill_from_tick
            return CompositeFillModel([
                SpreadModel(),
                FixedSlippage(points=0.0),  # points added in execute path
            ])

        # REALISTIC — ATR-scaled slippage + volume impact (default)
        return CompositeFillModel([
            SpreadModel(),
            VolatilitySlippage(
                pct_of_atr=self.config.atr_slip_pct,
                min_points=self.config.min_slip_pts,
                max_points=self.config.max_slip_pts,
            ),
            VolumeImpact(
                impact_coeff=self.config.impact_coeff,
                max_impact_pct=self.config.max_impact_pct,
            ),
        ])

    def _precompute_atr_and_volume(self) -> None:
        """Pre-compute system ATR and rolling average volume for every symbol.

        Called once during ``__init__``.  The resulting arrays are the same
        length as the bar series so look-ups are O(1) by bar index.
        """
        from app.services.backtest import indicators as _ind

        for sym, sd in self.data_handler._symbols.items():
            # ── System ATR ──────────────────────────────────────────
            # If the strategy already computed an ATR indicator, reuse it.
            atr_key = None
            for key in sd.indicator_arrays:
                # Accept any key whose type is ATR (e.g. "atr_1", "atr_14")
                if key.upper().startswith("ATR") or key.lower().startswith("atr"):
                    atr_key = key
                    break

            if atr_key is not None:
                self._system_atr[sym] = sd.indicator_arrays[atr_key]
            else:
                # Compute a system-level ATR(14)
                self._system_atr[sym] = _ind.atr(
                    sd.highs, sd.lows, sd.closes, _SYSTEM_ATR_PERIOD,
                )

            # ── Rolling average volume ──────────────────────────────
            if sd.volumes and any(v > 0 for v in sd.volumes):
                self._avg_volume[sym] = _ind.sma(sd.volumes, _AVG_VOLUME_WINDOW)
            else:
                self._avg_volume[sym] = [0.0] * sd.bar_count

    def _get_atr(self, symbol: str, bar_index: int) -> float:
        """Return the system ATR for *symbol* at *bar_index* (0 if unknown)."""
        arr = self._system_atr.get(symbol)
        if arr and 0 <= bar_index < len(arr):
            v = arr[bar_index]
            if not math.isnan(v):
                return v
        return 0.0

    def _get_avg_volume(self, symbol: str, bar_index: int) -> float:
        """Return rolling average volume for *symbol* at *bar_index*."""
        arr = self._avg_volume.get(symbol)
        if arr and 0 <= bar_index < len(arr):
            v = arr[bar_index]
            if not math.isnan(v):
                return v
        return 0.0

    # ── Public API ──────────────────────────────────────────────────

    def run(self) -> RunResult:
        """Execute the full backtest and return results.

        If ``config.use_fast_core`` is True, delegates the inner event
        loop to the Rust/fallback FastRunner (Phase 5) and then wraps
        the result through the normal tearsheet pipeline.
        """
        if self.config.use_fast_core:
            return self._run_fast_core()

        t0 = time.perf_counter()

        # Initialise
        self._warm_up_bars = self.data_handler.warm_up_bars
        self.strategy.initialize(self.ctx)

        # Feed all bars into the queue
        self.data_handler.feed_bars(self.queue)

        # Main event loop
        while not self.queue.is_empty:
            event = self.queue.pop()
            self._dispatch(event)

        # Finalize
        self.strategy.on_end()

        elapsed = time.perf_counter() - t0
        result = self._build_result(elapsed)
        return result

    # ── Fast Core Path (Phase 5) ──────────────────────────────────

    def _run_fast_core(self) -> RunResult:
        """Delegate to the Rust/fallback FastRunner for maximum speed.

        The fast core handles the hot-path internally (event queue, tick
        matching, portfolio M2M, indicators).  Strategy logic stays in
        Python via a callback.

        After the fast run, the results are wrapped through the same
        tearsheet pipeline as the standard runner.
        """
        from app.services.backtest.v2.core import (
            USING_RUST,
            Bar as FastBar,
            EngineConfig as FastConfig,
            SymbolConfig as FastSymConfig,
            FastRunner as _FastRunner,
        )

        logger.info(
            "Fast core: using %s engine",
            "Rust" if USING_RUST else "Python fallback",
        )

        t0 = time.perf_counter()

        # ── Build config ────────────────────────────────────────────
        default_margin_rate = 0.01
        if self.config.margin_rates:
            default_margin_rate = next(iter(self.config.margin_rates.values()), 0.01)

        fast_cfg = FastConfig(
            initial_cash=self.config.initial_cash,
            commission_per_lot=self.config.commission_per_lot,
            commission_pct=self.config.commission_pct,
            spread=self.config.spread,
            slippage_pct=self.config.slippage_pct,
            default_margin_rate=default_margin_rate,
            max_drawdown_pct=self.config.risk.max_drawdown_pct if hasattr(self.config.risk, 'max_drawdown_pct') else 0.0,
            max_positions=self.config.risk.max_open_positions if hasattr(self.config.risk, 'max_open_positions') else 0,
            exclusive_orders=self.config.risk.exclusive_orders if hasattr(self.config.risk, 'exclusive_orders') else False,
            warm_up_bars=self.config.warm_up_bars,
            bars_per_day=self.config.bars_per_day,
        )

        # ── Build symbol configs ────────────────────────────────────
        sym_names = list(self.data_handler._symbols.keys())
        sym_configs = [
            FastSymConfig(
                symbol_idx=i,
                name=name,
                point_value=self.config.point_values.get(name, 1.0),
                margin_rate=self.config.margin_rates.get(name, default_margin_rate),
                spread=self.config.spread,
            )
            for i, name in enumerate(sym_names)
        ]

        # ── Build bars ──────────────────────────────────────────────
        bars: list = []
        for sym_idx, sym_name in enumerate(sym_names):
            sym_data = self.data_handler._symbols[sym_name]
            n = len(sym_data.closes)
            for i in range(n):
                bars.append(FastBar(
                    timestamp_ns=(
                        sym_data.timestamps[i]
                        if hasattr(sym_data, 'timestamps') and i < len(getattr(sym_data, 'timestamps', []))
                        else i * 1_000_000_000
                    ),
                    symbol_idx=sym_idx,
                    bar_index=i,
                    open=sym_data.opens[i] if i < len(sym_data.opens) else 0.0,
                    high=sym_data.highs[i] if i < len(sym_data.highs) else 0.0,
                    low=sym_data.lows[i] if i < len(sym_data.lows) else 0.0,
                    close=sym_data.closes[i],
                    volume=sym_data.volumes[i] if i < len(sym_data.volumes) else 0.0,
                ))
        bars.sort(key=lambda b: (b.timestamp_ns, b.symbol_idx))

        # ── Strategy callback ───────────────────────────────────────
        # The fast runner calls strategy_cb(bar_dict, indicator_vals)
        # and expects a list of order dicts in return.
        self._warm_up_bars = self.config.warm_up_bars
        self.ctx._data_handler = self.data_handler
        self.ctx._portfolio = self.portfolio
        self.ctx._position_sizer = self.position_sizer
        self.strategy.initialize(self.ctx)

        def strategy_callback(bar_dict: dict, indicator_vals) -> list:
            """Bridge between fast core and Python strategy."""
            # Build a lightweight BarEvent for the strategy
            bar_event = BarEvent(
                timestamp_ns=bar_dict["timestamp_ns"],
                event_type=EventType.BAR,
                symbol=bar_dict.get("symbol", sym_names[bar_dict.get("symbol_idx", 0)]),
                bar_index=bar_dict["bar_index"],
                open=bar_dict["open"],
                high=bar_dict["high"],
                low=bar_dict["low"],
                close=bar_dict["close"],
                volume=bar_dict["volume"],
            )

            # Update context
            self.ctx._bar_index = bar_dict["bar_index"]

            # Let strategy react
            self.strategy.on_bar(bar_event)

            # Drain orders and convert to fast-core format
            orders = self.ctx._drain_orders()
            result = []
            for o in orders:
                od = {
                    "symbol_idx": sym_names.index(o.symbol) if o.symbol in sym_names else 0,
                    "side": o.side.value if hasattr(o.side, 'value') else int(o.side),
                    "order_type": o.order_type.value if hasattr(o.order_type, 'value') else int(o.order_type),
                    "quantity": o.quantity,
                }
                if o.limit_price is not None and o.limit_price > 0:
                    od["limit_price"] = o.limit_price
                if o.stop_price is not None and o.stop_price > 0:
                    od["stop_price"] = o.stop_price
                if o.tag:
                    od["tag"] = o.tag
                result.append(od)
            return result

        # ── Run ─────────────────────────────────────────────────────
        fast_runner = _FastRunner(config=fast_cfg, symbols=sym_configs, bars_flat=bars)
        bt_result, fast_portfolio = fast_runner.run(strategy_callback)

        elapsed = time.perf_counter() - t0

        # ── Convert to RunResult ────────────────────────────────────
        # Equity curve
        equity_curve = []
        peak = self.config.initial_cash
        # Build ordered list of timestamps (Unix seconds) from bars
        bar_ts_sec = []
        for b in bars:
            ts = b.timestamp_ns
            # Normalise: if it looks like nanoseconds (> year 2100 in seconds), convert
            if ts > 4_102_444_800:  # 2100-01-01 in Unix seconds
                ts = ts / 1_000_000_000
            bar_ts_sec.append(ts)

        for i, eq in enumerate(fast_portfolio.equity_curve):
            if eq > peak:
                peak = eq
            dd_pct = ((peak - eq) / peak * 100) if peak > 0 else 0.0
            # Map equity index to bar timestamp (index 0 = initial equity)
            if i > 0 and (i - 1) < len(bar_ts_sec):
                ts = bar_ts_sec[i - 1]
            elif bar_ts_sec:
                ts = bar_ts_sec[-1]
            else:
                ts = 0
            equity_curve.append({
                "bar_index": max(0, i - 1),
                "timestamp": ts,
                "equity": eq,
                "cash": fast_portfolio.cash,
                "drawdown_pct": dd_pct,
            })

        # Closed trades
        raw_trades = fast_portfolio.get_trades() if hasattr(fast_portfolio, 'get_trades') else []
        closed_trades = []
        for t in raw_trades:
            side_str = "long" if t.get("side", 1) == 1 else "short"
            closed_trades.append({
                "trade_id": f"ft_{len(closed_trades)}",
                "symbol": sym_names[t.get("symbol_idx", 0)] if t.get("symbol_idx", 0) < len(sym_names) else "UNKNOWN",
                "side": side_str,
                "quantity": t.get("quantity", 0.0),
                "entry_price": t.get("entry_price", 0.0),
                "exit_price": t.get("exit_price", 0.0),
                "pnl": t.get("pnl", 0.0),
                "pnl_pct": t.get("pnl_pct", 0.0),
                "commission": t.get("commission", 0.0),
                "slippage": t.get("slippage", 0.0),
                "entry_bar": t.get("entry_bar", 0),
                "exit_bar": t.get("exit_bar", 0),
                "entry_time_ns": t.get("entry_time_ns", 0),
                "exit_time_ns": t.get("exit_time_ns", 0),
                "duration_bars": t.get("duration_bars", 0),
                "is_winner": t.get("pnl", 0.0) > 0,
            })

        # ── Tearsheet ───────────────────────────────────────────────
        ts_config = self.config.tearsheet or TearsheetConfig(
            bars_per_day=self.config.bars_per_day,
        )
        ts_config.bars_per_day = self.config.bars_per_day

        close_prices = None
        if self.data_handler._symbols:
            import numpy as _np
            primary_sym = next(iter(self.data_handler._symbols))
            sym_data = self.data_handler._symbols[primary_sym]
            close_prices = _np.array(sym_data.closes, dtype=_np.float64)

        tearsheet = build_tearsheet(
            equity_curve=equity_curve,
            closed_trades=closed_trades,
            initial_capital=self.config.initial_cash,
            total_bars=bt_result.bars_processed,
            close_prices=close_prices,
            config=ts_config,
        )

        return RunResult(
            equity_curve=equity_curve,
            closed_trades=closed_trades,
            open_positions=[],
            stats=tearsheet.metrics,
            bars_processed=bt_result.bars_processed,
            elapsed_seconds=elapsed,
            halted=bt_result.halted,
            halt_reason=bt_result.halt_reason or "",
            tearsheet=tearsheet.to_dict(),
        )

    # ── Event Dispatch ──────────────────────────────────────────────

    def _dispatch(self, event: Event) -> None:
        """Route an event to the correct handler."""
        if event.event_type == EventType.BAR:
            self._on_bar(event)  # type: ignore
        elif event.event_type == EventType.TICK:
            self._on_tick(event)  # type: ignore
        elif event.event_type == EventType.FILL:
            self._on_fill(event)  # type: ignore
        elif event.event_type == EventType.ORDER:
            self._on_order(event)  # type: ignore
        elif event.event_type == EventType.CANCEL:
            self._on_cancel(event)  # type: ignore
        elif event.event_type == EventType.TIMER:
            pass  # Reserved for future use

    # ── Bar Processing ──────────────────────────────────────────────

    def _on_bar(self, event: BarEvent) -> None:
        """Handle a new bar event."""
        self._current_bar_index = event.bar_index
        self.ctx._bar_index = event.bar_index

        # Update last price
        self._last_prices[event.symbol] = event.close

        # Skip warm-up bars (indicators need history)
        if event.bar_index < self._warm_up_bars:
            self._prev_bars[event.symbol] = event
            return

        self._bars_processed += 1

        # 1. Process pending limit/stop orders via tick engine
        self._process_pending_orders(event)

        # 2. Let strategy react to the bar
        self.strategy.on_bar(event)

        # 3. Collect orders submitted by the strategy
        self._process_strategy_orders(event)

        # 4. Collect cancel requests from the strategy
        self._process_cancel_requests()

        # 5. Snapshot equity for the equity curve
        self.portfolio.snapshot_equity(
            prices=self._last_prices,
            bar_index=event.bar_index,
        )

        # 6. Check drawdown halt
        self.risk_manager.update_drawdown_check()

        # 7. Track previous bar for gap detection
        self._prev_bars[event.symbol] = event

    # ── Tick Processing ─────────────────────────────────────────────

    def _on_tick(self, event: TickEvent) -> None:
        """Handle a tick event (Phase 2 — tick fill model)."""
        self._last_prices[event.symbol] = event.last_price or event.bid
        self.strategy.on_tick(event)

    # ── Order Processing ────────────────────────────────────────────

    def _process_strategy_orders(self, bar: BarEvent) -> None:
        """Validate and submit orders from the strategy context."""
        orders = self.ctx._drain_orders()
        for order in orders:
            self._submit_order(order, bar)

    def _submit_order(self, order: Order, bar: BarEvent) -> None:
        """Risk-check and submit/execute an order."""
        # Risk validation
        result = self.risk_manager.validate_order(order, self._last_prices)
        if not result.passed:
            order.reject(bar.timestamp_ns, result.reason)
            self.strategy.on_order_rejected(order, result.reason)
            return

        order.submit(bar.timestamp_ns)
        self.order_book.add(order)

        # Exclusive mode: close opposite position before opening new one
        if self.config.risk.exclusive_orders:
            pos = self.portfolio.get_position(order.symbol)
            if not pos.is_flat:
                is_flip = (
                    (pos.is_long and order.side == OrderSide.SELL)
                    or (pos.is_short and order.side == OrderSide.BUY)
                )
                # Also check if entering new position while one exists
                is_new_entry = (
                    (pos.is_long and order.side == OrderSide.BUY)
                    or (pos.is_short and order.side == OrderSide.SELL)
                )
                if is_flip or (not self.config.risk.allow_pyramiding and not is_new_entry):
                    # Force close existing position first
                    self._force_close_position(order.symbol, bar)

        # Market orders fill immediately via tick engine
        if order.order_type == OrderType.MARKET:
            atr = self._get_atr(order.symbol, bar.bar_index)
            avg_volume = self._get_avg_volume(order.symbol, bar.bar_index)
            tick_result = self.tick_engine.process_market_order(
                order, bar, atr=atr, avg_volume=avg_volume,
            )
            self._execute_fill_from_tick(tick_result, bar)
        # Limit/Stop orders are left pending for _process_pending_orders

    def _process_pending_orders(self, bar: BarEvent) -> None:
        """Check pending limit/stop orders against the tick engine."""
        active_orders = self.order_book.get_active_for_symbol(bar.symbol)
        pending = [o for o in active_orders if o.order_type != OrderType.MARKET]

        if not pending:
            return

        prev_bar = self._prev_bars.get(bar.symbol)

        # Look up real ATR and average volume for this symbol / bar
        atr = self._get_atr(bar.symbol, bar.bar_index)
        avg_volume = self._get_avg_volume(bar.symbol, bar.bar_index)

        tick_fills = self.tick_engine.process_bar(
            bar=bar,
            pending_orders=pending,
            prev_bar=prev_bar,
            atr=atr,
            avg_volume=avg_volume,
        )

        # ── Pessimistic SL/TP priority ─────────────────────────────
        # When both SL (stop) and TP (limit) of the same bracket trigger
        # within the same bar, ensure the SL fills first so the TP gets
        # cancelled via OCO.  This prevents optimistic bias.
        if self.config.pessimistic_sl_tp and len(tick_fills) >= 2:
            tick_fills = self._reorder_pessimistic(tick_fills)

        for tick_result in tick_fills:
            # Skip fills for orders cancelled during this tick (e.g. OCO siblings)
            if tick_result.order.status in (OrderStatus.CANCELLED, OrderStatus.FILLED):
                continue
            self._execute_fill_from_tick(tick_result, bar)

    # ── Pessimistic SL/TP Reordering ──────────────────────────────

    def _reorder_pessimistic(
        self, fills: list[TickFillResult],
    ) -> list[TickFillResult]:
        """Reorder fills so that stop-loss fills are processed before
        take-profit fills when both trigger in the same bar.

        This prevents optimistic bias: if you can't know which extreme
        was actually hit first, assume the worst case (SL hit first).

        Identification heuristic:
        - Stop orders (SL) have ``order_type == STOP``
        - Limit orders (TP) have ``order_type == LIMIT``
        - They are OCO siblings if one's ``oco_id`` references the other
          OR they share the same symbol and are on opposite sides of an
          existing position.

        When an SL and a TP for the same symbol both appear in ``fills``
        at different tick indices OR the same tick index, we move the SL
        before the TP regardless of the original tick ordering.
        """
        # Fast exit: most bars will have 0 or 1 fill
        if len(fills) < 2:
            return fills

        # Partition into stops (SL candidates) and limits (TP candidates)
        # by symbol so we only compare within-symbol pairs.
        from collections import defaultdict
        by_symbol: dict[str, list[tuple[int, TickFillResult]]] = defaultdict(list)
        for idx, fr in enumerate(fills):
            by_symbol[fr.order.symbol].append((idx, fr))

        # Build a set of indices that need to be moved earlier
        reordered = list(fills)
        swapped = False
        for sym, sym_fills in by_symbol.items():
            if len(sym_fills) < 2:
                continue
            stops = [(i, fr) for i, fr in sym_fills if fr.order.order_type == OrderType.STOP]
            limits = [(i, fr) for i, fr in sym_fills if fr.order.order_type == OrderType.LIMIT]
            if not stops or not limits:
                continue

            # For each SL/TP pair on the same symbol, make sure the stop
            # appears before the limit in the result list.
            for si, sfr in stops:
                for li, lfr in limits:
                    if si > li:
                        # Stop appears after limit → swap them in reordered
                        pos_s = reordered.index(sfr)
                        pos_l = reordered.index(lfr)
                        if pos_s > pos_l:
                            reordered[pos_l], reordered[pos_s] = reordered[pos_s], reordered[pos_l]
                            swapped = True

        return reordered

    # ── Fill Execution (V2 — tick engine aware) ─────────────────────

    def _execute_fill_from_tick(
        self, tick_result: TickFillResult, bar: BarEvent,
    ) -> None:
        """Execute a fill from a TickFillResult.

        The tick engine has already computed the adjusted fill price
        (spread, slippage, impact). We add commission and book the fill.
        """
        order = tick_result.order
        fill_price = tick_result.fill_price

        # Ensure price floor
        fill_price = max(fill_price, 0.0001)

        # Calculate commission
        qty = order.remaining_quantity
        commission = (
            self.config.commission_per_lot * qty
            + self.config.commission_pct * fill_price * qty
        )

        # Calculate slippage (distance from raw to final price)
        slippage = abs(tick_result.fill_price - tick_result.raw_price)

        # Apply additional pct-based slippage if configured (backward compat)
        if self.config.slippage_pct > 0:
            extra_slippage = fill_price * self.config.slippage_pct
            if order.side == OrderSide.BUY:
                fill_price += extra_slippage
            else:
                fill_price -= extra_slippage
            slippage += extra_slippage
            fill_price = max(fill_price, 0.0001)

        # Create fill
        fill = Fill(
            fill_id=f"f_{order.order_id}_{bar.bar_index}",
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=qty,
            price=fill_price,
            commission=commission,
            slippage=slippage,
            timestamp_ns=tick_result.timestamp_ns,
        )

        # Apply fill to order
        order.apply_fill(fill)

        # Apply fill to portfolio (position + cash)
        closed_trade = self.portfolio.apply_fill(fill, bar_index=bar.bar_index)

        # Update position sizer with closed-trade PnL (for Kelly criterion)
        if closed_trade is not None:
            self.position_sizer.update_trade_stats(closed_trade.pnl)

        # Handle linked orders (OCO / OTO)
        if order.status == OrderStatus.FILLED:
            # Cancel OCO siblings
            self.order_book.cancel_linked(order, bar.timestamp_ns)
            # Activate OTO children
            self.order_book.activate_oto_children(order, bar.timestamp_ns)

        # Notify strategy
        fill_event = FillEvent(
            timestamp_ns=fill.timestamp_ns,
            event_type=EventType.FILL,
            symbol=fill.symbol,
            order_id=fill.order_id,
            side=fill.side.value,
            quantity=fill.quantity,
            price=fill.price,
            commission=fill.commission,
        )
        self.strategy.on_fill(fill_event)

        logger.debug(
            "FILL %s %s %.4f %s @ %.5f  comm=%.2f  slip=%.5f%s",
            fill.side.value,
            fill.quantity,
            fill.symbol,
            order.order_type.value,
            fill.price,
            fill.commission,
            fill.slippage,
            " [GAP]" if tick_result.is_gap_fill else "",
        )

    def _execute_fill(self, order: Order, raw_price: float, bar: BarEvent) -> None:
        """Legacy fill execution — wraps into TickFillResult for compatibility."""
        tick_result = TickFillResult(
            order=order,
            fill_price=raw_price,
            raw_price=raw_price,
            tick_index=0,
            timestamp_ns=bar.timestamp_ns,
        )
        self._execute_fill_from_tick(tick_result, bar)

    def _force_close_position(self, symbol: str, bar: BarEvent) -> None:
        """Force close an existing position (for exclusive mode)."""
        pos = self.portfolio.get_position(symbol)
        if pos.is_flat:
            return

        close_side = OrderSide.SELL if pos.is_long else OrderSide.BUY
        from app.services.backtest.v2.engine.order import market_order as mo
        close_order = mo(symbol, close_side, abs(pos.quantity), "auto_close", pos.point_value)
        close_order.submit(bar.timestamp_ns)
        self.order_book.add(close_order)
        atr = self._get_atr(symbol, bar.bar_index)
        avg_volume = self._get_avg_volume(symbol, bar.bar_index)
        tick_result = self.tick_engine.process_market_order(
            close_order, bar, atr=atr, avg_volume=avg_volume,
        )
        self._execute_fill_from_tick(tick_result, bar)

    # ── Cancel Processing ───────────────────────────────────────────

    def _process_cancel_requests(self) -> None:
        """Process cancel requests from the strategy."""
        cancel_ids = self.ctx._drain_cancel_requests()
        for order_id in cancel_ids:
            order = self.order_book.get(order_id)
            if order and order.is_active:
                order.cancel(0)
                self.order_book.cancel_linked(order, 0)

    def _on_fill(self, event: FillEvent) -> None:
        """Handle fill events generated externally (future use)."""
        pass

    def _on_order(self, event: OrderEvent) -> None:
        """Handle order events generated externally (future use)."""
        pass

    def _on_cancel(self, event: CancelEvent) -> None:
        """Handle cancel events generated externally (future use)."""
        pass

    # ── Result Building ─────────────────────────────────────────────

    def _build_result(self, elapsed: float) -> RunResult:
        """Build the final result bundle."""
        # Force close all open positions at last known price
        # (standard backtest convention)
        for symbol, pos in list(self.position_book.positions.items()):
            if not pos.is_flat:
                last_price = self._last_prices.get(symbol, 0)
                if last_price > 0:
                    self.portfolio.force_close_all(
                        prices=self._last_prices,
                        timestamp_ns=0,
                        bar_index=self._current_bar_index,
                        reason="end_of_data",
                    )
                    break

        # Equity curve from snapshots (rich dicts)
        equity_curve = []
        for snap in self.portfolio._equity_snapshots:
            equity_curve.append({
                "bar_index": snap.bar_index,
                "timestamp": snap.timestamp_ns,
                "equity": snap.total_equity,
                "cash": snap.cash,
                "drawdown_pct": (
                    ((self.portfolio._peak_equity - snap.total_equity)
                     / self.portfolio._peak_equity * 100)
                    if self.portfolio._peak_equity > 0 else 0.0
                ),
            })

        # Closed trades
        closed_trades = []
        for t in self.portfolio.closed_trades:
            closed_trades.append({
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "side": t.side,
                "quantity": t.quantity,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "commission": t.commission,
                "slippage": t.slippage,
                "entry_bar": t.entry_bar_index,
                "exit_bar": t.exit_bar_index,
                "entry_time_ns": t.entry_time_ns,
                "exit_time_ns": t.exit_time_ns,
                "duration_bars": t.duration_bars,
                "is_winner": t.is_winner,
            })

        # Open positions at end (should be none after force close)
        open_positions = []
        for symbol, pos in self.position_book.positions.items():
            if not pos.is_flat:
                open_positions.append({
                    "symbol": symbol,
                    "side": pos.side.value,
                    "quantity": pos.quantity,
                    "avg_entry": pos.avg_entry_price,
                })

        # ── Build Tearsheet (Phase 3) ──────────────────────────────
        ts_config = self.config.tearsheet or TearsheetConfig(
            bars_per_day=self.config.bars_per_day,
        )
        # Ensure bars_per_day is synced
        ts_config.bars_per_day = self.config.bars_per_day

        # Collect close prices for benchmark (primary symbol)
        close_prices = None
        if self.data_handler._symbols:
            import numpy as _np
            primary_sym = next(iter(self.data_handler._symbols))
            sym_data = self.data_handler._symbols[primary_sym]
            close_prices = _np.array(sym_data.closes, dtype=_np.float64)

        tearsheet = build_tearsheet(
            equity_curve=equity_curve,
            closed_trades=closed_trades,
            initial_capital=self.config.initial_cash,
            total_bars=self._bars_processed,
            close_prices=close_prices,
            config=ts_config,
        )

        # Stats is now the comprehensive metrics dict from tearsheet
        stats = tearsheet.metrics

        return RunResult(
            equity_curve=equity_curve,
            closed_trades=closed_trades,
            open_positions=open_positions,
            stats=stats,
            bars_processed=self._bars_processed,
            elapsed_seconds=elapsed,
            halted=self.risk_manager.is_halted,
            halt_reason=self.risk_manager.halt_reason,
            tearsheet=tearsheet.to_dict(),
        )

    # NOTE: _compute_stats() was removed in Phase 1B.  All metrics are
    # now computed by the tearsheet analytics pipeline (metrics.py).
    # -----------------------------------------------------------------
