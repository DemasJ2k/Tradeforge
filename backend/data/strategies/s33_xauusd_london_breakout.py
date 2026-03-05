"""
Strategy 33: XAUUSD London Breakout (Gold-Optimized)
=====================================================
Inspired by: Classic London session breakout, tuned for XAUUSD.

Core idea: Gold forms a well-defined range during the Asian session
(00:00–07:00 UTC). The London open (07:00 UTC) frequently breaks this
range with high momentum as institutional players enter. This variant
uses the Asian range MIDPOINT as the stop-loss (tighter than the
opposite-side approach in the generic s25 version), a take-profit
scaled to the Asian range size, and a trailing stop based on ATR.

Logic:
  1. Track Asian session high/low from asia_start_hour to asia_end_hour.
  2. At London open, validate range size against ATR bounds.
  3. Breakout = close beyond range boundary + buffer.
  4. SL at the range midpoint (not the opposite boundary).
  5. TP at tp_mult x Asian range from entry.
  6. Trailing stop: once in profit by 0.5x ATR, trail at 1x ATR.
  7. Close all trades at london_end_hour; max max_daily_trades per day.

Markets : XAUUSD
Timeframe: M5
"""

DEFAULTS = {
    "asia_start_hour":     0,
    "asia_end_hour":       7,
    "london_start_hour":   7,
    "london_end_hour":     12,
    "breakout_buffer_pct": 0.0005,
    "tp_mult":             1.0,
    "atr_period":          14,
    "min_range_atr":       0.3,
    "max_range_atr":       2.0,
    "risk_per_trade":      0.01,
    "max_daily_trades":    2,
}


