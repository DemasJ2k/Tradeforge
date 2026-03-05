"""
Strategy 34: XAUUSD NY Momentum (London-to-NY Continuation)
=============================================================
Inspired by: Institutional order-flow theory — strong London moves
often extend into the New York session via Fibonacci continuation.

Core idea: Measure the London session directional move (07:00–13:00 UTC).
If the move is significant relative to ATR, expect a continuation during
the NY session. Wait for a pullback to the 20-period EMA, then enter in
the London direction. Take-profit at the 1.618 Fibonacci extension of
the London move.

Logic:
  1. Record London open price at london_start_hour (07 UTC).
  2. At ny_start_hour (13 UTC), compute London move and direction.
  3. If abs(london_move) > london_atr_thresh * ATR, the session is
     "trending" — look for a pullback entry during NY.
  4. Long setup (London bullish): wait for close to pull back near EMA
     (close <= ema * 1.002) then bounce (close > open = bullish bar).
  5. Short setup (London bearish): wait for close to rally to EMA
     (close >= ema * 0.998) then reject (close < open = bearish bar).
  6. SL: swing low/high of pullback bar +/- ATR * atr_sl_mult.
  7. TP: London open + London move * fib_target (1.618 extension).
  8. Close all trades at ny_end_hour; max 1 trade per NY session.

Markets : XAUUSD
Timeframe: H1
"""

DEFAULTS = {
    "london_start_hour": 7,
    "ny_start_hour":     13,
    "ny_end_hour":       20,
    "london_atr_thresh": 0.7,
    "ema_period":        20,
    "fib_target":        1.618,
    "atr_period":        14,
    "atr_sl_mult":       1.0,
    "risk_per_trade":    0.01,
}


