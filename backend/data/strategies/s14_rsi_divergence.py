"""
Strategy 14: MACD + EMA Momentum
==================================
Replaces RSI Divergence (PF=0.72-0.81, consistent loser).

Core idea: MACD(12,26,9) histogram direction with EMA(50) trend filter.
  Long : MACD histogram turns positive (prev <= 0, now > 0) while close > EMA(50)
  Short: MACD histogram turns negative (prev >= 0, now < 0) while close < EMA(50)
  SL = 1.5 ATR, TP = 3.0 ATR

Markets : Universal (indices, forex, crypto)
Timeframe: M5-H1
"""

DEFAULTS = {
    "macd_fast":        12,
    "macd_slow":        26,
    "macd_signal":      9,
    "ema_trend":        50,
    "atr_period":       14,
    "atr_sl_mult":      1.5,
    "atr_tp_mult":      3.0,
    "risk_per_trade":   0.01,
}

SETTINGS = [
    {"key": "macd_fast",      "label": "MACD Fast EMA",           "type": "int",   "default": 12,   "min": 5,    "max": 20,   "step": 1,    "group": "Indicator Settings", "description": "Fast EMA period for MACD line"},
    {"key": "macd_slow",      "label": "MACD Slow EMA",           "type": "int",   "default": 26,   "min": 15,   "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "Slow EMA period for MACD line"},
    {"key": "macd_signal",    "label": "MACD Signal Period",       "type": "int",   "default": 9,    "min": 3,    "max": 20,   "step": 1,    "group": "Indicator Settings", "description": "Signal line EMA period"},
    {"key": "ema_trend",      "label": "Trend EMA Period",         "type": "int",   "default": 50,   "min": 10,   "max": 200,  "step": 5,    "group": "Filters",            "description": "EMA period for trend direction filter"},
    {"key": "atr_period",     "label": "ATR Period",               "type": "int",   "default": 14,   "min": 5,    "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "ATR lookback for SL/TP sizing"},
    {"key": "atr_sl_mult",    "label": "ATR Stop-Loss Mult",       "type": "float", "default": 1.5,  "min": 0.5,  "max": 5.0,  "step": 0.1,  "group": "Risk Management",    "description": "ATR multiplier for stop-loss distance"},
    {"key": "atr_tp_mult",    "label": "ATR Take-Profit Mult",     "type": "float", "default": 3.0,  "min": 0.5,  "max": 10.0, "step": 0.1,  "group": "Risk Management",    "description": "ATR multiplier for take-profit distance"},
    {"key": "risk_per_trade", "label": "Risk Per Trade",           "type": "float", "default": 0.01, "min": 0.001,"max": 0.05, "step": 0.001,"group": "Risk Management",    "description": "Fraction of account equity risked per trade"},
]


def _ema_on_values(values, period):
    """EMA on a list of floats."""
    n = len(values)
    out = [0.0] * n
    if period > n:
        return out
    out[period - 1] = sum(values[:period]) / period
    k = 2.0 / (period + 1)
    for i in range(period, n):
        out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out


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


def _macd(bars, fast_p, slow_p, sig_p):
    """MACD line, signal line, histogram."""
    n = len(bars)
    closes = [bars[i]["close"] for i in range(n)]
    fast_ema = _ema_on_values(closes, fast_p)
    slow_ema = _ema_on_values(closes, slow_p)
    macd_line = [fast_ema[i] - slow_ema[i] for i in range(n)]
    signal_line = _ema_on_values(macd_line, sig_p)
    histogram = [macd_line[i] - signal_line[i] for i in range(n)]
    return macd_line, signal_line, histogram


class RSIDivergence:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.ema_vals = _ema(bars, self.s["ema_trend"])
        self.atr_vals = _atr(bars, self.s["atr_period"])
        _, _, self.histogram = _macd(bars, self.s["macd_fast"], self.s["macd_slow"], self.s["macd_signal"])

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["ema_trend"], s["macd_slow"] + s["macd_signal"], s["atr_period"]) + 2
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        ema_val = self.ema_vals[i]
        if atr_val <= 0 or ema_val <= 0:
            return

        if len(open_trades) > 0:
            return

        close = bar["close"]
        hist_now = self.histogram[i]
        hist_prev = self.histogram[i - 1]

        # Long: histogram turns positive + uptrend
        if hist_prev <= 0 and hist_now > 0 and close > ema_val:
            sl = close - atr_val * s["atr_sl_mult"]
            tp = close + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # Short: histogram turns negative + downtrend
        elif hist_prev >= 0 and hist_now < 0 and close < ema_val:
            sl = close + atr_val * s["atr_sl_mult"]
            tp = close - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
