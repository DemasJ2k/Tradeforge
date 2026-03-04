"""
Strategy 02: ICT Silver Bullet
===============================
Inspired by: ICT (Inner Circle Trader) — widely used by profitable traders
on Chart Fanatics, Tanja Trades ($100k+), and prop firm traders.

Core idea: Time-based algorithmic model that trades Fair Value Gaps (FVG)
after liquidity sweeps during specific institutional windows.

Three windows (New York time):
  - London Open: 03:00–04:00
  - New York AM:  10:00–11:00
  - New York PM:  14:00–15:00

Entry: After a liquidity sweep + displacement, enter on the FVG retracement.
Exit:  Target opposing liquidity pool or 2R minimum.

Markets : Universal (futures, forex, crypto)
Timeframe: 1m–5m
"""

DEFAULTS = {
    "atr_period":       14,
    "atr_sl_mult":      1.5,
    "min_rr":           2.0,    # minimum risk:reward
    "fvg_min_size_atr": 0.15,   # FVG imbalance min size (lowered from 0.3)
    "lookback_swing":   20,     # bars to find swing highs/lows for liquidity
    "sweep_lookback":   5,      # bars to look back for recent sweep
    "session_filter":   True,   # only trade during kill zone windows
    "risk_per_trade":   0.01,
}