SETTINGS = [
    {"key": "asia_start_hour",     "label": "Asia Start (UTC)",       "type": "int",   "default": 0,      "min": 0,    "max": 23,   "step": 1,     "group": "Session",         "description": "Hour (UTC) when Asian range tracking begins"},
    {"key": "asia_end_hour",       "label": "Asia End (UTC)",         "type": "int",   "default": 7,      "min": 1,    "max": 23,   "step": 1,     "group": "Session",         "description": "Hour (UTC) when Asian range tracking ends and London prep begins"},
    {"key": "london_start_hour",   "label": "London Start (UTC)",     "type": "int",   "default": 7,      "min": 0,    "max": 23,   "step": 1,     "group": "Session",         "description": "Hour (UTC) when London trading session begins"},
    {"key": "london_end_hour",     "label": "London End (UTC)",       "type": "int",   "default": 12,     "min": 1,    "max": 23,   "step": 1,     "group": "Session",         "description": "Hour (UTC) when London session ends and all trades are closed"},
    {"key": "breakout_buffer_pct", "label": "Breakout Buffer %",      "type": "float", "default": 0.0005, "min": 0.0,  "max": 0.01, "step": 0.0001,"group": "Entry Rules",     "description": "Percentage buffer beyond Asian range required for valid breakout"},
    {"key": "tp_mult",             "label": "TP Range Multiplier",    "type": "float", "default": 1.0,    "min": 0.3,  "max": 5.0,  "step": 0.1,   "group": "Exit Rules",      "description": "Take-profit as a multiple of the Asian range size"},
    {"key": "atr_period",          "label": "ATR Period",             "type": "int",   "default": 14,     "min": 5,    "max": 50,   "step": 1,     "group": "Indicator Settings", "description": "Lookback period for Average True Range calculation"},
    {"key": "min_range_atr",       "label": "Min Range (ATR mult)",   "type": "float", "default": 0.3,    "min": 0.1,  "max": 2.0,  "step": 0.1,   "group": "Filters",         "description": "Minimum Asian range size as a multiple of ATR"},
    {"key": "max_range_atr",       "label": "Max Range (ATR mult)",   "type": "float", "default": 2.0,    "min": 0.5,  "max": 10.0, "step": 0.1,   "group": "Filters",         "description": "Maximum Asian range size as a multiple of ATR"},
    {"key": "risk_per_trade",      "label": "Risk Per Trade",         "type": "float", "default": 0.01,   "min": 0.001,"max": 0.05, "step": 0.001, "group": "Risk Management", "description": "Fraction of account equity risked per trade (0.01 = 1%)"},
    {"key": "max_daily_trades",    "label": "Max Daily Trades",       "type": "int",   "default": 2,      "min": 1,    "max": 5,    "step": 1,     "group": "Risk Management", "description": "Maximum breakout trades allowed per London session"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _get_hour(bar):
    """Extract hour from bar time string. Handles various formats."""
    t = bar.get("time", "")
    if isinstance(t, str):
        for sep in [" ", "T"]:
            if sep in t:
                time_part = t.split(sep)[-1]
                try:
                    return int(time_part.split(":")[0])
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
    """Extract date string from bar time for daily grouping."""
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

class XAUUSDLondonBreakout:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.atr_vals = _atr(bars, self.s["atr_period"])

        # Asian range state
        self.asia_high = 0.0
        self.asia_low = float("inf")
        self.asia_range_ready = False

        # Daily tracking
        self.current_day = ""
        self.daily_trades = 0

        # Trailing stop tracking  {trade_id: best_price}
        self.trail_best = {}

    # ------------------------------------------------------------------
    def _reset_day(self, day):
        self.asia_high = 0.0
        self.asia_low = float("inf")
        self.asia_range_ready = False
        self.current_day = day
        self.daily_trades = 0
        self.trail_best = {}

    # ------------------------------------------------------------------
    def _update_trailing(self, i, bar):
        """Move stop-loss toward price when trade is in profit."""
        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return
        for t in list(open_trades):
            tid = id(t)
            entry = t["entry_price"]
            direction = t["direction"]

            if direction == "long":
                best = self.trail_best.get(tid, bar["high"])
                best = max(best, bar["high"])
                self.trail_best[tid] = best
                # Only trail once price has moved 0.5 ATR in our favor
                if best - entry > 0.5 * atr_val:
                    new_sl = best - atr_val
                    if new_sl > t["stop_loss"]:
                        t["stop_loss"] = new_sl
            else:
                best = self.trail_best.get(tid, bar["low"])
                best = min(best, bar["low"])
                self.trail_best[tid] = best
                if entry - best > 0.5 * atr_val:
                    new_sl = best + atr_val
                    if new_sl < t["stop_loss"]:
                        t["stop_loss"] = new_sl

    # ------------------------------------------------------------------
    def on_bar(self, i, bar):
        s = self.s
        if i < s["atr_period"] + 2:
            return

        hour = _get_hour(bar)
        if hour == -1:
            return

        day = _get_day(bar)
        close = bar["close"]
        atr_val = self.atr_vals[i]

        # New day — reset Asian range
        if day != self.current_day and day != "":
            self._reset_day(day)

        # --- Asian session: accumulate range ---
        if s["asia_start_hour"] <= hour < s["asia_end_hour"]:
            if self.asia_high == 0.0 and self.asia_low == float("inf"):
                self.asia_high = bar["high"]
                self.asia_low = bar["low"]
            else:
                self.asia_high = max(self.asia_high, bar["high"])
                self.asia_low = min(self.asia_low, bar["low"])
            return

        # Mark Asian range as ready once we leave the Asian window
        if not self.asia_range_ready and self.asia_high > 0 and self.asia_low < float("inf"):
            self.asia_range_ready = True

        # --- Outside London session: close all trades ---
        if hour < s["london_start_hour"] or hour >= s["london_end_hour"]:
            for t in list(open_trades):
                close_trade(t, i, close, "session_end")
            return

        # --- Inside London session ---
        # Update trailing stops for open trades
        if len(open_trades) > 0:
            self._update_trailing(i, bar)
            return

        # Validate we have a usable Asian range
        if not self.asia_range_ready:
            return
        if atr_val <= 0:
            return

        asia_range = self.asia_high - self.asia_low
        if asia_range <= 0:
            return

        # Range size filter
        if asia_range < atr_val * s["min_range_atr"]:
            return
        if asia_range > atr_val * s["max_range_atr"]:
            return

        # Max daily trades
        if self.daily_trades >= s["max_daily_trades"]:
            return

        buffer = asia_range * s["breakout_buffer_pct"]
        range_mid = (self.asia_high + self.asia_low) / 2.0

        # --- Long breakout ---
        if close > self.asia_high + buffer:
            sl = range_mid                            # midpoint SL
            tp = close + asia_range * s["tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
            self.daily_trades += 1

        # --- Short breakout ---
        elif close < self.asia_low - buffer:
            sl = range_mid                            # midpoint SL
            tp = close - asia_range * s["tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
            self.daily_trades += 1
