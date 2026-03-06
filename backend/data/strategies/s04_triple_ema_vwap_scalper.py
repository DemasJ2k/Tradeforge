"""
Strategy 04: Triple EMA Crossover Scalper
==========================================
Rewritten: Removed VWAP (cumulative — diverges on long datasets) and the
tight pullback requirement (too restrictive with 3 conditions stacked).

Core idea: 3 EMAs (9, 21, 55) for trend detection + ADX filter.
  - LONG:  fast EMA crosses above mid EMA AND both above slow EMA, ADX > 20
  - SHORT: fast EMA crosses below mid EMA AND both below slow EMA, ADX > 20

One trade at a time. Fixed ATR-based SL/TP.

Markets : Universal
Timeframe: 1m-15m
"""

DEFAULTS = {
    "ema_fast":       9,
    "ema_mid":        21,
    "ema_slow":       55,
    "adx_period":     14,
    "adx_threshold":  20,
    "atr_period":     14,
    "atr_sl_mult":    1.5,
    "atr_tp_mult":    2.5,
    "risk_per_trade": 0.01,
}


SETTINGS = [
    {"key": "ema_fast",       "label": "Fast EMA Period",          "type": "int",   "default": 9,    "min": 5,     "max": 30,   "step": 1,    "group": "Indicator Settings", "description": "Period for the fast exponential moving average"},
    {"key": "ema_mid",        "label": "Mid EMA Period",           "type": "int",   "default": 21,   "min": 10,    "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "Period for the mid exponential moving average"},
    {"key": "ema_slow",       "label": "Slow EMA Period",          "type": "int",   "default": 55,   "min": 30,    "max": 200,  "step": 1,    "group": "Indicator Settings", "description": "Period for the slow exponential moving average"},
    {"key": "adx_period",     "label": "ADX Period",               "type": "int",   "default": 14,   "min": 7,     "max": 30,   "step": 1,    "group": "Filters",            "description": "Lookback period for ADX trend-strength filter"},
    {"key": "adx_threshold",  "label": "ADX Threshold",            "type": "int",   "default": 20,   "min": 10,    "max": 40,   "step": 1,    "group": "Filters",            "description": "Minimum ADX value to confirm a trending market"},
    {"key": "atr_period",     "label": "ATR Period",               "type": "int",   "default": 14,   "min": 5,     "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "Lookback period for Average True Range calculation"},
    {"key": "atr_sl_mult",    "label": "ATR Stop-Loss Multiple",   "type": "float", "default": 1.5,  "min": 0.5,   "max": 4.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Stop-loss distance as a multiple of ATR"},
    {"key": "atr_tp_mult",    "label": "ATR Take-Profit Multiple", "type": "float", "default": 2.5,  "min": 1.0,   "max": 6.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Take-profit distance as a multiple of ATR"},
    {"key": "risk_per_trade", "label": "Risk Per Trade",           "type": "float", "default": 0.01, "min": 0.001, "max": 0.1,  "step": 0.001, "group": "Risk Management",   "description": "Fraction of account balance risked per trade"},
]


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def _ema(data, period):
    out = [0.0] * len(data)
    if period > len(data):
        return out
    k = 2.0 / (period + 1)
    out[period - 1] = sum(data[:period]) / period
    for i in range(period, len(data)):
        out[i] = data[i] * k + out[i - 1] * (1 - k)
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


def _adx(bars, period):
    """Compute ADX (trend strength, 0-100). Returns a single list."""
    n = len(bars)
    adx = [0.0] * n
    if 2 * period + 1 > n:
        return adx

    dmp = [0.0] * n
    dmm = [0.0] * n
    trs = [0.0] * n
    for i in range(1, n):
        h_diff = bars[i]["high"] - bars[i - 1]["high"]
        l_diff = bars[i - 1]["low"] - bars[i]["low"]
        dmp[i] = h_diff if h_diff > l_diff and h_diff > 0 else 0.0
        dmm[i] = l_diff if l_diff > h_diff and l_diff > 0 else 0.0
        trs[i] = max(bars[i]["high"] - bars[i]["low"],
                      abs(bars[i]["high"] - bars[i - 1]["close"]),
                      abs(bars[i]["low"] - bars[i - 1]["close"]))

    sm_tr = sum(trs[1:period + 1])
    sm_dp = sum(dmp[1:period + 1])
    sm_dm = sum(dmm[1:period + 1])
    dx_list = []

    for i in range(period, n):
        if i > period:
            sm_tr = sm_tr - sm_tr / period + trs[i]
            sm_dp = sm_dp - sm_dp / period + dmp[i]
            sm_dm = sm_dm - sm_dm / period + dmm[i]

        di_plus = 100 * sm_dp / sm_tr if sm_tr > 0 else 0
        di_minus = 100 * sm_dm / sm_tr if sm_tr > 0 else 0
        di_sum = di_plus + di_minus
        dx = 100 * abs(di_plus - di_minus) / di_sum if di_sum > 0 else 0
        dx_list.append(dx)
        if len(dx_list) == period:
            adx[i] = sum(dx_list) / period
        elif len(dx_list) > period:
            adx[i] = (adx[i - 1] * (period - 1) + dx) / period

    return adx


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

class TripleEmaVwapScalper:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        closes = [b["close"] for b in bars]
        self.ema_fast = _ema(closes, self.s["ema_fast"])
        self.ema_mid = _ema(closes, self.s["ema_mid"])
        self.ema_slow = _ema(closes, self.s["ema_slow"])
        self.atr_values = _atr(bars, self.s["atr_period"])
        self.adx_values = _adx(bars, self.s["adx_period"])

    def on_bar(self, i, bar):
        s = self.s
        # Warmup: need slow EMA + 2*adx_period settled
        warmup = max(s["ema_slow"], s["adx_period"] * 2) + 2
        if i < warmup:
            return

        atr_val = self.atr_values[i]
        if atr_val <= 0:
            return

        # One trade at a time
        if len(open_trades) > 0:
            return

        # ADX filter: skip choppy / ranging markets
        if self.adx_values[i] < s["adx_threshold"]:
            return

        ef = self.ema_fast[i]
        em = self.ema_mid[i]
        es = self.ema_slow[i]
        ef_prev = self.ema_fast[i - 1]
        em_prev = self.ema_mid[i - 1]

        close = bar["close"]

        # LONG: fast crosses above mid, both above slow
        if ef > em and ef_prev <= em_prev and ef > es and em > es:
            sl = close - atr_val * s["atr_sl_mult"]
            tp = close + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # SHORT: fast crosses below mid, both below slow
        elif ef < em and ef_prev >= em_prev and ef < es and em < es:
            sl = close + atr_val * s["atr_sl_mult"]
            tp = close - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
