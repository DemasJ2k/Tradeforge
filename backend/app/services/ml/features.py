"""
Feature engineering for ML models.

NumPy-vectorized computation of technical features from OHLCV data.
Feature groups: returns, volatility, candle_patterns, sma, ema, rsi, atr,
macd, bollinger, adx, stochastic, volume, time, regime, momentum.
"""

import math
import numpy as np
from typing import Optional
from datetime import datetime

from app.services.backtest import indicators as ind


# ── Vectorized helpers ─────────────────────────────────

def _safe_div(a: np.ndarray, b: np.ndarray, fill: float = 0.0) -> np.ndarray:
    """Element-wise division, returning fill where b == 0."""
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(b != 0, a / b, fill)
    return result


def _rolling_mean(arr: np.ndarray, window: int) -> np.ndarray:
    """Fast rolling mean via cumulative sum."""
    n = len(arr)
    result = np.full(n, np.nan)
    cs = np.cumsum(arr)
    result[window - 1] = cs[window - 1] / window
    result[window:] = (cs[window:] - cs[:-window]) / window
    return result


def _rolling_std(arr: np.ndarray, window: int) -> np.ndarray:
    """Fast rolling std via cumulative sums."""
    n = len(arr)
    result = np.full(n, np.nan)
    cs = np.cumsum(arr)
    cs2 = np.cumsum(arr ** 2)
    s = np.empty(n)
    s2 = np.empty(n)
    s[window - 1] = cs[window - 1]
    s2[window - 1] = cs2[window - 1]
    s[window:] = cs[window:] - cs[:-window]
    s2[window:] = cs2[window:] - cs2[:-window]
    mean = s / window
    var = s2 / window - mean ** 2
    var = np.maximum(var, 0)
    result[window - 1:] = np.sqrt(var[window - 1:])
    return result


def _to_np(vals: list) -> np.ndarray:
    """Convert indicator output list to numpy array."""
    return np.array(vals, dtype=np.float64)


# ── Feature group builders ────────────────────────────

def _feat_returns(c: np.ndarray) -> dict[str, np.ndarray]:
    """1-bar return."""
    r = np.empty_like(c)
    r[0] = 0.0
    r[1:] = _safe_div(c[1:] - c[:-1], c[:-1])
    return {"return_1": r}


def _feat_returns_multi(c: np.ndarray) -> dict[str, np.ndarray]:
    """Multi-bar returns."""
    out = {}
    for lag in (2, 3, 5, 10):
        r = np.zeros_like(c)
        r[lag:] = _safe_div(c[lag:] - c[:-lag], c[:-lag])
        out[f"return_{lag}"] = r
    return out


def _feat_volatility(c: np.ndarray) -> dict[str, np.ndarray]:
    """Rolling volatility of returns."""
    rets = np.empty_like(c)
    rets[0] = 0.0
    rets[1:] = _safe_div(c[1:] - c[:-1], c[:-1])
    out = {}
    for period in (5, 10, 20):
        out[f"volatility_{period}"] = _rolling_std(rets, period)
    return out


def _feat_candle_patterns(o: np.ndarray, h: np.ndarray,
                          l: np.ndarray, c: np.ndarray) -> dict[str, np.ndarray]:
    """Candle body ratio, wick ratios, range."""
    bar_range = h - l
    body = _safe_div(c - o, bar_range)
    upper = _safe_div(h - np.maximum(o, c), bar_range)
    lower = _safe_div(np.minimum(o, c) - l, bar_range)
    rr = _safe_div(bar_range, c)
    return {
        "candle_body": body,
        "candle_upper_wick": upper,
        "candle_lower_wick": lower,
        "candle_range_ratio": rr,
    }


