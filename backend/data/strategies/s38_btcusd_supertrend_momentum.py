"""
Strategy 38: BTCUSD SuperTrend Momentum
==========================================
Simplified SuperTrend + EMA trend-following strategy.

Core idea: Use SuperTrend for primary trend direction, confirm with
EMA(21) alignment. Enter when both agree; exit on SuperTrend flip.

Logic:
  1. Compute SuperTrend(10, 3.0) for trend direction.
  2. Compute EMA(21) for trend confirmation.
  3. Long:  SuperTrend bullish (price above ST line) AND close > EMA.
  4. Short: SuperTrend bearish (price below ST line) AND close < EMA.
  5. SL at SuperTrend line, TP at entry +/- ATR * atr_tp_mult.
  6. Exit: close trade when SuperTrend flips direction.

Removed from original: RSI filter, ADX filter, session filter,
EMA pullback proximity requirement. These stacked filters killed
nearly all entries.

Markets : BTCUSD (crypto)
Timeframe: H1
"""

DEFAULTS = {
    "st_period":      10,
    "st_mult":        3.0,
    "ema_period":     21,
    "atr_period":     14,
    "atr_tp_mult":    3.0,
    "risk_per_trade": 0.01,
}


SETTINGS = [
    {"key": "st_period",      "label": "SuperTrend Period",     "type": "int",   "default": 10,   "min": 5,     "max": 50,   "step": 1,     "group": "Indicator Settings", "description": "Lookback period for SuperTrend ATR calculation"},
    {"key": "st_mult",        "label": "SuperTrend Multiplier", "type": "float", "default": 3.0,  "min": 1.0,   "max": 10.0, "step": 0.1,   "group": "Indicator Settings", "description": "ATR multiplier for SuperTrend band width"},
    {"key": "ema_period",     "label": "EMA Period",            "type": "int",   "default": 21,   "min": 5,     "max": 100,  "step": 1,     "group": "Indicator Settings", "description": "Period for the EMA trend confirmation filter"},
    {"key": "atr_period",     "label": "ATR Period",            "type": "int",   "default": 14,   "min": 5,     "max": 50,   "step": 1,     "group": "Indicator Settings", "description": "Lookback period for ATR used in TP calculation"},
    {"key": "atr_tp_mult",    "label": "ATR TP Multiplier",    "type": "float", "default": 3.0,  "min": 1.0,   "max": 10.0, "step": 0.5,   "group": "Exit Rules",         "description": "Take-profit distance as a multiple of ATR from entry price"},
    {"key": "risk_per_trade", "label": "Risk Per Trade",       "type": "float", "default": 0.01, "min": 0.001, "max": 0.05, "step": 0.001, "group": "Risk Management",    "description": "Fraction of account equity risked per trade (0.01 = 1%)"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atr(bars, period):
    """Wilder ATR (EMA-smoothed true range)."""
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


def _supertrend(bars, atr_vals, period, mult):
    """Returns (st_line, direction) arrays. direction: 1=bullish, -1=bearish."""
    n = len(bars)
    st = [0.0] * n
    direction = [1] * n
    upper = [0.0] * n
    lower = [0.0] * n
    for i in range(period, n):
        hl2 = (bars[i]["high"] + bars[i]["low"]) / 2
        atr = atr_vals[i] if atr_vals[i] > 0 else 0
        upper[i] = hl2 + mult * atr
        lower[i] = hl2 - mult * atr
        if i > period:
            if lower[i] < lower[i - 1] and bars[i - 1]["close"] > lower[i - 1]:
                lower[i] = lower[i - 1]
            if upper[i] > upper[i - 1] and bars[i - 1]["close"] < upper[i - 1]:
                upper[i] = upper[i - 1]
        if i == period:
            direction[i] = 1
        else:
            prev_dir = direction[i - 1]
            if prev_dir == 1 and bars[i]["close"] < lower[i]:
                direction[i] = -1
            elif prev_dir == -1 and bars[i]["close"] > upper[i]:
                direction[i] = 1
            else:
                direction[i] = prev_dir
        st[i] = lower[i] if direction[i] == 1 else upper[i]
    return st, direction


def _ema(bars, period):
    """Compute EMA on close prices."""
    n = len(bars)
    out = [0.0] * n
    if period > n:
        return out
    out[period - 1] = sum(bars[j]["close"] for j in range(period)) / period
    k = 2.0 / (period + 1)
    for i in range(period, n):
        out[i] = bars[i]["close"] * k + out[i - 1] * (1 - k)
    return out


# ---------------------------------------------------------------------------
# Strategy class
# ---------------------------------------------------------------------------

class BtcSupertrendMomentum:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.atr_vals = _atr(bars, self.s["atr_period"])
        st_atr = _atr(bars, self.s["st_period"])
        self.st_line, self.st_dir = _supertrend(
            bars, st_atr, self.s["st_period"], self.s["st_mult"]
        )
        self.ema_vals = _ema(bars, self.s["ema_period"])

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["st_period"], s["ema_period"], s["atr_period"]) + 2
        if i < warmup:
            return

        close = bar["close"]
        cur_dir = self.st_dir[i]
        prev_dir = self.st_dir[i - 1] if i > 0 else 0

        # --- Exit: close trade when SuperTrend flips direction ---
        if cur_dir != prev_dir and prev_dir != 0 and len(open_trades) > 0:
            for t in list(open_trades):
                close_trade(t, i, close, "st_flip")

        # --- No new trades if already positioned ---
        if len(open_trades) > 0:
            return

        # --- Validate indicators ---
        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        ema_val = self.ema_vals[i]
        if ema_val <= 0:
            return

        st_val = self.st_line[i]
        if st_val <= 0:
            return

        # --- Entry: SuperTrend direction + EMA confirmation ---
        if cur_dir == 1 and close > ema_val:
            # Bullish: price above SuperTrend line AND above EMA
            sl = st_val
            if sl >= close:
                return
            tp = close + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        elif cur_dir == -1 and close < ema_val:
            # Bearish: price below SuperTrend line AND below EMA
            sl = st_val
            if sl <= close:
                return
            tp = close - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
