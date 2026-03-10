"""
RL Agent evaluator for V2 backtest engine.

Wraps RLInferenceAgent as a StrategyBase subclass so the RL policy
can be backtested through the standard V2 event loop with full
slippage, spread, commission, and tearsheet analytics.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

from app.services.backtest.v2.engine.events import BarEvent, FillEvent
from app.services.backtest.v2.engine.strategy_base import StrategyBase

logger = logging.getLogger(__name__)

# Action constants (must match rl_environment.py)
ACTION_WAIT = 0
ACTION_BUY = 1
ACTION_SELL = 2
ACTION_CLOSE = 3
ACTION_TRAIL = 4


class RLBacktestStrategy(StrategyBase):
    """V2 strategy that uses a trained RL policy for trading decisions.

    The RL agent observes technical features + position state and outputs
    an action (wait/buy/sell/close/trail_stop).
    """

    def __init__(
        self,
        rl_agent,
        symbol: str = "ASSET",
        lot_size: float = 0.01,
        trail_atr_mult: float = 2.0,
    ):
        super().__init__(name="RLAgent", params={})
        self.rl_agent = rl_agent
        self.symbol = symbol
        self.lot_size = lot_size
        self.trail_atr_mult = trail_atr_mult
        # Position tracking for observation building
        self._position_dir = 0  # 0=flat, 1=long, -1=short
        self._entry_price = 0.0
        self._bars_in_trade = 0
        self._bars_since_close = 0
        self._peak_equity = 0.0
        self._action_counts = {i: 0 for i in range(5)}

    def on_init(self) -> None:
        self._peak_equity = self.ctx.get_equity()

    def on_bar(self, event: BarEvent) -> None:
        bar_idx = self.ctx.bar_index
        if bar_idx < 60:  # Need warm-up for features
            return

        # Build observation for RL agent
        bars_data = self._collect_recent_bars(event)
        if not bars_data:
            return

        # Get position state for context
        pos = self.ctx.get_position(self.symbol)
        if pos and not pos.is_flat:
            self._position_dir = 1 if pos.is_long else -1
            self._bars_in_trade += 1
        else:
            if self._position_dir != 0:
                self._bars_since_close = 0
            self._position_dir = 0
            self._entry_price = 0.0
            self._bars_in_trade = 0
            self._bars_since_close += 1

        position_state = {
            "position_dir": self._position_dir,
            "entry_price": self._entry_price,
            "bars_in_trade": self._bars_in_trade,
            "bars_since_close": self._bars_since_close,
        }

        # Update peak equity for drawdown
        equity = self.ctx.get_equity()
        if equity > self._peak_equity:
            self._peak_equity = equity

        # Get RL decision
        decision = self.rl_agent.decide(bars_data, position_state)
        if not decision:
            return

        action = decision.get("action", ACTION_WAIT)
        self._action_counts[action] = self._action_counts.get(action, 0) + 1

        # Execute action
        self._execute_action(action, event)

    def _execute_action(self, action: int, event: BarEvent) -> None:
        pos = self.ctx.get_position(self.symbol)
        is_flat = pos is None or pos.is_flat

        if action == ACTION_WAIT:
            pass

        elif action == ACTION_BUY:
            if is_flat:
                # Open long with ATR-based SL/TP
                atr = self._get_atr(self.ctx.bar_index)
                sl = event.close - atr * 2.0 if atr > 0 else 0.0
                tp = event.close + atr * 3.0 if atr > 0 else 0.0
                self.ctx.buy_bracket(
                    self.symbol, self.lot_size,
                    stop_loss=sl, take_profit=tp,
                    tag="rl_buy",
                )
                self._entry_price = event.close
                self._position_dir = 1
                self._bars_in_trade = 0

        elif action == ACTION_SELL:
            if is_flat:
                atr = self._get_atr(self.ctx.bar_index)
                sl = event.close + atr * 2.0 if atr > 0 else 0.0
                tp = event.close - atr * 3.0 if atr > 0 else 0.0
                self.ctx.sell_bracket(
                    self.symbol, self.lot_size,
                    stop_loss=sl, take_profit=tp,
                    tag="rl_sell",
                )
                self._entry_price = event.close
                self._position_dir = -1
                self._bars_in_trade = 0

        elif action == ACTION_CLOSE:
            if not is_flat:
                self.ctx.close_position(self.symbol, tag="rl_close")

        elif action == ACTION_TRAIL:
            if not is_flat:
                # Tighten stop loss using ATR
                atr = self._get_atr(self.ctx.bar_index)
                if atr > 0:
                    trail_dist = atr * self.trail_atr_mult
                    if pos.is_long:
                        new_sl = event.close - trail_dist
                        if new_sl > self._entry_price:
                            # Close and re-enter with tighter stop
                            self.ctx.close_position(self.symbol, tag="rl_trail")
                            self.ctx.buy_bracket(
                                self.symbol, self.lot_size,
                                stop_loss=new_sl,
                                take_profit=event.close + trail_dist * 1.5,
                                tag="rl_trail_re",
                            )
                    else:
                        new_sl = event.close + trail_dist
                        if new_sl < self._entry_price:
                            self.ctx.close_position(self.symbol, tag="rl_trail")
                            self.ctx.sell_bracket(
                                self.symbol, self.lot_size,
                                stop_loss=new_sl,
                                take_profit=event.close - trail_dist * 1.5,
                                tag="rl_trail_re",
                            )

    def on_fill(self, event: FillEvent) -> None:
        pass

    def on_end(self) -> None:
        total = sum(self._action_counts.values())
        if total > 0:
            logger.info(
                "RL action distribution: wait=%d buy=%d sell=%d close=%d trail=%d",
                self._action_counts[0], self._action_counts[1],
                self._action_counts[2], self._action_counts[3],
                self._action_counts[4],
            )

    def get_action_stats(self) -> dict:
        return dict(self._action_counts)

    # ── Helpers ──

    def _collect_recent_bars(self, event: BarEvent) -> list[dict]:
        """Collect last 60 bars as OHLCV dicts for RL agent."""
        bars = []
        for i in range(59, -1, -1):
            bar = self.ctx.get_bar(self.symbol, bars_ago=i)
            if bar is None:
                return []
            bars.append({
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": getattr(bar, "volume", 0.0),
            })
        return bars

    def _get_atr(self, bar_idx: int) -> float:
        dh = self.ctx._data_handler
        if dh is None:
            return 0.0
        sd = dh.get_symbol_data(self.symbol)
        if sd is None:
            return 0.0
        for key, arr in sd.indicator_arrays.items():
            if "atr" in key.lower() and bar_idx < len(arr):
                v = arr[bar_idx]
                if not math.isnan(v):
                    return v
        return 0.0