def _feat_sma(c: np.ndarray, closes_list: list[float]) -> dict[str, np.ndarray]:
    """Normalized distance from SMA."""
    n = len(c)
    out = {}
    for period in (10, 20, 50):
        sma_vals = _to_np(ind.sma(closes_list, period))
        dist = np.full(n, np.nan)
        mask = ~np.isnan(sma_vals) & (sma_vals > 0)
        dist[mask] = (c[mask] - sma_vals[mask]) / sma_vals[mask]
        out[f"sma_{period}_dist"] = dist
    return out


def _feat_ema(c: np.ndarray, closes_list: list[float]) -> dict[str, np.ndarray]:
    """Normalized distance from EMA."""
    n = len(c)
    out = {}
    for period in (10, 20, 50):
        ema_vals = _to_np(ind.ema(closes_list, period))
        dist = np.full(n, np.nan)
        mask = ~np.isnan(ema_vals) & (ema_vals > 0)
        dist[mask] = (c[mask] - ema_vals[mask]) / ema_vals[mask]
        out[f"ema_{period}_dist"] = dist
    return out


def _feat_rsi(closes_list: list[float], n: int) -> dict[str, np.ndarray]:
    """RSI normalized to [-1, 1]."""
    out = {}
    for period in (7, 14, 21):
        rsi_vals = _to_np(ind.rsi(closes_list, period))
        norm = np.full(n, np.nan)
        mask = ~np.isnan(rsi_vals)
        norm[mask] = (rsi_vals[mask] - 50.0) / 50.0
        out[f"rsi_{period}"] = norm
    return out


def _feat_atr(highs_list: list[float], lows_list: list[float],
              closes_list: list[float], c: np.ndarray) -> dict[str, np.ndarray]:
    """ATR normalized by price."""
    n = len(c)
    out = {}
    for period in (7, 14):
        atr_vals = _to_np(ind.atr(highs_list, lows_list, closes_list, period))
        norm = np.full(n, np.nan)
        mask = ~np.isnan(atr_vals) & (c > 0)
        norm[mask] = atr_vals[mask] / c[mask]
        out[f"atr_{period}_norm"] = norm
    return out


def _feat_macd(closes_list: list[float], c: np.ndarray) -> dict[str, np.ndarray]:
    """MACD line and histogram normalized by price."""
    n = len(c)
    macd_line, _, histogram = ind.macd(closes_list)
    macd_arr = _to_np(macd_line)
    hist_arr = _to_np(histogram)

    nm = np.full(n, np.nan)
    nh = np.full(n, np.nan)
    mask_m = ~np.isnan(macd_arr) & (c > 0)
    mask_h = ~np.isnan(hist_arr) & (c > 0)
    nm[mask_m] = macd_arr[mask_m] / c[mask_m]
    nh[mask_h] = hist_arr[mask_h] / c[mask_h]
    return {"macd_norm": nm, "macd_hist_norm": nh}


def _feat_bollinger(closes_list: list[float], c: np.ndarray) -> dict[str, np.ndarray]:
    """Bollinger Band position and width."""
    n = len(c)
    upper, middle, lower = ind.bollinger_bands(closes_list)
    u, m, lo = _to_np(upper), _to_np(middle), _to_np(lower)

    bb_pos = np.full(n, np.nan)
    bb_width = np.full(n, np.nan)
    mask = ~np.isnan(u) & ~np.isnan(lo)
    bw = u - lo
    ok = mask & (bw > 0)
    bb_pos[ok] = (c[ok] - lo[ok]) / bw[ok]
    bb_width[ok] = np.where(m[ok] > 0, bw[ok] / m[ok], 0.0)
    return {"bb_position": bb_pos, "bb_width": bb_width}


def _feat_adx(highs_list: list[float], lows_list: list[float],
              closes_list: list[float], n: int) -> dict[str, np.ndarray]:
    """ADX normalized to [0, 1]."""
    adx_vals = _to_np(ind.adx(highs_list, lows_list, closes_list, 14))
    norm = np.full(n, np.nan)
    mask = ~np.isnan(adx_vals)
    norm[mask] = adx_vals[mask] / 100.0
    return {"adx_14": norm}


