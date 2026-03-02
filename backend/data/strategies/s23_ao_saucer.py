"""
Strategy 23: Awesome Oscillator Saucer
========================================
Inspired by: Bill Williams — "Trading Chaos" author, creator of AO.

Core idea: The Awesome Oscillator = SMA(5) of median price − SMA(34) of
median price. The "Saucer" pattern = AO is above zero, dips (one red bar),
then turns green again → continuation signal.

Additional Williams signals:
  - Twin Peaks: Two AO peaks below zero with a bar between → bullish
  - Zero Line Cross: AO crosses above/below zero

Markets : Universal
Timeframe: 15m / 1H / 4H / Daily
"""

DEFAULTS = {
    "ao_fast":          5,
    "ao_slow":          34,
    "use_saucer":       True,
    "use_twin_peaks":   True,
    "use_zero_cross":   False,  # Disabled — too many false signals in chop
    "atr_period":       14,
    "atr_sl_mult":      2.0,    # Widened from 1.5 — momentum needs room
    "atr_tp_mult":      3.0,    # Widened from 2.5
    "risk_per_trade":   0.01,
}


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

    def _saucer_bull(self, i):
        """Bullish saucer: AO > 0, ao[i-2] > ao[i-1] (dip), ao[i] > ao[i-1] (recovery)."""
        if i < 3:
            return False
        return (self.ao[i] > 0 and self.ao[i - 1] > 0 and self.ao[i - 2] > 0 and
                self.ao[i - 2] > self.ao[i - 1] and self.ao[i] > self.ao[i - 1])

    def _saucer_bear(self, i):
        """Bearish saucer: AO < 0, dip up then resume down."""
        if i < 3:
            return False
        return (self.ao[i] < 0 and self.ao[i - 1] < 0 and self.ao[i - 2] < 0 and
                self.ao[i - 2] < self.ao[i - 1] and self.ao[i] < self.ao[i - 1])

    def _twin_peaks_bull(self, i):
        """Twin Peaks bullish: two AO valleys below zero, second higher than first."""
        if i < 10:
            return False
        # Find two recent valleys below zero
        valleys = []
        for j in range(i - 1, max(i - 50, 2) - 1, -1):
            is_valley = (self.ao[j] < 0 and self.ao[j] < self.ao[j - 1])
            if is_valley and j + 1 <= i:
                is_valley = is_valley and (self.ao[j] < self.ao[j + 1])
            if is_valley:
                valleys.append((j, self.ao[j]))
                if len(valleys) == 2:
                    break
        if len(valleys) < 2:
            return False
        # Second valley (more recent) should be higher (less negative) than first
        return valleys[0][1] > valleys[1][1]

    def _twin_peaks_bear(self, i):
        """Twin Peaks bearish: two AO peaks above zero, second lower than first."""
        if i < 10:
            return False
        peaks = []
        for j in range(i - 1, max(i - 50, 2) - 1, -1):
            is_peak = (self.ao[j] > 0 and self.ao[j] > self.ao[j - 1])
            if is_peak and j + 1 <= i:
                is_peak = is_peak and (self.ao[j] > self.ao[j + 1])
            if is_peak:
                peaks.append((j, self.ao[j]))
                if len(peaks) == 2:
                    break
        if len(peaks) < 2:
            return False
        return peaks[0][1] < peaks[1][1]

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["ao_slow"], s["atr_period"]) + 5
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        close = bar["close"]

        # Exit: AO flips to opposite side of zero
        for t in list(open_trades):
            if t["direction"] == "long" and self.ao[i] < 0 and self.ao[i - 1] >= 0:
                close_trade(t, i, close, "ao_zero_cross_exit")
            elif t["direction"] == "short" and self.ao[i] > 0 and self.ao[i - 1] <= 0:
                close_trade(t, i, close, "ao_zero_cross_exit")

        if len(open_trades) > 0:
            return

        signal_long = False
        signal_short = False

        # Check signals in priority order
        if s["use_saucer"]:
            if self._saucer_bull(i):
                signal_long = True
            elif self._saucer_bear(i):
                signal_short = True

        if not signal_long and not signal_short and s["use_twin_peaks"]:
            if self._twin_peaks_bull(i):
                signal_long = True
            elif self._twin_peaks_bear(i):
                signal_short = True

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
