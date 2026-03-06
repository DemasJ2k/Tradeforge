"""
Strategy 35: EMA Price Cross + Momentum
=========================================
Replaces XAGUSD EMA Momentum (only 3 trades, too many filters).

Core idea: Price crosses above/below EMA(20) with momentum confirmation.
  Long : close crosses above EMA(20) AND (close - open) > 0.3 * ATR (bullish candle)
  Short: close crosses below EMA(20) AND (open - close) > 0.3 * ATR (bearish candle)
  No session filter, no ADX, no volume filter. Keep it extremely simple.
  SL = 1.5 ATR, TP = 2.5 ATR

Markets : Universal (indices, forex, crypto)
Timeframe: M5-H1
"""

DEFAULTS = {
    "ema_period":       20,
    "atr_period":       14,
    "momentum_atr":     0.3,
    "atr_sl_mult":      1.5,
    "atr_tp_mult":      2.5,
    "risk_per_trade":   0.01,
}

SETTINGS = [
    {"key": "ema_period",     "label": "EMA Period",               "type": "int",   "default": 20,   "min": 5,    "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "EMA period for price cross signal"},
    {"key": "atr_period",     "label": "ATR Period",               "type": "int",   "default": 14,   "min": 5,    "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "ATR lookback for SL/TP sizing and momentum threshold"},
    {"key": "momentum_atr",   "label": "Momentum ATR Fraction",    "type": "float", "default": 0.3,  "min": 0.1,  "max": 1.0,  "step": 0.05, "group": "Entry Rules",        "description": "Candle body must exceed this fraction of ATR for momentum confirmation"},
    {"key": "atr_sl_mult",    "label": "ATR Stop-Loss Mult",       "type": "float", "default": 1.5,  "min": 0.5,  "max": 4.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Stop-loss distance as ATR multiple from entry"},
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


class XagusdEmaMomentum:
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
        if atr_val <= 0 or ema_now <= 0:
            return

        if len(open_trades) > 0:
            return

        close = bar["close"]
        prev_close = self.bars[i - 1]["close"]
        body = close - bar["open"]
        min_body = atr_val * s["momentum_atr"]

        # Long: close crosses above EMA + bullish momentum
        if prev_close <= ema_prev and close > ema_now and body > min_body:
            sl = close - atr_val * s["atr_sl_mult"]
            tp = close + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # Short: close crosses below EMA + bearish momentum
        elif prev_close >= ema_prev and close < ema_now and (-body) > min_body:
            sl = close + atr_val * s["atr_sl_mult"]
            tp = close - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