SETTINGS = [
    {"key": "london_start_hour", "label": "London Start (UTC)",      "type": "int",   "default": 7,     "min": 0,    "max": 23,   "step": 1,    "group": "Session",            "description": "Hour (UTC) marking London open — used as the reference price"},
    {"key": "ny_start_hour",     "label": "NY Start (UTC)",          "type": "int",   "default": 13,    "min": 0,    "max": 23,   "step": 1,    "group": "Session",            "description": "Hour (UTC) when the NY session begins and pullback entries are allowed"},
    {"key": "ny_end_hour",       "label": "NY End (UTC)",            "type": "int",   "default": 20,    "min": 1,    "max": 23,   "step": 1,    "group": "Session",            "description": "Hour (UTC) when the NY session ends and all trades are closed"},
    {"key": "london_atr_thresh", "label": "London Move Threshold",   "type": "float", "default": 0.7,   "min": 0.1,  "max": 3.0,  "step": 0.1,  "group": "Entry Rules",        "description": "Minimum London move size in ATR multiples to qualify as trending"},
    {"key": "ema_period",        "label": "EMA Period",              "type": "int",   "default": 20,    "min": 5,    "max": 100,  "step": 1,    "group": "Indicator Settings", "description": "Period of the Exponential Moving Average used for pullback detection"},
    {"key": "fib_target",        "label": "Fib Extension Target",    "type": "float", "default": 1.618, "min": 1.0,  "max": 3.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Fibonacci extension multiple of London move for take-profit target"},
    {"key": "atr_period",        "label": "ATR Period",              "type": "int",   "default": 14,    "min": 5,    "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "Lookback period for Average True Range calculation"},
    {"key": "atr_sl_mult",       "label": "ATR SL Multiplier",       "type": "float", "default": 1.0,   "min": 0.3,  "max": 3.0,  "step": 0.1,  "group": "Risk Management",    "description": "Stop-loss distance beyond pullback extreme in ATR multiples"},
    {"key": "risk_per_trade",    "label": "Risk Per Trade",          "type": "float", "default": 0.01,  "min": 0.001,"max": 0.05, "step": 0.001,"group": "Risk Management",    "description": "Fraction of account equity risked per trade (0.01 = 1%)"},
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


def _ema(bars, period, key="close"):
    n = len(bars)
    out = [0.0] * n
    if n < period:
        return out
    out[period - 1] = sum(b[key] for b in bars[:period]) / period
    k = 2.0 / (period + 1)
    for i in range(period, n):
        out[i] = bars[i][key] * k + out[i - 1] * (1.0 - k)
    return out


def _get_hour(bar):
    """Extract hour from bar time string. Handles various formats."""
    t = bar.get("time", "")
    if isinstance(t, str):
        for sep in [" ", "T"]:
            if sep in t:
                time_part = t.split(sep)[-1]
                try:
                    return int(time_part.split(":")[0])
                except (ValueError, IndexError):
                    pass
    elif isinstance(t, (int, float)):
        import datetime
        try:
            return datetime.datetime.utcfromtimestamp(t).hour
        except (ValueError, OSError):
            pass
    return -1


def _get_day(bar):
    """Extract date string from bar time for daily grouping."""
    t = bar.get("time", "")
    if isinstance(t, str):
        return t[:10]
    elif isinstance(t, (int, float)):
        import datetime
        try:
            return datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
        except (ValueError, OSError):
            pass
    return ""


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

class XAUUSDNYMomentum:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.atr_vals = _atr(bars, self.s["atr_period"])
        self.ema_vals = _ema(bars, self.s["ema_period"])

        # Session state — reset each day
        self.current_day = ""
        self.london_open_price = 0.0
        self.london_close_price = 0.0
        self.london_move = 0.0
        self.london_direction = 0     # +1 bullish, -1 bearish, 0 neutral
        self.ny_traded = False
        self.london_open_set = False
        self.london_assessed = False

    # ------------------------------------------------------------------
    def _reset_day(self, day):
        self.current_day = day
        self.london_open_price = 0.0
        self.london_close_price = 0.0
        self.london_move = 0.0
        self.london_direction = 0
        self.ny_traded = False
        self.london_open_set = False
        self.london_assessed = False

    # ------------------------------------------------------------------
    def on_bar(self, i, bar):
        s = self.s
        min_warmup = max(s["atr_period"], s["ema_period"]) + 2
        if i < min_warmup:
            return

        hour = _get_hour(bar)
        if hour == -1:
            return

        day = _get_day(bar)
        close = bar["close"]

        # New day — reset state
        if day != self.current_day and day != "":
            self._reset_day(day)

        atr_val = self.atr_vals[i]
        ema_val = self.ema_vals[i]

        # --- Record London open price ---
        if hour == s["london_start_hour"] and not self.london_open_set:
            self.london_open_price = bar["open"]
            self.london_open_set = True
            return

        # --- Assess London move at NY start ---
        if hour == s["ny_start_hour"] and not self.london_assessed:
            self.london_assessed = True
            if not self.london_open_set or self.london_open_price <= 0:
                return
            self.london_close_price = close
            self.london_move = self.london_close_price - self.london_open_price
            move_size = abs(self.london_move)

            if atr_val <= 0:
                return

            # Check if London move is significant
            if move_size >= s["london_atr_thresh"] * atr_val:
                self.london_direction = 1 if self.london_move > 0 else -1
            else:
                self.london_direction = 0
            return

        # --- Pre-London or between sessions: nothing to do ---
        if hour < s["ny_start_hour"] or hour >= s["ny_end_hour"]:
            # Close trades at session end
            if hour >= s["ny_end_hour"]:
                for t in list(open_trades):
                    close_trade(t, i, close, "session_end")
            return

        # --- NY session: manage existing trades ---
        if len(open_trades) > 0:
            return

        # --- NY session: look for pullback entry ---
        if self.ny_traded:
            return
        if self.london_direction == 0:
            return
        if atr_val <= 0 or ema_val <= 0:
            return

        # Pullback proximity threshold (0.2% of price)
        proximity = close * 0.002

        # ------ LONG setup (London was bullish) ------
        if self.london_direction == 1:
            # Price must have pulled back near EMA
            if close <= ema_val + proximity and close >= ema_val - proximity:
                # Confirm bullish bounce: close > open (green bar)
                if close > bar["open"]:
                    sl = bar["low"] - atr_val * s["atr_sl_mult"]
                    # TP at Fibonacci extension of London move
                    tp = self.london_open_price + self.london_move * s["fib_target"]
                    # Sanity: TP must be above entry
                    if tp > close and close > sl:
                        open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
                        self.ny_traded = True

        # ------ SHORT setup (London was bearish) ------
        elif self.london_direction == -1:
            # Price must have rallied back near EMA
            if close >= ema_val - proximity and close <= ema_val + proximity:
                # Confirm bearish rejection: close < open (red bar)
                if close < bar["open"]:
                    sl = bar["high"] + atr_val * s["atr_sl_mult"]
                    # TP at Fibonacci extension of London move (move is negative)
                    tp = self.london_open_price + self.london_move * s["fib_target"]
                    # Sanity: TP must be below entry
                    if tp < close and close < sl:
                        open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
                        self.ny_traded = True
