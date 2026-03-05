"""
Strategy 30: NAS100 Gap Fill + VWAP Confirmation
===================================================
Inspired by: Gap-fill mean-reversion trading on equity indices combined
with session VWAP confirmation.

Core idea: When the NAS100 opens with a gap (compared to the previous
session close), price tends to "fill" that gap during the session. We use
VWAP as a confirmation filter: enter when price crosses VWAP in the
gap-fill direction.

Logic:
  1. Detect gap at market open by comparing prior session close to current
     session open. Gap must be between min_gap_pct and max_gap_pct.
  2. Compute session VWAP (resets daily).
  3. Gap up  -> wait for price to cross BELOW VWAP -> SHORT toward gap fill.
     Gap down -> wait for price to cross ABOVE VWAP -> LONG toward gap fill.
  4. SL = ATR * atr_sl_mult beyond the gap extreme (open price).
  5. TP = previous session close (full gap fill level).
  6. Max 1 trade per gap event. Session hours: 13:00-17:00 UTC.

Markets : NAS100 / US100
Timeframe: H1
"""

DEFAULTS = {
    "min_gap_pct":        0.002,    # minimum gap size (0.2%)
    "max_gap_pct":        0.0075,   # maximum gap size (0.75%)
    "atr_period":         14,
    "atr_sl_mult":        1.5,
    "session_start_hour": 13,       # 13:00 UTC
    "session_end_hour":   17,       # 17:00 UTC
    "risk_per_trade":     0.01,
}


SETTINGS = [
    {"key": "min_gap_pct",        "label": "Min Gap %",                "type": "float", "default": 0.002,  "min": 0.0005, "max": 0.01,  "step": 0.0005, "group": "Entry Rules",     "description": "Minimum gap size as a fraction of previous close to qualify as tradeable"},
    {"key": "max_gap_pct",        "label": "Max Gap %",                "type": "float", "default": 0.0075, "min": 0.001,  "max": 0.05,  "step": 0.001,  "group": "Entry Rules",     "description": "Maximum gap size as a fraction of previous close; larger gaps are skipped"},
    {"key": "atr_period",         "label": "ATR Period",               "type": "int",   "default": 14,     "min": 5,      "max": 50,    "step": 1,      "group": "Indicator Settings", "description": "Lookback period for Average True Range calculation"},
    {"key": "atr_sl_mult",        "label": "ATR SL Multiplier",        "type": "float", "default": 1.5,    "min": 0.5,    "max": 5.0,   "step": 0.1,    "group": "Risk Management", "description": "Stop-loss distance as a multiple of ATR beyond the gap extreme"},
    {"key": "session_start_hour", "label": "Session Start (UTC)",      "type": "int",   "default": 13,     "min": 0,      "max": 23,    "step": 1,      "group": "Session",         "description": "Hour (UTC) when the trading window opens for gap-fill entries"},
    {"key": "session_end_hour",   "label": "Session End (UTC)",        "type": "int",   "default": 17,     "min": 1,      "max": 23,    "step": 1,      "group": "Session",         "description": "Hour (UTC) when the session ends and all open trades are closed"},
    {"key": "risk_per_trade",     "label": "Risk Per Trade",           "type": "float", "default": 0.01,   "min": 0.001,  "max": 0.05,  "step": 0.001,  "group": "Risk Management", "description": "Fraction of account equity risked per trade (0.01 = 1%)"},
]


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
            dt = datetime.datetime.utcfromtimestamp(t)
            return dt.hour
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


def _vwap(bars):
    """Session VWAP that resets daily. Returns list of VWAP values."""
    n = len(bars)
    out = [0.0] * n
    cum_pv = 0.0
    cum_vol = 0.0
    last_day = -1
    for i in range(n):
        b = bars[i]
        t = b.get("time", 0)
        if isinstance(t, (int, float)):
            import datetime
            try:
                day = datetime.datetime.utcfromtimestamp(t).date()
            except (ValueError, OSError):
                day = i // 300
        elif isinstance(t, str):
            day = t[:10]
        else:
            day = i // 300

        if day != last_day:
            cum_pv = 0.0
            cum_vol = 0.0
            last_day = day

        typical = (b["high"] + b["low"] + b["close"]) / 3
        vol = b.get("volume", 1)
        cum_pv += typical * vol
        cum_vol += vol
        out[i] = cum_pv / cum_vol if cum_vol > 0 else typical
    return out


def _sma(values, period):
    """Simple moving average over a list of floats."""
    n = len(values)
    out = [0.0] * n
    if period > n:
        return out
    running = sum(values[:period])
    out[period - 1] = running / period
    for i in range(period, n):
        running += values[i] - values[i - period]
        out[i] = running / period
    return out


class NAS100GapFillVWAP:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.atr_vals = _atr(bars, self.s["atr_period"])
        self.vwap_vals = _vwap(bars)

        # Gap tracking state
        self.current_day = ""
        self.prev_session_close = 0.0
        self.session_open = 0.0
        self.gap_direction = ""       # "up" or "down" or ""
        self.gap_traded = False       # only 1 trade per gap
        self.session_active = False
        self.prev_day_had_close = False

    def _detect_gap(self, bar):
        """Check if bar represents a valid gap from previous session close."""
        s = self.s
        if self.prev_session_close <= 0:
            return ""

        gap = (bar["open"] - self.prev_session_close) / self.prev_session_close
        abs_gap = abs(gap)

        if abs_gap < s["min_gap_pct"] or abs_gap > s["max_gap_pct"]:
            return ""

        return "up" if gap > 0 else "down"

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

        # New day detected
        if day != self.current_day and day != "":
            # Store previous session close before resetting
            if self.current_day != "":
                self.prev_session_close = self.bars[i - 1]["close"]
                self.prev_day_had_close = True

            self.current_day = day
            self.gap_direction = ""
            self.gap_traded = False
            self.session_active = False

            # Detect gap on first bar of the new day
            if self.prev_day_had_close:
                self.gap_direction = self._detect_gap(bar)
                self.session_open = bar["open"]

        # Outside session window — close all trades
        if hour < s["session_start_hour"] or hour >= s["session_end_hour"]:
            for t in list(open_trades):
                close_trade(t, i, close, "session_end")
            self.session_active = False
            return

        self.session_active = True

        # No gap detected today or already traded this gap
        if self.gap_direction == "" or self.gap_traded:
            return

        if atr_val <= 0:
            return

        # Already in a trade
        if len(open_trades) > 0:
            return

        vwap_now = self.vwap_vals[i]
        vwap_prev = self.vwap_vals[i - 1] if i > 0 else vwap_now
        prev_close = self.bars[i - 1]["close"]

        # Gap UP -> price filling down -> enter SHORT when close crosses below VWAP
        if self.gap_direction == "up":
            if prev_close >= vwap_prev and close < vwap_now:
                sl = self.session_open + atr_val * s["atr_sl_mult"]
                tp = self.prev_session_close  # full gap fill
                open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
                self.gap_traded = True

        # Gap DOWN -> price filling up -> enter LONG when close crosses above VWAP
        elif self.gap_direction == "down":
            if prev_close <= vwap_prev and close > vwap_now:
                sl = self.session_open - atr_val * s["atr_sl_mult"]
                tp = self.prev_session_close  # full gap fill
                open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
                self.gap_traded = True
