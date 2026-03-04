"""
Strategy 16: VWAP Mean Reversion Bands
========================================
Inspired by: Brian Shannon ("Technical Analysis Using Multiple Timeframes").

Core idea: VWAP acts as institutional fair value. Price tends to revert to
VWAP, especially with standard deviation bands. Use VWAP ±1σ / ±2σ bands.
  Long : Price touches -2σ band and bounces (reversal candle)
  Short: Price touches +2σ band and rejects

Filters: Volume spike confirms institutional participation.

Markets : Universal (especially intraday on liquid instruments)
Timeframe: 1m / 5m / 15m (intraday)
"""

DEFAULTS = {
    "vwap_period":      100,       # Rolling VWAP window (fixed window, no decay)
    "band_mult_entry":  2.0,       # Entry at ±2.0 stdev bands
    "band_mult_exit":   0.5,       # Exit near VWAP (±0.5 stdev)
    "vol_spike_mult":   1.0,       # Volume must be 1.0x avg (disabled effectively)
    "vol_avg_period":   20,
    "reversal_confirm": True,      # Re-enabled: require reversal candle for MR
    "atr_period":       14,
    "atr_sl_mult":      1.5,
    "atr_tp_mult":      2.5,
    "risk_per_trade":   0.01,
}


SETTINGS = [
    {"key": "vwap_period",      "label": "VWAP Period",            "type": "int",   "default": 100,  "min": 20,   "max": 500,  "step": 1,   "group": "Indicator Settings", "description": "Rolling VWAP lookback window (bars)"},
    {"key": "band_mult_entry",  "label": "Entry Band Multiplier",  "type": "float", "default": 2.0,  "min": 0.5,  "max": 4.0,  "step": 0.1, "group": "Entry Rules",        "description": "Std-dev multiplier for entry bands (e.g. 2.0 = +/-2 sigma)"},
    {"key": "band_mult_exit",   "label": "Exit Band Multiplier",   "type": "float", "default": 0.5,  "min": 0.1,  "max": 2.0,  "step": 0.1, "group": "Exit Rules",         "description": "Std-dev multiplier for exit zone near VWAP"},
    {"key": "vol_spike_mult",   "label": "Volume Spike Multiplier","type": "float", "default": 1.0,  "min": 0.5,  "max": 5.0,  "step": 0.1, "group": "Filters",            "description": "Minimum volume as multiple of average (1.0 = no filter)"},
    {"key": "vol_avg_period",   "label": "Volume Average Period",  "type": "int",   "default": 20,   "min": 5,    "max": 100,  "step": 1,   "group": "Filters",            "description": "Lookback period for average volume calculation"},
    {"key": "reversal_confirm", "label": "Require Reversal Candle","type": "bool",  "default": True,                                          "group": "Entry Rules",        "description": "Require a reversal candle pattern before entering"},
    {"key": "atr_period",       "label": "ATR Period",             "type": "int",   "default": 14,   "min": 5,    "max": 50,   "step": 1,   "group": "Risk Management",    "description": "ATR lookback period for stop/target sizing"},
    {"key": "atr_sl_mult",      "label": "ATR Stop-Loss Mult",    "type": "float", "default": 1.5,  "min": 0.5,  "max": 5.0,  "step": 0.1, "group": "Risk Management",    "description": "ATR multiplier for stop-loss distance"},
    {"key": "atr_tp_mult",      "label": "ATR Take-Profit Mult",  "type": "float", "default": 2.5,  "min": 0.5,  "max": 10.0, "step": 0.1, "group": "Risk Management",    "description": "ATR multiplier for take-profit distance (fallback if VWAP target invalid)"},
    {"key": "risk_per_trade",   "label": "Risk Per Trade",         "type": "float", "default": 0.01, "min": 0.001,"max": 0.05, "step": 0.001,"group": "Risk Management",   "description": "Fraction of account equity risked per trade"},
]


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


