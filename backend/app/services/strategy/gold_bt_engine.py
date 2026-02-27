"""
Gold Breakout Trader (Gold BT) Strategy Engine — TradeForge Port.

Ported from: PineScript "Gold Breakout Trader" indicator.

Core logic:
  1. At periodic intervals (every N hours), capture reference price = close
  2. Build zones around reference:
     - Gray box: refPrice ± boxHeight/2
     - Buy Stop = grayBoxTop + buffer
     - Sell Stop = grayBoxBottom - buffer
  3. BUY signal when close crosses above Buy Stop
  4. SELL signal when close crosses below Sell Stop
  5. TP1/TP2/TP3 calculated from stacked zone heights
  6. SL = opposite stop level (or configurable distance)
"""

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_GOLD_BT_CONFIG = {
    "trigger_interval_hours": 2,    # Create zones every N hours
    "box_height": 10.0,            # Gray box height in USD
    "stop_line_buffer": 2.0,       # Buffer from gray box to stop lines
    "stop_to_tp_gap": 2.0,        # Gap from stop line to first TP zone
    "tp_zone_gap": 1.0,           # Gap between TP zones
    "tp1_height": 4.0,            # TP1 zone height in USD
    "tp2_height": 4.0,            # TP2 zone height in USD
    "tp3_height": 4.0,            # TP3 zone height in USD
    "sl_type": "opposite_stop",   # opposite_stop | gray_box | fixed_usd
    "sl_fixed_usd": 14.0,         # Only used when sl_type = fixed_usd
    "use_tp2": True,              # Whether to use TP2 as main target
    "use_tp3": False,             # Whether to use TP3 as main target
    "lot_split": [0.5, 0.5],     # TP1/TP2 lot split
}


@dataclass
class GoldBTSignal:
    """Signal emitted when price crosses a stop level."""
    direction: int              # 1 = bullish (BUY), -1 = bearish (SELL)
    signal_type: str            # "BREAKOUT_BUY" or "BREAKOUT_SELL"
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit_1: float = 0.0
    take_profit_2: float = 0.0
    take_profit_3: float = 0.0
    ref_price: float = 0.0
    buy_stop: float = 0.0
    sell_stop: float = 0.0
    bar_time: Optional[datetime] = None
    is_reversal: bool = True
    confidence: float = 0.0
    reason: str = ""


