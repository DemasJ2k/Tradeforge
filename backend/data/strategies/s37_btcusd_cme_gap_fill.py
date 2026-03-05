"""
Strategy 37: BTCUSD CME Gap Fill
==================================
Inspired by: Institutional gap-fill behavior observed on BTC CME futures.

Core idea: Bitcoin CME futures close Friday 17:00 ET and reopen Sunday 18:00 ET.
Price action during the weekend (on spot markets) creates a gap between Friday
close and Monday open. Historically ~70-80% of CME gaps get filled within the
first few hours of Monday trading.

Logic:
  1. Track Friday's last closing price (day_of_week == 4).
  2. On Monday (day_of_week == 0), compute gap = Monday open - Friday close.
  3. Qualify gap: min_gap <= abs(gap) <= max_gap.
  4. Wait for a reversal candle toward the gap fill direction.
     - Gap up  -> short on bearish candle toward Friday close.
     - Gap down -> long on bullish candle toward Friday close.
  5. SL: Weekend extreme + buffer_usd.
  6. TP: Friday close level (full gap fill).
  7. Only trade Monday 00:00-12:00 UTC; max 2 entries per Monday.

Markets : BTCUSD (crypto / CME futures)
Timeframe: 5m (intraday)
"""

DEFAULTS = {
    "min_gap":            200.0,
    "max_gap":            2000.0,
    "buffer_usd":         100.0,
    "atr_period":         14,
    "monday_end_hour":    12,
    "risk_per_trade":     0.01,
    "max_monday_trades":  2,
}


SETTINGS = [
    {"key": "min_gap",           "label": "Min Gap ($)",            "type": "float", "default": 200.0,  "min": 50.0,   "max": 1000.0,  "step": 50.0,  "group": "Gap Rules",       "description": "Minimum gap size in USD required to qualify for a trade"},
    {"key": "max_gap",           "label": "Max Gap ($)",            "type": "float", "default": 2000.0, "min": 500.0,  "max": 10000.0, "step": 100.0, "group": "Gap Rules",       "description": "Maximum gap size in USD; gaps larger than this are skipped as too risky"},
    {"key": "buffer_usd",        "label": "SL Buffer ($)",          "type": "float", "default": 100.0,  "min": 10.0,   "max": 500.0,   "step": 10.0,  "group": "Risk Management", "description": "Dollar buffer beyond the gap extreme for stop-loss placement"},
    {"key": "atr_period",        "label": "ATR Period",             "type": "int",   "default": 14,     "min": 5,      "max": 50,      "step": 1,     "group": "Indicator Settings", "description": "Lookback period for Average True Range calculation"},
    {"key": "monday_end_hour",   "label": "Monday Cutoff Hour (UTC)", "type": "int", "default": 12,     "min": 4,      "max": 20,      "step": 1,     "group": "Session",         "description": "UTC hour after which no new gap-fill trades are opened on Monday"},
    {"key": "risk_per_trade",    "label": "Risk Per Trade",         "type": "float", "default": 0.01,   "min": 0.001,  "max": 0.05,    "step": 0.001, "group": "Risk Management", "description": "Fraction of account equity risked per trade (0.01 = 1%)"},
    {"key": "max_monday_trades", "label": "Max Monday Trades",      "type": "int",   "default": 2,      "min": 1,      "max": 5,       "step": 1,     "group": "Risk Management", "description": "Maximum number of gap-fill entries allowed per Monday session"},
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


def _get_day_of_week(bar):
    """Return weekday: 0=Monday ... 4=Friday. Returns -1 on failure."""
    t = bar.get("time", "")
    if isinstance(t, str):
        try:
            import datetime
            fmt = "%Y-%m-%d" if "-" in t else "%Y.%m.%d"
            dt = datetime.datetime.strptime(t[:10], fmt)
            return dt.weekday()
        except (ValueError, IndexError):
            pass
    elif isinstance(t, (int, float)):
        import datetime
        try:
            return datetime.datetime.utcfromtimestamp(t).weekday()
        except (ValueError, OSError):
            pass
    return -1


class BtcCmeGapFill:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.atr_vals = _atr(bars, self.s["atr_period"])

        # State tracking
        self.friday_close = 0.0
        self.friday_recorded = False

        self.monday_gap = 0.0
        self.gap_direction = 0        # 1 = gap up, -1 = gap down
        self.gap_qualified = False
        self.monday_trades = 0
        self.monday_high = 0.0
        self.monday_low = float("inf")
        self.last_monday_date = ""
        self.entry_attempted = False

    def _get_date_str(self, bar):
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

    def on_bar(self, i, bar):
        s = self.s
        if i < s["atr_period"] + 2:
            return

        dow = _get_day_of_week(bar)
        hour = _get_hour(bar)
        if dow == -1 or hour == -1:
            return

        close = bar["close"]

        # --- Friday: record the last close ---
        if dow == 4:
            self.friday_close = close
            self.friday_recorded = True
            return

        # --- Saturday / Sunday: skip ---
        if dow in (5, 6):
            return

        # --- Monday: gap-fill logic ---
        if dow == 0:
            date_str = self._get_date_str(bar)

            # Reset state on new Monday
            if date_str != self.last_monday_date:
                self.last_monday_date = date_str
                self.monday_trades = 0
                self.monday_high = bar["high"]
                self.monday_low = bar["low"]
                self.gap_qualified = False
                self.gap_direction = 0
                self.entry_attempted = False

                # Compute gap if Friday close was recorded
                if self.friday_recorded and self.friday_close > 0:
                    self.monday_gap = bar["open"] - self.friday_close
                    abs_gap = abs(self.monday_gap)
                    if s["min_gap"] <= abs_gap <= s["max_gap"]:
                        self.gap_qualified = True
                        if self.monday_gap > 0:
                            self.gap_direction = 1   # gap up
                        else:
                            self.gap_direction = -1  # gap down
                else:
                    return
            else:
                # Track Monday's running high / low for SL placement
                self.monday_high = max(self.monday_high, bar["high"])
                self.monday_low = min(self.monday_low, bar["low"])

            # Only trade first half of Monday
            if hour >= s["monday_end_hour"]:
                # Close any remaining open trades at cutoff
                for t in list(open_trades):
                    close_trade(t, i, close, "monday_cutoff")
                return

            if not self.gap_qualified:
                return

            if self.monday_trades >= s["max_monday_trades"]:
                return

            if len(open_trades) > 0:
                return

            # --- Look for reversal candle toward gap fill ---
            bar_open = bar["open"]
            is_bearish = close < bar_open
            is_bullish = close > bar_open

            if self.gap_direction == 1 and is_bearish:
                # Gap up -> short toward friday_close
                sl = self.monday_high + s["buffer_usd"]
                tp = self.friday_close
                if sl <= close:
                    return  # SL must be above entry
                open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
                self.monday_trades += 1

            elif self.gap_direction == -1 and is_bullish:
                # Gap down -> long toward friday_close
                sl = self.monday_low - s["buffer_usd"]
                tp = self.friday_close
                if sl >= close:
                    return  # SL must be below entry
                open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
                self.monday_trades += 1

        # --- Tuesday through Thursday: close leftover trades ---
        elif dow in (1, 2, 3):
            if len(open_trades) > 0:
                for t in list(open_trades):
                    close_trade(t, i, close, "gap_expired")
            # Reset gap state
            self.gap_qualified = False
            self.gap_direction = 0
