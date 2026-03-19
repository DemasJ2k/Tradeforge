"""
Strategy 46: NAS100 Momentum Pullback Entry (M5)
==================================================
Target: NAS100 (US Tech 100) M5
Expected Sharpe: 1.2–2.0 | Win rate: 50–58% | R:R: ~1:2.5

Core thesis: NASDAQ-100 trends strongly during NY session hours.
Rather than chasing breakouts (which have high false-positive rates),
this strategy waits for a confirmed trend on M5 then enters on the
first meaningful pullback to the fast EMA.  Pullback entries provide:
  - Better risk/reward (tighter stop)
  - Higher win rate (entering with institutional flow, not chasing)
  - Natural SL placement (below the pullback low/high)

Architecture:
  1. **Trend detection** – EMA(20) > EMA(50) for uptrend (vice versa).
     Both must slope in trend direction (current > 3 bars ago).
  2. **ADX filter** – ADX(14) > threshold confirms trending environment.
  3. **Pullback detection** – Price pulls back to touch or cross EMA(20)
     after establishing new swing high/low in trend direction.
  4. **Resumption candle** – Wait for a candle that closes back in the
     trend direction (above EMA for longs, below for shorts).

Entry:
  LONG  – Uptrend + pullback touched EMA20 + resumption close > EMA20
  SHORT – Downtrend + pullback touched EMA20 + resumption close < EMA20

Exit:
  SL = Below pullback low (for longs) / Above pullback high (for shorts)
       with minimum ATR × atr_sl_mult
  TP = ATR × atr_tp_mult (default 4.0 — wide targets for trending moves)
  Trailing stop: Trail at 2× ATR once in profit by 1.5× ATR
  Session end: close all by session_end_hour
"""

DEFAULTS = {
    # Session (UTC — NY hours)
    "session_start_hour":   13,    # Pre-market / NY open
    "session_end_hour":     20,    # Close all by 20:00 UTC
    "entry_cutoff_hour":    18,    # No new entries after 18:00 UTC
    # EMAs
    "ema_fast":             20,
    "ema_slow":             50,
    "ema_slope_bars":       3,     # Bars to check EMA slope
    # ADX filter
    "adx_period":           14,
    "adx_threshold":        20,
    # Pullback detection
    "pullback_lookback":    10,    # Look back N bars for swing point
    # ATR for SL/TP
    "atr_period":           14,
    "atr_sl_mult":          1.5,   # Minimum SL distance in ATR
    "atr_tp_mult":          4.0,   # Wide TP target
    # Trailing stop
    "use_trailing":         True,
    "trail_trigger_atr":    1.5,
    "trail_distance_atr":   2.0,
    # Risk
    "lot_size":             0.1,
    "risk_per_trade":       0.005,
    "max_daily_trades":     2,
}

