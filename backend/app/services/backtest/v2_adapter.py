"""
V2 Engine API Adapter — bridges the FastAPI backtest layer to V2 Runner.

Responsibilities:
  1. Convert V1-style Bar objects + strategy_config into V2 DataHandler + StrategyBase
  2. Build RunConfig from BacktestRequest parameters
  3. Convert RunResult back to API-compatible response objects
  4. Provide a BuilderStrategy (StrategyBase) that evaluates rule-based strategies
  5. Multi-symbol portfolio backtesting (Phase 4)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Optional

from app.services.backtest.engine import Bar, BacktestResult, Trade
from app.services.backtest.v2.engine.data_handler import DataHandler
from app.services.backtest.v2.engine.runner import Runner, RunConfig, RunResult
from app.services.backtest.v2.engine.strategy_base import StrategyBase, StrategyContext
from app.services.backtest.v2.engine.events import BarEvent
from app.services.backtest.v2.engine.order import OrderSide
from app.services.backtest.v2.engine.risk_manager import RiskConfig
from app.services.backtest.v2.execution.tick_engine import TickMode
from app.services.backtest.condition_engine import (
    evaluate_condition_tree,
    evaluate_direction,
    passes_filters as ce_passes_filters,
)

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# Builder Strategy — evaluates indicator / entry-rule / exit-rule JSON
# ────────────────────────────────────────────────────────────────────

class BuilderStrategy(StrategyBase):
    """V2 strategy that replicates V1 rule-based BacktestEngine logic.

    Receives the same strategy_config dict that BacktestEngine uses:
      indicators, entry_rules, exit_rules, risk_params, filters
    and translates them into V2 order submissions.
    """

    def __init__(self, strategy_config: dict, symbol: str = "ASSET", point_value: float = 1.0):
        super().__init__(name="BuilderStrategy", params=strategy_config)
        self.symbol = symbol
        self.point_value = point_value
        self.config = strategy_config
        self._max_positions = self.config.get("risk_params", {}).get("max_positions", 1)

    def on_bar(self, event: BarEvent) -> None:
        """Evaluate entry/exit rules on each bar — mirrors V1 logic."""
        bar_idx = self.ctx.bar_index

        # Need at least 1 previous bar for cross-over detection
        if bar_idx < 1:
            return

        # 1. Check exit rules & trailing stop on open positions
        self._check_exits(event)

        # 2. Check entries
        self._check_entries(event)

    # ── Entry Logic ─────────────────────────────────────────────────

    def _check_entries(self, event: BarEvent) -> None:
        bar_idx = self.ctx.bar_index
        risk = self.config.get("risk_params", {})
        max_pos = risk.get("max_positions", 1)

        # Count open positions
        if self.ctx.get_position_count() >= max_pos:
            return

        # Check filters
        if not self._passes_filters(event):
            return

        entry_rules = self.config.get("entry_rules", [])
        direction = self._eval_rules_with_direction(entry_rules, bar_idx)
        if direction:
            self._open_trade(event, direction)

    def _open_trade(self, event: BarEvent, direction: str) -> None:
        risk = self.config.get("risk_params", {})
        sl_type = risk.get("stop_loss_type", "fixed_pips")
        sl_val = risk.get("stop_loss_value", 50)
        tp_type = risk.get("take_profit_type", "fixed_pips")
        tp_val = risk.get("take_profit_value", 100)

        entry_price = event.close
        atr_val = self._get_atr_value(self.ctx.bar_index)

        # Calculate SL/TP
        if direction == "long":
            sl = self._calc_sl_tp(entry_price, sl_type, sl_val, atr_val, is_sl=True, is_long=True)
            tp = self._calc_sl_tp(entry_price, tp_type, tp_val, atr_val, is_sl=False, is_long=True)
            if tp_type == "rr_ratio" and sl > 0:
                risk_dist = entry_price - sl
                tp = entry_price + risk_dist * tp_val
        else:
            sl = self._calc_sl_tp(entry_price, sl_type, sl_val, atr_val, is_sl=True, is_long=False)
            tp = self._calc_sl_tp(entry_price, tp_type, tp_val, atr_val, is_sl=False, is_long=False)
            if tp_type == "rr_ratio" and sl > 0:
                risk_dist = sl - entry_price
                tp = entry_price - risk_dist * tp_val

        # Dynamic position sizing (Phase 1D)
        # Compute lot size via StrategyContext → PositionSizer
        size = self.ctx.compute_position_size(
            symbol=self.symbol,
            entry_price=entry_price,
            stop_loss=sl if sl > 0 else entry_price,  # fallback if no SL
            direction=direction,
        )

        # TP2 / lot split
        tp2_type = risk.get("take_profit_2_type", "")
        tp2_val = risk.get("take_profit_2_value", 0)
        lot_split = risk.get("lot_split", [])
        tp2 = 0.0
        if tp2_type and tp2_val > 0:
            tp2 = self._calc_sl_tp(entry_price, tp2_type, tp2_val, atr_val,
                                   is_sl=False, is_long=(direction == "long"))

        if lot_split and len(lot_split) == 2 and tp2 > 0:
            size1 = round(size * lot_split[0], 4)
            size2 = round(size * lot_split[1], 4)
            if direction == "long":
                if size1 > 0:
                    self.ctx.buy_bracket(self.symbol, size1, stop_loss=sl, take_profit=tp, tag="entry_tp1")
                if size2 > 0:
                    self.ctx.buy_bracket(self.symbol, size2, stop_loss=sl, take_profit=tp2, tag="entry_tp2")
            else:
                if size1 > 0:
                    self.ctx.sell_bracket(self.symbol, size1, stop_loss=sl, take_profit=tp, tag="entry_tp1")
                if size2 > 0:
                    self.ctx.sell_bracket(self.symbol, size2, stop_loss=sl, take_profit=tp2, tag="entry_tp2")
        elif sl > 0 or tp > 0:
            # Single bracket order with SL/TP
            if direction == "long":
                self.ctx.buy_bracket(self.symbol, size, stop_loss=sl, take_profit=tp, tag="entry")
            else:
                self.ctx.sell_bracket(self.symbol, size, stop_loss=sl, take_profit=tp, tag="entry")
        else:
            # Plain market order
            if direction == "long":
                self.ctx.buy_market(self.symbol, size, tag="entry")
            else:
                self.ctx.sell_market(self.symbol, size, tag="entry")

    # ── Exit Logic ──────────────────────────────────────────────────

    def _check_exits(self, event: BarEvent) -> None:
        """Check exit rules (SL/TP handled by bracket orders in V2).

        Direction-aware: only evaluates exit rules matching the current
        position direction (or "both").
        """
        bar_idx = self.ctx.bar_index
        exit_rules = self.config.get("exit_rules", [])
        if not exit_rules:
            return
        pos = self.ctx.get_position(self.symbol)
        if not pos or pos.is_flat:
            return
        pos_dir = "long" if pos.is_long else "short"
        filtered = [r for r in exit_rules
                    if r.get("direction", "both") in (pos_dir, "both")]
        if filtered and self._eval_rules(filtered, bar_idx):
            self.ctx.close_position(self.symbol, tag="exit_signal")

    # ── Rule Evaluation (delegated to condition_engine) ──────────────

    def _get_value(self, source: str, bar_idx: int) -> float:
        """Get a value from the data handler — indicator, price, or literal."""
        val = self.ctx.get_value(self.symbol, source, bars_ago=self.ctx.bar_index - bar_idx)
        if val is not None and not math.isnan(val):
            return val
        # Try numeric literal
        try:
            return float(source)
        except (ValueError, TypeError):
            return float("nan")

    def _eval_rules(self, rules: list[dict], bar_idx: int) -> bool:
        """Evaluate entry/exit rules via the shared condition engine."""
        return evaluate_condition_tree(rules, bar_idx, self._get_value)

    def _eval_rules_with_direction(self, rules: list[dict], bar_idx: int) -> str:
        """Evaluate rules and return trade direction via the shared condition engine."""
        return evaluate_direction(rules, bar_idx, self._get_value)

    # ── Filters (delegated to condition_engine) ─────────────────────

    def _passes_filters(self, event: BarEvent) -> bool:
        filters = self.config.get("filters", {})
        if not filters:
            return True
        return ce_passes_filters(
            filters,
            event.timestamp_ns,
            self._get_value,
            self.ctx.bar_index,
        )

    def _get_indicator_value(self, prefix: str, bar_idx: int) -> Optional[float]:
        """Search for an indicator value by prefix (e.g. 'adx', 'atr')."""
        dh = self.ctx._data_handler
        if dh is None:
            return None
        sd = dh.get_symbol_data(self.symbol)
        if sd is None:
            return None
        for key, arr in sd.indicator_arrays.items():
            if prefix in key.lower() and bar_idx < len(arr):
                v = arr[bar_idx]
                if not math.isnan(v):
                    return v
        return None

    def _get_atr_value(self, bar_idx: int) -> float:
        val = self._get_indicator_value("atr", bar_idx)
        return val if val is not None else 0.0

    def _calc_sl_tp(self, entry: float, sl_type: str, value: float, atr_val: float,
                    is_sl: bool, is_long: bool) -> float:
        if value <= 0:
            return 0.0
        if sl_type == "fixed_pips":
            dist = value * self.point_value
        elif sl_type == "atr_multiple":
            dist = value * atr_val if atr_val > 0 else value
        elif sl_type in ("atr_pct", "adr_pct"):
            adr_val = self._get_indicator_value("adr", self.ctx.bar_index) or 0.0
            dist = adr_val * value / 100 if adr_val > 0 else value * self.point_value
        elif sl_type == "percent":
            dist = entry * value / 100
        elif sl_type == "rr_ratio":
            return 0.0
        else:
            dist = value * self.point_value

        if is_long:
            return entry - dist if is_sl else entry + dist
        else:
            return entry + dist if is_sl else entry - dist


# ────────────────────────────────────────────────────────────────────
# Tick Mode Mapping
# ────────────────────────────────────────────────────────────────────

TICK_MODE_MAP = {
    "ohlc_five": TickMode.OHLC_FIVE,
    "brownian": TickMode.BROWNIAN,
    "real_tick": TickMode.REAL_TICK,
}


# ────────────────────────────────────────────────────────────────────
# Public Adapter API
# ────────────────────────────────────────────────────────────────────

def run_v2_backtest(
    bars: list[Bar],
    strategy_config: dict,
    symbol: str,
    initial_balance: float = 10_000.0,
    spread_points: float = 0.0,
    commission_per_lot: float = 0.0,
    point_value: float = 1.0,
    # V2-specific
    slippage_pct: float = 0.0,
    commission_pct: float = 0.0,
    margin_rate: float = 0.01,
    use_fast_core: bool = False,
    bars_per_day: float = 1.0,
    tick_mode: str = "ohlc_five",
) -> RunResult:
    """Run a V2 backtest with builder-style strategy config.

    This is the main adapter function called from the API layer.
    It sets up the V2 DataHandler, BuilderStrategy, and RunConfig,
    then runs the backtest and returns a RunResult.
    """
    # 1. Build DataHandler
    data_handler = DataHandler()
    indicator_configs = strategy_config.get("indicators", [])
    data_handler.add_symbol(
        symbol=symbol,
        bars=bars,
        indicator_configs=indicator_configs if indicator_configs else None,
        point_value=point_value,
    )

    # 2. Build Strategy
    strategy = BuilderStrategy(
        strategy_config=strategy_config,
        symbol=symbol,
        point_value=point_value,
    )

    # 3. Build RunConfig
    from app.services.backtest.v2.engine.position_sizer import sizing_config_from_risk_params as _scfrp
    _risk_params = strategy_config.get("risk_params", {})
    config = RunConfig(
        initial_cash=initial_balance,
        commission_per_lot=commission_per_lot,
        commission_pct=commission_pct,
        spread=spread_points,
        slippage_pct=slippage_pct,
        point_values={symbol: point_value},
        margin_rates={symbol: margin_rate},
        risk=RiskConfig(
            max_positions=_risk_params.get("max_positions", 1),
            exclusive_orders=True,
        ),
        sizing=_scfrp(_risk_params),
        tick_mode=TICK_MODE_MAP.get(tick_mode, TickMode.OHLC_FIVE),
        bars_per_day=bars_per_day,
        use_fast_core=use_fast_core,
        warm_up_bars=data_handler.warm_up_bars if use_fast_core else 0,
    )

    # 4. Run
    runner = Runner(data_handler=data_handler, strategy=strategy, config=config)
    result = runner.run()
    return result


# ════════════════════════════════════════════════════════════════════
#  Unified Backtest Entrypoint (Phase 1C)
# ════════════════════════════════════════════════════════════════════

def run_unified_backtest(
    bars: list[Bar],
    strategy_config: dict,
    symbol: str,
    initial_balance: float = 10_000.0,
    spread_points: float = 0.0,
    commission_per_lot: float = 0.0,
    point_value: float = 1.0,
    slippage_pct: float = 0.0,
    commission_pct: float = 0.0,
    margin_rate: float = 0.01,
    use_fast_core: bool = False,
    bars_per_day: float = 1.0,
    tick_mode: str = "ohlc_five",
) -> RunResult:
    """Unified backtest runner — routes ALL strategy types through V2.

    Detects the strategy type from ``strategy_config`` and selects the
    appropriate V2 StrategyBase implementation:

    - ``mss_config`` present → MSSStrategy
    - ``gold_bt_config`` present → GoldBreakoutStrategy
    - Otherwise             → BuilderStrategy (rule-based)

    Replaces the V1 ``BacktestEngine`` and ``strategy_backtester.py``
    with proper V2 fill pipeline, metrics, and tearsheet.
    """
    from app.services.backtest.v2.engine.strategies import (
        MSSStrategy,
        GoldBreakoutStrategy,
    )
    from app.services.backtest.v2.engine.instrument import get_instrument_spec
    from app.services.backtest.v2.engine.position_sizer import (
        SizingConfig, sizing_config_from_risk_params,
    )

    # Auto-resolve instrument spec if point_value is default
    spec = get_instrument_spec(symbol)
    if point_value == 1.0 and spec.contract_size != 100_000:
        # User didn't override — use catalogue value
        point_value = spec.point_value

    # Detect strategy type
    filters = strategy_config.get("filters", {})
    mss_config = filters.get("mss_config")
    gold_bt_config = filters.get("gold_bt_config")

    if mss_config:
        mss_params = dict(mss_config)
        # Use risk_params lot_size if available
        lot_size = strategy_config.get("risk_params", {}).get("position_size_value", 0.01)
        mss_params.setdefault("lot_size", lot_size)
        strategy: StrategyBase = MSSStrategy(symbol=symbol, params=mss_params)
    elif gold_bt_config:
        gold_params = dict(gold_bt_config)
        lot_size = strategy_config.get("risk_params", {}).get("position_size_value", 0.01)
        gold_params.setdefault("lot_size", lot_size)
        strategy = GoldBreakoutStrategy(symbol=symbol, params=gold_params)
    else:
        strategy = BuilderStrategy(
            strategy_config=strategy_config,
            symbol=symbol,
            point_value=point_value,
        )

    # Build DataHandler
    data_handler = DataHandler()
    indicator_configs = strategy_config.get("indicators", [])
    data_handler.add_symbol(
        symbol=symbol,
        bars=bars,
        indicator_configs=indicator_configs if indicator_configs else None,
        point_value=point_value,
    )

    # Build position sizing config from risk_params
    risk_params = strategy_config.get("risk_params", {})
    sizing = sizing_config_from_risk_params(risk_params)

    # Build RunConfig
    config = RunConfig(
        initial_cash=initial_balance,
        commission_per_lot=commission_per_lot,
        commission_pct=commission_pct,
        spread=spread_points,
        slippage_pct=slippage_pct,
        point_values={symbol: point_value},
        margin_rates={symbol: margin_rate},
        risk=RiskConfig(
            max_positions=risk_params.get("max_positions", 1),
            exclusive_orders=True,
        ),
        sizing=sizing,
        tick_mode=TICK_MODE_MAP.get(tick_mode, TickMode.OHLC_FIVE),
        bars_per_day=bars_per_day,
        use_fast_core=use_fast_core,
        warm_up_bars=data_handler.warm_up_bars if use_fast_core else 0,
    )

    # Run
    runner = Runner(data_handler=data_handler, strategy=strategy, config=config)
    return runner.run()


def v2_result_to_v1(
    run_result: RunResult,
    initial_balance: float,
    total_bars: int,
) -> BacktestResult:
    """Convert a V2 RunResult to a V1 BacktestResult for backward compat."""
    result = BacktestResult()
    stats = run_result.stats or {}

    # Map trades
    trades = []
    for t in run_result.closed_trades:
        side = t.get("side", "long")
        # Convert nanosecond timestamps to seconds (float) for V1 compat
        entry_ns = t.get("entry_time_ns", 0)
        exit_ns = t.get("exit_time_ns", 0)
        entry_time = entry_ns / 1e9 if entry_ns else 0.0
        exit_time = exit_ns / 1e9 if exit_ns else 0.0
        trade = Trade(
            entry_bar=t.get("entry_bar", 0),
            entry_time=entry_time,
            entry_price=t.get("entry_price", 0),
            direction=side,
            size=t.get("quantity", 0.01),
            stop_loss=0.0,
            take_profit=0.0,
            exit_bar=t.get("exit_bar"),
            exit_time=exit_time if exit_time else None,
            exit_price=t.get("exit_price"),
            exit_reason=t.get("tag", ""),
            pnl=t.get("pnl", 0),
            pnl_pct=t.get("pnl_pct", 0),
        )
        trades.append(trade)

    result.trades = trades
    result.total_trades = stats.get("total_trades", len(trades))
    result.total_bars = total_bars

    # Map equity curve (V2 = list[dict], V1 = list[float])
    result.equity_curve = [e.get("equity", initial_balance) for e in run_result.equity_curve]

    # Map stats
    result.winning_trades = stats.get("winning_trades", 0)
    result.losing_trades = stats.get("losing_trades", 0)
    result.win_rate = stats.get("win_rate", 0) * 100 if stats.get("win_rate", 0) <= 1 else stats.get("win_rate", 0)
    result.gross_profit = stats.get("gross_profit", 0)
    result.gross_loss = stats.get("gross_loss", 0)
    result.net_profit = stats.get("net_profit", 0)
    result.profit_factor = stats.get("profit_factor", 0)
    result.max_drawdown = stats.get("max_drawdown", 0)
    result.max_drawdown_pct = stats.get("max_drawdown_pct", 0)
    result.avg_win = stats.get("avg_win", 0)
    result.avg_loss = stats.get("avg_loss", 0)
    result.largest_win = stats.get("largest_win", 0)
    result.largest_loss = stats.get("largest_loss", 0)
    result.avg_trade = stats.get("avg_trade", 0)
    result.sharpe_ratio = stats.get("sharpe_ratio", 0)
    result.expectancy = stats.get("expectancy", 0)

    return result


def v2_result_to_api_response(
    run_result: RunResult,
    initial_balance: float,
    total_bars: int,
) -> dict:
    """Build API response data from V2 RunResult.

    Returns a dict with keys matching BacktestResponse / BacktestStats schemas
    plus V2-specific extensions (tearsheet, full stats).
    """
    stats = run_result.stats or {}

    # Map to V1 BacktestStats shape (subset of V2 metrics)
    api_stats = {
        "total_trades": stats.get("total_trades", 0),
        "winning_trades": stats.get("winning_trades", 0),
        "losing_trades": stats.get("losing_trades", 0),
        "win_rate": _pct(stats.get("win_rate", 0)),
        "gross_profit": _round(stats.get("gross_profit", 0)),
        "gross_loss": _round(stats.get("gross_loss", 0)),
        "net_profit": _round(stats.get("net_profit", 0)),
        "profit_factor": round(stats.get("profit_factor", 0), 4),
        "max_drawdown": _round(stats.get("max_drawdown", 0)),
        "max_drawdown_pct": _round(stats.get("max_drawdown_pct", 0)),
        "avg_win": _round(stats.get("avg_win", 0)),
        "avg_loss": _round(stats.get("avg_loss", 0)),
        "largest_win": _round(stats.get("largest_win", 0)),
        "largest_loss": _round(stats.get("largest_loss", 0)),
        "avg_trade": _round(stats.get("avg_trade", 0)),
        "sharpe_ratio": round(stats.get("sharpe_ratio", 0), 4),
        "expectancy": _round(stats.get("expectancy", 0)),
        "total_bars": total_bars,
    }

    # Map trades to TradeResult-compatible dicts
    trades_out = []
    for t in run_result.closed_trades:
        side = t.get("side", "long")
        # Convert nanosecond timestamps to seconds (float)
        entry_ns = t.get("entry_time_ns", 0)
        exit_ns = t.get("exit_time_ns", 0)
        entry_time = entry_ns / 1e9 if entry_ns else 0.0
        exit_time = exit_ns / 1e9 if exit_ns else 0.0
        trades_out.append({
            "entry_bar": t.get("entry_bar", 0),
            "entry_time": entry_time,
            "entry_price": round(t.get("entry_price", 0), 5),
            "direction": side,
            "size": t.get("quantity", 0.01),
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "exit_bar": t.get("exit_bar"),
            "exit_time": exit_time if exit_time else None,
            "exit_price": round(t.get("exit_price", 0), 5) if t.get("exit_price") else None,
            "exit_reason": t.get("tag", ""),
            "pnl": round(t.get("pnl", 0), 2),
            "pnl_pct": round(t.get("pnl_pct", 0), 2),
            "commission": round(t.get("commission", 0), 4),
            "slippage": round(t.get("slippage", 0), 4),
            "duration_bars": t.get("duration_bars", 0),
        })

    # Equity curve — flat list of floats for V1 compat
    equity_flat = [e.get("equity", initial_balance) for e in run_result.equity_curve]
    # Downsample if too large
    if len(equity_flat) > 2000:
        step = len(equity_flat) // 2000
        equity_flat = equity_flat[::step] + [equity_flat[-1]]
    equity_flat = [round(v, 2) for v in equity_flat]

    return {
        "stats": api_stats,
        "trades": trades_out,
        "equity_curve": equity_flat,
        "v2_stats": stats,                      # Full 55+ metrics
        "tearsheet": run_result.tearsheet,       # Full tearsheet dict
        "elapsed_seconds": round(run_result.elapsed_seconds, 3),
    }


# ── Helpers ──

def _round(v, digits=2):
    try:
        return round(float(v), digits)
    except (TypeError, ValueError):
        return 0.0

def _pct(v):
    """Convert win_rate: V2 returns 0..1 fraction, V1 API expects 0..100."""
    try:
        fv = float(v)
        if fv <= 1.0:
            return round(fv * 100, 2)
        return round(fv, 2)
    except (TypeError, ValueError):
        return 0.0


# ────────────────────────────────────────────────────────────────────
# Phase 4 — Multi-Symbol Portfolio Backtest
# ────────────────────────────────────────────────────────────────────

class MultiSymbolBuilderStrategy(StrategyBase):
    """V2 strategy that applies the same rule set to multiple symbols.

    For each incoming BarEvent, identifies which symbol it belongs to
    and evaluates entry/exit rules using that symbol's data.
    Portfolio-level position limits are enforced by the RiskManager.
    """

    def __init__(
        self,
        strategy_config: dict,
        symbols: list[str],
        point_values: dict[str, float] | None = None,
    ):
        super().__init__(name="MultiSymbolBuilder", params=strategy_config)
        self.symbols = symbols
        self.point_values = point_values or {}
        self.config = strategy_config

    def on_bar(self, event: BarEvent) -> None:
        bar_idx = self.ctx.bar_index
        if bar_idx < 1:
            return

        symbol = event.symbol

        # 1. Check exit rules on open positions for this symbol
        self._check_exits(event, symbol)

        # 2. Check entries for this symbol
        self._check_entries(event, symbol)

    def _check_entries(self, event: BarEvent, symbol: str) -> None:
        bar_idx = self.ctx.bar_index
        risk = self.config.get("risk_params", {})
        max_pos = risk.get("max_positions", 1)

        if self.ctx.get_position_count() >= max_pos:
            return

        if not self._passes_filters(event, symbol):
            return

        entry_rules = self.config.get("entry_rules", [])
        direction = self._eval_rules_with_direction(entry_rules, bar_idx, symbol)
        if direction:
            self._open_trade(event, direction, symbol)

    def _open_trade(self, event: BarEvent, direction: str, symbol: str) -> None:
        risk = self.config.get("risk_params", {})
        size = risk.get("position_size_value", 0.01)
        sl_type = risk.get("stop_loss_type", "fixed_pips")
        sl_val = risk.get("stop_loss_value", 50)
        tp_type = risk.get("take_profit_type", "fixed_pips")
        tp_val = risk.get("take_profit_value", 100)

        pv = self.point_values.get(symbol, 1.0)
        entry_price = event.close
        atr_val = self._get_atr_value(bar_idx=self.ctx.bar_index, symbol=symbol)

        if direction == "long":
            sl = self._calc_sl_tp(entry_price, sl_type, sl_val, atr_val, pv, is_sl=True, is_long=True)
            tp = self._calc_sl_tp(entry_price, tp_type, tp_val, atr_val, pv, is_sl=False, is_long=True)
            if tp_type == "rr_ratio" and sl > 0:
                tp = entry_price + (entry_price - sl) * tp_val
        else:
            sl = self._calc_sl_tp(entry_price, sl_type, sl_val, atr_val, pv, is_sl=True, is_long=False)
            tp = self._calc_sl_tp(entry_price, tp_type, tp_val, atr_val, pv, is_sl=False, is_long=False)
            if tp_type == "rr_ratio" and sl > 0:
                tp = entry_price - (sl - entry_price) * tp_val

        # TP2 / lot split
        tp2_type = risk.get("take_profit_2_type", "")
        tp2_val = risk.get("take_profit_2_value", 0)
        lot_split = risk.get("lot_split", [])
        tp2 = 0.0
        if tp2_type and tp2_val > 0:
            tp2 = self._calc_sl_tp(entry_price, tp2_type, tp2_val, atr_val, pv,
                                   is_sl=False, is_long=(direction == "long"))

        if lot_split and len(lot_split) == 2 and tp2 > 0:
            s1 = round(size * lot_split[0], 4)
            s2 = round(size * lot_split[1], 4)
            if direction == "long":
                if s1 > 0:
                    self.ctx.buy_bracket(symbol, s1, stop_loss=sl, take_profit=tp, tag="entry_tp1")
                if s2 > 0:
                    self.ctx.buy_bracket(symbol, s2, stop_loss=sl, take_profit=tp2, tag="entry_tp2")
            else:
                if s1 > 0:
                    self.ctx.sell_bracket(symbol, s1, stop_loss=sl, take_profit=tp, tag="entry_tp1")
                if s2 > 0:
                    self.ctx.sell_bracket(symbol, s2, stop_loss=sl, take_profit=tp2, tag="entry_tp2")
        elif sl > 0 or tp > 0:
            if direction == "long":
                self.ctx.buy_bracket(symbol, size, stop_loss=sl, take_profit=tp, tag="entry")
            else:
                self.ctx.sell_bracket(symbol, size, stop_loss=sl, take_profit=tp, tag="entry")
        else:
            if direction == "long":
                self.ctx.buy_market(symbol, size, tag="entry")
            else:
                self.ctx.sell_market(symbol, size, tag="entry")

    def _check_exits(self, event: BarEvent, symbol: str) -> None:
        bar_idx = self.ctx.bar_index
        exit_rules = self.config.get("exit_rules", [])
        if not exit_rules:
            return
        pos = self.ctx.get_position(symbol)
        if not pos or pos.is_flat:
            return
        pos_dir = "long" if pos.is_long else "short"
        filtered = [r for r in exit_rules
                    if r.get("direction", "both") in (pos_dir, "both")]
        if filtered and self._eval_rules(filtered, bar_idx, symbol):
            self.ctx.close_position(symbol, tag="exit_signal")

    # ── Rule evaluation (symbol-aware, delegated to condition_engine) ──

    def _get_value(self, source: str, bar_idx: int, symbol: str) -> float:
        val = self.ctx.get_value(symbol, source, bars_ago=self.ctx.bar_index - bar_idx)
        if val is not None and not math.isnan(val):
            return val
        try:
            return float(source)
        except (ValueError, TypeError):
            return float("nan")

    def _eval_rules(self, rules: list[dict], bar_idx: int, symbol: str) -> bool:
        """Evaluate entry/exit rules via the shared condition engine."""
        def value_fn(src: str, idx: int) -> float:
            return self._get_value(src, idx, symbol)
        return evaluate_condition_tree(rules, bar_idx, value_fn)

    def _eval_rules_with_direction(self, rules: list[dict], bar_idx: int, symbol: str) -> str:
        """Evaluate rules and return trade direction via the shared condition engine."""
        def value_fn(src: str, idx: int) -> float:
            return self._get_value(src, idx, symbol)
        return evaluate_direction(rules, bar_idx, value_fn)

    # ── Filters (symbol-aware, delegated to condition_engine) ───────

    def _passes_filters(self, event: BarEvent, symbol: str) -> bool:
        filters = self.config.get("filters", {})
        if not filters:
            return True
        def value_fn(src: str, idx: int) -> float:
            return self._get_value(src, idx, symbol)
        return ce_passes_filters(
            filters,
            event.timestamp_ns,
            value_fn,
            self.ctx.bar_index,
        )

    def _get_indicator_value(self, prefix: str, bar_idx: int, symbol: str) -> Optional[float]:
        dh = self.ctx._data_handler
        if dh is None:
            return None
        sd = dh.get_symbol_data(symbol)
        if sd is None:
            return None
        for key, arr in sd.indicator_arrays.items():
            if prefix in key.lower() and bar_idx < len(arr):
                v = arr[bar_idx]
                if not math.isnan(v):
                    return v
        return None

    def _get_atr_value(self, bar_idx: int, symbol: str) -> float:
        val = self._get_indicator_value("atr", bar_idx, symbol)
        return val if val is not None else 0.0

    def _calc_sl_tp(self, entry: float, sl_type: str, value: float, atr_val: float,
                    point_value: float, is_sl: bool, is_long: bool) -> float:
        if value <= 0:
            return 0.0
        if sl_type == "fixed_pips":
            dist = value * point_value
        elif sl_type == "atr_multiple":
            dist = value * atr_val if atr_val > 0 else value
        elif sl_type in ("atr_pct", "adr_pct"):
            # Use the symbol-specific ADR indicator
            adr_val = 0.0
            dh = self.ctx._data_handler
            if dh:
                sd = dh.get_symbol_data(self.symbols[0] if self.symbols else "")
                if sd:
                    for k, arr in sd.indicator_arrays.items():
                        if "adr" in k.lower() and self.ctx.bar_index < len(arr):
                            v = arr[self.ctx.bar_index]
                            if not math.isnan(v):
                                adr_val = v
                                break
            dist = adr_val * value / 100 if adr_val > 0 else value * point_value
        elif sl_type == "percent":
            dist = entry * value / 100
        elif sl_type == "rr_ratio":
            return 0.0
        else:
            dist = value * point_value

        if is_long:
            return entry - dist if is_sl else entry + dist
        else:
            return entry + dist if is_sl else entry - dist


def run_v2_portfolio_backtest(
    symbols_data: list[dict],
    strategy_config: dict,
    initial_balance: float = 10_000.0,
    spread_points: float = 0.0,
    commission_per_lot: float = 0.0,
    slippage_pct: float = 0.0,
    commission_pct: float = 0.0,
    margin_rate: float = 0.01,
    use_fast_core: bool = False,
    bars_per_day: float = 1.0,
    tick_mode: str = "ohlc_five",
) -> tuple[RunResult, dict]:
    """Run a multi-symbol portfolio backtest.

    Args:
        symbols_data: list of dicts, each with:
            - symbol (str): Symbol name
            - bars (list[Bar]): Bar data
            - point_value (float): Point value for PnL
        strategy_config: Strategy definition (indicators, rules, risk_params, filters)
        ... (same params as run_v2_backtest)

    Returns:
        (RunResult, portfolio_analytics_dict)
    """
    from app.services.backtest.v2.analytics.portfolio_analytics import (
        build_portfolio_analytics,
    )

    symbols = [sd["symbol"] for sd in symbols_data]
    point_values = {sd["symbol"]: sd.get("point_value", 1.0) for sd in symbols_data}

    # 1. Build DataHandler with all symbols
    data_handler = DataHandler()
    indicator_configs = strategy_config.get("indicators", [])
    for sd in symbols_data:
        data_handler.add_symbol(
            symbol=sd["symbol"],
            bars=sd["bars"],
            indicator_configs=indicator_configs if indicator_configs else None,
            point_value=sd.get("point_value", 1.0),
        )

    # 2. Build multi-symbol strategy
    strategy = MultiSymbolBuilderStrategy(
        strategy_config=strategy_config,
        symbols=symbols,
        point_values=point_values,
    )

    # 3. Build RunConfig
    risk_params = strategy_config.get("risk_params", {})
    from app.services.backtest.v2.engine.position_sizer import sizing_config_from_risk_params as _pscfrp
    config = RunConfig(
        initial_cash=initial_balance,
        commission_per_lot=commission_per_lot,
        commission_pct=commission_pct,
        spread=spread_points,
        slippage_pct=slippage_pct,
        point_values=point_values,
        margin_rates={sym: margin_rate for sym in symbols},
        risk=RiskConfig(
            max_positions=risk_params.get("max_positions", len(symbols)),
            max_positions_per_symbol=1,
            exclusive_orders=True,
        ),
        sizing=_pscfrp(risk_params),
        tick_mode=TICK_MODE_MAP.get(tick_mode, TickMode.OHLC_FIVE),
        bars_per_day=bars_per_day,
        use_fast_core=use_fast_core,
        warm_up_bars=data_handler.warm_up_bars if use_fast_core else 0,
    )

    # 4. Run
    runner = Runner(data_handler=data_handler, strategy=strategy, config=config)
    result = runner.run()

    # 5. Build portfolio analytics
    symbol_closes = {}
    for sd in symbols_data:
        sym = sd["symbol"]
        sym_data = data_handler.get_symbol_data(sym)
        if sym_data:
            symbol_closes[sym] = sym_data.closes

    portfolio_analytics = build_portfolio_analytics(
        closed_trades=result.closed_trades,
        equity_curve=result.equity_curve,
        symbol_closes=symbol_closes,
        symbols=symbols,
    )

    return result, portfolio_analytics


def v2_portfolio_result_to_api_response(
    run_result: RunResult,
    portfolio_analytics: dict,
    initial_balance: float,
    total_bars: int,
) -> dict:
    """Build API response for a portfolio backtest.

    Extends the single-symbol response with portfolio-specific fields.
    """
    base = v2_result_to_api_response(run_result, initial_balance, total_bars)
    base["portfolio_analytics"] = portfolio_analytics
    return base
