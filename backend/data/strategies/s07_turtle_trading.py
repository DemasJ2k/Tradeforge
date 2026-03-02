"""
Strategy 07: Turtle Trading System (Donchian Channel Breakout)
===============================================================
Inspired by: Richard Dennis & William Eckhardt — $5K to $100M.
Curtis Faith improvement: 40-day MA > 200-day MA filter.

Core idea: Price-channel breakout trend-following system.
  System 1: 20-day breakout entry, 10-day breakout exit
  System 2: 55-day breakout entry, 20-day breakout exit
  Position sizing based on ATR (N-value).

Markets : Universal (liquid futures, forex, crypto, stocks)
Timeframe: Daily (swing/position trading)
"""

DEFAULTS = {
    "entry_period":    20,     # Donchian channel entry lookback
    "exit_period":     10,     # Donchian channel exit lookback
    "atr_period":      20,     # N-value calculation
    "ma_fast":         40,     # trend filter fast MA
    "ma_slow":         200,    # trend filter slow MA
    "use_trend_filter": True,  # Curtis Faith improvement
    "risk_per_trade":  0.01,   # 1% risk
    "atr_stop_mult":   2.0,    # initial stop = 2N
}


def _sma(data, period):
    out = [0.0] * len(data)
    if period > len(data):
        return out
    s = sum(data[:period])
    out[period - 1] = s / period
    for i in range(period, len(data)):
        s += data[i] - data[i - period]
        out[i] = s / period
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


def _donchian_high(bars, i, period):
    start = max(0, i - period)
    return max(bars[j]["high"] for j in range(start, i))


def _donchian_low(bars, i, period):
    start = max(0, i - period)
    return min(bars[j]["low"] for j in range(start, i))


class TurtleTradingSystem:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        closes = [b["close"] for b in bars]
        self.ma_fast = _sma(closes, self.s["ma_fast"])
        self.ma_slow = _sma(closes, self.s["ma_slow"])
        self.atr_values = _atr(bars, self.s["atr_period"])

    def on_bar(self, i, bar):
        s = self.s
        min_lookback = max(s["entry_period"], s["exit_period"], s["ma_slow"]) + 1
        if i < min_lookback:
            return
        atr_val = self.atr_values[i]
        if atr_val <= 0:
            return

        close = bar["close"]

        # ── Exit logic (check before entry) ──
        if len(open_trades) > 0:
            for t in list(open_trades):
                if t["direction"] == "long":
                    exit_low = _donchian_low(self.bars, i, s["exit_period"])
                    if close < exit_low:
                        close_trade(t, i, close, "donchian_exit")
                else:
                    exit_high = _donchian_high(self.bars, i, s["exit_period"])
                    if close > exit_high:
                        close_trade(t, i, close, "donchian_exit")
            return

        # ── Trend filter ──
        if s["use_trend_filter"]:
            if self.ma_fast[i] <= 0 or self.ma_slow[i] <= 0:
                return

        # ── Entry logic ──
        entry_high = _donchian_high(self.bars, i, s["entry_period"])
        entry_low = _donchian_low(self.bars, i, s["entry_period"])

        # Long breakout
        if close > entry_high:
            if not s["use_trend_filter"] or self.ma_fast[i] > self.ma_slow[i]:
                sl = close - atr_val * s["atr_stop_mult"]
                tp = close + atr_val * s["atr_stop_mult"] * 3
                open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # Short breakout
        elif close < entry_low:
            if not s["use_trend_filter"] or self.ma_fast[i] < self.ma_slow[i]:
                sl = close + atr_val * s["atr_stop_mult"]
                tp = close - atr_val * s["atr_stop_mult"] * 3
                open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
