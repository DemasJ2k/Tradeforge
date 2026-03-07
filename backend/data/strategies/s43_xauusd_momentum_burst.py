"""
Strategy 43: XAUUSD Momentum Burst Scalper
=============================================
Target: XAUUSD M15

Core idea: Enter on large-body candles (body > body_thresh * ATR) that
signal a momentum burst, with RSI confirmation to avoid chasing exhausted
moves. Gold frequently prints impulsive candles during news or session
opens -- this strategy captures the follow-through.

Entry:
  LONG  -- Bullish candle (close > open) with body/ATR > body_thresh
           AND RSI < rsi_cap (not overbought yet)
  SHORT -- Bearish candle (close < open) with body/ATR > body_thresh
           AND RSI > (100 - rsi_cap) (not oversold yet)

Exit:
  SL = ATR(14) * atr_sl_mult from entry
  TP = ATR(14) * atr_tp_mult from entry

24h session, works on M15.
"""

# -- Settings (tunable via FlowrexAlgo UI) --------------------------
DEFAULTS = {
    "rsi_period":       6,
    "body_thresh":      0.15,
    "rsi_cap":          82,
    "atr_period":       14,
    "atr_sl_mult":      1.93,
    "atr_tp_mult":      1.21,
    "risk_per_trade":   0.005,
}

SETTINGS = [
    {"key": "rsi_period",     "label": "RSI Period",             "type": "int",   "default": 6,     "min": 2,     "max": 20,   "step": 1,    "group": "Indicator Settings", "description": "RSI lookback period for momentum confirmation"},
    {"key": "atr_period",     "label": "ATR Period",             "type": "int",   "default": 14,    "min": 5,     "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "ATR lookback period for body threshold and SL/TP sizing"},
    {"key": "body_thresh",    "label": "Body/ATR Threshold",     "type": "float", "default": 0.15,  "min": 0.05,  "max": 2.0,  "step": 0.05, "group": "Entry Rules",        "description": "Minimum candle body size as a fraction of ATR to qualify as a momentum burst"},
    {"key": "rsi_cap",        "label": "RSI Cap (Long)",         "type": "int",   "default": 82,    "min": 50,    "max": 95,   "step": 1,    "group": "Entry Rules",        "description": "RSI must be below this for longs (above 100-cap for shorts) to avoid exhaustion"},
    {"key": "atr_sl_mult",    "label": "ATR Stop-Loss Mult",     "type": "float", "default": 1.93,  "min": 0.5,   "max": 5.0,  "step": 0.1,  "group": "Risk Management",    "description": "ATR multiplier for stop-loss distance"},
    {"key": "atr_tp_mult",    "label": "ATR Take-Profit Mult",   "type": "float", "default": 1.21,  "min": 0.25,  "max": 5.0,  "step": 0.05, "group": "Risk Management",    "description": "ATR multiplier for take-profit distance"},
    {"key": "risk_per_trade", "label": "Risk Per Trade",         "type": "float", "default": 0.005, "min": 0.001, "max": 0.05, "step": 0.001,"group": "Risk Management",    "description": "Fraction of account equity risked per trade"},
]


# -- Helpers --------------------------------------------------------
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


def _rsi(bars, period):
    n = len(bars)
    out = [50.0] * n
    if period + 1 > n:
        return out
    gains = losses = 0.0
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
        g = max(diff, 0)
        l = max(-diff, 0)
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def _get_hour(bar):
    t = bar.get("time", "")
    if isinstance(t, str):
        for sep in [" ", "T"]:
            if sep in t:
                try:
                    return int(t.split(sep)[-1].split(":")[0])
                except Exception:
                    pass
    elif isinstance(t, (int, float)):
        import datetime
        try:
            return datetime.datetime.utcfromtimestamp(t).hour
        except Exception:
            pass
    return -1


# -- Strategy -------------------------------------------------------
class XAUUSDMomentumBurst:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.rsi_vals = _rsi(bars, self.s["rsi_period"])
        self.atr_vals = _atr(bars, self.s["atr_period"])

    def on_bar(self, i, bar):
        p = self.s
        warmup = max(p["atr_period"] + 1, p["rsi_period"] + 1)
        if i < warmup:
            return

        if len(open_trades) > 0:
            return

        atr_val = self.atr_vals[i]
        rsi_val = self.rsi_vals[i]

        if atr_val <= 0:
            return

        close = bar["close"]
        opn = bar["open"]
        body = abs(close - opn)
        body_ratio = body / atr_val

        # Check if candle body is large enough
        if body_ratio < p["body_thresh"]:
            return

        entry = close
        sl_dist = atr_val * p["atr_sl_mult"]
        tp_dist = atr_val * p["atr_tp_mult"]

        # LONG: bullish momentum candle + RSI not exhausted
        if close > opn and rsi_val < p["rsi_cap"]:
            sl = entry - sl_dist
            tp = entry + tp_dist
            open_trade(i, "long", entry, sl, tp, p["risk_per_trade"])

        # SHORT: bearish momentum candle + RSI not exhausted
        elif close < opn and rsi_val > (100 - p["rsi_cap"]):
            sl = entry + sl_dist
            tp = entry - tp_dist
            open_trade(i, "short", entry, sl, tp, p["risk_per_trade"])
