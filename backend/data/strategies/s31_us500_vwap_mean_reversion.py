"""
Strategy 31: US500 VWAP Mean Reversion
======================================
Target : US500 (S&P 500 index) M5
Style  : Intraday mean reversion back to session VWAP

Core idea: When price deviates significantly from session VWAP during
ranging conditions (low ADX), enter on a reversal candle expecting a
snap-back toward VWAP. Session-based: all trades close at session end.

Entry:
  - Price deviation from VWAP exceeds ATR * atr_mult
  - Reversal candle pattern (close moves back toward VWAP)
  - ADX < adx_max (ranging market favors mean reversion)
  - Within allowed session hours (UTC)
  - No existing position

Exit:
  - TP at VWAP level
  - SL at candle extreme +/- ATR * atr_sl_mult
  - Forced close at session_end_hour
"""

# -- Settings (tunable via FlowrexAlgo UI) ---------------------------------
DEFAULTS = {
    "atr_period":        14,
    "atr_mult":          1.0,
    "adx_max":           30,
    "atr_sl_mult":       0.5,
    "session_start_hour": 13,
    "session_end_hour":  20,
    "risk_per_trade":    0.01,
    "max_daily_trades":  4,
}

SETTINGS = [
    {"key": "atr_period",        "label": "ATR Period",          "type": "int",   "default": 14,   "min": 5,    "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "Lookback period for Average True Range calculation"},
    {"key": "atr_mult",          "label": "VWAP Deviation Mult", "type": "float", "default": 1.0,  "min": 0.3,  "max": 3.0,  "step": 0.1,  "group": "Indicator Settings", "description": "Minimum price deviation from VWAP as a multiple of ATR to trigger entry"},
    {"key": "adx_max",           "label": "ADX Max (Range)",     "type": "int",   "default": 30,   "min": 15,   "max": 50,   "step": 1,    "group": "Filters",            "description": "Maximum ADX value; above this the market is trending and entries are skipped"},
    {"key": "atr_sl_mult",       "label": "ATR Stop-Loss Mult",  "type": "float", "default": 0.5,  "min": 0.2,  "max": 2.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Stop-loss distance beyond candle extreme as a multiple of ATR"},
    {"key": "session_start_hour", "label": "Session Start (UTC)", "type": "int",  "default": 13,   "min": 0,    "max": 23,   "step": 1,    "group": "Filters",            "description": "UTC hour when the strategy starts scanning for entries"},
    {"key": "session_end_hour",  "label": "Session End (UTC)",   "type": "int",   "default": 20,   "min": 1,    "max": 23,   "step": 1,    "group": "Filters",            "description": "UTC hour when the strategy closes all open positions"},
    {"key": "risk_per_trade",    "label": "Risk Per Trade",      "type": "float", "default": 0.01, "min": 0.001,"max": 0.1,  "step": 0.001,"group": "Risk Management",    "description": "Fraction of account balance risked per trade"},
    {"key": "max_daily_trades",  "label": "Max Daily Trades",    "type": "int",   "default": 4,    "min": 1,    "max": 20,   "step": 1,    "group": "Risk Management",    "description": "Maximum number of trades allowed per session day"},
]


# -- Helpers ----------------------------------------------------------------
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
                time_part = t.split(sep)[-1]
                try:
                    return int(time_part.split(":")[0])
                except:
                    pass
    elif isinstance(t, (int, float)):
        import datetime
        try:
            dt = datetime.datetime.utcfromtimestamp(t)
            return dt.hour
        except:
            pass
    return -1


def _vwap(bars):
    n = len(bars)
    out = [0.0] * n
    cum_pv = 0.0
    cum_vol = 0.0
    last_day = -1
    for i in range(n):
        b = bars[i]
        t = b.get("time", 0)
        if isinstance(t, (int, float)):
            import datetime
            try:
                day = datetime.datetime.utcfromtimestamp(t).date()
            except:
                day = i // 300
        elif isinstance(t, str):
            day = t[:10]
        else:
            day = i // 300
        if day != last_day:
            cum_pv = 0.0
            cum_vol = 0.0
            last_day = day
        typical = (b["high"] + b["low"] + b["close"]) / 3
        vol = b.get("volume", 1)
        cum_pv += typical * vol
        cum_vol += vol
        out[i] = cum_pv / cum_vol if cum_vol > 0 else typical
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


def _get_day(bar):
    t = bar.get("time", "")
    if isinstance(t, str):
        return t[:10]
    elif isinstance(t, (int, float)):
        import datetime
        try:
            return str(datetime.datetime.utcfromtimestamp(t).date())
        except:
            pass
    return ""


# -- Strategy Logic ---------------------------------------------------------
class US500VwapMeanReversion:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.atr_values = _atr(bars, self.s["atr_period"])
        self.adx_values = _adx(bars, self.s["atr_period"])
        self.vwap_values = _vwap(bars)
        self.daily_trade_count = 0
        self.last_trade_day = ""

    def on_bar(self, i, bar):
        s = self.s
        if i < s["atr_period"] * 2 + 1:
            return

        hour = _get_hour(bar)
        today = _get_day(bar)

        # Reset daily trade counter on new day
        if today != self.last_trade_day:
            self.daily_trade_count = 0
            self.last_trade_day = today

        # Close all positions at session end
        if hour >= s["session_end_hour"]:
            for t in list(open_trades):
                close_trade(t, i, bar["close"], "session_end")
            return

        # Only trade within session window
        if hour < s["session_start_hour"] or hour >= s["session_end_hour"]:
            return

        atr_val = self.atr_values[i]
        adx_val = self.adx_values[i]
        vwap_val = self.vwap_values[i]

        if atr_val <= 0 or vwap_val <= 0:
            return

        # No trade if already positioned or daily limit hit
        if len(open_trades) > 0:
            return
        if self.daily_trade_count >= s["max_daily_trades"]:
            return

        # ADX filter: only trade in ranging conditions
        if adx_val > s["adx_max"]:
            return

        close = bar["close"]
        deviation = atr_val * s["atr_mult"]
        prev = self.bars[i - 1]

        # -- LONG: price below VWAP by deviation + reversal candle --
        if close < vwap_val - deviation:
            if close > bar["open"] and close > prev["close"]:
                sl = bar["low"] - atr_val * s["atr_sl_mult"]
                tp = vwap_val
                open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
                self.daily_trade_count += 1

        # -- SHORT: price above VWAP by deviation + reversal candle --
        elif close > vwap_val + deviation:
            if close < bar["open"] and close < prev["close"]:
                sl = bar["high"] + atr_val * s["atr_sl_mult"]
                tp = vwap_val
                open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
                self.daily_trade_count += 1
