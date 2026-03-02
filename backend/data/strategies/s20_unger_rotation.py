"""
Strategy 20: Andrea Unger Multi-Strategy Rotation
====================================================
Inspired by: Andrea Unger — 4-time World Trading Champion.

Core idea: Unger's key insight — no single strategy works forever. Use
regime detection to switch between trend-following and mean-reversion.

Regime Detection:
  - High ADX + rising → Trending market → Use breakout system
  - Low ADX + flat   → Range-bound    → Use mean reversion system
  - Volatility expansion = breakout trades
  - Volatility contraction = fade extremes

Markets : Universal (Unger trades futures: indices, forex, commodities)
Timeframe: 1H / 4H / Daily
"""

DEFAULTS = {
    "adx_period":           14,
    "adx_trend_threshold":  25,
    "atr_period":           14,
    "atr_vol_period":       20,     # Compare ATR to its own MA for vol regime
    # Trend-following params (used in trending regime)
    "donchian_period":      20,
    "trend_atr_sl_mult":    2.0,
    "trend_atr_tp_mult":    3.5,
    # Mean-reversion params (used in ranging regime)
    "rsi_period":           7,      # Faster RSI (was 14 - too slow for MR)
    "rsi_os":               35,     # Relaxed from 30
    "rsi_ob":               65,     # Relaxed from 70
    "bb_period":            20,
    "bb_mult":              2.0,
    "mr_atr_sl_mult":       1.5,
    "mr_atr_tp_mult":       2.5,    # Widened from 2.0
    "risk_per_trade":       0.01,
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


def _rsi(bars, period):
    n = len(bars)
    out = [50.0] * n
    if period + 1 > n:
        return out
    gains = losses = 0.0
    for j in range(1, period + 1):
        d = bars[j]["close"] - bars[j - 1]["close"]
        if d > 0:
            gains += d
        else:
            losses -= d
    ag = gains / period
    al = losses / period
    if al == 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - 100.0 / (1.0 + ag / al)
    for i in range(period + 1, n):
        d = bars[i]["close"] - bars[i - 1]["close"]
        g = max(d, 0)
        l = max(-d, 0)
        ag = (ag * (period - 1) + g) / period
        al = (al * (period - 1) + l) / period
        if al == 0:
            out[i] = 100.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + ag / al)
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
        di_s = di_p + di_m
        dx = 100 * abs(di_p - di_m) / di_s if di_s > 0 else 0
        dx_list.append(dx)
        if len(dx_list) == period:
            out[i] = sum(dx_list) / period
        elif len(dx_list) > period:
            out[i] = (out[i - 1] * (period - 1) + dx) / period
    return out


class UngerRotation:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        n = len(bars)
        closes = [b["close"] for b in bars]

        self.adx = _adx(bars, self.s["adx_period"])
        self.atr_vals = _atr(bars, self.s["atr_period"])
        self.atr_ma = _sma_vals(self.atr_vals, self.s["atr_vol_period"])
        self.rsi = _rsi(bars, self.s["rsi_period"])

        # Donchian for trend strategy
        dp = self.s["donchian_period"]
        self.don_hi = [0.0] * n
        self.don_lo = [0.0] * n
        for i in range(dp - 1, n):
            self.don_hi[i] = max(bars[j]["high"] for j in range(i - dp + 1, i + 1))
            self.don_lo[i] = min(bars[j]["low"] for j in range(i - dp + 1, i + 1))

        # BB for mean reversion
        bb_p = self.s["bb_period"]
        self.bb_mid = _sma_vals(closes, bb_p)
        self.bb_upper = [0.0] * n
        self.bb_lower = [0.0] * n
        for i in range(bb_p - 1, n):
            mean = self.bb_mid[i]
            if mean > 0:
                var = sum((bars[j]["close"] - mean) ** 2 for j in range(i - bb_p + 1, i + 1)) / bb_p
                sd = var ** 0.5
                self.bb_upper[i] = mean + self.s["bb_mult"] * sd
                self.bb_lower[i] = mean - self.s["bb_mult"] * sd

        self.entry_regime = None  # Track what regime trade was entered in

    def _regime(self, i):
        """Detect market regime: 'trend' or 'range'."""
        if self.adx[i] > self.s["adx_trend_threshold"] and self.adx[i] > self.adx[i - 1]:
            return "trend"
        return "range"

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["adx_period"] * 2, s["donchian_period"], s["bb_period"],
                     s["atr_period"] + s["atr_vol_period"]) + 5
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        close = bar["close"]
        regime = self._regime(i)

        # Exit logic uses regime at ENTRY time (not current — fixes regime mismatch bug)
        for t in list(open_trades):
            entry_r = self.entry_regime or regime
            if t["direction"] == "long":
                # Trend exit: Donchian low break
                if entry_r == "trend" and close < self.don_lo[i]:
                    close_trade(t, i, close, "donchian_exit")
                    self.entry_regime = None
                # MR exit: revert to BB midline
                elif entry_r == "range" and close >= self.bb_mid[i]:
                    close_trade(t, i, close, "bb_mid_exit")
                    self.entry_regime = None
            elif t["direction"] == "short":
                if entry_r == "trend" and close > self.don_hi[i]:
                    close_trade(t, i, close, "donchian_exit")
                    self.entry_regime = None
                elif entry_r == "range" and close <= self.bb_mid[i]:
                    close_trade(t, i, close, "bb_mid_exit")
                    self.entry_regime = None

        if len(open_trades) > 0:
            return

        if regime == "trend":
            # Trend-following: Donchian breakout
            prev_close = self.bars[i - 1]["close"]
            if close > self.don_hi[i - 1] and prev_close <= self.don_hi[i - 2]:
                sl = close - atr_val * s["trend_atr_sl_mult"]
                tp = close + atr_val * s["trend_atr_tp_mult"]
                open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
                self.entry_regime = "trend"
            elif close < self.don_lo[i - 1] and prev_close >= self.don_lo[i - 2]:
                sl = close + atr_val * s["trend_atr_sl_mult"]
                tp = close - atr_val * s["trend_atr_tp_mult"]
                open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
                self.entry_regime = "trend"

        else:
            # Mean reversion: RSI + BB
            if self.rsi[i] < s["rsi_os"] and close <= self.bb_lower[i] and self.bb_lower[i] > 0:
                sl = close - atr_val * s["mr_atr_sl_mult"]
                tp = self.bb_mid[i]
                if tp <= close:
                    tp = close + atr_val * s["mr_atr_tp_mult"]
                open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
                self.entry_regime = "range"
            elif self.rsi[i] > s["rsi_ob"] and close >= self.bb_upper[i] and self.bb_upper[i] > 0:
                sl = close + atr_val * s["mr_atr_sl_mult"]
                tp = self.bb_mid[i]
                if tp >= close:
                    tp = close - atr_val * s["mr_atr_tp_mult"]
                open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
                self.entry_regime = "range"
