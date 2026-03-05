"""
Strategy 39: ETHUSD Momentum Scalper (EMA Cross + Volume + ADX)
================================================================
Target: ETHUSD M5

Core idea: Capture momentum bursts during US/London overlap session using
fast/slow EMA crossovers confirmed by volume spikes and ADX trend strength.
ETH's higher volatility relative to BTC provides amplified R:R on breakouts.

Entry:
  LONG  — fast EMA crosses above slow EMA, volume spike, ADX > threshold
  SHORT — fast EMA crosses below slow EMA, same filters
  Session filter: UTC 13:00–17:00 only

Exit:
  SL = ATR(10) * atr_sl_mult from entry
  TP = ATR(10) * atr_tp_mult from entry
  Force close at session end
"""

# ── Settings (tunable via FlowrexAlgo UI) ─────────────────────────
DEFAULTS = {
    "fast_ema":           8,
    "slow_ema":           21,
    "vol_period":         20,
    "vol_mult":           1.5,
    "atr_period":         10,
    "adx_period":         14,
    "adx_min":            20,
    "atr_sl_mult":        1.0,
    "atr_tp_mult":        2.0,
    "session_start_hour": 13,
    "session_end_hour":   17,
    "risk_per_trade":     0.01,
    "max_daily_trades":   3,
}

