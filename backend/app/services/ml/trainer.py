"""
ML model training and prediction service.

Supports:
  Level 1: Adaptive parameter optimization (Random Forest / XGBoost)
  Level 2: Signal prediction (XGBoost → LSTM)
  Level 3: Full ML strategies (RL agents) — placeholder

Uses scikit-learn and XGBoost for tree-based models.
Models are serialized to disk via joblib.
"""

import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.services.ml.features import compute_features, compute_targets, clean_data

logger = logging.getLogger(__name__)

# Model storage directory
_MODEL_DIR = Path(settings.UPLOAD_DIR).parent / "ml_models"
_MODEL_DIR.mkdir(parents=True, exist_ok=True)


class MLTrainer:
    """Handles training, evaluation, and prediction for ML models."""

    @staticmethod
    def train_model(
        ohlcv_data: list[dict],
        model_type: str = "random_forest",
        features_config: Optional[dict] = None,
        target_config: Optional[dict] = None,
        hyperparams: Optional[dict] = None,
        model_id: int = 0,
    ) -> dict:
        """
        Train an ML model on OHLCV data.

        Args:
            ohlcv_data: List of dicts with keys: open, high, low, close, volume
            model_type: "random_forest", "xgboost", "gradient_boosting"
            features_config: Which features to compute
            target_config: What to predict (direction, return, volatility)
            hyperparams: Model hyperparameters
            model_id: Database model ID for file naming

        Returns:
            Dict with train_metrics, val_metrics, feature_importance, model_path
        """
        import joblib

        hp = hyperparams or {}
        n = len(ohlcv_data)
        if n < 100:
            raise ValueError(f"Need at least 100 bars, got {n}")

        # Extract OHLCV
        opens = [d["open"] for d in ohlcv_data]
        highs = [d["high"] for d in ohlcv_data]
        lows = [d["low"] for d in ohlcv_data]
        closes = [d["close"] for d in ohlcv_data]
        volumes = [d.get("volume", 0) for d in ohlcv_data]

        # Compute features
        feature_names, feature_matrix = compute_features(
            opens, highs, lows, closes, volumes, features_config
        )
        if not feature_names:
            raise ValueError("No features computed — check data")

        # Compute targets
        target_name, targets = compute_targets(closes, target_config)

        # Clean NaN rows
        feature_names, X, y = clean_data(feature_names, feature_matrix, targets)

        if len(X) < 50:
            raise ValueError(f"Not enough valid samples after cleaning: {len(X)}")

        logger.info("Training %s: %d samples, %d features", model_type, len(X), len(feature_names))

        # Train/validation split (time-series aware: use last 20% as validation)
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]

        # Build and train model
        model = _build_model(model_type, hp, target_config)

        # Early stopping for XGBoost
        early_rounds = hp.get("early_stopping_rounds", 0)
        if early_rounds > 0 and model_type == "xgboost":
            try:
                model.fit(
                    X_train, y_train,
                    eval_set=[(X_val, y_val)],
                    verbose=False,
                )
            except Exception:
                model.fit(X_train, y_train)
        else:
            model.fit(X_train, y_train)

        # Evaluate
        train_pred = model.predict(X_train)
        val_pred = model.predict(X_val)

        is_classification = (target_config or {}).get("type", "direction") in ("direction",)

        train_metrics = _compute_metrics(y_train, train_pred, is_classification)
        val_metrics = _compute_metrics(y_val, val_pred, is_classification)

        # Feature importance
        importance = _get_feature_importance(model, feature_names)

        # Save model
        model_path = str(_MODEL_DIR / f"model_{model_id}.joblib")
        joblib.dump({
            "model": model,
            "feature_names": feature_names,
            "target_name": target_name,
            "model_type": model_type,
        }, model_path)

        logger.info(
            "Model %d trained: train_acc=%.3f, val_acc=%.3f",
            model_id,
            train_metrics.get("accuracy", 0),
            val_metrics.get("accuracy", 0),
        )

        return {
            "train_metrics": train_metrics,
            "val_metrics": val_metrics,
            "feature_importance": importance,
            "model_path": model_path,
            "n_train": len(X_train),
            "n_val": len(X_val),
            "n_features": len(feature_names),
            "feature_names": feature_names,
            "target_name": target_name,
        }

    @staticmethod
    def train_walk_forward(
        ohlcv_data: list[dict],
        model_type: str = "random_forest",
        features_config: Optional[dict] = None,
        target_config: Optional[dict] = None,
        hyperparams: Optional[dict] = None,
        model_id: int = 0,
        n_folds: int = 5,
    ) -> dict:
        """
        Train with walk-forward cross-validation.

        Uses expanding window (anchored) approach:
          Fold 1: train[0:20%], val[20%:40%]
          Fold 2: train[0:40%], val[40%:60%]
          ...
        Final model trained on all data except last 20%.

        Returns aggregated CV metrics + final model.
        """
        import joblib
        import numpy as np

        hp = hyperparams or {}
        n = len(ohlcv_data)
        if n < 200:
            raise ValueError(f"Need at least 200 bars for walk-forward, got {n}")

        opens = [d["open"] for d in ohlcv_data]
        highs = [d["high"] for d in ohlcv_data]
        lows = [d["low"] for d in ohlcv_data]
        closes = [d["close"] for d in ohlcv_data]
        volumes = [d.get("volume", 0) for d in ohlcv_data]

        feature_names, feature_matrix = compute_features(
            opens, highs, lows, closes, volumes, features_config
        )
        if not feature_names:
            raise ValueError("No features computed")

        target_name, targets = compute_targets(closes, target_config)
        feature_names, X, y = clean_data(feature_names, feature_matrix, targets)

        if len(X) < 100:
            raise ValueError(f"Not enough valid samples: {len(X)}")

        is_classification = (target_config or {}).get("type", "direction") in ("direction",)

        # Walk-forward folds (expanding window)
        segment_size = len(X) // (n_folds + 1)
        fold_metrics = []

        for fold in range(n_folds):
            train_end = segment_size * (fold + 1)
            val_start = train_end
            val_end = min(train_end + segment_size, len(X))

            if val_end <= val_start or train_end < 50:
                continue

            X_train_f, y_train_f = X[:train_end], y[:train_end]
            X_val_f, y_val_f = X[val_start:val_end], y[val_start:val_end]

            model = _build_model(model_type, hp, target_config)

            early_rounds = hp.get("early_stopping_rounds", 0)
            if early_rounds > 0 and model_type == "xgboost":
                try:
                    model.fit(X_train_f, y_train_f, eval_set=[(X_val_f, y_val_f)], verbose=False)
                except Exception:
                    model.fit(X_train_f, y_train_f)
            else:
                model.fit(X_train_f, y_train_f)

            val_pred = model.predict(X_val_f)
            metrics = _compute_metrics(y_val_f, val_pred, is_classification)
            metrics["fold"] = fold + 1
            metrics["n_train"] = len(X_train_f)
            metrics["n_val"] = len(X_val_f)
            fold_metrics.append(metrics)

            logger.info(
                "WF Fold %d: train=%d, val=%d, acc=%.4f",
                fold + 1, len(X_train_f), len(X_val_f),
                metrics.get("accuracy", metrics.get("r2", 0)),
            )

        # Train final model on 80% (standard holdout for the saved model)
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]

        final_model = _build_model(model_type, hp, target_config)
        early_rounds = hp.get("early_stopping_rounds", 0)
        if early_rounds > 0 and model_type == "xgboost":
            try:
                final_model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
            except Exception:
                final_model.fit(X_train, y_train)
        else:
            final_model.fit(X_train, y_train)

        train_pred = final_model.predict(X_train)
        val_pred = final_model.predict(X_val)
        train_metrics = _compute_metrics(y_train, train_pred, is_classification)
        val_metrics = _compute_metrics(y_val, val_pred, is_classification)
        importance = _get_feature_importance(final_model, feature_names)

        # Aggregate WF metrics
        if fold_metrics and is_classification:
            wf_avg_accuracy = sum(m.get("accuracy", 0) for m in fold_metrics) / len(fold_metrics)
            wf_avg_f1 = sum(m.get("f1", 0) for m in fold_metrics) / len(fold_metrics)
            wf_std_accuracy = (
                sum((m.get("accuracy", 0) - wf_avg_accuracy) ** 2 for m in fold_metrics)
                / len(fold_metrics)
            ) ** 0.5
        else:
            wf_avg_accuracy = 0
            wf_avg_f1 = 0
            wf_std_accuracy = 0

        model_path = str(_MODEL_DIR / f"model_{model_id}.joblib")
        joblib.dump({
            "model": final_model,
            "feature_names": feature_names,
            "target_name": target_name,
            "model_type": model_type,
        }, model_path)

        logger.info(
            "WF Model %d: avg_cv_acc=%.4f (std=%.4f), final_val_acc=%.4f",
            model_id, wf_avg_accuracy, wf_std_accuracy,
            val_metrics.get("accuracy", 0),
        )

        return {
            "train_metrics": train_metrics,
            "val_metrics": val_metrics,
            "feature_importance": importance,
            "model_path": model_path,
            "n_train": len(X_train),
            "n_val": len(X_val),
            "n_features": len(feature_names),
            "feature_names": feature_names,
            "target_name": target_name,
            "walk_forward": {
                "n_folds": len(fold_metrics),
                "fold_metrics": fold_metrics,
                "avg_accuracy": round(wf_avg_accuracy, 4),
                "avg_f1": round(wf_avg_f1, 4),
                "std_accuracy": round(wf_std_accuracy, 4),
            },
        }

    @staticmethod
    def predict(
        model_path: str,
        ohlcv_data: list[dict],
        features_config: Optional[dict] = None,
    ) -> list[dict]:
        """
        Make predictions using a trained model.

        Returns list of dicts: [{prediction, confidence, features}, ...]
        """
        import joblib

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found: {model_path}")

        saved = joblib.load(model_path)
        model = saved["model"]
        feature_names = saved["feature_names"]

        opens = [d["open"] for d in ohlcv_data]
        highs = [d["high"] for d in ohlcv_data]
        lows = [d["low"] for d in ohlcv_data]
        closes = [d["close"] for d in ohlcv_data]
        volumes = [d.get("volume", 0) for d in ohlcv_data]

        _, feature_matrix = compute_features(
            opens, highs, lows, closes, volumes, features_config
        )

        results = []
        for i, row in enumerate(feature_matrix):
            if any(math.isnan(v) for v in row):
                continue

            pred = float(model.predict([row])[0])
            # Get prediction probability if available
            confidence = 0.5
            if hasattr(model, "predict_proba"):
                proba = model.predict_proba([row])
                confidence = float(max(proba[0]))

            results.append({
                "bar_index": i,
                "prediction": pred,
                "confidence": confidence,
                "features": {name: row[j] for j, name in enumerate(feature_names)},
            })

        return results

    @staticmethod
    def train_level3(
        ohlcv_data: list[dict],
        sub_type: str = "lstm",
        seq_len: int = 20,
        hidden_units: int = 64,
        features_config: Optional[dict] = None,
        target_config: Optional[dict] = None,
        model_id: int = 0,
    ) -> dict:
        """
        Train a Level 3 Advanced ML model.

        sub_type="lstm"     → LSTM sequence model (TensorFlow/Keras, falls back to ensemble)
        sub_type="ensemble" → Stacked ensemble: RandomForest + XGBoost + LogisticRegression
        """
        import joblib

        opens = [d["open"] for d in ohlcv_data]
        highs = [d["high"] for d in ohlcv_data]
        lows = [d["low"] for d in ohlcv_data]
        closes = [d["close"] for d in ohlcv_data]
        volumes = [d.get("volume", 0) for d in ohlcv_data]

        feature_names, feature_matrix = compute_features(
            opens, highs, lows, closes, volumes, features_config
        )
        if not feature_names:
            raise ValueError("No features computed — check data")

        target_name, targets = compute_targets(closes, target_config)
        feature_names, X, y = clean_data(feature_names, feature_matrix, targets)

        if len(X) < 50:
            raise ValueError(f"Not enough valid samples after cleaning: {len(X)}")

        logger.info("Level 3 training (%s): %d samples, %d features", sub_type, len(X), len(feature_names))

        if sub_type == "lstm":
            model, scaler, val_accuracy, meta = MLTrainer._train_lstm(
                X, y, feature_names, seq_len=seq_len, units=hidden_units
            )
            # Save model — use joblib wrapper so predict pipeline stays consistent
            model_path = str(_MODEL_DIR / f"model_{model_id}.joblib")
            joblib.dump({
                "model": model,
                "scaler": scaler,
                "feature_names": feature_names,
                "target_name": target_name,
                "model_type": "lstm",
                "meta": meta,
            }, model_path)

            val_metrics = {"accuracy": round(val_accuracy, 4)}
            train_metrics = {"accuracy": round(val_accuracy, 4)}  # LSTM: use val as proxy
            feature_importance = {}

        else:
            model, scaler, val_accuracy, train_accuracy, meta = MLTrainer._train_ensemble(
                X, y, feature_names
            )
            model_path = str(_MODEL_DIR / f"model_{model_id}.joblib")
            joblib.dump({
                "model": model,
                "scaler": scaler,
                "feature_names": feature_names,
                "target_name": target_name,
                "model_type": "ensemble",
                "meta": meta,
            }, model_path)

            val_metrics = {"accuracy": round(val_accuracy, 4)}
            train_metrics = {"accuracy": round(train_accuracy, 4)}
            # Extract feature importance from the RF sub-estimator if possible
            feature_importance = {}
            try:
                rf_est = None
                for name, est in model.estimators_:
                    if name == "rf":
                        rf_est = est
                        break
                if rf_est is not None and hasattr(rf_est, "feature_importances_"):
                    feature_importance = dict(
                        sorted(
                            {n: round(float(v), 6) for n, v in zip(feature_names, rf_est.feature_importances_)}.items(),
                            key=lambda x: -x[1],
                        )
                    )
            except Exception:
                pass

        logger.info(
            "Level 3 model %d (%s) trained: val_acc=%.3f",
            model_id, sub_type, val_accuracy,
        )

        return {
            "train_metrics": train_metrics,
            "val_metrics": val_metrics,
            "feature_importance": feature_importance,
            "model_path": model_path,
            "n_train": int(len(X) * 0.8),
            "n_val": int(len(X) * 0.2),
            "n_features": len(feature_names),
            "feature_names": feature_names,
            "target_name": target_name,
            "meta": meta,
        }

    @staticmethod
    def _train_lstm(X, y, feature_names, seq_len: int = 20, units: int = 64):
        """Train LSTM model using Keras/TensorFlow for time-series prediction."""
        import numpy as np
        from sklearn.preprocessing import StandardScaler
        from sklearn.metrics import accuracy_score

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        # Create sequences
        def make_sequences(data, labels, sl):
            Xs, ys = [], []
            for i in range(len(data) - sl):
                Xs.append(data[i:i + sl])
                ys.append(labels[i + sl])
            return np.array(Xs), np.array(ys)

        X_seq, y_seq = make_sequences(X_scaled, y.values if hasattr(y, "values") else list(y), seq_len)

        if len(X_seq) < 40:
            raise ValueError(f"Not enough sequences after windowing (got {len(X_seq)}). Use more data or reduce seq_len.")

        split = int(len(X_seq) * 0.8)
        X_train, X_val = X_seq[:split], X_seq[split:]
        y_train, y_val = y_seq[:split], y_seq[split:]

        try:
            import tensorflow as tf
            from tensorflow import keras

            model = keras.Sequential([
                keras.layers.LSTM(units, input_shape=(seq_len, X_scaled.shape[1]), return_sequences=False),
                keras.layers.Dropout(0.2),
                keras.layers.Dense(32, activation='relu'),
                keras.layers.Dense(1, activation='sigmoid'),
            ])
            model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
            model.fit(X_train, y_train, epochs=20, batch_size=32,
                      validation_data=(X_val, y_val), verbose=0)

            val_pred = (model.predict(X_val, verbose=0) > 0.5).astype(int).flatten()
            val_accuracy = float(accuracy_score(y_val, val_pred))
            meta = {"architecture": f"LSTM({units})", "seq_len": seq_len, "sub_type": "lstm"}
            return model, scaler, val_accuracy, meta

        except ImportError:
            logger.warning("TensorFlow not available — falling back to ensemble for Level 3 LSTM")
            # Re-use ensemble training path
            model, scaler2, val_accuracy, train_accuracy, meta = MLTrainer._train_ensemble(
                X, y if hasattr(y, "values") else y, feature_names
            )
            meta["sub_type"] = "lstm_fallback_ensemble"
            return model, scaler2, val_accuracy, meta

    @staticmethod
    def _train_ensemble(X, y, feature_names):
        """Train stacked ensemble: RandomForest + XGBoost + LogisticRegression."""
        import numpy as np
        from sklearn.ensemble import RandomForestClassifier, StackingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.metrics import accuracy_score
        from sklearn.model_selection import train_test_split

        try:
            from xgboost import XGBClassifier
            xgb_est = XGBClassifier(
                n_estimators=100, max_depth=4, learning_rate=0.1,
                use_label_encoder=False, eval_metric='logloss', random_state=42
            )
        except ImportError:
            from sklearn.ensemble import GradientBoostingClassifier
            xgb_est = GradientBoostingClassifier(n_estimators=100, max_depth=4, random_state=42)

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        y_arr = y.values if hasattr(y, "values") else list(y)
        X_train, X_val, y_train, y_val = train_test_split(
            X_scaled, y_arr, test_size=0.2, random_state=42
        )

        estimators = [
            ('rf', RandomForestClassifier(n_estimators=100, random_state=42)),
            ('xgb', xgb_est),
        ]
        stack = StackingClassifier(
            estimators=estimators,
            final_estimator=LogisticRegression(max_iter=1000),
            cv=3,
        )
        stack.fit(X_train, y_train)

        val_pred = stack.predict(X_val)
        train_pred = stack.predict(X_train)
        val_accuracy = float(accuracy_score(y_val, val_pred))
        train_accuracy = float(accuracy_score(y_train, train_pred))

        meta = {"architecture": "Stacked(RF+XGB+LR)", "sub_type": "ensemble"}
        return stack, scaler, val_accuracy, train_accuracy, meta

    @staticmethod
    def delete_model(model_path: str):
        """Delete a serialized model file."""
        if os.path.exists(model_path):
            os.remove(model_path)


