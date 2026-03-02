"""
Backward-compatibility adapter: V1 strategy config → V2 StrategyBase.

Converts V1-style JSON strategy configurations (with entry_rules, exit_rules,
indicators, risk_params, and filters) into a concrete V2 StrategyBase subclass
that the V2 Runner can execute.

Also converts V2 RunResult back into V1 BacktestResult format for the
existing API layer.
"""

from __future__ import annotations

import math
import logging
from typing import Any, Optional

from app.services.backtest.v2.engine.events import BarEvent
from app.services.backtest.v2.engine.order import OrderSide, OrderType
from app.services.backtest.v2.engine.strategy_base import StrategyBase, StrategyContext
from app.services.backtest.v2.engine.runner import Runner, RunConfig, RunResult
from app.services.backtest.v2.engine.risk_manager import RiskConfig
from app.services.backtest.v2.engine.data_handler import DataHandler
from app.services.backtest.condition_engine import (
    evaluate_condition_tree,
    evaluate_direction,
    passes_filters as ce_passes_filters,
)

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# V1 → V2 Strategy Adapter
# ────────────────────────────────────────────────────────────────────

class V1StrategyAdapter(StrategyBase):
    """
    Wraps a V1 strategy_config dict as a V2 StrategyBase.

    Replicates V1 BacktestEngine logic:
      - Evaluates entry_rules, exit_rules with AND/OR logic
      - Applies risk_params for SL/TP/trailing/lot-split
      - Respects filters (time, day, ADX, volatility)

    This lets V1 strategies run on the V2 engine with zero config changes.
    """

    def __init__(self, strategy_config: dict, symbol: str, point_value: float = 1.0):
        super().__init__(name="V1Adapter", params=strategy_config)
        self.v1_config = strategy_config
        self.symbol = symbol
        self.pv = point_value

    # ── Lifecycle ───────────────────────────────────────────────────

    def on_init(self) -> None:
        """Nothing extra to set up — indicators are pre-computed by DataHandler."""
        pass

    def on_bar(self, event: BarEvent) -> None:
        """Replicate V1 bar-by-bar logic: check exits, then check entries."""
        if event.symbol != self.symbol:
            return

        idx = event.bar_index

        # --- Exit checks ---
        self._check_v1_exits(event, idx)

        # --- Entry checks ---
        self._check_v1_entries(event, idx)

    # ── Entry Logic ─────────────────────────────────────────────────

    def _check_v1_entries(self, event: BarEvent, idx: int) -> None:
        risk = self.v1_config.get("risk_params", {})
        max_pos = risk.get("max_positions", 1)

        if self.ctx.get_position_count() >= max_pos:
            return

        if not self._passes_filters(event, idx):
            return

        entry_rules = self.v1_config.get("entry_rules", [])
        direction = self._eval_rules_with_direction(entry_rules, idx)
        if not direction:
            return

        self._open_v1_trade(event, idx, direction)

    def _open_v1_trade(self, event: BarEvent, idx: int, direction: str) -> None:
        """Open a trade using V1 risk_params logic."""
        risk = self.v1_config.get("risk_params", {})
        entry_price = event.close  # spread is added by the Runner's fill model
        size = risk.get("position_size_value", 0.01)

        # SL / TP calculation
        sl_type = risk.get("stop_loss_type", "fixed_pips")
        sl_val = risk.get("stop_loss_value", 50)
        tp_type = risk.get("take_profit_type", "fixed_pips")
        tp_val = risk.get("take_profit_value", 100)

        atr_val = self._get_indicator_value("atr", idx)

        is_long = direction == "long"
        sl = self._calc_sl_tp(entry_price, sl_type, sl_val, atr_val, is_sl=True, is_long=is_long, idx=idx)
        tp = self._calc_sl_tp(entry_price, tp_type, tp_val, atr_val, is_sl=False, is_long=is_long, idx=idx)

        # RR ratio for TP
        if tp_type == "rr_ratio" and sl > 0:
            risk_dist = abs(entry_price - sl)
            tp = entry_price + risk_dist * tp_val if is_long else entry_price - risk_dist * tp_val

        # TP2 / lot split
        tp2_type = risk.get("take_profit_2_type", "")
        tp2_val = risk.get("take_profit_2_value", 0)
        lot_split = risk.get("lot_split", [])
        tp2 = 0.0
        if tp2_type and tp2_val > 0:
            tp2 = self._calc_sl_tp(entry_price, tp2_type, tp2_val, atr_val, is_sl=False, is_long=is_long, idx=idx)

        side = OrderSide.BUY if is_long else OrderSide.SELL

        if lot_split and len(lot_split) == 2 and tp2 > 0:
            size1 = round(size * lot_split[0], 4)
            size2 = round(size * lot_split[1], 4)
            if size1 > 0:
                self._place_bracket(side, size1, sl, tp, tag=f"v1_tp1_{direction}")
            if size2 > 0:
                self._place_bracket(side, size2, sl, tp2, tag=f"v1_tp2_{direction}")
        else:
            self._place_bracket(side, size, sl, tp, tag=f"v1_{direction}")

    def _place_bracket(self, side: OrderSide, qty: float, sl: float, tp: float, tag: str) -> None:
        """Submit a bracket order through the context."""
        if side == OrderSide.BUY:
            self.ctx.buy_bracket(
                symbol=self.symbol,
                quantity=qty,
                stop_loss=sl if sl > 0 else None,
                take_profit=tp if tp > 0 else None,
                tag=tag,
                point_value=self.pv,
            )
        else:
            self.ctx.sell_bracket(
                symbol=self.symbol,
                quantity=qty,
                stop_loss=sl if sl > 0 else None,
                take_profit=tp if tp > 0 else None,
                tag=tag,
                point_value=self.pv,
            )

    # ── Exit Logic ──────────────────────────────────────────────────

    def _check_v1_exits(self, event: BarEvent, idx: int) -> None:
        """Check exit rules and trailing stop."""
        exit_rules = self.v1_config.get("exit_rules", [])
        if exit_rules and self._eval_rules(exit_rules, idx):
            pos = self.ctx.get_position(self.symbol)
            if pos and not pos.is_flat:
                self.ctx.close_position(self.symbol, "exit_signal")
                return

        # Trailing stop: adjust SL on open limit/stop orders
        risk = self.v1_config.get("risk_params", {})
        if risk.get("trailing_stop") and risk.get("trailing_stop_value", 0) > 0:
            # Note: V2 trailing stop will be implemented in Phase 2
            # For now, the bracket SL/TP orders handle basic exits
            pass

    # ── Condition Evaluation (delegated to condition_engine) ───────

    def _get_value(self, source: str, idx: int) -> float:
        """Get a value at a bar index (mirrors V1 _get_value)."""
        if self.ctx._data_handler is not None:
            result = self.ctx._data_handler.get_value(self.symbol, source, idx)
            if result is not None and not math.isnan(result):
                return result
        return float("nan")

    def _eval_rules(self, rules: list[dict], idx: int) -> bool:
        """Evaluate entry/exit rules via the shared condition engine."""
        return evaluate_condition_tree(rules, idx, self._get_value)

    def _eval_rules_with_direction(self, rules: list[dict], idx: int) -> str:
        """Evaluate rules and return trade direction via the shared condition engine."""
        return evaluate_direction(rules, idx, self._get_value)

    # ── Filters (delegated to condition_engine) ─────────────────────

    def _passes_filters(self, event: BarEvent, idx: int) -> bool:
        filters = self.v1_config.get("filters", {})
        if not filters:
            return True
        return ce_passes_filters(
            filters,
            event.timestamp_ns,
            self._get_value,
            idx,
        )

    # ── SL/TP Calculation (mirrors V1 _calc_sl_tp) ──────────────────

    def _calc_sl_tp(
        self, entry: float, sl_type: str, value: float, atr_val: float,
        is_sl: bool, is_long: bool, idx: int = 0,
    ) -> float:
        if value <= 0:
            return 0.0

        if sl_type == "fixed_pips":
            dist = value * self.pv
        elif sl_type == "atr_multiple":
            dist = value * atr_val if atr_val > 0 else value
        elif sl_type in ("atr_pct", "adr_pct"):
            adr_val = self._get_indicator_value("adr", idx)
            if adr_val is None or math.isnan(adr_val):
                adr_val = 0
            dist = adr_val * value / 100 if adr_val > 0 else value * self.pv
        elif sl_type == "percent":
            dist = entry * value / 100
        elif sl_type == "rr_ratio":
            return 0.0
        else:
            dist = value * self.pv

        if is_long:
            return entry - dist if is_sl else entry + dist
        else:
            return entry + dist if is_sl else entry - dist

    # ── Indicator Helpers ───────────────────────────────────────────

    def _get_indicator_value(self, ind_type: str, idx: int) -> Optional[float]:
        """Find an indicator value by type prefix (e.g., 'atr', 'adx', 'adr')."""
        if self.ctx._data_handler is None:
            return None
        sym_data = self.ctx._data_handler._symbols.get(self.symbol)
        if sym_data is None:
            return None
        bar = sym_data.get_bar(idx)
        if bar is None:
            return None
        # Search indicator values for a matching key
        for key, val in bar.indicators.items():
            if ind_type.lower() in key.lower():
                return val
        return None


