"""
Strategy 47: MACD + RSI Composite (Crypto)
==========================================
Walk-forward validated OK on BTCUSD H1 (PF=1.166, negative PF degradation).

Core idea: MACD signal line crossover confirmed by RSI momentum filter.
RSI must be above 50 for longs, below 50 for shorts — ensures we trade
WITH momentum, not against it.

Signal logic:
  Long:  MACD line crosses above signal line AND RSI > 50
  Short: MACD line crosses below signal line AND RSI < 50
  Exit:  Opposite MACD crossover OR SL/TP hit

Markets : BTCUSD, ETHUSD
Timeframe: H1 / H4
"""

DEFAULTS = {
    "macd_fast":       12,
    "macd_slow":       26,
    "macd_signal":     9,
    "rsi_period":      14,
    "rsi_bull_level":  50,     # RSI must be above this for longs
    "rsi_bear_level":  50,     # RSI must be below this for shorts
    "atr_period":      14,
    "atr_sl_mult":     2.0,
    "atr_tp_mult":     4.0,
    "risk_per_trade":  0.005,
}

SETTINGS = [
    {"key": "macd_fast", "label": "MACD Fast EMA", "type": "int", "default": 12, "min": 5, "max": 30, "step": 1, "group": "Indicator Settings", "description": "Fast EMA period for MACD calculation"},
    {"key": "macd_slow", "label": "MACD Slow EMA", "type": "int", "default": 26, "min": 15, "max": 60, "step": 1, "group": "Indicator Settings", "description": "Slow EMA period for MACD calculation"},
    {"key": "macd_signal", "label": "MACD Signal Period", "type": "int", "default": 9, "min": 3, "max": 20, "step": 1, "group": "Indicator Settings", "description": "Signal line EMA smoothing period"},
    {"key": "rsi_period", "label": "RSI Period", "type": "int", "default": 14, "min": 5, "max": 30, "step": 1, "group": "Indicator Settings", "description": "RSI lookback period"},
    {"key": "rsi_bull_level", "label": "RSI Bull Level", "type": "int", "default": 50, "min": 40, "max": 65, "step": 1, "group": "Entry Rules", "description": "RSI must be above this for long entries"},
    {"key": "rsi_bear_level", "label": "RSI Bear Level", "type": "int", "default": 50, "min": 35, "max": 60, "step": 1, "group": "Entry Rules", "description": "RSI must be below this for short entries"},
    {"key": "atr_period", "label": "ATR Period", "type": "int", "default": 14, "min": 5, "max": 50, "step": 1, "group": "Indicator Settings", "description": "ATR period for SL/TP sizing"},
    {"key": "atr_sl_mult", "label": "ATR SL Multiplier", "type": "float", "default": 2.0, "min": 0.5, "max": 5.0, "step": 0.1, "group": "Risk Management", "description": "ATR multiplier for stop-loss"},
    {"key": "atr_tp_mult", "label": "ATR TP Multiplier", "type": "float", "default": 4.0, "min": 1.0, "max": 12.0, "step": 0.5, "group": "Risk Management", "description": "ATR multiplier for take-profit"},
    {"key": "risk_per_trade", "label": "Risk Per Trade", "type": "float", "default": 0.005, "min": 0.001, "max": 0.05, "step": 0.001, "group": "Risk Management", "description": "Fraction of equity risked per trade"},
]


def _ema(values, period):
    n = len(values)
    out = [0.0] * n
    if period > n:
        return out
    out[period - 1] = sum(values[:period]) / period
    k = 2.0 / (period + 1)
    for i in range(period, n):
        out[i] = values[i] * k + out[i - 1] * (1 - k)
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


def _rsi(bars, period):
    n = len(bars)
    out = [50.0] * n
    if period + 1 > n:
        return out
    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        delta = bars[i]["close"] - bars[i - 1]["close"]
        gains[i] = max(delta, 0)
        losses[i] = max(-delta, 0)
    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    if avg_loss > 0:
        rs = avg_gain / avg_loss
        out[period] = 100 - 100 / (1 + rs)
    else:
        out[period] = 100.0
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            out[i] = 100 - 100 / (1 + rs)
        else:
            out[i] = 100.0
    return out


class MACDRSICrypto:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        n = len(bars)

        closes = [b["close"] for b in bars]

        # MACD
        fast_ema = _ema(closes, self.s["macd_fast"])
        slow_ema = _ema(closes, self.s["macd_slow"])
        self.macd_line = [fast_ema[i] - slow_ema[i] for i in range(n)]
        self.signal_line = _ema(self.macd_line, self.s["macd_signal"])

        # RSI
        self.rsi_vals = _rsi(bars, self.s["rsi_period"])

        # ATR
        self.atr_vals = _atr(bars, self.s["atr_period"])

    def on_bar(self, i, bar):
        s = self.s
        warmup = s["macd_slow"] + s["macd_signal"] + 2
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        close = bar["close"]
        macd = self.macd_line[i]
        macd_prev = self.macd_line[i - 1]
        signal = self.signal_line[i]
        signal_prev = self.signal_line[i - 1]
        rsi = self.rsi_vals[i]

        # MACD crossover detection
        cross_up = macd_prev <= signal_prev and macd > signal
        cross_down = macd_prev >= signal_prev and macd < signal

        # Exit: opposite MACD crossover
        for t in list(open_trades):
            if t["direction"] == "long" and cross_down:
                close_trade(t, i, close, "macd_cross_exit")
            elif t["direction"] == "short" and cross_up:
                close_trade(t, i, close, "macd_cross_exit")

        if len(open_trades) > 0:
            return

        # Entry: MACD cross + RSI confirmation
        if cross_up and rsi > s["rsi_bull_level"]:
            sl = close - s["atr_sl_mult"] * atr_val
            tp = close + s["atr_tp_mult"] * atr_val
            open_trade(i, "long", close, sl, tp)

        elif cross_down and rsi < s["rsi_bear_level"]:
            sl = close + s["atr_sl_mult"] * atr_val
            tp = close - s["atr_tp_mult"] * atr_val
            open_trade(i, "short", close, sl, tp)
