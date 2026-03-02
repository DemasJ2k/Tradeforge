"""
Strategy 04: Triple EMA + VWAP Scalper
=======================================
Inspired by: The EMA VWAP scalping method (62% win rate, 20+ trades/day
automated setups on Tradovate & similar platforms).

Core idea: 3 EMAs (9, 21, 55) for trend alignment + VWAP for value.
  - LONG: 9 > 21 > 55 (bullish stack), price above VWAP, pullback to 21 EMA
  - SHORT: 9 < 21 < 55 (bearish stack), price below VWAP, pullback to 21 EMA

Markets : Universal
Timeframe: 1m–5m
"""

DEFAULTS = {
    "ema_fast":       9,
    "ema_mid":        21,
    "ema_slow":       55,
    "atr_period":     14,
    "atr_sl_mult":    1.2,
    "atr_tp_mult":    1.8,
    "pullback_pct":   0.3,    # close must be within 30% of distance to mid EMA
    "risk_per_trade": 0.01,
}


def _ema(data, period):
    out = [0.0] * len(data)
    if period > len(data):
        return out
    k = 2.0 / (period + 1)
    out[period - 1] = sum(data[:period]) / period
    for i in range(period, len(data)):
        out[i] = data[i] * k + out[i - 1] * (1 - k)
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


def _vwap(bars):
    """Cumulative VWAP."""
    n = len(bars)
    out = [0.0] * n
    cum_pv = 0.0
    cum_v = 0.0
    for i in range(n):
        vol = bars[i].get("volume", 1) or 1
        typical = (bars[i]["high"] + bars[i]["low"] + bars[i]["close"]) / 3
        cum_pv += typical * vol
        cum_v += vol
        out[i] = cum_pv / cum_v if cum_v > 0 else typical
    return out


class TripleEmaVwapScalper:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        closes = [b["close"] for b in bars]
        self.ema_fast = _ema(closes, self.s["ema_fast"])
        self.ema_mid = _ema(closes, self.s["ema_mid"])
        self.ema_slow = _ema(closes, self.s["ema_slow"])
        self.vwap = _vwap(bars)
        self.atr_values = _atr(bars, self.s["atr_period"])

    def on_bar(self, i, bar):
        s = self.s
        if i < s["ema_slow"] + 2:
            return
        atr_val = self.atr_values[i]
        if atr_val <= 0 or len(open_trades) > 0:
            return

        ef = self.ema_fast[i]
        em = self.ema_mid[i]
        es = self.ema_slow[i]
        vw = self.vwap[i]
        close = bar["close"]

        # Bullish EMA stack + above VWAP
        if ef > em > es and close > vw:
            # Pullback: close near mid EMA
            dist = abs(close - em)
            if dist < atr_val * s["pullback_pct"]:
                sl = close - atr_val * s["atr_sl_mult"]
                tp = close + atr_val * s["atr_tp_mult"]
                open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # Bearish EMA stack + below VWAP
        elif ef < em < es and close < vw:
            dist = abs(close - em)
            if dist < atr_val * s["pullback_pct"]:
                sl = close + atr_val * s["atr_sl_mult"]
                tp = close - atr_val * s["atr_tp_mult"]
                open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
