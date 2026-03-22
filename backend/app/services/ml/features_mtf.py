"""
Multi-Timeframe Feature Engine for Expert Agent.

Computes features from multiple timeframes (M5, H1, H4) and combines
them into a single feature vector. This mimics how expert traders check
higher timeframes for trend direction before entering on lower timeframes.

Also includes session awareness (Asian/London/NY/Dead zone) and
kill zone detection.
"""

import math
import numpy as np
from datetime import datetime, timezone
from typing import Optional

from app.services.ml.features import (
    compute_features,
    _safe_div,
    _rolling_mean,
    _rolling_std,
    _to_np,
)
from app.services.ml.market_structure import compute_market_structure_features
from app.services.backtest import indicators as ind


# ── Session Definitions (UTC) ─────────────────────────

SESSIONS = {
    "asian":        (0, 8),     # 00:00 - 08:00 UTC (Tokyo/Sydney)
    "london":       (8, 13),    # 08:00 - 13:00 UTC (London session)
    "new_york":     (13, 21),   # 13:00 - 21:00 UTC (NY session)
    "dead_zone":    (21, 24),   # 21:00 - 00:00 UTC (low liquidity)
}

KILL_ZONES = {
    "london_open":  (7, 9),     # 07:00 - 09:00 UTC — highest GBP/EUR vol
    "ny_open":      (12, 15),   # 12:00 - 15:00 UTC — highest US vol
    "london_close": (15, 17),   # 15:00 - 17:00 UTC — fakeout risk
}


# ── Session Feature Computation ───────────────────────

def compute_session_features(
    timestamps: list[datetime | None] | None,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    opens: np.ndarray,
) -> dict[str, np.ndarray]:
    """
    Compute session-aware features.

    Returns:
        session_asian/london/ny/dead: one-hot session encoding
        kill_zone_london_open/ny_open/london_close: kill zone flags
        session_range_pct: % of session range consumed so far
        session_open_dist: normalized distance from session open price
    """
    n = len(closes)
    features: dict[str, np.ndarray] = {}

    if timestamps is None or all(t is None for t in timestamps):
        # Return zeros if no timestamps
        for name in ["session_asian", "session_london", "session_ny", "session_dead",
                      "kill_zone_london_open", "kill_zone_ny_open", "kill_zone_london_close",
                      "session_range_pct", "session_open_dist"]:
            features[name] = np.zeros(n)
        return features

    # Session one-hot encoding
    sess_asian = np.zeros(n)
    sess_london = np.zeros(n)
    sess_ny = np.zeros(n)
    sess_dead = np.zeros(n)

    # Kill zone flags
    kz_london = np.zeros(n)
    kz_ny = np.zeros(n)
    kz_lc = np.zeros(n)

    # Session-relative metrics
    session_range_pct = np.zeros(n)
    session_open_dist = np.zeros(n)

    # Track session state
    current_session = None
    session_open_price = 0.0
    session_high = 0.0
    session_low = float("inf")

    for i, ts in enumerate(timestamps):
        if ts is None:
            continue

        hour = ts.hour

        # Determine session
        if 0 <= hour < 8:
            sess_asian[i] = 1.0
            new_session = "asian"
        elif 8 <= hour < 13:
            sess_london[i] = 1.0
            new_session = "london"
        elif 13 <= hour < 21:
            sess_ny[i] = 1.0
            new_session = "ny"
        else:
            sess_dead[i] = 1.0
            new_session = "dead"

        # Kill zones
        if 7 <= hour < 9:
            kz_london[i] = 1.0
        if 12 <= hour < 15:
            kz_ny[i] = 1.0
        if 15 <= hour < 17:
            kz_lc[i] = 1.0

        # Track session metrics
        if new_session != current_session:
            current_session = new_session
            session_open_price = opens[i]
            session_high = highs[i]
            session_low = lows[i]
        else:
            session_high = max(session_high, highs[i])
            session_low = min(session_low, lows[i])

        # Session range consumed
        total_range = session_high - session_low
        if total_range > 0 and session_open_price > 0:
            session_range_pct[i] = abs(closes[i] - session_open_price) / total_range
            session_range_pct[i] = min(session_range_pct[i], 2.0)  # cap at 2x

        # Distance from session open (normalized by price)
        if session_open_price > 0:
            session_open_dist[i] = (closes[i] - session_open_price) / session_open_price

    features["session_asian"] = sess_asian
    features["session_london"] = sess_london
    features["session_ny"] = sess_ny
    features["session_dead"] = sess_dead
    features["kill_zone_london_open"] = kz_london
    features["kill_zone_ny_open"] = kz_ny
    features["kill_zone_london_close"] = kz_lc
    features["session_range_pct"] = session_range_pct
    features["session_open_dist"] = session_open_dist

    return features


