"""
Strategy 20: Williams %R + EMA Trend
======================================
Replaces Unger Rotation (PF=0.59-0.69, both modes fail).

Core idea: Williams %R(14) oscillator with EMA(50) trend filter.
  Long : Williams %R crosses above -80 (oversold) while close > EMA(50)
  Short: Williams %R crosses below -20 (overbought) while close < EMA(50)
  SL = 1.5 ATR, TP = 2.5 ATR

Markets : Universal (indices, forex, crypto)
Timeframe: M5-H1
"""

DEFAULTS = {
    "wr_period":        14,
    "wr_os":            -80,
    "wr_ob":            -20,
    "ema_period":       50,
    "atr_period":       14,
    "atr_sl_mult":      1.5,
    "atr_tp_mult":      2.5,
    "risk_per_trade":   0.01,
}

SETTINGS = [
    {"key": "wr_period",      "label": "Williams %R Period",       "type": "int",   "default": 14,   "min": 5,    "max": 30,   "step": 1,    "group": "Indicator Settings", "description": "Lookback for Williams %R"},
    {"key": "wr_os",          "label": "Oversold Level",           "type": "int",   "default": -80,  "min": -95,  "max": -60,  "step": 1,    "group": "Entry Rules",        "description": "Williams %R oversold threshold (long trigger)"},
    {"key": "wr_ob",          "label": "Overbought Level",         "type": "int",   "default": -20,  "min": -40,  "max": -5,   "step": 1,    "group": "Entry Rules",        "description": "Williams %R overbought threshold (short trigger)"},
    {"key": "ema_period",     "label": "Trend EMA Period",         "type": "int",   "default": 50,   "min": 10,   "max": 200,  "step": 5,    "group": "Filters",            "description": "EMA period for trend direction filter"},
    {"key": "atr_period",     "label": "ATR Period",               "type": "int",   "default": 14,   "min": 5,    "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "ATR lookback for SL/TP sizing"},
    {"key": "atr_sl_mult",    "label": "ATR Stop-Loss Mult",       "type": "float", "default": 1.5,  "min": 0.5,  "max": 5.0,  "step": 0.1,  "group": "Risk Management",    "description": "ATR multiplier for stop-loss distance"},
    {"key": "atr_tp_mult",    "label": "ATR Take-Profit Mult",     "type": "float", "default": 2.5,  "min": 0.5,  "max": 10.0, "step": 0.1,  "group": "Risk Management",    "description": "ATR multiplier for take-profit distance"},
    {"key": "risk_per_trade", "label": "Risk Per Trade",           "type": "float", "default": 0.01, "min": 0.001,"max": 0.05, "step": 0.001,"group": "Risk Management",    "description": "Fraction of account equity risked per trade"},
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


def _williams_r(bars, period):
    """Williams %R oscillator. Range: -100 (oversold) to 0 (overbought)."""
    n = len(bars)
    out = [-50.0] * n
    for i in range(period - 1, n):
        highest = max(bars[j]["high"] for j in range(i - period + 1, i + 1))
        lowest = min(bars[j]["low"] for j in range(i - period + 1, i + 1))
        rng = highest - lowest
        if rng > 0:
            out[i] = -100.0 * (highest - bars[i]["close"]) / rng
        else:
            out[i] = -50.0
    return out


class UngerRotation:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.ema_vals = _ema(bars, self.s["ema_period"])
        self.atr_vals = _atr(bars, self.s["atr_period"])
        self.wr_vals = _williams_r(bars, self.s["wr_period"])

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["ema_period"], s["atr_period"], s["wr_period"]) + 2
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        ema_val = self.ema_vals[i]
        if atr_val <= 0 or ema_val <= 0:
            return

        if len(open_trades) > 0:
            return

        close = bar["close"]
        wr_now = self.wr_vals[i]
        wr_prev = self.wr_vals[i - 1]

        # Long: %R crosses above oversold level + uptrend
        if wr_prev <= s["wr_os"] and wr_now > s["wr_os"] and close > ema_val:
            sl = close - atr_val * s["atr_sl_mult"]
            tp = close + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # Short: %R crosses below overbought level + downtrend
        elif wr_prev >= s["wr_ob"] and wr_now < s["wr_ob"] and close < ema_val:
            sl = close + atr_val * s["atr_sl_mult"]
            tp = close - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
