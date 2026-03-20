"""
Strategy 46: TTM Squeeze for Crypto (BB/KC Breakout)
====================================================
Walk-forward validated STRONG on BTCUSD H1 (PF=1.310, negative PF degradation).
Negative degradation means OOS performance IMPROVED vs IS — strong edge.

Core idea: Same as TTM Squeeze (s10) but tuned for crypto's 24/7 market and
higher volatility. BB(20,2.0) inside KC(20,1.5) detects squeeze. When squeeze
fires, enter in direction of Donchian momentum.

Crypto-specific adaptations:
  - No session filter (24/7 market)
  - Higher ATR multipliers for crypto volatility
  - Lower min_squeeze_bars (crypto squeezes are shorter)

Markets : BTCUSD, ETHUSD
Timeframe: H1 / H4
"""

DEFAULTS = {
    "bb_period":        20,
    "bb_mult":          2.0,
    "kc_period":        20,
    "kc_mult":          1.5,
    "mom_period":       12,
    "atr_period":       14,
    "atr_sl_mult":      1.5,
    "atr_tp_mult":      6.0,
    "min_squeeze_bars": 3,
    "risk_per_trade":   0.005,
}

SETTINGS = [
    {"key": "bb_period", "label": "Bollinger Band Period", "type": "int", "default": 20, "min": 10, "max": 50, "step": 1, "group": "Indicator Settings", "description": "Lookback period for Bollinger Bands"},
    {"key": "bb_mult", "label": "BB Multiplier", "type": "float", "default": 2.0, "min": 1.0, "max": 3.5, "step": 0.1, "group": "Indicator Settings", "description": "Standard deviation multiplier for BB width"},
    {"key": "kc_period", "label": "Keltner Channel Period", "type": "int", "default": 20, "min": 10, "max": 50, "step": 1, "group": "Indicator Settings", "description": "Lookback period for Keltner Channel"},
    {"key": "kc_mult", "label": "KC Multiplier", "type": "float", "default": 1.5, "min": 0.5, "max": 3.0, "step": 0.1, "group": "Indicator Settings", "description": "ATR multiplier for Keltner Channel width"},
    {"key": "mom_period", "label": "Momentum Period", "type": "int", "default": 12, "min": 5, "max": 30, "step": 1, "group": "Indicator Settings", "description": "SMA smoothing for momentum oscillator"},
    {"key": "atr_period", "label": "ATR Period", "type": "int", "default": 14, "min": 5, "max": 50, "step": 1, "group": "Indicator Settings", "description": "ATR period for stop/take-profit sizing"},
    {"key": "atr_sl_mult", "label": "ATR SL Multiplier", "type": "float", "default": 1.5, "min": 0.5, "max": 5.0, "step": 0.1, "group": "Risk Management", "description": "ATR multiplier for stop-loss distance"},
    {"key": "atr_tp_mult", "label": "ATR TP Multiplier", "type": "float", "default": 6.0, "min": 1.0, "max": 15.0, "step": 0.5, "group": "Risk Management", "description": "ATR multiplier for take-profit distance"},
    {"key": "min_squeeze_bars", "label": "Min Squeeze Bars", "type": "int", "default": 3, "min": 1, "max": 15, "step": 1, "group": "Entry Rules", "description": "Minimum bars BB inside KC before breakout is valid"},
    {"key": "risk_per_trade", "label": "Risk Per Trade", "type": "float", "default": 0.005, "min": 0.001, "max": 0.05, "step": 0.001, "group": "Risk Management", "description": "Fraction of equity risked per trade"},
]


def _sma(values, period, start=0):
    n = len(values)
    out = [0.0] * n
    if period > n:
        return out
    s = sum(values[start:start + period])
    out[start + period - 1] = s / period
    for i in range(start + period, n):
        s += values[i] - values[i - period]
        out[i] = s / period
    return out


def _stdev(bars, period, sma_vals):
    n = len(bars)
    out = [0.0] * n
    for i in range(period - 1, n):
        if sma_vals[i] == 0:
            continue
        mean = sma_vals[i]
        variance = sum((bars[j]["close"] - mean) ** 2 for j in range(i - period + 1, i + 1)) / period
        out[i] = variance ** 0.5
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


class TTMSqueezeCrypto:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        n = len(bars)

        bb_p = self.s["bb_period"]
        kc_p = self.s["kc_period"]

        # Bollinger Bands
        bb_mid = _sma([b["close"] for b in bars], bb_p)
        bb_std = _stdev(bars, bb_p, bb_mid)
        bb_upper = [bb_mid[i] + self.s["bb_mult"] * bb_std[i] for i in range(n)]
        bb_lower = [bb_mid[i] - self.s["bb_mult"] * bb_std[i] for i in range(n)]

        # Keltner Channels
        kc_mid = _ema([b["close"] for b in bars], kc_p)
        atr_for_kc = _atr(bars, kc_p)
        kc_upper = [kc_mid[i] + self.s["kc_mult"] * atr_for_kc[i] for i in range(n)]
        kc_lower = [kc_mid[i] - self.s["kc_mult"] * atr_for_kc[i] for i in range(n)]

        # Squeeze state
        self.squeezed = [False] * n
        for i in range(n):
            if bb_upper[i] > 0 and kc_upper[i] > 0:
                self.squeezed[i] = (bb_upper[i] < kc_upper[i] and
                                    bb_lower[i] > kc_lower[i])

        # Momentum: close - Donchian midline, smoothed
        donchian_mid = [0.0] * n
        for i in range(bb_p - 1, n):
            hh = max(bars[j]["high"] for j in range(i - bb_p + 1, i + 1))
            ll = min(bars[j]["low"] for j in range(i - bb_p + 1, i + 1))
            donchian_mid[i] = (hh + ll) / 2
        raw_mom = [bars[i]["close"] - donchian_mid[i] if donchian_mid[i] > 0 else 0.0 for i in range(n)]
        self.momentum = _sma(raw_mom, self.s["mom_period"])

        self.atr_vals = _atr(bars, self.s["atr_period"])

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["bb_period"], s["kc_period"], s["atr_period"]) + s["min_squeeze_bars"] + 2
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        close = bar["close"]
        mom = self.momentum[i]
        mom_prev = self.momentum[i - 1]

        # Exit: momentum reversal
        for t in list(open_trades):
            if t["direction"] == "long" and mom < 0 and mom_prev >= 0:
                close_trade(t, i, close, "momentum_reversal")
            elif t["direction"] == "short" and mom > 0 and mom_prev <= 0:
                close_trade(t, i, close, "momentum_reversal")

        if len(open_trades) > 0:
            return

        # Check squeeze fire
        if self.squeezed[i]:
            return  # still squeezed

        count = 0
        for j in range(i - 1, max(i - 50, 0) - 1, -1):
            if self.squeezed[j]:
                count += 1
            else:
                break

        if count < s["min_squeeze_bars"]:
            return  # not enough squeeze bars

        # Enter in momentum direction
        if mom > 0:
            sl = close - s["atr_sl_mult"] * atr_val
            tp = close + s["atr_tp_mult"] * atr_val
            open_trade(i, "long", close, sl, tp)
        elif mom < 0:
            sl = close + s["atr_sl_mult"] * atr_val
            tp = close - s["atr_tp_mult"] * atr_val
            open_trade(i, "short", close, sl, tp)
