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


SETTINGS = [
    {"key": "rsi_period", "label": "RSI Period", "type": "int", "default": 2, "min": 2, "max": 10, "step": 1, "group": "Indicator Settings", "description": "Lookback period for ultra-short RSI (Connors uses 2)"},
    {"key": "rsi_buy_thresh", "label": "RSI Buy Threshold", "type": "int", "default": 10, "min": 1, "max": 30, "step": 1, "group": "Entry Rules", "description": "Buy when RSI falls below this level (oversold)"},
    {"key": "rsi_sell_thresh", "label": "RSI Sell Threshold", "type": "int", "default": 90, "min": 70, "max": 99, "step": 1, "group": "Entry Rules", "description": "Sell/short when RSI rises above this level (overbought)"},
    {"key": "cum_rsi_bars", "label": "Cumulative RSI Bars", "type": "int", "default": 2, "min": 1, "max": 5, "step": 1, "group": "Entry Rules", "description": "Number of bars to sum RSI over for cumulative RSI signal"},
    {"key": "cum_rsi_buy", "label": "Cumulative RSI Buy", "type": "int", "default": 50, "min": 10, "max": 100, "step": 5, "group": "Entry Rules", "description": "Cumulative RSI must be below this value for a long entry"},
    {"key": "cum_rsi_sell", "label": "Cumulative RSI Sell", "type": "int", "default": 150, "min": 100, "max": 200, "step": 5, "group": "Entry Rules", "description": "Cumulative RSI must be above this value for a short entry"},
    {"key": "sma_period", "label": "Trend SMA Period", "type": "int", "default": 200, "min": 50, "max": 300, "step": 10, "group": "Filters", "description": "SMA period for trend filter (long only above, short only below)"},
    {"key": "use_rsi_exit", "label": "Use RSI Exit", "type": "bool", "default": False, "group": "Exit Rules", "description": "Enable early exit when RSI reverts to normal levels"},
    {"key": "exit_rsi_long", "label": "Exit RSI Long", "type": "int", "default": 70, "min": 50, "max": 90, "step": 5, "group": "Exit Rules", "description": "Exit long position when RSI rises above this level (if RSI exit enabled)"},
    {"key": "exit_rsi_short", "label": "Exit RSI Short", "type": "int", "default": 30, "min": 10, "max": 50, "step": 5, "group": "Exit Rules", "description": "Exit short position when RSI drops below this level (if RSI exit enabled)"},
    {"key": "adx_period", "label": "ADX Period", "type": "int", "default": 14, "min": 7, "max": 30, "step": 1, "group": "Indicator Settings", "description": "Lookback period for ADX trend strength indicator"},
    {"key": "adx_max", "label": "ADX Maximum", "type": "int", "default": 25, "min": 15, "max": 50, "step": 1, "group": "Filters", "description": "Skip trades when ADX exceeds this value (strong trend = mean reversion fails)"},
    {"key": "atr_period", "label": "ATR Period", "type": "int", "default": 14, "min": 5, "max": 50, "step": 1, "group": "Indicator Settings", "description": "Lookback period for Average True Range calculation"},
    {"key": "atr_sl_mult", "label": "ATR Stop-Loss Multiplier", "type": "float", "default": 1.5, "min": 0.5, "max": 5.0, "step": 0.1, "group": "Risk Management", "description": "ATR multiplier for stop-loss distance from entry"},
    {"key": "atr_tp_mult", "label": "ATR Take-Profit Multiplier", "type": "float", "default": 2.0, "min": 0.5, "max": 10.0, "step": 0.1, "group": "Risk Management", "description": "ATR multiplier for take-profit distance from entry"},
    {"key": "risk_per_trade", "label": "Risk Per Trade", "type": "float", "default": 0.01, "min": 0.001, "max": 0.05, "step": 0.001, "group": "Risk Management", "description": "Fraction of account equity risked per trade"},
]


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
