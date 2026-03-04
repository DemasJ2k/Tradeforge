"""
Strategy 01: Valentini Auction Market Theory (Volume Profile)
=============================================================
Inspired by: Fabio Valentini (3x Robbins World Cup, Chart Fanatics)

Core idea: Volume Profile + Order Flow to detect balance vs. imbalance.
Two models:
  1. TREND MODEL  – When price breaks out of the value area (above VAH or
     below VAL), ride the continuation move toward new value.
  2. MEAN REVERSION MODEL – When breakout fails and price re-enters the
     value area, trade the snap-back to the Point of Control (POC).

Markets : Universal (futures, forex, crypto, stocks)
Timeframe: 5m–15m (scalping/intraday)
"""

# ── Settings (tunable via TradeForge UI) ─────────────────────────
DEFAULTS = {
    "vp_lookback":     100,   # bars for volume profile calculation
    "vp_value_pct":    70.0,  # % of volume defining the value area
    "atr_period":      14,
    "atr_sl_mult":     1.5,   # SL = ATR * mult
    "atr_tp_mult":     2.5,   # TP = ATR * mult (trend model)
    "mean_rev_tp_pct": 0.5,   # TP at 50% retracement to POC (mean-rev model)
    "risk_per_trade":  0.01,  # 1 % of balance
    "adx_threshold":   20,    # ADX > threshold → trend model; else mean-rev
}


