"""
V2-native strategy implementations for MSS and Gold Breakout.

These replace the legacy ``strategy_backtester.py`` functions by
expressing the same logic as proper ``StrategyBase`` subclasses.
They benefit from V2's fill pipeline (slippage, spread, volume impact),
metrics, and tearsheet — eliminating the hardcoded ×100 PnL multiplier.
"""

from __future__ import annotations

import math
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.backtest.v2.engine.events import BarEvent
from app.services.backtest.v2.engine.strategy_base import StrategyBase, StrategyContext

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
#  MSS Strategy (Market Structure Shift)
# ════════════════════════════════════════════════════════════════════

class MSSStrategy(StrategyBase):
    """Market Structure Shift (MSS) strategy expressed as a V2 StrategyBase.

    Detects swing pivot highs/lows using a lookback window, identifies
    breakout (close above pivot high = bullish, close below pivot low =
    bearish), and enters trades with ADR10-based SL/TP levels.

    Config keys (passed via ``params``):
        swing_lb         – pivot lookback (default 42)
        tp1_pct          – TP1 as % of ADR10 (default 15.0)
        tp2_pct          – TP2 as % of ADR10 (default 25.0)
        sl_pct           – SL as % of ADR10 (default 25.0)
        use_pullback     – use pullback entry (default True)
        pb_pct           – pullback fib fraction (default 0.382)
        confirm          – "close" or "high/low" (default "close")
        lot_size         – position size in lots (default 0.01)
    """

    def __init__(self, symbol: str, params: dict[str, Any] | None = None):
        super().__init__(name="MSS_V2", params=params or {})
        self.symbol = symbol

        cfg = self.params
        self.lb: int = cfg.get("swing_lb", 42)
        self.tp1_pct: float = cfg.get("tp1_pct", 15.0)
        self.tp2_pct: float = cfg.get("tp2_pct", 25.0)
        self.sl_pct: float = cfg.get("sl_pct", 25.0)
        self.use_pullback: bool = cfg.get("use_pullback", True)
        self.pb_pct: float = cfg.get("pb_pct", 0.382)
        self.use_close: bool = cfg.get("confirm", "close") == "close"
        self.lot_size: float = cfg.get("lot_size", 0.01)

        # Runtime state
        self._pivot_highs: list[Optional[float]] = []
        self._pivot_lows: list[Optional[float]] = []
        self._last_high: float = float("nan")
        self._last_low: float = float("nan")
        self._high_active: bool = False
        self._low_active: bool = False
        self._daily_ranges: list[float] = []
        self._day_high: float = 0.0
        self._day_low: float = float("inf")
        self._prev_day: int = -1
        self._active_dir: int = 0  # 0=flat, 1=long, -1=short

    # ── Helpers ─────────────────────────────────────────────────────

    def _get_highs_lows_closes(self, n: int):
        """Collect historical H/L/C arrays from data handler."""
        highs, lows, closes = [], [], []
        for ago in range(n - 1, -1, -1):
            h = self.ctx.get_value(self.symbol, "price.high", bars_ago=ago)
            l = self.ctx.get_value(self.symbol, "price.low", bars_ago=ago)
            c = self.ctx.get_value(self.symbol, "price.close", bars_ago=ago)
            highs.append(h if h is not None else 0.0)
            lows.append(l if l is not None else 0.0)
            closes.append(c if c is not None else 0.0)
        return highs, lows, closes

    def _compute_adr10(self, bar_index: int) -> float:
        """Compute ADR10 (Average Daily Range over last 10 trading days)."""
        # Update daily range tracking
        h = self.ctx.get_value(self.symbol, "price.high") or 0.0
        l = self.ctx.get_value(self.symbol, "price.low") or 0.0
        ts = self.ctx.get_value(self.symbol, "price.time") or 0.0

        if ts > 0:
            try:
                dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                day_ord = dt.toordinal()
            except (OSError, ValueError):
                day_ord = -1
        else:
            day_ord = bar_index  # fallback: treat each bar as a "day"

        if self._prev_day == -1:
            self._prev_day = day_ord

        if day_ord != self._prev_day:
            # New day — save previous day's range
            if self._day_high > self._day_low:
                self._daily_ranges.append(self._day_high - self._day_low)
            self._day_high = h
            self._day_low = l
            self._prev_day = day_ord
        else:
            self._day_high = max(self._day_high, h)
            self._day_low = min(self._day_low, l) if l > 0 else self._day_low

        if not self._daily_ranges:
            return 0.0
        last_n = self._daily_ranges[-10:]
        return sum(last_n) / len(last_n)

    # ── Main ────────────────────────────────────────────────────────

    def on_bar(self, event: BarEvent) -> None:
        bar_idx = self.ctx.bar_index
        lb = self.lb

        if bar_idx < lb * 2:
            # Still warming up — accumulate ADR data
            self._compute_adr10(bar_idx)
            return

        # Get current bar data
        cur_high = event.high
        cur_low = event.low
        cur_close = event.close

        # ADR10
        adr = self._compute_adr10(bar_idx)

        # --- Detect pivot at bar (bar_idx - lb) ---
        pivot_bar = bar_idx - lb
        if pivot_bar >= lb:
            # Check pivot high
            center_h = self.ctx.get_value(self.symbol, "price.high", bars_ago=lb) or 0.0
            is_pivot_high = True
            is_pivot_low = True
            center_l = self.ctx.get_value(self.symbol, "price.low", bars_ago=lb) or 0.0

            for offset in range(-lb, lb + 1):
                if offset == 0:
                    continue
                bars_ago = lb - offset
                if bars_ago < 0:
                    bars_ago = 0
                h_val = self.ctx.get_value(self.symbol, "price.high", bars_ago=bars_ago)
                l_val = self.ctx.get_value(self.symbol, "price.low", bars_ago=bars_ago)
                if h_val is not None and h_val >= center_h:
                    is_pivot_high = False
                if l_val is not None and l_val <= center_l:
                    is_pivot_low = False
                if not is_pivot_high and not is_pivot_low:
                    break

            if is_pivot_high and center_h > 0:
                self._last_high = center_h
                self._high_active = True
            if is_pivot_low and center_l > 0:
                self._last_low = center_l
                self._low_active = True

        # Breakout detection
        src_h = cur_close if self.use_close else cur_high
        src_l = cur_close if self.use_close else cur_low

        bullish = False
        bearish = False

        if self._high_active and not math.isnan(self._last_high) and src_h > self._last_high:
            bullish = True
            self._high_active = False
        if self._low_active and not math.isnan(self._last_low) and src_l < self._last_low:
            bearish = True
            self._low_active = False

        # --- Check exits for active position ---
        pos = self.ctx.get_position(self.symbol)
        has_pos = pos is not None and not pos.is_flat

        # --- Signal handling ---
        signal_dir = 0
        if bullish and not math.isnan(self._last_high):
            signal_dir = 1
        elif bearish and not math.isnan(self._last_low):
            signal_dir = -1

        if signal_dir == 0:
            return

        # Close existing position on reversal
        if has_pos:
            self.ctx.close_position(self.symbol, tag="reversal")

        # Open new trade
        if adr <= 0:
            return

        tp1_dist = adr * (self.tp1_pct / 100.0)
        tp2_dist = adr * (self.tp2_pct / 100.0)
        sl_dist = adr * (self.sl_pct / 100.0)

        pivot = self._last_high if signal_dir == 1 else self._last_low

        if signal_dir == 1:
            entry = pivot - self.pb_pct * sl_dist if self.use_pullback else pivot
            sl = entry - sl_dist
            tp2 = entry + tp2_dist
        else:
            entry = pivot + self.pb_pct * sl_dist if self.use_pullback else pivot
            sl = entry + sl_dist
            tp2 = entry - tp2_dist

        if signal_dir == 1:
            self.ctx.buy_bracket(
                self.symbol, self.lot_size,
                stop_loss=sl, take_profit=tp2,
                tag="mss_long",
            )
        else:
            self.ctx.sell_bracket(
                self.symbol, self.lot_size,
                stop_loss=sl, take_profit=tp2,
                tag="mss_short",
            )


