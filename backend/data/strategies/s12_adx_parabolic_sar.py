"""
Strategy 12: ADX + Parabolic SAR Trend Follower
=================================================
Inspired by: J. Welles Wilder — inventor of both ADX and Parabolic SAR.

Core idea: ADX confirms a strong trend exists (> 25), Parabolic SAR provides
dynamic trailing stop and entry direction. Only trade when trend is strong.

Improvements:
  - ADX slope filter: ADX must be rising (not just above threshold)
  - DI+/DI- crossover confirms direction before SAR entry
  - ATR-based position sizing

Markets : Universal
Timeframe: 1H / 4H / Daily
"""

DEFAULTS = {
    "adx_period":       14,
    "adx_threshold":    20,     # Lowered from 25 — more entries
    "adx_require_rising": False,  # Removed — too restrictive, rarely coincides with SAR flip
    "sar_af_start":     0.02,
    "sar_af_step":      0.02,
    "sar_af_max":       0.20,
    "atr_period":       14,
    "atr_sl_mult":      2.0,
    "atr_tp_mult":      4.0,    # Widened from 3.5 — let trend trades run
    "risk_per_trade":   0.01,
}


SETTINGS = [
    {"key": "adx_period", "label": "ADX Period", "type": "int", "default": 14, "min": 7, "max": 30, "step": 1, "group": "Indicator Settings", "description": "Lookback period for ADX and DI+/DI- calculation"},
    {"key": "adx_threshold", "label": "ADX Threshold", "type": "int", "default": 20, "min": 10, "max": 40, "step": 1, "group": "Filters", "description": "Minimum ADX value required to confirm a strong trend before entry"},
    {"key": "adx_require_rising", "label": "Require Rising ADX", "type": "bool", "default": False, "group": "Filters", "description": "Only enter when ADX slope is positive (rising trend strength)"},
    {"key": "sar_af_start", "label": "SAR AF Start", "type": "float", "default": 0.02, "min": 0.01, "max": 0.05, "step": 0.01, "group": "Indicator Settings", "description": "Parabolic SAR initial acceleration factor"},
    {"key": "sar_af_step", "label": "SAR AF Step", "type": "float", "default": 0.02, "min": 0.01, "max": 0.05, "step": 0.01, "group": "Indicator Settings", "description": "Parabolic SAR acceleration factor increment per new extreme"},
    {"key": "sar_af_max", "label": "SAR AF Maximum", "type": "float", "default": 0.20, "min": 0.10, "max": 0.40, "step": 0.01, "group": "Indicator Settings", "description": "Parabolic SAR maximum acceleration factor cap"},
    {"key": "atr_period", "label": "ATR Period", "type": "int", "default": 14, "min": 5, "max": 50, "step": 1, "group": "Indicator Settings", "description": "Lookback period for ATR used in stop-loss and take-profit"},
    {"key": "atr_sl_mult", "label": "ATR Stop-Loss Multiplier", "type": "float", "default": 2.0, "min": 0.5, "max": 5.0, "step": 0.1, "group": "Risk Management", "description": "ATR multiplier for stop-loss distance from entry"},
    {"key": "atr_tp_mult", "label": "ATR Take-Profit Multiplier", "type": "float", "default": 4.0, "min": 0.5, "max": 10.0, "step": 0.1, "group": "Risk Management", "description": "ATR multiplier for take-profit distance from entry"},
    {"key": "risk_per_trade", "label": "Risk Per Trade", "type": "float", "default": 0.01, "min": 0.001, "max": 0.05, "step": 0.001, "group": "Risk Management", "description": "Fraction of account equity risked per trade"},
]


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


