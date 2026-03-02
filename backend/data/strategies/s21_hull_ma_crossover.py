"""
Strategy 21: Hull Moving Average Crossover
=============================================
Inspired by: Alan Hull — inventor of Hull MA (HMA), designed to reduce lag.

HMA = WMA(2*WMA(n/2) - WMA(n), sqrt(n))

Core idea: HMA reacts faster than SMA/EMA while staying smooth. Use dual HMA
crossover (fast HMA crosses slow HMA) for momentum entries with minimal lag.

Markets : Universal
Timeframe: 15m / 1H / 4H
"""

DEFAULTS = {
    "fast_period":      9,
    "slow_period":      21,
    "atr_period":       14,
    "atr_sl_mult":      2.0,
    "atr_tp_mult":      3.0,
    "adx_period":       14,
    "adx_threshold":    20,
    "risk_per_trade":   0.01,
}


def _wma(values, period):
    """Weighted Moving Average."""
    n = len(values)
    out = [0.0] * n
    if period > n:
        return out
    denom = period * (period + 1) / 2
    for i in range(period - 1, n):
        s = sum(values[i - period + 1 + j] * (j + 1) for j in range(period))
        out[i] = s / denom
    return out


def _hma(values, period):
    """Hull Moving Average."""
    n = len(values)
    half = max(int(period / 2), 1)
    sqrt_p = max(int(period ** 0.5), 1)
    wma_half = _wma(values, half)
    wma_full = _wma(values, period)
    diff = [2 * wma_half[i] - wma_full[i] for i in range(n)]
    return _wma(diff, sqrt_p)


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


def _adx(bars, period):
    n = len(bars)
    out = [0.0] * n
    if 2 * period + 1 > n:
        return out
    dmp = [0.0] * n
    dmm = [0.0] * n
    trs = [0.0] * n
    for i in range(1, n):
        h = bars[i]["high"] - bars[i - 1]["high"]
        l = bars[i - 1]["low"] - bars[i]["low"]
        dmp[i] = h if h > l and h > 0 else 0.0
        dmm[i] = l if l > h and l > 0 else 0.0
        trs[i] = max(bars[i]["high"] - bars[i]["low"],
                      abs(bars[i]["high"] - bars[i - 1]["close"]),
                      abs(bars[i]["low"] - bars[i - 1]["close"]))
    sm_tr = sum(trs[1:period + 1])
    sm_dp = sum(dmp[1:period + 1])
    sm_dm = sum(dmm[1:period + 1])
    dx_list = []
    for i in range(period, n):
        if i > period:
            sm_tr = sm_tr - sm_tr / period + trs[i]
            sm_dp = sm_dp - sm_dp / period + dmp[i]
            sm_dm = sm_dm - sm_dm / period + dmm[i]
        di_p = 100 * sm_dp / sm_tr if sm_tr > 0 else 0
        di_m = 100 * sm_dm / sm_tr if sm_tr > 0 else 0
        ds = di_p + di_m
        dx = 100 * abs(di_p - di_m) / ds if ds > 0 else 0
        dx_list.append(dx)
        if len(dx_list) == period:
            out[i] = sum(dx_list) / period
        elif len(dx_list) > period:
            out[i] = (out[i - 1] * (period - 1) + dx) / period
    return out


class HullMACrossover:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        closes = [b["close"] for b in bars]

        self.fast_hma = _hma(closes, self.s["fast_period"])
        self.slow_hma = _hma(closes, self.s["slow_period"])
        self.atr_vals = _atr(bars, self.s["atr_period"])
        self.adx_vals = _adx(bars, self.s["adx_period"])

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["slow_period"], s["adx_period"] * 2, s["atr_period"]) + 5
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        close = bar["close"]
        fast = self.fast_hma[i]
        fast_prev = self.fast_hma[i - 1]
        slow = self.slow_hma[i]
        slow_prev = self.slow_hma[i - 1]

        if fast <= 0 or slow <= 0:
            return

        # Exit on reverse cross
        for t in list(open_trades):
            if t["direction"] == "long" and fast < slow and fast_prev >= slow_prev:
                close_trade(t, i, close, "hma_bear_cross")
            elif t["direction"] == "short" and fast > slow and fast_prev <= slow_prev:
                close_trade(t, i, close, "hma_bull_cross")

        if len(open_trades) > 0:
            return

        # ADX filter
        if self.adx_vals[i] < s["adx_threshold"]:
            return

        # Bull cross: fast HMA crosses above slow HMA
        if fast > slow and fast_prev <= slow_prev:
            sl = close - atr_val * s["atr_sl_mult"]
            tp = close + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # Bear cross
        elif fast < slow and fast_prev >= slow_prev:
            sl = close + atr_val * s["atr_sl_mult"]
            tp = close - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
