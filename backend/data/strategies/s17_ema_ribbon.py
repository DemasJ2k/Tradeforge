"""
Strategy 17: EMA Ribbon Momentum
==================================
Inspired by: Guppy Multiple Moving Average (GMMA) by Daryl Guppy.

Core idea: Use a "ribbon" of EMAs (8,13,21,34,55,89). When short-term EMAs
fan out above long-term EMAs → strong bullish momentum. Fan below → bearish.

Entry: All short EMAs > all long EMAs (or vice versa) + price closes beyond
       the ribbon. Expansion (spread increasing) confirms momentum.
Exit:  Short EMAs start crossing back into long EMAs.

Markets : Universal
Timeframe: 15m / 1H / 4H / Daily
"""

DEFAULTS = {
    "short_emas":       [8, 13, 21],
    "long_emas":        [34, 55, 89],
    "expansion_bars":   3,          # Min bars of expanding ribbon
    "atr_period":       14,
    "atr_sl_mult":      2.0,
    "atr_tp_mult":      3.5,
    "trail_ema":        21,         # Trailing exit EMA
    "risk_per_trade":   0.01,
}


SETTINGS = [
    {"key": "short_emas",       "label": "Short EMA Periods",     "type": "text",  "default": "[8, 13, 21]",                                  "group": "Indicator Settings", "description": "List of short EMA periods forming the fast ribbon"},
    {"key": "long_emas",        "label": "Long EMA Periods",      "type": "text",  "default": "[34, 55, 89]",                                 "group": "Indicator Settings", "description": "List of long EMA periods forming the slow ribbon"},
    {"key": "expansion_bars",   "label": "Expansion Bars",        "type": "int",   "default": 3,    "min": 1,    "max": 20,   "step": 1,   "group": "Entry Rules",        "description": "Minimum consecutive bars of ribbon expansion to confirm trend"},
    {"key": "atr_period",       "label": "ATR Period",            "type": "int",   "default": 14,   "min": 5,    "max": 50,   "step": 1,   "group": "Risk Management",    "description": "ATR lookback period for stop/target sizing"},
    {"key": "atr_sl_mult",      "label": "ATR Stop-Loss Mult",   "type": "float", "default": 2.0,  "min": 0.5,  "max": 5.0,  "step": 0.1, "group": "Risk Management",    "description": "ATR multiplier for stop-loss distance"},
    {"key": "atr_tp_mult",      "label": "ATR Take-Profit Mult", "type": "float", "default": 3.5,  "min": 0.5,  "max": 10.0, "step": 0.1, "group": "Risk Management",    "description": "ATR multiplier for take-profit distance"},
    {"key": "trail_ema",        "label": "Trailing Exit EMA",    "type": "int",   "default": 21,   "min": 5,    "max": 100,  "step": 1,   "group": "Exit Rules",         "description": "EMA period used for trailing exit (close below = exit long)"},
    {"key": "risk_per_trade",   "label": "Risk Per Trade",        "type": "float", "default": 0.01, "min": 0.001,"max": 0.05, "step": 0.001,"group": "Risk Management",   "description": "Fraction of account equity risked per trade"},
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


class EMARibbon:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        n = len(bars)
        closes = [b["close"] for b in bars]

        self.short_ema_vals = [_ema(closes, p) for p in self.s["short_emas"]]
        self.long_ema_vals = [_ema(closes, p) for p in self.s["long_emas"]]
        self.trail_ema = _ema(closes, self.s["trail_ema"])
        self.atr_vals = _atr(bars, self.s["atr_period"])

        # Ribbon spread: average short EMA - average long EMA
        self.spread = [0.0] * n
        for i in range(n):
            short_avg = sum(e[i] for e in self.short_ema_vals) / max(len(self.short_ema_vals), 1)
            long_avg = sum(e[i] for e in self.long_ema_vals) / max(len(self.long_ema_vals), 1)
            self.spread[i] = short_avg - long_avg

    def _all_short_above_long(self, i):
        min_short = min(e[i] for e in self.short_ema_vals)
        max_long = max(e[i] for e in self.long_ema_vals)
        return min_short > max_long

    def _all_short_below_long(self, i):
        max_short = max(e[i] for e in self.short_ema_vals)
        min_long = min(e[i] for e in self.long_ema_vals)
        return max_short < min_long

    def _is_expanding(self, i, direction):
        """Check if spread has been increasing for expansion_bars."""
        bars_needed = self.s["expansion_bars"]
        if i < bars_needed:
            return False
        for j in range(1, bars_needed + 1):
            if direction == "up" and self.spread[i - j + 1] <= self.spread[i - j]:
                return False
            elif direction == "down" and self.spread[i - j + 1] >= self.spread[i - j]:
                return False
        return True

    def on_bar(self, i, bar):
        s = self.s
        max_period = max(s["long_emas"]) if s["long_emas"] else 89
        warmup = max_period + s["expansion_bars"] + 3
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        close = bar["close"]
        trail = self.trail_ema[i]

        # Exit: price crosses back through trail EMA
        for t in list(open_trades):
            if t["direction"] == "long" and close < trail:
                close_trade(t, i, close, "ema_trail_exit")
            elif t["direction"] == "short" and close > trail:
                close_trade(t, i, close, "ema_trail_exit")

        if len(open_trades) > 0:
            return

        # Long: all short EMAs above all long EMAs + expanding + close above ribbon
        if self._all_short_above_long(i) and self._is_expanding(i, "up"):
            top_short = max(e[i] for e in self.short_ema_vals)
            if close > top_short:
                sl = close - atr_val * s["atr_sl_mult"]
                tp = close + atr_val * s["atr_tp_mult"]
                open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # Short: all short EMAs below all long EMAs + expanding down
        elif self._all_short_below_long(i) and self._is_expanding(i, "down"):
            bottom_short = min(e[i] for e in self.short_ema_vals)
            if close < bottom_short:
                sl = close + atr_val * s["atr_sl_mult"]
                tp = close - atr_val * s["atr_tp_mult"]
                open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
