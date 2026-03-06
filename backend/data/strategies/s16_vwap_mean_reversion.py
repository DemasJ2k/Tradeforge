"""
Strategy 16: Donchian Channel Breakout
========================================
Replaces VWAP Mean Reversion (PF=0.24-0.29, worst performer).

Core idea: Donchian Channel (20-period high/low).
  Long : close breaks above 20-bar high
  Short: close breaks below 20-bar low
  SL = channel midline, TP = 2x channel half-width from entry

Markets : Universal (indices, forex, crypto)
Timeframe: M5-H1
"""

DEFAULTS = {
    "donchian_period":  20,
    "tp_mult":          2.0,
    "risk_per_trade":   0.01,
}

SETTINGS = [
    {"key": "donchian_period", "label": "Donchian Period",         "type": "int",   "default": 20,   "min": 5,    "max": 100,  "step": 1,    "group": "Indicator Settings", "description": "Lookback period for Donchian Channel high/low"},
    {"key": "tp_mult",         "label": "TP Channel Width Mult",   "type": "float", "default": 2.0,  "min": 1.0,  "max": 5.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Take-profit distance as a multiple of channel half-width"},
    {"key": "risk_per_trade",  "label": "Risk Per Trade",          "type": "float", "default": 0.01, "min": 0.001,"max": 0.1,  "step": 0.001,"group": "Risk Management",    "description": "Fraction of account equity risked per trade"},
]


class VWAPMeanReversion:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        n = len(bars)
        dp = self.s["donchian_period"]

        # Precompute Donchian high/low (using bars [i-dp .. i-1], excluding current bar)
        self.don_hi = [0.0] * n
        self.don_lo = [0.0] * n
        for i in range(dp, n):
            self.don_hi[i] = max(bars[j]["high"] for j in range(i - dp, i))
            self.don_lo[i] = min(bars[j]["low"] for j in range(i - dp, i))

    def on_bar(self, i, bar):
        s = self.s
        dp = s["donchian_period"]
        if i < dp + 1:
            return

        if len(open_trades) > 0:
            return

        close = bar["close"]
        don_hi = self.don_hi[i]
        don_lo = self.don_lo[i]
        half_width = (don_hi - don_lo) / 2.0
        midline = (don_hi + don_lo) / 2.0

        if half_width <= 0:
            return

        # Long: close breaks above previous Donchian high
        if close > don_hi:
            sl = midline
            tp = close + s["tp_mult"] * half_width
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # Short: close breaks below previous Donchian low
        elif close < don_lo:
            sl = midline
            tp = close - s["tp_mult"] * half_width
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