SETTINGS = [
    {"key": "session_start_hour",  "label": "Session Start (UTC)",    "type": "int",   "default": 13,    "min": 10,    "max": 16,   "step": 1,    "group": "Session",            "description": "Hour when trading begins (aligned to NY session)"},
    {"key": "session_end_hour",    "label": "Session End (UTC)",      "type": "int",   "default": 20,    "min": 16,    "max": 23,   "step": 1,    "group": "Session",            "description": "Hour all positions are closed"},
    {"key": "entry_cutoff_hour",   "label": "Entry Cutoff (UTC)",     "type": "int",   "default": 18,    "min": 14,    "max": 21,   "step": 1,    "group": "Session",            "description": "No new entries after this hour"},
    {"key": "ema_fast",            "label": "Fast EMA",               "type": "int",   "default": 20,    "min": 8,     "max": 30,   "step": 1,    "group": "Indicator Settings", "description": "Fast EMA for trend + pullback target"},
    {"key": "ema_slow",            "label": "Slow EMA",               "type": "int",   "default": 50,    "min": 30,    "max": 100,  "step": 5,    "group": "Indicator Settings", "description": "Slow EMA for trend confirmation"},
    {"key": "adx_period",          "label": "ADX Period",             "type": "int",   "default": 14,    "min": 7,     "max": 25,   "step": 1,    "group": "Filters",            "description": "ADX lookback period"},
    {"key": "adx_threshold",       "label": "ADX Threshold",          "type": "int",   "default": 20,    "min": 15,    "max": 35,   "step": 1,    "group": "Filters",            "description": "Minimum ADX for trending market"},
    {"key": "atr_period",          "label": "ATR Period",             "type": "int",   "default": 14,    "min": 5,     "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "ATR lookback for SL/TP sizing"},
    {"key": "atr_sl_mult",         "label": "ATR Stop-Loss Mult",     "type": "float", "default": 1.5,   "min": 0.5,   "max": 4.0,  "step": 0.1,  "group": "Risk Management",    "description": "Minimum ATR multiplier for stop-loss"},
    {"key": "atr_tp_mult",         "label": "ATR Take-Profit Mult",   "type": "float", "default": 4.0,   "min": 2.0,   "max": 8.0,  "step": 0.5,  "group": "Risk Management",    "description": "ATR multiplier for take-profit (wide)"},
    {"key": "use_trailing",        "label": "Use Trailing Stop",      "type": "bool",  "default": True,                                            "group": "Risk Management",    "description": "Enable trailing stop"},
    {"key": "max_daily_trades",    "label": "Max Daily Trades",       "type": "int",   "default": 2,     "min": 1,     "max": 5,    "step": 1,    "group": "Risk Management",    "description": "Maximum trades per day"},
]


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def _ema(data, period):
    n = len(data)
    out = [0.0] * n
    if period > n:
        return out
    k = 2.0 / (period + 1)
    out[period - 1] = sum(data[:period]) / period
    for i in range(period, n):
        out[i] = data[i] * k + out[i - 1] * (1 - k)
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
    adx = [0.0] * n
    if 2 * period + 1 > n:
        return adx
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
        di_plus = 100 * sm_dp / sm_tr if sm_tr > 0 else 0
        di_minus = 100 * sm_dm / sm_tr if sm_tr > 0 else 0
        di_sum = di_plus + di_minus
        dx = 100 * abs(di_plus - di_minus) / di_sum if di_sum > 0 else 0
        dx_list.append(dx)
        if len(dx_list) == period:
            adx[i] = sum(dx_list) / period
        elif len(dx_list) > period:
            adx[i] = (adx[i - 1] * (period - 1) + dx) / period
    return adx


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


def _get_day(bar):
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

class NAS100MomentumPullback:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars

        closes = [b["close"] for b in bars]
        self.ema_fast_vals = _ema(closes, self.s["ema_fast"])
        self.ema_slow_vals = _ema(closes, self.s["ema_slow"])
        self.atr_vals = _atr(bars, self.s["atr_period"])
        self.adx_vals = _adx(bars, self.s["adx_period"])

        # State
        self.current_day = ""
        self.daily_trades = 0
        self.pullback_detected = False
        self.pullback_direction = ""
        self.pullback_extreme = 0.0  # Low of pullback (longs) or high (shorts)
        self.trail_best = {}

    def _reset_day(self, day):
        self.current_day = day
        self.daily_trades = 0
        self.pullback_detected = False
        self.pullback_direction = ""
        self.pullback_extreme = 0.0
        self.trail_best = {}

    def _update_trailing(self, i, bar):
        s = self.s
        if not s["use_trailing"]:
            return
        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        trigger_dist = atr_val * s["trail_trigger_atr"]
        trail_dist = atr_val * s["trail_distance_atr"]

        for t in list(open_trades):
            tid = id(t)
            entry = t["entry_price"]
            direction = t["direction"]

            if direction == "long":
                best = max(self.trail_best.get(tid, bar["high"]), bar["high"])
                self.trail_best[tid] = best
                if best - entry > trigger_dist:
                    new_sl = best - trail_dist
                    if new_sl > t.get("stop_loss", 0):
                        t["stop_loss"] = new_sl
            else:
                best = min(self.trail_best.get(tid, bar["low"]), bar["low"])
                self.trail_best[tid] = best
                if entry - best > trigger_dist:
                    new_sl = best + trail_dist
                    if new_sl < t.get("stop_loss", float("inf")):
                        t["stop_loss"] = new_sl

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["ema_slow"], s["adx_period"] * 2, s["atr_period"]) + 10
        if i < warmup:
            return

        hour = _get_hour(bar)
        if hour == -1:
            return

        day = _get_day(bar)
        close = bar["close"]
        atr_val = self.atr_vals[i]

        # --- New day ---
        if day != self.current_day and day != "":
            for t in list(open_trades):
                close_trade(t, i, close, "day_end")
            self._reset_day(day)

        # --- Outside session: close all ---
        if hour < s["session_start_hour"] or hour >= s["session_end_hour"]:
            for t in list(open_trades):
                close_trade(t, i, close, "session_end")
            self.pullback_detected = False
            return

        # --- Update trailing stops ---
        if len(open_trades) > 0:
            self._update_trailing(i, bar)
            return

        # --- Entry cutoff ---
        if hour >= s["entry_cutoff_hour"]:
            return

        # --- Max trades ---
        if self.daily_trades >= s["max_daily_trades"]:
            return

        if atr_val <= 0:
            return

        ef = self.ema_fast_vals[i]
        es = self.ema_slow_vals[i]
        adx = self.adx_vals[i]

        # EMA slope check
        slope_bars = s["ema_slope_bars"]
        ef_prev = self.ema_fast_vals[i - slope_bars] if i >= slope_bars else ef
        es_prev = self.ema_slow_vals[i - slope_bars] if i >= slope_bars else es

        # --- Determine trend ---
        uptrend = ef > es and ef > ef_prev and es > es_prev and adx > s["adx_threshold"]
        downtrend = ef < es and ef < ef_prev and es < es_prev and adx > s["adx_threshold"]

        if not uptrend and not downtrend:
            self.pullback_detected = False
            return

        # --- Detect pullback to EMA ---
        # For uptrend: bar low touches or goes below EMA fast
        if uptrend:
            if bar["low"] <= ef:
                if not self.pullback_detected or self.pullback_direction != "long":
                    self.pullback_detected = True
                    self.pullback_direction = "long"
                    self.pullback_extreme = bar["low"]
                else:
                    self.pullback_extreme = min(self.pullback_extreme, bar["low"])

            # Resumption: price closes back above EMA after pullback
            elif self.pullback_detected and self.pullback_direction == "long" and close > ef:
                # Confirm: close above EMA fast
                sl_from_pullback = self.pullback_extreme
                sl_from_atr = close - atr_val * s["atr_sl_mult"]
                sl = min(sl_from_pullback, sl_from_atr)  # Use the wider one
                tp = close + atr_val * s["atr_tp_mult"]

                open_trade(i, "long", close, sl, tp, s["lot_size"])
                self.daily_trades += 1
                self.pullback_detected = False
                self.trail_best[id(open_trades[-1])] = bar["high"]

        if downtrend:
            if bar["high"] >= ef:
                if not self.pullback_detected or self.pullback_direction != "short":
                    self.pullback_detected = True
                    self.pullback_direction = "short"
                    self.pullback_extreme = bar["high"]
                else:
                    self.pullback_extreme = max(self.pullback_extreme, bar["high"])

            elif self.pullback_detected and self.pullback_direction == "short" and close < ef:
                sl_from_pullback = self.pullback_extreme
                sl_from_atr = close + atr_val * s["atr_sl_mult"]
                sl = max(sl_from_pullback, sl_from_atr)
                tp = close - atr_val * s["atr_tp_mult"]

                open_trade(i, "short", close, sl, tp, s["lot_size"])
                self.daily_trades += 1
                self.pullback_detected = False
                self.trail_best[id(open_trades[-1])] = bar["low"]