def _feat_stochastic(highs_list: list[float], lows_list: list[float],
                     closes_list: list[float], n: int) -> dict[str, np.ndarray]:
    """Stochastic %K and %D normalized to [-1, 1]."""
    k_line, d_line = ind.stochastic(highs_list, lows_list, closes_list)
    k_arr, d_arr = _to_np(k_line), _to_np(d_line)
    k_norm = np.full(n, np.nan)
    d_norm = np.full(n, np.nan)
    mk = ~np.isnan(k_arr)
    md = ~np.isnan(d_arr)
    k_norm[mk] = (k_arr[mk] - 50.0) / 50.0
    d_norm[md] = (d_arr[md] - 50.0) / 50.0
    return {"stoch_k": k_norm, "stoch_d": d_norm}


def _feat_volume(v: np.ndarray, volumes_list: list[float]) -> dict[str, np.ndarray]:
    """Volume ratio vs 20-bar SMA."""
    if not np.any(v > 0):
        return {}
    n = len(v)
    vsma = _to_np(ind.sma(volumes_list, 20))
    ratio = np.full(n, np.nan)
    mask = ~np.isnan(vsma) & (vsma > 0)
    ratio[mask] = v[mask] / vsma[mask]
    return {"volume_ratio_20": ratio}


def _feat_time(timestamps: list[datetime | None] | None, n: int) -> dict[str, np.ndarray]:
    """Cyclical time-of-day and day-of-week encoding (sin/cos)."""
    if timestamps is None or all(t is None for t in timestamps):
        return {}

    hour_sin = np.full(n, np.nan)
    hour_cos = np.full(n, np.nan)
    dow_sin = np.full(n, np.nan)
    dow_cos = np.full(n, np.nan)

    for i, ts in enumerate(timestamps):
        if ts is None:
            continue
        h = ts.hour + ts.minute / 60.0
        hour_sin[i] = math.sin(2.0 * math.pi * h / 24.0)
        hour_cos[i] = math.cos(2.0 * math.pi * h / 24.0)
        dow = ts.weekday()  # 0=Mon .. 4=Fri
        dow_sin[i] = math.sin(2.0 * math.pi * dow / 5.0)
        dow_cos[i] = math.cos(2.0 * math.pi * dow / 5.0)

    return {
        "time_hour_sin": hour_sin,
        "time_hour_cos": hour_cos,
        "time_dow_sin": dow_sin,
        "time_dow_cos": dow_cos,
    }


def _feat_regime(c: np.ndarray, highs_list: list[float],
                 lows_list: list[float], closes_list: list[float]) -> dict[str, np.ndarray]:
    """Market regime features: ATR ratio, return autocorrelation, vol clustering."""
    n = len(c)

    # ATR ratio (short / long): > 1 = expanding volatility, < 1 = contracting
    atr_7 = _to_np(ind.atr(highs_list, lows_list, closes_list, 7))
    atr_21 = _to_np(ind.atr(highs_list, lows_list, closes_list, 21))
    atr_ratio = np.full(n, np.nan)
    mask = ~np.isnan(atr_7) & ~np.isnan(atr_21) & (atr_21 > 0)
    atr_ratio[mask] = atr_7[mask] / atr_21[mask]

    # Return autocorrelation (20-bar rolling)
    rets = np.empty_like(c)
    rets[0] = 0.0
    rets[1:] = _safe_div(c[1:] - c[:-1], c[:-1])
    autocorr = np.full(n, np.nan)
    window = 20
    for i in range(window, n):
        w = rets[i - window + 1: i + 1]
        mean_w = np.mean(w)
        var_w = np.var(w)
        if var_w > 1e-12:
            # Lag-1 autocorrelation
            cov = np.mean((w[1:] - mean_w) * (w[:-1] - mean_w))
            autocorr[i] = cov / var_w

    # Volatility clustering: recent vol / older vol ratio
    vol_recent = _rolling_std(rets, 5)
    vol_older = _rolling_std(rets, 20)
    vol_cluster = np.full(n, np.nan)
    mask2 = ~np.isnan(vol_recent) & ~np.isnan(vol_older) & (vol_older > 1e-12)
    vol_cluster[mask2] = vol_recent[mask2] / vol_older[mask2]

    return {
        "regime_atr_ratio": atr_ratio,
        "regime_autocorr": autocorr,
        "regime_vol_cluster": vol_cluster,
    }


