"""
Strategy 32: CCI + EMA Trend Filter
=====================================
Replaces US500 RSI(2) Mean Reversion (PF=0.02-0.04, catastrophic).

Core idea: CCI(20) crossover at extreme levels with EMA(50) trend filter.
  Long : CCI crosses above -100 while close > EMA(50) (leaving oversold in uptrend)
  Short: CCI crosses below +100 while close < EMA(50) (leaving overbought in downtrend)
  SL = 1.5 ATR, TP = 3.0 ATR

Markets : Universal (indices, forex, crypto)
Timeframe: M5-H1
"""

DEFAULTS = {
    "cci_period":       20,
    "cci_os":           -100,
    "cci_ob":           100,
    "ema_period":       50,
    "atr_period":       14,
    "atr_sl_mult":      1.5,
    "atr_tp_mult":      3.0,
    "risk_per_trade":   0.01,
}

SETTINGS = [
    {"key": "cci_period",     "label": "CCI Period",               "type": "int",   "default": 20,   "min": 10,   "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "Lookback for Commodity Channel Index"},
    {"key": "cci_os",         "label": "CCI Oversold Level",       "type": "int",   "default": -100, "min": -200, "max": -50,  "step": 10,   "group": "Entry Rules",        "description": "CCI level below which market is oversold"},
    {"key": "cci_ob",         "label": "CCI Overbought Level",     "type": "int",   "default": 100,  "min": 50,   "max": 200,  "step": 10,   "group": "Entry Rules",        "description": "CCI level above which market is overbought"},
    {"key": "ema_period",     "label": "Trend EMA Period",         "type": "int",   "default": 50,   "min": 10,   "max": 200,  "step": 5,    "group": "Filters",            "description": "EMA period for trend direction filter"},
    {"key": "atr_period",     "label": "ATR Period",               "type": "int",   "default": 14,   "min": 5,    "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "ATR lookback for SL/TP sizing"},
    {"key": "atr_sl_mult",    "label": "ATR Stop-Loss Mult",       "type": "float", "default": 1.5,  "min": 0.5,  "max": 5.0,  "step": 0.1,  "group": "Risk Management",    "description": "ATR multiplier for stop-loss distance"},
    {"key": "atr_tp_mult",    "label": "ATR Take-Profit Mult",     "type": "float", "default": 3.0,  "min": 0.5,  "max": 10.0, "step": 0.1,  "group": "Risk Management",    "description": "ATR multiplier for take-profit distance"},
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


def _cci(bars, period):
    """Commodity Channel Index. CCI = (TP - SMA(TP)) / (0.015 * MeanDev)."""
    n = len(bars)
    out = [0.0] * n
    tp = [(bars[i]["high"] + bars[i]["low"] + bars[i]["close"]) / 3.0 for i in range(n)]

    for i in range(period - 1, n):
        sma = sum(tp[i - period + 1:i + 1]) / period
        mean_dev = sum(abs(tp[j] - sma) for j in range(i - period + 1, i + 1)) / period
        if mean_dev > 0:
            out[i] = (tp[i] - sma) / (0.015 * mean_dev)
        else:
            out[i] = 0.0
    return out


class US500Rsi2MeanReversion:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.ema_vals = _ema(bars, self.s["ema_period"])
        self.atr_vals = _atr(bars, self.s["atr_period"])
        self.cci_vals = _cci(bars, self.s["cci_period"])

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["ema_period"], s["atr_period"], s["cci_period"]) + 2
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        ema_val = self.ema_vals[i]
        if atr_val <= 0 or ema_val <= 0:
            return

        if len(open_trades) > 0:
            return

        close = bar["close"]
        cci_now = self.cci_vals[i]
        cci_prev = self.cci_vals[i - 1]

        # Long: CCI crosses above oversold level + uptrend
        if cci_prev <= s["cci_os"] and cci_now > s["cci_os"] and close > ema_val:
            sl = close - atr_val * s["atr_sl_mult"]
            tp = close + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # Short: CCI crosses below overbought level + downtrend
        elif cci_prev >= s["cci_ob"] and cci_now < s["cci_ob"] and close < ema_val:
            sl = close + atr_val * s["atr_sl_mult"]
            tp = close - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