class GoldBTEngine:
    """
    Gold Breakout Trader strategy engine for a single symbol (XAUUSD).

    Maintains state:
    - ref_price: Current reference price (set at trigger intervals)
    - buy_stop / sell_stop: Current stop levels
    - last_trigger_time: When zones were last set

    Usage:
        engine = GoldBTEngine("XAUUSD")
        signal = engine.evaluate(bars)
        if signal:
            # signal has entry_price, sl, tp1, tp2, tp3
    """

    def __init__(self, symbol: str, config: Optional[dict] = None):
        self.symbol = symbol
        cfg = {**DEFAULT_GOLD_BT_CONFIG, **(config or {})}

        # Strategy parameters
        self.trigger_interval_hours: int = cfg["trigger_interval_hours"]
        self.box_height: float = cfg["box_height"]
        self.stop_line_buffer: float = cfg["stop_line_buffer"]
        self.stop_to_tp_gap: float = cfg["stop_to_tp_gap"]
        self.tp_zone_gap: float = cfg["tp_zone_gap"]
        self.tp1_height: float = cfg["tp1_height"]
        self.tp2_height: float = cfg["tp2_height"]
        self.tp3_height: float = cfg["tp3_height"]
        self.sl_type: str = cfg["sl_type"]
        self.sl_fixed_usd: float = cfg["sl_fixed_usd"]
        self.use_tp2: bool = cfg["use_tp2"]
        self.use_tp3: bool = cfg["use_tp3"]
        self.lot_split: list[float] = cfg.get("lot_split", [0.5, 0.5])

        # Persistent state
        self.ref_price: float = 0.0
        self.buy_stop: float = 0.0
        self.sell_stop: float = 0.0
        self.last_trigger_time: Optional[datetime] = None
        self.last_processed_bar_time: Optional[int] = None
        self._warmed_up: bool = False

        # Derived zone levels (recalculated on each trigger)
        self.tp1_up: float = 0.0
        self.tp2_up: float = 0.0
        self.tp3_up: float = 0.0
        self.tp1_dn: float = 0.0
        self.tp2_dn: float = 0.0
        self.tp3_dn: float = 0.0

        # Statistics
        self.total_signals: int = 0
        self.buy_signals: int = 0
        self.sell_signals: int = 0

        logger.info(
            "[GoldBT] %s: Engine initialized | Interval=%dh Box=%.1f Buffer=%.1f TP1=%.1f TP2=%.1f TP3=%.1f",
            symbol, self.trigger_interval_hours, self.box_height,
            self.stop_line_buffer, self.tp1_height, self.tp2_height, self.tp3_height,
        )

    def _is_trigger_bar(self, bar_time: datetime) -> bool:
        """Check if this bar aligns with a trigger interval."""
        interval_secs = self.trigger_interval_hours * 3600
        # Trigger when bar_time is on the interval boundary (minute = 0)
        if bar_time.minute != 0:
            return False
        if bar_time.hour % self.trigger_interval_hours != 0:
            return False
        # Avoid re-triggering same interval
        if self.last_trigger_time and bar_time <= self.last_trigger_time:
            return False
        return True

    def _recalc_zones(self, ref_price: float):
        """Recalculate all zone levels from reference price."""
        self.ref_price = ref_price
        half_box = self.box_height / 2.0
        gray_top = ref_price + half_box
        gray_bot = ref_price - half_box

        self.buy_stop = gray_top + self.stop_line_buffer
        self.sell_stop = gray_bot - self.stop_line_buffer

        # TP zones above (for BUY trades)
        tp1_up_bot = self.buy_stop + self.stop_to_tp_gap
        tp1_up_top = tp1_up_bot + self.tp1_height
        self.tp1_up = (tp1_up_top + tp1_up_bot) / 2.0

        tp2_up_bot = tp1_up_top + self.tp_zone_gap
        tp2_up_top = tp2_up_bot + self.tp2_height
        self.tp2_up = (tp2_up_top + tp2_up_bot) / 2.0

        tp3_up_bot = tp2_up_top + self.tp_zone_gap
        tp3_up_top = tp3_up_bot + self.tp3_height
        self.tp3_up = (tp3_up_top + tp3_up_bot) / 2.0

        # TP zones below (for SELL trades)
        tp1_dn_top = self.sell_stop - self.stop_to_tp_gap
        tp1_dn_bot = tp1_dn_top - self.tp1_height
        self.tp1_dn = (tp1_dn_top + tp1_dn_bot) / 2.0

        tp2_dn_top = tp1_dn_bot - self.tp_zone_gap
        tp2_dn_bot = tp2_dn_top - self.tp2_height
        self.tp2_dn = (tp2_dn_top + tp2_dn_bot) / 2.0

        tp3_dn_top = tp2_dn_bot - self.tp_zone_gap
        tp3_dn_bot = tp3_dn_top - self.tp3_height
        self.tp3_dn = (tp3_dn_top + tp3_dn_bot) / 2.0

    def warmup(self, bars: list[dict]) -> None:
        """Replay bars to establish initial zone state."""
        if not bars:
            return
        for bar in bars:
            ts = int(bar["time"])
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            if self._is_trigger_bar(dt):
                self._recalc_zones(bar["close"])
                self.last_trigger_time = dt
        self._warmed_up = True
        self.last_processed_bar_time = int(bars[-1]["time"])
        logger.info(
            "[GoldBT] %s: Warmup complete | %d bars | ref=%.2f buy_stop=%.2f sell_stop=%.2f",
            self.symbol, len(bars), self.ref_price, self.buy_stop, self.sell_stop,
        )

    def evaluate(self, bars: list[dict]) -> Optional[GoldBTSignal]:
        """
        Evaluate bars and return a GoldBTSignal if a breakout is detected.

        Args:
            bars: List of bar dicts with keys: time, open, high, low, close, volume.

        Returns:
            GoldBTSignal if breakout detected, None otherwise.
        """
        if not bars or len(bars) < 2:
            return None

        last_bar = bars[-1]
        prev_bar = bars[-2]
        current_bar_time = int(last_bar["time"])

        # Deduplicate
        if self.last_processed_bar_time == current_bar_time:
            return None

        # Auto-warmup
        if not self._warmed_up:
            self.warmup(bars[:-1])

        dt = datetime.fromtimestamp(current_bar_time, tz=timezone.utc)

        # Check if this is a trigger bar — update zones
        if self._is_trigger_bar(dt):
            self._recalc_zones(last_bar["close"])
            self.last_trigger_time = dt
            self.last_processed_bar_time = current_bar_time
            return None  # Don't signal on the trigger bar itself

        self.last_processed_bar_time = current_bar_time

        # No zones set yet
        if self.buy_stop == 0 or self.sell_stop == 0:
            return None

        # Check for crossover: close crosses above buy_stop
        prev_close = prev_bar["close"]
        curr_close = last_bar["close"]

        # BUY: previous close <= buy_stop AND current close > buy_stop
        if prev_close <= self.buy_stop and curr_close > self.buy_stop:
            return self._build_signal(1, curr_close, dt)

        # SELL: previous close >= sell_stop AND current close < sell_stop
        if prev_close >= self.sell_stop and curr_close < self.sell_stop:
            return self._build_signal(-1, curr_close, dt)

        return None

    def _build_signal(self, direction: int, close_price: float, bar_time: datetime) -> GoldBTSignal:
        """Build a GoldBTSignal from current state."""
        if direction == 1:  # BUY
            entry = self.buy_stop
            tp1 = self.tp1_up
            tp2 = self.tp2_up
            tp3 = self.tp3_up

            if self.sl_type == "opposite_stop":
                sl = self.sell_stop
            elif self.sl_type == "gray_box":
                sl = self.ref_price - self.box_height / 2.0
            else:
                sl = entry - self.sl_fixed_usd

            signal_type = "BREAKOUT_BUY"
        else:  # SELL
            entry = self.sell_stop
            tp1 = self.tp1_dn
            tp2 = self.tp2_dn
            tp3 = self.tp3_dn

            if self.sl_type == "opposite_stop":
                sl = self.buy_stop
            elif self.sl_type == "gray_box":
                sl = self.ref_price + self.box_height / 2.0
            else:
                sl = entry + self.sl_fixed_usd

            signal_type = "BREAKOUT_SELL"

        self.total_signals += 1
        if direction == 1:
            self.buy_signals += 1
        else:
            self.sell_signals += 1

        dir_str = "BUY" if direction == 1 else "SELL"
        risk = abs(entry - sl)
        reward = abs(tp1 - entry)
        confidence = min(0.8, reward / risk) if risk > 0 else 0.3

        logger.info(
            "[GoldBT] %s: %s | Entry=%.2f SL=%.2f TP1=%.2f TP2=%.2f TP3=%.2f",
            self.symbol, dir_str, entry, sl, tp1, tp2, tp3,
        )

        return GoldBTSignal(
            direction=direction,
            signal_type=signal_type,
            entry_price=entry,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            take_profit_3=tp3,
            ref_price=self.ref_price,
            buy_stop=self.buy_stop,
            sell_stop=self.sell_stop,
            bar_time=bar_time,
            is_reversal=True,
            confidence=confidence,
            reason=f"{dir_str} breakout at {entry:.2f} (ref={self.ref_price:.2f})",
        )

    def has_reversal_signal(self, bars: list[dict]) -> bool:
        """Check if opposite breakout occurred (to close existing positions)."""
        if not bars or len(bars) < 2 or self.buy_stop == 0:
            return False
        prev_close = bars[-2]["close"]
        curr_close = bars[-1]["close"]
        buy_cross = prev_close <= self.buy_stop and curr_close > self.buy_stop
        sell_cross = prev_close >= self.sell_stop and curr_close < self.sell_stop
        return buy_cross or sell_cross

    def get_state_summary(self) -> dict:
        return {
            "symbol": self.symbol,
            "ref_price": self.ref_price,
            "buy_stop": self.buy_stop,
            "sell_stop": self.sell_stop,
            "tp1_up": self.tp1_up,
            "tp2_up": self.tp2_up,
            "tp3_up": self.tp3_up,
            "tp1_dn": self.tp1_dn,
            "tp2_dn": self.tp2_dn,
            "tp3_dn": self.tp3_dn,
            "total_signals": self.total_signals,
            "buy_signals": self.buy_signals,
            "sell_signals": self.sell_signals,
            "last_trigger": self.last_trigger_time.isoformat() if self.last_trigger_time else None,
        }