def _feat_fractal_dimension(c: np.ndarray) -> dict[str, np.ndarray]:
    """Higuchi fractal dimension — measures market complexity (1.0=smooth, 2.0=noisy)."""
    n = len(c)
    out = {}
    window = 50
    k_max = 8
    fd = np.full(n, np.nan)

    for i in range(window, n):
        x = c[i - window + 1: i + 1]
        L_k = np.zeros(k_max)
        for k in range(1, k_max + 1):
            n_k = (window - 1) // k
            if n_k < 1:
                break
            lengths = []
            for m in range(1, k + 1):
                idx = np.arange(0, n_k) * k + m - 1
                idx = idx[idx < window]
                if len(idx) < 2:
                    continue
                seg = x[idx]
                length = np.sum(np.abs(np.diff(seg))) * (window - 1) / (k * len(idx) * k)
                lengths.append(length)
            if lengths:
                L_k[k - 1] = np.mean(lengths)
        valid = L_k > 0
        if np.sum(valid) >= 3:
            log_k = np.log(np.arange(1, k_max + 1)[valid])
            log_L = np.log(L_k[valid])
            slope = np.polyfit(log_k, log_L, 1)[0]
            fd[i] = -slope

    out["fractal_dimension"] = fd
    return out


def _feat_hurst_exponent(c: np.ndarray) -> dict[str, np.ndarray]:
    """R/S analysis for Hurst exponent — trend persistence measure.

    H > 0.5: trending, H < 0.5: mean-reverting, H = 0.5: random walk.
    """
    n = len(c)
    window = 100
    hurst = np.full(n, np.nan)

    for i in range(window, n):
        x = c[i - window + 1: i + 1]
        returns = np.diff(np.log(np.maximum(x, 1e-12)))
        lags = [2, 4, 8, 16, 32]
        rs_values = []
        lag_values = []

        for lag in lags:
            if lag >= len(returns):
                break
            n_segments = len(returns) // lag
            if n_segments < 1:
                continue
            rs_list = []
            for seg_i in range(n_segments):
                seg = returns[seg_i * lag: (seg_i + 1) * lag]
                mean_seg = np.mean(seg)
                deviations = np.cumsum(seg - mean_seg)
                r = np.max(deviations) - np.min(deviations)
                s = np.std(seg, ddof=1) if np.std(seg) > 1e-12 else 1e-12
                rs_list.append(r / s)
            if rs_list:
                rs_values.append(np.log(np.mean(rs_list)))
                lag_values.append(np.log(lag))

        if len(rs_values) >= 3:
            hurst[i] = np.polyfit(lag_values, rs_values, 1)[0]

    return {"hurst_exponent": hurst}


def _feat_order_flow_imbalance(
    c: np.ndarray, v: np.ndarray
) -> dict[str, np.ndarray]:
    """Volume-weighted directional pressure."""
    n = len(c)
    out = {}

    # Direction: +1 if close > prev close, -1 otherwise
    direction = np.zeros(n)
    direction[1:] = np.sign(c[1:] - c[:-1])
    direction[direction == 0] = 1.0  # flat → treat as up

    # Directional volume
    dir_vol = direction * v

    # Rolling imbalance: sum(dir_vol) / sum(abs(vol)) over window
    for window in (10, 20):
        imb = np.full(n, np.nan)
        cum_dv = np.cumsum(dir_vol)
        cum_v = np.cumsum(v)
        for i in range(window, n):
            sv = cum_v[i] - cum_v[i - window]
            if sv > 0:
                imb[i] = (cum_dv[i] - cum_dv[i - window]) / sv
        out[f"order_flow_imbalance_{window}"] = imb

    # Buy pressure ratio: up-volume / total volume
    up_vol = np.where(direction > 0, v, 0.0)
    cum_up = np.cumsum(up_vol)
    buy_pressure = np.full(n, np.nan)
    for i in range(20, n):
        total = cum_v[i] - cum_v[i - 20]
        if total > 0:
            buy_pressure[i] = (cum_up[i] - cum_up[i - 20]) / total
    out["buy_pressure_ratio_20"] = buy_pressure

    return out


