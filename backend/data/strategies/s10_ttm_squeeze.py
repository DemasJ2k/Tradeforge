"""
Strategy 10: TTM Squeeze Momentum Breakout
============================================
Inspired by: John Carter — "Mastering the Trade" author.

Core idea: When Bollinger Bands contract inside Keltner Channels, volatility
is "squeezed." When the squeeze fires (BB expands outside KC), a momentum
burst follows. Enter in the direction of momentum when squeeze releases.

Signal logic:
  Squeeze ON  = BB_upper < KC_upper AND BB_lower > KC_lower
  Squeeze OFF = BB_upper >= KC_upper OR BB_lower <= KC_lower
  Momentum    = close - midline_of_donchian(20) smoothed with SMA

Entry: Squeeze fires (was ON, now OFF) + momentum direction
Exit : Momentum reversal or opposite squeeze fire

Markets : Universal
Timeframe: 15m / 1H / 4H / Daily
"""

DEFAULTS = {
    "bb_period":    20,
    "bb_mult":      2.0,
    "kc_period":    20,
    "kc_mult":      1.5,
    "mom_period":   12,     # Momentum smoothing
    "atr_period":   14,
    "atr_sl_mult":  2.0,
    "atr_tp_mult":  3.0,
    "min_squeeze_bars": 4,  # Min bars in squeeze before breakout valid
    "risk_per_trade": 0.01,
}


SETTINGS = [
    {"key": "bb_period", "label": "Bollinger Band Period", "type": "int", "default": 20, "min": 10, "max": 50, "step": 1, "group": "Indicator Settings", "description": "Lookback period for Bollinger Bands moving average and standard deviation"},
    {"key": "bb_mult", "label": "Bollinger Band Multiplier", "type": "float", "default": 2.0, "min": 1.0, "max": 3.5, "step": 0.1, "group": "Indicator Settings", "description": "Standard deviation multiplier for Bollinger Band width"},
    {"key": "kc_period", "label": "Keltner Channel Period", "type": "int", "default": 20, "min": 10, "max": 50, "step": 1, "group": "Indicator Settings", "description": "Lookback period for Keltner Channel EMA and ATR"},
    {"key": "kc_mult", "label": "Keltner Channel Multiplier", "type": "float", "default": 1.5, "min": 0.5, "max": 3.0, "step": 0.1, "group": "Indicator Settings", "description": "ATR multiplier for Keltner Channel width"},
    {"key": "mom_period", "label": "Momentum Period", "type": "int", "default": 12, "min": 5, "max": 30, "step": 1, "group": "Indicator Settings", "description": "SMA smoothing period for the momentum oscillator"},
    {"key": "atr_period", "label": "ATR Period", "type": "int", "default": 14, "min": 5, "max": 50, "step": 1, "group": "Indicator Settings", "description": "Lookback period for ATR used in stop-loss and take-profit"},
    {"key": "atr_sl_mult", "label": "ATR Stop-Loss Multiplier", "type": "float", "default": 2.0, "min": 0.5, "max": 5.0, "step": 0.1, "group": "Risk Management", "description": "ATR multiplier for stop-loss distance from entry"},
    {"key": "atr_tp_mult", "label": "ATR Take-Profit Multiplier", "type": "float", "default": 3.0, "min": 0.5, "max": 10.0, "step": 0.1, "group": "Risk Management", "description": "ATR multiplier for take-profit distance from entry"},
    {"key": "min_squeeze_bars", "label": "Min Squeeze Bars", "type": "int", "default": 4, "min": 1, "max": 20, "step": 1, "group": "Entry Rules", "description": "Minimum consecutive bars BB must be inside KC before breakout is valid"},
    {"key": "risk_per_trade", "label": "Risk Per Trade", "type": "float", "default": 0.01, "min": 0.001, "max": 0.05, "step": 0.001, "group": "Risk Management", "description": "Fraction of account equity risked per trade"},
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


def _sma_bars(bars, period, key="close"):
    return _sma([b[key] for b in bars], period)


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


class TTMSqueeze:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        n = len(bars)

        bb_p = self.s["bb_period"]
        kc_p = self.s["kc_period"]

        # Bollinger Bands
        self.bb_mid = _sma_bars(bars, bb_p)
        self.bb_std = _stdev(bars, bb_p, self.bb_mid)
        self.bb_upper = [self.bb_mid[i] + self.s["bb_mult"] * self.bb_std[i] for i in range(n)]
        self.bb_lower = [self.bb_mid[i] - self.s["bb_mult"] * self.bb_std[i] for i in range(n)]

        # Keltner Channels
        self.kc_mid = _ema([b["close"] for b in bars], kc_p)
        atr_for_kc = _atr(bars, kc_p)
        self.kc_upper = [self.kc_mid[i] + self.s["kc_mult"] * atr_for_kc[i] for i in range(n)]
        self.kc_lower = [self.kc_mid[i] - self.s["kc_mult"] * atr_for_kc[i] for i in range(n)]

        # Squeeze state: True = squeezed
        self.squeezed = [False] * n
        for i in range(n):
            if self.bb_upper[i] > 0 and self.kc_upper[i] > 0:
                self.squeezed[i] = (self.bb_upper[i] < self.kc_upper[i] and
                                    self.bb_lower[i] > self.kc_lower[i])

        # Momentum: close - midline of Donchian(20), smoothed
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

        # Exit: momentum reverses
        for t in list(open_trades):
            if t["direction"] == "long" and mom < 0 and mom_prev >= 0:
                close_trade(t, i, close, "momentum_reversal")
            elif t["direction"] == "short" and mom > 0 and mom_prev <= 0:
                close_trade(t, i, close, "momentum_reversal")

        if len(open_trades) > 0:
            return

        # Check squeeze fire: was squeezed for min_squeeze_bars, now released
        if self.squeezed[i]:
            return  # still in squeeze

        # Count consecutive squeeze bars before this release
        count = 0
        for j in range(i - 1, max(i - 50, 0) - 1, -1):
            if self.squeezed[j]:
                count += 1
            else:
                break
        if count < s["min_squeeze_bars"]:
            return  # not enough squeeze build-up

        # Direction from momentum
        if mom > 0 and mom > mom_prev:
            sl = close - atr_val * s["atr_sl_mult"]
            tp = close + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
        elif mom < 0 and mom < mom_prev:
            sl = close + atr_val * s["atr_sl_mult"]
            tp = close - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
