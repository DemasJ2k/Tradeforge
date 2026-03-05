"""
Strategy 35: XAGUSD EMA Momentum Crossover
===========================================
Target : XAGUSD M5
Core   : Fast/Slow EMA crossover filtered by ADX for momentum confirmation.

Entry  :
  - LONG : fast EMA crosses above slow EMA, ADX > threshold
  - SHORT: fast EMA crosses below slow EMA, ADX > threshold
  - Filtered to NY session hours (best silver liquidity)
Exit   :
  - ATR-based SL/TP
  - Forced close at session end
"""

DEFAULTS = {
    "fast_ema":          5,
    "slow_ema":          13,
    "atr_period":        10,
    "adx_period":        14,
    "adx_min":           25,
    "atr_sl_mult":       1.0,
    "atr_tp_mult":       1.5,
    "session_start_hour": 15,
    "session_end_hour":  18,
    "risk_per_trade":    0.01,
    "max_daily_trades":  3,
}


SETTINGS = [
    {"key": "fast_ema",          "label": "Fast EMA Period",        "type": "int",   "default": 5,    "min": 3,     "max": 20,   "step": 1,    "group": "Indicator Settings", "description": "Period for the fast exponential moving average"},
    {"key": "slow_ema",          "label": "Slow EMA Period",        "type": "int",   "default": 13,   "min": 8,     "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "Period for the slow exponential moving average"},
    {"key": "atr_period",        "label": "ATR Period",             "type": "int",   "default": 10,   "min": 5,     "max": 30,   "step": 1,    "group": "Indicator Settings", "description": "Lookback period for Average True Range calculation"},
    {"key": "adx_period",        "label": "ADX Period",             "type": "int",   "default": 14,   "min": 7,     "max": 30,   "step": 1,    "group": "Indicator Settings", "description": "Lookback period for Average Directional Index"},
    {"key": "adx_min",           "label": "ADX Minimum",            "type": "int",   "default": 25,   "min": 15,    "max": 40,   "step": 1,    "group": "Entry Rules",        "description": "Minimum ADX value required for entry (momentum filter)"},
    {"key": "atr_sl_mult",       "label": "ATR Stop-Loss Multiple", "type": "float", "default": 1.0,  "min": 0.5,   "max": 3.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Stop-loss distance as a multiple of ATR"},
    {"key": "atr_tp_mult",       "label": "ATR Take-Profit Multiple","type": "float","default": 1.5,  "min": 1.0,   "max": 5.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Take-profit distance as a multiple of ATR"},
    {"key": "session_start_hour","label": "Session Start (UTC)",    "type": "int",   "default": 15,   "min": 0,     "max": 23,   "step": 1,    "group": "Session Filter",     "description": "UTC hour when the trading session opens"},
    {"key": "session_end_hour",  "label": "Session End (UTC)",      "type": "int",   "default": 18,   "min": 0,     "max": 23,   "step": 1,    "group": "Session Filter",     "description": "UTC hour when the trading session closes (open trades closed)"},
    {"key": "risk_per_trade",    "label": "Risk Per Trade",         "type": "float", "default": 0.01, "min": 0.001, "max": 0.1,  "step": 0.001,"group": "Risk Management",    "description": "Fraction of account balance risked per trade"},
    {"key": "max_daily_trades",  "label": "Max Daily Trades",       "type": "int",   "default": 3,    "min": 1,     "max": 10,   "step": 1,    "group": "Risk Management",    "description": "Maximum number of trades allowed per session day"},
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


def _ema(bars, period, key="close"):
    n = len(bars)
    out = [0.0] * n
    if n < period:
        return out
    out[period - 1] = sum(b[key] for b in bars[:period]) / period
    k = 2 / (period + 1)
    for i in range(period, n):
        out[i] = bars[i][key] * k + out[i - 1] * (1 - k)
    return out


def _adx(bars, period):
    n = len(bars)
    out = [0.0] * n
    if n < period * 2:
        return out
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    tr = [0.0] * n
    for i in range(1, n):
        hi_diff = bars[i]["high"] - bars[i - 1]["high"]
        lo_diff = bars[i - 1]["low"] - bars[i]["low"]
        plus_dm[i] = hi_diff if hi_diff > lo_diff and hi_diff > 0 else 0
        minus_dm[i] = lo_diff if lo_diff > hi_diff and lo_diff > 0 else 0
        tr[i] = max(bars[i]["high"] - bars[i]["low"],
                     abs(bars[i]["high"] - bars[i - 1]["close"]),
                     abs(bars[i]["low"] - bars[i - 1]["close"]))
    sm_tr = [0.0] * n
    sm_pdm = [0.0] * n
    sm_mdm = [0.0] * n
    sm_tr[period] = sum(tr[1:period + 1])
    sm_pdm[period] = sum(plus_dm[1:period + 1])
    sm_mdm[period] = sum(minus_dm[1:period + 1])
    for i in range(period + 1, n):
        sm_tr[i] = sm_tr[i - 1] - (sm_tr[i - 1] / period) + tr[i]
        sm_pdm[i] = sm_pdm[i - 1] - (sm_pdm[i - 1] / period) + plus_dm[i]
        sm_mdm[i] = sm_mdm[i - 1] - (sm_mdm[i - 1] / period) + minus_dm[i]
    dx = [0.0] * n
    for i in range(period, n):
        if sm_tr[i] == 0:
            continue
        pdi = 100 * sm_pdm[i] / sm_tr[i]
        mdi = 100 * sm_mdm[i] / sm_tr[i]
        s = pdi + mdi
        dx[i] = 100 * abs(pdi - mdi) / s if s > 0 else 0
    out[period * 2 - 1] = sum(dx[period:period * 2]) / period if period > 0 else 0
    for i in range(period * 2, n):
        out[i] = (out[i - 1] * (period - 1) + dx[i]) / period
    return out


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

class XagusdEmaMomentum:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.fast = _ema(bars, self.s["fast_ema"])
        self.slow = _ema(bars, self.s["slow_ema"])
        self.atr_vals = _atr(bars, self.s["atr_period"])
        self.adx_vals = _adx(bars, self.s["adx_period"])
        self.daily_count = 0
        self.last_day = None

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["slow_ema"], s["adx_period"] * 2) + 2
        if i < warmup:
            return

        hour = _get_hour(bar)

        # ---- Reset daily trade counter ----
        day_key = bar.get("time", "")[:10] if isinstance(bar.get("time", ""), str) else ""
        if day_key and day_key != self.last_day:
            self.daily_count = 0
            self.last_day = day_key

        # ---- Close trades at session end ----
        if hour >= s["session_end_hour"] and len(open_trades) > 0:
            for t in list(open_trades):
                close_trade(t, i, bar["close"], "session_end")
            return

        # ---- Session filter ----
        if hour < s["session_start_hour"] or hour >= s["session_end_hour"]:
            return

        # ---- Guards ----
        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return
        if len(open_trades) > 0:
            return
        if self.daily_count >= s["max_daily_trades"]:
            return

        adx_val = self.adx_vals[i]
        if adx_val < s["adx_min"]:
            return

        fast_now = self.fast[i]
        fast_prev = self.fast[i - 1]
        slow_now = self.slow[i]
        slow_prev = self.slow[i - 1]
        close = bar["close"]

        # ---- Long crossover ----
        if fast_now > slow_now and fast_prev <= slow_prev:
            sl = close - atr_val * s["atr_sl_mult"]
            tp = close + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
            self.daily_count += 1

        # ---- Short crossover ----
        elif fast_now < slow_now and fast_prev >= slow_prev:
            sl = close + atr_val * s["atr_sl_mult"]
            tp = close - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
            self.daily_count += 1