def _feat_microstructure(
    h: np.ndarray, l: np.ndarray, c: np.ndarray
) -> dict[str, np.ndarray]:
    """Parkinson & Garman-Klass volatility estimators."""
    n = len(c)
    out = {}

    # Parkinson volatility (uses high-low range)
    log_hl = np.log(np.maximum(h, 1e-12) / np.maximum(l, 1e-12))
    parkinson_sq = log_hl ** 2 / (4 * np.log(2))

    for window in (10, 20):
        park = np.full(n, np.nan)
        cs = np.cumsum(parkinson_sq)
        for i in range(window, n):
            park[i] = np.sqrt((cs[i] - cs[i - window]) / window)
        out[f"parkinson_vol_{window}"] = park

    # Garman-Klass volatility (uses OHLC)
    log_hl2 = 0.5 * log_hl ** 2
    log_co = np.zeros(n)
    log_co[1:] = np.log(np.maximum(c[1:], 1e-12) / np.maximum(c[:-1], 1e-12))
    gk_sq = log_hl2 - (2 * np.log(2) - 1) * log_co ** 2

    for window in (10, 20):
        gk = np.full(n, np.nan)
        cs = np.cumsum(gk_sq)
        for i in range(window, n):
            val = (cs[i] - cs[i - window]) / window
            gk[i] = np.sqrt(max(val, 0))
        out[f"garman_klass_vol_{window}"] = gk

    return out


def _feat_momentum(c: np.ndarray) -> dict[str, np.ndarray]:
    """Rate of change + price acceleration."""
    n = len(c)
    out = {}

    # Rate of change (ROC) = (price - price_n) / price_n
    for period in (5, 10, 20):
        roc = np.full(n, np.nan)
        roc[period:] = _safe_div(c[period:] - c[:-period], c[:-period])
        out[f"momentum_roc_{period}"] = roc

    # Price acceleration (2nd derivative): ROC of ROC
    rets = np.empty_like(c)
    rets[0] = 0.0
    rets[1:] = _safe_div(c[1:] - c[:-1], c[:-1])
    accel = np.full(n, np.nan)
    accel[2:] = rets[2:] - rets[1:-1]
    out["momentum_acceleration"] = accel

    return out


# ── Main compute function ────────────────────────────

