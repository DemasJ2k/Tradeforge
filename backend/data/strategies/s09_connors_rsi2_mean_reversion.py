"""
Strategy 09: Connors RSI(2) Mean Reversion
============================================
Inspired by: Larry Connors — 30%+ annual returns since 1999 on S&P 500.

Core idea: Ultra-short-term RSI(2) identifies extreme oversold/overbought
conditions. Buy when RSI(2) < 10, sell when RSI(2) > 90. Works best
on indices and liquid stocks/pairs.

Improvements:
  - Add 200-SMA trend filter (long only above, short only below).
  - Cumulative RSI variation: sum RSI(2) over 2 bars for a smoother signal.
  - ADX filter to avoid strong trends where mean reversion fails.

Markets : Universal (best on indices, Large-cap forex)
Timeframe: Daily
"""

DEFAULTS = {
    "rsi_period":       2,
    "rsi_buy_thresh":   10,     # Buy when RSI(2) falls below
    "rsi_sell_thresh":  90,     # Sell/short when RSI(2) rises above
    "cum_rsi_bars":     2,      # Cumulative RSI lookback
    "cum_rsi_buy":      50,     # Cumulative RSI buy threshold (relaxed from 35)
    "cum_rsi_sell":     150,    # Cumulative RSI sell threshold (relaxed from 160)
    "sma_period":       200,
    "use_rsi_exit":     False,  # Disabled — RSI exit cuts winners short, creating neg asymmetry
    "exit_rsi_long":    70,     # Exit long when RSI(2) > this (if enabled)
    "exit_rsi_short":   30,     # Exit short when RSI(2) < this (if enabled)
    "adx_period":       14,
    "adx_max":          25,     # Lowered from 30 — stricter trend filter
    "atr_period":       14,
    "atr_sl_mult":      1.5,    # Tightened SL (was 2.0) to balance R:R
    "atr_tp_mult":      2.0,    # Widened TP (was 1.5) — let MR plays develop
    "risk_per_trade":   0.01,
}


def _sma(bars, period, key="close"):
    n = len(bars)
    out = [0.0] * n
    if period > n:
        return out
    s = sum(bars[j][key] for j in range(period))
    out[period - 1] = s / period
    for i in range(period, n):
        s += bars[i][key] - bars[i - period][key]
        out[i] = s / period
    return out


def _rsi(bars, period):
    n = len(bars)
    out = [50.0] * n
    if period + 1 > n:
        return out
    gains = 0.0
    losses = 0.0
    for j in range(1, period + 1):
        diff = bars[j]["close"] - bars[j - 1]["close"]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        out[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        out[period] = 100.0 - 100.0 / (1.0 + rs)
    for i in range(period + 1, n):
        diff = bars[i]["close"] - bars[i - 1]["close"]
        g = diff if diff > 0 else 0.0
        l = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i] = 100.0 - 100.0 / (1.0 + rs)
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
    """Simplified ADX."""
    n = len(bars)
    out = [0.0] * n
    if 2 * period + 1 > n:
        return out
    dm_plus = [0.0] * n
    dm_minus = [0.0] * n
    trs = [0.0] * n
    for i in range(1, n):
        h_diff = bars[i]["high"] - bars[i - 1]["high"]
        l_diff = bars[i - 1]["low"] - bars[i]["low"]
        dm_plus[i] = h_diff if h_diff > l_diff and h_diff > 0 else 0.0
        dm_minus[i] = l_diff if l_diff > h_diff and l_diff > 0 else 0.0
        trs[i] = max(bars[i]["high"] - bars[i]["low"],
                      abs(bars[i]["high"] - bars[i - 1]["close"]),
                      abs(bars[i]["low"] - bars[i - 1]["close"]))
    sm_tr = sum(trs[1:period + 1])
    sm_dp = sum(dm_plus[1:period + 1])
    sm_dm = sum(dm_minus[1:period + 1])
    dx_list = []
    for i in range(period, n):
        if i > period:
            sm_tr = sm_tr - sm_tr / period + trs[i]
            sm_dp = sm_dp - sm_dp / period + dm_plus[i]
            sm_dm = sm_dm - sm_dm / period + dm_minus[i]
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


class ConnorsRSI2:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.rsi = _rsi(bars, self.s["rsi_period"])
        self.sma = _sma(bars, self.s["sma_period"])
        self.atr_vals = _atr(bars, self.s["atr_period"])
        self.adx_vals = _adx(bars, self.s["adx_period"])

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["sma_period"], s["adx_period"] * 2, s["rsi_period"] + s["cum_rsi_bars"]) + 1
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        sma_val = self.sma[i]
        adx_val = self.adx_vals[i]
        close = bar["close"]

        if atr_val <= 0 or sma_val <= 0:
            return

        # Optional RSI exit (disabled by default — creates neg win/loss asymmetry)
        if s.get("use_rsi_exit", False):
            for t in list(open_trades):
                if t["direction"] == "long" and self.rsi[i] > s.get("exit_rsi_long", 70):
                    close_trade(t, i, close, "rsi_exit_revert")
                elif t["direction"] == "short" and self.rsi[i] < s.get("exit_rsi_short", 30):
                    close_trade(t, i, close, "rsi_exit_revert")

        if len(open_trades) > 0:
            return

        # ADX filter: skip if ADX > max (strong trend = mean reversion fails)
        if adx_val > s["adx_max"]:
            return

        # Cumulative RSI
        cum_rsi = sum(self.rsi[i - j] for j in range(s["cum_rsi_bars"]))

        # Long: price above 200-SMA (uptrend), RSI(2) oversold
        if close > sma_val and cum_rsi < s["cum_rsi_buy"]:
            sl = close - atr_val * s["atr_sl_mult"]
            tp = close + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # Short: price below 200-SMA (downtrend), RSI(2) overbought
        elif close < sma_val and cum_rsi > s["cum_rsi_sell"]:
            sl = close + atr_val * s["atr_sl_mult"]
            tp = close - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
