"""
Strategy 02: Keltner Channel Breakout
======================================
Replaces ICT Silver Bullet (too complex, PF=0.26-0.43).

Core idea: Keltner Channel = EMA(20) +/- 2*ATR(10). Trade breakouts
in the direction of the trend (rising/falling EMA).
  Long : close > upper band AND EMA(20) rising (EMA[i] > EMA[i-1])
  Short: close < lower band AND EMA(20) falling (EMA[i] < EMA[i-1])
  SL = EMA(20), TP = entry + 2.5*ATR

Markets : Universal (indices, forex, crypto)
Timeframe: M5-H1
"""

DEFAULTS = {
    "ema_period":       20,
    "atr_period":       10,
    "kc_mult":          2.0,
    "atr_tp_mult":      2.5,
    "risk_per_trade":   0.01,
}

SETTINGS = [
    {"key": "ema_period",     "label": "EMA Period",               "type": "int",   "default": 20,   "min": 10,   "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "EMA period for Keltner Channel centre line"},
    {"key": "atr_period",     "label": "ATR Period",               "type": "int",   "default": 10,   "min": 5,    "max": 30,   "step": 1,    "group": "Indicator Settings", "description": "ATR lookback for channel width"},
    {"key": "kc_mult",        "label": "KC ATR Multiplier",        "type": "float", "default": 2.0,  "min": 1.0,  "max": 4.0,  "step": 0.1,  "group": "Indicator Settings", "description": "ATR multiplier for Keltner Channel bands"},
    {"key": "atr_tp_mult",    "label": "ATR Take-Profit Mult",     "type": "float", "default": 2.5,  "min": 1.0,  "max": 6.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Take-profit distance as ATR multiple from entry"},
    {"key": "risk_per_trade", "label": "Risk Per Trade",           "type": "float", "default": 0.01, "min": 0.001,"max": 0.1,  "step": 0.001,"group": "Risk Management",    "description": "Fraction of account equity risked per trade"},
]


def _ema(bars, period):
    n = len(bars)
    out = [0.0] * n
    if period > n:
        return out
    out[period - 1] = sum(bars[j]["close"] for j in range(period)) / period
    k = 2.0 / (period + 1)
    for i in range(period, n):
        out[i] = bars[i]["close"] * k + out[i - 1] * (1 - k)
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


class ICTSilverBullet:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.ema_vals = _ema(bars, self.s["ema_period"])
        self.atr_vals = _atr(bars, self.s["atr_period"])

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["ema_period"], s["atr_period"]) + 2
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        ema_now = self.ema_vals[i]
        ema_prev = self.ema_vals[i - 1]

        if atr_val <= 0 or ema_now <= 0 or ema_prev <= 0:
            return

        if len(open_trades) > 0:
            return

        close = bar["close"]
        upper = ema_now + s["kc_mult"] * atr_val
        lower = ema_now - s["kc_mult"] * atr_val

        # Long: close breaks above upper band + EMA rising
        if close > upper and ema_now > ema_prev:
            sl = ema_now  # SL at EMA centre
            tp = close + s["atr_tp_mult"] * atr_val
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # Short: close breaks below lower band + EMA falling
        elif close < lower and ema_now < ema_prev:
            sl = ema_now  # SL at EMA centre
            tp = close - s["atr_tp_mult"] * atr_val
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
