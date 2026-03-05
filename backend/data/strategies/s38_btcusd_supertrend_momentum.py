"""
Strategy 38: BTCUSD SuperTrend Momentum
==========================================
Inspired by: Oliver Seban's SuperTrend combined with EMA pullback,
RSI filter, and ADX trend-strength confirmation.

Core idea: Use SuperTrend for direction, wait for price to pull back
to the 21 EMA, confirm with RSI (30-70 neutral zone) and ADX (>20
trending). Entry on the pullback bounce; trail stop with SuperTrend.

Logic:
  1. Compute SuperTrend(10, 3.0) for trend direction.
  2. Compute EMA(21) for pullback reference.
  3. Compute RSI(14) to avoid overbought/oversold entries.
  4. Compute ADX(14) to confirm trending market.
  5. Long:  ST bullish + price near EMA from above + RSI 30-70 + ADX > 20.
  6. Short: ST bearish + price near EMA from below + RSI 30-70 + ADX > 20.
  7. SL at SuperTrend line, TP at entry +/- ATR * atr_tp_mult.
  8. Trail: close trade when SuperTrend flips direction.

Markets : BTCUSD (crypto)
Timeframe: H1
"""

DEFAULTS = {
    "st_period":          10,
    "st_mult":            3.0,
    "ema_period":         21,
    "rsi_period":         14,
    "adx_period":         14,
    "adx_min":            20.0,
    "atr_period":         14,
    "atr_tp_mult":        3.0,
    "pullback_pct":       0.005,
    "session_start_hour": 13,
    "session_end_hour":   21,
    "risk_per_trade":     0.01,
}


