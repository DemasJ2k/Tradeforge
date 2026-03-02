"""
Data handler for the V2 backtesting engine.

Responsibilities:
  - Converts raw bar/tick data into events and feeds them into the EventQueue
  - Enforces indicator warm-up period (skips first N bars from signal generation)
  - Multi-symbol: synchronizes bars across symbols by timestamp
  - Provides a "data window" API for strategies to look back at historical bars
  - Pre-computes indicators and attaches them to bars
  - Multi-timeframe: resamples lower-TF bars into higher-TF bars (Phase 1E)
  - Tick data: stores and feeds TickEvents (Phase 1E)

Key differences from V1:
  - V1 pre-computed indicators as flat arrays; V2 attaches per-bar snapshots
  - V1 had no warm-up enforcement; V2 skips warm-up period automatically
  - V2 supports multiple symbols feeding into the same queue
  - V2 supports multiple timeframes per symbol via resampling (Phase 1E)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from app.services.backtest.v2.engine.events import (
    BarEvent,
    TickEvent,
    EventType,
    timestamp_ns_from_unix,
)
from app.services.backtest.v2.engine.event_queue import EventQueue
from app.services.backtest import indicators as ind
from app.services.backtest import patterns as pat


# ── Timeframe Utilities (Phase 1E) ─────────────────────────────────

# Common timeframe labels → seconds
TIMEFRAME_SECONDS: dict[str, int] = {
    "M1": 60, "M2": 120, "M3": 180, "M4": 240, "M5": 300,
    "M6": 360, "M10": 600, "M12": 720, "M15": 900,
    "M20": 1200, "M30": 1800,
    "H1": 3600, "H2": 7200, "H3": 10800, "H4": 14400,
    "H6": 21600, "H8": 28800, "H12": 43200,
    "D1": 86400, "W1": 604800, "MN1": 2592000,
}


def parse_timeframe(label: str) -> int:
    """Convert a timeframe label (e.g. 'M5', 'H1', 'D1') to seconds.

    Also accepts raw seconds as string (e.g. '600').
    """
    label = label.strip().upper()
    if label in TIMEFRAME_SECONDS:
        return TIMEFRAME_SECONDS[label]
    try:
        return int(label)
    except ValueError:
        raise ValueError(f"Unknown timeframe: {label}")


def detect_timeframe(timestamps: list[float], label: str = "") -> int:
    """Auto-detect the bar interval in seconds from timestamps.

    If *label* is provided, uses the known mapping.  Otherwise computes
    the median interval from the first 100 inter-bar deltas.
    """
    if label:
        try:
            return parse_timeframe(label)
        except ValueError:
            pass

    if len(timestamps) < 2:
        return 0

    deltas = []
    for i in range(1, min(len(timestamps), 101)):
        d = timestamps[i] - timestamps[i - 1]
        if d > 0:
            deltas.append(d)

    if not deltas:
        return 0

    deltas.sort()
    return int(deltas[len(deltas) // 2])


# ── Bar Data ────────────────────────────────────────────────────────


@dataclass(slots=True)
class BarData:
    """A single OHLCV bar with attached indicators."""
    timestamp_ns: int = 0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    bar_index: int = 0
    indicators: dict[str, float] = field(default_factory=dict)


class SymbolData:
    """Historical bar data and indicator values for a single symbol.

    Provides:
      - Array-based storage for fast indicator computation
      - Per-bar access via index
      - Indicator pre-computation from config
      - Warm-up period calculation
    """

    def __init__(self, symbol: str, point_value: float = 1.0, timeframe_s: int = 0):
        self.symbol = symbol
        self.point_value = point_value
        self.timeframe_s: int = timeframe_s  # bar period in seconds (0 = unknown)

        # Raw OHLCV arrays (for indicator computation)
        self.timestamps: list[float] = []  # Unix seconds
        self.opens: list[float] = []
        self.highs: list[float] = []
        self.lows: list[float] = []
        self.closes: list[float] = []
        self.volumes: list[float] = []

        # Pre-computed indicator arrays (filled by compute_indicators)
        self.indicator_arrays: dict[str, list[float]] = {}

        # Higher-timeframe data (Phase 1E — multi-TF)
        # Keyed by timeframe label, e.g. {"H1": SymbolData, "D1": SymbolData}
        self.htf_data: dict[str, "SymbolData"] = {}
        # Mapping: base bar index → HTF bar index for each HTF
        self._htf_index_map: dict[str, list[int]] = {}

        # Metadata
        self._warm_up_bars: int = 0
        self._bar_count: int = 0

    @property
    def bar_count(self) -> int:
        return self._bar_count

    @property
    def warm_up_bars(self) -> int:
        return self._warm_up_bars

    def load_bars(self, bars: list) -> None:
        """Load bars from V1 Bar objects or raw dicts.

        Supports both V1 `Bar` dataclass and dict format.
        Timestamps are normalised to Unix-seconds (float).
        """
        import datetime as _dt

        def _to_unix(val) -> float:
            if isinstance(val, _dt.datetime):
                return val.timestamp()
            return float(val)

        for b in bars:
            if hasattr(b, "time"):
                # V1 Bar dataclass
                self.timestamps.append(_to_unix(b.time))
                self.opens.append(b.open)
                self.highs.append(b.high)
                self.lows.append(b.low)
                self.closes.append(b.close)
                self.volumes.append(getattr(b, "volume", 0.0))
            elif isinstance(b, dict):
                self.timestamps.append(_to_unix(b.get("time", 0.0)))
                self.opens.append(b.get("open", 0.0))
                self.highs.append(b.get("high", 0.0))
                self.lows.append(b.get("low", 0.0))
                self.closes.append(b.get("close", 0.0))
                self.volumes.append(b.get("volume", 0.0))
        self._bar_count = len(self.timestamps)

    def get_bar(self, index: int) -> BarData:
        """Get a BarData at a specific index with indicator values."""
        if index < 0 or index >= self._bar_count:
            raise IndexError(f"Bar index {index} out of range [0, {self._bar_count})")

        indicators = {}
        for ind_id, arr in self.indicator_arrays.items():
            if index < len(arr):
                val = arr[index]
                if not math.isnan(val):
                    indicators[ind_id] = val

        return BarData(
            timestamp_ns=timestamp_ns_from_unix(self.timestamps[index]),
            open=self.opens[index],
            high=self.highs[index],
            low=self.lows[index],
            close=self.closes[index],
            volume=self.volumes[index],
            bar_index=index,
            indicators=indicators,
        )

    def get_value(self, source: str, bar_index: int) -> float:
        """Get a value for a given source at a bar index.

        source can be:
         - "price.open", "price.high", "price.low", "price.close", "price.volume"
         - An indicator ID (e.g., "sma_20", "rsi_14")
         - A numeric literal (e.g., "50", "1.5")
        """
        if bar_index < 0 or bar_index >= self._bar_count:
            return float("nan")

        if source.startswith("price."):
            field_name = source.split(".")[1]
            arrays = {
                "open": self.opens, "high": self.highs,
                "low": self.lows, "close": self.closes,
                "volume": self.volumes,
            }
            arr = arrays.get(field_name)
            if arr and bar_index < len(arr):
                return arr[bar_index]
            return float("nan")

        if source in self.indicator_arrays:
            arr = self.indicator_arrays[source]
            if bar_index < len(arr):
                return arr[bar_index]
            return float("nan")

        # Try numeric literal
        try:
            return float(source)
        except (ValueError, TypeError):
            return float("nan")

    def compute_indicators(self, indicator_configs: list[dict]) -> None:
        """Pre-compute all indicators from strategy config.

        This mirrors V1's _compute_indicators() but is cleaner and
        also calculates the warm-up period.
        """
        source_map = {
            "open": self.opens,
            "high": self.highs,
            "low": self.lows,
            "close": self.closes,
            "volume": self.volumes,
        }

        max_warmup = 0

        for cfg in indicator_configs:
            ind_id = cfg["id"]
            ind_type = cfg["type"].upper()
            params = cfg.get("params", {})
            source = source_map.get(params.get("source", "close"), self.closes)
            period = int(params.get("period", 20))

            if ind_type == "SMA":
                self.indicator_arrays[ind_id] = ind.sma(source, period)
                max_warmup = max(max_warmup, period)

            elif ind_type == "EMA":
                self.indicator_arrays[ind_id] = ind.ema(source, period)
                max_warmup = max(max_warmup, period)

            elif ind_type == "RSI":
                p = int(params.get("period", 14))
                self.indicator_arrays[ind_id] = ind.rsi(source, p)
                max_warmup = max(max_warmup, p + 1)

            elif ind_type == "ATR":
                p = int(params.get("period", 14))
                self.indicator_arrays[ind_id] = ind.atr(
                    self.highs, self.lows, self.closes, p
                )
                max_warmup = max(max_warmup, p + 1)

            elif ind_type == "MACD":
                fast = int(params.get("fast", 12))
                slow = int(params.get("slow", 26))
                sig = int(params.get("signal", 9))
                ml, sl, hist = ind.macd(source, fast, slow, sig)
                self.indicator_arrays[ind_id] = ml
                self.indicator_arrays[f"{ind_id}_signal"] = sl
                self.indicator_arrays[f"{ind_id}_hist"] = hist
                max_warmup = max(max_warmup, slow + sig)

            elif ind_type == "BOLLINGER":
                std_dev = float(params.get("std_dev", 2.0))
                upper, middle, lower = ind.bollinger_bands(source, period, std_dev)
                self.indicator_arrays[f"{ind_id}_upper"] = upper
                self.indicator_arrays[ind_id] = middle
                self.indicator_arrays[f"{ind_id}_lower"] = lower
                max_warmup = max(max_warmup, period)

            elif ind_type == "STOCHASTIC":
                k_p = int(params.get("k_period", 14))
                d_p = int(params.get("d_period", 3))
                smooth = int(params.get("smooth", 3))
                k, d = ind.stochastic(
                    self.highs, self.lows, self.closes, k_p, d_p, smooth
                )
                self.indicator_arrays[ind_id] = k
                self.indicator_arrays[f"{ind_id}_d"] = d
                max_warmup = max(max_warmup, k_p + d_p + smooth)

            elif ind_type == "ADX":
                p = int(params.get("period", 14))
                self.indicator_arrays[ind_id] = ind.adx(
                    self.highs, self.lows, self.closes, p
                )
                max_warmup = max(max_warmup, p * 2 + 1)

            elif ind_type == "PIVOTHIGH":
                lb = int(params.get("lookback", 42))
                self.indicator_arrays[ind_id] = ind.pivot_high(self.highs, lb)
                max_warmup = max(max_warmup, lb * 2)

            elif ind_type == "PIVOTLOW":
                lb = int(params.get("lookback", 42))
                self.indicator_arrays[ind_id] = ind.pivot_low(self.lows, lb)
                max_warmup = max(max_warmup, lb * 2)

            elif ind_type == "ADR":
                p = int(params.get("period", 10))
                self.indicator_arrays[ind_id] = ind.adr(
                    self.highs, self.lows, p, self.timestamps
                )
                max_warmup = max(max_warmup, p * 10)  # ~10 bars per day

            elif ind_type == "VWAP":
                self.indicator_arrays[ind_id] = ind.vwap(
                    self.highs, self.lows, self.closes, self.volumes, self.timestamps
                )
                max_warmup = max(max_warmup, 1)

            elif ind_type in ("PIVOT", "PIVOT_POINTS"):
                pivots = ind.daily_pivot_points(
                    self.highs, self.lows, self.closes, self.timestamps
                )
                for key in ("pp", "r1", "r2", "r3", "s1", "s2", "s3"):
                    self.indicator_arrays[f"{ind_id}_{key}"] = pivots[key]
                self.indicator_arrays[ind_id] = pivots["pp"]
                max_warmup = max(max_warmup, 1)

            # ── Phase 2A: New Indicators ────────────────────────

            # Trend
            elif ind_type == "DEMA":
                self.indicator_arrays[ind_id] = ind.dema(source, period)
                max_warmup = max(max_warmup, period * 2)

            elif ind_type == "TEMA":
                self.indicator_arrays[ind_id] = ind.tema(source, period)
                max_warmup = max(max_warmup, period * 3)

            elif ind_type == "ZLEMA":
                self.indicator_arrays[ind_id] = ind.zlema(source, period)
                max_warmup = max(max_warmup, period)

            elif ind_type == "HULL_MA":
                self.indicator_arrays[ind_id] = ind.hull_ma(source, period)
                max_warmup = max(max_warmup, period + int(period ** 0.5))

            elif ind_type == "ICHIMOKU":
                tenkan_p = int(params.get("tenkan", 9))
                kijun_p = int(params.get("kijun", 26))
                senkou_b_p = int(params.get("senkou_b", 52))
                disp = int(params.get("displacement", 26))
                result = ind.ichimoku(
                    self.highs, self.lows, self.closes,
                    tenkan_p, kijun_p, senkou_b_p, disp,
                )
                self.indicator_arrays[ind_id] = result["tenkan"]
                self.indicator_arrays[f"{ind_id}_kijun"] = result["kijun"]
                self.indicator_arrays[f"{ind_id}_senkou_a"] = result["senkou_a"]
                self.indicator_arrays[f"{ind_id}_senkou_b"] = result["senkou_b"]
                self.indicator_arrays[f"{ind_id}_chikou"] = result["chikou"]
                max_warmup = max(max_warmup, senkou_b_p + disp)

            elif ind_type == "SUPERTREND":
                p = int(params.get("period", 10))
                mult = float(params.get("multiplier", 3.0))
                level, direction = ind.supertrend(
                    self.highs, self.lows, self.closes, p, mult
                )
                self.indicator_arrays[ind_id] = level
                self.indicator_arrays[f"{ind_id}_dir"] = direction
                max_warmup = max(max_warmup, p + 1)

            elif ind_type == "DONCHIAN":
                p = int(params.get("period", 20))
                upper, middle, lower = ind.donchian_channel(self.highs, self.lows, p)
                self.indicator_arrays[f"{ind_id}_upper"] = upper
                self.indicator_arrays[ind_id] = middle
                self.indicator_arrays[f"{ind_id}_lower"] = lower
                max_warmup = max(max_warmup, p)

            elif ind_type == "KELTNER":
                ema_p = int(params.get("ema_period", 20))
                atr_p = int(params.get("atr_period", 10))
                mult = float(params.get("multiplier", 2.0))
                upper, middle, lower = ind.keltner_channel(
                    self.highs, self.lows, self.closes, ema_p, atr_p, mult
                )
                self.indicator_arrays[f"{ind_id}_upper"] = upper
                self.indicator_arrays[ind_id] = middle
                self.indicator_arrays[f"{ind_id}_lower"] = lower
                max_warmup = max(max_warmup, max(ema_p, atr_p) + 1)

            elif ind_type == "PARABOLIC_SAR":
                af_start = float(params.get("af_start", 0.02))
                af_step = float(params.get("af_step", 0.02))
                af_max = float(params.get("af_max", 0.20))
                self.indicator_arrays[ind_id] = ind.parabolic_sar(
                    self.highs, self.lows, af_start, af_step, af_max
                )
                max_warmup = max(max_warmup, 2)

            # Oscillators
            elif ind_type == "CCI":
                p = int(params.get("period", 20))
                self.indicator_arrays[ind_id] = ind.cci(
                    self.highs, self.lows, self.closes, p
                )
                max_warmup = max(max_warmup, p)

            elif ind_type == "WILLIAMS_R":
                p = int(params.get("period", 14))
                self.indicator_arrays[ind_id] = ind.williams_r(
                    self.highs, self.lows, self.closes, p
                )
                max_warmup = max(max_warmup, p)

            elif ind_type == "MFI":
                p = int(params.get("period", 14))
                self.indicator_arrays[ind_id] = ind.mfi(
                    self.highs, self.lows, self.closes, self.volumes, p
                )
                max_warmup = max(max_warmup, p + 1)

            elif ind_type == "STOCHASTIC_RSI":
                rsi_p = int(params.get("rsi_period", 14))
                stoch_p = int(params.get("stoch_period", 14))
                k_sm = int(params.get("k_smooth", 3))
                d_sm = int(params.get("d_smooth", 3))
                k, d = ind.stochastic_rsi(source, rsi_p, stoch_p, k_sm, d_sm)
                self.indicator_arrays[ind_id] = k
                self.indicator_arrays[f"{ind_id}_d"] = d
                max_warmup = max(max_warmup, rsi_p + stoch_p + k_sm + d_sm)

            elif ind_type == "ROC":
                p = int(params.get("period", 14))
                self.indicator_arrays[ind_id] = ind.roc(source, p)
                max_warmup = max(max_warmup, p)

            elif ind_type == "AWESOME_OSCILLATOR":
                fast = int(params.get("fast", 5))
                slow = int(params.get("slow", 34))
                self.indicator_arrays[ind_id] = ind.awesome_oscillator(
                    self.highs, self.lows, fast, slow
                )
                max_warmup = max(max_warmup, slow)

            # Volume
            elif ind_type == "OBV":
                self.indicator_arrays[ind_id] = ind.obv(self.closes, self.volumes)
                max_warmup = max(max_warmup, 1)

            elif ind_type == "VWAP_BANDS":
                ns = float(params.get("num_std", 2.0))
                upper, vwap_l, lower = ind.vwap_bands(
                    self.highs, self.lows, self.closes, self.volumes,
                    self.timestamps, ns,
                )
                self.indicator_arrays[f"{ind_id}_upper"] = upper
                self.indicator_arrays[ind_id] = vwap_l
                self.indicator_arrays[f"{ind_id}_lower"] = lower
                max_warmup = max(max_warmup, 1)

            elif ind_type == "AD_LINE":
                self.indicator_arrays[ind_id] = ind.ad_line(
                    self.highs, self.lows, self.closes, self.volumes
                )
                max_warmup = max(max_warmup, 1)

            elif ind_type == "CMF":
                p = int(params.get("period", 20))
                self.indicator_arrays[ind_id] = ind.cmf(
                    self.highs, self.lows, self.closes, self.volumes, p
                )
                max_warmup = max(max_warmup, p)

            # Volatility
            elif ind_type == "ATR_BANDS":
                atr_p = int(params.get("atr_period", 14))
                mult = float(params.get("multiplier", 2.0))
                basis = params.get("basis", "ema")
                basis_p = int(params.get("basis_period", 20))
                upper, middle, lower = ind.atr_bands(
                    self.highs, self.lows, self.closes, atr_p, mult, basis, basis_p
                )
                self.indicator_arrays[f"{ind_id}_upper"] = upper
                self.indicator_arrays[ind_id] = middle
                self.indicator_arrays[f"{ind_id}_lower"] = lower
                max_warmup = max(max_warmup, max(atr_p, basis_p) + 1)

            elif ind_type == "HISTORICAL_VOLATILITY":
                p = int(params.get("period", 20))
                ann = float(params.get("annualize", 252.0))
                self.indicator_arrays[ind_id] = ind.historical_volatility(
                    self.closes, p, ann
                )
                max_warmup = max(max_warmup, p + 1)

            elif ind_type == "STDDEV_CHANNEL":
                p = int(params.get("period", 20))
                ns = float(params.get("num_std", 2.0))
                upper, middle, lower = ind.stddev_channel(self.closes, p, ns)
                self.indicator_arrays[f"{ind_id}_upper"] = upper
                self.indicator_arrays[ind_id] = middle
                self.indicator_arrays[f"{ind_id}_lower"] = lower
                max_warmup = max(max_warmup, p)

            # Smart Money / ICT
            elif ind_type == "FAIR_VALUE_GAPS":
                bull, bear = ind.fair_value_gaps(
                    self.highs, self.lows, self.closes, self.opens
                )
                self.indicator_arrays[f"{ind_id}_bull"] = bull
                self.indicator_arrays[f"{ind_id}_bear"] = bear
                self.indicator_arrays[ind_id] = bull  # default to bullish
                max_warmup = max(max_warmup, 3)

            elif ind_type == "ORDER_BLOCKS":
                lb = int(params.get("swing_lookback", 5))
                mult = float(params.get("impulse_mult", 2.0))
                bull, bear = ind.order_blocks(
                    self.highs, self.lows, self.closes, self.opens, lb, mult
                )
                self.indicator_arrays[f"{ind_id}_bull"] = bull
                self.indicator_arrays[f"{ind_id}_bear"] = bear
                self.indicator_arrays[ind_id] = bull
                max_warmup = max(max_warmup, lb + 2)

            elif ind_type == "LIQUIDITY_SWEEPS":
                lb = int(params.get("lookback", 20))
                hi, lo = ind.liquidity_sweeps(
                    self.highs, self.lows, self.closes, lb
                )
                self.indicator_arrays[f"{ind_id}_high"] = hi
                self.indicator_arrays[f"{ind_id}_low"] = lo
                self.indicator_arrays[ind_id] = hi
                max_warmup = max(max_warmup, lb + 1)

            # Session / Time
            elif ind_type == "SESSION_HL":
                s_start = int(params.get("session_start", 8))
                s_end = int(params.get("session_end", 17))
                hi, lo = ind.session_high_low(
                    self.highs, self.lows, self.timestamps, s_start, s_end
                )
                self.indicator_arrays[f"{ind_id}_high"] = hi
                self.indicator_arrays[f"{ind_id}_low"] = lo
                self.indicator_arrays[ind_id] = hi
                max_warmup = max(max_warmup, 1)

            elif ind_type == "PREV_DAY_LEVELS":
                levels = ind.previous_day_levels(
                    self.highs, self.lows, self.closes, self.timestamps
                )
                self.indicator_arrays[f"{ind_id}_pdh"] = levels["pdh"]
                self.indicator_arrays[f"{ind_id}_pdl"] = levels["pdl"]
                self.indicator_arrays[f"{ind_id}_pdc"] = levels["pdc"]
                self.indicator_arrays[ind_id] = levels["pdh"]
                max_warmup = max(max_warmup, 1)

            elif ind_type == "WEEKLY_OPEN":
                self.indicator_arrays[ind_id] = ind.weekly_open(
                    self.opens, self.timestamps
                )
                max_warmup = max(max_warmup, 1)

            elif ind_type == "KILL_ZONES":
                lk_start = int(params.get("london_start", 2))
                lk_end = int(params.get("london_end", 5))
                ny_start = int(params.get("ny_start", 7))
                ny_end = int(params.get("ny_end", 10))
                lk, ny = ind.kill_zones(
                    self.timestamps, lk_start, lk_end, ny_start, ny_end
                )
                self.indicator_arrays[f"{ind_id}_london"] = lk
                self.indicator_arrays[f"{ind_id}_ny"] = ny
                self.indicator_arrays[ind_id] = lk
                max_warmup = max(max_warmup, 1)

            # ── Candlestick Patterns (Phase 3C) ──────────────────
            elif ind_type == "CANDLE_PATTERN":
                pattern_name = params.get("pattern", "engulfing")
                extra = {k: v for k, v in params.items() if k != "pattern"}
                signal = pat.detect_pattern(
                    pattern_name,
                    self.opens, self.highs, self.lows, self.closes,
                    **extra,
                )
                self.indicator_arrays[ind_id] = signal
                max_warmup = max(max_warmup, 3)  # 3-bar patterns need 3 bars

        self._warm_up_bars = max_warmup

    # ── Multi-Timeframe Resampling (Phase 1E) ───────────────────

    def resample_to_htf(
        self,
        target_tf_label: str,
        indicator_configs: list[dict] | None = None,
    ) -> "SymbolData":
        """Resample this bar series to a higher timeframe.

        Creates a new ``SymbolData`` representing the higher-TF bars and
        stores it in ``self.htf_data[target_tf_label]``.  Also builds an
        index map so that ``htf_bar_for(base_bar_index)`` is O(1).

        Parameters
        ----------
        target_tf_label : str
            E.g. "H1", "H4", "D1".
        indicator_configs : list[dict] | None
            Indicator definitions to compute on the resampled data.

        Returns
        -------
        The newly created SymbolData for the higher timeframe.
        """
        target_s = parse_timeframe(target_tf_label)
        if self.timeframe_s and target_s <= self.timeframe_s:
            raise ValueError(
                f"Target timeframe {target_tf_label} ({target_s}s) must be "
                f"larger than base ({self.timeframe_s}s)"
            )
        if self._bar_count == 0:
            raise ValueError("No bars to resample")

        # ── Aggregate bars ──────────────────────────────────────
        htf_ts: list[float] = []
        htf_o: list[float] = []
        htf_h: list[float] = []
        htf_l: list[float] = []
        htf_c: list[float] = []
        htf_v: list[float] = []
        # Map base bar index → HTF bar index
        idx_map: list[int] = []

        bucket_start: float = -1.0
        bucket_o = bucket_h = bucket_l = bucket_c = bucket_v = 0.0
        htf_idx = -1

        for i in range(self._bar_count):
            ts = self.timestamps[i]
            # Determine which target bucket this bar belongs to
            bucket_key = (ts // target_s) * target_s

            if bucket_key != bucket_start:
                # Close previous bucket
                if bucket_start >= 0:
                    htf_ts.append(bucket_start)
                    htf_o.append(bucket_o)
                    htf_h.append(bucket_h)
                    htf_l.append(bucket_l)
                    htf_c.append(bucket_c)
                    htf_v.append(bucket_v)

                # Start new bucket
                bucket_start = bucket_key
                bucket_o = self.opens[i]
                bucket_h = self.highs[i]
                bucket_l = self.lows[i]
                bucket_c = self.closes[i]
                bucket_v = self.volumes[i]
                htf_idx += 1
            else:
                # Accumulate into current bucket
                bucket_h = max(bucket_h, self.highs[i])
                bucket_l = min(bucket_l, self.lows[i])
                bucket_c = self.closes[i]
                bucket_v += self.volumes[i]

            idx_map.append(htf_idx)

        # Flush last bucket
        if bucket_start >= 0:
            htf_ts.append(bucket_start)
            htf_o.append(bucket_o)
            htf_h.append(bucket_h)
            htf_l.append(bucket_l)
            htf_c.append(bucket_c)
            htf_v.append(bucket_v)

        # Build SymbolData for HTF
        htf_sd = SymbolData(
            symbol=self.symbol,
            point_value=self.point_value,
            timeframe_s=target_s,
        )
        htf_sd.timestamps = htf_ts
        htf_sd.opens = htf_o
        htf_sd.highs = htf_h
        htf_sd.lows = htf_l
        htf_sd.closes = htf_c
        htf_sd.volumes = htf_v
        htf_sd._bar_count = len(htf_ts)

        if indicator_configs:
            htf_sd.compute_indicators(indicator_configs)

        self.htf_data[target_tf_label.upper()] = htf_sd
        self._htf_index_map[target_tf_label.upper()] = idx_map

        return htf_sd

    def htf_bar_index_for(self, base_bar_index: int, tf_label: str) -> int:
        """Given a base-TF bar index, return the corresponding HTF bar index.

        Returns -1 if out of range or the timeframe isn't registered.
        The returned index points to the *completed* HTF bar (the one whose
        close is already known), which lags the current base bar by up to
        one HTF period.  This prevents look-ahead bias.
        """
        idx_map = self._htf_index_map.get(tf_label.upper())
        if idx_map is None or base_bar_index < 0 or base_bar_index >= len(idx_map):
            return -1
        htf_idx = idx_map[base_bar_index]
        # Prevent look-ahead: use the *previous* HTF bar unless we're exactly
        # at the first bar of a new HTF bucket.
        if htf_idx > 0:
            # If this base bar is in the same bucket as the next, the bucket
            # is still forming → use previous completed bar.
            if base_bar_index + 1 < len(idx_map) and idx_map[base_bar_index + 1] == htf_idx:
                return htf_idx - 1
            # Last bar in bucket (or beyond) → the bucket just closed
            return htf_idx
        return -1  # First HTF bar is still forming


# ── Tick Data (Phase 1E) ───────────────────────────────────────────


@dataclass(slots=True)
class TickData:
    """A single tick record (bid/ask or last trade)."""
    timestamp: float = 0.0  # Unix seconds
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    volume: float = 0.0


class TickStore:
    """Stores tick data for a single symbol.

    Used when real tick data is available (instead of synthetic ticks
    generated from OHLC bars).
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.timestamps: list[float] = []
        self.bids: list[float] = []
        self.asks: list[float] = []
        self.lasts: list[float] = []
        self.volumes: list[float] = []
        self._count: int = 0

    @property
    def tick_count(self) -> int:
        return self._count

    def load_ticks(self, ticks: list) -> None:
        """Load ticks from TickData objects, dicts, or tuples.

        Dict keys: timestamp, bid, ask, last, volume
        Tuple: (timestamp, bid, ask, last, volume) or (timestamp, bid, ask)
        """
        for t in ticks:
            if isinstance(t, TickData):
                self.timestamps.append(t.timestamp)
                self.bids.append(t.bid)
                self.asks.append(t.ask)
                self.lasts.append(t.last)
                self.volumes.append(t.volume)
            elif isinstance(t, dict):
                self.timestamps.append(t.get("timestamp", 0.0))
                self.bids.append(t.get("bid", 0.0))
                self.asks.append(t.get("ask", 0.0))
                self.lasts.append(t.get("last", 0.0))
                self.volumes.append(t.get("volume", 0.0))
            elif isinstance(t, (list, tuple)):
                self.timestamps.append(t[0] if len(t) > 0 else 0.0)
                self.bids.append(t[1] if len(t) > 1 else 0.0)
                self.asks.append(t[2] if len(t) > 2 else 0.0)
                self.lasts.append(t[3] if len(t) > 3 else 0.0)
                self.volumes.append(t[4] if len(t) > 4 else 0.0)
        self._count = len(self.timestamps)


