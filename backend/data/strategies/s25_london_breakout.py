"""
Strategy 25: London Breakout Session
=======================================
Inspired by: Professional institutional forex traders + ICT concepts.

Core idea: The Asian session (00:00–08:00 GMT) creates a range. London
open (08:00 GMT) often breaks this range with strong momentum. Trade the
breakout from Asia range during London session.

Logic:
  1. Identify Asian session high/low (configurable hours)
  2. Wait for London open
  3. First breakout of Asian range = entry
  4. Target: 1.5–2x the Asian range size
  5. Stop: Opposite side of Asian range

Markets : Forex, Indices, Crypto (session-aware markets)
Timeframe: 5m / 15m (intraday)
"""

DEFAULTS = {
    "asia_start_hour":      0,
    "asia_end_hour":        8,
    "london_start_hour":    8,
    "london_end_hour":      16,
    "breakout_buffer_pct":  0.001,   # 0.1% buffer beyond range
    "target_range_mult":    1.5,
    "sl_at_range_opposite": True,
    "atr_period":           14,
    "atr_sl_mult":          1.5,     # Fallback if range SL not used
    "min_range_atr":        0.3,     # Min range must be 0.3x ATR (filter tight ranges)
    "max_range_atr":        3.0,     # Max range 3x ATR (filter too volatile)
    "risk_per_trade":       0.01,
    "max_daily_trades":     2,
}


SETTINGS = [
    {"key": "asia_start_hour",      "label": "Asia Session Start (UTC)",  "type": "int",   "default": 0,     "min": 0,    "max": 23,  "step": 1,    "group": "Session",         "description": "Hour (UTC) when the Asian session range tracking begins"},
    {"key": "asia_end_hour",        "label": "Asia Session End (UTC)",    "type": "int",   "default": 8,     "min": 1,    "max": 23,  "step": 1,    "group": "Session",         "description": "Hour (UTC) when the Asian session range tracking ends"},
    {"key": "london_start_hour",    "label": "London Session Start (UTC)","type": "int",   "default": 8,     "min": 0,    "max": 23,  "step": 1,    "group": "Session",         "description": "Hour (UTC) when the London trading session begins"},
    {"key": "london_end_hour",      "label": "London Session End (UTC)",  "type": "int",   "default": 16,    "min": 1,    "max": 23,  "step": 1,    "group": "Session",         "description": "Hour (UTC) when the London trading session ends"},
    {"key": "breakout_buffer_pct",  "label": "Breakout Buffer %",        "type": "float", "default": 0.001, "min": 0.0,  "max": 0.01,"step": 0.001,"group": "Entry Rules",     "description": "Percentage buffer beyond the Asian range required for a valid breakout"},
    {"key": "target_range_mult",    "label": "Target Range Multiplier",  "type": "float", "default": 1.5,   "min": 0.5,  "max": 5.0, "step": 0.1,  "group": "Exit Rules",      "description": "Take-profit as a multiple of the Asian session range size"},
    {"key": "sl_at_range_opposite", "label": "SL at Range Opposite",     "type": "bool",  "default": True,                                          "group": "Exit Rules",      "description": "Place stop-loss at the opposite side of the Asian range instead of ATR-based"},
    {"key": "atr_period",           "label": "ATR Period",               "type": "int",   "default": 14,    "min": 5,    "max": 50,  "step": 1,    "group": "Risk Management", "description": "Lookback period for Average True Range calculation"},
    {"key": "atr_sl_mult",          "label": "ATR SL Multiplier",        "type": "float", "default": 1.5,   "min": 0.5,  "max": 5.0, "step": 0.1,  "group": "Risk Management", "description": "Fallback stop-loss distance (ATR multiples) when range SL is disabled"},
    {"key": "min_range_atr",        "label": "Min Range (ATR)",          "type": "float", "default": 0.3,   "min": 0.1,  "max": 2.0, "step": 0.1,  "group": "Filters",         "description": "Minimum Asian range size in ATR units to filter out tight ranges"},
    {"key": "max_range_atr",        "label": "Max Range (ATR)",          "type": "float", "default": 3.0,   "min": 1.0,  "max": 10.0,"step": 0.1,  "group": "Filters",         "description": "Maximum Asian range size in ATR units to filter out excessive volatility"},
    {"key": "risk_per_trade",       "label": "Risk Per Trade",           "type": "float", "default": 0.01,  "min": 0.001,"max": 0.05,"step": 0.001,"group": "Risk Management", "description": "Fraction of account equity risked per trade (0.01 = 1%)"},
    {"key": "max_daily_trades",     "label": "Max Daily Trades",         "type": "int",   "default": 2,     "min": 1,    "max": 10,  "step": 1,    "group": "Risk Management", "description": "Maximum number of trades allowed per trading day"},
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
        # Try common formats: "2024-01-01 08:30:00", "2024-01-01T08:30:00"
        for sep in [" ", "T"]:
            if sep in t:
                time_part = t.split(sep)[-1]
                try:
                    return int(time_part.split(":")[0])
                except (ValueError, IndexError):
                    pass
    elif isinstance(t, (int, float)):
        # Unix timestamp
        import datetime
        try:
            dt = datetime.datetime.utcfromtimestamp(t)
            return dt.hour
        except (ValueError, OSError):
            pass
    return -1


class LondonBreakout:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.atr_vals = _atr(bars, self.s["atr_period"])
        self.asia_high = 0.0
        self.asia_low = float("inf")
        self.in_london = False
        self.traded_today = 0
        self.last_asia_reset = -1

    def on_bar(self, i, bar):
        s = self.s
        if i < s["atr_period"] + 2:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        hour = _get_hour(bar)
        close = bar["close"]

        # If we can't detect hours, use a fallback based on bar index modulo
        if hour == -1:
            # Fallback: skip session logic, use simple range breakout
            return

        # Track Asian range
        if s["asia_start_hour"] <= hour < s["asia_end_hour"]:
            if self.last_asia_reset != i // 1000:  # Rough daily reset
                self.asia_high = bar["high"]
                self.asia_low = bar["low"]
                self.last_asia_reset = i // 1000
                self.traded_today = 0
                self.in_london = False
            else:
                self.asia_high = max(self.asia_high, bar["high"])
                self.asia_low = min(self.asia_low, bar["low"])
            return

        # London session
        if s["london_start_hour"] <= hour < s["london_end_hour"]:
            self.in_london = True
        else:
            self.in_london = False
            # Close any open trades at end of London session
            for t in list(open_trades):
                close_trade(t, i, close, "session_end")
            return

        if not self.in_london:
            return

        # Check SL/TP for existing trades
        if len(open_trades) > 0:
            return

        if self.traded_today >= s["max_daily_trades"]:
            return

        asia_range = self.asia_high - self.asia_low
        if asia_range <= 0 or self.asia_low == float("inf"):
            return

        # Range size filter
        if asia_range < atr_val * s["min_range_atr"]:
            return
        if asia_range > atr_val * s["max_range_atr"]:
            return

        buffer = asia_range * s["breakout_buffer_pct"]

        # Breakout above Asian high
        if close > self.asia_high + buffer:
            if s["sl_at_range_opposite"]:
                sl = self.asia_low
            else:
                sl = close - atr_val * s["atr_sl_mult"]
            tp = close + asia_range * s["target_range_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
            self.traded_today += 1

        # Breakout below Asian low
        elif close < self.asia_low - buffer:
            if s["sl_at_range_opposite"]:
                sl = self.asia_high
            else:
                sl = close + atr_val * s["atr_sl_mult"]
            tp = close - asia_range * s["target_range_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
            self.traded_today += 1
