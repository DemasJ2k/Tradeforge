"""
Meta-Labeling — Two-stage ML prediction system.

Concept (from Marcos López de Prado, "Advances in Financial Machine Learning"):
  Stage 1: A primary model predicts direction (buy/sell signal)
  Stage 2: A meta model predicts whether the primary signal will be profitable
           (i.e. trade / no-trade filter)

The meta model uses the primary model's prediction + confidence as additional
features alongside the original feature matrix. This separates the "what side"
decision from the "should I trade" decision.

Benefits:
  - Filters out low-quality signals from the primary model
  - Can dramatically improve profit factor and reduce drawdown
  - Works with any primary model (LightGBM, XGBoost, CatBoost, RF, ensemble)

Usage:
  1. Train a primary model (Level 1 or 2) for direction prediction
  2. Train a meta model that references the primary model
  3. At prediction time: primary predicts direction, meta predicts trade/no-trade
  4. Only execute trades where meta model says "trade" with sufficient confidence
"""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.services.ml.features import (
    compute_features,
    compute_targets,
    clean_data,
    apply_rolling_zscore,
)

logger = logging.getLogger(__name__)

_MODEL_DIR = Path(settings.UPLOAD_DIR).parent / "ml_models"
_MODEL_DIR.mkdir(parents=True, exist_ok=True)


