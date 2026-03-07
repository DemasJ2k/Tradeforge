"""
Strategy 44: XAGUSD Stochastic Flip Scalper
=============================================
Target: XAGUSD M5

Core idea: Trade Stochastic K/D crossovers in extreme overbought/oversold
zones on silver. Silver's high beta and mean-reverting nature on M5 makes
it ideal for stochastic-based scalping. An optional EMA trend filter can
be enabled to trade only in the trend direction.

Entry:
  LONG  -- K < stoch_os (oversold zone) AND K crosses above D
           (K > D on current bar, prev K <= prev D)
           Optional: close > trend EMA when use_trend_filter is True
  SHORT -- K > stoch_ob (overbought zone) AND K crosses below D
           (K < D on current bar, prev K >= prev D)
           Optional: close < trend EMA when use_trend_filter is True

Exit:
  SL = ATR(14) * atr_sl_mult from entry
  TP = ATR(14) * atr_tp_mult from entry

24h session, works on M5.
"""

# -- Settings (tunable via FlowrexAlgo UI) --------------------------
DEFAULTS = {
    "stoch_k_period":   8,
    "stoch_d_period":   3,
    "stoch_os":         29,
    "stoch_ob":         89,
    "trend_ema":        38,
    "use_trend_filter": False,
    "atr_period":       14,
    "atr_sl_mult":      0.375,
    "atr_tp_mult":      0.93,
    "risk_per_trade":   0.005,
}

SETTINGS = [
    {"key": "stoch_k_period",   "label": "Stoch %K Period",        "type": "int",   "default": 8,     "min": 3,     "max": 21,   "step": 1,    "group": "Indicator Settings", "description": "Lookback period for raw Stochastic %K calculation"},
    {"key": "stoch_d_period",   "label": "Stoch %D Period",        "type": "int",   "default": 3,     "min": 2,     "max": 10,   "step": 1,    "group": "Indicator Settings", "description": "EMA smoothing period for %D signal line"},
    {"key": "trend_ema",        "label": "Trend EMA Period",       "type": "int",   "default": 38,    "min": 10,    "max": 200,  "step": 1,    "group": "Indicator Settings", "description": "EMA period for optional trend direction filter"},
    {"key": "atr_period",       "label": "ATR Period",             "type": "int",   "default": 14,    "min": 5,     "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "ATR lookback period for stop/target sizing"},
    {"key": "stoch_os",         "label": "Stoch Oversold Level",   "type": "int",   "default": 29,    "min": 5,     "max": 45,   "step": 1,    "group": "Entry Rules",        "description": "K must be below this level for long entries"},
    {"key": "stoch_ob",         "label": "Stoch Overbought Level", "type": "int",   "default": 89,    "min": 65,    "max": 95,   "step": 1,    "group": "Entry Rules",        "description": "K must be above this level for short entries"},
    {"key": "use_trend_filter", "label": "Use Trend Filter",       "type": "bool",  "default": False,                                          "group": "Filters",            "description": "When enabled, only take longs above EMA and shorts below EMA"},
    {"key": "atr_sl_mult",      "label": "ATR Stop-Loss Mult",     "type": "float", "default": 0.375, "min": 0.1,   "max": 5.0,  "step": 0.025,"group": "Risk Management",    "description": "ATR multiplier for stop-loss distance"},
    {"key": "atr_tp_mult",      "label": "ATR Take-Profit Mult",   "type": "float", "default": 0.93,  "min": 0.25,  "max": 5.0,  "step": 0.05, "group": "Risk Management",    "description": "ATR multiplier for take-profit distance"},
    {"key": "risk_per_trade",   "label": "Risk Per Trade",         "type": "float", "default": 0.005, "min": 0.001, "max": 0.05, "step": 0.001,"group": "Risk Management",    "description": "Fraction of account equity risked per trade"},
]


# -- Helpers --------------------------------------------------------
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
    if period > n:
        return out
    out[period - 1] = sum(b[key] for b in bars[:period]) / period
    k = 2.0 / (period + 1)
    for i in range(period, n):
        out[i] = bars[i][key] * k + out[i - 1] * (1 - k)
    return out


def _stochastic(bars, k_period, d_period):
    """Stochastic oscillator with EMA-smoothed %D.

    Returns (stoch_k, stoch_d) as lists of length len(bars).
    %K = (close - lowest_low) / (highest_high - lowest_low) * 100
    %D = EMA(%K, d_period)
    """
    n = len(bars)
    stoch_k = [50.0] * n
    for i in range(k_period - 1, n):
        highest = max(bars[j]["high"] for j in range(i - k_period + 1, i + 1))
        lowest = min(bars[j]["low"] for j in range(i - k_period + 1, i + 1))
        rng = highest - lowest
        if rng > 0:
            stoch_k[i] = 100.0 * (bars[i]["close"] - lowest) / rng
        else:
            stoch_k[i] = 50.0

    # %D as EMA of %K
    stoch_d = [50.0] * n
    if d_period > n:
        return stoch_k, stoch_d
    start = k_period - 1
    if start + d_period - 1 >= n:
        return stoch_k, stoch_d
    seed_start = start
    seed_end = start + d_period
    stoch_d[seed_end - 1] = sum(stoch_k[seed_start:seed_end]) / d_period
    mul = 2.0 / (d_period + 1)
    for i in range(seed_end, n):
        stoch_d[i] = stoch_k[i] * mul + stoch_d[i - 1] * (1 - mul)
    return stoch_k, stoch_d


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


# -- Strategy -------------------------------------------------------
class XAGUSDStochFlipScalper:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.stoch_k, self.stoch_d = _stochastic(
            bars, self.s["stoch_k_period"], self.s["stoch_d_period"]
        )
        self.atr_vals = _atr(bars, self.s["atr_period"])
        self.ema_vals = _ema(bars, self.s["trend_ema"]) if self.s["use_trend_filter"] else None

    def on_bar(self, i, bar):
        p = self.s
        warmup = max(p["stoch_k_period"] + p["stoch_d_period"],
                     p["atr_period"] + 1, p["trend_ema"] if p["use_trend_filter"] else 0) + 2
        if i < warmup:
            return

        if len(open_trades) > 0:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        k_now = self.stoch_k[i]
        k_prev = self.stoch_k[i - 1]
        d_now = self.stoch_d[i]
        d_prev = self.stoch_d[i - 1]
        close = bar["close"]

        entry = close
        sl_dist = atr_val * p["atr_sl_mult"]
        tp_dist = atr_val * p["atr_tp_mult"]

        # LONG: K in oversold zone AND K crosses above D
        if k_now < p["stoch_os"] and k_now > d_now and k_prev <= d_prev:
            if p["use_trend_filter"] and self.ema_vals is not None:
                if close <= self.ema_vals[i]:
                    return
            sl = entry - sl_dist
            tp = entry + tp_dist
            open_trade(i, "long", entry, sl, tp, p["risk_per_trade"])

        # SHORT: K in overbought zone AND K crosses below D
        elif k_now > p["stoch_ob"] and k_now < d_now and k_prev >= d_prev:
            if p["use_trend_filter"] and self.ema_vals is not None:
                if close >= self.ema_vals[i]:
                    return
            sl = entry + sl_dist
            tp = entry - tp_dist
            open_trade(i, "short", entry, sl, tp, p["risk_per_trade"])
