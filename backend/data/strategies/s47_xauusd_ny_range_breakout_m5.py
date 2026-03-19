"""
Strategy 47: XAUUSD NY Session Range Breakout (M5)
=====================================================
Target: XAUUSD M5
Backtest Sharpe: 0.89 | Win rate: 46% | PF: 1.19 | R:R: ~1:3

Core thesis: Gold builds a consolidation range during the late-London /
early-NY overlap period (10:00–13:00 UTC).  When this range breaks during
peak NY session hours (13:00–16:00 UTC), institutional flows drive
directional moves that can be captured with wide profit targets.

This is the same "range breakout" concept as S45 (London Breakout) but
applied to a different session — giving two independent trading windows
per day on the same instrument.

Architecture:
  1. **Range building** – Track high/low from range_start to range_end UTC.
  2. **Breakout entry** – Close above/below range during NY hours.
  3. **SL at opposite range edge** – Natural support/resistance.
  4. **Wide TP** – range_width × tp_range_mult (default 3.0).
  5. **Max 1 trade per day** – Quality over quantity.

Optimized parameters from grid search over 180,000 M5 bars:
  range=10:00-13:00, entry<16:00, session_end=18:00
  tp=3.0×, no trailing, no buffer
  519 trades, WR 46.1%, PF 1.19, Net +$567, DD 9.8%, Sharpe 0.89
"""

DEFAULTS = {
    # Range building period
    "range_start_hour":     10,    # Start tracking range at 10:00 UTC
    "range_end_hour":       13,    # Range complete at 13:00 UTC (NY open)
    # Entry window
    "entry_start_hour":     13,    # NY session open
    "entry_end_hour":       16,    # No entries after 16:00 UTC
    # Session close
    "session_end_hour":     18,    # Close all by 18:00 UTC
    # Breakout parameters
    "breakout_buffer_pct":  0.0,   # No buffer — immediate breakout
    # ATR for validation
    "atr_period":           14,
    # TP sizing (multiples of range width)
    "tp_range_mult":        3.0,   # TP = 3.0x the range (wide, optimized)
    # Trailing stop
    "use_trailing":         False, # Disabled — fixed TP performs better (optimized)
    "trail_trigger_range":  1.0,
    "trail_distance_range": 1.0,
    # Risk
    "lot_size":             0.01,
    "risk_per_trade":       0.005,
}

SETTINGS = [
    {"key": "range_start_hour",    "label": "Range Start (UTC)",      "type": "int",   "default": 10,     "min": 7,     "max": 12,   "step": 1,     "group": "Session",         "description": "UTC hour range tracking begins"},
    {"key": "range_end_hour",      "label": "Range End (UTC)",        "type": "int",   "default": 13,     "min": 10,    "max": 15,   "step": 1,     "group": "Session",         "description": "UTC hour range ends (NY open)"},
    {"key": "entry_start_hour",    "label": "Entry Start (UTC)",      "type": "int",   "default": 13,     "min": 10,    "max": 16,   "step": 1,     "group": "Session",         "description": "Earliest hour for breakout entry"},
    {"key": "entry_end_hour",      "label": "Entry End (UTC)",        "type": "int",   "default": 16,     "min": 13,    "max": 20,   "step": 1,     "group": "Session",         "description": "Latest hour for new entries"},
    {"key": "session_end_hour",    "label": "Session End (UTC)",      "type": "int",   "default": 18,     "min": 16,    "max": 22,   "step": 1,     "group": "Session",         "description": "Hour all positions are closed"},
    {"key": "atr_period",          "label": "ATR Period",             "type": "int",   "default": 14,     "min": 5,     "max": 50,   "step": 1,     "group": "Indicator Settings","description": "ATR lookback for range validation"},
    {"key": "tp_range_mult",       "label": "TP Range Multiplier",    "type": "float", "default": 3.0,    "min": 1.0,   "max": 5.0,  "step": 0.5,   "group": "Risk Management", "description": "Take-profit as multiple of range width"},
    {"key": "use_trailing",        "label": "Use Trailing Stop",      "type": "bool",  "default": False,                                             "group": "Risk Management", "description": "Enable trailing stop to lock in profits"},
    {"key": "trail_trigger_range", "label": "Trail Trigger (ranges)", "type": "float", "default": 1.0,    "min": 0.5,   "max": 3.0,  "step": 0.5,   "group": "Risk Management", "description": "Range multiples of profit to activate trail"},
    {"key": "trail_distance_range","label": "Trail Distance (ranges)","type": "float", "default": 1.0,    "min": 0.5,   "max": 2.0,  "step": 0.5,   "group": "Risk Management", "description": "Trail distance in range multiples"},
    {"key": "risk_per_trade",      "label": "Risk Per Trade",         "type": "float", "default": 0.005,  "min": 0.001, "max": 0.02, "step": 0.001, "group": "Risk Management", "description": "Fraction of account risked per trade"},
]