# ────────────────────────────────────────────────────────────────────
# V1 → V2 Config Conversion
# ────────────────────────────────────────────────────────────────────

def v1_config_to_run_config(
    strategy_config: dict,
    initial_balance: float = 10_000.0,
    spread_points: float = 0.0,
    commission_per_lot: float = 0.0,
    point_value: float = 1.0,
) -> RunConfig:
    """Convert V1 BacktestEngine constructor params to V2 RunConfig."""
    risk = strategy_config.get("risk_params", {})
    max_pos = risk.get("max_positions", 1)

    return RunConfig(
        initial_cash=initial_balance,
        commission_per_lot=commission_per_lot,
        spread=spread_points / 2,  # V1 uses full spread, V2 uses half-spread
        point_values={"*": point_value},
        risk=RiskConfig(
            max_positions=max_pos,
            max_positions_per_symbol=max_pos,
            max_order_size=1000.0,
            min_order_size=0.0001,
            exclusive_orders=True,  # V1 always replaces previous position
            allow_pyramiding=False,
        ),
    )


# ────────────────────────────────────────────────────────────────────
# V2 Result → V1 Format Conversion
# ────────────────────────────────────────────────────────────────────

def run_result_to_v1_format(result: RunResult) -> dict:
    """Convert V2 RunResult to V1-compatible BacktestResult dictionary.

    Used by the API layer to return responses in the existing schema format.
    """
    # Convert trades to V1 format
    v1_trades = []
    for t in result.closed_trades:
        v1_trades.append({
            "entry_bar": t.get("entry_bar", 0),
            "entry_time": 0,  # V2 doesn't store unix timestamp per trade
            "entry_price": t.get("entry_price", 0),
            "direction": t.get("side", "long"),
            "size": t.get("quantity", 0),
            "stop_loss": 0,
            "take_profit": 0,
            "exit_bar": t.get("exit_bar", 0),
            "exit_time": 0,
            "exit_price": t.get("exit_price", 0),
            "exit_reason": "v2_close",
            "pnl": t.get("pnl", 0),
            "pnl_pct": t.get("pnl_pct", 0),
        })

    # Equity curve (V1 uses flat list of equity values)
    equity = [e["equity"] for e in result.equity_curve] if result.equity_curve else []

    stats = result.stats

    return {
        "trades": v1_trades,
        "equity_curve": equity,
        "total_trades": stats.get("total_trades", 0),
        "winning_trades": stats.get("winning_trades", 0),
        "losing_trades": stats.get("losing_trades", 0),
        "win_rate": stats.get("win_rate", 0),
        "gross_profit": stats.get("gross_profit", 0),
        "gross_loss": stats.get("gross_loss", 0),
        "net_profit": stats.get("net_profit", 0),
        "profit_factor": stats.get("profit_factor", 0),
        "max_drawdown": stats.get("max_drawdown_pct", 0),
        "max_drawdown_pct": stats.get("max_drawdown_pct", 0),
        "avg_win": stats.get("avg_win", 0),
        "avg_loss": stats.get("avg_loss", 0),
        "largest_win": stats.get("largest_win", 0),
        "largest_loss": stats.get("largest_loss", 0),
        "avg_trade": stats.get("expectancy", 0),
        "sharpe_ratio": stats.get("sharpe_ratio", 0),
        "sqn": stats.get("sqn", 0),
        "expectancy": stats.get("expectancy", 0),
        "total_bars": stats.get("total_trades", 0),
    }


