"""
Feature engineering for ML models.

Computes technical features from OHLCV data for use in
ML model training and prediction.
"""

import math
from typing import Optional

from app.services.backtest import indicators as ind


def compute_features(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    feature_config: Optional[dict] = None,
) -> tuple[list[str], list[list[float]]]:
    """
    Compute ML features from OHLCV data.

    Returns:
        (feature_names, feature_matrix)
        feature_matrix[i] is the feature vector for bar i.
        Rows with NaN features are excluded.
    """
    n = len(closes)
    if n < 50:
        return [], []

    config = feature_config or {}
    selected = config.get("features", _DEFAULT_FEATURES)

    all_features: dict[str, list[float]] = {}

    # ── Price-based features ──────────────────────
    if "returns" in selected:
        rets = [0.0] + [(closes[i] - closes[i - 1]) / closes[i - 1] if closes[i - 1] != 0 else 0 for i in range(1, n)]
        all_features["return_1"] = rets

    if "returns_multi" in selected:
        for lag in [2, 3, 5, 10]:
            r = [0.0] * n
            for i in range(lag, n):
                if closes[i - lag] != 0:
                    r[i] = (closes[i] - closes[i - lag]) / closes[i - lag]
            all_features[f"return_{lag}"] = r

    if "volatility" in selected:
        # Rolling std of returns
        rets = [0.0] + [(closes[i] - closes[i - 1]) / closes[i - 1] if closes[i - 1] != 0 else 0 for i in range(1, n)]
        for period in [5, 10, 20]:
            vol = [float("nan")] * n
            for i in range(period, n):
                window = rets[i - period + 1: i + 1]
                mean = sum(window) / period
                var = sum((x - mean) ** 2 for x in window) / period
                vol[i] = math.sqrt(var) if var >= 0 else 0
            all_features[f"volatility_{period}"] = vol

    if "candle_patterns" in selected:
        body = [0.0] * n
        upper_wick = [0.0] * n
        lower_wick = [0.0] * n
        range_ratio = [0.0] * n
        for i in range(n):
            bar_range = highs[i] - lows[i]
            if bar_range > 0:
                body[i] = (closes[i] - opens[i]) / bar_range
                upper_wick[i] = (highs[i] - max(opens[i], closes[i])) / bar_range
                lower_wick[i] = (min(opens[i], closes[i]) - lows[i]) / bar_range
            if closes[i] > 0:
                range_ratio[i] = bar_range / closes[i]
        all_features["candle_body"] = body
        all_features["candle_upper_wick"] = upper_wick
        all_features["candle_lower_wick"] = lower_wick
        all_features["candle_range_ratio"] = range_ratio

    # ── Indicator features ────────────────────────
    if "sma" in selected:
        for period in [10, 20, 50]:
            sma_vals = ind.sma(closes, period)
            # Normalized distance from price
            dist = [float("nan")] * n
            for i in range(n):
                if not math.isnan(sma_vals[i]) and sma_vals[i] > 0:
                    dist[i] = (closes[i] - sma_vals[i]) / sma_vals[i]
            all_features[f"sma_{period}_dist"] = dist

    if "ema" in selected:
        for period in [10, 20, 50]:
            ema_vals = ind.ema(closes, period)
            dist = [float("nan")] * n
            for i in range(n):
                if not math.isnan(ema_vals[i]) and ema_vals[i] > 0:
                    dist[i] = (closes[i] - ema_vals[i]) / ema_vals[i]
            all_features[f"ema_{period}_dist"] = dist

    if "rsi" in selected:
        for period in [7, 14, 21]:
            rsi_vals = ind.rsi(closes, period)
            norm = [float("nan")] * n
            for i in range(n):
                if not math.isnan(rsi_vals[i]):
                    norm[i] = (rsi_vals[i] - 50) / 50  # Normalize to [-1, 1]
            all_features[f"rsi_{period}"] = norm

    if "atr" in selected:
        for period in [7, 14]:
            atr_vals = ind.atr(highs, lows, closes, period)
            norm = [float("nan")] * n
            for i in range(n):
                if not math.isnan(atr_vals[i]) and closes[i] > 0:
                    norm[i] = atr_vals[i] / closes[i]  # Normalize by price
            all_features[f"atr_{period}_norm"] = norm

    if "macd" in selected:
        macd_line, signal_line, histogram = ind.macd(closes)
        norm_macd = [float("nan")] * n
        norm_hist = [float("nan")] * n
        for i in range(n):
            if not math.isnan(macd_line[i]) and closes[i] > 0:
                norm_macd[i] = macd_line[i] / closes[i]
            if not math.isnan(histogram[i]) and closes[i] > 0:
                norm_hist[i] = histogram[i] / closes[i]
        all_features["macd_norm"] = norm_macd
        all_features["macd_hist_norm"] = norm_hist

    if "bollinger" in selected:
        upper, middle, lower = ind.bollinger_bands(closes)
        bb_pos = [float("nan")] * n
        bb_width = [float("nan")] * n
        for i in range(n):
            if not math.isnan(upper[i]) and not math.isnan(lower[i]):
                bw = upper[i] - lower[i]
                if bw > 0:
                    bb_pos[i] = (closes[i] - lower[i]) / bw
                    bb_width[i] = bw / middle[i] if middle[i] > 0 else 0
        all_features["bb_position"] = bb_pos
        all_features["bb_width"] = bb_width

    if "adx" in selected:
        adx_vals = ind.adx(highs, lows, closes, 14)
        norm = [float("nan")] * n
        for i in range(n):
            if not math.isnan(adx_vals[i]):
                norm[i] = adx_vals[i] / 100  # Normalize to [0, 1]
        all_features["adx_14"] = norm

    if "stochastic" in selected:
        k_line, d_line = ind.stochastic(highs, lows, closes)
        k_norm = [float("nan")] * n
        d_norm = [float("nan")] * n
        for i in range(n):
            if not math.isnan(k_line[i]):
                k_norm[i] = (k_line[i] - 50) / 50
            if not math.isnan(d_line[i]):
                d_norm[i] = (d_line[i] - 50) / 50
        all_features["stoch_k"] = k_norm
        all_features["stoch_d"] = d_norm

    # ── Volume features ───────────────────────────
    if "volume" in selected and any(v > 0 for v in volumes):
        vol_sma_20 = ind.sma(volumes, 20)
        vol_ratio = [float("nan")] * n
        for i in range(n):
            if not math.isnan(vol_sma_20[i]) and vol_sma_20[i] > 0:
                vol_ratio[i] = volumes[i] / vol_sma_20[i]
        all_features["volume_ratio_20"] = vol_ratio

    # ── Time features ─────────────────────────────
    if "time" in selected:
        # These require actual timestamps; skip for raw price data
        pass

    # ── Build matrix ──────────────────────────────
    feature_names = list(all_features.keys())
    feature_matrix: list[list[float]] = []

    for i in range(n):
        row = [all_features[name][i] for name in feature_names]
        feature_matrix.append(row)

    return feature_names, feature_matrix


