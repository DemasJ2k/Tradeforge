"""
Institutional Composite Strategy (s27)
======================================
A comprehensive institutional-grade strategy that combines the most
proven concepts from ICT, SMC, Wyckoff, and CTA methodologies.

Core Logic (based on deep institutional research):
  1. SESSION TIMING (Kill Zone filter)
     - Only trades during London (02:00-05:00 EST) and NY (07:00-10:00 EST)
     - Aligns with peak institutional activity and volume

  2. MARKET STRUCTURE (HTF Bias)
     - Uses BOS/CHoCH detection for trend direction
     - EMA trend filter as additional confirmation

  3. LIQUIDITY SWEEP DETECTION
     - Identifies stop hunts at swing highs/lows
     - Waits for price to wick beyond and close back inside
     - This is THE signature institutional footprint

  4. ENTRY AT INSTITUTIONAL ZONES
     - Fair Value Gaps (3-candle imbalance zones)
     - Order Blocks (last opposing candle before impulse)
     - Entries at these zones after a confirmed sweep

  5. PREMIUM / DISCOUNT FILTER
     - Only buy in discount (below 50% of range)
     - Only sell in premium (above 50% of range)
     - Based on OTE (Optimal Trade Entry) Fibonacci zones

  6. AMD MODEL (Power of 3)
     - Asian Range = Accumulation
     - Kill Zone break of Asian range = Manipulation
     - Trade the reversal = Distribution

  7. VOLUME ANOMALY DETECTION
     - Relative volume spikes at key levels confirm institutional activity
     - Tick volume serves as ~80% correlated proxy

Risk Management:
  - ATR-based SL/TP
  - Max concurrent positions limit
  - Cooldown between trades
  - Position sizing via risk percentage

Author: TradeForge AI
Version: 2.0 (research-based rebuild)
"""

import math

DEFAULTS = {
    # --- Session / Kill Zone ---
    "use_kill_zone": True,
    "london_start_hour": 7,    # UTC (02:00 EST = 07:00 UTC)
    "london_end_hour": 10,     # UTC (05:00 EST = 10:00 UTC)
    "ny_start_hour": 12,       # UTC (07:00 EST = 12:00 UTC)
    "ny_end_hour": 15,         # UTC (10:00 EST = 15:00 UTC)

    # --- Market Structure ---
    "swing_length": 15,        # bars to define swing highs/lows
    "use_ema_filter": True,    # use EMA trend filter
    "ema_fast": 21,
    "ema_slow": 50,

    # --- Liquidity Sweep ---
    "sweep_lookback": 25,       # bars to look back for swing levels
    "sweep_threshold_atr": 0.1, # how far past swing = sweep (ATR)

    # --- Fair Value Gaps ---
    "fvg_min_size_atr": 0.3,   # minimum FVG size in ATR units
    "fvg_max_age": 25,         # max candles old an FVG can be

    # --- Order Blocks ---
    "ob_min_impulse_atr": 1.5, # min ATR move after OB to validate
    "ob_max_age": 30,          # max candles old an OB can be

    # --- Premium / Discount ---
    "use_pd_filter": True,
    "pd_range_lookback": 50,   # bars for Fib zone calculation
    "premium_fib": 0.5,        # above = premium, below = discount

    # --- AMD Model ---
    "use_amd": False,           # Asian range manipulation
    "asian_start_hour": 0,     # UTC
    "asian_end_hour": 7,       # UTC

    # --- Volume Confirmation ---
    "use_volume_filter": True,
    "vol_lookback": 20,
    "vol_spike_mult": 1.3,     # 1.3x = 30% above avg

    # --- Risk Management ---
    "atr_period": 14,
    "atr_sl_mult": 2.0,
    "atr_tp_mult": 3.5,
    "cooldown_bars": 3,
    "max_concurrent": 2,
    "risk_per_trade": 0.01,
}