def train_meta_model(
    ohlcv_data: list[dict],
    primary_model_path: str,
    model_type: str = "lightgbm",
    features_config: Optional[dict] = None,
    target_config: Optional[dict] = None,
    hyperparams: Optional[dict] = None,
    model_id: int = 0,
) -> dict:
    """
    Train a meta-labeling model.

    Steps:
      1. Load primary model and generate its predictions on the training data
      2. Build meta features = original features + primary prediction + primary confidence
      3. Build meta targets = 1 if primary direction was correct, 0 otherwise
      4. Train a binary classifier on meta features → meta targets
      5. Save both primary and meta model references

    Args:
        ohlcv_data: List of OHLCV dicts
        primary_model_path: Path to the trained primary model (.joblib)
        model_type: Tree model type for the meta model
        features_config: Feature configuration
        target_config: Target configuration
        hyperparams: Model hyperparameters
        model_id: Database model ID for file naming

    Returns:
        Dict with train_metrics, val_metrics, feature_importance, model_path, etc.
    """
    import joblib
    import numpy as np

    hp = hyperparams or {}
    n = len(ohlcv_data)
    if n < 200:
        raise ValueError(f"Need at least 200 bars for meta-labeling, got {n}")

    # ── Load primary model ───────────────────────────────────
    if not os.path.exists(primary_model_path):
        raise FileNotFoundError(f"Primary model not found: {primary_model_path}")

    primary_saved = joblib.load(primary_model_path)
    primary_model = primary_saved["model"]
    primary_scaler = primary_saved.get("scaler")

    # ── Compute features ─────────────────────────────────────
    opens = [d["open"] for d in ohlcv_data]
    highs = [d["high"] for d in ohlcv_data]
    lows = [d["low"] for d in ohlcv_data]
    closes = [d["close"] for d in ohlcv_data]
    volumes = [d.get("volume", 0) for d in ohlcv_data]
    timestamps = [d.get("datetime") for d in ohlcv_data]
    if all(t is None for t in timestamps):
        timestamps = None

    feature_names, feature_matrix = compute_features(
        opens, highs, lows, closes, volumes, features_config,
        timestamps=timestamps,
    )
    if not feature_names:
        raise ValueError("No features computed — check data")

    # Optional rolling Z-score normalization
    normalize = (features_config or {}).get("normalize", "none")
    if normalize == "zscore" and feature_matrix:
        zscore_window = (features_config or {}).get("zscore_window", 50)
        feature_matrix = apply_rolling_zscore(feature_matrix, window=zscore_window)

    # Compute actual targets (for determining if primary was correct)
    target_name, targets = compute_targets(closes, target_config, highs=highs, lows=lows)

    # Clean NaN rows
    feature_names_clean, X_clean, y_clean = clean_data(feature_names, feature_matrix, targets)

    if len(X_clean) < 100:
        raise ValueError(f"Not enough valid samples after cleaning: {len(X_clean)}")

    X_arr = np.array(X_clean)
    y_arr = np.array(y_clean)

    # ── Generate primary model predictions on all data ───────
    primary_preds = []
    primary_confs = []

    for row in X_arr:
        pred_row = row
        if primary_scaler is not None:
            pred_row = primary_scaler.transform([row])[0]

        pred = float(primary_model.predict([pred_row])[0])
        primary_preds.append(pred)

        conf = 0.5
        if hasattr(primary_model, "predict_proba"):
            proba = primary_model.predict_proba([pred_row])
            conf = float(max(proba[0]))
        primary_confs.append(conf)

    primary_preds = np.array(primary_preds)
    primary_confs = np.array(primary_confs)

    # ── Build meta features ──────────────────────────────────
    # Meta features = original features + primary_prediction + primary_confidence
    meta_feature_names = feature_names_clean + ["meta_primary_pred", "meta_primary_conf"]
    X_meta = np.column_stack([X_arr, primary_preds, primary_confs])

    # ── Build meta targets ───────────────────────────────────
    # Meta target = 1 if primary prediction was correct, 0 otherwise
    target_type = (target_config or {}).get("type", "direction")

    if target_type in ("direction", "triple_barrier"):
        # Binary: was the primary prediction correct?
        if target_type == "triple_barrier":
            # For triple barrier: correct means predicted the right barrier
            meta_targets = (primary_preds == y_arr).astype(float)
        else:
            # For direction: correct means same class
            meta_targets = (primary_preds == y_arr).astype(float)
    else:
        # Regression: correct means same sign
        meta_targets = ((primary_preds > 0) == (y_arr > 0)).astype(float)

    logger.info(
        "Meta-labeling: %d samples, %d features (+2 meta), %.1f%% primary correct",
        len(X_meta), len(meta_feature_names),
        float(np.mean(meta_targets)) * 100,
    )

    # ── Train/val split (chronological) ──────────────────────
    split_idx = int(len(X_meta) * 0.8)
    X_train, X_val = X_meta[:split_idx], X_meta[split_idx:]
    y_train, y_val = meta_targets[:split_idx], meta_targets[split_idx:]

    # ── Build and train meta model ───────────────────────────
    from app.services.ml.trainer import _build_model, _compute_metrics, _get_feature_importance

    # Meta model is always binary classification (trade / no-trade)
    meta_target_config = {"type": "direction"}
    model = _build_model(model_type, hp, meta_target_config)

    early_rounds = hp.get("early_stopping_rounds", 0)
    if early_rounds > 0 and model_type in ("xgboost", "lightgbm"):
        try:
            model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
        except Exception:
            model.fit(X_train, y_train)
    elif early_rounds > 0 and model_type == "catboost":
        try:
            model.fit(X_train, y_train, eval_set=(X_val, y_val),
                      early_stopping_rounds=early_rounds, verbose=False)
        except Exception:
            model.fit(X_train, y_train)
    else:
        model.fit(X_train, y_train)

    # ── Evaluate ─────────────────────────────────────────────
    train_pred = model.predict(X_train)
    val_pred = model.predict(X_val)

    c_val = closes[split_idx:split_idx + len(y_val)]
    train_metrics = _compute_metrics(y_train.tolist(), train_pred, True)
    val_metrics = _compute_metrics(y_val.tolist(), val_pred, True, c_val)

    importance = _get_feature_importance(model, meta_feature_names)

    # ── Compute combined strategy metrics ────────────────────
    # Simulate: only trade when meta says "trade" (pred=1)
    val_primary_preds = primary_preds[split_idx:]
    val_meta_preds = val_pred
    val_actual = y_arr[split_idx:]
    val_closes = np.array(closes[split_idx:split_idx + len(val_actual)], dtype=np.float64)

    combined_stats = _compute_combined_metrics(
        val_primary_preds, val_meta_preds, val_actual, val_closes, target_type
    )
    val_metrics["meta_filter_rate"] = combined_stats.get("filter_rate", 0)
    val_metrics["meta_filtered_accuracy"] = combined_stats.get("filtered_accuracy", 0)
    val_metrics["meta_trades_taken"] = combined_stats.get("trades_taken", 0)
    val_metrics["meta_trades_total"] = combined_stats.get("trades_total", 0)

    # ── Save model ───────────────────────────────────────────
    model_path = str(_MODEL_DIR / f"model_{model_id}.joblib")
    joblib.dump({
        "model": model,
        "feature_names": meta_feature_names,
        "target_name": "meta_correct",
        "model_type": model_type,
        "is_meta_model": True,
        "primary_model_path": primary_model_path,
        "primary_scaler": primary_scaler,
        "primary_model": primary_model,
    }, model_path)

    logger.info(
        "Meta model %d trained: val_acc=%.3f, filter_rate=%.1f%%, filtered_acc=%.3f",
        model_id,
        val_metrics.get("accuracy", 0),
        combined_stats.get("filter_rate", 0) * 100,
        combined_stats.get("filtered_accuracy", 0),
    )

    return {
        "train_metrics": train_metrics,
        "val_metrics": val_metrics,
        "feature_importance": importance,
        "model_path": model_path,
        "n_train": len(X_train),
        "n_val": len(X_val),
        "n_features": len(meta_feature_names),
        "feature_names": meta_feature_names,
        "target_name": "meta_correct",
        "meta_stats": combined_stats,
    }


