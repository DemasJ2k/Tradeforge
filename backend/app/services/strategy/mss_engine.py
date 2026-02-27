"""
Market Structure Shift (MSS) Strategy Engine — TradeForge Port.

Ported from: mt5_live_trading_bot-main/src/mss_strategy_engine.py

Core logic:
  1. Pivot High/Low detection with configurable lookback (default 42)
  2. BOS (Break of Structure) / CHoCH (Change of Character) detection
  3. Entry at breakout level with synthetic pullback adjustment
  4. TP1/TP2/SL based on ADR10 percentages
  5. Reversal: close ALL positions when new BOS/CHoCH fires

Adapted to work with TradeForge bar format (list[dict]) instead of
numpy structured arrays from MT5 directly.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Default MSS configuration matching the proven live bot params
DEFAULT_MSS_CONFIG = {
    "swing_lb": 42,
    "tp1_pct": 15.0,
    "tp2_pct": 25.0,
    "sl_pct": 25.0,
    "confirm": "close",       # Use close price for breakout confirmation
    "htf_filter": False,
    "use_pullback": True,
    "pb_pct": 0.382,
}


@dataclass
class MSSSignal:
    """Signal emitted when a BOS or CHoCH is detected."""
    direction: int              # 1 = bullish, -1 = bearish
    signal_type: str            # "BOS" or "CHoCH"
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit_1: float = 0.0
    take_profit_2: float = 0.0
    pivot_level: float = 0.0
    adr10: float = 0.0
    bar_time: Optional[datetime] = None
    is_reversal: bool = True
    confidence: float = 0.0
    reason: str = ""


class MSSEngine:
    """
    Market Structure Shift strategy engine for a single symbol.

    Maintains PERSISTENT state across bar updates:
    - last_high / last_low: Most recent confirmed pivot levels
    - high_active / low_active: Whether those pivots are still unbroken
    - last_break_dir: Direction of last breakout (for CHoCH detection)

    Usage:
        engine = MSSEngine("XAUUSD")
        signal = engine.evaluate(bars, adr10=25.0)
        if signal:
            # signal is an MSSSignal with entry_price, sl, tp1, tp2, etc.
    """

    def __init__(self, symbol: str, config: Optional[dict] = None):
        self.symbol = symbol
        cfg = {**DEFAULT_MSS_CONFIG, **(config or {})}

        # Strategy parameters
        self.swing_lb: int = cfg["swing_lb"]
        self.tp1_pct: float = cfg["tp1_pct"]
        self.tp2_pct: float = cfg["tp2_pct"]
        self.sl_pct: float = cfg["sl_pct"]
        self.use_close: bool = cfg["confirm"] == "close"
        self.htf_filter: bool = cfg["htf_filter"]
        self.use_pullback: bool = cfg["use_pullback"]
        self.pb_pct: float = cfg["pb_pct"]

        # Persistent state
        self.last_high: float = float("nan")
        self.last_low: float = float("nan")
        self.high_active: bool = False
        self.low_active: bool = False
        self.last_break_dir: int = 0  # 1=bullish, -1=bearish

        self.last_processed_bar_time: Optional[int] = None
        self._warmed_up: bool = False

        # Statistics
        self.total_signals: int = 0
        self.bullish_signals: int = 0
        self.bearish_signals: int = 0

        logger.info(
            "[MSS] %s: Engine initialized | LB=%d TP1=%.1f%% TP2=%.1f%% SL=%.1f%% PB=%s",
            symbol, self.swing_lb, self.tp1_pct, self.tp2_pct, self.sl_pct,
            f"{self.pb_pct}" if self.use_pullback else "OFF",
        )

    # ── Helpers ─────────────────────────────────────────────

    @staticmethod
    def compute_adr10(daily_bars: list[dict]) -> float:
        """Compute 10-day Average Daily Range from D1 bars (list of dicts)."""
        if not daily_bars:
            return 0.0
        ranges = [b["high"] - b["low"] for b in daily_bars]
        n = min(10, len(ranges))
        return sum(ranges[-n:]) / n

    @staticmethod
    def _is_pivot_high(highs: list[float], i: int, lb: int) -> bool:
        """Check if bar i is a pivot high: unique maximum in [i-lb, i+lb]."""
        window = highs[i - lb: i + lb + 1]
        val = highs[i]
        return val == max(window) and window.count(val) == 1

    @staticmethod
    def _is_pivot_low(lows: list[float], i: int, lb: int) -> bool:
        """Check if bar i is a pivot low: unique minimum in [i-lb, i+lb]."""
        window = lows[i - lb: i + lb + 1]
        val = lows[i]
        return val == min(window) and window.count(val) == 1

    # ── Warmup ──────────────────────────────────────────────

    def warmup(self, bars: list[dict]) -> None:
        """
        First-time initialization: replay all available bars to build up
        the full structure state. Should be called with maximum available
        history for best accuracy.
        """
        N = len(bars)
        min_needed = self.swing_lb * 2 + 1
        if N < min_needed:
            logger.warning("[MSS] %s: Warmup data too short (%d bars, need %d)", self.symbol, N, min_needed)
            return

        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]
        closes = [b["close"] for b in bars]

        # Detect all pivots
        pivot_highs: list[Optional[float]] = [None] * N
        pivot_lows: list[Optional[float]] = [None] * N

        for i in range(self.swing_lb, N - self.swing_lb):
            if self._is_pivot_high(highs, i, self.swing_lb):
                pivot_highs[i] = highs[i]
            if self._is_pivot_low(lows, i, self.swing_lb):
                pivot_lows[i] = lows[i]

        # Replay all bars to build structure state
        for i in range(self.swing_lb * 2, N):
            pivot_bar = i - self.swing_lb
            if pivot_bar >= 0:
                if pivot_highs[pivot_bar] is not None:
                    self.last_high = pivot_highs[pivot_bar]
                    self.high_active = True
                if pivot_lows[pivot_bar] is not None:
                    self.last_low = pivot_lows[pivot_bar]
                    self.low_active = True

            # Breakout detection
            src_high = closes[i] if self.use_close else highs[i]
            src_low = closes[i] if self.use_close else lows[i]

            if self.high_active and not math.isnan(self.last_high):
                if src_high > self.last_high:
                    self.high_active = False
                    self.last_break_dir = 1

            if self.low_active and not math.isnan(self.last_low):
                if src_low < self.last_low:
                    self.low_active = False
                    self.last_break_dir = -1

        self.last_processed_bar_time = int(bars[-1]["time"])
        self._warmed_up = True

        logger.info(
            "[MSS] %s: Warmup complete | %d bars | last_high=%.5f active=%s | last_low=%.5f active=%s | break_dir=%d",
            self.symbol, N, self.last_high, self.high_active, self.last_low, self.low_active, self.last_break_dir,
        )

    # ── Incremental bar processing ──────────────────────────

    def _process_new_bar(self, bars: list[dict]) -> Optional[dict]:
        """
        Process ONLY the newest bar using persisted state.

        Returns signal dict or None.
        """
        N = len(bars)
        last_idx = N - 1

        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]
        closes = [b["close"] for b in bars]

        # Step 1: Check for newly confirmed pivot
        pivot_candidate_idx = last_idx - self.swing_lb
        if pivot_candidate_idx >= self.swing_lb:
            if self._is_pivot_high(highs, pivot_candidate_idx, self.swing_lb):
                self.last_high = highs[pivot_candidate_idx]
                self.high_active = True
            if self._is_pivot_low(lows, pivot_candidate_idx, self.swing_lb):
                self.last_low = lows[pivot_candidate_idx]
                self.low_active = True

        # Step 2: Check for breakout on the last bar
        src_high = closes[last_idx] if self.use_close else highs[last_idx]
        src_low = closes[last_idx] if self.use_close else lows[last_idx]

        bullish_breakout = False
        bearish_breakout = False

        if self.high_active and not math.isnan(self.last_high):
            if src_high > self.last_high:
                bullish_breakout = True
                self.high_active = False

        if self.low_active and not math.isnan(self.last_low):
            if src_low < self.last_low:
                bearish_breakout = True
                self.low_active = False

        # CHoCH detection
        is_bullish_choch = bullish_breakout and self.last_break_dir == -1
        is_bearish_choch = bearish_breakout and self.last_break_dir == 1

        # Update break direction
        if bullish_breakout:
            self.last_break_dir = 1
        if bearish_breakout:
            self.last_break_dir = -1

        # Step 3: Generate signal
        bar_time_ts = int(bars[last_idx]["time"])

        if bullish_breakout and not math.isnan(self.last_high):
            return {
                "direction": 1,
                "signal_type": "CHoCH" if is_bullish_choch else "BOS",
                "pivot_level": self.last_high,
                "bar_time": datetime.fromtimestamp(bar_time_ts, tz=timezone.utc),
                "is_reversal": True,
            }

        if bearish_breakout and not math.isnan(self.last_low):
            return {
                "direction": -1,
                "signal_type": "CHoCH" if is_bearish_choch else "BOS",
                "pivot_level": self.last_low,
                "bar_time": datetime.fromtimestamp(bar_time_ts, tz=timezone.utc),
                "is_reversal": True,
            }

        return None

    # ── Main evaluate method ────────────────────────────────

    def evaluate(self, bars: list[dict], adr10: float = 0.0) -> Optional[MSSSignal]:
        """
        Evaluate bars and return an MSSSignal if a BOS/CHoCH breakout is detected.

        Args:
            bars: List of bar dicts with keys: time, open, high, low, close, volume.
                  Must have at least 2*swing_lb + 1 bars.
            adr10: 10-day Average Daily Range. If 0, TP/SL won't be calculated.

        Returns:
            MSSSignal if breakout detected on the last bar, None otherwise.
        """
        min_needed = self.swing_lb * 2 + 1
        if not bars or len(bars) < min_needed:
            return None

        if adr10 <= 0 or math.isnan(adr10):
            logger.warning("[MSS] %s: Invalid ADR10=%.5f", self.symbol, adr10)
            return None

        # Deduplicate: don't process the same bar twice
        current_bar_time = int(bars[-1]["time"])
        if self.last_processed_bar_time == current_bar_time:
            return None

        # First call: auto-warmup
        if not self._warmed_up:
            if len(bars) > min_needed + 1:
                self.warmup(bars[:-1])
            else:
                self.warmup(bars)
                return None

        # Incremental: process only the new bar
        raw_signal = self._process_new_bar(bars)
        self.last_processed_bar_time = current_bar_time

        if raw_signal is None:
            return None

        # Fill in ADR10-based TP/SL levels
        tp1_dist = adr10 * (self.tp1_pct / 100.0)
        tp2_dist = adr10 * (self.tp2_pct / 100.0)
        sl_dist = adr10 * (self.sl_pct / 100.0)

        pivot = raw_signal["pivot_level"]
        direction = raw_signal["direction"]

        if direction == 1:
            entry = pivot - self.pb_pct * sl_dist if self.use_pullback else pivot
            sl = entry - sl_dist
            tp1 = entry + tp1_dist
            tp2 = entry + tp2_dist
        else:
            entry = pivot + self.pb_pct * sl_dist if self.use_pullback else pivot
            sl = entry + sl_dist
            tp1 = entry - tp1_dist
            tp2 = entry - tp2_dist

        self.total_signals += 1
        if direction == 1:
            self.bullish_signals += 1
        else:
            self.bearish_signals += 1

        dir_str = "BULLISH" if direction == 1 else "BEARISH"
        sig_type = raw_signal["signal_type"]
        confidence = 0.7 if sig_type == "CHoCH" else 0.5

        logger.info(
            "[MSS] %s: %s %s | Pivot=%.5f Entry=%.5f SL=%.5f TP1=%.5f TP2=%.5f",
            self.symbol, dir_str, sig_type, pivot, entry, sl, tp1, tp2,
        )

        return MSSSignal(
            direction=direction,
            signal_type=sig_type,
            entry_price=entry,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            pivot_level=pivot,
            adr10=adr10,
            bar_time=raw_signal["bar_time"],
            is_reversal=raw_signal["is_reversal"],
            confidence=confidence,
            reason=f"{dir_str} {sig_type} at pivot {pivot:.5f}",
        )

    # ── Reversal check (read-only) ──────────────────────────

    def has_reversal_signal(self, bars: list[dict]) -> bool:
        """
        Check if the current (last) bar has ANY BOS/CHoCH breakout.
        Read-only — does NOT modify engine state.
        """
        min_needed = self.swing_lb * 2 + 1
        if not bars or len(bars) < min_needed:
            return False

        N = len(bars)
        last_idx = N - 1

        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]
        closes = [b["close"] for b in bars]

        # Use current state (read-only copies)
        last_high = self.last_high
        last_low = self.last_low
        high_active = self.high_active
        low_active = self.low_active

        # Check if a new pivot would be confirmed by this bar
        pivot_candidate_idx = last_idx - self.swing_lb
        if pivot_candidate_idx >= self.swing_lb:
            if self._is_pivot_high(highs, pivot_candidate_idx, self.swing_lb):
                last_high = highs[pivot_candidate_idx]
                high_active = True
            if self._is_pivot_low(lows, pivot_candidate_idx, self.swing_lb):
                last_low = lows[pivot_candidate_idx]
                low_active = True

        src_high = closes[last_idx] if self.use_close else highs[last_idx]
        src_low = closes[last_idx] if self.use_close else lows[last_idx]

        bullish = high_active and not math.isnan(last_high) and src_high > last_high
        bearish = low_active and not math.isnan(last_low) and src_low < last_low

        return bullish or bearish

    # ── State summary ───────────────────────────────────────

    def get_state_summary(self) -> dict:
        """Return current engine state for display."""
        dir_map = {1: "BULLISH", -1: "BEARISH", 0: "NONE"}
        return {
            "symbol": self.symbol,
            "last_high": self.last_high if not math.isnan(self.last_high) else None,
            "last_low": self.last_low if not math.isnan(self.last_low) else None,
            "high_active": self.high_active,
            "low_active": self.low_active,
            "last_break_dir": dir_map.get(self.last_break_dir, "NONE"),
            "total_signals": self.total_signals,
            "bullish_signals": self.bullish_signals,
            "bearish_signals": self.bearish_signals,
            "last_processed": (
                datetime.fromtimestamp(self.last_processed_bar_time, tz=timezone.utc).isoformat()
                if self.last_processed_bar_time else None
            ),
        }
