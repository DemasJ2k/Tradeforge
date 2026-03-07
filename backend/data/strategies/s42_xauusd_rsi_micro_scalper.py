"""
Strategy 42: XAUUSD RSI Micro Scalper
========================================
Target: XAUUSD M5

Core idea: Ultra-fast RSI(2-3) bounce scalp tuned for gold. Same logic as
the BTCUSD RSI Micro Scalper but with parameters optimized for gold's price
action characteristics -- wider oversold threshold (40) and shorter trend
EMA (13) to better capture gold's faster mean-reversion dynamics.

Entry:
  LONG  -- RSI < rsi_os (oversold) AND close > trend EMA
  SHORT -- RSI > rsi_ob (overbought) AND close < trend EMA

Exit:
  SL = ATR(14) * atr_sl_mult from entry
  TP = ATR(14) * atr_tp_mult from entry

24h session, works on M5.
"""

# -- Settings (tunable via FlowrexAlgo UI) --------------------------
DEFAULTS = {
    "rsi_period":       3,
    "rsi_os":           46,
    "rsi_ob":           86,
    "trend_ema":        17,
    "atr_period":       14,
    "atr_sl_mult":      2.25,
    "atr_tp_mult":      1.02,
    "risk_per_trade":   0.005,
}

SETTINGS = [
    {"key": "rsi_period",     "label": "RSI Period",             "type": "int",   "default": 3,     "min": 2,     "max": 14,   "step": 1,    "group": "Indicator Settings", "description": "Ultra-short RSI lookback period for micro scalping"},
    {"key": "trend_ema",      "label": "Trend EMA Period",       "type": "int",   "default": 17,    "min": 5,     "max": 200,  "step": 1,    "group": "Indicator Settings", "description": "EMA period used as trend direction filter (short for gold)"},
    {"key": "atr_period",     "label": "ATR Period",             "type": "int",   "default": 14,    "min": 5,     "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "ATR lookback period for stop/target sizing"},
    {"key": "rsi_os",         "label": "RSI Oversold Level",     "type": "int",   "default": 46,    "min": 10,    "max": 50,   "step": 1,    "group": "Entry Rules",        "description": "RSI must be below this level to trigger a long entry"},
    {"key": "rsi_ob",         "label": "RSI Overbought Level",   "type": "int",   "default": 86,    "min": 50,    "max": 95,   "step": 1,    "group": "Entry Rules",        "description": "RSI must be above this level to trigger a short entry"},
    {"key": "atr_sl_mult",    "label": "ATR Stop-Loss Mult",     "type": "float", "default": 2.25,  "min": 0.5,   "max": 5.0,  "step": 0.1,  "group": "Risk Management",    "description": "ATR multiplier for stop-loss distance"},
    {"key": "atr_tp_mult",    "label": "ATR Take-Profit Mult",   "type": "float", "default": 1.02,  "min": 0.25,  "max": 5.0,  "step": 0.05, "group": "Risk Management",    "description": "ATR multiplier for take-profit distance"},
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


def _ema(bars, period, key="close"):
    n = len(bars)
    out = [0.0] * n
    if period > n:
        return out
    out[period - 1] = sum(b[key] for b in bars[:period]) / period
    k = 2.0 / (period + 1)
    for i in range(period, n):
        out[i] = bars[i][key] * k + out[i - 1] * (1 - k)
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
class XAUUSDRSIMicroScalper:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.rsi_vals = _rsi(bars, self.s["rsi_period"])
        self.ema_vals = _ema(bars, self.s["trend_ema"])
        self.atr_vals = _atr(bars, self.s["atr_period"])

    def on_bar(self, i, bar):
        p = self.s
        warmup = max(p["trend_ema"], p["atr_period"] + 1, p["rsi_period"] + 1)
        if i < warmup:
            return

        if len(open_trades) > 0:
            return

        atr_val = self.atr_vals[i]
        ema_val = self.ema_vals[i]
        rsi_val = self.rsi_vals[i]

        if atr_val <= 0 or ema_val <= 0:
            return

        close = bar["close"]
        entry = close
        sl_dist = atr_val * p["atr_sl_mult"]
        tp_dist = atr_val * p["atr_tp_mult"]

        # LONG: RSI oversold + price above trend EMA
        if rsi_val < p["rsi_os"] and close > ema_val:
            sl = entry - sl_dist
            tp = entry + tp_dist
            open_trade(i, "long", entry, sl, tp, p["risk_per_trade"])

        # SHORT: RSI overbought + price below trend EMA
        elif rsi_val > p["rsi_ob"] and close < ema_val:
            sl = entry + sl_dist
            tp = entry - tp_dist
            open_trade(i, "short", entry, sl, tp, p["risk_per_trade"])