# ────────────────────────────────────────────────────────────────────
# Convenience: Run V1 config on V2 engine (drop-in replacement)
# ────────────────────────────────────────────────────────────────────

def run_v1_on_v2(
    bars: list[dict],
    strategy_config: dict,
    initial_balance: float = 10_000.0,
    spread_points: float = 0.0,
    commission_per_lot: float = 0.0,
    point_value: float = 1.0,
    symbol: str = "SYMBOL",
) -> dict:
    """
    One-call function to run a V1 strategy config through the V2 engine.

    Parameters:
        bars: List of dicts with keys: time, open, high, low, close, volume
        strategy_config: V1-format dict with indicators, entry_rules, etc.
        initial_balance: Starting capital
        spread_points: Full spread in price units
        commission_per_lot: Commission per lot
        point_value: Tick value multiplier
        symbol: Symbol name

    Returns:
        V1-compatible result dict (same shape as BacktestResult)
    """
    # Build data handler
    data_handler = DataHandler()
    indicators_config = strategy_config.get("indicators", [])
    data_handler.add_symbol(symbol, bars, indicators_config)

    # Build run config
    config = v1_config_to_run_config(
        strategy_config, initial_balance, spread_points,
        commission_per_lot, point_value,
    )

    # Build strategy adapter
    strategy = V1StrategyAdapter(strategy_config, symbol, point_value)

    # Run
    runner = Runner(data_handler=data_handler, strategy=strategy, config=config)
    result = runner.run()

    # Convert to V1 format
    return run_result_to_v1_format(result)
