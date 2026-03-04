"""
Strategy 05: Opening Range Breakout (ORB)
==========================================
Inspired by: EminiMind (2026 update), Trade with Pat (350k subs),
classic institutional day-trading method.

Core idea: Capture the first 15-min range of the session. Trade
breakout of that range with stop at opposite side.
  - LONG:  price breaks above ORB high → target 1:2 RR
  - SHORT: price breaks below ORB low  → target 1:2 RR

Markets : Universal (best on futures, forex, stocks)
Timeframe: 5m–15m
"""

DEFAULTS = {
    "orb_bars":        3,      # first 3 bars define the opening range (3x5min = 15min)
    "atr_period":      14,
    "atr_filter_mult": 0.5,   # ORB range must be > 0.5*ATR to filter noise
    "rr_ratio":        2.0,   # risk:reward
    "use_atr_stop":    False,  # if True, use ATR-based stop instead of ORB range
    "atr_sl_mult":     1.5,
    "risk_per_trade":  0.01,
    "max_trades_day":  2,      # max trades per ORB session
}


SETTINGS = [
    {"key": "orb_bars",        "label": "ORB Bars",                "type": "int",   "default": 3,    "min": 1,     "max": 10,   "step": 1,    "group": "Indicator Settings", "description": "Number of bars that define the opening range"},
    {"key": "atr_period",      "label": "ATR Period",              "type": "int",   "default": 14,   "min": 5,     "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "Lookback period for Average True Range calculation"},
    {"key": "atr_filter_mult", "label": "ATR Filter Multiple",     "type": "float", "default": 0.5,  "min": 0.1,   "max": 2.0,  "step": 0.1,  "group": "Filters",            "description": "ORB range must exceed this ATR multiple to qualify as tradeable"},
    {"key": "rr_ratio",        "label": "Risk:Reward Ratio",       "type": "float", "default": 2.0,  "min": 1.0,   "max": 5.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Take-profit as a multiple of the risk (stop-loss distance)"},
    {"key": "use_atr_stop",    "label": "Use ATR Stop",            "type": "bool",  "default": False,                                          "group": "Exit Rules",         "description": "Use ATR-based stop-loss instead of ORB range as risk"},
    {"key": "atr_sl_mult",     "label": "ATR Stop-Loss Multiple",  "type": "float", "default": 1.5,  "min": 0.5,   "max": 4.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Stop-loss distance as a multiple of ATR (when ATR stop enabled)"},
    {"key": "risk_per_trade",  "label": "Risk Per Trade",          "type": "float", "default": 0.01, "min": 0.001, "max": 0.1,  "step": 0.001, "group": "Risk Management",   "description": "Fraction of account balance risked per trade"},
    {"key": "max_trades_day",  "label": "Max Trades Per Day",      "type": "int",   "default": 2,    "min": 1,     "max": 10,   "step": 1,    "group": "Risk Management",    "description": "Maximum number of trades allowed per ORB session"},
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


def _get_session_key(bar):
    """Extract date from bar time for session grouping."""
    t = bar.get("time", "")
    if isinstance(t, str) and "T" in t:
        return t.split("T")[0]
    elif isinstance(t, (int, float)):
        from datetime import datetime, timezone
        return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
    return ""


class OpeningRangeBreakout:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.atr_values = _atr(bars, self.s["atr_period"])
        self.session_ranges = {}  # date → {high, low, defined, trades}
        self._precompute_sessions()

    def _precompute_sessions(self):
        orb_bars = self.s["orb_bars"]
        current_session = None
        session_bar_count = 0

        for i, bar in enumerate(self.bars):
            key = _get_session_key(bar)
            if not key:
                continue
            if key != current_session:
                current_session = key
                session_bar_count = 0
                self.session_ranges[key] = {
                    "high": bar["high"],
                    "low": bar["low"],
                    "defined": False,
                    "trades": 0,
                    "start_bar": i,
                }

            session_bar_count += 1
            sr = self.session_ranges[key]

            if session_bar_count <= orb_bars:
                sr["high"] = max(sr["high"], bar["high"])
                sr["low"] = min(sr["low"], bar["low"])
                if session_bar_count == orb_bars:
                    sr["defined"] = True

    def on_bar(self, i, bar):
        s = self.s
        if i < s["atr_period"] + s["orb_bars"] + 1:
            return
        atr_val = self.atr_values[i]
        if atr_val <= 0 or len(open_trades) > 0:
            return

        key = _get_session_key(bar)
        sr = self.session_ranges.get(key)
        if not sr or not sr["defined"]:
            return
        if sr["trades"] >= s["max_trades_day"]:
            return
        if i <= sr["start_bar"] + s["orb_bars"]:
            return

        orb_high = sr["high"]
        orb_low = sr["low"]
        orb_range = orb_high - orb_low

        # Filter: range must be meaningful
        if orb_range < atr_val * s["atr_filter_mult"]:
            return

        close = bar["close"]
        prev_close = self.bars[i - 1]["close"]

        if s["use_atr_stop"]:
            risk = atr_val * s["atr_sl_mult"]
        else:
            risk = orb_range

        # Breakout above ORB high
        if close > orb_high and prev_close <= orb_high:
            sl = close - risk
            tp = close + risk * s["rr_ratio"]
            open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
            sr["trades"] += 1

        # Breakout below ORB low
        elif close < orb_low and prev_close >= orb_low:
            sl = close + risk
            tp = close - risk * s["rr_ratio"]
            open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
            sr["trades"] += 1
