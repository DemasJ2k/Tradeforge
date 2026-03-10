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
from app.services.ml.features import compute_features, compute_targets, clean_data, apply_rolling_zscore

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

        # Extract OHLCV + timestamps
        opens = [d["open"] for d in ohlcv_data]
        highs = [d["high"] for d in ohlcv_data]
        lows = [d["low"] for d in ohlcv_data]
        closes = [d["close"] for d in ohlcv_data]
        volumes = [d.get("volume", 0) for d in ohlcv_data]
        timestamps = [d.get("datetime") for d in ohlcv_data]
        if all(t is None for t in timestamps):
            timestamps = None

        # Compute features
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

        # Compute targets
        target_name, targets = compute_targets(closes, target_config, highs=highs, lows=lows)

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

        # Early stopping for gradient boosting models
        early_rounds = hp.get("early_stopping_rounds", 0)
        if early_rounds > 0 and model_type in ("xgboost", "lightgbm"):
            try:
                model.fit(
                    X_train, y_train,
                    eval_set=[(X_val, y_val)],
                    verbose=False,
                )
            except Exception:
                model.fit(X_train, y_train)
        elif early_rounds > 0 and model_type == "catboost":
            try:
                model.fit(
                    X_train, y_train,
                    eval_set=(X_val, y_val),
                    early_stopping_rounds=early_rounds,
                    verbose=False,
                )
            except Exception:
                model.fit(X_train, y_train)
        else:
            model.fit(X_train, y_train)

        # Evaluate
        train_pred = model.predict(X_train)
        val_pred = model.predict(X_val)

        is_classification = (target_config or {}).get("type", "direction") in ("direction", "triple_barrier")

        # Split closes for financial metrics
        c_train = closes[split_idx:split_idx + len(y_train)] if len(closes) > split_idx else None
        c_val = closes[split_idx:split_idx + len(y_val)] if len(closes) > split_idx else None

        train_metrics = _compute_metrics(y_train, train_pred, is_classification, c_train)
        val_metrics = _compute_metrics(y_val, val_pred, is_classification, c_val)

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
    def train_with_optuna(
        ohlcv_data: list[dict],
        model_type: str = "lightgbm",
        features_config: Optional[dict] = None,
        target_config: Optional[dict] = None,
        model_id: int = 0,
        n_trials: int = 50,
        timeout: int = 600,
        cv_method: str = "walk_forward",
        n_folds: int = 3,
    ) -> dict:
        """
        Train with Optuna hyperparameter auto-tuning.

        Uses TPE sampler to search over model hyperparameters.
        Each trial evaluates via walk-forward CV or purged k-fold.

        Returns same dict as train_model() with extra optuna results.
        """
        import joblib
        import numpy as np
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)

        n = len(ohlcv_data)
        if n < 200:
            raise ValueError(f"Need at least 200 bars for Optuna tuning, got {n}")

        # Prepare data once
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
            raise ValueError("No features computed")

        normalize = (features_config or {}).get("normalize", "none")
        if normalize == "zscore" and feature_matrix:
            zscore_window = (features_config or {}).get("zscore_window", 50)
            feature_matrix = apply_rolling_zscore(feature_matrix, window=zscore_window)

        target_name, targets = compute_targets(closes, target_config, highs=highs, lows=lows)
        feature_names, X, y = clean_data(feature_names, feature_matrix, targets)

        if len(X) < 100:
            raise ValueError(f"Not enough valid samples after cleaning: {len(X)}")

        is_classification = (target_config or {}).get("type", "direction") in ("direction", "triple_barrier")

        def _get_param_space(trial, mt):
            """Define Optuna search space per model type."""
            common = {
                "n_estimators": trial.suggest_int("n_estimators", 50, 500),
                "max_depth": trial.suggest_int("max_depth", 3, 12),
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            }
            if mt in ("xgboost", "lightgbm", "catboost"):
                common["subsample"] = trial.suggest_float("subsample", 0.6, 1.0)
                common["colsample_bytree"] = trial.suggest_float("colsample_bytree", 0.6, 1.0)
                common["reg_alpha"] = trial.suggest_float("reg_alpha", 1e-8, 5.0, log=True)
                common["reg_lambda"] = trial.suggest_float("reg_lambda", 1e-8, 5.0, log=True)
                common["min_child_weight"] = trial.suggest_int("min_child_weight", 1, 10)
            if mt == "random_forest":
                common["min_samples_split"] = trial.suggest_int("min_samples_split", 2, 20)
                common["min_samples_leaf"] = trial.suggest_int("min_samples_leaf", 1, 10)
            return common

        def _cv_score(hp_dict):
            """Evaluate hyperparams via walk-forward CV."""
            segment_size = len(X) // (n_folds + 1)
            fold_scores = []

            for fold in range(n_folds):
                train_end = segment_size * (fold + 1)
                val_start = train_end
                val_end = min(train_end + segment_size, len(X))

                if val_end <= val_start or train_end < 50:
                    continue

                X_tr, y_tr = X[:train_end], y[:train_end]
                X_vl, y_vl = X[val_start:val_end], y[val_start:val_end]

                mdl = _build_model(model_type, hp_dict, target_config)
                try:
                    if model_type in ("xgboost", "lightgbm"):
                        mdl.fit(X_tr, y_tr, eval_set=[(X_vl, y_vl)], verbose=False)
                    elif model_type == "catboost":
                        mdl.fit(X_tr, y_tr, eval_set=(X_vl, y_vl), verbose=False)
                    else:
                        mdl.fit(X_tr, y_tr)
                except Exception:
                    mdl.fit(X_tr, y_tr)

                pred = mdl.predict(X_vl)
                if is_classification:
                    from sklearn.metrics import accuracy_score
                    fold_scores.append(accuracy_score(y_vl, pred))
                else:
                    from sklearn.metrics import r2_score
                    fold_scores.append(r2_score(y_vl, pred))

            return float(np.mean(fold_scores)) if fold_scores else 0.0

        def objective(trial):
            hp_dict = _get_param_space(trial, model_type)
            score = _cv_score(hp_dict)

            # Pruning for early stopping
            trial.report(score, 0)
            if trial.should_prune():
                raise optuna.TrialPruned()

            return score

        # Run Optuna study
        study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=42),
            pruner=optuna.pruners.MedianPruner(n_startup_trials=5),
        )
        study.optimize(objective, n_trials=n_trials, timeout=timeout, show_progress_bar=False)

        best_params = study.best_params
        best_value = study.best_value

        logger.info(
            "Optuna done: %d trials, best_score=%.4f, best_params=%s",
            len(study.trials), best_value, best_params,
        )

        # Compute param importances
        try:
            from optuna.importance import get_param_importances
            param_importances = get_param_importances(study)
            param_importances = {k: round(v, 4) for k, v in param_importances.items()}
        except Exception:
            param_importances = {}

        # Train final model with best params on 80% holdout
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]

        final_model = _build_model(model_type, best_params, target_config)
        try:
            if model_type in ("xgboost", "lightgbm"):
                final_model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
            elif model_type == "catboost":
                final_model.fit(X_train, y_train, eval_set=(X_val, y_val), verbose=False)
            else:
                final_model.fit(X_train, y_train)
        except Exception:
            final_model.fit(X_train, y_train)

        train_pred = final_model.predict(X_train)
        val_pred = final_model.predict(X_val)

        c_train = closes[split_idx:split_idx + len(y_train)] if len(closes) > split_idx else None
        c_val = closes[split_idx:split_idx + len(y_val)] if len(closes) > split_idx else None

        train_metrics = _compute_metrics(y_train, train_pred, is_classification, c_train)
        val_metrics = _compute_metrics(y_val, val_pred, is_classification, c_val)
        importance = _get_feature_importance(final_model, feature_names)

        # Embed Optuna results into val_metrics
        val_metrics["optuna"] = {
            "best_params": best_params,
            "best_value": round(best_value, 4),
            "n_trials": len(study.trials),
            "param_importances": param_importances,
        }

        # Save model
        model_path = str(_MODEL_DIR / f"model_{model_id}.joblib")
        joblib.dump({
            "model": final_model,
            "feature_names": feature_names,
            "target_name": target_name,
            "model_type": model_type,
            "optuna_best_params": best_params,
        }, model_path)

        logger.info(
            "Optuna model %d trained: val_acc=%.3f, best_optuna=%.3f",
            model_id, val_metrics.get("accuracy", 0), best_value,
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
        timestamps = [d.get("datetime") for d in ohlcv_data]
        if all(t is None for t in timestamps):
            timestamps = None

        feature_names, feature_matrix = compute_features(
            opens, highs, lows, closes, volumes, features_config,
            timestamps=timestamps,
        )
        if not feature_names:
            raise ValueError("No features computed")

        # Optional rolling Z-score normalization
        normalize = (features_config or {}).get("normalize", "none")
        if normalize == "zscore" and feature_matrix:
            zscore_window = (features_config or {}).get("zscore_window", 50)
            feature_matrix = apply_rolling_zscore(feature_matrix, window=zscore_window)

        target_name, targets = compute_targets(closes, target_config, highs=highs, lows=lows)
        feature_names, X, y = clean_data(feature_names, feature_matrix, targets)

        if len(X) < 100:
            raise ValueError(f"Not enough valid samples: {len(X)}")

        is_classification = (target_config or {}).get("type", "direction") in ("direction", "triple_barrier")

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
            if early_rounds > 0 and model_type in ("xgboost", "lightgbm"):
                try:
                    model.fit(X_train_f, y_train_f, eval_set=[(X_val_f, y_val_f)], verbose=False)
                except Exception:
                    model.fit(X_train_f, y_train_f)
            elif early_rounds > 0 and model_type == "catboost":
                try:
                    model.fit(X_train_f, y_train_f, eval_set=(X_val_f, y_val_f), early_stopping_rounds=early_rounds, verbose=False)
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
        if early_rounds > 0 and model_type in ("xgboost", "lightgbm"):
            try:
                final_model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
            except Exception:
                final_model.fit(X_train, y_train)
        elif early_rounds > 0 and model_type == "catboost":
            try:
                final_model.fit(X_train, y_train, eval_set=(X_val, y_val), early_stopping_rounds=early_rounds, verbose=False)
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
    def train_purged_kfold(
        ohlcv_data: list[dict],
        model_type: str = "lightgbm",
        features_config: Optional[dict] = None,
        target_config: Optional[dict] = None,
        hyperparams: Optional[dict] = None,
        model_id: int = 0,
        n_folds: int = 5,
        embargo_pct: float = 0.02,
    ) -> dict:
        """
        Train with purged k-fold cross-validation (financial ML best practice).

        Purging: removes training samples whose target labels overlap with
        the test fold's time range (prevents label leakage).
        Embargo: adds a gap between train and test sets (prevents feature leakage
        from rolling indicators).

        Final model trained on 80% with standard holdout for deployment.
        """
        import joblib
        import numpy as np

        hp = hyperparams or {}
        n = len(ohlcv_data)
        if n < 200:
            raise ValueError(f"Need at least 200 bars for purged k-fold, got {n}")

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
            raise ValueError("No features computed")

        # Optional rolling Z-score normalization
        normalize = (features_config or {}).get("normalize", "none")
        if normalize == "zscore" and feature_matrix:
            from app.services.ml.features import apply_rolling_zscore
            zscore_window = (features_config or {}).get("zscore_window", 50)
            feature_matrix = apply_rolling_zscore(feature_matrix, window=zscore_window)

        target_name, targets = compute_targets(closes, target_config, highs=highs, lows=lows)
        feature_names, X, y = clean_data(feature_names, feature_matrix, targets)

        if len(X) < 100:
            raise ValueError(f"Not enough valid samples: {len(X)}")

        is_classification = (target_config or {}).get("type", "direction") in ("direction", "triple_barrier")
        horizon = (target_config or {}).get("horizon", 1)
        embargo_size = max(1, int(len(X) * embargo_pct))

        X_arr = np.array(X)
        y_arr = np.array(y)

        # Purged k-fold splits
        fold_size = len(X_arr) // n_folds
        fold_metrics = []

        for fold in range(n_folds):
            test_start = fold * fold_size
            test_end = min(test_start + fold_size, len(X_arr))

            # Purge: remove training samples whose target horizon overlaps test
            purge_start = max(0, test_start - horizon)
            purge_end = min(len(X_arr), test_end + horizon)

            # Embargo: gap after test set
            embargo_end = min(len(X_arr), test_end + embargo_size)

            # Build train indices: everything except purged zone + embargo zone
            train_mask = np.ones(len(X_arr), dtype=bool)
            train_mask[purge_start:embargo_end] = False

            if np.sum(train_mask) < 50 or (test_end - test_start) < 10:
                continue

            X_train_f = X_arr[train_mask]
            y_train_f = y_arr[train_mask]
            X_test_f = X_arr[test_start:test_end]
            y_test_f = y_arr[test_start:test_end]

            model = _build_model(model_type, hp, target_config)

            early_rounds = hp.get("early_stopping_rounds", 0)
            if early_rounds > 0 and model_type in ("xgboost", "lightgbm"):
                try:
                    model.fit(X_train_f, y_train_f, eval_set=[(X_test_f, y_test_f)], verbose=False)
                except Exception:
                    model.fit(X_train_f, y_train_f)
            elif early_rounds > 0 and model_type == "catboost":
                try:
                    model.fit(X_train_f, y_train_f, eval_set=(X_test_f, y_test_f),
                              early_stopping_rounds=early_rounds, verbose=False)
                except Exception:
                    model.fit(X_train_f, y_train_f)
            else:
                model.fit(X_train_f, y_train_f)

            test_pred = model.predict(X_test_f)
            metrics = _compute_metrics(y_test_f.tolist(), test_pred, is_classification)
            metrics["fold"] = fold + 1
            metrics["n_train"] = int(np.sum(train_mask))
            metrics["n_test"] = test_end - test_start
            metrics["n_purged"] = int(purge_end - purge_start - (test_end - test_start))
            fold_metrics.append(metrics)

            logger.info(
                "Purged KF Fold %d: train=%d (purged=%d), test=%d, acc=%.4f",
                fold + 1, int(np.sum(train_mask)),
                metrics["n_purged"], test_end - test_start,
                metrics.get("accuracy", metrics.get("r2", 0)),
            )

        # Train final model on 80%
        split_idx = int(len(X_arr) * 0.8)
        X_train, X_val = X_arr[:split_idx], X_arr[split_idx:]
        y_train, y_val = y_arr[:split_idx], y_arr[split_idx:]

        final_model = _build_model(model_type, hp, target_config)
        early_rounds = hp.get("early_stopping_rounds", 0)
        if early_rounds > 0 and model_type in ("xgboost", "lightgbm"):
            try:
                final_model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
            except Exception:
                final_model.fit(X_train, y_train)
        elif early_rounds > 0 and model_type == "catboost":
            try:
                final_model.fit(X_train, y_train, eval_set=(X_val, y_val),
                                early_stopping_rounds=early_rounds, verbose=False)
            except Exception:
                final_model.fit(X_train, y_train)
        else:
            final_model.fit(X_train, y_train)

        train_pred = final_model.predict(X_train)
        val_pred = final_model.predict(X_val)
        c_val = closes[split_idx:split_idx + len(y_val)]
        train_metrics = _compute_metrics(y_train.tolist(), train_pred, is_classification)
        val_metrics = _compute_metrics(y_val.tolist(), val_pred, is_classification, c_val)
        importance = _get_feature_importance(final_model, feature_names)

        # Aggregate fold metrics
        if fold_metrics and is_classification:
            pkf_avg_acc = sum(m.get("accuracy", 0) for m in fold_metrics) / len(fold_metrics)
            pkf_std_acc = (
                sum((m.get("accuracy", 0) - pkf_avg_acc) ** 2 for m in fold_metrics)
                / len(fold_metrics)
            ) ** 0.5
        else:
            pkf_avg_acc = 0
            pkf_std_acc = 0

        model_path = str(_MODEL_DIR / f"model_{model_id}.joblib")
        joblib.dump({
            "model": final_model,
            "feature_names": feature_names,
            "target_name": target_name,
            "model_type": model_type,
        }, model_path)

        logger.info(
            "Purged KF Model %d: avg_cv_acc=%.4f (std=%.4f), final_val_acc=%.4f",
            model_id, pkf_avg_acc, pkf_std_acc,
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
            "purged_kfold": {
                "n_folds": len(fold_metrics),
                "fold_metrics": fold_metrics,
                "avg_accuracy": round(pkf_avg_acc, 4),
                "std_accuracy": round(pkf_std_acc, 4),
                "embargo_pct": embargo_pct,
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
        scaler = saved.get("scaler")  # Level 3 models may have a scaler

        opens = [d["open"] for d in ohlcv_data]
        highs = [d["high"] for d in ohlcv_data]
        lows = [d["low"] for d in ohlcv_data]
        closes = [d["close"] for d in ohlcv_data]
        volumes = [d.get("volume", 0) for d in ohlcv_data]
        timestamps = [d.get("datetime") for d in ohlcv_data]
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

        results = []
        for i, row in enumerate(feature_matrix):
            if any(math.isnan(v) for v in row):
                continue

            # Apply scaler if model was trained with one (Level 3 models)
            pred_row = row
            if scaler is not None:
                pred_row = list(scaler.transform([row])[0])

            pred = float(model.predict([pred_row])[0])
            # Get prediction probability if available
            confidence = 0.5
            if hasattr(model, "predict_proba"):
                proba = model.predict_proba([pred_row])
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

        target_name, targets = compute_targets(closes, target_config, highs=highs, lows=lows)
        feature_names, X, y = clean_data(feature_names, feature_matrix, targets)

        if len(X) < 50:
            raise ValueError(f"Not enough valid samples after cleaning: {len(X)}")

        logger.info("Level 3 training (%s): %d samples, %d features", sub_type, len(X), len(feature_names))

        if sub_type == "lstm":
            # LSTM redirects to ensemble (not viable on 2GB server, inferior to trees on tabular data)
            logger.info("LSTM requested — redirecting to stacked ensemble")
            sub_type = "ensemble"

        if sub_type == "ensemble" or True:  # Always ensemble now
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
        """
        LSTM is not viable on 2GB Render — always falls back to ensemble.
        Kept for backward compatibility but immediately redirects.
        """
        logger.warning("LSTM not supported (requires TensorFlow + GPU). Using stacked ensemble instead.")
        model, scaler, val_accuracy, train_accuracy, meta = MLTrainer._train_ensemble(
            X, y, feature_names
        )
        meta["sub_type"] = "ensemble"
        meta["note"] = "LSTM requested but redirected to ensemble (no TensorFlow on server)"
        return model, scaler, val_accuracy, meta

    @staticmethod
    def _train_ensemble(X, y, feature_names):
        """Train stacked ensemble: RandomForest + XGBoost + LogisticRegression."""
        import numpy as np
        from sklearn.ensemble import RandomForestClassifier, StackingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.metrics import accuracy_score

        try:
            from xgboost import XGBClassifier
            xgb_est = XGBClassifier(
                n_estimators=100, max_depth=4, learning_rate=0.1,
                use_label_encoder=False, eval_metric='logloss', random_state=42
            )
        except ImportError:
            from sklearn.ensemble import GradientBoostingClassifier
            xgb_est = GradientBoostingClassifier(n_estimators=100, max_depth=4, random_state=42)

        y_arr = y.values if hasattr(y, "values") else list(y)

        # Chronological split (time-series aware — no shuffling)
        split_idx = int(len(X) * 0.8)
        X_train_raw, X_val_raw = X[:split_idx], X[split_idx:]
        y_train, y_val = y_arr[:split_idx], y_arr[split_idx:]

        # Fit scaler on training data only, then transform both
        scaler = StandardScaler()
        X_train = scaler.fit_transform(X_train_raw)
        X_val = scaler.transform(X_val_raw)

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
    is_classification = (target_config or {}).get("type", "direction") in ("direction", "triple_barrier")

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

    elif model_type == "lightgbm":
        try:
            import lightgbm as lgb
            common = dict(
                n_estimators=hp.get("n_estimators", 200),
                max_depth=hp.get("max_depth", 6),
                learning_rate=hp.get("learning_rate", 0.1),
                subsample=hp.get("subsample", 0.8),
                colsample_bytree=hp.get("colsample_bytree", 0.8),
                reg_alpha=hp.get("reg_alpha", 0.0),
                reg_lambda=hp.get("reg_lambda", 1.0),
                min_child_weight=hp.get("min_child_weight", 1),
                random_state=42,
                n_jobs=-1,
                verbose=-1,
            )
            if is_classification:
                return lgb.LGBMClassifier(**common)
            else:
                return lgb.LGBMRegressor(**common)
        except ImportError:
            logger.warning("LightGBM not installed, falling back to GradientBoosting")
            model_type = "gradient_boosting"

    elif model_type == "catboost":
        try:
            from catboost import CatBoostClassifier, CatBoostRegressor
            common = dict(
                iterations=hp.get("n_estimators", 200),
                depth=hp.get("max_depth", 6),
                learning_rate=hp.get("learning_rate", 0.1),
                l2_leaf_reg=hp.get("reg_lambda", 3.0),
                random_seed=42,
                verbose=0,
                thread_count=-1,
            )
            if is_classification:
                return CatBoostClassifier(**common)
            else:
                return CatBoostRegressor(**common)
        except ImportError:
            logger.warning("CatBoost not installed, falling back to GradientBoosting")
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


def _compute_metrics(
    y_true: list[float],
    y_pred,
    is_classification: bool,
    closes: Optional[list[float]] = None,
) -> dict:
    """Compute evaluation metrics, including financial metrics when closes are provided."""
    import numpy as np
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
    from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

    if is_classification:
        # Use weighted average for multiclass (e.g. triple barrier: 0, 0.5, 1)
        avg = "weighted" if len(set(y_true)) > 2 else "binary"
        metrics = {
            "accuracy": round(accuracy_score(y_true, y_pred), 4),
            "precision": round(precision_score(y_true, y_pred, zero_division=0, average=avg), 4),
            "recall": round(recall_score(y_true, y_pred, zero_division=0, average=avg), 4),
            "f1": round(f1_score(y_true, y_pred, zero_division=0, average=avg), 4),
        }
    else:
        metrics = {
            "mse": round(mean_squared_error(y_true, y_pred), 6),
            "mae": round(mean_absolute_error(y_true, y_pred), 6),
            "r2": round(r2_score(y_true, y_pred), 4),
        }

    # Financial metrics (when close prices available)
    if closes is not None and len(closes) == len(y_pred):
        fin = _compute_financial_metrics(y_true, y_pred, closes, is_classification)
        metrics.update(fin)

    return metrics


def _compute_financial_metrics(
    y_true: list[float],
    y_pred,
    closes: list[float],
    is_classification: bool,
) -> dict:
    """Compute Sharpe ratio, profit factor, and max drawdown from predicted signals."""
    import numpy as np

    c = np.array(closes, dtype=np.float64)
    yt = np.array(y_true, dtype=np.float64)
    yp = np.array(y_pred, dtype=np.float64)

    # Compute per-bar returns
    if len(c) < 2:
        return {}

    bar_returns = np.zeros(len(c))
    bar_returns[1:] = (c[1:] - c[:-1]) / np.where(c[:-1] != 0, c[:-1], 1.0)

    # Signal returns: go long when pred=1, stay out (or short) when pred=0
    if is_classification:
        signals = np.where(yp >= 0.5, 1.0, -1.0)
    else:
        signals = np.sign(yp)

    # Use lagged signals (predict at bar i, get return at bar i+1)
    # But since our y_pred is already aligned to the future return, use directly
    signal_returns = signals * bar_returns

    # Skip first bar (no return) and any NaN
    sr = signal_returns[1:]
    sr = sr[np.isfinite(sr)]

    if len(sr) < 10:
        return {}

    # Sharpe ratio (annualized, assume 252 trading days for daily-like frequency)
    mean_r = np.mean(sr)
    std_r = np.std(sr, ddof=1) if np.std(sr) > 1e-12 else 1e-12
    sharpe = round(float(mean_r / std_r * np.sqrt(252)), 4)

    # Profit factor (gross profit / gross loss)
    gross_profit = float(np.sum(sr[sr > 0])) if np.any(sr > 0) else 0.0
    gross_loss = float(np.abs(np.sum(sr[sr < 0]))) if np.any(sr < 0) else 0.001
    profit_factor = round(gross_profit / gross_loss, 4)

    # Max drawdown of equity curve
    equity = np.cumsum(sr)
    peak = np.maximum.accumulate(equity)
    drawdown = peak - equity
    max_dd = round(float(np.max(drawdown)) if len(drawdown) > 0 else 0.0, 4)

    return {
        "sharpe_ratio": sharpe,
        "profit_factor": profit_factor,
        "max_drawdown": max_dd,
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
