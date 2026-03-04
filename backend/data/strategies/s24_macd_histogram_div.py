"""
Strategy 24: MACD Histogram Divergence
=========================================
Inspired by: Gerald Appel (creator) + Alexander Elder (MACD histogram method).

Core idea: Elder's improvement — use MACD histogram (MACD - Signal) slope
changes and divergences instead of just line crossovers. Histogram
reversal from extreme = early signal before the classic MACD cross.

Entry: Histogram divergence with price (histogram makes higher low while
price makes lower low = bullish), confirmed by histogram turning positive.
Exit:  Histogram flips direction or approaches zero.

Markets : Universal
Timeframe: 1H / 4H / Daily
"""

DEFAULTS = {
    "fast_period":      12,
    "slow_period":      26,
    "signal_period":    9,
    "div_lookback":     30,     # Max bars between divergence pivots
    "sma_filter":       50,     # Trend filter
    "atr_period":       14,
    "atr_sl_mult":      2.0,
    "atr_tp_mult":      3.0,
    "risk_per_trade":   0.01,
}


SETTINGS = [
    {"key": "fast_period",    "label": "MACD Fast Period",     "type": "int",   "default": 12,   "min": 5,   "max": 30,  "step": 1,   "group": "Indicator Settings", "description": "Fast EMA period for MACD line calculation"},
    {"key": "slow_period",    "label": "MACD Slow Period",     "type": "int",   "default": 26,   "min": 15,  "max": 60,  "step": 1,   "group": "Indicator Settings", "description": "Slow EMA period for MACD line calculation"},
    {"key": "signal_period",  "label": "Signal Period",        "type": "int",   "default": 9,    "min": 3,   "max": 20,  "step": 1,   "group": "Indicator Settings", "description": "EMA period for the MACD signal line"},
    {"key": "div_lookback",   "label": "Divergence Lookback",  "type": "int",   "default": 30,   "min": 10,  "max": 80,  "step": 1,   "group": "Entry Rules",        "description": "Maximum bars between divergence pivot points"},
    {"key": "sma_filter",     "label": "SMA Trend Filter",     "type": "int",   "default": 50,   "min": 10,  "max": 200, "step": 1,   "group": "Filters",            "description": "SMA period used as a trend filter (long above, short below)"},
    {"key": "atr_period",     "label": "ATR Period",           "type": "int",   "default": 14,   "min": 5,   "max": 50,  "step": 1,   "group": "Risk Management",    "description": "Lookback period for Average True Range calculation"},
    {"key": "atr_sl_mult",    "label": "ATR SL Multiplier",    "type": "float", "default": 2.0,  "min": 0.5, "max": 5.0, "step": 0.1, "group": "Risk Management",    "description": "Stop-loss distance as a multiple of ATR"},
    {"key": "atr_tp_mult",    "label": "ATR TP Multiplier",    "type": "float", "default": 3.0,  "min": 0.5, "max": 8.0, "step": 0.1, "group": "Risk Management",    "description": "Take-profit distance as a multiple of ATR"},
    {"key": "risk_per_trade", "label": "Risk Per Trade",       "type": "float", "default": 0.01, "min": 0.001,"max": 0.05,"step": 0.001,"group": "Risk Management",   "description": "Fraction of account equity risked per trade (0.01 = 1%)"},
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


def _sma_bars(bars, period, key="close"):
    n = len(bars)
    out = [0.0] * n
    if period > n:
        return out
    s = sum(bars[j][key] for j in range(period))
    out[period - 1] = s / period
    for i in range(period, n):
        s += bars[i][key] - bars[i - period][key]
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


class MACDHistogramDiv:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        n = len(bars)
        closes = [b["close"] for b in bars]

        ema_fast = _ema(closes, self.s["fast_period"])
        ema_slow = _ema(closes, self.s["slow_period"])
        self.macd_line = [ema_fast[i] - ema_slow[i] for i in range(n)]
        self.signal_line = _ema(self.macd_line, self.s["signal_period"])
        self.histogram = [self.macd_line[i] - self.signal_line[i] for i in range(n)]

        self.sma = _sma_bars(bars, self.s["sma_filter"])
        self.atr_vals = _atr(bars, self.s["atr_period"])
        self.last_signal = -100

    def _find_hist_troughs(self, end_idx, count=5):
        """Find histogram troughs (local minima below zero)."""
        troughs = []
        for i in range(end_idx - 1, max(end_idx - self.s["div_lookback"] - 5, 2) - 1, -1):
            if (self.histogram[i] < 0 and
                    self.histogram[i] < self.histogram[i - 1] and
                    self.histogram[i] < self.histogram[i + 1]):
                troughs.append((i, self.histogram[i], self.bars[i]["low"]))
                if len(troughs) >= count:
                    break
        return troughs

    def _find_hist_peaks(self, end_idx, count=5):
        """Find histogram peaks (local maxima above zero)."""
        peaks = []
        for i in range(end_idx - 1, max(end_idx - self.s["div_lookback"] - 5, 2) - 1, -1):
            if (self.histogram[i] > 0 and
                    self.histogram[i] > self.histogram[i - 1] and
                    self.histogram[i] > self.histogram[i + 1]):
                peaks.append((i, self.histogram[i], self.bars[i]["high"]))
                if len(peaks) >= count:
                    break
        return peaks

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["slow_period"], s["signal_period"] + s["slow_period"],
                     s["sma_filter"], s["atr_period"]) + 5
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        close = bar["close"]
        hist = self.histogram[i]
        hist_prev = self.histogram[i - 1]

        # Exit: histogram reverses direction significantly
        for t in list(open_trades):
            if t["direction"] == "long" and hist < 0 and hist_prev >= 0:
                close_trade(t, i, close, "histogram_flip")
            elif t["direction"] == "short" and hist > 0 and hist_prev <= 0:
                close_trade(t, i, close, "histogram_flip")

        if len(open_trades) > 0:
            return

        if i - self.last_signal < 5:
            return

        # Bullish: histogram trough divergence + histogram turning up
        if hist > hist_prev and hist_prev < 0:
            troughs = self._find_hist_troughs(i, count=3)
            if len(troughs) >= 2:
                recent, prev_t = troughs[0], troughs[1]
                bar_diff = recent[0] - prev_t[0]
                if 3 <= bar_diff <= s["div_lookback"]:
                    # Histogram higher low + price lower low = bullish div
                    if recent[1] > prev_t[1] and recent[2] < prev_t[2]:
                        if close > self.sma[i]:
                            sl = close - atr_val * s["atr_sl_mult"]
                            tp = close + atr_val * s["atr_tp_mult"]
                            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
                            self.last_signal = i
                            return

        # Bearish: histogram peak divergence + histogram turning down
        if hist < hist_prev and hist_prev > 0:
            peaks = self._find_hist_peaks(i, count=3)
            if len(peaks) >= 2:
                recent, prev_p = peaks[0], peaks[1]
                bar_diff = recent[0] - prev_p[0]
                if 3 <= bar_diff <= s["div_lookback"]:
                    # Histogram lower high + price higher high = bearish div
                    if recent[1] < prev_p[1] and recent[2] > prev_p[2]:
                        if close < self.sma[i]:
                            sl = close + atr_val * s["atr_sl_mult"]
                            tp = close - atr_val * s["atr_tp_mult"]
                            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
                            self.last_signal = i
                            return
