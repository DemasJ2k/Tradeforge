"""
Strategy 26: Market Structure Signals (BOS / CHoCH)
=====================================================
Converted from: PineScript "Market Structure Signals" by ProjectSyndicate.

Core idea: Detect pivot highs/lows using lookback window, then trade
Break of Structure (BOS) and Change of Character (CHoCH) breakouts.
  Long : Close breaks above last swing high (bullish BOS/CHoCH)
  Short: Close breaks below last swing low (bearish BOS/CHoCH)

TP/SL based on ADR (Average Daily Range) percentages, approximated
via ATR on the bar timeframe.

CHoCH (Change of Character) signals are higher probability because
they indicate a reversal in market structure direction.

Markets : Universal
Timeframe: 15m / 1H / 4H
"""

DEFAULTS = {
    "swing_length":     22,     # Optimized — balance between signal quality and frequency
    "bos_confirm":      "close",  # "close" or "wick" for breakout confirmation
    "choch_only":       False,  # If True, only trade CHoCH (reversal) signals
    "atr_period":       14,     # Standard ATR period
    "atr_sl_mult":      3.0,    # SL = 3x ATR — wide enough to avoid noise stops
    "atr_tp_mult":      5.0,    # TP = 5x ATR — let breakout trends run (1.67:1 R:R)
    "ema_period":       50,     # Trend filter (disabled by default)
    "use_ema_filter":   False,  # Disabled — reduces opportunities without improving PF
    "cooldown_bars":    3,      # Min bars between trades
    "risk_per_trade":   0.01,
}


def _atr(bars, period):
    """Average True Range."""
    n = len(bars)
    trs = [0.0] * n
    for i in range(1, n):
        trs[i] = max(bars[i]["high"] - bars[i]["low"],
                      abs(bars[i]["high"] - bars[i - 1]["close"]),
                      abs(bars[i]["low"] - bars[i - 1]["close"]))
    out = [0.0] * n
    if period + 1 > n:
        return out
    out[period] = sum(trs[1:period + 1]) / period
    for i in range(period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + trs[i]) / period
    return out


def _ema(values, period):
    """Exponential Moving Average."""
    n = len(values)
    out = [0.0] * n
    if period > n:
        return out
    out[period - 1] = sum(values[:period]) / period
    k = 2.0 / (period + 1)
    for i in range(period, n):
        out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out


def _find_pivots(bars, length):
    """
    Find pivot highs and pivot lows.
    A pivot high at bar i requires high[i] to be the highest
    among bars[i-length .. i+length].
    Returns (pivot_highs, pivot_lows) — dicts mapping bar_index to price.
    """
    n = len(bars)
    pivot_highs = {}
    pivot_lows = {}

    for i in range(length, n - length):
        # Check pivot high
        is_ph = True
        h = bars[i]["high"]
        for j in range(i - length, i + length + 1):
            if j == i:
                continue
            if bars[j]["high"] > h:
                is_ph = False
                break
        if is_ph:
            pivot_highs[i] = h

        # Check pivot low
        is_pl = True
        lo = bars[i]["low"]
        for j in range(i - length, i + length + 1):
            if j == i:
                continue
            if bars[j]["low"] < lo:
                is_pl = False
                break
        if is_pl:
            pivot_lows[i] = lo

    return pivot_highs, pivot_lows