def compute_features(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    feature_config: Optional[dict] = None,
    timestamps: list[datetime | None] | None = None,
) -> tuple[list[str], list[list[float]]]:
    """
    Compute ML features from OHLCV data (NumPy-vectorized).

    Args:
        opens, highs, lows, closes, volumes: OHLCV price data as lists
        feature_config: dict with "features" key listing selected groups
        timestamps: optional list of datetime objects for time features

    Returns:
        (feature_names, feature_matrix)
        feature_matrix[i] is the feature vector for bar i.
    """
    n = len(closes)
    if n < 50:
        return [], []

    config = feature_config or {}
    selected = config.get("features", _DEFAULT_FEATURES)

    # Convert to numpy arrays once
    o = np.array(opens, dtype=np.float64)
    h = np.array(highs, dtype=np.float64)
    l = np.array(lows, dtype=np.float64)
    c = np.array(closes, dtype=np.float64)
    v = np.array(volumes, dtype=np.float64)

    all_features: dict[str, np.ndarray] = {}

    # ── Price features ────────────────────
    if "returns" in selected:
        all_features.update(_feat_returns(c))
    if "returns_multi" in selected:
        all_features.update(_feat_returns_multi(c))
    if "volatility" in selected:
        all_features.update(_feat_volatility(c))
    if "candle_patterns" in selected:
        all_features.update(_feat_candle_patterns(o, h, l, c))

    # ── Indicator features ────────────────
    if "sma" in selected:
        all_features.update(_feat_sma(c, closes))
    if "ema" in selected:
        all_features.update(_feat_ema(c, closes))
    if "rsi" in selected:
        all_features.update(_feat_rsi(closes, n))
    if "atr" in selected:
        all_features.update(_feat_atr(highs, lows, closes, c))
    if "macd" in selected:
        all_features.update(_feat_macd(closes, c))
    if "bollinger" in selected:
        all_features.update(_feat_bollinger(closes, c))
    if "adx" in selected:
        all_features.update(_feat_adx(highs, lows, closes, n))
    if "stochastic" in selected:
        all_features.update(_feat_stochastic(highs, lows, closes, n))

    # ── Volume features ───────────────────
    if "volume" in selected:
        all_features.update(_feat_volume(v, volumes))

    # ── Time features (cyclical encoding) ─
    if "time" in selected:
        all_features.update(_feat_time(timestamps, n))

    # ── Regime features ───────────────────
    if "regime" in selected:
        all_features.update(_feat_regime(c, highs, lows, closes))

    # ── Momentum features ─────────────────
    if "momentum" in selected:
        all_features.update(_feat_momentum(c))

    # ── Advanced features ─────────────────
    if "fractal_dimension" in selected:
        all_features.update(_feat_fractal_dimension(c))
    if "hurst_exponent" in selected:
        all_features.update(_feat_hurst_exponent(c))
    if "order_flow_imbalance" in selected:
        all_features.update(_feat_order_flow_imbalance(c, v))
    if "microstructure" in selected:
        all_features.update(_feat_microstructure(h, l, c))

    # ── Build matrix ──────────────────────
    feature_names = list(all_features.keys())
    if not feature_names:
        return [], []

    # Stack columns into (n, n_features) matrix and convert to list-of-lists
    mat = np.column_stack([all_features[name] for name in feature_names])
    feature_matrix = mat.tolist()

    return feature_names, feature_matrix


# ── Target computation ────────────────────────────────

