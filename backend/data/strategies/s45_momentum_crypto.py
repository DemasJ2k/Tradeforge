"""
Strategy 45: Momentum ROC + SMA + ATR Rising (Crypto)
=====================================================
Walk-forward validated STRONG on BTCUSD D1 (PF=1.374) and ETHUSD D1 (PF=1.434).

Core idea: Enter trend continuations when Rate of Change confirms momentum,
price is above/below SMA trend filter, and ATR is rising (expanding volatility
= trend acceleration, not consolidation).

Signal logic:
  Long:  ROC(10) > 0 AND close > SMA(20) AND ATR_slope(5) > 0
  Short: ROC(10) < 0 AND close < SMA(20) AND ATR_slope(5) > 0
  Exit:  SL = 2x ATR, TP = 4x ATR, or ROC flips sign

Markets : BTCUSD, ETHUSD, SOLUSD
Timeframe: D1 / H4
"""

DEFAULTS = {
    "roc_period":      10,
    "sma_period":      20,
    "atr_period":      14,
    "atr_slope_period": 5,     # Bars to measure ATR slope
    "atr_sl_mult":     2.0,
    "atr_tp_mult":     4.0,
    "cooldown_bars":   5,      # Min bars between trades
    "risk_per_trade":  0.005,
}

SETTINGS = [
    {"key": "roc_period", "label": "ROC Period", "type": "int", "default": 10, "min": 3, "max": 30, "step": 1, "group": "Indicator Settings", "description": "Rate of Change lookback period for momentum measurement"},
    {"key": "sma_period", "label": "SMA Trend Filter Period", "type": "int", "default": 20, "min": 10, "max": 100, "step": 1, "group": "Indicator Settings", "description": "Simple Moving Average period for trend direction filter"},
    {"key": "atr_period", "label": "ATR Period", "type": "int", "default": 14, "min": 5, "max": 50, "step": 1, "group": "Indicator Settings", "description": "Average True Range period for volatility measurement"},
    {"key": "atr_slope_period", "label": "ATR Slope Period", "type": "int", "default": 5, "min": 2, "max": 15, "step": 1, "group": "Indicator Settings", "description": "Bars to measure ATR slope (rising = expanding volatility)"},
    {"key": "atr_sl_mult", "label": "ATR Stop-Loss Multiplier", "type": "float", "default": 2.0, "min": 0.5, "max": 5.0, "step": 0.1, "group": "Risk Management", "description": "ATR multiplier for stop-loss distance"},
    {"key": "atr_tp_mult", "label": "ATR Take-Profit Multiplier", "type": "float", "default": 4.0, "min": 1.0, "max": 12.0, "step": 0.5, "group": "Risk Management", "description": "ATR multiplier for take-profit distance"},
    {"key": "cooldown_bars", "label": "Cooldown Bars", "type": "int", "default": 5, "min": 0, "max": 20, "step": 1, "group": "Entry Rules", "description": "Minimum bars between consecutive trades to avoid overtrading"},
    {"key": "risk_per_trade", "label": "Risk Per Trade", "type": "float", "default": 0.005, "min": 0.001, "max": 0.05, "step": 0.001, "group": "Risk Management", "description": "Fraction of equity risked per trade"},
]


def _sma(values, period):
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


def _roc(bars, period):
    """Rate of Change: (close[i] - close[i-period]) / close[i-period] * 100"""
    n = len(bars)
    out = [0.0] * n
    for i in range(period, n):
        prev_close = bars[i - period]["close"]
        if prev_close > 0:
            out[i] = (bars[i]["close"] - prev_close) / prev_close * 100.0
    return out


class MomentumCrypto:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        n = len(bars)

        self.sma_vals = _sma([b["close"] for b in bars], self.s["sma_period"])
        self.roc_vals = _roc(bars, self.s["roc_period"])
        self.atr_vals = _atr(bars, self.s["atr_period"])

        # ATR slope: positive = expanding volatility
        slope_p = self.s["atr_slope_period"]
        self.atr_rising = [False] * n
        for i in range(slope_p, n):
            if self.atr_vals[i] > 0 and self.atr_vals[i - slope_p] > 0:
                self.atr_rising[i] = self.atr_vals[i] > self.atr_vals[i - slope_p]

        self._last_trade_bar = -999

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["roc_period"], s["sma_period"], s["atr_period"]) + s["atr_slope_period"] + 2
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        close = bar["close"]
        roc = self.roc_vals[i]
        roc_prev = self.roc_vals[i - 1]
        sma = self.sma_vals[i]

        # Exit: ROC flips sign (momentum reversal)
        for t in list(open_trades):
            if t["direction"] == "long" and roc < 0 and roc_prev >= 0:
                close_trade(t, i, close, "roc_reversal")
            elif t["direction"] == "short" and roc > 0 and roc_prev <= 0:
                close_trade(t, i, close, "roc_reversal")

        if len(open_trades) > 0:
            return

        # Cooldown check
        if i - self._last_trade_bar < s["cooldown_bars"]:
            return

        # Entry conditions
        atr_ok = self.atr_rising[i]

        if roc > 0 and close > sma and atr_ok:
            sl = close - s["atr_sl_mult"] * atr_val
            tp = close + s["atr_tp_mult"] * atr_val
            open_trade(i, "long", close, sl, tp)
            self._last_trade_bar = i

        elif roc < 0 and close < sma and atr_ok:
            sl = close + s["atr_sl_mult"] * atr_val
            tp = close - s["atr_tp_mult"] * atr_val
            open_trade(i, "short", close, sl, tp)
            self._last_trade_bar = i
