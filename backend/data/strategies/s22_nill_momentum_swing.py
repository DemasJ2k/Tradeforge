"""
Strategy 22: Patrick Nill Momentum Swing
==========================================
Inspired by: Patrick Nill — 9-time Robbins Cup ranked, won twice (70-200%/yr).

Core idea: Nill combines momentum breakout with mean-reversion timing.
Uses dual momentum (ROC on two timeframes), enters when both align,
with MFI (Money Flow Index) confirming institutional money flow.

Logic:
  Fast Momentum  = ROC(10) — short-term burst
  Slow Momentum  = ROC(30) — underlying trend
  MFI(14) confirms money flow direction
  Entry when both ROCs positive + MFI > 50 (long) or vice versa
  Exit on momentum divergence (fast flips while slow still positive)

Markets : Universal (Nill trades futures)
Timeframe: Daily / 4H
"""

DEFAULTS = {
    "roc_fast":         10,
    "roc_slow":         30,
    "mfi_period":       14,
    "mfi_bull":         50,
    "mfi_bear":         50,
    "atr_period":       14,
    "atr_sl_mult":      2.0,
    "atr_tp_mult":      3.5,
    "risk_per_trade":   0.01,
}


SETTINGS = [
    {"key": "roc_fast",         "label": "Fast ROC Period",        "type": "int",   "default": 10,   "min": 3,    "max": 30,   "step": 1,   "group": "Indicator Settings", "description": "Rate of Change period for short-term momentum"},
    {"key": "roc_slow",         "label": "Slow ROC Period",        "type": "int",   "default": 30,   "min": 10,   "max": 100,  "step": 1,   "group": "Indicator Settings", "description": "Rate of Change period for underlying trend momentum"},
    {"key": "mfi_period",       "label": "MFI Period",             "type": "int",   "default": 14,   "min": 5,    "max": 50,   "step": 1,   "group": "Indicator Settings", "description": "Money Flow Index lookback period"},
    {"key": "mfi_bull",         "label": "MFI Bullish Threshold",  "type": "int",   "default": 50,   "min": 30,   "max": 80,   "step": 1,   "group": "Entry Rules",        "description": "MFI must be above this level for long entries"},
    {"key": "mfi_bear",         "label": "MFI Bearish Threshold",  "type": "int",   "default": 50,   "min": 20,   "max": 70,   "step": 1,   "group": "Entry Rules",        "description": "MFI must be below this level for short entries"},
    {"key": "atr_period",       "label": "ATR Period",             "type": "int",   "default": 14,   "min": 5,    "max": 50,   "step": 1,   "group": "Risk Management",    "description": "ATR lookback period for stop/target sizing"},
    {"key": "atr_sl_mult",      "label": "ATR Stop-Loss Mult",    "type": "float", "default": 2.0,  "min": 0.5,  "max": 5.0,  "step": 0.1, "group": "Risk Management",    "description": "ATR multiplier for stop-loss distance"},
    {"key": "atr_tp_mult",      "label": "ATR Take-Profit Mult",  "type": "float", "default": 3.5,  "min": 0.5,  "max": 10.0, "step": 0.1, "group": "Risk Management",    "description": "ATR multiplier for take-profit distance"},
    {"key": "risk_per_trade",   "label": "Risk Per Trade",         "type": "float", "default": 0.01, "min": 0.001,"max": 0.05, "step": 0.001,"group": "Risk Management",   "description": "Fraction of account equity risked per trade"},
]


def _roc(bars, period):
    """Rate of Change."""
    n = len(bars)
    out = [0.0] * n
    for i in range(period, n):
        if bars[i - period]["close"] != 0:
            out[i] = 100 * (bars[i]["close"] - bars[i - period]["close"]) / bars[i - period]["close"]
    return out


def _mfi(bars, period):
    """Money Flow Index."""
    n = len(bars)
    out = [50.0] * n
    tp = [(bars[i]["high"] + bars[i]["low"] + bars[i]["close"]) / 3.0 for i in range(n)]
    mf = [tp[i] * max(bars[i].get("volume", 0), 1) for i in range(n)]

    for i in range(period, n):
        pos = 0.0
        neg = 0.0
        for j in range(i - period + 1, i + 1):
            if tp[j] > tp[j - 1]:
                pos += mf[j]
            elif tp[j] < tp[j - 1]:
                neg += mf[j]
        if neg == 0:
            out[i] = 100.0
        elif pos == 0:
            out[i] = 0.0
        else:
            ratio = pos / neg
            out[i] = 100.0 - 100.0 / (1.0 + ratio)
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


class NillMomentumSwing:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.roc_fast = _roc(bars, self.s["roc_fast"])
        self.roc_slow = _roc(bars, self.s["roc_slow"])
        self.mfi = _mfi(bars, self.s["mfi_period"])
        self.atr_vals = _atr(bars, self.s["atr_period"])

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["roc_slow"], s["mfi_period"], s["atr_period"]) + 3
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        close = bar["close"]
        rf = self.roc_fast[i]
        rs = self.roc_slow[i]
        mfi = self.mfi[i]

        # Exit: fast momentum flips against position
        for t in list(open_trades):
            if t["direction"] == "long" and rf < 0:
                close_trade(t, i, close, "momentum_exit")
            elif t["direction"] == "short" and rf > 0:
                close_trade(t, i, close, "momentum_exit")

        if len(open_trades) > 0:
            return

        # Long: both ROCs positive + MFI bullish
        if rf > 0 and rs > 0 and mfi > s["mfi_bull"]:
            # Additional: fast momentum just turned (was <= 0 previous bar)
            if self.roc_fast[i - 1] <= 0:
                sl = close - atr_val * s["atr_sl_mult"]
                tp = close + atr_val * s["atr_tp_mult"]
                open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # Short: both ROCs negative + MFI bearish
        elif rf < 0 and rs < 0 and mfi < s["mfi_bear"]:
            if self.roc_fast[i - 1] >= 0:
                sl = close + atr_val * s["atr_sl_mult"]
                tp = close - atr_val * s["atr_tp_mult"]
                open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
