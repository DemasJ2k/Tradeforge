"""
Strategy 08: Larry Williams Volatility Breakout
=================================================
Inspired by: Larry Williams — 11,000% return in Robbins World Cup.
Kevin McCormick (trained by Williams, 253.8% in 2021).

Core idea: Use previous day's range to set breakout levels.
  BuyStop  = Open + factor * (PrevHigh - PrevLow)
  SellStop = Open - factor * (PrevHigh - PrevLow)
  Factor typically 0.25 (as described by Williams).

Markets : Universal (best on futures, forex)
Timeframe: Daily bars (swing)
"""

DEFAULTS = {
    "breakout_factor":  1.0,    # High factor for H1 — only strongest breakouts
    "atr_period":       14,
    "atr_sl_mult":      1.5,    # Tighter SL (was 2.0 - loss too large vs wins)
    "atr_tp_mult":      2.5,    # Balanced TP (was 3.5 - unreachable with early exit removed)
    "williams_r_period": 10,    # Williams %R — used only for entry filter now
    "williams_r_ob":    -20,
    "williams_r_os":    -80,
    "use_wr_exit":      False,  # Disabled — was cutting winners short, creating neg asymmetry
    "cooldown_bars":    15,     # Longer cooldown to reduce overtrading
    "risk_per_trade":   0.01,
}


SETTINGS = [
    {"key": "breakout_factor", "label": "Breakout Factor", "type": "float", "default": 1.0, "min": 0.1, "max": 3.0, "step": 0.05, "group": "Entry Rules", "description": "Multiplier of previous bar range to set breakout levels above/below the open"},
    {"key": "atr_period", "label": "ATR Period", "type": "int", "default": 14, "min": 5, "max": 50, "step": 1, "group": "Indicator Settings", "description": "Lookback period for Average True Range calculation"},
    {"key": "atr_sl_mult", "label": "ATR Stop-Loss Multiplier", "type": "float", "default": 1.5, "min": 0.5, "max": 5.0, "step": 0.1, "group": "Risk Management", "description": "ATR multiplier for stop-loss distance from entry"},
    {"key": "atr_tp_mult", "label": "ATR Take-Profit Multiplier", "type": "float", "default": 2.5, "min": 0.5, "max": 10.0, "step": 0.1, "group": "Risk Management", "description": "ATR multiplier for take-profit distance from entry"},
    {"key": "williams_r_period", "label": "Williams %R Period", "type": "int", "default": 10, "min": 5, "max": 30, "step": 1, "group": "Indicator Settings", "description": "Lookback period for Williams %R oscillator"},
    {"key": "williams_r_ob", "label": "Williams %R Overbought", "type": "int", "default": -20, "min": -10, "max": -30, "step": 1, "group": "Filters", "description": "Overbought threshold for Williams %R (used for exit filter if enabled)"},
    {"key": "williams_r_os", "label": "Williams %R Oversold", "type": "int", "default": -80, "min": -70, "max": -95, "step": 1, "group": "Filters", "description": "Oversold threshold for Williams %R (used for exit filter if enabled)"},
    {"key": "use_wr_exit", "label": "Use Williams %R Exit", "type": "bool", "default": False, "group": "Exit Rules", "description": "Enable early exit when Williams %R reaches overbought/oversold levels"},
    {"key": "cooldown_bars", "label": "Cooldown Bars", "type": "int", "default": 15, "min": 0, "max": 50, "step": 1, "group": "Filters", "description": "Minimum bars to wait between trades to prevent overtrading"},
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


def _williams_r(bars, period):
    """Williams %R oscillator."""
    n = len(bars)
    out = [0.0] * n
    for i in range(period - 1, n):
        start = i - period + 1
        hh = max(bars[j]["high"] for j in range(start, i + 1))
        ll = min(bars[j]["low"] for j in range(start, i + 1))
        if hh == ll:
            out[i] = -50.0
        else:
            out[i] = -100 * (hh - bars[i]["close"]) / (hh - ll)
    return out


class LarryWilliamsBreakout:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.atr_values = _atr(bars, self.s["atr_period"])
        self.wr = _williams_r(bars, self.s["williams_r_period"])
        self.last_trade_bar = -999

    def on_bar(self, i, bar):
        s = self.s
        if i < max(s["atr_period"], s["williams_r_period"]) + 2:
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

        # Optional Williams %R exit (disabled by default — creates neg asymmetry)
        if s.get("use_wr_exit", False):
            for t in list(open_trades):
                if t["direction"] == "long" and self.wr[i] > s["williams_r_ob"]:
                    close_trade(t, i, close, "williams_r_exit")
                    self.last_trade_bar = i
                elif t["direction"] == "short" and self.wr[i] < s["williams_r_os"]:
                    close_trade(t, i, close, "williams_r_exit")
                    self.last_trade_bar = i

        if len(open_trades) > 0:
            return

        # Cooldown filter
        if i - self.last_trade_bar < s.get("cooldown_bars", 5):
            return

        # Long breakout
        if bar["high"] >= buy_level and close > buy_level:
            sl = close - atr_val * s["atr_sl_mult"]
            tp = close + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # Short breakout
        elif bar["low"] <= sell_level and close < sell_level:
            sl = close + atr_val * s["atr_sl_mult"]
            tp = close - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
