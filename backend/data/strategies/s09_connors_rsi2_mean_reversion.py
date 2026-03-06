"""
Strategy 09: Stochastic + EMA Momentum
========================================
Replaces Connors RSI(2) Mean Reversion (PF=0.33-0.38).

Core idea: Stochastic(14,3,3) crossover signals filtered by EMA(50) trend.
  Long : StochK crosses above 20 while close > EMA(50)
  Short: StochK crosses below 80 while close < EMA(50)
  SL = 1.5 ATR, TP = 3.0 ATR

Markets : Universal (indices, forex, crypto)
Timeframe: M5-H1
"""

DEFAULTS = {
    "stoch_k_period":   14,
    "stoch_k_smooth":   3,
    "stoch_d_smooth":   3,
    "stoch_os":         20,
    "stoch_ob":         80,
    "ema_period":       50,
    "atr_period":       14,
    "atr_sl_mult":      1.5,
    "atr_tp_mult":      3.0,
    "risk_per_trade":   0.01,
}

SETTINGS = [
    {"key": "stoch_k_period", "label": "Stoch %K Period",         "type": "int",   "default": 14,   "min": 5,    "max": 30,   "step": 1,    "group": "Indicator Settings", "description": "Lookback for raw Stochastic %K"},
    {"key": "stoch_k_smooth", "label": "Stoch %K Smoothing",      "type": "int",   "default": 3,    "min": 1,    "max": 10,   "step": 1,    "group": "Indicator Settings", "description": "SMA smoothing applied to raw %K"},
    {"key": "stoch_d_smooth", "label": "Stoch %D Smoothing",      "type": "int",   "default": 3,    "min": 1,    "max": 10,   "step": 1,    "group": "Indicator Settings", "description": "SMA smoothing of %K to get %D"},
    {"key": "stoch_os",       "label": "Oversold Level",           "type": "int",   "default": 20,   "min": 5,    "max": 35,   "step": 1,    "group": "Entry Rules",        "description": "StochK cross above this level triggers long"},
    {"key": "stoch_ob",       "label": "Overbought Level",         "type": "int",   "default": 80,   "min": 65,   "max": 95,   "step": 1,    "group": "Entry Rules",        "description": "StochK cross below this level triggers short"},
    {"key": "ema_period",     "label": "Trend EMA Period",         "type": "int",   "default": 50,   "min": 10,   "max": 200,  "step": 5,    "group": "Filters",            "description": "EMA trend filter period"},
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


def _sma(values, period):
    """SMA on a list of floats."""
    n = len(values)
    out = [0.0] * n
    if period > n:
        return out
    s = sum(values[:period])
    out[period - 1] = s / period
    for i in range(period, n):
        s += values[i] - values[i - period]
        out[i] = s / period
    return out


def _stochastic(bars, k_period, k_smooth, d_smooth):
    """Stochastic oscillator. Returns (stoch_k, stoch_d)."""
    n = len(bars)
    raw_k = [50.0] * n
    for i in range(k_period - 1, n):
        highest = max(bars[j]["high"] for j in range(i - k_period + 1, i + 1))
        lowest = min(bars[j]["low"] for j in range(i - k_period + 1, i + 1))
        rng = highest - lowest
        if rng > 0:
            raw_k[i] = 100.0 * (bars[i]["close"] - lowest) / rng
        else:
            raw_k[i] = 50.0

    stoch_k = _sma(raw_k, k_smooth)
    stoch_d = _sma(stoch_k, d_smooth)
    return stoch_k, stoch_d


class ConnorsRSI2:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.ema_vals = _ema(bars, self.s["ema_period"])
        self.atr_vals = _atr(bars, self.s["atr_period"])
        self.stoch_k, self.stoch_d = _stochastic(
            bars, self.s["stoch_k_period"], self.s["stoch_k_smooth"], self.s["stoch_d_smooth"]
        )

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["ema_period"], s["atr_period"],
                     s["stoch_k_period"] + s["stoch_k_smooth"] + s["stoch_d_smooth"]) + 2
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        ema_val = self.ema_vals[i]
        if atr_val <= 0 or ema_val <= 0:
            return

        if len(open_trades) > 0:
            return

        close = bar["close"]
        k_now = self.stoch_k[i]
        k_prev = self.stoch_k[i - 1]

        # Long: StochK crosses above oversold level + uptrend
        if k_prev <= s["stoch_os"] and k_now > s["stoch_os"] and close > ema_val:
            sl = close - atr_val * s["atr_sl_mult"]
            tp = close + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # Short: StochK crosses below overbought level + downtrend
        elif k_prev >= s["stoch_ob"] and k_now < s["stoch_ob"] and close < ema_val:
            sl = close + atr_val * s["atr_sl_mult"]
            tp = close - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
