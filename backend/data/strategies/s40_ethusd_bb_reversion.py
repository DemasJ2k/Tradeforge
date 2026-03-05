"""
Strategy 40: ETHUSD Bollinger Band Mean Reversion
===================================================
Target: ETHUSD H4

Core idea: Trade reversals at Bollinger Band extremes when the bands are
wide enough (not in a squeeze). ETH on higher timeframes shows reliable
mean-reversion when price overextends beyond the bands and prints a
reversal candle back inside.

Entry:
  LONG  — price low touches/exceeds lower band, close > lower band,
           bullish candle (close > open)
  SHORT — price high touches/exceeds upper band, close < upper band,
           bearish candle (close < open)
  Filter: BB width must exceed min_width_pct * average width (no squeeze)

Exit:
  SL = ATR(14) * atr_sl_mult beyond the BB extreme
  TP = BB middle band (SMA)
"""

# ── Settings (tunable via FlowrexAlgo UI) ─────────────────────────
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
    {"key": "bb_period",        "label": "BB Period",              "type": "int",   "default": 20,   "min": 10,    "max": 100,  "step": 1,    "group": "Indicator Settings", "description": "Lookback period for the Bollinger Band SMA"},
    {"key": "bb_std",           "label": "BB Std Dev Multiple",    "type": "float", "default": 2.0,  "min": 1.0,   "max": 4.0,  "step": 0.1,  "group": "Indicator Settings", "description": "Number of standard deviations for the upper/lower bands"},
    {"key": "atr_period",       "label": "ATR Period",             "type": "int",   "default": 14,   "min": 5,     "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "Lookback period for Average True Range calculation"},
    {"key": "atr_sl_mult",      "label": "ATR Stop-Loss Multiple", "type": "float", "default": 2.0,  "min": 0.5,   "max": 5.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Stop-loss distance as a multiple of ATR beyond the BB extreme"},
    {"key": "min_width_pct",    "label": "Min Width % of Avg",     "type": "float", "default": 0.5,  "min": 0.1,   "max": 2.0,  "step": 0.1,  "group": "Filters",            "description": "BB width must exceed this fraction of average width (squeeze filter)"},
    {"key": "width_avg_period", "label": "Width Avg Period",       "type": "int",   "default": 50,   "min": 10,    "max": 200,  "step": 1,    "group": "Filters",            "description": "Lookback period for computing average Bollinger Band width"},
    {"key": "risk_per_trade",   "label": "Risk Per Trade",         "type": "float", "default": 0.01, "min": 0.001, "max": 0.1,  "step": 0.001,"group": "Risk Management",    "description": "Fraction of account balance risked per trade"},
]


# ── Helpers ──────────────────────────────────────────────────────
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


def _sma_arr(data, period):
    """Simple moving average over a plain numeric array."""
    n = len(data)
    out = [0.0] * n
    if period > n:
        return out
    s = sum(data[:period])
    out[period - 1] = s / period
    for i in range(period, n):
        s += data[i] - data[i - period]
        out[i] = s / period
    return out


def _get_hour(bar):
    t = bar.get("time", "")
    if isinstance(t, str):
        for sep in [" ", "T"]:
            if sep in t:
                try:
                    return int(t.split(sep)[-1].split(":")[0])
                except:
                    pass
    elif isinstance(t, (int, float)):
        import datetime
        try:
            return datetime.datetime.utcfromtimestamp(t).hour
        except:
            pass
    return -1


# ── Strategy ─────────────────────────────────────────────────────
class ETHUSDBBReversion:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        p = self.s
        self.upper, self.middle, self.lower, self.width = _bb(
            bars, p["bb_period"], p["bb_std"]
        )
        self.avg_width = _sma_arr(self.width, p["width_avg_period"])
        self.atr = _atr(bars, p["atr_period"])

    def on_bar(self, i, bar):
        p = self.s

        # -- need enough data for all indicators --
        min_bars = max(
            p["bb_period"],
            p["bb_period"] + p["width_avg_period"] - 1,
            p["atr_period"] + 1,
        )
        if i < min_bars:
            return

        # -- skip if already in a position --
        if len(open_trades) > 0:
            return

        # -- read indicator values --
        ub = self.upper[i]
        mb = self.middle[i]
        lb = self.lower[i]
        bw = self.width[i]
        avg_w = self.avg_width[i]
        atr_val = self.atr[i]

        if atr_val <= 0 or avg_w <= 0:
            return

        # -- squeeze filter: band width must exceed threshold --
        if bw < p["min_width_pct"] * avg_w:
            return

        hi = bar["high"]
        lo = bar["low"]
        cl = bar["close"]
        op = bar["open"]
        sl_dist = atr_val * p["atr_sl_mult"]

        # -- LONG: price touched/exceeded lower band, closed back inside, bullish candle --
        if lo <= lb and cl > lb and cl > op:
            entry = cl
            sl = lb - sl_dist
            tp = mb
            # only take trade if TP is above entry (valid R:R)
            if tp > entry:
                open_trade(i, "long", entry, sl, tp, p["risk_per_trade"])
            return

        # -- SHORT: price touched/exceeded upper band, closed back inside, bearish candle --
        if hi >= ub and cl < ub and cl < op:
            entry = cl
            sl = ub + sl_dist
            tp = mb
            # only take trade if TP is below entry (valid R:R)
            if tp < entry:
                open_trade(i, "short", entry, sl, tp, p["risk_per_trade"])
            return
