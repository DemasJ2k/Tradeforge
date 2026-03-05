"""
Strategy 32: US500 RSI(2) Mean Reversion
========================================
Target : US500 (S&P 500 index) M30
Style  : Swing / intraday mean reversion using ultra-short RSI

Core idea: RSI with a period of 2 is extremely sensitive and identifies
short-term overbought/oversold extremes. Combined with an EMA trend filter,
this strategy buys oversold dips in uptrends and sells overbought rallies
in downtrends.

Entry:
  - RSI(2) < oversold AND close > EMA(50) -> Long (oversold in uptrend)
  - RSI(2) > overbought AND close < EMA(50) -> Short (overbought in downtrend)
  - No existing position

Exit:
  - TP at ATR * atr_tp_mult from entry
  - SL at ATR * atr_sl_mult from entry
  - Early exit when RSI crosses 50 (momentum exhaustion)
"""

# -- Settings (tunable via FlowrexAlgo UI) ---------------------------------
DEFAULTS = {
    "rsi_period":      2,
    "oversold":        10,
    "overbought":      90,
    "trend_ema":       50,
    "atr_period":      14,
    "atr_sl_mult":     1.5,
    "atr_tp_mult":     2.0,
    "risk_per_trade":  0.01,
}

SETTINGS = [
    {"key": "rsi_period",     "label": "RSI Period",           "type": "int",   "default": 2,    "min": 2,     "max": 10,   "step": 1,    "group": "Indicator Settings", "description": "Lookback period for the RSI calculation (2 = ultra-short-term)"},
    {"key": "oversold",       "label": "Oversold Threshold",   "type": "int",   "default": 10,   "min": 2,     "max": 30,   "step": 1,    "group": "Indicator Settings", "description": "RSI level below which the market is considered oversold"},
    {"key": "overbought",     "label": "Overbought Threshold", "type": "int",   "default": 90,   "min": 70,    "max": 98,   "step": 1,    "group": "Indicator Settings", "description": "RSI level above which the market is considered overbought"},
    {"key": "trend_ema",      "label": "Trend EMA Period",     "type": "int",   "default": 50,   "min": 10,    "max": 200,  "step": 1,    "group": "Indicator Settings", "description": "EMA period used as a trend filter; longs only above, shorts only below"},
    {"key": "atr_period",     "label": "ATR Period",           "type": "int",   "default": 14,   "min": 5,     "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "Lookback period for Average True Range calculation"},
    {"key": "atr_sl_mult",    "label": "ATR Stop-Loss Mult",   "type": "float", "default": 1.5,  "min": 0.5,   "max": 4.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Stop-loss distance as a multiple of ATR from entry price"},
    {"key": "atr_tp_mult",    "label": "ATR Take-Profit Mult", "type": "float", "default": 2.0,  "min": 1.0,   "max": 6.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Take-profit distance as a multiple of ATR from entry price"},
    {"key": "risk_per_trade", "label": "Risk Per Trade",       "type": "float", "default": 0.01, "min": 0.001, "max": 0.1,  "step": 0.001,"group": "Risk Management",    "description": "Fraction of account balance risked per trade"},
]


# -- Helpers ----------------------------------------------------------------
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
    if n < period + 1:
        return out
    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        ch = bars[i]["close"] - bars[i - 1]["close"]
        gains[i] = ch if ch > 0 else 0
        losses[i] = -ch if ch < 0 else 0
    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    if avg_loss > 0:
        rs = avg_gain / avg_loss
        out[period] = 100 - 100 / (1 + rs)
    else:
        out[period] = 100 if avg_gain > 0 else 50
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            out[i] = 100 - 100 / (1 + rs)
        else:
            out[i] = 100 if avg_gain > 0 else 50
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


# -- Strategy Logic ---------------------------------------------------------
class US500Rsi2MeanReversion:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.atr_values = _atr(bars, self.s["atr_period"])
        self.rsi_values = _rsi(bars, self.s["rsi_period"])
        self.ema_values = _ema(bars, self.s["trend_ema"])

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["atr_period"] + 1, s["trend_ema"], s["rsi_period"] + 1)
        if i < warmup:
            return

        atr_val = self.atr_values[i]
        rsi_val = self.rsi_values[i]
        ema_val = self.ema_values[i]

        if atr_val <= 0 or ema_val <= 0:
            return

        close = bar["close"]

        # -- Manage open positions: early exit on RSI crossing 50 --
        if len(open_trades) > 0:
            for t in list(open_trades):
                if t["direction"] == "long" and rsi_val >= 50:
                    close_trade(t, i, close, "rsi_cross_50")
                elif t["direction"] == "short" and rsi_val <= 50:
                    close_trade(t, i, close, "rsi_cross_50")
            return

        # -- LONG: oversold in uptrend --
        if rsi_val < s["oversold"] and close > ema_val:
            sl = close - atr_val * s["atr_sl_mult"]
            tp = close + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # -- SHORT: overbought in downtrend --
        elif rsi_val > s["overbought"] and close < ema_val:
            sl = close + atr_val * s["atr_sl_mult"]
            tp = close - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
