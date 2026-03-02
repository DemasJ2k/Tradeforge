"""
Builder Strategy — Evaluates JSON rule-based strategies (visual builder).

Translates the strategy_config (indicators, entry_rules, exit_rules,
risk_params, filters) into V3 engine orders using the condition_engine.
"""

from __future__ import annotations

import math
import logging
from typing import Optional

from .bar import Bar
from .strategy import StrategyBase, StrategyContext
from .order import Order

# Reuse existing condition engine
from app.services.backtest.condition_engine import (
    evaluate_condition_tree,
    evaluate_direction,
    passes_filters as ce_passes_filters,
)

logger = logging.getLogger(__name__)


class BuilderStrategy(StrategyBase):
    """Strategy that evaluates visual-builder rule configs.

    Reads strategy_config with:
      - indicators: list of indicator configs
      - entry_rules: condition tree for entries
      - exit_rules: condition tree for exits
      - risk_params: SL/TP/sizing config
      - filters: time/volatility filters
    """

    def __init__(self, strategy_config: dict, symbol: str = "ASSET"):
        super().__init__(name="BuilderStrategy", params=strategy_config)
        self.symbol = symbol
        self.config = strategy_config
        self._risk = strategy_config.get("risk_params", {})

    def on_bar(self, bar: Bar) -> None:
        if self.ctx.bar_index < 1:
            return

        # 1. Check exits on open positions
        self._check_exits(bar)

        # 2. Check entries
        self._check_entries(bar)

    def _check_entries(self, bar: Bar) -> None:
        max_pos = self._risk.get("max_positions", 1)
        if not self.ctx.is_flat(self.symbol):
            return  # Already in a position

        # Check filters
        if not self._passes_filters(bar):
            return

        entry_rules = self.config.get("entry_rules", [])
        direction = evaluate_direction(
            entry_rules, self.ctx.bar_index, self._get_value
        )

        if direction:
            self._open_trade(bar, direction)

    def _open_trade(self, bar: Bar, direction: str) -> None:
        sl_type = self._risk.get("stop_loss_type", "fixed_pips")
        sl_val = self._risk.get("stop_loss_value", 50)
        tp_type = self._risk.get("take_profit_type", "fixed_pips")
        tp_val = self._risk.get("take_profit_value", 100)

        entry_price = bar.close
        atr_val = self._get_atr(self.ctx.bar_index)

        # Calculate SL
        sl = self._calc_level(entry_price, sl_type, sl_val, atr_val,
                              is_sl=True, is_long=(direction == "long"))

        # Calculate TP
        tp = self._calc_level(entry_price, tp_type, tp_val, atr_val,
                              is_sl=False, is_long=(direction == "long"))

        # Handle R:R ratio for TP
        if tp_type == "rr_ratio" and sl > 0:
            risk_dist = abs(entry_price - sl)
            if direction == "long":
                tp = entry_price + risk_dist * tp_val
            else:
                tp = entry_price - risk_dist * tp_val

        # Trailing stop
        trail = self._risk.get("trailing_stop_value", 0)
        trail_type = self._risk.get("trailing_stop_type", "")
        trail_offset = 0.0
        if trail > 0 and trail_type:
            if trail_type == "fixed_pips":
                trail_offset = trail * (self.ctx._instrument.point_value if self.ctx else 1)
            elif trail_type == "atr_multiple":
                trail_offset = trail * atr_val if atr_val > 0 else 0
            elif trail_type == "percent":
                trail_offset = entry_price * trail / 100

        # TP2 / lot split
        tp2_type = self._risk.get("take_profit_2_type", "")
        tp2_val = self._risk.get("take_profit_2_value", 0)
        lot_split = self._risk.get("lot_split", [])

        if tp2_type and tp2_val > 0 and lot_split and len(lot_split) == 2:
            tp2 = self._calc_level(entry_price, tp2_type, tp2_val, atr_val,
                                   is_sl=False, is_long=(direction == "long"))
            # Two bracket orders with lot split
            if direction == "long":
                self.ctx.buy_bracket(
                    stop_loss=sl, take_profit=tp, trail_offset=trail_offset,
                    symbol=self.symbol, tag="entry_tp1",
                )
                # Second bracket uses same SL but different TP
                self.ctx.buy_bracket(
                    stop_loss=sl, take_profit=tp2, trail_offset=trail_offset,
                    symbol=self.symbol, tag="entry_tp2",
                )
            else:
                self.ctx.sell_bracket(
                    stop_loss=sl, take_profit=tp, trail_offset=trail_offset,
                    symbol=self.symbol, tag="entry_tp1",
                )
                self.ctx.sell_bracket(
                    stop_loss=sl, take_profit=tp2, trail_offset=trail_offset,
                    symbol=self.symbol, tag="entry_tp2",
                )
        else:
            # Single bracket
            if direction == "long":
                self.ctx.buy_bracket(
                    stop_loss=sl, take_profit=tp, trail_offset=trail_offset,
                    symbol=self.symbol, tag="entry",
                )
            else:
                self.ctx.sell_bracket(
                    stop_loss=sl, take_profit=tp, trail_offset=trail_offset,
                    symbol=self.symbol, tag="entry",
                )

    def _check_exits(self, bar: Bar) -> None:
        """Check exit rules (SL/TP handled by bracket orders already)."""
        if self.ctx.is_flat(self.symbol):
            return

        exit_rules = self.config.get("exit_rules", [])
        if exit_rules:
            triggered = evaluate_condition_tree(
                exit_rules, self.ctx.bar_index, self._get_value
            )
            if triggered:
                self.ctx.close_position(self.symbol, tag="exit_signal")

    # ── Helpers ─────────────────────────────────────────────────────

    def _get_value(self, source: str, bar_idx: int) -> float:
        """Value resolver for the condition engine."""
        val = self.ctx.get_indicator(source, bars_ago=self.ctx.bar_index - bar_idx)
        if not math.isnan(val):
            return val
        # Try numeric literal
        try:
            return float(source)
        except (ValueError, TypeError):
            return float("nan")

    def _get_atr(self, bar_idx: int) -> float:
        """Find ATR indicator value."""
        # Search for any ATR indicator
        sd = self.ctx._feed.get_symbol_data(self.symbol)
        if sd:
            for key in sd.indicators:
                if "atr" in key.lower():
                    val = sd.get_indicator(key, bar_idx)
                    if not math.isnan(val):
                        return val
        return 0.0

    def _calc_level(
        self, entry: float, level_type: str, value: float,
        atr_val: float, is_sl: bool, is_long: bool,
    ) -> float:
        """Calculate SL or TP price level."""
        if value <= 0:
            return 0.0

        pv = self.ctx._instrument.point_value if self.ctx else 1.0

        if level_type == "fixed_pips":
            dist = value * pv
        elif level_type == "atr_multiple":
            dist = value * atr_val if atr_val > 0 else value * pv
        elif level_type in ("atr_pct", "adr_pct"):
            adr_val = self._get_indicator_val("adr", self.ctx.bar_index)
            dist = adr_val * value / 100 if adr_val > 0 else value * pv
        elif level_type == "percent":
            dist = entry * value / 100
        elif level_type == "rr_ratio":
            return 0.0  # Handled by caller
        else:
            dist = value * pv

        if is_long:
            return entry - dist if is_sl else entry + dist
        else:
            return entry + dist if is_sl else entry - dist

    def _get_indicator_val(self, prefix: str, bar_idx: int) -> float:
        sd = self.ctx._feed.get_symbol_data(self.symbol)
        if sd:
            for key in sd.indicators:
                if prefix in key.lower():
                    val = sd.get_indicator(key, bar_idx)
                    if not math.isnan(val):
                        return val
        return 0.0

    def _passes_filters(self, bar: Bar) -> bool:
        filters = self.config.get("filters", {})
        if not filters:
            return True
        return ce_passes_filters(
            filters, bar.timestamp, self._get_value, self.ctx.bar_index
        )
