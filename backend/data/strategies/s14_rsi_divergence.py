"""
Strategy 14: RSI Divergence Swing Trader
==========================================
Inspired by: Andrew Cardwell (RSI specialist) & classic divergence theory.

Core idea: Hidden/regular divergence between price and RSI signals reversals
or continuation.
  Regular Bullish: Price lower low + RSI higher low → reversal long
  Regular Bearish: Price higher high + RSI lower high → reversal short
  Hidden Bullish:  Price higher low + RSI lower low → continuation long
  Hidden Bearish:  Price lower high + RSI higher high → continuation short

Markets : Universal
Timeframe: 1H / 4H / Daily
"""

DEFAULTS = {
    "rsi_period":       14,
    "pivot_lookback":   5,      # Bars to confirm pivot high/low
    "max_div_bars":     30,     # Max bars between two pivot points for divergence
    "min_div_bars":     5,      # Min bars separation
    "use_hidden_div":   True,
    "sma_trend_period": 50,     # Trend filter
    "atr_period":       14,
    "atr_sl_mult":      2.0,
    "atr_tp_mult":      3.0,
    "risk_per_trade":   0.01,
}


def _rsi(bars, period):
    n = len(bars)
    out = [50.0] * n
    if period + 1 > n:
        return out
    gains = 0.0
    losses = 0.0
    for j in range(1, period + 1):
        diff = bars[j]["close"] - bars[j - 1]["close"]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period + 1, n):
        diff = bars[i]["close"] - bars[i - 1]["close"]
        g = diff if diff > 0 else 0.0
        l = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def _sma(bars, period, key="close"):
    n = len(bars)
    out = [0.0] * n
    if period > n:
        return out
    s = sum(bars[j][key] for j in range(period))
    out[period - 1] = s / period
    for i in range(period, n):
        s += bars[i][key] - bars[i - period][key]
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


def _find_pivot_lows(bars, rsi_vals, lookback, end_idx, count=10):
    """Find recent pivot lows (price lows confirmed by lookback bars on each side)."""
    pivots = []
    start = max(lookback, 1)
    for i in range(end_idx - 1, start - 1, -1):
        if len(pivots) >= count:
            break
        is_pivot = True
        for j in range(1, lookback + 1):
            if i - j < 0 or i + j > end_idx:
                is_pivot = False
                break
            if bars[i]["low"] > bars[i - j]["low"] or bars[i]["low"] > bars[i + j]["low"]:
                is_pivot = False
                break
        if is_pivot:
            pivots.append((i, bars[i]["low"], rsi_vals[i]))
    return pivots


def _find_pivot_highs(bars, rsi_vals, lookback, end_idx, count=10):
    """Find recent pivot highs."""
    pivots = []
    start = max(lookback, 1)
    for i in range(end_idx - 1, start - 1, -1):
        if len(pivots) >= count:
            break
        is_pivot = True
        for j in range(1, lookback + 1):
            if i - j < 0 or i + j > end_idx:
                is_pivot = False
                break
            if bars[i]["high"] < bars[i - j]["high"] or bars[i]["high"] < bars[i + j]["high"]:
                is_pivot = False
                break
        if is_pivot:
            pivots.append((i, bars[i]["high"], rsi_vals[i]))
    return pivots


class RSIDivergence:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.rsi = _rsi(bars, self.s["rsi_period"])
        self.sma = _sma(bars, self.s["sma_trend_period"])
        self.atr_vals = _atr(bars, self.s["atr_period"])
        self.last_signal_bar = -100

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["rsi_period"], s["sma_trend_period"], s["atr_period"]) + s["pivot_lookback"] + s["max_div_bars"] + 2
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        if atr_val <= 0:
            return

        close = bar["close"]
        rsi_val = self.rsi[i]

        # Exit on RSI extremes or fixed TP/SL (handled by harness)
        for t in list(open_trades):
            if t["direction"] == "long" and rsi_val > 70:
                close_trade(t, i, close, "rsi_overbought")
            elif t["direction"] == "short" and rsi_val < 30:
                close_trade(t, i, close, "rsi_oversold")

        if len(open_trades) > 0:
            return

        # Debounce: skip if recent signal
        if i - self.last_signal_bar < s["min_div_bars"]:
            return

        lookback = s["pivot_lookback"]

        # Check BULLISH divergence
        lows = _find_pivot_lows(self.bars, self.rsi, lookback, i, count=5)
        if len(lows) >= 2:
            recent = lows[0]  # most recent pivot low
            for prev in lows[1:]:
                bar_diff = recent[0] - prev[0]
                if bar_diff < s["min_div_bars"] or bar_diff > s["max_div_bars"]:
                    continue
                # Regular bullish: lower price low + higher RSI low
                if recent[1] < prev[1] and recent[2] > prev[2]:
                    if close > self.sma[i]:  # Trend filter (allow longs in uptrend)
                        sl = close - atr_val * s["atr_sl_mult"]
                        tp = close + atr_val * s["atr_tp_mult"]
                        open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
                        self.last_signal_bar = i
                        return
                # Hidden bullish: higher price low + lower RSI low
                if s["use_hidden_div"] and recent[1] > prev[1] and recent[2] < prev[2]:
                    if close > self.sma[i]:
                        sl = close - atr_val * s["atr_sl_mult"]
                        tp = close + atr_val * s["atr_tp_mult"]
                        open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
                        self.last_signal_bar = i
                        return

        # Check BEARISH divergence
        highs = _find_pivot_highs(self.bars, self.rsi, lookback, i, count=5)
        if len(highs) >= 2:
            recent = highs[0]
            for prev in highs[1:]:
                bar_diff = recent[0] - prev[0]
                if bar_diff < s["min_div_bars"] or bar_diff > s["max_div_bars"]:
                    continue
                # Regular bearish: higher price high + lower RSI high
                if recent[1] > prev[1] and recent[2] < prev[2]:
                    if close < self.sma[i]:
                        sl = close + atr_val * s["atr_sl_mult"]
                        tp = close - atr_val * s["atr_tp_mult"]
                        open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
                        self.last_signal_bar = i
                        return
                # Hidden bearish: lower price high + higher RSI high
                if s["use_hidden_div"] and recent[1] < prev[1] and recent[2] > prev[2]:
                    if close < self.sma[i]:
                        sl = close + atr_val * s["atr_sl_mult"]
                        tp = close - atr_val * s["atr_tp_mult"]
                        open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
                        self.last_signal_bar = i
                        return