class InstitutionalComposite:
    """
    Mimics institutional trading by combining:
    - Kill Zone timing (trade when institutions trade)
    - Liquidity sweeps (trade where institutions fill)
    - FVG/OB entries (trade at institutional price levels)
    - Premium/Discount filter (trade at institutional value)
    """

    def init(self, bars, settings):
        self.bars = bars
        self.s = {**DEFAULTS, **settings}
        n = len(bars)

        # Pre-compute ATR (Wilder method)
        self.atr = [0.0] * n
        p = self.s["atr_period"]
        if n > p + 1:
            tr_sum = 0.0
            for i in range(1, p + 1):
                tr = max(bars[i]["high"] - bars[i]["low"],
                         abs(bars[i]["high"] - bars[i - 1]["close"]),
                         abs(bars[i]["low"] - bars[i - 1]["close"]))
                tr_sum += tr
            self.atr[p] = tr_sum / p
            k = 1.0 / p
            for i in range(p + 1, n):
                tr = max(bars[i]["high"] - bars[i]["low"],
                         abs(bars[i]["high"] - bars[i - 1]["close"]),
                         abs(bars[i]["low"] - bars[i - 1]["close"]))
                self.atr[i] = self.atr[i - 1] * (1 - k) + tr * k

        # Pre-compute EMAs
        self.ema_fast = self._ema(n, self.s["ema_fast"])
        self.ema_slow = self._ema(n, self.s["ema_slow"])

        # Pre-compute volume moving average
        vl = self.s["vol_lookback"]
        self.vol_avg = [0.0] * n
        if n > vl:
            v_sum = sum(bars[i]["volume"] for i in range(vl))
            self.vol_avg[vl - 1] = v_sum / vl
            for i in range(vl, n):
                v_sum += bars[i]["volume"] - bars[i - vl]["volume"]
                self.vol_avg[i] = v_sum / vl

        # Detect swing highs/lows
        sw = self.s["swing_length"]
        self.swing_highs = {}
        self.swing_lows = {}
        for i in range(sw, n - sw):
            ws = max(0, i - sw)
            we = min(n, i + sw + 1)
            is_high = all(bars[i]["high"] >= bars[j]["high"]
                          for j in range(ws, we) if j != i)
            is_low = all(bars[i]["low"] <= bars[j]["low"]
                         for j in range(ws, we) if j != i)
            if is_high:
                self.swing_highs[i] = bars[i]["high"]
            if is_low:
                self.swing_lows[i] = bars[i]["low"]

        # Detect market structure (BOS tracking)
        self.structure_bias = [0] * n
        self._compute_structure(n)

        # Pre-detect Fair Value Gaps
        self.fvg_bull = []
        self.fvg_bear = []
        self._detect_fvgs(n)

        # Pre-detect Order Blocks
        self.ob_bull = []
        self.ob_bear = []
        self._detect_order_blocks(n)

        # State
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

    def _compute_structure(self, n):
        last_sh = 0.0
        last_sl = float('inf')
        bias = 0
        for i in range(n):
            bar = self.bars[i]
            if i in self.swing_highs:
                last_sh = self.swing_highs[i]
            if i in self.swing_lows:
                last_sl = self.swing_lows[i]
            if last_sh > 0 and bar["close"] > last_sh:
                bias = 1
            elif last_sl < float('inf') and bar["close"] < last_sl:
                bias = -1
            self.structure_bias[i] = bias

    def _detect_fvgs(self, n):
        min_size = self.s["fvg_min_size_atr"]
        for i in range(2, n):
            atr = self.atr[i]
            if atr <= 0:
                continue
            # Bullish FVG
            gb = self.bars[i - 2]["high"]
            gt = self.bars[i]["low"]
            if gt > gb and (gt - gb) >= min_size * atr:
                self.fvg_bull.append((i, gt, gb))
            # Bearish FVG
            gt_b = self.bars[i - 2]["low"]
            gb_b = self.bars[i]["high"]
            if gt_b > gb_b and (gt_b - gb_b) >= min_size * atr:
                self.fvg_bear.append((i, gt_b, gb_b))

    def _detect_order_blocks(self, n):
        impulse = self.s["ob_min_impulse_atr"]
        for i in range(2, n):
            atr = self.atr[i]
            if atr <= 0:
                continue
            prev = self.bars[i - 1]
            curr = self.bars[i]
            # Bullish OB
            if (prev["close"] < prev["open"]
                    and curr["close"] > curr["open"]
                    and (curr["close"] - prev["low"]) >= impulse * atr):
                self.ob_bull.append((i - 1, prev["high"], prev["low"]))
            # Bearish OB
            if (prev["close"] > prev["open"]
                    and curr["close"] < curr["open"]
                    and (prev["high"] - curr["close"]) >= impulse * atr):
                self.ob_bear.append((i - 1, prev["high"], prev["low"]))

    def _in_kill_zone(self, bar):
        time_str = bar.get("time", "")
        if not time_str:
            return True
        hour = self._extract_hour(time_str)
        if hour < 0:
            return True
        ls, le = self.s["london_start_hour"], self.s["london_end_hour"]
        ns, ne = self.s["ny_start_hour"], self.s["ny_end_hour"]
        return (ls <= hour < le) or (ns <= hour < ne)

    def _extract_hour(self, time_str):
        try:
            ts = time_str.replace("T", " ").replace(".", "-", 2)
            parts = ts.split(" ")
            if len(parts) >= 2:
                return int(parts[1].split(":")[0])
        except (ValueError, IndexError):
            pass
        return -1

    def _check_sweep(self, i):
        bar = self.bars[i]
        atr = self.atr[i]
        if atr <= 0:
            return 0
        threshold = self.s["sweep_threshold_atr"] * atr
        lookback = self.s["sweep_lookback"]

        # Bullish sweep: wick below swing low, close back above
        for si in range(max(0, i - lookback), i):
            if si in self.swing_lows:
                sl_lvl = self.swing_lows[si]
                if bar["low"] < sl_lvl - threshold and bar["close"] > sl_lvl:
                    return 1

        # Bearish sweep: wick above swing high, close back below
        for si in range(max(0, i - lookback), i):
            if si in self.swing_highs:
                sh_lvl = self.swing_highs[si]
                if bar["high"] > sh_lvl + threshold and bar["close"] < sh_lvl:
                    return -1
        return 0

    def _price_in_fvg(self, price, i, direction):
        max_age = self.s["fvg_max_age"]
        fvgs = self.fvg_bull if direction == "long" else self.fvg_bear
        for (fidx, top, bottom) in reversed(fvgs):
            if fidx > i:
                continue
            if i - fidx > max_age:
                break
            if bottom <= price <= top:
                return True
        return False

    def _price_in_ob(self, price, i, direction):
        max_age = self.s["ob_max_age"]
        obs = self.ob_bull if direction == "long" else self.ob_bear
        for (oidx, top, bottom) in reversed(obs):
            if oidx > i:
                continue
            if i - oidx > max_age:
                break
            if bottom <= price <= top:
                return True
        return False

    def _in_correct_zone(self, price, i, direction):
        if not self.s["use_pd_filter"]:
            return True
        lb = self.s["pd_range_lookback"]
        start = max(0, i - lb)
        rh = max(self.bars[j]["high"] for j in range(start, i + 1))
        rl = min(self.bars[j]["low"] for j in range(start, i + 1))
        tr = rh - rl
        if tr <= 0:
            return True
        pos = (price - rl) / tr
        fib = self.s["premium_fib"]
        if direction == "long":
            return pos < fib
        else:
            return pos > (1 - fib)

    def _volume_confirmed(self, i):
        if not self.s["use_volume_filter"]:
            return True
        avg = self.vol_avg[i]
        if avg <= 0:
            return True
        return self.bars[i]["volume"] >= avg * self.s["vol_spike_mult"]

    def _check_amd(self, i):
        if not self.s["use_amd"]:
            return 0
        bar = self.bars[i]
        hour = self._extract_hour(bar.get("time", ""))
        if hour < 0:
            return 0
        ls, le = self.s["london_start_hour"], self.s["london_end_hour"]
        if not (ls <= hour < le):
            return 0
        # Find Asian range
        as_h, ae_h = self.s["asian_start_hour"], self.s["asian_end_hour"]
        a_high, a_low = 0.0, float('inf')
        for j in range(max(0, i - 60), i):
            h = self._extract_hour(self.bars[j].get("time", ""))
            if as_h <= h < ae_h:
                a_high = max(a_high, self.bars[j]["high"])
                a_low = min(a_low, self.bars[j]["low"])
        if a_high <= a_low or a_high == 0:
            return 0
        if bar["high"] > a_high and bar["close"] < a_high:
            return -1
        if bar["low"] < a_low and bar["close"] > a_low:
            return 1
        return 0

    # ============================================================
    # MAIN SIGNAL LOGIC
    # ============================================================
    def on_bar(self, i, bar):
        atr = self.atr[i]
        if atr <= 0 or i < self.s["ema_slow"] + 10:
            return
        if i - self.last_trade_bar < self.s["cooldown_bars"]:
            return
        if len(open_trades) >= self.s["max_concurrent"]:
            return

        close = bar["close"]

        # FILTER 1: Kill Zone
        if self.s["use_kill_zone"] and not self._in_kill_zone(bar):
            return

        # FILTER 2: Trend Direction (structure + EMA confluence)
        trend = self.structure_bias[i]
        if self.s["use_ema_filter"]:
            ema_t = 0
            if self.ema_fast[i] > self.ema_slow[i] and close > self.ema_slow[i]:
                ema_t = 1
            elif self.ema_fast[i] < self.ema_slow[i] and close < self.ema_slow[i]:
                ema_t = -1
            if ema_t != 0 and trend != 0 and ema_t != trend:
                return
            if trend == 0:
                trend = ema_t
        if trend == 0:
            return

        direction = "long" if trend > 0 else "short"

        # SIGNAL: Liquidity Sweep
        sweep = self._check_sweep(i)
        primary = (sweep != 0 and sweep == trend)

        # SIGNAL: AMD manipulation reversal
        amd = self._check_amd(i)
        secondary = (amd != 0 and amd == trend)

        # SIGNAL: Price at institutional zone + fresh BOS
        in_zone = (self._price_in_fvg(close, i, direction) or
                   self._price_in_ob(close, i, direction))
        fresh_bos = (self.structure_bias[i] == trend and
                     i > 0 and self.structure_bias[i - 1] != trend)
        tertiary = in_zone and fresh_bos

        if not (primary or secondary or tertiary):
            return

        # FILTER 3: Premium/Discount
        if not self._in_correct_zone(close, i, direction):
            return

        # FILTER 4: Volume confirmation (required if no sweep)
        if not primary and not self._volume_confirmed(i):
            return

        # EXECUTE TRADE
        sl_m = self.s["atr_sl_mult"]
        tp_m = self.s["atr_tp_mult"]
        risk = self.s["risk_per_trade"]

        if direction == "long":
            open_trade(i, "long", close, close - sl_m * atr,
                       close + tp_m * atr, risk)
        else:
            open_trade(i, "short", close, close + sl_m * atr,
                       close - tp_m * atr, risk)

        self.last_trade_bar = i