def _build_model(model_type: str, hp: dict, target_config: Optional[dict] = None):
    """Build a scikit-learn compatible model."""
    is_classification = (target_config or {}).get("type", "direction") in ("direction",)

    if model_type == "random_forest":
        if is_classification:
            from sklearn.ensemble import RandomForestClassifier
            return RandomForestClassifier(
                n_estimators=hp.get("n_estimators", 100),
                max_depth=hp.get("max_depth", 10),
                min_samples_split=hp.get("min_samples_split", 5),
                min_samples_leaf=hp.get("min_samples_leaf", 2),
                random_state=42,
                n_jobs=-1,
            )
        else:
            from sklearn.ensemble import RandomForestRegressor
            return RandomForestRegressor(
                n_estimators=hp.get("n_estimators", 100),
                max_depth=hp.get("max_depth", 10),
                min_samples_split=hp.get("min_samples_split", 5),
                min_samples_leaf=hp.get("min_samples_leaf", 2),
                random_state=42,
                n_jobs=-1,
            )

    elif model_type == "xgboost":
        try:
            import xgboost as xgb
            early_rounds = hp.get("early_stopping_rounds", 0)
            common = dict(
                n_estimators=hp.get("n_estimators", 200),
                max_depth=hp.get("max_depth", 6),
                learning_rate=hp.get("learning_rate", 0.1),
                subsample=hp.get("subsample", 0.8),
                colsample_bytree=hp.get("colsample_bytree", 0.8),
                reg_alpha=hp.get("reg_alpha", 0.0),
                reg_lambda=hp.get("reg_lambda", 1.0),
                min_child_weight=hp.get("min_child_weight", 1),
                gamma=hp.get("gamma", 0.0),
                random_state=42,
            )
            if early_rounds > 0:
                common["early_stopping_rounds"] = early_rounds
            if is_classification:
                return xgb.XGBClassifier(
                    **common,
                    use_label_encoder=False,
                    eval_metric="logloss",
                )
            else:
                return xgb.XGBRegressor(**common)
        except ImportError:
            logger.warning("XGBoost not installed, falling back to GradientBoosting")
            model_type = "gradient_boosting"

    if model_type == "gradient_boosting":
        if is_classification:
            from sklearn.ensemble import GradientBoostingClassifier
            return GradientBoostingClassifier(
                n_estimators=hp.get("n_estimators", 100),
                max_depth=hp.get("max_depth", 5),
                learning_rate=hp.get("learning_rate", 0.1),
                random_state=42,
            )
        else:
            from sklearn.ensemble import GradientBoostingRegressor
            return GradientBoostingRegressor(
                n_estimators=hp.get("n_estimators", 100),
                max_depth=hp.get("max_depth", 5),
                learning_rate=hp.get("learning_rate", 0.1),
                random_state=42,
            )

    # Default fallback
    from sklearn.ensemble import RandomForestClassifier
    return RandomForestClassifier(n_estimators=100, random_state=42)


def _compute_metrics(y_true: list[float], y_pred, is_classification: bool) -> dict:
    """Compute evaluation metrics."""
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
    from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

    if is_classification:
        return {
            "accuracy": round(accuracy_score(y_true, y_pred), 4),
            "precision": round(precision_score(y_true, y_pred, zero_division=0), 4),
            "recall": round(recall_score(y_true, y_pred, zero_division=0), 4),
            "f1": round(f1_score(y_true, y_pred, zero_division=0), 4),
        }
    else:
        return {
            "mse": round(mean_squared_error(y_true, y_pred), 6),
            "mae": round(mean_absolute_error(y_true, y_pred), 6),
            "r2": round(r2_score(y_true, y_pred), 4),
        }


def _get_feature_importance(model, feature_names: list[str]) -> dict:
    """Extract feature importances from a trained model."""
    importance = {}
    if hasattr(model, "feature_importances_"):
        for name, imp in zip(feature_names, model.feature_importances_):
            importance[name] = round(float(imp), 6)
    # Sort by importance
    importance = dict(sorted(importance.items(), key=lambda x: -x[1]))
    return importance