# ── DataHandler ─────────────────────────────────────────────────────


class DataHandler:
    """
    Feeds market data events into the EventQueue.

    Supports single or multi-symbol backtesting.
    Handles indicator pre-computation and warm-up period enforcement.

    Phase 1E additions:
      - Multi-timeframe resampling (add_htf)
      - HTF value/bar access
      - Tick data storage & feeding
    """

    def __init__(self):
        self._symbols: dict[str, SymbolData] = {}
        self._tick_stores: dict[str, TickStore] = {}  # Phase 1E
        self._global_warm_up: int = 0

    def add_symbol(
        self,
        symbol: str,
        bars: list,
        indicator_configs: list[dict] | None = None,
        point_value: float = 1.0,
        timeframe_label: str = "",
    ) -> SymbolData:
        """Register a symbol's data and compute its indicators.

        Args:
            symbol: Symbol name (e.g., "XAUUSD")
            bars: List of V1 Bar objects or dicts
            indicator_configs: Indicator definitions from strategy config
            point_value: Point value for PnL calculation
            timeframe_label: E.g. "M5", "H1" (auto-detected if empty)

        Returns:
            The SymbolData object for further reference.
        """
        tf_s = parse_timeframe(timeframe_label) if timeframe_label else 0
        sd = SymbolData(symbol=symbol, point_value=point_value, timeframe_s=tf_s)
        sd.load_bars(bars)

        # Auto-detect timeframe if not provided
        if sd.timeframe_s == 0 and sd.bar_count >= 2:
            sd.timeframe_s = detect_timeframe(sd.timestamps)

        if indicator_configs:
            sd.compute_indicators(indicator_configs)

        self._symbols[symbol] = sd
        self._global_warm_up = max(self._global_warm_up, sd.warm_up_bars)
        return sd

    # ── Multi-Timeframe (Phase 1E) ─────────────────────────────────

    def add_htf(
        self,
        symbol: str,
        tf_label: str,
        indicator_configs: list[dict] | None = None,
    ) -> SymbolData:
        """Create a higher-timeframe bar series for *symbol* by resampling.

        The resampled data is stored inside the SymbolData for that symbol
        and is accessible via ``get_htf_value`` / ``get_htf_bar``.

        Parameters
        ----------
        symbol : str
            Must already be registered via ``add_symbol``.
        tf_label : str
            Target timeframe label, e.g. "H1", "H4", "D1".
        indicator_configs : list[dict] | None
            Indicators to compute on the resampled data.
        """
        sd = self._symbols.get(symbol)
        if sd is None:
            raise ValueError(f"Symbol {symbol} not registered; call add_symbol first")
        return sd.resample_to_htf(tf_label, indicator_configs)

    def get_htf_value(
        self,
        symbol: str,
        tf_label: str,
        source: str,
        base_bar_index: int,
    ) -> Optional[float]:
        """Get a HTF value aligned to a base-TF bar index (no look-ahead).

        Parameters
        ----------
        symbol : str
        tf_label : str
            E.g. "H1", "D1".
        source : str
            E.g. "price.close", "sma_20", indicator ID.
        base_bar_index : int
            The current base-timeframe bar index.
        """
        sd = self._symbols.get(symbol)
        if sd is None:
            return None
        htf_sd = sd.htf_data.get(tf_label.upper())
        if htf_sd is None:
            return None
        htf_idx = sd.htf_bar_index_for(base_bar_index, tf_label)
        if htf_idx < 0:
            return None
        return htf_sd.get_value(source, htf_idx)

    def get_htf_bar(
        self,
        symbol: str,
        tf_label: str,
        base_bar_index: int,
    ) -> Optional[BarData]:
        """Get a complete HTF BarData aligned to a base-TF bar index."""
        sd = self._symbols.get(symbol)
        if sd is None:
            return None
        htf_sd = sd.htf_data.get(tf_label.upper())
        if htf_sd is None:
            return None
        htf_idx = sd.htf_bar_index_for(base_bar_index, tf_label)
        if htf_idx < 0 or htf_idx >= htf_sd.bar_count:
            return None
        return htf_sd.get_bar(htf_idx)

    # ── Tick Data (Phase 1E) ───────────────────────────────────────

    def add_ticks(self, symbol: str, ticks: list) -> TickStore:
        """Register tick data for a symbol.

        Parameters
        ----------
        symbol : str
        ticks : list
            List of TickData, dicts, or tuples.
        """
        store = TickStore(symbol=symbol)
        store.load_ticks(ticks)
        self._tick_stores[symbol] = store
        return store

    def feed_ticks(self, queue: EventQueue) -> int:
        """Generate TickEvents for all symbols and push into the queue.

        Returns total number of tick events pushed.
        """
        total = 0
        for symbol, store in self._tick_stores.items():
            for i in range(store.tick_count):
                ts_ns = timestamp_ns_from_unix(store.timestamps[i])
                event = TickEvent(
                    timestamp_ns=ts_ns,
                    event_type=EventType.TICK,
                    symbol=symbol,
                    bid=store.bids[i],
                    ask=store.asks[i],
                    last=store.lasts[i],
                    volume=store.volumes[i],
                    tick_index=i,
                )
                queue.push(event)
                total += 1
        return total

    def get_tick_store(self, symbol: str) -> Optional[TickStore]:
        """Get the TickStore for a symbol."""
        return self._tick_stores.get(symbol)

    def get_symbol_data(self, symbol: str) -> Optional[SymbolData]:
        """Get SymbolData for a symbol."""
        return self._symbols.get(symbol)

    @property
    def symbols(self) -> list[str]:
        """List of registered symbols."""
        return list(self._symbols.keys())

    @property
    def warm_up_bars(self) -> int:
        """Global warm-up period (max across all symbols)."""
        return self._global_warm_up

    def feed_bars(self, queue: EventQueue) -> int:
        """Generate BarEvents for all symbols and push into the queue.

        For multi-symbol: bars are interleaved by timestamp so
        the queue processes them in chronological order.

        Returns total number of bar events pushed.
        """
        total = 0

        for symbol, sd in self._symbols.items():
            for i in range(sd.bar_count):
                ts_ns = timestamp_ns_from_unix(sd.timestamps[i])
                event = BarEvent(
                    timestamp_ns=ts_ns,
                    event_type=EventType.BAR,
                    symbol=symbol,
                    open=sd.opens[i],
                    high=sd.highs[i],
                    low=sd.lows[i],
                    close=sd.closes[i],
                    volume=sd.volumes[i],
                    bar_index=i,
                )
                queue.push(event)
                total += 1

        return total

    def total_bars(self, symbol: str = "") -> int:
        """Total bar count for a symbol (or max across all if not specified)."""
        if symbol:
            sd = self._symbols.get(symbol)
            return sd.bar_count if sd else 0
        return max((sd.bar_count for sd in self._symbols.values()), default=0)

    def last_prices(self, bar_index: int = -1) -> dict[str, float]:
        """Get the close price of each symbol at a given bar index.

        If bar_index is -1, returns the last bar's close for each symbol.
        """
        prices = {}
        for symbol, sd in self._symbols.items():
            idx = bar_index if bar_index >= 0 else sd.bar_count - 1
            if 0 <= idx < sd.bar_count:
                prices[symbol] = sd.closes[idx]
        return prices

    def get_value(self, symbol: str, source: str, bar_index: int) -> Optional[float]:
        """Proxy to SymbolData.get_value for a specific symbol."""
        sd = self._symbols.get(symbol)
        if sd is None:
            return None
        val = sd.get_value(source, bar_index)
        return val if val is not None else None

    def get_bar(self, symbol: str, bar_index: int):
        """Proxy to SymbolData.get_bar for a specific symbol."""
        sd = self._symbols.get(symbol)
        if sd is None:
            return None
        return sd.get_bar(bar_index)