SETTINGS = [
    {"key": "st_period",          "label": "SuperTrend Period",       "type": "int",   "default": 10,    "min": 5,     "max": 50,   "step": 1,     "group": "Indicator Settings", "description": "Lookback period for SuperTrend ATR calculation"},
    {"key": "st_mult",            "label": "SuperTrend Multiplier",   "type": "float", "default": 3.0,   "min": 1.0,   "max": 10.0, "step": 0.1,   "group": "Indicator Settings", "description": "ATR multiplier for SuperTrend band width"},
    {"key": "ema_period",         "label": "EMA Period",              "type": "int",   "default": 21,    "min": 5,     "max": 100,  "step": 1,     "group": "Indicator Settings", "description": "Period for the Exponential Moving Average pullback reference"},
    {"key": "rsi_period",         "label": "RSI Period",              "type": "int",   "default": 14,    "min": 5,     "max": 50,   "step": 1,     "group": "Indicator Settings", "description": "Lookback period for Relative Strength Index"},
    {"key": "adx_period",         "label": "ADX Period",              "type": "int",   "default": 14,    "min": 5,     "max": 50,   "step": 1,     "group": "Indicator Settings", "description": "Lookback period for Average Directional Index"},
    {"key": "adx_min",            "label": "Min ADX",                 "type": "float", "default": 20.0,  "min": 10.0,  "max": 50.0, "step": 1.0,   "group": "Filters",            "description": "Minimum ADX value required to confirm a trending market"},
    {"key": "atr_period",         "label": "ATR Period",              "type": "int",   "default": 14,    "min": 5,     "max": 50,   "step": 1,     "group": "Indicator Settings", "description": "Lookback period for ATR used in TP calculation"},
    {"key": "atr_tp_mult",        "label": "ATR TP Multiplier",      "type": "float", "default": 3.0,   "min": 1.0,   "max": 10.0, "step": 0.5,   "group": "Exit Rules",         "description": "Take-profit distance as a multiple of ATR from entry price"},
    {"key": "pullback_pct",       "label": "Pullback Threshold %",   "type": "float", "default": 0.005, "min": 0.001, "max": 0.02, "step": 0.001, "group": "Entry Rules",        "description": "Maximum percentage distance from EMA to qualify as a pullback (0.005 = 0.5%)"},
    {"key": "session_start_hour", "label": "Session Start (UTC)",    "type": "int",   "default": 13,    "min": 0,     "max": 23,   "step": 1,     "group": "Session",            "description": "UTC hour when the trading session begins"},
    {"key": "session_end_hour",   "label": "Session End (UTC)",      "type": "int",   "default": 21,    "min": 1,     "max": 23,   "step": 1,     "group": "Session",            "description": "UTC hour when the trading session ends"},
    {"key": "risk_per_trade",     "label": "Risk Per Trade",         "type": "float", "default": 0.01,  "min": 0.001, "max": 0.05, "step": 0.001, "group": "Risk Management",    "description": "Fraction of account equity risked per trade (0.01 = 1%)"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _get_hour(bar):
    t = bar.get("time", "")
    if isinstance(t, str):
        for sep in [" ", "T"]:
            if sep in t:
                try:
                    return int(t.split(sep)[-1].split(":")[0])
                except (ValueError, IndexError):
                    pass
    elif isinstance(t, (int, float)):
        import datetime
        try:
            return datetime.datetime.utcfromtimestamp(t).hour
        except (ValueError, OSError):
            pass
    return -1


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
    # Seed with SMA
    out[period - 1] = sum(bars[j]["close"] for j in range(period)) / period
    k = 2.0 / (period + 1)
    for i in range(period, n):
        out[i] = bars[i]["close"] * k + out[i - 1] * (1 - k)
    return out


def _rsi(bars, period):
    """Compute RSI on close prices."""
    n = len(bars)
    out = [50.0] * n
    if period + 1 > n:
        return out
    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        delta = bars[i]["close"] - bars[i - 1]["close"]
        if delta > 0:
            gains[i] = delta
        else:
            losses[i] = -delta
    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    if avg_loss > 0:
        rs = avg_gain / avg_loss
        out[period] = 100.0 - 100.0 / (1.0 + rs)
    else:
        out[period] = 100.0
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            out[i] = 100.0 - 100.0 / (1.0 + rs)
        else:
            out[i] = 100.0
    return out


def _adx(bars, period):
    """Compute ADX. Returns adx[] array."""
    n = len(bars)
    out = [0.0] * n
    if period + 1 > n:
        return out
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    tr = [0.0] * n
    for i in range(1, n):
        up_move = bars[i]["high"] - bars[i - 1]["high"]
        down_move = bars[i - 1]["low"] - bars[i]["low"]
        plus_dm[i] = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm[i] = down_move if down_move > up_move and down_move > 0 else 0.0
        tr[i] = max(bars[i]["high"] - bars[i]["low"],
                     abs(bars[i]["high"] - bars[i - 1]["close"]),
                     abs(bars[i]["low"] - bars[i - 1]["close"]))
    # Smooth with Wilder's method
    smooth_tr = [0.0] * n
    smooth_plus = [0.0] * n
    smooth_minus = [0.0] * n
    smooth_tr[period] = sum(tr[1:period + 1])
    smooth_plus[period] = sum(plus_dm[1:period + 1])
    smooth_minus[period] = sum(minus_dm[1:period + 1])
    for i in range(period + 1, n):
        smooth_tr[i] = smooth_tr[i - 1] - smooth_tr[i - 1] / period + tr[i]
        smooth_plus[i] = smooth_plus[i - 1] - smooth_plus[i - 1] / period + plus_dm[i]
        smooth_minus[i] = smooth_minus[i - 1] - smooth_minus[i - 1] / period + minus_dm[i]
    # DI+ / DI- / DX
    dx = [0.0] * n
    for i in range(period, n):
        if smooth_tr[i] > 0:
            di_plus = 100.0 * smooth_plus[i] / smooth_tr[i]
            di_minus = 100.0 * smooth_minus[i] / smooth_tr[i]
        else:
            di_plus = 0.0
            di_minus = 0.0
        di_sum = di_plus + di_minus
        dx[i] = 100.0 * abs(di_plus - di_minus) / di_sum if di_sum > 0 else 0.0
    # ADX = smoothed DX
    start = period * 2
    if start >= n:
        return out
    out[start] = sum(dx[period:start + 1]) / (period + 1)
    for i in range(start + 1, n):
        out[i] = (out[i - 1] * (period - 1) + dx[i]) / period
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
        self.rsi_vals = _rsi(bars, self.s["rsi_period"])
        self.adx_vals = _adx(bars, self.s["adx_period"])
        self.prev_dir = 0

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["st_period"], s["ema_period"], s["rsi_period"],
                      s["adx_period"] * 2) + 2
        if i < warmup:
            return

        close = bar["close"]
        cur_dir = self.st_dir[i]
        prev_dir = self.st_dir[i - 1] if i > 0 else 0

        # --- Trail / exit: close trade when SuperTrend flips ---
        if cur_dir != prev_dir and prev_dir != 0 and len(open_trades) > 0:
            for t in list(open_trades):
                close_trade(t, i, close, "st_flip")

        # --- Session filter ---
        hour = _get_hour(bar)
        if hour == -1:
            return
        if s["session_start_hour"] <= s["session_end_hour"]:
            in_session = s["session_start_hour"] <= hour < s["session_end_hour"]
        else:
            in_session = hour >= s["session_start_hour"] or hour < s["session_end_hour"]
        if not in_session:
            return

        # --- No new trades if already positioned ---
        if len(open_trades) > 0:
            return

        # --- Filter checks ---
        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        ema_val = self.ema_vals[i]
        if ema_val <= 0:
            return

        rsi_val = self.rsi_vals[i]
        adx_val = self.adx_vals[i]

        # RSI must be in neutral zone
        if rsi_val < 30 or rsi_val > 70:
            return

        # ADX must confirm trend
        if adx_val < s["adx_min"]:
            return

        # Pullback: price must be near EMA
        dist_pct = abs(close - ema_val) / ema_val
        if dist_pct > s["pullback_pct"]:
            return

        st_val = self.st_line[i]
        if st_val <= 0:
            return

        # --- Entry logic ---
        if cur_dir == 1 and close >= ema_val:
            # Bullish ST + price pulled back to EMA from above
            sl = st_val
            if sl >= close:
                return
            tp = close + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        elif cur_dir == -1 and close <= ema_val:
            # Bearish ST + price pulled back to EMA from below
            sl = st_val
            if sl <= close:
                return
            tp = close - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