SETTINGS = [
    {"key": "atr_period",       "label": "ATR Period",             "type": "int",   "default": 14,   "min": 5,     "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "Lookback period for Average True Range calculation"},
    {"key": "atr_sl_mult",      "label": "ATR Stop-Loss Multiple", "type": "float", "default": 1.5,  "min": 0.5,   "max": 4.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Stop-loss distance as a multiple of ATR"},
    {"key": "min_rr",           "label": "Minimum Risk:Reward",    "type": "float", "default": 2.0,  "min": 1.0,   "max": 5.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Minimum risk-to-reward ratio for trade entries"},
    {"key": "fvg_min_size_atr", "label": "FVG Min Size (ATR)",     "type": "float", "default": 0.15, "min": 0.05,  "max": 1.0,  "step": 0.01, "group": "Entry Rules",        "description": "Minimum Fair Value Gap size as a fraction of ATR"},
    {"key": "lookback_swing",   "label": "Swing Lookback",         "type": "int",   "default": 20,   "min": 10,    "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "Number of bars to identify swing highs/lows for liquidity levels"},
    {"key": "sweep_lookback",   "label": "Sweep Lookback",         "type": "int",   "default": 5,    "min": 3,     "max": 20,   "step": 1,    "group": "Entry Rules",        "description": "Number of bars a liquidity sweep remains valid for FVG entry"},
    {"key": "session_filter",   "label": "Session Filter",         "type": "bool",  "default": True,                                           "group": "Session",            "description": "Only trade during ICT kill zone windows (London Open, NY AM, NY PM)"},
    {"key": "risk_per_trade",   "label": "Risk Per Trade",         "type": "float", "default": 0.01, "min": 0.001, "max": 0.1,  "step": 0.001, "group": "Risk Management",   "description": "Fraction of account balance risked per trade"},
]


def _atr(bars, period):
    n = len(bars)
    trs = [0.0] * n
    for i in range(1, n):
        trs[i] = max(
            bars[i]["high"] - bars[i]["low"],
            abs(bars[i]["high"] - bars[i - 1]["close"]),
            abs(bars[i]["low"] - bars[i - 1]["close"]),
        )
    out = [0.0] * n
    if period + 1 > n:
        return out
    out[period] = sum(trs[1 : period + 1]) / period
    for i in range(period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + trs[i]) / period
    return out


def _is_kill_zone(bar):
    """Check if the bar falls in an ICT kill zone (approximate via hour)."""
    t = bar.get("time", "")
    if not t:
        return True  # if no time info, allow trading
    try:
        # Try to parse hour from ISO string or timestamp
        if isinstance(t, str) and "T" in t:
            hour = int(t.split("T")[1][:2])
        elif isinstance(t, (int, float)):
            from datetime import datetime, timezone
            hour = datetime.fromtimestamp(t, tz=timezone.utc).hour
        else:
            return True
    except Exception:
        return True
    # Kill zones (approximate UTC — user should adjust for their broker offset)
    # London 07:00-08:00 UTC, NY AM 14:00-15:00 UTC, NY PM 18:00-19:00 UTC
    return hour in (7, 8, 14, 15, 18, 19)


def _find_fvg(bars, i, atr_val=0):
    """Detect Fair Value Gaps / Imbalance at bar i (3-candle pattern).
    
    Pure FVG: bars[i-2].high < bars[i].low (gap up) — rare in liquid markets.
    Imbalance FVG: Middle candle has strong body (>0.5*ATR) and the gap between
    bar 0 and bar 2 is small relative to the displacement (allows partial overlap).
    
    Returns (direction, gap_top, gap_bottom) or None.
    """
    if i < 2:
        return None
    b0, b1, b2 = bars[i - 2], bars[i - 1], bars[i]

    # Pure FVG
    if b0["high"] < b2["low"]:
        return ("bullish", b2["low"], b0["high"])
    if b0["low"] > b2["high"]:
        return ("bearish", b0["low"], b2["high"])

    # Imbalance / displacement-based FVG (relaxed)
    # Middle candle (b1) must have large body showing displacement
    b1_body = abs(b1["close"] - b1["open"])
    min_body = max(atr_val * 0.4, 0.0001) if atr_val > 0 else 0.0001

    if b1_body < min_body:
        return None

    # Bullish imbalance: b1 is strong bullish, gap between b0.high and b2.low is small
    if b1["close"] > b1["open"]:
        overlap = b0["high"] - b2["low"]
        if overlap < b1_body * 0.5:  # Allow up to 50% overlap
            gap_top = max(b2["low"], b0["high"])
            gap_bot = min(b2["low"], b0["high"])
            if gap_top > gap_bot:
                return ("bullish", gap_top, gap_bot)

    # Bearish imbalance: b1 is strong bearish, gap between b0.low and b2.high is small
    if b1["close"] < b1["open"]:
        overlap = b2["high"] - b0["low"]
        if overlap < b1_body * 0.5:
            gap_top = max(b0["low"], b2["high"])
            gap_bot = min(b0["low"], b2["high"])
            if gap_top > gap_bot:
                return ("bearish", gap_top, gap_bot)

    return None


def _swing_high(bars, i, lookback):
    """Find highest high in lookback window before i."""
    start = max(0, i - lookback)
    if start >= i:
        return 0
    return max(bars[j]["high"] for j in range(start, i))


def _swing_low(bars, i, lookback):
    """Find lowest low in lookback window before i."""
    start = max(0, i - lookback)
    if start >= i:
        return float("inf")
    return min(bars[j]["low"] for j in range(start, i))


def _liquidity_swept(bars, i, lookback):
    """Did the current bar sweep a recent liquidity level?
    Returns 'high_swept' or 'low_swept' or None.
    """
    if i < lookback + 1:
        return None
    prev_high = _swing_high(bars, i, lookback)
    prev_low = _swing_low(bars, i, lookback)

    # Swept high then closed below it (bearish sweep)
    if bars[i]["high"] > prev_high and bars[i]["close"] < prev_high:
        return "high_swept"
    # Swept low then closed above it (bullish sweep)
    if bars[i]["low"] < prev_low and bars[i]["close"] > prev_low:
        return "low_swept"
    return None


class ICTSilverBullet:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.atr_values = _atr(bars, self.s["atr_period"])
        self.pending_fvg = None  # (direction, entry, sl, tp, expiry_bar)
        self.recent_sweep = None  # (direction, bar_index)

    def on_bar(self, i, bar):
        s = self.s
        if i < max(s["lookback_swing"], s["atr_period"]) + 3:
            return
        atr_val = self.atr_values[i]
        if atr_val <= 0:
            return

        # Check if we have a pending FVG entry
        if self.pending_fvg and len(open_trades) == 0:
            direction, entry_price, sl, tp, expiry = self.pending_fvg
            if i > expiry:
                self.pending_fvg = None
            elif direction == "long" and bar["low"] <= entry_price <= bar["high"]:
                open_trade(i, "long", entry_price, sl, tp, s["risk_per_trade"])
                self.pending_fvg = None
                return
            elif direction == "short" and bar["low"] <= entry_price <= bar["high"]:
                open_trade(i, "short", entry_price, sl, tp, s["risk_per_trade"])
                self.pending_fvg = None
                return

        if len(open_trades) > 0:
            return

        # Session filter
        if s["session_filter"] and not _is_kill_zone(bar):
            self.recent_sweep = None  # Reset sweep outside kill zones
            return

        # Track liquidity sweeps (allow sweep to precede FVG by several bars)
        sweep = _liquidity_swept(self.bars, i, s["lookback_swing"])
        if sweep:
            self.recent_sweep = (sweep, i)

        # Expire old sweeps
        sweep_lb = s.get("sweep_lookback", 5)
        if self.recent_sweep and i - self.recent_sweep[1] > sweep_lb:
            self.recent_sweep = None

        if not self.recent_sweep:
            return

        # Look for FVG/displacement in current bar
        fvg = _find_fvg(self.bars, i, atr_val)
        if not fvg:
            return

        sweep_dir = self.recent_sweep[0]
        fvg_dir, gap_top, gap_bottom = fvg
        gap_size = gap_top - gap_bottom

        # Validate FVG size
        if gap_size < atr_val * s["fvg_min_size_atr"]:
            return

        # Bullish: swept low + bullish FVG → long on FVG retracement
        if sweep_dir == "low_swept" and fvg_dir == "bullish":
            entry = gap_top  # enter at top of gap on pullback
            sl = gap_bottom - atr_val * 0.3
            risk = entry - sl
            if risk <= 0:
                return
            tp = entry + risk * s["min_rr"]
            self.pending_fvg = ("long", entry, sl, tp, i + 15)
            self.recent_sweep = None

        # Bearish: swept high + bearish FVG → short on FVG retracement
        elif sweep_dir == "high_swept" and fvg_dir == "bearish":
            entry = gap_bottom  # enter at bottom of gap on pullback
            sl = gap_top + atr_val * 0.3
            risk = sl - entry
            if risk <= 0:
                return
            tp = entry - risk * s["min_rr"]
            self.pending_fvg = ("short", entry, sl, tp, i + 15)
            self.recent_sweep = None
