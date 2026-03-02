"""
Strategy 03: Smart Money Concepts — Liquidity Sweep + FVG + Order Block
========================================================================
Inspired by: ICT Smart Money Concepts, widely used by Chart Fanatics traders

Core idea: Combine three institutional concepts:
  1. Liquidity Sweep — price takes out a swing high/low (stop hunt)
  2. Market Structure Shift — break of recent structure confirms reversal
  3. Entry at Order Block or FVG left behind by the displacement

Markets : Universal (all liquid markets)
Timeframe: 1m–15m (scalping/intraday)
"""

DEFAULTS = {
    "atr_period":        14,
    "atr_sl_mult":       1.5,
    "atr_tp_mult":       3.0,
    "swing_lookback":    15,    # bars to identify swing points
    "ob_lookback":       5,     # bars to look back for order blocks
    "risk_per_trade":    0.01,
}


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


def _swing_highs(bars, i, lookback):
    start = max(0, i - lookback)
    highs = [(j, bars[j]["high"]) for j in range(start, i)]
    if not highs:
        return []
    return sorted(highs, key=lambda x: -x[1])


def _swing_lows(bars, i, lookback):
    start = max(0, i - lookback)
    lows = [(j, bars[j]["low"]) for j in range(start, i)]
    if not lows:
        return []
    return sorted(lows, key=lambda x: x[1])


def _find_order_block(bars, i, lookback, direction):
    """Find the last order block before bar i.
    Bullish OB: last bearish candle before a strong up move
    Bearish OB: last bullish candle before a strong down move
    Returns (ob_high, ob_low) or None.
    """
    start = max(0, i - lookback)
    if direction == "bullish":
        for j in range(i - 1, start - 1, -1):
            if bars[j]["close"] < bars[j]["open"]:  # bearish candle
                return (bars[j]["high"], bars[j]["low"])
    else:
        for j in range(i - 1, start - 1, -1):
            if bars[j]["close"] > bars[j]["open"]:  # bullish candle
                return (bars[j]["high"], bars[j]["low"])
    return None


def _detect_mss(bars, i, lookback):
    """Detect Market Structure Shift.
    Bullish MSS: swing low was taken out, then price breaks above recent swing high
    Bearish MSS: swing high was taken out, then price breaks below recent swing low
    Returns 'bullish', 'bearish', or None.
    """
    if i < lookback + 2:
        return None

    lows = _swing_lows(bars, i, lookback)
    highs = _swing_highs(bars, i, lookback)
    if not lows or not highs:
        return None

    recent_low = lows[0][1]
    recent_high = highs[0][1]

    # Bullish MSS: current bar swept the low(s) and then closed above structure
    if bars[i]["low"] < recent_low and bars[i]["close"] > bars[i]["open"]:
        # Check if we broke above a recent minor high
        mid_highs = [bars[j]["high"] for j in range(max(0, i - 5), i)]
        if mid_highs and bars[i]["close"] > max(mid_highs):
            return "bullish"

    # Bearish MSS
    if bars[i]["high"] > recent_high and bars[i]["close"] < bars[i]["open"]:
        mid_lows = [bars[j]["low"] for j in range(max(0, i - 5), i)]
        if mid_lows and bars[i]["close"] < min(mid_lows):
            return "bearish"

    return None


class SmartMoneyConcepts:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.atr_values = _atr(bars, self.s["atr_period"])

    def on_bar(self, i, bar):
        s = self.s
        if i < s["swing_lookback"] + s["ob_lookback"] + 3:
            return
        atr_val = self.atr_values[i]
        if atr_val <= 0 or len(open_trades) > 0:
            return

        mss = _detect_mss(self.bars, i, s["swing_lookback"])
        if not mss:
            return

        ob = _find_order_block(self.bars, i, s["ob_lookback"], mss)
        if not ob:
            return

        ob_high, ob_low = ob

        if mss == "bullish":
            entry = bar["close"]
            sl = entry - atr_val * s["atr_sl_mult"]
            tp = entry + atr_val * s["atr_tp_mult"]
            open_trade(i, "long", entry, sl, tp, s["risk_per_trade"])

        elif mss == "bearish":
            entry = bar["close"]
            sl = entry + atr_val * s["atr_sl_mult"]
            tp = entry - atr_val * s["atr_tp_mult"]
            open_trade(i, "short", entry, sl, tp, s["risk_per_trade"])