def _adx_full(bars, period):
    """Returns (adx, di_plus, di_minus) arrays."""
    n = len(bars)
    adx = [0.0] * n
    di_plus = [0.0] * n
    di_minus = [0.0] * n
    if 2 * period + 1 > n:
        return adx, di_plus, di_minus

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

        di_plus[i] = 100 * sm_dp / sm_tr if sm_tr > 0 else 0
        di_minus[i] = 100 * sm_dm / sm_tr if sm_tr > 0 else 0
        di_sum = di_plus[i] + di_minus[i]
        dx = 100 * abs(di_plus[i] - di_minus[i]) / di_sum if di_sum > 0 else 0
        dx_list.append(dx)
        if len(dx_list) == period:
            adx[i] = sum(dx_list) / period
        elif len(dx_list) > period:
            adx[i] = (adx[i - 1] * (period - 1) + dx) / period

    return adx, di_plus, di_minus


def _parabolic_sar(bars, af_start, af_step, af_max):
    """Compute Parabolic SAR. Returns (sar, direction) arrays.
    direction: 1 = bullish (SAR below price), -1 = bearish (SAR above price)."""
    n = len(bars)
    sar = [0.0] * n
    direction = [0] * n
    if n < 3:
        return sar, direction

    # Init: assume uptrend
    bull = True
    af = af_start
    ep = bars[1]["high"]
    sar[1] = bars[0]["low"]
    direction[1] = 1

    for i in range(2, n):
        prev_sar = sar[i - 1]

        if bull:
            sar_val = prev_sar + af * (ep - prev_sar)
            # SAR cannot be above prior two lows
            sar_val = min(sar_val, bars[i - 1]["low"], bars[i - 2]["low"])

            if bars[i]["low"] < sar_val:
                # Flip to bearish
                bull = False
                sar_val = ep
                ep = bars[i]["low"]
                af = af_start
            else:
                if bars[i]["high"] > ep:
                    ep = bars[i]["high"]
                    af = min(af + af_step, af_max)
        else:
            sar_val = prev_sar + af * (ep - prev_sar)
            # SAR cannot be below prior two highs
            sar_val = max(sar_val, bars[i - 1]["high"], bars[i - 2]["high"])

            if bars[i]["high"] > sar_val:
                # Flip to bullish
                bull = True
                sar_val = ep
                ep = bars[i]["high"]
                af = af_start
            else:
                if bars[i]["low"] < ep:
                    ep = bars[i]["low"]
                    af = min(af + af_step, af_max)

        sar[i] = sar_val
        direction[i] = 1 if bull else -1

    return sar, direction


class ADXParabolicSAR:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.adx, self.di_plus, self.di_minus = _adx_full(bars, self.s["adx_period"])
        self.sar, self.sar_dir = _parabolic_sar(
            bars, self.s["sar_af_start"], self.s["sar_af_step"], self.s["sar_af_max"])
        self.atr_vals = _atr(bars, self.s["atr_period"])

    def on_bar(self, i, bar):
        s = self.s
        warmup = s["adx_period"] * 2 + 3
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        close = bar["close"]
        adx_val = self.adx[i]
        sar_dir = self.sar_dir[i]
        sar_dir_prev = self.sar_dir[i - 1]

        # Exit on SAR flip
        for t in list(open_trades):
            if t["direction"] == "long" and sar_dir == -1 and sar_dir_prev == 1:
                close_trade(t, i, close, "sar_flip")
            elif t["direction"] == "short" and sar_dir == 1 and sar_dir_prev == -1:
                close_trade(t, i, close, "sar_flip")

        if len(open_trades) > 0:
            return

        # ADX filter
        if adx_val < s["adx_threshold"]:
            return

        # ADX rising filter (smoothed over 3 bars if enabled)
        if s["adx_require_rising"] and i >= 3:
            adx_slope = self.adx[i] - self.adx[i - 3]
            if adx_slope <= 0:
                return

        # SAR flip + DI confirmation
        if sar_dir == 1 and sar_dir_prev == -1 and self.di_plus[i] > self.di_minus[i]:
            sl = close - atr_val * s["atr_sl_mult"]
            tp = close + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        elif sar_dir == -1 and sar_dir_prev == 1 and self.di_minus[i] > self.di_plus[i]:
            sl = close + atr_val * s["atr_sl_mult"]
            tp = close - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