# ── Higher Timeframe Feature Aggregation ──────────────

def compute_htf_features(
    htf_bars: list[dict],
    prefix: str,
    closes_m5: np.ndarray,
) -> dict[str, np.ndarray]:
    """
    Compute features from a higher timeframe (H1 or H4) and map them
    to the M5 bar array length.

    The HTF features are "stepped" — they hold their value until the
    next HTF bar closes, just like a real trader would see them.

    Args:
        htf_bars: list of OHLCV dicts for the higher timeframe
        prefix: "h1" or "h4" to namespace the features
        closes_m5: M5 close array (for alignment and length)

    Returns:
        Dict of feature arrays, all length = len(closes_m5)
    """
    n = len(closes_m5)
    features: dict[str, np.ndarray] = {}

    if not htf_bars or len(htf_bars) < 50:
        # Return NaN arrays if insufficient HTF data
        for name in [
            f"{prefix}_trend_ema20", f"{prefix}_trend_ema50",
            f"{prefix}_trend_slope", f"{prefix}_rsi_14",
            f"{prefix}_adx_14", f"{prefix}_atr_norm",
            f"{prefix}_bb_position", f"{prefix}_macd_hist",
            f"{prefix}_structure_dir",
        ]:
            features[name] = np.full(n, np.nan)
        return features

    # Extract HTF OHLCV
    htf_o = np.array([b["open"] for b in htf_bars], dtype=np.float64)
    htf_h = np.array([b["high"] for b in htf_bars], dtype=np.float64)
    htf_l = np.array([b["low"] for b in htf_bars], dtype=np.float64)
    htf_c = np.array([b["close"] for b in htf_bars], dtype=np.float64)
    htf_n = len(htf_c)

    # Compute HTF indicators
    htf_closes = htf_c.tolist()
    htf_highs = htf_h.tolist()
    htf_lows = htf_l.tolist()

    # EMA distances (trend direction)
    ema20 = _to_np(ind.ema(htf_closes, 20))
    ema50 = _to_np(ind.ema(htf_closes, 50))
    ema20_dist = np.full(htf_n, np.nan)
    ema50_dist = np.full(htf_n, np.nan)
    m20 = ~np.isnan(ema20) & (ema20 > 0)
    m50 = ~np.isnan(ema50) & (ema50 > 0)
    ema20_dist[m20] = (htf_c[m20] - ema20[m20]) / ema20[m20]
    ema50_dist[m50] = (htf_c[m50] - ema50[m50]) / ema50[m50]

    # EMA slope (trend strength): change in EMA over 3 bars
    ema20_slope = np.full(htf_n, np.nan)
    for i in range(3, htf_n):
        if not np.isnan(ema20[i]) and not np.isnan(ema20[i - 3]) and ema20[i - 3] > 0:
            ema20_slope[i] = (ema20[i] - ema20[i - 3]) / ema20[i - 3]

    # RSI
    rsi_raw = _to_np(ind.rsi(htf_closes, 14))
    htf_rsi = np.full(htf_n, np.nan)
    mask_r = ~np.isnan(rsi_raw)
    htf_rsi[mask_r] = (rsi_raw[mask_r] - 50.0) / 50.0

    # ADX
    adx_raw = _to_np(ind.adx(htf_highs, htf_lows, htf_closes, 14))
    htf_adx = np.full(htf_n, np.nan)
    mask_a = ~np.isnan(adx_raw)
    htf_adx[mask_a] = adx_raw[mask_a] / 100.0

    # ATR normalized
    atr_raw = _to_np(ind.atr(htf_highs, htf_lows, htf_closes, 14))
    htf_atr = np.full(htf_n, np.nan)
    mask_at = ~np.isnan(atr_raw) & (htf_c > 0)
    htf_atr[mask_at] = atr_raw[mask_at] / htf_c[mask_at]

    # Bollinger position
    bb_u, bb_m, bb_l = ind.bollinger_bands(htf_closes)
    bb_u, bb_m, bb_l = _to_np(bb_u), _to_np(bb_m), _to_np(bb_l)
    htf_bb = np.full(htf_n, np.nan)
    mask_bb = ~np.isnan(bb_u) & ~np.isnan(bb_l)
    bw = bb_u - bb_l
    ok_bb = mask_bb & (bw > 0)
    htf_bb[ok_bb] = (htf_c[ok_bb] - bb_l[ok_bb]) / bw[ok_bb]

    # MACD histogram
    macd_line, _, macd_hist = ind.macd(htf_closes)
    htf_macd_h = _to_np(macd_hist)
    htf_macd_norm = np.full(htf_n, np.nan)
    mask_mh = ~np.isnan(htf_macd_h) & (htf_c > 0)
    htf_macd_norm[mask_mh] = htf_macd_h[mask_mh] / htf_c[mask_mh]

    # Market structure direction
    struct = compute_market_structure_features(htf_o, htf_h, htf_l, htf_c, lookback=3)
    htf_struct_dir = struct["structure_direction"]

    # Map HTF values to M5 resolution (forward-fill)
    # Each HTF bar covers multiple M5 bars. We use timestamps if available,
    # otherwise assume uniform distribution.
    htf_timestamps = [b.get("datetime") or b.get("timestamp") for b in htf_bars]
    m5_timestamps_available = False

    # Simple approach: distribute HTF bars evenly across M5 bars
    # ratio = n / htf_n gives approximate M5 bars per HTF bar
    ratio = max(1, n // max(htf_n, 1))

    def _map_to_m5(htf_arr: np.ndarray) -> np.ndarray:
        """Forward-fill HTF array to M5 length."""
        out = np.full(n, np.nan)
        for hi in range(htf_n):
            m5_start = hi * ratio
            m5_end = min((hi + 1) * ratio, n)
            if m5_start < n:
                out[m5_start:m5_end] = htf_arr[hi]
        # Fill any remaining M5 bars with last HTF value
        last_valid = htf_arr[~np.isnan(htf_arr)]
        if len(last_valid) > 0:
            last_val = last_valid[-1]
            remaining_start = htf_n * ratio
            if remaining_start < n:
                mask = np.isnan(out[remaining_start:])
                out[remaining_start:][mask] = last_val
        return out

    features[f"{prefix}_trend_ema20"] = _map_to_m5(ema20_dist)
    features[f"{prefix}_trend_ema50"] = _map_to_m5(ema50_dist)
    features[f"{prefix}_trend_slope"] = _map_to_m5(ema20_slope)
    features[f"{prefix}_rsi_14"] = _map_to_m5(htf_rsi)
    features[f"{prefix}_adx_14"] = _map_to_m5(htf_adx)
    features[f"{prefix}_atr_norm"] = _map_to_m5(htf_atr)
    features[f"{prefix}_bb_position"] = _map_to_m5(htf_bb)
    features[f"{prefix}_macd_hist"] = _map_to_m5(htf_macd_norm)
    features[f"{prefix}_structure_dir"] = _map_to_m5(htf_struct_dir)

    return features


# ── ADR (Average Daily Range) Features ────────────────

def compute_adr_features(
    daily_bars: list[dict],
    m5_highs: np.ndarray,
    m5_lows: np.ndarray,
    m5_closes: np.ndarray,
    adr_period: int = 10,
) -> dict[str, np.ndarray]:
    """
    Compute Average Daily Range features.

    Expert traders use ADR to gauge how much movement is "left" in the day.
    If price has already moved 90% of ADR, further moves are less likely.

    Returns:
        adr_consumed_pct: what % of ADR has been consumed today
        adr_remaining_normalized: normalized ADR remaining
    """
    n = len(m5_closes)
    adr_consumed = np.zeros(n)
    adr_remaining = np.zeros(n)

    if not daily_bars or len(daily_bars) < adr_period:
        return {
            "adr_consumed_pct": adr_consumed,
            "adr_remaining_norm": adr_remaining,
        }

    # Compute ADR from daily bars
    daily_ranges = [d["high"] - d["low"] for d in daily_bars]
    adr = np.mean(daily_ranges[-adr_period:])

    if adr <= 0:
        return {
            "adr_consumed_pct": adr_consumed,
            "adr_remaining_norm": adr_remaining,
        }

    # For each M5 bar, track the daily high/low
    # Simple: reset on significant time gap or use date if available
    day_high = m5_highs[0]
    day_low = m5_lows[0]
    prev_date = None

    for i in range(n):
        # Reset daily tracking (every ~288 M5 bars = 24h)
        if i > 0 and i % 288 == 0:
            day_high = m5_highs[i]
            day_low = m5_lows[i]

        day_high = max(day_high, m5_highs[i])
        day_low = min(day_low, m5_lows[i])

        consumed = day_high - day_low
        adr_consumed[i] = min(consumed / adr, 2.0)
        adr_remaining[i] = max(0, (adr - consumed) / adr)

    return {
        "adr_consumed_pct": adr_consumed,
        "adr_remaining_norm": adr_remaining,
    }


# ── Master Feature Builder ───────────────────────────

def compute_expert_features(
    m5_bars: list[dict],
    h1_bars: Optional[list[dict]] = None,
    h4_bars: Optional[list[dict]] = None,
    daily_bars: Optional[list[dict]] = None,
    feature_config: Optional[dict] = None,
) -> tuple[list[str], np.ndarray]:
    """
    Compute the complete expert feature set for M5 bars.

    Combines:
    1. Standard technical features (30+ from features.py)
    2. Market structure features (22 from market_structure.py)
    3. Session features (9 features)
    4. H1 context features (9 features)
    5. H4 context features (9 features)
    6. ADR features (2 features)

    Total: ~80+ features per M5 bar.

    Args:
        m5_bars: list of M5 OHLCV dicts
        h1_bars: optional H1 bars for higher-timeframe context
        h4_bars: optional H4 bars for higher-timeframe context
        daily_bars: optional daily bars for ADR computation
        feature_config: feature selection config

    Returns:
        (feature_names, feature_matrix) where feature_matrix is (n, n_features)
    """
    n = len(m5_bars)
    if n < 60:
        return [], np.array([])

    # Extract M5 OHLCV
    opens = [b["open"] for b in m5_bars]
    highs = [b["high"] for b in m5_bars]
    lows = [b["low"] for b in m5_bars]
    closes = [b["close"] for b in m5_bars]
    volumes = [b.get("volume", 0) for b in m5_bars]
    timestamps = [b.get("datetime") for b in m5_bars]
    if all(t is None for t in timestamps):
        timestamps = None

    o = np.array(opens, dtype=np.float64)
    h = np.array(highs, dtype=np.float64)
    l = np.array(lows, dtype=np.float64)
    c = np.array(closes, dtype=np.float64)

    # 1. Standard technical features (comprehensive set)
    config = feature_config or {}
    expert_features = config.get("features", [
        "returns", "returns_multi", "volatility", "candle_patterns",
        "sma", "ema", "rsi", "atr", "macd", "bollinger", "adx",
        "stochastic", "volume", "time", "regime", "momentum",
        "order_flow_imbalance", "microstructure",
    ])
    std_config = {"features": expert_features}

    std_names, std_matrix = compute_features(
        opens, highs, lows, closes, volumes, std_config,
        timestamps=timestamps,
    )

    if not std_names:
        return [], np.array([])

    std_mat = np.array(std_matrix, dtype=np.float64)

    # Collect all extra features
    extra_features: dict[str, np.ndarray] = {}

    # 2. Market structure features
    ms_features = compute_market_structure_features(o, h, l, c, swing_lookback=5)
    extra_features.update(ms_features)

    # 3. Session features
    sess_features = compute_session_features(timestamps, h, l, c, o)
    extra_features.update(sess_features)

    # 4. H1 context features
    if h1_bars and len(h1_bars) >= 50:
        h1_features = compute_htf_features(h1_bars, "h1", c)
        extra_features.update(h1_features)

    # 5. H4 context features
    if h4_bars and len(h4_bars) >= 50:
        h4_features = compute_htf_features(h4_bars, "h4", c)
        extra_features.update(h4_features)

    # 6. ADR features
    if daily_bars and len(daily_bars) >= 10:
        adr_features = compute_adr_features(daily_bars, h, l, c)
        extra_features.update(adr_features)

    # Combine all features into a single matrix
    extra_names = list(extra_features.keys())
    if extra_names:
        extra_mat = np.column_stack([extra_features[name] for name in extra_names])
        all_names = std_names + extra_names
        all_mat = np.column_stack([std_mat, extra_mat])
    else:
        all_names = std_names
        all_mat = std_mat

    return all_names, all_mat


# ── Feature name list for reference ───────────────────

EXPERT_FEATURE_GROUPS = {
    "standard_technical": [
        "returns", "returns_multi", "volatility", "candle_patterns",
        "sma", "ema", "rsi", "atr", "macd", "bollinger", "adx",
        "stochastic", "volume", "time", "regime", "momentum",
        "order_flow_imbalance", "microstructure",
    ],
    "market_structure": [
        "bos_bullish", "bos_bearish", "choch_bullish", "choch_bearish",
        "structure_direction", "swing_high_dist", "swing_low_dist",
        "ob_bullish_proximity", "ob_bearish_proximity",
        "ob_bullish_touch", "ob_bearish_touch",
        "fvg_bullish_proximity", "fvg_bearish_proximity",
        "fvg_bullish_active", "fvg_bearish_active",
        "liq_sweep_bullish", "liq_sweep_bearish", "liq_sweep_recency",
        "smc_bullish_confluence", "smc_bearish_confluence", "smc_net_bias",
    ],
    "session": [
        "session_asian", "session_london", "session_ny", "session_dead",
        "kill_zone_london_open", "kill_zone_ny_open", "kill_zone_london_close",
        "session_range_pct", "session_open_dist",
    ],
    "h1_context": [
        "h1_trend_ema20", "h1_trend_ema50", "h1_trend_slope",
        "h1_rsi_14", "h1_adx_14", "h1_atr_norm",
        "h1_bb_position", "h1_macd_hist", "h1_structure_dir",
    ],
    "h4_context": [
        "h4_trend_ema20", "h4_trend_ema50", "h4_trend_slope",
        "h4_rsi_14", "h4_adx_14", "h4_atr_norm",
        "h4_bb_position", "h4_macd_hist", "h4_structure_dir",
    ],
    "adr": ["adr_consumed_pct", "adr_remaining_norm"],
}