def compute_targets(
    closes: list[float],
    target_config: Optional[dict] = None,
) -> tuple[str, list[float]]:
    """
    Compute prediction targets from close prices.

    Returns:
        (target_name, target_values)
    """
    config = target_config or {}
    target_type = config.get("type", "direction")
    horizon = config.get("horizon", 1)
    n = len(closes)

    if target_type == "direction":
        # Binary: 1 = price goes up, 0 = price goes down
        targets = [float("nan")] * n
        for i in range(n - horizon):
            ret = (closes[i + horizon] - closes[i]) / closes[i] if closes[i] > 0 else 0
            targets[i] = 1.0 if ret > 0 else 0.0
        return f"direction_{horizon}bar", targets

    elif target_type == "return":
        # Regression: predict return magnitude
        targets = [float("nan")] * n
        for i in range(n - horizon):
            targets[i] = (closes[i + horizon] - closes[i]) / closes[i] if closes[i] > 0 else 0
        return f"return_{horizon}bar", targets

    elif target_type == "volatility":
        # Predict future volatility
        targets = [float("nan")] * n
        for i in range(n - horizon):
            window = closes[i: i + horizon + 1]
            if len(window) > 1:
                rets = [(window[j] - window[j - 1]) / window[j - 1] for j in range(1, len(window)) if window[j - 1] != 0]
                if rets:
                    mean = sum(rets) / len(rets)
                    var = sum((r - mean) ** 2 for r in rets) / len(rets)
                    targets[i] = math.sqrt(var)
        return f"volatility_{horizon}bar", targets

    else:
        # Default to direction
        targets = [float("nan")] * n
        for i in range(n - horizon):
            targets[i] = 1.0 if closes[i + horizon] > closes[i] else 0.0
        return "direction_1bar", targets


def clean_data(
    feature_names: list[str],
    feature_matrix: list[list[float]],
    targets: list[float],
) -> tuple[list[str], list[list[float]], list[float]]:
    """Remove rows with NaN values in features or target."""
    clean_X = []
    clean_y = []
    for i, (row, t) in enumerate(zip(feature_matrix, targets)):
        if math.isnan(t):
            continue
        if any(math.isnan(v) for v in row):
            continue
        clean_X.append(row)
        clean_y.append(t)
    return feature_names, clean_X, clean_y


# Default feature set
_DEFAULT_FEATURES = [
    "returns", "returns_multi", "volatility", "candle_patterns",
    "sma", "ema", "rsi", "atr", "macd", "bollinger", "adx",
    "stochastic", "volume",
]