def predict_with_meta(
    primary_model_path: str,
    meta_model_path: str,
    bars: list[dict],
    features_config: Optional[dict] = None,
    target_config: Optional[dict] = None,
) -> Optional[dict]:
    """
    Two-stage prediction: primary model → meta model.

    Returns:
        Dict with direction, confidence, should_trade, meta_confidence
        or None on failure.
    """
    import joblib
    import numpy as np

    if not bars or len(bars) < 50:
        return None

    try:
        # Load models
        meta_saved = joblib.load(meta_model_path)
        meta_model = meta_saved["model"]
        primary_model = meta_saved.get("primary_model")
        primary_scaler = meta_saved.get("primary_scaler")

        if primary_model is None:
            # Fallback: load primary from its own path
            if not os.path.exists(primary_model_path):
                return None
            primary_saved = joblib.load(primary_model_path)
            primary_model = primary_saved["model"]
            primary_scaler = primary_saved.get("scaler")

        # Compute features
        opens = [b["open"] for b in bars]
        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]
        closes = [b["close"] for b in bars]
        volumes = [b.get("volume", 0) for b in bars]
        timestamps = [b.get("datetime") for b in bars]
        if all(t is None for t in timestamps):
            timestamps = None

        _, feature_matrix = compute_features(
            opens, highs, lows, closes, volumes, features_config,
            timestamps=timestamps,
        )

        # Apply rolling Z-score if configured
        normalize = (features_config or {}).get("normalize", "none")
        if normalize == "zscore" and feature_matrix:
            zscore_window = (features_config or {}).get("zscore_window", 50)
            feature_matrix = apply_rolling_zscore(feature_matrix, window=zscore_window)

        if not feature_matrix:
            return None

        # Use last row
        last_row = feature_matrix[-1]
        if any(math.isnan(v) for v in last_row):
            return None

        # Primary prediction
        pred_row = list(last_row)
        if primary_scaler is not None:
            pred_row = list(primary_scaler.transform([pred_row])[0])

        primary_pred = float(primary_model.predict([pred_row])[0])
        primary_conf = 0.5
        if hasattr(primary_model, "predict_proba"):
            proba = primary_model.predict_proba([pred_row])
            primary_conf = float(max(proba[0]))

        # Meta prediction (original features + primary pred + primary conf)
        meta_row = list(last_row) + [primary_pred, primary_conf]
        meta_pred = float(meta_model.predict([meta_row])[0])
        meta_conf = 0.5
        if hasattr(meta_model, "predict_proba"):
            proba = meta_model.predict_proba([meta_row])
            meta_conf = float(max(proba[0]))

        # Determine direction from primary model
        target_type = (target_config or {}).get("type", "direction")
        if target_type == "direction":
            direction = 1 if primary_pred >= 0.5 else -1
        elif target_type == "return":
            direction = 1 if primary_pred > 0 else -1
        elif target_type == "triple_barrier":
            direction = 1 if primary_pred == 1.0 else (-1 if primary_pred == 0.0 else 0)
        else:
            direction = 0

        # Meta decision: should_trade = meta says "correct" (pred=1)
        should_trade = meta_pred >= 0.5

        return {
            "direction": direction,
            "confidence": primary_conf,
            "should_trade": should_trade,
            "meta_confidence": meta_conf,
            "primary_prediction": primary_pred,
            "meta_prediction": meta_pred,
        }

    except Exception as e:
        logger.error("[MetaLabel] Prediction failed: %s", e)
        return None


def _compute_combined_metrics(
    primary_preds: "np.ndarray",
    meta_preds: "np.ndarray",
    actual: "np.ndarray",
    closes: "np.ndarray",
    target_type: str,
) -> dict:
    """Compute metrics for the combined primary + meta strategy."""
    import numpy as np

    # Which trades the meta model approves
    trade_mask = meta_preds >= 0.5
    trades_taken = int(np.sum(trade_mask))
    trades_total = len(meta_preds)

    if trades_taken == 0:
        return {
            "filter_rate": 1.0,
            "filtered_accuracy": 0.0,
            "trades_taken": 0,
            "trades_total": trades_total,
        }

    filter_rate = 1.0 - (trades_taken / trades_total)

    # Accuracy of primary model on meta-approved trades only
    if target_type in ("direction", "triple_barrier"):
        correct = primary_preds[trade_mask] == actual[trade_mask]
    else:
        correct = (primary_preds[trade_mask] > 0) == (actual[trade_mask] > 0)

    filtered_accuracy = float(np.mean(correct))

    return {
        "filter_rate": round(filter_rate, 4),
        "filtered_accuracy": round(filtered_accuracy, 4),
        "trades_taken": trades_taken,
        "trades_total": trades_total,
    }