def compute_targets(
    closes: list[float],
    target_config: Optional[dict] = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> tuple[str, list[float]]:
    """
    Compute prediction targets from close prices.

    Supports: direction, return, volatility, triple_barrier.

    Returns:
        (target_name, target_values)
    """
    config = target_config or {}
    target_type = config.get("type", "direction")
    horizon = config.get("horizon", 1)

    c = np.array(closes, dtype=np.float64)
    n = len(c)

    if target_type == "direction":
        targets = np.full(n, np.nan)
        future = c[horizon:]
        current = c[:n - horizon]
        ret = _safe_div(future - current, current)
        targets[:n - horizon] = np.where(ret > 0, 1.0, 0.0)
        return f"direction_{horizon}bar", targets.tolist()

    elif target_type == "return":
        targets = np.full(n, np.nan)
        future = c[horizon:]
        current = c[:n - horizon]
        targets[:n - horizon] = _safe_div(future - current, current)
        return f"return_{horizon}bar", targets.tolist()

    elif target_type == "volatility":
        targets = np.full(n, np.nan)
        for i in range(n - horizon):
            window = c[i: i + horizon + 1]
            if len(window) > 1:
                rets = _safe_div(window[1:] - window[:-1], window[:-1])
                targets[i] = float(np.std(rets))
        return f"volatility_{horizon}bar", targets.tolist()

    elif target_type == "triple_barrier":
        return _compute_triple_barrier(c, highs, lows, config)

    else:
        # Default to direction
        targets = np.full(n, np.nan)
        future = c[horizon:]
        current = c[:n - horizon]
        targets[:n - horizon] = np.where(future > current, 1.0, 0.0)
        return "direction_1bar", targets.tolist()


def _compute_triple_barrier(
    c: np.ndarray,
    highs: list[float] | None,
    lows: list[float] | None,
    config: dict,
) -> tuple[str, list[float]]:
    """
    Triple barrier labeling: SL/TP based on ATR + time expiry.

    Labels: 1.0 = TP hit first, 0.0 = SL hit first, 0.5 = time expired (neutral).
    """
    n = len(c)
    sl_mult = config.get("sl_atr_mult", 1.5)
    tp_mult = config.get("tp_atr_mult", 2.0)
    max_bars = config.get("max_holding_bars", 10)

    # Need highs/lows for barrier checks
    if highs is None or lows is None:
        # Fallback to direction
        return compute_targets(c.tolist(), {"type": "direction", "horizon": 1})

    h = np.array(highs, dtype=np.float64)
    lo = np.array(lows, dtype=np.float64)

    # Compute ATR(14) for dynamic barrier sizes
    atr_vals = _to_np(ind.atr(list(h), list(lo), list(c), 14))

    targets = np.full(n, np.nan)
    for i in range(n - max_bars):
        if np.isnan(atr_vals[i]) or atr_vals[i] <= 0:
            continue

        entry = c[i]
        sl_dist = atr_vals[i] * sl_mult
        tp_dist = atr_vals[i] * tp_mult
        tp_price = entry + tp_dist
        sl_price = entry - sl_dist

        label = 0.5  # Default: time barrier hit
        for j in range(1, max_bars + 1):
            idx = i + j
            if idx >= n:
                break
            # Check if TP hit (high reached TP)
            if h[idx] >= tp_price:
                label = 1.0
                break
            # Check if SL hit (low reached SL)
            if lo[idx] <= sl_price:
                label = 0.0
                break

        targets[i] = label

    return f"triple_barrier_sl{sl_mult}_tp{tp_mult}", targets.tolist()


# ── Data cleaning ─────────────────────────────────────

def clean_data(
    feature_names: list[str],
    feature_matrix: list[list[float]],
    targets: list[float],
) -> tuple[list[str], list[list[float]], list[float]]:
    """Remove rows with NaN values in features or target (vectorized)."""
    X = np.array(feature_matrix, dtype=np.float64)
    y = np.array(targets, dtype=np.float64)

    # Mask: True where all features and target are finite (not NaN/inf)
    valid = np.isfinite(y)
    if X.ndim == 2:
        valid &= np.all(np.isfinite(X), axis=1)

    return feature_names, X[valid].tolist(), y[valid].tolist()


# ── Rolling Z-score normalization ─────────────────────

def apply_rolling_zscore(
    feature_matrix: list[list[float]],
    window: int = 50,
) -> list[list[float]]:
    """
    Apply rolling Z-score normalization to feature matrix.

    For each feature, normalizes using rolling mean/std over `window` bars.
    Preserves temporal structure (unlike global StandardScaler).
    Rows before the window are set to 0 (insufficient history).
    """
    X = np.array(feature_matrix, dtype=np.float64)
    n, d = X.shape
    result = np.zeros_like(X)

    for col in range(d):
        col_data = X[:, col]
        rmean = _rolling_mean(col_data, window)
        rstd = _rolling_std(col_data, window)
        mask = ~np.isnan(rmean) & ~np.isnan(rstd) & (rstd > 1e-12)
        result[mask, col] = (col_data[mask] - rmean[mask]) / rstd[mask]

    return result.tolist()


# ── Default feature set ───────────────────────────────

_DEFAULT_FEATURES = [
    "returns", "returns_multi", "volatility", "candle_patterns",
    "sma", "ema", "rsi", "atr", "macd", "bollinger", "adx",
    "stochastic", "volume",
]
