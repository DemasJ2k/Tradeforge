"""
Strategy 28: Volatility Event Breakout
========================================
Fixed: converted from legacy module-level init()/on_bar() pattern to class.
Fixed: open_trade() call signature (6 args: i, direction, entry, sl, tp, risk).

Detects sudden volatility spikes (ATR > 1.5x its own SMA) and trades
the breakout direction using a channel of recent high/low.

Entry:
  1. ATR(14) exceeds atr_spike_mult * SMA(ATR, 50)  ->  volatility event
  2. Price breaks above 10-bar high  ->  LONG
  3. Price breaks below 10-bar low   ->  SHORT

Exit: SL = 2.0 * ATR, TP = 3.5 * ATR

Markets : Universal (indices, forex, crypto)
Timeframe: M5-H1
"""

import math

DEFAULTS = {
    "atr_period":         14,
    "atr_avg_period":     50,
    "atr_spike_mult":     1.5,
    "breakout_lookback":  10,
    "atr_sl_mult":        2.0,
    "atr_tp_mult":        3.5,
    "cooldown_bars":      5,
    "max_concurrent":     1,
    "risk_per_trade":     0.01,
}

SETTINGS = [
    {"key": "atr_period",       "label": "ATR Period",              "type": "int",   "default": 14,   "min": 5,    "max": 50,   "step": 1,    "group": "Volatility",  "description": "Lookback period for Average True Range"},
    {"key": "atr_avg_period",   "label": "ATR Average Period",      "type": "int",   "default": 50,   "min": 10,   "max": 200,  "step": 1,    "group": "Volatility",  "description": "SMA period applied to ATR to determine baseline volatility"},
    {"key": "atr_spike_mult",   "label": "ATR Spike Multiplier",    "type": "float", "default": 1.5,  "min": 1.1,  "max": 4.0,  "step": 0.1,  "group": "Volatility",  "description": "ATR must exceed its average by this multiple to flag a volatility event"},
    {"key": "breakout_lookback","label": "Breakout Lookback Bars",  "type": "int",   "default": 10,   "min": 3,    "max": 50,   "step": 1,    "group": "Breakout",    "description": "Number of bars used to define the high/low breakout channel"},
    {"key": "atr_sl_mult",      "label": "SL (ATR mult)",           "type": "float", "default": 2.0,  "min": 0.5,  "max": 5.0,  "step": 0.1,  "group": "Risk",        "description": "Stop-loss distance as a multiple of ATR"},
    {"key": "atr_tp_mult",      "label": "TP (ATR mult)",           "type": "float", "default": 3.5,  "min": 1.0,  "max": 10.0, "step": 0.1,  "group": "Risk",        "description": "Take-profit distance as a multiple of ATR"},
    {"key": "cooldown_bars",    "label": "Cooldown Bars",           "type": "int",   "default": 5,    "min": 0,    "max": 30,   "step": 1,    "group": "Risk",        "description": "Minimum bars between consecutive trades"},
    {"key": "max_concurrent",   "label": "Max Open Trades",         "type": "int",   "default": 1,    "min": 1,    "max": 5,    "step": 1,    "group": "Risk",        "description": "Maximum simultaneous open positions"},
    {"key": "risk_per_trade",   "label": "Risk Per Trade",          "type": "float", "default": 0.01, "min": 0.001,"max": 0.1,  "step": 0.001,"group": "Risk Management", "description": "Fraction of account equity risked per trade"},
]


def _wilder_atr(bars, period):
    n = len(bars)
    tr = [0.0] * n
    atr = [0.0] * n
    for i in range(1, n):
        hl = bars[i]["high"] - bars[i]["low"]
        hc = abs(bars[i]["high"] - bars[i - 1]["close"])
        lc = abs(bars[i]["low"] - bars[i - 1]["close"])
        tr[i] = max(hl, hc, lc)
    if period > 0 and n > period:
        atr[period] = sum(tr[1:period + 1]) / period
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def _sma_array(values, period):
    """SMA on a list of floats."""
    n = len(values)
    out = [0.0] * n
    if period > n:
        return out
    s = 0.0
    for i in range(n):
        s += values[i]
        if i >= period:
            s -= values[i - period]
        if i >= period - 1:
            out[i] = s / period
    return out


class NewsEventGuard:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.atr_vals = _wilder_atr(bars, self.s["atr_period"])
        self.atr_avg = _sma_array(self.atr_vals, self.s["atr_avg_period"])
        self.last_trade_bar = -999

    def on_bar(self, i, bar):
        s = self.s
        warmup = s["atr_period"] + s["atr_avg_period"] + s["breakout_lookback"]
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        avg_val = self.atr_avg[i]
        if atr_val <= 0 or avg_val <= 0:
            return

        # 1. Volatility event detection
        if atr_val < s["atr_spike_mult"] * avg_val:
            return

        # 2. Position / cooldown checks
        if len(open_trades) >= s["max_concurrent"]:
            return
        if i - self.last_trade_bar < s["cooldown_bars"]:
            return

        # 3. Compute breakout channel
        lb = s["breakout_lookback"]
        highest_high = -math.inf
        lowest_low = math.inf
        for j in range(i - lb, i):
            highest_high = max(highest_high, self.bars[j]["high"])
            lowest_low = min(lowest_low, self.bars[j]["low"])

        close = bar["close"]
        high = bar["high"]
        low = bar["low"]

        sl_dist = atr_val * s["atr_sl_mult"]
        tp_dist = atr_val * s["atr_tp_mult"]

        # 4. Breakout entry
        if high > highest_high:
            sl = close - sl_dist
            tp = close + tp_dist
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
            self.last_trade_bar = i

        elif low < lowest_low:
            sl = close + sl_dist
            tp = close - tp_dist
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
            self.last_trade_bar = i