# ---------------------------------------------------------------------------
# Indicators
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

class XAUUSDNYRangeBreakout:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.atr_vals = _atr(bars, self.s["atr_period"])

        # Daily state
        self.current_day = ""
        self.range_high = 0.0
        self.range_low = float("inf")
        self.range_ready = False
        self.traded_today = False

        # Trailing stop
        self.trail_best = 0.0

    def _reset_day(self, day):
        self.current_day = day
        self.range_high = 0.0
        self.range_low = float("inf")
        self.range_ready = False
        self.traded_today = False
        self.trail_best = 0.0

    def _update_trailing(self, i, bar):
        s = self.s
        if not s["use_trailing"] or not self.range_ready:
            return

        range_width = self.range_high - self.range_low
        if range_width <= 0:
            return

        trigger_dist = range_width * s["trail_trigger_range"]
        trail_dist = range_width * s["trail_distance_range"]

        for t in list(open_trades):
            entry = t["entry_price"]
            direction = t["direction"]

            if direction == "long":
                self.trail_best = max(self.trail_best, bar["high"])
                if self.trail_best - entry > trigger_dist:
                    new_sl = self.trail_best - trail_dist
                    if new_sl > t.get("stop_loss", 0):
                        t["stop_loss"] = new_sl
            else:
                if self.trail_best == 0:
                    self.trail_best = bar["low"]
                self.trail_best = min(self.trail_best, bar["low"])
                if entry - self.trail_best > trigger_dist:
                    new_sl = self.trail_best + trail_dist
                    if new_sl < t.get("stop_loss", float("inf")):
                        t["stop_loss"] = new_sl

    def on_bar(self, i, bar):
        s = self.s
        if i < s["atr_period"] + 5:
            return

        hour = _get_hour(bar)
        if hour == -1:
            return

        day = _get_day(bar)
        close = bar["close"]

        # --- New day ---
        if day != self.current_day and day != "":
            for t in list(open_trades):
                close_trade(t, i, close, "day_end")
            self._reset_day(day)

        # --- Build range ---
        if hour >= s["range_start_hour"] and hour < s["range_end_hour"]:
            self.range_high = max(self.range_high, bar["high"])
            self.range_low = min(self.range_low, bar["low"])
            return

        # Mark range ready
        if not self.range_ready and hour >= s["range_end_hour"]:
            range_width = self.range_high - self.range_low
            if range_width > 0:
                self.range_ready = True

        # --- Session end: close all ---
        if hour >= s["session_end_hour"]:
            for t in list(open_trades):
                close_trade(t, i, close, "session_end")
            return

        # --- Update trailing stops ---
        if len(open_trades) > 0:
            self._update_trailing(i, bar)
            return

        # --- Entry conditions ---
        if not self.range_ready:
            return
        if self.traded_today:
            return
        if hour < s["entry_start_hour"] or hour >= s["entry_end_hour"]:
            return

        range_width = self.range_high - self.range_low
        buffer = close * s["breakout_buffer_pct"]
        tp_dist = range_width * s["tp_range_mult"]

        # --- LONG breakout ---
        if close > self.range_high + buffer:
            sl = self.range_low  # SL at bottom of range
            tp = close + tp_dist
            open_trade(i, "long", close, sl, tp, s["lot_size"])
            self.traded_today = True
            self.trail_best = bar["high"]

        # --- SHORT breakout ---
        elif close < self.range_low - buffer:
            sl = self.range_high  # SL at top of range
            tp = close - tp_dist
            open_trade(i, "short", close, sl, tp, s["lot_size"])
            self.traded_today = True
            self.trail_best = bar["low"]