SETTINGS = [
    {"key": "vp_lookback",     "label": "VP Lookback",            "type": "int",   "default": 100,  "min": 20,    "max": 500,  "step": 1,    "group": "Indicator Settings", "description": "Number of bars used to calculate the volume profile"},
    {"key": "vp_value_pct",    "label": "Value Area %",           "type": "float", "default": 70.0, "min": 50.0,  "max": 90.0, "step": 1.0,  "group": "Indicator Settings", "description": "Percentage of total volume that defines the value area around POC"},
    {"key": "atr_period",      "label": "ATR Period",             "type": "int",   "default": 14,   "min": 5,     "max": 50,   "step": 1,    "group": "Indicator Settings", "description": "Lookback period for Average True Range calculation"},
    {"key": "atr_sl_mult",     "label": "ATR Stop-Loss Multiple", "type": "float", "default": 1.5,  "min": 0.5,   "max": 4.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Stop-loss distance as a multiple of ATR"},
    {"key": "atr_tp_mult",     "label": "ATR Take-Profit Multiple", "type": "float", "default": 2.5, "min": 1.0,  "max": 6.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Take-profit distance as a multiple of ATR (trend model)"},
    {"key": "mean_rev_tp_pct", "label": "Mean Reversion TP %",    "type": "float", "default": 0.5,  "min": 0.1,   "max": 1.0,  "step": 0.1,  "group": "Exit Rules",         "description": "Take-profit as percentage of distance to POC (mean-reversion model)"},
    {"key": "risk_per_trade",  "label": "Risk Per Trade",         "type": "float", "default": 0.01, "min": 0.001, "max": 0.1,  "step": 0.001, "group": "Risk Management",   "description": "Fraction of account balance risked per trade"},
    {"key": "adx_threshold",   "label": "ADX Threshold",          "type": "int",   "default": 20,   "min": 10,    "max": 50,   "step": 1,    "group": "Filters",            "description": "ADX value above which the trend model is used; below uses mean-reversion"},
]


# ── Helpers ──────────────────────────────────────────────────────
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


def _ema(data, period):
    out = [0.0] * len(data)
    if period > len(data):
        return out
    k = 2.0 / (period + 1)
    out[period - 1] = sum(data[:period]) / period
    for i in range(period, len(data)):
        out[i] = data[i] * k + out[i - 1] * (1 - k)
    return out


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


def _adx(bars, period=14):
    n = len(bars)
    out = [0.0] * n
    if n < period * 2 + 1:
        return out
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    tr = [0.0] * n
    for i in range(1, n):
        up = bars[i]["high"] - bars[i - 1]["high"]
        dn = bars[i - 1]["low"] - bars[i]["low"]
        plus_dm[i] = up if (up > dn and up > 0) else 0.0
        minus_dm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(
            bars[i]["high"] - bars[i]["low"],
            abs(bars[i]["high"] - bars[i - 1]["close"]),
            abs(bars[i]["low"] - bars[i - 1]["close"]),
        )
    smooth_tr = sum(tr[1 : period + 1])
    smooth_plus = sum(plus_dm[1 : period + 1])
    smooth_minus = sum(minus_dm[1 : period + 1])
    dx_vals = []
    for i in range(period, n):
        if i > period:
            smooth_tr = smooth_tr - smooth_tr / period + tr[i]
            smooth_plus = smooth_plus - smooth_plus / period + plus_dm[i]
            smooth_minus = smooth_minus - smooth_minus / period + minus_dm[i]
        plus_di = 100 * smooth_plus / smooth_tr if smooth_tr > 0 else 0
        minus_di = 100 * smooth_minus / smooth_tr if smooth_tr > 0 else 0
        s = plus_di + minus_di
        dx = 100 * abs(plus_di - minus_di) / s if s > 0 else 0
        dx_vals.append(dx)
    if len(dx_vals) >= period:
        adx_val = sum(dx_vals[:period]) / period
        idx = period + period - 1
        if idx < n:
            out[idx] = adx_val
        for j in range(period, len(dx_vals)):
            adx_val = (adx_val * (period - 1) + dx_vals[j]) / period
            idx = period + j
            if idx < n:
                out[idx] = adx_val
    return out


def _volume_profile(bars, end_idx, lookback):
    """Simple volume profile: return POC, VAH, VAL."""
    start = max(0, end_idx - lookback + 1)
    if start >= end_idx:
        return None, None, None

    # Collect price-volume buckets
    prices = []
    for i in range(start, end_idx + 1):
        b = bars[i]
        vol = b.get("volume", 1) or 1
        mid = (b["high"] + b["low"]) / 2
        prices.append((mid, vol))

    if not prices:
        return None, None, None

    lo = min(p[0] for p in prices)
    hi = max(p[0] for p in prices)
    if hi == lo:
        return lo, lo, lo

    num_bins = 50
    bin_size = (hi - lo) / num_bins
    bins = [0.0] * num_bins
    for price, vol in prices:
        idx = min(int((price - lo) / bin_size), num_bins - 1)
        bins[idx] += vol

    total_vol = sum(bins)
    poc_bin = bins.index(max(bins))
    poc = lo + (poc_bin + 0.5) * bin_size

    # Value area: 70% of volume around POC
    va_vol = bins[poc_bin]
    lo_idx, hi_idx = poc_bin, poc_bin
    while va_vol < total_vol * 0.70:
        expand_lo = bins[lo_idx - 1] if lo_idx > 0 else 0
        expand_hi = bins[hi_idx + 1] if hi_idx < num_bins - 1 else 0
        if expand_hi >= expand_lo and hi_idx < num_bins - 1:
            hi_idx += 1
            va_vol += expand_hi
        elif lo_idx > 0:
            lo_idx -= 1
            va_vol += expand_lo
        else:
            break

    val = lo + lo_idx * bin_size
    vah = lo + (hi_idx + 1) * bin_size
    return poc, vah, val


# ── Strategy Logic ───────────────────────────────────────────────
class ValentiniAuctionMarket:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        self.atr_values = _atr(bars, self.s["atr_period"])
        self.adx_values = _adx(bars, self.s["atr_period"])

    def on_bar(self, i, bar):
        s = self.s
        if i < s["vp_lookback"] + 1:
            return
        atr_val = self.atr_values[i]
        adx_val = self.adx_values[i]
        if atr_val <= 0:
            return
        if len(open_trades) > 0:
            return

        poc, vah, val = _volume_profile(self.bars, i - 1, s["vp_lookback"])
        if poc is None:
            return

        close = bar["close"]
        prev_close = self.bars[i - 1]["close"]

        is_trending = adx_val > s["adx_threshold"]

        # ── TREND MODEL (breakout from value area) ──
        if is_trending:
            # Bullish breakout: price breaks above VAH
            if close > vah and prev_close <= vah:
                sl = close - atr_val * s["atr_sl_mult"]
                tp = close + atr_val * s["atr_tp_mult"]
                open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
            # Bearish breakout: price breaks below VAL
            elif close < val and prev_close >= val:
                sl = close + atr_val * s["atr_sl_mult"]
                tp = close - atr_val * s["atr_tp_mult"]
                open_trade(i, "short", close, sl, tp, s["risk_per_trade"])

        # ── MEAN REVERSION MODEL (failed breakout snaps back to POC) ──
        else:
            # Failed bullish breakout: was above VAH, now re-enters
            if prev_close > vah and close <= vah:
                sl = close + atr_val * s["atr_sl_mult"]
                tp = close - abs(close - poc) * s["mean_rev_tp_pct"]
                open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
            # Failed bearish breakout: was below VAL, now re-enters
            elif prev_close < val and close >= val:
                sl = close - atr_val * s["atr_sl_mult"]
                tp = close + abs(poc - close) * s["mean_rev_tp_pct"]
                open_trade(i, "long", close, sl, tp, s["risk_per_trade"])