# ════════════════════════════════════════════════════════════════════
#  Gold Breakout Strategy
# ════════════════════════════════════════════════════════════════════

class GoldBreakoutStrategy(StrategyBase):
    """Gold Breakout strategy expressed as a V2 StrategyBase.

    At configurable interval triggers (every N hours on the hour),
    marks a reference price and computes a "box" with buy_stop and
    sell_stop levels.  Entries on breakout; SL/TP zones are box-derived.

    Config keys (passed via ``params``):
        trigger_interval_hours – interval (default 2)
        box_height             – box height in price units (default 10.0)
        stop_line_buffer       – buffer beyond box edge (default 2.0)
        stop_to_tp_gap         – gap between stop line and TP1 zone (default 2.0)
        tp_zone_gap            – gap between TP1 and TP2 zones (default 1.0)
        tp1_height             – TP1 zone height (default 4.0)
        tp2_height             – TP2 zone height (default 4.0)
        sl_type                – "opposite_stop", "gray_box", or "fixed" (default "opposite_stop")
        sl_fixed_usd           – fixed SL distance if sl_type="fixed" (default 14.0)
        lot_size               – position size in lots (default 0.01)
    """

    def __init__(self, symbol: str, params: dict[str, Any] | None = None):
        super().__init__(name="GoldBT_V2", params=params or {})
        self.symbol = symbol

        cfg = self.params
        self.interval_h: int = cfg.get("trigger_interval_hours", 2)
        self.box_h: float = cfg.get("box_height", 10.0)
        self.buffer: float = cfg.get("stop_line_buffer", 2.0)
        self.s2tp_gap: float = cfg.get("stop_to_tp_gap", 2.0)
        self.tp_gap: float = cfg.get("tp_zone_gap", 1.0)
        self.tp1_h: float = cfg.get("tp1_height", 4.0)
        self.tp2_h: float = cfg.get("tp2_height", 4.0)
        self.sl_type: str = cfg.get("sl_type", "opposite_stop")
        self.sl_fixed: float = cfg.get("sl_fixed_usd", 14.0)
        self.lot_size: float = cfg.get("lot_size", 0.01)

        # Runtime state
        self._ref_price: float = 0.0
        self._buy_stop: float = 0.0
        self._sell_stop: float = 0.0
        self._last_trigger_hour: int = -1
        self._last_trigger_day: int = -1
        self._prev_close: float = 0.0

    # ── Helpers ─────────────────────────────────────────────────────

    def _calc_levels(self, direction: int) -> tuple[float, float, float, float]:
        """Compute (entry, sl, tp1_mid, tp2_mid)."""
        if direction == 1:
            entry = self._buy_stop
            t1_bot = entry + self.s2tp_gap
            t1_top = t1_bot + self.tp1_h
            tp1_mid = (t1_top + t1_bot) / 2.0
            t2_bot = t1_top + self.tp_gap
            t2_top = t2_bot + self.tp2_h
            tp2_mid = (t2_top + t2_bot) / 2.0
            if self.sl_type == "opposite_stop":
                sl = self._sell_stop
            elif self.sl_type == "gray_box":
                sl = self._ref_price - self.box_h / 2.0
            else:
                sl = entry - self.sl_fixed
        else:
            entry = self._sell_stop
            t1_top = entry - self.s2tp_gap
            t1_bot = t1_top - self.tp1_h
            tp1_mid = (t1_top + t1_bot) / 2.0
            t2_top = t1_bot - self.tp_gap
            t2_bot = t2_top - self.tp2_h
            tp2_mid = (t2_top + t2_bot) / 2.0
            if self.sl_type == "opposite_stop":
                sl = self._buy_stop
            elif self.sl_type == "gray_box":
                sl = self._ref_price + self.box_h / 2.0
            else:
                sl = entry + self.sl_fixed

        return entry, sl, tp1_mid, tp2_mid

    # ── Main ────────────────────────────────────────────────────────

    def on_bar(self, event: BarEvent) -> None:
        bar_idx = self.ctx.bar_index
        if bar_idx < 1:
            self._prev_close = event.close
            return

        # Check trigger (every N hours at :00)
        ts = event.timestamp_ns / 1e9 if event.timestamp_ns > 1e15 else event.timestamp_ns
        try:
            dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            h, m = dt.hour, dt.minute
            day_ord = dt.toordinal()
        except (OSError, ValueError):
            h, m, day_ord = -1, -1, -1

        is_trigger = False
        if m == 0 and h >= 0 and h % self.interval_h == 0:
            if day_ord != self._last_trigger_day or h != self._last_trigger_hour:
                is_trigger = True
                self._last_trigger_day = day_ord
                self._last_trigger_hour = h

        if is_trigger:
            self._ref_price = event.close
            half = self.box_h / 2.0
            self._buy_stop = self._ref_price + half + self.buffer
            self._sell_stop = self._ref_price - half - self.buffer
            self._prev_close = event.close
            return

        if self._buy_stop == 0:
            self._prev_close = event.close
            return

        # Check for new entry signals
        prev_close = self._prev_close
        curr_close = event.close

        new_signal = 0
        if prev_close <= self._buy_stop and curr_close > self._buy_stop:
            new_signal = 1
        elif prev_close >= self._sell_stop and curr_close < self._sell_stop:
            new_signal = -1

        if new_signal != 0:
            # Close existing position on reversal
            pos = self.ctx.get_position(self.symbol)
            if pos is not None and not pos.is_flat:
                self.ctx.close_position(self.symbol, tag="reversal")

            # Open new trade with bracket
            _entry, sl, _tp1, tp2 = self._calc_levels(new_signal)

            if new_signal == 1:
                self.ctx.buy_bracket(
                    self.symbol, self.lot_size,
                    stop_loss=sl, take_profit=tp2,
                    tag="gold_bt_long",
                )
            else:
                self.ctx.sell_bracket(
                    self.symbol, self.lot_size,
                    stop_loss=sl, take_profit=tp2,
                    tag="gold_bt_short",
                )

        self._prev_close = event.close
