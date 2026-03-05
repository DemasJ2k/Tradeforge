"""
Strategy 36: XAGUSD Bollinger Band Mean Reversion
==================================================
Target : XAGUSD H1
Core   : Bollinger Band touch with reversal candle confirmation.

Entry  :
  - LONG : price touches/exceeds lower BB, bullish reversal candle
           (low <= lower band, close > lower band, close > open)
  - SHORT: price touches/exceeds upper BB, bearish reversal candle
           (high >= upper band, close < upper band, close < open)
  - BB width must exceed min_width_pct * average width (no squeeze)
Exit   :
  - TP at BB middle band
  - SL at ATR * mult beyond the BB extreme
"""

DEFAULTS = {
    "bb_period":        20,
    "bb_std":           2.0,
    "atr_period":       14,
    "atr_sl_mult":      2.0,
    "min_width_pct":    0.5,
    "width_avg_period": 50,
    "risk_per_trade":   0.01,
}


SETTINGS = [
    {"key": "bb_period",        "label": "BB Period",               "type": "int",   "default": 20,   "min": 10,    "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "Lookback period for Bollinger Bands SMA calculation"},
    {"key": "bb_std",           "label": "BB Std Deviation",        "type": "float", "default": 2.0,  "min": 1.0,   "max": 3.5,  "step": 0.1,  "group": "Indicator Settings", "description": "Standard deviation multiplier for Bollinger Bands"},
    {"key": "atr_period",       "label": "ATR Period",              "type": "int",   "default": 14,   "min": 5,     "max": 30,   "step": 1,    "group": "Indicator Settings", "description": "Lookback period for Average True Range calculation"},
    {"key": "atr_sl_mult",      "label": "ATR Stop-Loss Multiple",  "type": "float", "default": 2.0,  "min": 1.0,   "max": 4.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Stop-loss distance as a multiple of ATR beyond the BB extreme"},
    {"key": "min_width_pct",    "label": "Min BB Width %",          "type": "float", "default": 0.5,  "min": 0.1,   "max": 1.0,  "step": 0.05, "group": "Entry Rules",        "description": "Minimum BB width as a fraction of average width (squeeze filter)"},
    {"key": "width_avg_period", "label": "Width Average Period",    "type": "int",   "default": 50,   "min": 20,    "max": 100,  "step": 5,    "group": "Indicator Settings", "description": "Lookback period for calculating average BB width"},
    {"key": "risk_per_trade",   "label": "Risk Per Trade",          "type": "float", "default": 0.01, "min": 0.001, "max": 0.1,  "step": 0.001,"group": "Risk Management",    "description": "Fraction of account balance risked per trade"},
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


def _bb(bars, period, std_dev):
    """Returns (upper, middle, lower, width) arrays."""
    n = len(bars)
    upper = [0.0] * n
    middle = [0.0] * n
    lower = [0.0] * n
    width = [0.0] * n
    for i in range(period - 1, n):
        closes = [bars[j]["close"] for j in range(i - period + 1, i + 1)]
        m = sum(closes) / period
        variance = sum((c - m) ** 2 for c in closes) / period
        std = variance ** 0.5
        middle[i] = m
        upper[i] = m + std_dev * std
        lower[i] = m - std_dev * std
        width[i] = upper[i] - lower[i]
    return upper, middle, lower, width


def _avg_width(width_arr, i, avg_period):
    """Average of the last avg_period width values ending at index i."""
    start = max(0, i - avg_period + 1)
    segment = [w for w in width_arr[start:i + 1] if w > 0]
    if not segment:
        return 0.0
    return sum(segment) / len(segment)


def _get_hour(bar):
    t = bar.get("time", "")
    if isinstance(t, str):
        for sep in [" ", "T"]:
            if sep in t:
                try:
                    return int(t.split(sep)[-1].split(":")[0])
                except Exception:
                    pass
    elif isinstance(t, (int, float)):
        import datetime
        try:
            return datetime.datetime.utcfromtimestamp(t).hour
        except Exception:
            pass
    return -1


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

class XagusdBbReversion:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.upper, self.middle, self.lower, self.width = _bb(
            bars, self.s["bb_period"], self.s["bb_std"]
        )
        self.atr_vals = _atr(bars, self.s["atr_period"])

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["bb_period"], s["atr_period"]) + s["width_avg_period"] + 2
        if i < warmup:
            return

        # ---- Guards ----
        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return
        if len(open_trades) > 0:
            return

        upper = self.upper[i]
        middle = self.middle[i]
        lower = self.lower[i]
        cur_width = self.width[i]

        if cur_width <= 0 or middle <= 0:
            return

        # ---- Squeeze filter: BB width must be above threshold ----
        avg_w = _avg_width(self.width, i, s["width_avg_period"])
        if avg_w <= 0:
            return
        if cur_width < s["min_width_pct"] * avg_w:
            return

        hi = bar["high"]
        lo = bar["low"]
        cl = bar["close"]
        op = bar["open"]

        # ---- Long: reversal at lower band ----
        if lo <= lower and cl > lower and cl > op:
            sl = lower - atr_val * s["atr_sl_mult"]
            tp = middle
            if tp <= cl:
                return  # no room for profit
            open_trade(i, "long", cl, sl, tp, s["risk_per_trade"])

        # ---- Short: reversal at upper band ----
        elif hi >= upper and cl < upper and cl < op:
            sl = upper + atr_val * s["atr_sl_mult"]
            tp = middle
            if tp >= cl:
                return  # no room for profit
            open_trade(i, "short", cl, sl, tp, s["risk_per_trade"])
