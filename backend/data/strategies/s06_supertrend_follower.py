"""
Strategy 06: Supertrend Trend Follower
=======================================
Inspired by: Oliver Seban's Supertrend indicator — backtested 11.07%
avg gain/trade over 60 years on S&P500. Universal trend rider.

Core idea: ATR-based trailing stop that flips direction on crossover.
  - LONG:  price closes above Supertrend line (line goes green)
  - SHORT: price closes below Supertrend line (line goes red)
  - Trail stop with the Supertrend line itself.

Markets : Universal
Timeframe: 15m–Daily (all timeframes)
"""

DEFAULTS = {
    "atr_period":     10,
    "multiplier":     3.0,
    "risk_per_trade": 0.01,
    "flat_filter":    5,      # skip if Supertrend flat for N bars (whipsaw zone)
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


def _supertrend(bars, atr_vals, period, mult):
    """Compute Supertrend. Returns (st_line[], direction[])."""
    n = len(bars)
    st = [0.0] * n
    direction = [0] * n  # 1 = up (bullish), -1 = down (bearish)

    for i in range(period + 1, n):
        hl2 = (bars[i]["high"] + bars[i]["low"]) / 2
        atr_val = atr_vals[i]
        if atr_val <= 0:
            st[i] = st[i - 1]
            direction[i] = direction[i - 1]
            continue

        upper = hl2 + mult * atr_val
        lower = hl2 - mult * atr_val

        # Carry forward: don't let lower band decrease or upper band increase
        if i > period + 1:
            if lower > st[i - 1] or bars[i - 1]["close"] < st[i - 1]:
                pass  # use new lower
            else:
                lower = max(lower, st[i - 1]) if direction[i - 1] == 1 else lower

            if upper < st[i - 1] or bars[i - 1]["close"] > st[i - 1]:
                pass
            else:
                upper = min(upper, st[i - 1]) if direction[i - 1] == -1 else upper

        # Determine direction
        if direction[i - 1] == 1:
            if bars[i]["close"] < lower:
                direction[i] = -1
                st[i] = upper
            else:
                direction[i] = 1
                st[i] = max(lower, st[i - 1]) if st[i - 1] > 0 else lower
        elif direction[i - 1] == -1:
            if bars[i]["close"] > upper:
                direction[i] = 1
                st[i] = lower
            else:
                direction[i] = -1
                st[i] = min(upper, st[i - 1]) if st[i - 1] > 0 else upper
        else:
            # Initial
            if bars[i]["close"] > hl2:
                direction[i] = 1
                st[i] = lower
            else:
                direction[i] = -1
                st[i] = upper

    return st, direction


class SupertrendFollower:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.atr_values = _atr(bars, self.s["atr_period"])
        self.st_line, self.st_dir = _supertrend(
            bars, self.atr_values, self.s["atr_period"], self.s["multiplier"]
        )
        self.current_dir = 0

    def on_bar(self, i, bar):
        s = self.s
        if i < s["atr_period"] + 2:
            return
        if self.st_dir[i] == 0:
            return

        new_dir = self.st_dir[i]
        old_dir = self.st_dir[i - 1] if i > 0 else 0

        # Close existing trades on direction flip
        if new_dir != old_dir and old_dir != 0:
            for t in list(open_trades):
                close_trade(t, i, bar["close"], "signal_reversal")

        # Check for whipsaw filter
        if s["flat_filter"] > 0 and i >= s["flat_filter"]:
            flat_count = 0
            for j in range(i - s["flat_filter"], i):
                if self.st_dir[j] != self.st_dir[j - 1] if j > 0 else False:
                    flat_count += 1
            if flat_count >= 2:
                return  # too many flips = choppy

        # Enter on direction change
        if new_dir != old_dir and new_dir != 0 and len(open_trades) == 0:
            atr_val = self.atr_values[i]
            if atr_val <= 0:
                return
            if new_dir == 1:
                sl = self.st_line[i] - atr_val * 0.2  # slightly below ST line
                tp = bar["close"] + atr_val * 3.0
                open_trade(i, "long", bar["close"], sl, tp, s["risk_per_trade"])
            else:
                sl = self.st_line[i] + atr_val * 0.2
                tp = bar["close"] - atr_val * 3.0
                open_trade(i, "short", bar["close"], sl, tp, s["risk_per_trade"])
