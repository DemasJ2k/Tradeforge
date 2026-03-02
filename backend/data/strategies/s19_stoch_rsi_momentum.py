"""
Strategy 19: Stochastic RSI Momentum
=======================================
Inspired by: Tushar Chande and Stanley Kroll — creators of Stochastic RSI.

Core idea: Apply Stochastic formula to RSI values instead of price, creating
an oscillator that cycles faster than regular RSI. Catches momentum bursts.

Stoch RSI = (RSI - Lowest RSI over N) / (Highest RSI over N - Lowest RSI over N)
K line = SMA(StochRSI, 3)
D line = SMA(K, 3)

Entry: K crosses above D in oversold zone (< 20) = Long
       K crosses below D in overbought zone (> 80) = Short
Exit:  Opposite cross or opposing zone reached.

Markets : Universal
Timeframe: 5m / 15m / 1H
"""

DEFAULTS = {
    "rsi_period":       14,
    "stoch_period":     14,
    "k_smooth":         3,
    "d_smooth":         3,
    "ob_level":         80,
    "os_level":         20,
    "ema_trend_period": 50,     # Trend filter
    "atr_period":       14,
    "atr_sl_mult":      1.5,
    "atr_tp_mult":      2.5,
    "risk_per_trade":   0.01,
}


def _rsi(bars, period):
    n = len(bars)
    out = [50.0] * n
    if period + 1 > n:
        return out
    gains = losses = 0.0
    for j in range(1, period + 1):
        diff = bars[j]["close"] - bars[j - 1]["close"]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period + 1, n):
        diff = bars[i]["close"] - bars[i - 1]["close"]
        g = max(diff, 0)
        l = max(-diff, 0)
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


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


class StochRSIMomentum:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        n = len(bars)

        rsi = _rsi(bars, self.s["rsi_period"])
        sp = self.s["stoch_period"]

        # Stochastic RSI
        stoch_rsi = [0.0] * n
        for i in range(sp - 1, n):
            start = i - sp + 1
            hi = max(rsi[j] for j in range(start, i + 1))
            lo = min(rsi[j] for j in range(start, i + 1))
            if hi - lo > 0:
                stoch_rsi[i] = 100 * (rsi[i] - lo) / (hi - lo)
            else:
                stoch_rsi[i] = 50.0

        self.k_line = _sma_vals(stoch_rsi, self.s["k_smooth"])
        self.d_line = _sma_vals(self.k_line, self.s["d_smooth"])
        self.ema_trend = _ema([b["close"] for b in bars], self.s["ema_trend_period"])
        self.atr_vals = _atr(bars, self.s["atr_period"])

    def on_bar(self, i, bar):
        s = self.s
        warmup = s["rsi_period"] + s["stoch_period"] + s["k_smooth"] + s["d_smooth"] + 5
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        close = bar["close"]
        k = self.k_line[i]
        k_prev = self.k_line[i - 1]
        d = self.d_line[i]
        d_prev = self.d_line[i - 1]

        # Exit on opposing zone
        for t in list(open_trades):
            if t["direction"] == "long" and k > s["ob_level"] and k < k_prev:
                close_trade(t, i, close, "stoch_rsi_ob_exit")
            elif t["direction"] == "short" and k < s["os_level"] and k > k_prev:
                close_trade(t, i, close, "stoch_rsi_os_exit")

        if len(open_trades) > 0:
            return

        # K crosses above D in oversold zone → Long
        if k > d and k_prev <= d_prev and k < s["os_level"]:
            if close > self.ema_trend[i]:  # Trend filter (long only in uptrend)
                sl = close - atr_val * s["atr_sl_mult"]
                tp = close + atr_val * s["atr_tp_mult"]
                open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # K crosses below D in overbought zone → Short
        elif k < d and k_prev >= d_prev and k > s["ob_level"]:
            if close < self.ema_trend[i]:
                sl = close + atr_val * s["atr_sl_mult"]
                tp = close - atr_val * s["atr_tp_mult"]
                open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
