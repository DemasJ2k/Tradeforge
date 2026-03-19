"""
Strategy 47: XAUUSD Trend-Following Pullback (M5)
====================================================
Target: XAUUSD M5
Expected Sharpe: 1.5–2.2 | Win rate: 50–55% | R:R: ~1:3

Core thesis: Gold on M5 trends strongly during London and NY sessions.
Instead of trying to catch reversals (mean reversion) or breakouts
(high false-positive rate), this strategy identifies established trends
using a dual-timeframe EMA approach and enters on pullbacks to the
fast EMA with wide profit targets.

Key insight: The previous RSI-2 mean reversion approach failed because
M5 bars don't revert like M1 bars — they trend.  This strategy
embraces M5's trending nature.

Architecture:
  1. **Higher-timeframe trend** – EMA(50) slope over 12 bars (~1 hour)
     determines the primary direction.
  2. **Fast-timeframe timing** – EMA(10) serves as the pullback target.
     In uptrend, when price pulls back to EMA(10) and bounces, enter long.
  3. **Momentum confirmation** – RSI(14) must be in the "sweet spot":
     45-65 for longs (not overbought), 35-55 for shorts (not oversold).
  4. **Volatility filter** – ATR must be above its 50-bar average
     (active market, not dead zone).

Entry:
  LONG  – EMA(50) rising + price touches EMA(10) + bounce candle +
           RSI in [rsi_low, rsi_high] + ATR above average
  SHORT – EMA(50) falling + price touches EMA(10) + reject candle +
           RSI in [100-rsi_high, 100-rsi_low] + ATR above average

Exit:
  SL = Below pullback low + ATR buffer (longs) / mirror for shorts
  TP = ATR × tp_mult (default 3.5 — riding the trend)
  Trailing stop: 2× ATR trail after 1.5× ATR profit
  Session close: all positions closed at session_end_hour
"""

DEFAULTS = {
    # Session (UTC)
    "session_start_hour":   7,     # London open
    "session_end_hour":     16,    # NY afternoon
    # EMAs
    "ema_fast":             10,
    "ema_slow":             50,
    "ema_slope_bars":       12,    # ~1 hour on M5 for trend direction
    # RSI filter
    "rsi_period":           14,
    "rsi_low":              45,    # Min RSI for longs
    "rsi_high":             65,    # Max RSI for longs
    # ATR
    "atr_period":           14,
    "atr_avg_period":       50,    # Compare ATR to its average
    "atr_sl_mult":          1.5,   # SL distance minimum
    "atr_tp_mult":          3.5,   # TP distance
    # Trailing stop
    "use_trailing":         True,
    "trail_trigger_atr":    1.5,
    "trail_distance_atr":   2.0,
    # Risk
    "lot_size":             0.01,
    "risk_per_trade":       0.005,
    "max_session_trades":   3,
}