class VWAPMeanReversion:
    def init(self, bars, s):
        self.s = {**DEFAULTS, **s}
        self.bars = bars
        n = len(bars)
        vp = self.s["vwap_period"]

        # Compute rolling VWAP with fixed window — stable anchor for mean reversion
        self.vwap = [0.0] * n
        self.vwap_upper = [0.0] * n
        self.vwap_lower = [0.0] * n

        # Pre-compute typical price and volume arrays
        tp_arr = [(bars[i]["high"] + bars[i]["low"] + bars[i]["close"]) / 3.0 for i in range(n)]
        vol_arr = [max(bars[i].get("volume", 0), 1) for i in range(n)]

        for i in range(vp - 1, n):
            start = i - vp + 1
            sum_pv = 0.0
            sum_vol = 0.0
            for j in range(start, i + 1):
                sum_pv += tp_arr[j] * vol_arr[j]
                sum_vol += vol_arr[j]

            if sum_vol > 0:
                vwap_val = sum_pv / sum_vol
                self.vwap[i] = vwap_val

                # Standard deviation of TP around VWAP, volume-weighted
                sum_sq = 0.0
                for j in range(start, i + 1):
                    sum_sq += vol_arr[j] * (tp_arr[j] - vwap_val) ** 2
                variance = sum_sq / sum_vol
                stdev = variance ** 0.5

                self.vwap_upper[i] = vwap_val + self.s["band_mult_entry"] * stdev
                self.vwap_lower[i] = vwap_val - self.s["band_mult_entry"] * stdev

        # Volume average
        self.vol_avg = [0.0] * n
        vp = self.s["vol_avg_period"]
        vol_list = [max(bars[i].get("volume", 0), 0) for i in range(n)]
        if vp <= n:
            s_vol = sum(vol_list[:vp])
            self.vol_avg[vp - 1] = s_vol / vp
            for i in range(vp, n):
                s_vol += vol_list[i] - vol_list[i - vp]
                self.vol_avg[i] = s_vol / vp

        self.atr_vals = _atr(bars, self.s["atr_period"])

    def _is_bullish_reversal(self, i):
        """Bullish reversal candle: close > open, lower wick > body."""
        bar = self.bars[i]
        body = abs(bar["close"] - bar["open"])
        lower_wick = min(bar["open"], bar["close"]) - bar["low"]
        return bar["close"] > bar["open"] and lower_wick > body

    def _is_bearish_reversal(self, i):
        """Bearish reversal candle: close < open, upper wick > body."""
        bar = self.bars[i]
        body = abs(bar["close"] - bar["open"])
        upper_wick = bar["high"] - max(bar["open"], bar["close"])
        return bar["close"] < bar["open"] and upper_wick > body

    def on_bar(self, i, bar):
        s = self.s
        warmup = max(s["vwap_period"], s["vol_avg_period"], s["atr_period"]) + 5
        if i < warmup:
            return

        atr_val = self.atr_vals[i]
        vwap = self.vwap[i]
        if atr_val <= 0 or vwap <= 0:
            return

        close = bar["close"]
        vol = max(bar.get("volume", 0), 0)
        vol_avg = self.vol_avg[i]

        # Exit near VWAP
        for t in list(open_trades):
            dist_to_vwap = abs(close - vwap)
            half_band = abs(self.vwap_upper[i] - vwap) * (s["band_mult_exit"] / s["band_mult_entry"])
            if dist_to_vwap < half_band:
                close_trade(t, i, close, "vwap_reversion")

        if len(open_trades) > 0:
            return

        # Volume spike filter
        if vol_avg > 0 and vol < vol_avg * s["vol_spike_mult"]:
            return

        # Long: price at or below lower band + reversal candle
        if close <= self.vwap_lower[i]:
            if not s["reversal_confirm"] or self._is_bullish_reversal(i):
                sl = close - atr_val * s["atr_sl_mult"]
                tp = vwap  # Target = VWAP itself
                if tp <= close:
                    tp = close + atr_val * s["atr_tp_mult"]
                open_trade(i, "long", close, sl, tp, s["risk_per_trade"])

        # Short: price at or above upper band + reversal candle
        elif close >= self.vwap_upper[i]:
            if not s["reversal_confirm"] or self._is_bearish_reversal(i):
                sl = close + atr_val * s["atr_sl_mult"]
                tp = vwap
                if tp >= close:
                    tp = close - atr_val * s["atr_tp_mult"]
                open_trade(i, "short", close, sl, tp, s["risk_per_trade"])
