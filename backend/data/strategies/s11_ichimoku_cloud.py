"""
Strategy 11: Ichimoku Cloud Breakout
======================================
Inspired by: Goichi Hosoda (1930s-60s Japan — 30 years of development).
Verified system with worldwide adoption.

Logic:
  Long:  close > Kumo (cloud), Tenkan crosses above Kijun (TK cross),
         Chikou Span above price 26 bars ago (confirmation).
  Short: Mirror opposite.
  Exit:  TK reverse cross or price re-enters cloud.

Improvement: Add Kumo twist (Senkou A > Senkou B = bullish cloud) as filter.

Markets : Universal (originally equities)
Timeframe: 4H / Daily / Weekly
"""

DEFAULTS = {
    "tenkan_period":    9,
    "kijun_period":     26,
    "senkou_b_period":  52,
    "displacement":     26,
    "atr_period":       14,
    "atr_sl_mult":      2.5,
    "atr_tp_mult":      4.0,
    "require_chikou":   True,
    "require_kumo_twist": True,
    "risk_per_trade":   0.01,
}


def _donchian_mid(bars, period, i):
    start = max(0, i - period + 1)
    hh = max(bars[j]["high"] for j in range(start, i + 1))
    ll = min(bars[j]["low"] for j in range(start, i + 1))
    return (hh + ll) / 2.0


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


class IchimokuBreakout:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        n = len(bars)
        tp = self.s["tenkan_period"]
        kp = self.s["kijun_period"]
        sb = self.s["senkou_b_period"]
        disp = self.s["displacement"]

        # Tenkan-sen (conversion line, 9-period Donchian midpoint)
        self.tenkan = [0.0] * n
        for i in range(tp - 1, n):
            self.tenkan[i] = _donchian_mid(bars, tp, i)

        # Kijun-sen (base line, 26-period Donchian midpoint)
        self.kijun = [0.0] * n
        for i in range(kp - 1, n):
            self.kijun[i] = _donchian_mid(bars, kp, i)

        # Senkou Span A (average of Tenkan and Kijun, displaced 26 forward)
        # For backtesting we store where it currently is (shifted back into current bars)
        self.senkou_a = [0.0] * n
        for i in range(kp - 1, n):
            future_i = i + disp
            if future_i < n:
                self.senkou_a[future_i] = (self.tenkan[i] + self.kijun[i]) / 2.0
        # For current bar: use non-displaced version
        self.senkou_a_current = [(self.tenkan[i] + self.kijun[i]) / 2.0 if self.tenkan[i] > 0 and self.kijun[i] > 0 else 0.0 for i in range(n)]

        # Senkou Span B (52-period Donchian mid, displaced 26 forward)
        self.senkou_b = [0.0] * n
        self.senkou_b_current = [0.0] * n
        for i in range(sb - 1, n):
            val = _donchian_mid(bars, sb, i)
            self.senkou_b_current[i] = val
            future_i = i + disp
            if future_i < n:
                self.senkou_b[future_i] = val

        # Chikou Span = current close plotted 26 bars back
        # For signal: compare close to price 26 bars ago
        self.atr_vals = _atr(bars, self.s["atr_period"])

    def _cloud_top(self, i):
        return max(self.senkou_a_current[i], self.senkou_b_current[i])

    def _cloud_bottom(self, i):
        return min(self.senkou_a_current[i], self.senkou_b_current[i])

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["senkou_b_period"], s["kijun_period"] + s["displacement"], s["atr_period"]) + 2
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        close = bar["close"]
        tenkan = self.tenkan[i]
        kijun = self.kijun[i]
        tenkan_prev = self.tenkan[i - 1]
        kijun_prev = self.kijun[i - 1]
        cloud_top = self._cloud_top(i)
        cloud_bottom = self._cloud_bottom(i)

        if tenkan <= 0 or kijun <= 0 or cloud_top <= 0:
            return

        # Exit: price enters cloud or TK reverse cross
        for t in list(open_trades):
            in_cloud = cloud_bottom <= close <= cloud_top
            if t["direction"] == "long":
                tk_bear = tenkan < kijun and tenkan_prev >= kijun_prev
                if in_cloud or tk_bear:
                    close_trade(t, i, close, "ichimoku_exit")
            elif t["direction"] == "short":
                tk_bull = tenkan > kijun and tenkan_prev <= kijun_prev
                if in_cloud or tk_bull:
                    close_trade(t, i, close, "ichimoku_exit")

        if len(open_trades) > 0:
            return

        # Kumo twist filter
        if s["require_kumo_twist"]:
            bullish_cloud = self.senkou_a_current[i] > self.senkou_b_current[i]
            bearish_cloud = self.senkou_a_current[i] < self.senkou_b_current[i]
        else:
            bullish_cloud = bearish_cloud = True

        # Chikou confirmation
        if s["require_chikou"]:
            disp = s["displacement"]
            chikou_bull = close > self.bars[i - disp]["close"] if i >= disp else False
            chikou_bear = close < self.bars[i - disp]["close"] if i >= disp else False
        else:
            chikou_bull = chikou_bear = True

        # TK cross bull
        tk_bull_cross = tenkan > kijun and tenkan_prev <= kijun_prev

        # Long: price above cloud + TK bull cross + chikou + kumo twist
        if close > cloud_top and tk_bull_cross and chikou_bull and bullish_cloud:
            sl = close - atr_val * s["atr_sl_mult"]
            tp = close + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # TK cross bear
        tk_bear_cross = tenkan < kijun and tenkan_prev >= kijun_prev

        # Short: price below cloud + TK bear cross + chikou + kumo twist
        if close < cloud_bottom and tk_bear_cross and chikou_bear and bearish_cloud:
            sl = close + atr_val * s["atr_sl_mult"]
            tp = close - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