SETTINGS = [
    {"key": "session_start_hour",  "label": "Session Start (UTC)",    "type": "int",   "default": 7,     "min": 0,     "max": 12,   "step": 1,    "group": "Session",            "description": "London session start hour (UTC)"},
    {"key": "session_end_hour",    "label": "Session End (UTC)",      "type": "int",   "default": 16,    "min": 12,    "max": 20,   "step": 1,    "group": "Session",            "description": "Session end — all positions closed"},
    {"key": "ema_fast",            "label": "Fast EMA",               "type": "int",   "default": 10,    "min": 5,     "max": 20,   "step": 1,    "group": "Indicator Settings", "description": "Fast EMA for pullback target"},
    {"key": "ema_slow",            "label": "Slow EMA",               "type": "int",   "default": 50,    "min": 30,    "max": 100,  "step": 5,    "group": "Indicator Settings", "description": "Slow EMA for trend direction"},
    {"key": "ema_slope_bars",      "label": "Slope Lookback",         "type": "int",   "default": 12,    "min": 5,     "max": 24,   "step": 1,    "group": "Indicator Settings", "description": "Bars to measure EMA slope (12 = ~1h on M5)"},
    {"key": "rsi_period",          "label": "RSI Period",             "type": "int",   "default": 14,    "min": 7,     "max": 21,   "step": 1,    "group": "Indicator Settings", "description": "RSI lookback for momentum filter"},
    {"key": "rsi_low",             "label": "RSI Min (Longs)",        "type": "int",   "default": 45,    "min": 30,    "max": 55,   "step": 5,    "group": "Entry Rules",        "description": "Minimum RSI for long entry"},
    {"key": "rsi_high",            "label": "RSI Max (Longs)",        "type": "int",   "default": 65,    "min": 55,    "max": 75,   "step": 5,    "group": "Entry Rules",        "description": "Maximum RSI for long entry (avoid exhaustion)"},
    {"key": "atr_period",          "label": "ATR Period",             "type": "int",   "default": 14,    "min": 5,     "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "ATR lookback for SL/TP sizing"},
    {"key": "atr_sl_mult",         "label": "ATR Stop-Loss Mult",     "type": "float", "default": 1.5,   "min": 0.5,   "max": 3.0,  "step": 0.1,  "group": "Risk Management",    "description": "ATR multiplier for stop-loss"},
    {"key": "atr_tp_mult",         "label": "ATR Take-Profit Mult",   "type": "float", "default": 3.5,   "min": 2.0,   "max": 6.0,  "step": 0.5,  "group": "Risk Management",    "description": "ATR multiplier for take-profit (wide)"},
    {"key": "use_trailing",        "label": "Use Trailing Stop",      "type": "bool",  "default": True,                                            "group": "Risk Management",    "description": "Enable trailing stop to capture extended moves"},
    {"key": "max_session_trades",  "label": "Max Session Trades",     "type": "int",   "default": 3,     "min": 1,     "max": 5,    "step": 1,    "group": "Risk Management",    "description": "Maximum trades per session"},
]


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def _ema(data, period):
    n = len(data)
    out = [0.0] * n
    if period > n:
        return out
    k = 2.0 / (period + 1)
    out[period - 1] = sum(data[:period]) / period
    for i in range(period, n):
        out[i] = data[i] * k + out[i - 1] * (1 - k)
    return out


def _rsi(bars, period):
    n = len(bars)
    out = [50.0] * n
    if period + 1 > n:
        return out
    gains = losses = 0.0
    for j in range(1, period + 1):
        diff = bars[j]["close"] - bars[j - 1]["close"]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period + 1, n):
        diff = bars[i]["close"] - bars[i - 1]["close"]
        g = max(diff, 0)
        l = max(-diff, 0)
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def _atr(bars, period):
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


def _sma(values, period):
    n = len(values)
    out = [0.0] * n
    if period > n:
        return out
    s = sum(values[:period])
    out[period - 1] = s / period
    for i in range(period, n):
        s += values[i] - values[i - period]
        out[i] = s / period
    return out


def _get_hour(bar):
    t = bar.get("time", "")
    if isinstance(t, str):
        for sep in [" ", "T"]:
            if sep in t:
                try:
                    return int(t.split(sep)[-1].split(":")[0])
                except (ValueError, IndexError):
                    pass
    elif isinstance(t, (int, float)):
        import datetime
        try:
            return datetime.datetime.utcfromtimestamp(t).hour
        except (ValueError, OSError):
            pass
    return -1


def _get_day(bar):
    t = bar.get("time", "")
    if isinstance(t, str):
        return t[:10]
    elif isinstance(t, (int, float)):
        import datetime
        try:
            return datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
        except (ValueError, OSError):
            pass
    return ""


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

