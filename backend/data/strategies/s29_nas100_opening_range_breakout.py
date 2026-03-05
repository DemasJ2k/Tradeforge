"""
Strategy 29: NAS100 Opening Range Breakout
============================================
Inspired by: Classic US equities ORB adapted for NAS100/US100 futures.

Core idea: The first 15 minutes (3x M5 bars) after the US cash open
(09:30 ET = 13:30 UTC) define the Opening Range (OR). A breakout beyond
the OR high/low with volume confirmation triggers a trade in the breakout
direction. Trades are managed with range-based stops and a configurable
take-profit multiple of the OR size.

Logic:
  1. Build the Opening Range from the first `range_bars` M5 bars after
     the session start hour.
  2. After OR is established, wait for close above OR high + buffer (long)
     or close below OR low - buffer (short).
  3. Volume must exceed vol_mult * 20-bar SMA of volume.
  4. SL at opposite OR boundary, TP at tp_mult * OR range from entry.
  5. Close all trades at session end; max max_daily_trades per day.

Markets : NAS100 / US100
Timeframe: M5
"""

DEFAULTS = {
    "range_bars":          3,       # bars that define the opening range
    "breakout_buffer_pct": 0.001,   # 0.1% buffer beyond OR boundary
    "vol_mult":            1.2,     # volume must exceed this * avg volume
    "tp_mult":             1.5,     # TP = tp_mult * OR range
    "atr_period":          14,
    "session_start_hour":  13,      # 13:00 UTC = 09:00 ET (pre-market) / 09:30 ET approx
    "session_end_hour":    20,      # 20:00 UTC = 16:00 ET
    "risk_per_trade":      0.01,
    "max_daily_trades":    3,
}


SETTINGS = [
    {"key": "range_bars",          "label": "Opening Range Bars",       "type": "int",   "default": 3,     "min": 1,    "max": 12,   "step": 1,     "group": "Entry Rules",     "description": "Number of M5 bars after session start that define the Opening Range"},
    {"key": "breakout_buffer_pct", "label": "Breakout Buffer %",        "type": "float", "default": 0.001, "min": 0.0,  "max": 0.01, "step": 0.001, "group": "Entry Rules",     "description": "Percentage buffer beyond the OR boundary required for a valid breakout"},
    {"key": "vol_mult",            "label": "Volume Multiplier",        "type": "float", "default": 1.2,   "min": 0.5,  "max": 3.0,  "step": 0.1,   "group": "Filters",         "description": "Bar volume must exceed this multiple of the 20-bar average volume"},
    {"key": "tp_mult",             "label": "TP Range Multiplier",      "type": "float", "default": 1.5,   "min": 0.5,  "max": 5.0,  "step": 0.1,   "group": "Exit Rules",      "description": "Take-profit distance as a multiple of the Opening Range size"},
    {"key": "atr_period",          "label": "ATR Period",               "type": "int",   "default": 14,    "min": 5,    "max": 50,   "step": 1,     "group": "Indicator Settings", "description": "Lookback period for Average True Range calculation"},
    {"key": "session_start_hour",  "label": "Session Start (UTC)",      "type": "int",   "default": 13,    "min": 0,    "max": 23,   "step": 1,     "group": "Session",         "description": "Hour (UTC) when the US trading session begins and OR tracking starts"},
    {"key": "session_end_hour",    "label": "Session End (UTC)",        "type": "int",   "default": 20,    "min": 1,    "max": 23,   "step": 1,     "group": "Session",         "description": "Hour (UTC) when the session ends and all open trades are closed"},
    {"key": "risk_per_trade",      "label": "Risk Per Trade",           "type": "float", "default": 0.01,  "min": 0.001,"max": 0.05, "step": 0.001, "group": "Risk Management", "description": "Fraction of account equity risked per trade (0.01 = 1%)"},
    {"key": "max_daily_trades",    "label": "Max Daily Trades",         "type": "int",   "default": 3,     "min": 1,    "max": 10,   "step": 1,     "group": "Risk Management", "description": "Maximum number of breakout trades allowed per session day"},
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


def _sma_volume(bars, i, lookback=20):
    """Simple moving average of volume over the last `lookback` bars."""
    if i < lookback:
        return 0.0
    total = 0.0
    for j in range(i - lookback, i):
        total += bars[j].get("volume", 0)
    return total / lookback


class NAS100OpeningRangeBreakout:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.atr_vals = _atr(bars, self.s["atr_period"])

        # Daily OR tracking state
        self.or_high = 0.0
        self.or_low = float("inf")
        self.or_bar_count = 0
        self.or_defined = False
        self.current_day = ""
        self.daily_trades = 0

    def _reset_or(self, day):
        """Reset opening range tracking for a new session day."""
        self.or_high = 0.0
        self.or_low = float("inf")
        self.or_bar_count = 0
        self.or_defined = False
        self.current_day = day
        self.daily_trades = 0

    def on_bar(self, i, bar):
        s = self.s
        if i < s["atr_period"] + 2:
            return

        hour = _get_hour(bar)
        if hour == -1:
            return

        day = _get_day(bar)
        close = bar["close"]

        # New day detected — reset OR
        if day != self.current_day and day != "":
            self._reset_or(day)

        # Outside session window — close all trades
        if hour < s["session_start_hour"] or hour >= s["session_end_hour"]:
            for t in list(open_trades):
                close_trade(t, i, close, "session_end")
            return

        # Phase 1: Build the opening range
        if not self.or_defined:
            if hour == s["session_start_hour"] or self.or_bar_count > 0:
                if self.or_bar_count == 0:
                    # First OR bar
                    self.or_high = bar["high"]
                    self.or_low = bar["low"]
                    self.or_bar_count = 1
                else:
                    self.or_high = max(self.or_high, bar["high"])
                    self.or_low = min(self.or_low, bar["low"])
                    self.or_bar_count += 1

                if self.or_bar_count >= s["range_bars"]:
                    self.or_defined = True
            return

        # Phase 2: OR is defined — look for breakout
        or_range = self.or_high - self.or_low
        if or_range <= 0:
            return

        # Max daily trades check
        if self.daily_trades >= s["max_daily_trades"]:
            return

        # Skip if already in a trade
        if len(open_trades) > 0:
            return

        buffer = or_range * s["breakout_buffer_pct"]

        # Volume filter
        avg_vol = _sma_volume(self.bars, i, 20)
        if avg_vol > 0 and bar.get("volume", 0) < s["vol_mult"] * avg_vol:
            return

        # Long breakout
        if close > self.or_high + buffer:
            sl = self.or_low
            tp = close + or_range * s["tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
            self.daily_trades += 1

        # Short breakout
        elif close < self.or_low - buffer:
            sl = self.or_high
            tp = close - or_range * s["tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
            self.daily_trades += 1