SETTINGS = [
    {"key": "fast_ema",           "label": "Fast EMA Period",       "type": "int",   "default": 8,    "min": 3,     "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "Period for the fast exponential moving average"},
    {"key": "slow_ema",           "label": "Slow EMA Period",       "type": "int",   "default": 21,   "min": 10,    "max": 100,  "step": 1,    "group": "Indicator Settings", "description": "Period for the slow exponential moving average"},
    {"key": "vol_period",         "label": "Volume SMA Period",     "type": "int",   "default": 20,   "min": 5,     "max": 100,  "step": 1,    "group": "Indicator Settings", "description": "Lookback period for average volume calculation"},
    {"key": "vol_mult",           "label": "Volume Spike Multiple", "type": "float", "default": 1.5,  "min": 1.0,   "max": 5.0,  "step": 0.1,  "group": "Filters",            "description": "Current volume must exceed avg volume by this multiple"},
    {"key": "atr_period",         "label": "ATR Period",            "type": "int",   "default": 10,   "min": 5,     "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "Lookback period for Average True Range calculation"},
    {"key": "adx_period",         "label": "ADX Period",            "type": "int",   "default": 14,   "min": 7,     "max": 30,   "step": 1,    "group": "Indicator Settings", "description": "Period for the ADX trend strength indicator"},
    {"key": "adx_min",            "label": "ADX Minimum",           "type": "int",   "default": 20,   "min": 10,    "max": 50,   "step": 1,    "group": "Filters",            "description": "Minimum ADX value required for entry (trend strength)"},
    {"key": "atr_sl_mult",        "label": "ATR Stop-Loss Multiple","type": "float", "default": 1.0,  "min": 0.5,   "max": 4.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Stop-loss distance as a multiple of ATR"},
    {"key": "atr_tp_mult",        "label": "ATR Take-Profit Multiple","type": "float","default": 2.0, "min": 1.0,   "max": 6.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Take-profit distance as a multiple of ATR"},
    {"key": "session_start_hour", "label": "Session Start (UTC)",   "type": "int",   "default": 13,   "min": 0,     "max": 23,   "step": 1,    "group": "Filters",            "description": "UTC hour to begin accepting trades"},
    {"key": "session_end_hour",   "label": "Session End (UTC)",     "type": "int",   "default": 17,   "min": 0,     "max": 23,   "step": 1,    "group": "Filters",            "description": "UTC hour to stop accepting trades and close open positions"},
    {"key": "risk_per_trade",     "label": "Risk Per Trade",        "type": "float", "default": 0.01, "min": 0.001, "max": 0.1,  "step": 0.001,"group": "Risk Management",    "description": "Fraction of account balance risked per trade"},
    {"key": "max_daily_trades",   "label": "Max Daily Trades",      "type": "int",   "default": 3,    "min": 1,     "max": 20,   "step": 1,    "group": "Risk Management",    "description": "Maximum number of trades allowed per session day"},
]


# ── Helpers ──────────────────────────────────────────────────────
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
    if n < period:
        return out
    out[period - 1] = sum(b[key] for b in bars[:period]) / period
    k = 2 / (period + 1)
    for i in range(period, n):
        out[i] = bars[i][key] * k + out[i - 1] * (1 - k)
    return out


def _sma_vol(bars, period):
    n = len(bars)
    out = [0.0] * n
    for i in range(period - 1, n):
        out[i] = sum(bars[j].get("volume", 0) for j in range(i - period + 1, i + 1)) / period
    return out


def _adx(bars, period):
    n = len(bars)
    out = [0.0] * n
    if n < period * 2:
        return out
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    tr = [0.0] * n
    for i in range(1, n):
        hi_diff = bars[i]["high"] - bars[i - 1]["high"]
        lo_diff = bars[i - 1]["low"] - bars[i]["low"]
        plus_dm[i] = hi_diff if hi_diff > lo_diff and hi_diff > 0 else 0
        minus_dm[i] = lo_diff if lo_diff > hi_diff and lo_diff > 0 else 0
        tr[i] = max(bars[i]["high"] - bars[i]["low"],
                     abs(bars[i]["high"] - bars[i - 1]["close"]),
                     abs(bars[i]["low"] - bars[i - 1]["close"]))
    sm_tr = [0.0] * n
    sm_pdm = [0.0] * n
    sm_mdm = [0.0] * n
    sm_tr[period] = sum(tr[1:period + 1])
    sm_pdm[period] = sum(plus_dm[1:period + 1])
    sm_mdm[period] = sum(minus_dm[1:period + 1])
    for i in range(period + 1, n):
        sm_tr[i] = sm_tr[i - 1] - (sm_tr[i - 1] / period) + tr[i]
        sm_pdm[i] = sm_pdm[i - 1] - (sm_pdm[i - 1] / period) + plus_dm[i]
        sm_mdm[i] = sm_mdm[i - 1] - (sm_mdm[i - 1] / period) + minus_dm[i]
    dx = [0.0] * n
    for i in range(period, n):
        if sm_tr[i] == 0:
            continue
        pdi = 100 * sm_pdm[i] / sm_tr[i]
        mdi = 100 * sm_mdm[i] / sm_tr[i]
        s = pdi + mdi
        dx[i] = 100 * abs(pdi - mdi) / s if s > 0 else 0
    out[period * 2 - 1] = sum(dx[period:period * 2]) / period if period > 0 else 0
    for i in range(period * 2, n):
        out[i] = (out[i - 1] * (period - 1) + dx[i]) / period
    return out


def _get_hour(bar):
    t = bar.get("time", "")
    if isinstance(t, str):
        for sep in [" ", "T"]:
            if sep in t:
                try:
                    return int(t.split(sep)[-1].split(":")[0])
                except:
                    pass
    elif isinstance(t, (int, float)):
        import datetime
        try:
            return datetime.datetime.utcfromtimestamp(t).hour
        except:
            pass
    return -1


# ── Strategy ─────────────────────────────────────────────────────
class ETHUSDMomentumScalper:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.ema_fast = _ema(bars, self.s["fast_ema"])
        self.ema_slow = _ema(bars, self.s["slow_ema"])
        self.vol_avg = _sma_vol(bars, self.s["vol_period"])
        self.adx = _adx(bars, self.s["adx_period"])
        self.atr = _atr(bars, self.s["atr_period"])
        self.daily_count = 0
        self.last_day = -1

    def on_bar(self, i, bar):
        p = self.s
        hour = _get_hour(bar)

        # -- reset daily trade counter on new day --
        t = bar.get("time", "")
        day_key = str(t)[:10] if isinstance(t, str) else i // 288
        if day_key != self.last_day:
            self.daily_count = 0
            self.last_day = day_key

        # -- close all trades at session end --
        if hour >= p["session_end_hour"]:
            for tr in list(open_trades):
                close_trade(tr, i, bar["close"], "session_end")
            return

        # -- need enough data for indicators --
        min_bars = max(p["slow_ema"], p["atr_period"] + 1, p["adx_period"] * 2)
        if i < min_bars:
            return

        # -- skip if outside session or already positioned --
        if hour < p["session_start_hour"] or hour >= p["session_end_hour"]:
            return
        if len(open_trades) > 0:
            return
        if self.daily_count >= p["max_daily_trades"]:
            return

        # -- read indicator values --
        ef_now = self.ema_fast[i]
        ef_prev = self.ema_fast[i - 1]
        es_now = self.ema_slow[i]
        es_prev = self.ema_slow[i - 1]
        vol = bar.get("volume", 0)
        avg_vol = self.vol_avg[i]
        adx_val = self.adx[i]
        atr_val = self.atr[i]

        if atr_val <= 0 or avg_vol <= 0:
            return

        # -- check filters --
        vol_ok = vol > p["vol_mult"] * avg_vol
        adx_ok = adx_val > p["adx_min"]

        if not vol_ok or not adx_ok:
            return

        entry = bar["close"]
        sl_dist = atr_val * p["atr_sl_mult"]
        tp_dist = atr_val * p["atr_tp_mult"]

        # -- LONG cross: fast crosses above slow --
        if ef_now > es_now and ef_prev <= es_prev:
            sl = entry - sl_dist
            tp = entry + tp_dist
            open_trade(i, "long", entry, sl, tp, p["risk_per_trade"])
            self.daily_count += 1

        # -- SHORT cross: fast crosses below slow --
        elif ef_now < es_now and ef_prev >= es_prev:
            sl = entry + sl_dist
            tp = entry - tp_dist
            open_trade(i, "short", entry, sl, tp, p["risk_per_trade"])
            self.daily_count += 1
