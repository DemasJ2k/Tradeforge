"""
Institutional Composite Strategy (s27) — Simplified
====================================================
EMA trend bias + Fair Value Gap retracement entries.

Logic:
  1. EMA(21) vs EMA(50) determines bullish/bearish bias
  2. Detect FVGs (3-candle imbalance: bar[i-2].high < bar[i].low for bullish)
  3. Long: bullish EMA bias + bullish FVG in last N bars + price retraces into gap
  4. Short: bearish EMA bias + bearish FVG + price retraces into gap
  5. SL = ATR * 2.0, TP = ATR * 3.0
  6. Max 1 trade at a time, cooldown of 3 bars

Author: FlowrexAlgo AI
Version: 3.0 (simplified)
"""

DEFAULTS = {
    "ema_fast": 21,
    "ema_slow": 50,
    "fvg_lookback": 10,
    "atr_period": 14,
    "atr_sl_mult": 2.0,
    "atr_tp_mult": 3.0,
    "cooldown_bars": 3,
    "risk_per_trade": 0.01,
}

SETTINGS = [
    {"key": "ema_fast",        "label": "EMA Fast Period",    "type": "int",   "default": 21,   "min": 5,    "max": 50,  "step": 1,    "group": "Trend",           "description": "Fast EMA period for trend bias"},
    {"key": "ema_slow",        "label": "EMA Slow Period",    "type": "int",   "default": 50,   "min": 20,   "max": 200, "step": 1,    "group": "Trend",           "description": "Slow EMA period for trend bias"},
    {"key": "fvg_lookback",    "label": "FVG Lookback (bars)","type": "int",   "default": 10,   "min": 3,    "max": 30,  "step": 1,    "group": "Fair Value Gaps", "description": "How many bars back to search for an active FVG"},
    {"key": "atr_period",      "label": "ATR Period",         "type": "int",   "default": 14,   "min": 5,    "max": 50,  "step": 1,    "group": "Risk Management", "description": "Lookback period for ATR calculation"},
    {"key": "atr_sl_mult",     "label": "ATR SL Multiplier",  "type": "float", "default": 2.0,  "min": 0.5,  "max": 5.0, "step": 0.1,  "group": "Risk Management", "description": "Stop-loss distance as a multiple of ATR"},
    {"key": "atr_tp_mult",     "label": "ATR TP Multiplier",  "type": "float", "default": 3.0,  "min": 0.5,  "max": 8.0, "step": 0.1,  "group": "Risk Management", "description": "Take-profit distance as a multiple of ATR"},
    {"key": "cooldown_bars",   "label": "Cooldown Bars",      "type": "int",   "default": 3,    "min": 0,    "max": 20,  "step": 1,    "group": "Risk Management", "description": "Minimum bars between consecutive trades"},
    {"key": "risk_per_trade",  "label": "Risk Per Trade",     "type": "float", "default": 0.01, "min": 0.001,"max": 0.05,"step": 0.001,"group": "Risk Management", "description": "Fraction of account equity risked per trade"},
]


class InstitutionalComposite:
    """EMA trend + FVG retracement strategy."""

    def init(self, bars, settings):
        self.bars = bars
        self.s = {**DEFAULTS, **settings}
        n = len(bars)

        # --- ATR (Wilder / EMA-smoothed) ---
        self.atr = [0.0] * n
        p = self.s["atr_period"]
        if n > p + 1:
            tr_sum = 0.0
            for i in range(1, p + 1):
                tr_sum += max(
                    bars[i]["high"] - bars[i]["low"],
                    abs(bars[i]["high"] - bars[i - 1]["close"]),
                    abs(bars[i]["low"] - bars[i - 1]["close"]),
                )
            self.atr[p] = tr_sum / p
            k = 1.0 / p
            for i in range(p + 1, n):
                tr = max(
                    bars[i]["high"] - bars[i]["low"],
                    abs(bars[i]["high"] - bars[i - 1]["close"]),
                    abs(bars[i]["low"] - bars[i - 1]["close"]),
                )
                self.atr[i] = self.atr[i - 1] * (1 - k) + tr * k

        # --- EMAs ---
        self.ema_fast = self._ema(n, self.s["ema_fast"])
        self.ema_slow = self._ema(n, self.s["ema_slow"])

        # --- Detect all FVGs up front ---
        # Each entry: (bar_index, zone_top, zone_bottom)
        self.fvg_bull = []
        self.fvg_bear = []
        for i in range(2, n):
            # Bullish FVG: gap up — bar[i].low > bar[i-2].high
            if bars[i]["low"] > bars[i - 2]["high"]:
                self.fvg_bull.append((i, bars[i]["low"], bars[i - 2]["high"]))
            # Bearish FVG: gap down — bar[i].high < bar[i-2].low
            if bars[i]["high"] < bars[i - 2]["low"]:
                self.fvg_bear.append((i, bars[i - 2]["low"], bars[i]["high"]))

        # --- State ---
        self.last_trade_bar = -100

    def _ema(self, n, period):
        ema = [0.0] * n
        if n < period:
            return ema
        sma = sum(self.bars[i]["close"] for i in range(period)) / period
        ema[period - 1] = sma
        k = 2.0 / (period + 1)
        for i in range(period, n):
            ema[i] = self.bars[i]["close"] * k + ema[i - 1] * (1 - k)
        return ema

    def _recent_fvg(self, i, direction):
        """Return the most recent FVG zone (top, bottom) within lookback, or None."""
        lb = self.s["fvg_lookback"]
        fvgs = self.fvg_bull if direction == "long" else self.fvg_bear
        # Walk backwards through FVG list for efficiency
        for j in range(len(fvgs) - 1, -1, -1):
            fidx, top, bot = fvgs[j]
            if fidx > i:
                continue
            if i - fidx > lb:
                return None
            return (top, bot)
        return None

    # ------------------------------------------------------------------
    def on_bar(self, i, bar):
        atr = self.atr[i]
        if atr <= 0 or i < self.s["ema_slow"] + 2:
            return

        # Cooldown
        if i - self.last_trade_bar < self.s["cooldown_bars"]:
            return

        # Max 1 trade at a time
        if len(open_trades) >= 1:
            return

        close = bar["close"]

        # --- Condition 1: EMA trend bias ---
        if self.ema_fast[i] > self.ema_slow[i]:
            direction = "long"
        elif self.ema_fast[i] < self.ema_slow[i]:
            direction = "short"
        else:
            return

        # --- Condition 2: Recent FVG exists ---
        fvg = self._recent_fvg(i, direction)
        if fvg is None:
            return

        zone_top, zone_bot = fvg

        # --- Condition 3: Price retraces into the FVG zone ---
        # Bar's low dips into a bullish FVG, or bar's high reaches into a bearish FVG
        if direction == "long":
            if not (bar["low"] <= zone_top and close >= zone_bot):
                return
        else:
            if not (bar["high"] >= zone_bot and close <= zone_top):
                return

        # --- Execute trade ---
        sl_dist = self.s["atr_sl_mult"] * atr
        tp_dist = self.s["atr_tp_mult"] * atr
        risk = self.s["risk_per_trade"]

        if direction == "long":
            open_trade(i, "long", close, close - sl_dist, close + tp_dist, risk)
        else:
            open_trade(i, "short", close, close + sl_dist, close - tp_dist, risk)

        self.last_trade_bar = i