class MarketStructureSignals:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        n = len(bars)
        length = self.s["swing_length"]

        # Pre-compute ATR
        self.atr_vals = _atr(bars, self.s["atr_period"])

        # Pre-compute EMA for trend filter
        closes = [b["close"] for b in bars]
        self.ema_vals = _ema(closes, self.s["ema_period"])

        # Pre-compute all pivots
        pivot_highs, pivot_lows = _find_pivots(bars, length)

        # Build arrays tracking the "last known" swing high/low at each bar
        # A pivot at bar i is only confirmed at bar i + length (need right side)
        self.last_swing_high = [0.0] * n
        self.last_swing_high_bar = [0] * n
        self.last_swing_low = [0.0] * n
        self.last_swing_low_bar = [0] * n
        self.high_active = [False] * n
        self.low_active = [False] * n

        cur_sh = 0.0
        cur_sh_bar = 0
        cur_sl_val = 0.0
        cur_sl_bar = 0
        sh_active = False
        sl_active = False

        for i in range(n):
            # A pivot at bar (i - length) is confirmed at bar i
            confirm_bar = i - length
            if confirm_bar in pivot_highs:
                cur_sh = pivot_highs[confirm_bar]
                cur_sh_bar = confirm_bar
                sh_active = True

            if confirm_bar in pivot_lows:
                cur_sl_val = pivot_lows[confirm_bar]
                cur_sl_bar = confirm_bar
                sl_active = True

            self.last_swing_high[i] = cur_sh
            self.last_swing_high_bar[i] = cur_sh_bar
            self.last_swing_low[i] = cur_sl_val
            self.last_swing_low_bar[i] = cur_sl_bar
            self.high_active[i] = sh_active
            self.low_active[i] = sl_active

        # Pre-compute breakout events
        # Track: which bars have bullish/bearish breakouts, and whether CHoCH
        self.bullish_breakout = [False] * n
        self.bearish_breakout = [False] * n
        self.is_choch_bull = [False] * n
        self.is_choch_bear = [False] * n

        last_break_dir = 0  # 1 = bullish, -1 = bearish
        h_active_state = False
        l_active_state = False
        tracked_sh = 0.0
        tracked_sl = 0.0

        for i in range(1, n):
            confirm_bar = i - length
            if confirm_bar in pivot_highs:
                tracked_sh = pivot_highs[confirm_bar]
                h_active_state = True

            if confirm_bar in pivot_lows:
                tracked_sl = pivot_lows[confirm_bar]
                l_active_state = True

            # Breakout source
            use_close = self.s["bos_confirm"] == "close"
            break_src_high = bars[i]["close"] if use_close else bars[i]["high"]
            break_src_low = bars[i]["close"] if use_close else bars[i]["low"]

            if h_active_state and tracked_sh > 0 and break_src_high > tracked_sh:
                self.bullish_breakout[i] = True
                h_active_state = False
                if last_break_dir == -1:
                    self.is_choch_bull[i] = True
                last_break_dir = 1

            if l_active_state and tracked_sl > 0 and break_src_low < tracked_sl:
                self.bearish_breakout[i] = True
                l_active_state = False
                if last_break_dir == 1:
                    self.is_choch_bear[i] = True
                last_break_dir = -1

        self.last_trade_bar = -999

    def on_bar(self, i, bar):
        s = self.s
        warmup = s["swing_length"] * 2 + max(s["atr_period"], s["ema_period"]) + 5
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        # Let SL/TP handle exits — no early exit
        if len(open_trades) > 0:
            return

        # Cooldown
        if i - self.last_trade_bar < s["cooldown_bars"]:
            return

        close = bar["close"]
        ema_val = self.ema_vals[i]

        is_bull = self.bullish_breakout[i]
        is_bear = self.bearish_breakout[i]
        is_choch_b = self.is_choch_bull[i]
        is_choch_s = self.is_choch_bear[i]

        # If choch_only mode, skip plain BOS signals
        if s["choch_only"]:
            if is_bull and not is_choch_b:
                is_bull = False
            if is_bear and not is_choch_s:
                is_bear = False

        # EMA trend filter
        if s["use_ema_filter"] and ema_val > 0:
            if is_bull and close < ema_val:
                is_bull = False  # Don't go long below EMA
            if is_bear and close > ema_val:
                is_bear = False  # Don't go short above EMA

        # Bullish BOS / CHoCH → Long
        if is_bull:
            entry = close
            sl = entry - atr_val * s["atr_sl_mult"]
            tp = entry + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", entry, sl, tp, s["risk_per_trade"])
            self.last_trade_bar = i

        # Bearish BOS / CHoCH → Short
        elif is_bear:
            entry = close
            sl = entry + atr_val * s["atr_sl_mult"]
            tp = entry - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", entry, sl, tp, s["risk_per_trade"])
            self.last_trade_bar = i
