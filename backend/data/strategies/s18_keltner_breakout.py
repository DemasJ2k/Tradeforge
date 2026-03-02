"""
Strategy 18: Keltner Channel Breakout
========================================
Inspired by: Chester Keltner (1960) and Linda Bradford Raschke modernization.

Core idea: Keltner Channels = EMA(20) ± 2.5 * ATR(10). Breakout above upper
channel = strong bullish momentum; below lower = bearish. Use channel
re-entry as stop.

Enhancement: Add ADX filter to avoid false breakouts in choppy markets.

Markets : Universal
Timeframe: 15m / 1H / 4H
"""

DEFAULTS = {
    "kc_ema_period":    20,
    "kc_atr_period":    10,
    "kc_mult":          1.8,    # Narrower channels — more breakout signals (was 2.0)
    "adx_period":       14,
    "adx_threshold":    20,     # Lowered from 25 — catch more trends
    "atr_sl_period":    14,
    "atr_sl_mult":      2.0,
    "atr_tp_mult":      4.0,    # Wider TP — let winners run (was 3.5)
    "exit_on_reenter":  False,  # Disabled — was killing trades immediately
    "require_momentum": True,   # Require close confirms direction
    "risk_per_trade":   0.01,
}


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


def _adx(bars, period):
    n = len(bars)
    out = [0.0] * n
    if 2 * period + 1 > n:
        return out
    dmp = [0.0] * n
    dmm = [0.0] * n
    trs = [0.0] * n
    for i in range(1, n):
        h_diff = bars[i]["high"] - bars[i - 1]["high"]
        l_diff = bars[i - 1]["low"] - bars[i]["low"]
        dmp[i] = h_diff if h_diff > l_diff and h_diff > 0 else 0.0
        dmm[i] = l_diff if l_diff > h_diff and l_diff > 0 else 0.0
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
        di_sum = di_p + di_m
        dx = 100 * abs(di_p - di_m) / di_sum if di_sum > 0 else 0
        dx_list.append(dx)
        if len(dx_list) == period:
            out[i] = sum(dx_list) / period
        elif len(dx_list) > period:
            out[i] = (out[i - 1] * (period - 1) + dx) / period
    return out


class KeltnerBreakout:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        n = len(bars)
        closes = [b["close"] for b in bars]

        kc_ema = _ema(closes, self.s["kc_ema_period"])
        kc_atr = _atr(bars, self.s["kc_atr_period"])

        self.kc_mid = kc_ema
        self.kc_upper = [kc_ema[i] + self.s["kc_mult"] * kc_atr[i] for i in range(n)]
        self.kc_lower = [kc_ema[i] - self.s["kc_mult"] * kc_atr[i] for i in range(n)]
        self.adx_vals = _adx(bars, self.s["adx_period"])
        self.atr_vals = _atr(bars, self.s["atr_sl_period"])

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["kc_ema_period"], s["kc_atr_period"], s["adx_period"] * 2, s["atr_sl_period"]) + 3
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        close = bar["close"]
        upper = self.kc_upper[i]
        lower = self.kc_lower[i]

        # Exit: price re-enters channel
        for t in list(open_trades):
            if s["exit_on_reenter"]:
                if t["direction"] == "long" and close < upper:
                    close_trade(t, i, close, "kc_reenter")
                elif t["direction"] == "short" and close > lower:
                    close_trade(t, i, close, "kc_reenter")

        if len(open_trades) > 0:
            return

        # ADX filter
        if self.adx_vals[i] < s["adx_threshold"]:
            return

        # Breakout above upper channel
        prev_close = self.bars[i - 1]["close"]
        mom_ok_long = (not s["require_momentum"]) or (close > prev_close)
        mom_ok_short = (not s["require_momentum"]) or (close < prev_close)

        if close > upper and prev_close <= self.kc_upper[i - 1] and mom_ok_long:
            sl = close - atr_val * s["atr_sl_mult"]
            tp = close + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # Breakout below lower channel
        elif close < lower and prev_close >= self.kc_lower[i - 1] and mom_ok_short:
            sl = close + atr_val * s["atr_sl_mult"]
            tp = close - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
