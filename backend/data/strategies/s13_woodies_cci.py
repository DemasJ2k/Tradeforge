"""
Strategy 13: Woodies CCI Zero Line Reject
============================================
Inspired by: Ken Wood ("Woodie") — pioneer of CCI-based trading systems.

Core idea: CCI(14) trends above/below zero line. After a pullback to zero
(±50), if CCI bounces back in trend direction = Zero Line Reject (ZLR).
This is the highest probability Woodies pattern.

Additional pattern: Trend Line Break — CCI breaks a drawn trendline.

Markets : Universal
Timeframe: 5m / 15m / 1H
"""

DEFAULTS = {
    "cci_period":       14,
    "cci_turbo":        6,      # Short-term CCI for confirmation
    "zlr_zone":         50,     # CCI pulls back to within ±50 of zero
    "trend_bars":       5,      # Min bars CCI stays on one side before ZLR
    "atr_period":       14,
    "atr_sl_mult":      1.5,
    "atr_tp_mult":      2.5,
    "risk_per_trade":   0.01,
}


SETTINGS = [
    {"key": "cci_period", "label": "CCI Period", "type": "int", "default": 14, "min": 5, "max": 30, "step": 1, "group": "Indicator Settings", "description": "Lookback period for the primary Commodity Channel Index"},
    {"key": "cci_turbo", "label": "CCI Turbo Period", "type": "int", "default": 6, "min": 3, "max": 14, "step": 1, "group": "Indicator Settings", "description": "Lookback period for the short-term CCI used as entry confirmation"},
    {"key": "zlr_zone", "label": "ZLR Zone", "type": "int", "default": 50, "min": 20, "max": 100, "step": 5, "group": "Entry Rules", "description": "CCI must pull back to within this distance of zero for a Zero Line Reject"},
    {"key": "trend_bars", "label": "Trend Bars", "type": "int", "default": 5, "min": 2, "max": 20, "step": 1, "group": "Entry Rules", "description": "Minimum consecutive bars CCI must stay on one side of zero before a ZLR is valid"},
    {"key": "atr_period", "label": "ATR Period", "type": "int", "default": 14, "min": 5, "max": 50, "step": 1, "group": "Indicator Settings", "description": "Lookback period for ATR used in stop-loss and take-profit"},
    {"key": "atr_sl_mult", "label": "ATR Stop-Loss Multiplier", "type": "float", "default": 1.5, "min": 0.5, "max": 5.0, "step": 0.1, "group": "Risk Management", "description": "ATR multiplier for stop-loss distance from entry"},
    {"key": "atr_tp_mult", "label": "ATR Take-Profit Multiplier", "type": "float", "default": 2.5, "min": 0.5, "max": 10.0, "step": 0.1, "group": "Risk Management", "description": "ATR multiplier for take-profit distance from entry"},
    {"key": "risk_per_trade", "label": "Risk Per Trade", "type": "float", "default": 0.01, "min": 0.001, "max": 0.05, "step": 0.001, "group": "Risk Management", "description": "Fraction of account equity risked per trade"},
]


def _cci(bars, period):
    """Commodity Channel Index = (TP - SMA(TP)) / (0.015 * MeanDev)."""
    n = len(bars)
    out = [0.0] * n
    tp = [(bars[i]["high"] + bars[i]["low"] + bars[i]["close"]) / 3.0 for i in range(n)]
    for i in range(period - 1, n):
        start = i - period + 1
        sma = sum(tp[start:i + 1]) / period
        mean_dev = sum(abs(tp[j] - sma) for j in range(start, i + 1)) / period
        if mean_dev > 0:
            out[i] = (tp[i] - sma) / (0.015 * mean_dev)
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


class WoodiesCCI:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.cci = _cci(bars, self.s["cci_period"])
        self.cci_turbo = _cci(bars, self.s["cci_turbo"])
        self.atr_vals = _atr(bars, self.s["atr_period"])

    def _count_trend_bars(self, i, direction):
        """Count consecutive bars CCI is on one side of zero before the current bar."""
        count = 0
        for j in range(i - 1, max(0, i - 100) - 1, -1):
            if direction == "up" and self.cci[j] > 0:
                count += 1
            elif direction == "down" and self.cci[j] < 0:
                count += 1
            else:
                break
        return count

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["cci_period"], s["cci_turbo"], s["atr_period"]) + s["trend_bars"] + 2
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        close = bar["close"]
        cci = self.cci[i]
        cci_prev = self.cci[i - 1]
        turbo = self.cci_turbo[i]

        # Exit on CCI zero-line cross (trend break)
        for t in list(open_trades):
            if t["direction"] == "long" and cci < -s["zlr_zone"]:
                close_trade(t, i, close, "cci_reversal")
            elif t["direction"] == "short" and cci > s["zlr_zone"]:
                close_trade(t, i, close, "cci_reversal")

        if len(open_trades) > 0:
            return

        # Zero Line Reject — LONG
        # CCI was positive (trend up), pulled back to near zero (0 < cci < zlr_zone previously),
        # now bouncing back positive
        if cci > s["zlr_zone"] and abs(cci_prev) < s["zlr_zone"]:
            # Check prior trend
            # Look back from 2 bars ago to see if CCI was consistently positive
            trend_count = 0
            for j in range(i - 2, max(0, i - 50) - 1, -1):
                if self.cci[j] > 0:
                    trend_count += 1
                else:
                    break
            if trend_count >= s["trend_bars"] and turbo > 0:
                sl = close - atr_val * s["atr_sl_mult"]
                tp = close + atr_val * s["atr_tp_mult"]
                open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # Zero Line Reject — SHORT
        elif cci < -s["zlr_zone"] and abs(cci_prev) < s["zlr_zone"]:
            trend_count = 0
            for j in range(i - 2, max(0, i - 50) - 1, -1):
                if self.cci[j] < 0:
                    trend_count += 1
                else:
                    break
            if trend_count >= s["trend_bars"] and turbo < 0:
                sl = close + atr_val * s["atr_sl_mult"]
                tp = close - atr_val * s["atr_tp_mult"]
                open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
