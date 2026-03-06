"""
Strategy 23: Awesome Oscillator Saucer (Simplified)
=====================================================
Inspired by: Bill Williams — "Trading Chaos" author, creator of AO.

Core idea: The Awesome Oscillator = SMA(5) of median price − SMA(34) of
median price.

Signals (priority order):
  - Saucer (simplified): AO rising above zero → long, AO falling below zero → short.
    Only requires ao[i] > ao[i-1] with ao[i] on the correct side of zero.
  - Zero Line Cross: AO crosses above/below zero — simplest and most frequent signal.

Twin Peaks removed (too rare, overly complex).
AO zero-cross exit removed — ATR-based SL/TP handles all exits.

Markets : Universal
Timeframe: 15m / 1H / 4H / Daily
"""

DEFAULTS = {
    "ao_fast":          5,
    "ao_slow":          34,
    "use_saucer":       True,
    "use_zero_cross":   True,   # Enabled — simplest, most frequent AO signal
    "atr_period":       14,
    "atr_sl_mult":      1.5,    # Tighter SL for better R:R
    "atr_tp_mult":      3.0,
    "risk_per_trade":   0.01,
}


SETTINGS = [
    {"key": "ao_fast",        "label": "AO Fast Period",       "type": "int",   "default": 5,    "min": 2,   "max": 20,  "step": 1,   "group": "Indicator Settings", "description": "Fast SMA period for Awesome Oscillator median price"},
    {"key": "ao_slow",        "label": "AO Slow Period",       "type": "int",   "default": 34,   "min": 10,  "max": 60,  "step": 1,   "group": "Indicator Settings", "description": "Slow SMA period for Awesome Oscillator median price"},
    {"key": "use_saucer",     "label": "Enable Saucer Signal", "type": "bool",  "default": True,                                       "group": "Entry Rules",        "description": "Trade when AO momentum is increasing on the correct side of zero"},
    {"key": "use_zero_cross", "label": "Enable Zero Cross",    "type": "bool",  "default": True,                                       "group": "Entry Rules",        "description": "Trade AO zero-line crossovers — simplest momentum signal"},
    {"key": "atr_period",     "label": "ATR Period",           "type": "int",   "default": 14,   "min": 5,   "max": 50,  "step": 1,   "group": "Risk Management",    "description": "Lookback period for Average True Range calculation"},
    {"key": "atr_sl_mult",    "label": "ATR SL Multiplier",    "type": "float", "default": 1.5,  "min": 0.5, "max": 5.0, "step": 0.1, "group": "Risk Management",    "description": "Stop-loss distance as a multiple of ATR"},
    {"key": "atr_tp_mult",    "label": "ATR TP Multiplier",    "type": "float", "default": 3.0,  "min": 0.5, "max": 8.0, "step": 0.1, "group": "Risk Management",    "description": "Take-profit distance as a multiple of ATR"},
    {"key": "risk_per_trade", "label": "Risk Per Trade",       "type": "float", "default": 0.01, "min": 0.001,"max": 0.05,"step": 0.001,"group": "Risk Management",   "description": "Fraction of account equity risked per trade (0.01 = 1%)"},
]


def _sma_vals(values, period):
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


class AOSaucer:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        n = len(bars)

        median = [(bars[i]["high"] + bars[i]["low"]) / 2.0 for i in range(n)]
        sma_fast = _sma_vals(median, self.s["ao_fast"])
        sma_slow = _sma_vals(median, self.s["ao_slow"])
        self.ao = [sma_fast[i] - sma_slow[i] for i in range(n)]
        self.atr_vals = _atr(bars, self.s["atr_period"])

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["ao_slow"], s["atr_period"]) + 2
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        if len(open_trades) > 0:
            return

        close = bar["close"]
        signal_long = False
        signal_short = False

        # Saucer (simplified): AO rising on the correct side of zero
        if s["use_saucer"]:
            if self.ao[i] > 0 and self.ao[i] > self.ao[i - 1]:
                signal_long = True
            elif self.ao[i] < 0 and self.ao[i] < self.ao[i - 1]:
                signal_short = True

        # Zero Line Cross: AO crosses above or below zero
        if not signal_long and not signal_short and s["use_zero_cross"]:
            if self.ao[i] > 0 and self.ao[i - 1] <= 0:
                signal_long = True
            elif self.ao[i] < 0 and self.ao[i - 1] >= 0:
                signal_short = True

        if signal_long:
            sl = close - atr_val * s["atr_sl_mult"]
            tp = close + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
        elif signal_short:
            sl = close + atr_val * s["atr_sl_mult"]
            tp = close - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