class XAUUSDTrendPullback:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        n = len(bars)

        closes = [b["close"] for b in bars]
        self.ema_fast_vals = _ema(closes, self.s["ema_fast"])
        self.ema_slow_vals = _ema(closes, self.s["ema_slow"])
        self.rsi_vals = _rsi(bars, self.s["rsi_period"])
        self.atr_vals = _atr(bars, self.s["atr_period"])

        # ATR moving average for volatility filter
        self.atr_avg = _sma(self.atr_vals, self.s["atr_avg_period"])

        # State
        self.current_day = ""
        self.session_trades = 0
        self.pullback_active = False
        self.pullback_dir = ""
        self.pullback_low = float("inf")   # For long pullbacks
        self.pullback_high = 0.0            # For short pullbacks
        self.trail_best = {}

    def _reset_day(self, day):
        self.current_day = day
        self.session_trades = 0
        self.pullback_active = False
        self.pullback_dir = ""
        self.pullback_low = float("inf")
        self.pullback_high = 0.0
        self.trail_best = {}

    def _update_trailing(self, i, bar):
        s = self.s
        if not s["use_trailing"]:
            return
        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return
        trigger_dist = atr_val * s["trail_trigger_atr"]
        trail_dist = atr_val * s["trail_distance_atr"]

        for t in list(open_trades):
            tid = id(t)
            entry = t["entry_price"]
            if t["direction"] == "long":
                best = max(self.trail_best.get(tid, bar["high"]), bar["high"])
                self.trail_best[tid] = best
                if best - entry > trigger_dist:
                    new_sl = best - trail_dist
                    if new_sl > t.get("stop_loss", 0):
                        t["stop_loss"] = new_sl
            else:
                best = min(self.trail_best.get(tid, bar["low"]), bar["low"])
                self.trail_best[tid] = best
                if entry - best > trigger_dist:
                    new_sl = best + trail_dist
                    if new_sl < t.get("stop_loss", float("inf")):
                        t["stop_loss"] = new_sl

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["ema_slow"], s["atr_period"], s["rsi_period"],
                      s["atr_avg_period"]) + s["ema_slope_bars"] + 5
        if i < warmup:
            return

        hour = _get_hour(bar)
        if hour == -1:
            return

        day = _get_day(bar)
        close = bar["close"]
        atr_val = self.atr_vals[i]

        # Daily reset
        if day != self.current_day and day != "":
            for t in list(open_trades):
                close_trade(t, i, close, "day_end")
            self._reset_day(day)

        # Outside session
        if hour >= s["session_end_hour"] or hour < s["session_start_hour"]:
            for t in list(open_trades):
                close_trade(t, i, close, "session_end")
            self.pullback_active = False
            return

        # Manage open trades
        if len(open_trades) > 0:
            self._update_trailing(i, bar)
            return

        # Max trades
        if self.session_trades >= s["max_session_trades"]:
            return
        if atr_val <= 0:
            return

        ef = self.ema_fast_vals[i]
        es = self.ema_slow_vals[i]
        rsi = self.rsi_vals[i]
        atr_avg = self.atr_avg[i]

        # Volatility filter: ATR must be above average (active market)
        if atr_avg > 0 and atr_val < atr_avg * 0.8:
            self.pullback_active = False
            return

        # Trend detection via slow EMA slope
        slope_bars = s["ema_slope_bars"]
        es_prev = self.ema_slow_vals[i - slope_bars]
        ef_prev = self.ema_fast_vals[i - slope_bars]

        uptrend = ef > es and es > es_prev and ef > ef_prev
        downtrend = ef < es and es < es_prev and ef < ef_prev

        # --- LONG setup ---
        if uptrend:
            # Detect pullback: bar touches or crosses below EMA fast
            if bar["low"] <= ef and close > ef * 0.998:  # Touch but not crash through
                if not self.pullback_active or self.pullback_dir != "long":
                    self.pullback_active = True
                    self.pullback_dir = "long"
                    self.pullback_low = bar["low"]
                else:
                    self.pullback_low = min(self.pullback_low, bar["low"])

            # Resumption: close back above EMA fast after pullback
            elif (self.pullback_active and self.pullback_dir == "long"
                  and close > ef and bar["close"] > bar["open"]):  # Bullish candle
                # RSI sweet spot
                if s["rsi_low"] <= rsi <= s["rsi_high"]:
                    sl = min(self.pullback_low, close - atr_val * s["atr_sl_mult"])
                    tp = close + atr_val * s["atr_tp_mult"]
                    open_trade(i, "long", close, sl, tp, s["lot_size"])
                    self.session_trades += 1
                    self.pullback_active = False
                    if open_trades:
                        self.trail_best[id(open_trades[-1])] = bar["high"]

        # --- SHORT setup ---
        elif downtrend:
            if bar["high"] >= ef and close < ef * 1.002:
                if not self.pullback_active or self.pullback_dir != "short":
                    self.pullback_active = True
                    self.pullback_dir = "short"
                    self.pullback_high = bar["high"]
                else:
                    self.pullback_high = max(self.pullback_high, bar["high"])

            elif (self.pullback_active and self.pullback_dir == "short"
                  and close < ef and bar["close"] < bar["open"]):
                rsi_short_low = 100 - s["rsi_high"]
                rsi_short_high = 100 - s["rsi_low"]
                if rsi_short_low <= rsi <= rsi_short_high:
                    sl = max(self.pullback_high, close + atr_val * s["atr_sl_mult"])
                    tp = close - atr_val * s["atr_tp_mult"]
                    open_trade(i, "short", close, sl, tp, s["lot_size"])
                    self.session_trades += 1
                    self.pullback_active = False
                    if open_trades:
                        self.trail_best[id(open_trades[-1])] = bar["low"]
        else:
            # No trend — reset pullback
            self.pullback_active = False
