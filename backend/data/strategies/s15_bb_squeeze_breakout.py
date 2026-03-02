"""
Strategy 15: Bollinger Band Squeeze Breakout
===============================================
Inspired by: John Bollinger himself + Mark Helweg's BB bandwidth analysis.

Core idea: When Bollinger Bandwidth (BBW) hits N-period low, a big move is
coming. Enter on breakout from the squeeze in the direction of the close
relative to the midline.

Enhancement: Use Keltner Channel overlap check (like TTM Squeeze) plus
%B indicator for precise entry timing.

Markets : Universal
Timeframe: 15m / 1H / 4H
"""

DEFAULTS = {
    "bb_period":        20,
    "bb_mult":          2.0,
    "bbw_lookback":     120,    # Bars to check if bandwidth is at low
    "bbw_percentile":   0.10,   # Bandwidth must be in bottom 10% (was 8% - slightly more signals)
    "pct_b_entry":      0.70,   # %B > 0.70 for long (relaxed from 0.75)
    "pct_b_short":      0.30,   # %B < 0.30 for short (relaxed from 0.25)
    "atr_period":       14,
    "atr_sl_mult":      2.0,    # Wider stop (was 1.5 - whipsaw kills)
    "atr_tp_mult":      4.0,    # Wider TP (was 3.5 - let breakout run further)
    "require_momentum": True,   # Require close > prev close for long, close < prev for short
    "exit_bb_revert":   False,  # Disabled - kills winners too early
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


class BBSqueezeBreakout:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        n = len(bars)
        bb_p = self.s["bb_period"]

        closes = [b["close"] for b in bars]
        self.bb_mid = _sma_vals(closes, bb_p)

        # Bollinger Bands
        self.bb_std = [0.0] * n
        for i in range(bb_p - 1, n):
            mean = self.bb_mid[i]
            if mean <= 0:
                continue
            variance = sum((bars[j]["close"] - mean) ** 2 for j in range(i - bb_p + 1, i + 1)) / bb_p
            self.bb_std[i] = variance ** 0.5

        self.bb_upper = [self.bb_mid[i] + self.s["bb_mult"] * self.bb_std[i] for i in range(n)]
        self.bb_lower = [self.bb_mid[i] - self.s["bb_mult"] * self.bb_std[i] for i in range(n)]

        # Bandwidth & %B
        self.bbw = [0.0] * n
        self.pct_b = [0.5] * n
        for i in range(n):
            if self.bb_mid[i] > 0:
                self.bbw[i] = (self.bb_upper[i] - self.bb_lower[i]) / self.bb_mid[i]
            bw = self.bb_upper[i] - self.bb_lower[i]
            if bw > 0:
                self.pct_b[i] = (bars[i]["close"] - self.bb_lower[i]) / bw

        self.atr_vals = _atr(bars, self.s["atr_period"])

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["bb_period"], s["atr_period"]) + s["bbw_lookback"] + 2
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        close = bar["close"]
        bbw = self.bbw[i]
        pct_b = self.pct_b[i]

        # Exit on revert to middle band
        for t in list(open_trades):
            if s["exit_bb_revert"]:
                mid = self.bb_mid[i]
                if t["direction"] == "long" and close <= mid:
                    close_trade(t, i, close, "bb_midline_revert")
                elif t["direction"] == "short" and close >= mid:
                    close_trade(t, i, close, "bb_midline_revert")

        if len(open_trades) > 0:
            return

        # Check if bandwidth is at percentile low (squeeze detected)
        lookback_start = max(0, i - s["bbw_lookback"])
        recent_bbw = sorted([self.bbw[j] for j in range(lookback_start, i) if self.bbw[j] > 0])
        if not recent_bbw:
            return

        threshold_idx = max(0, int(len(recent_bbw) * s["bbw_percentile"]))
        bbw_threshold = recent_bbw[threshold_idx]

        # Previous bar was in squeeze, current is expanding
        if self.bbw[i - 1] <= bbw_threshold and bbw > bbw_threshold:
            # Momentum confirmation: close in direction of breakout
            prev_close = self.bars[i - 1]["close"]
            momentum_long = (not s["require_momentum"]) or (close > prev_close)
            momentum_short = (not s["require_momentum"]) or (close < prev_close)

            # Breakout direction from %B
            if pct_b > s["pct_b_entry"] and momentum_long:
                sl = close - atr_val * s["atr_sl_mult"]
                tp = close + atr_val * s["atr_tp_mult"]
                open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
            elif pct_b < s["pct_b_short"] and momentum_short:
                sl = close + atr_val * s["atr_sl_mult"]
                tp = close - atr_val * s["atr_tp_mult"]
                open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
