"""
Strategy 08c: Larry Williams Volatility Breakout V2 (Deferred-Entry Optimized)
===============================================================================
Optimized version for the V3 engine with deferred entry (no look-ahead bias).

Key changes from original s08:
  - Wider TP (6x ATR) compensates for deferred entry slippage
  - Wider SL (2x ATR) prevents premature stops from open gap
  - Trend filter (SMA50) only trades in trend direction
  - Longer cooldown (20 bars) reduces overtrading
  - Tighter breakout factor (0.5) requires stronger breakouts

Validated Results (V3 engine, deferred entry, no look-ahead):
  US30 H1  (50K bars, 2014-2026): PF 1.064, +$8999, 1380 trades, 9/13 positive years
  US30 M5  (15K bars, recent):    PF 1.198, +$3800, 259 trades (recent data only)
  US30 M5  (100K bars, full):     PF 0.827 (not profitable over full period)
  US30 M30 (97K bars):            PF 0.922 (not profitable)
  US30 M15 (100K bars):           PF 0.935 (not profitable)

Best on: US30 H1 (primary), US30 M5 (recent conditions only)
Avoid:   M15, M30 (insufficient edge with deferred entry)
"""

DEFAULTS = {
    "breakout_factor":    0.5,
    "atr_period":         14,
    "atr_sl_mult":        2.0,
    "atr_tp_mult":        6.0,
    "cooldown_bars":      20,
    "risk_per_trade":     0.01,
    "trend_sma_period":   50,
}

SETTINGS = [
    {"key": "breakout_factor", "label": "Breakout Factor", "type": "float", "default": 0.5, "min": 0.1, "max": 2.0, "step": 0.05, "group": "Entry Rules", "description": "Multiplier of previous bar range for breakout level"},
    {"key": "atr_period", "label": "ATR Period", "type": "int", "default": 14, "min": 5, "max": 50, "step": 1, "group": "Indicator Settings", "description": "ATR lookback period"},
    {"key": "atr_sl_mult", "label": "ATR Stop-Loss Mult", "type": "float", "default": 2.0, "min": 0.5, "max": 5.0, "step": 0.1, "group": "Risk Management", "description": "ATR multiplier for stop-loss (wider to survive open gaps)"},
    {"key": "atr_tp_mult", "label": "ATR Take-Profit Mult", "type": "float", "default": 6.0, "min": 2.0, "max": 10.0, "step": 0.5, "group": "Risk Management", "description": "ATR multiplier for take-profit (wide for trend capture)"},
    {"key": "cooldown_bars", "label": "Cooldown Bars", "type": "int", "default": 20, "min": 1, "max": 100, "step": 1, "group": "Filters", "description": "Minimum bars between trades"},
    {"key": "risk_per_trade", "label": "Risk Per Trade", "type": "float", "default": 0.01, "min": 0.001, "max": 0.05, "step": 0.001, "group": "Risk Management", "description": "Fraction of equity risked per trade"},
    {"key": "trend_sma_period", "label": "Trend SMA Period", "type": "int", "default": 50, "min": 10, "max": 200, "step": 5, "group": "Filters", "description": "SMA period for trend direction filter"},
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


class LarryWilliamsV2:
    def init(self, bars, s):
        self.s = dict(DEFAULTS)
        self.s.update(s)
        self.bars = bars
        self.atr_values = _atr(bars, self.s["atr_period"])
        self.sma_values = _sma(bars, self.s["trend_sma_period"])
        self.last_trade_bar = -999

    def on_bar(self, i, bar):
        s = self.s
        if i < max(s["atr_period"], s["trend_sma_period"]) + 2:
            return
        atr_val = self.atr_values[i]
        if atr_val <= 0:
            return

        prev = self.bars[i - 1]
        prev_range = prev["high"] - prev["low"]
        if prev_range <= 0:
            return

        buy_level = bar["open"] + s["breakout_factor"] * prev_range
        sell_level = bar["open"] - s["breakout_factor"] * prev_range
        close = bar["close"]

        if len(open_trades) > 0:
            return
        if i - self.last_trade_bar < s["cooldown_bars"]:
            return

        # Trend filter: only trade in SMA direction
        sma = self.sma_values[i]
        if sma <= 0:
            return

        # Long breakout (price above SMA = uptrend)
        if bar["high"] >= buy_level and close > buy_level and close > sma:
            sl = close - atr_val * s["atr_sl_mult"]
            tp = close + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
            self.last_trade_bar = i

        # Short breakout (price below SMA = downtrend)
        elif bar["low"] <= sell_level and close < sell_level and close < sma:
            sl = close + atr_val * s["atr_sl_mult"]
            tp = close - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
            self.last_trade_bar = i
