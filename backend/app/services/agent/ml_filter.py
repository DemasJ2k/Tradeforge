"""
ML Signal Filter — uses a trained ML model to filter/enhance strategy signals.

When attached to an agent, the ML model provides an additional confidence score
and directional prediction that the agent uses to:
  1. Confirm strategy signals (ML agrees → boost confidence)
  2. Filter out weak signals (ML disagrees → reduce confidence or skip)
  3. Adjust position sizing based on combined confidence

Integration modes:
  - "filter":  Skip trades where ML disagrees with strategy direction
  - "enhance": Adjust confidence score (weighted avg of strategy + ML confidence)
  - "veto":    Only trade when BOTH strategy and ML agree
"""

import logging
import math
import os
from typing import Optional

logger = logging.getLogger(__name__)


class MLSignalFilter:
    """
    Loads a trained ML model and provides real-time prediction filtering.

    Usage:
        ml_filter = MLSignalFilter(model_path, features_config)
        result = ml_filter.predict(bars)
        # result.direction = 1 or -1
        # result.confidence = 0.0 - 1.0
    """

    def __init__(
        self,
        model_path: str,
        features_config: Optional[dict] = None,
        target_config: Optional[dict] = None,
        mode: str = "enhance",
    ):
        self.model_path = model_path
        self.features_config = features_config or {}
        self.target_config = target_config or {}
        self.mode = mode  # filter | enhance | veto
        self._model = None
        self._scaler = None
        self._feature_names: list[str] = []
        self._loaded = False
        # Meta-labeling support
        self._is_meta_model = False
        self._primary_model = None
        self._primary_scaler = None
        self._primary_model_path: Optional[str] = None

    def load(self) -> bool:
        """Load the model from disk. Returns True if successful."""
        if self._loaded:
            return True

        if not self.model_path or not os.path.exists(self.model_path):
            logger.warning("[MLFilter] Model not found: %s", self.model_path)
            return False

        try:
            import joblib
            saved = joblib.load(self.model_path)
            self._model = saved["model"]
            self._feature_names = saved["feature_names"]
            self._scaler = saved.get("scaler")  # Level 3 models have a scaler
            # Detect meta-labeling model
            self._is_meta_model = saved.get("is_meta_model", False)
            if self._is_meta_model:
                self._primary_model = saved.get("primary_model")
                self._primary_scaler = saved.get("primary_scaler")
                self._primary_model_path = saved.get("primary_model_path")
                logger.info("[MLFilter] Loaded META-LABELING model from %s", self.model_path)
            self._loaded = True
            logger.info(
                "[MLFilter] Loaded model from %s (%d features, meta=%s)",
                self.model_path, len(self._feature_names), self._is_meta_model,
            )
            return True
        except Exception as e:
            logger.error("[MLFilter] Failed to load model: %s", e)
            return False

    def predict(self, bars: list[dict]) -> Optional[dict]:
        """
        Run ML prediction on the latest bars.

        Args:
            bars: List of bar dicts with keys: open, high, low, close, volume

        Returns:
            Dict with: direction (1/-1), confidence (0-1), raw_prediction, features_used
            None if prediction fails.
        """
        if not self._loaded and not self.load():
            return None

        if not bars or len(bars) < 50:
            return None

        try:
            # Meta-labeling: use two-stage prediction
            if self._is_meta_model:
                return self._predict_meta(bars)

            from app.services.ml.features import compute_features

            opens = [b["open"] for b in bars]
            highs = [b["high"] for b in bars]
            lows = [b["low"] for b in bars]
            closes = [b["close"] for b in bars]
            volumes = [b.get("volume", 0) for b in bars]
            timestamps = [b.get("datetime") for b in bars]
            if all(t is None for t in timestamps):
                timestamps = None

            _, feature_matrix = compute_features(
                opens, highs, lows, closes, volumes, self.features_config,
                timestamps=timestamps,
            )

            # Apply rolling Z-score if configured
            normalize = self.features_config.get("normalize", "none")
            if normalize == "zscore" and feature_matrix:
                from app.services.ml.features import apply_rolling_zscore
                zscore_window = self.features_config.get("zscore_window", 50)
                feature_matrix = apply_rolling_zscore(feature_matrix, window=zscore_window)

            if not feature_matrix:
                return None

            # Use the last row (most recent bar)
            last_row = feature_matrix[-1]

            # Check for NaN
            if any(math.isnan(v) for v in last_row):
                return None

            # Apply scaler if model was trained with one (Level 3 models)
            if self._scaler is not None:
                last_row = list(self._scaler.transform([last_row])[0])

            # Make prediction
            raw_pred = float(self._model.predict([last_row])[0])

            # Get confidence from predict_proba if available
            confidence = 0.5
            if hasattr(self._model, "predict_proba"):
                proba = self._model.predict_proba([last_row])
                confidence = float(max(proba[0]))

            # Determine direction
            target_type = self.target_config.get("type", "direction")
            if target_type == "direction":
                direction = 1 if raw_pred >= 0.5 else -1
            elif target_type == "return":
                direction = 1 if raw_pred > 0 else -1
            else:
                # volatility or other — neutral
                direction = 0

            return {
                "direction": direction,
                "confidence": confidence,
                "raw_prediction": raw_pred,
            }

        except Exception as e:
            logger.error("[MLFilter] Prediction failed: %s", e)
            return None

    def _predict_meta(self, bars: list[dict]) -> Optional[dict]:
        """Two-stage meta-labeling prediction."""
        try:
            from app.services.ml.meta_labeler import predict_with_meta

            result = predict_with_meta(
                primary_model_path=self._primary_model_path or "",
                meta_model_path=self.model_path,
                bars=bars,
                features_config=self.features_config,
                target_config=self.target_config,
            )
            if result is None:
                return None

            # If meta says "don't trade", return direction 0 with low confidence
            if not result["should_trade"]:
                return {
                    "direction": 0,
                    "confidence": 0.1,
                    "raw_prediction": result["primary_prediction"],
                    "meta_filtered": True,
                    "meta_confidence": result["meta_confidence"],
                }

            return {
                "direction": result["direction"],
                "confidence": result["confidence"] * result["meta_confidence"],
                "raw_prediction": result["primary_prediction"],
                "meta_filtered": False,
                "meta_confidence": result["meta_confidence"],
            }

        except Exception as e:
            logger.error("[MLFilter] Meta prediction failed: %s", e)
            return None

    def evaluate_signal(
        self,
        strategy_direction: int,
        strategy_confidence: float,
        bars: list[dict],
    ) -> dict:
        """
        Evaluate a strategy signal against the ML model prediction.

        Args:
            strategy_direction: 1 (bullish) or -1 (bearish)
            strategy_confidence: Strategy's confidence score (0-1)
            bars: Recent bars for ML prediction

        Returns:
            Dict with:
              - approved: bool (whether to proceed with the trade)
              - combined_confidence: float (blended confidence score)
              - ml_direction: int (ML model's predicted direction)
              - ml_confidence: float (ML model's confidence)
              - reason: str (explanation)
        """
        ml_pred = self.predict(bars)

        # If ML prediction fails, fall back to strategy-only
        if ml_pred is None:
            return {
                "approved": True,
                "combined_confidence": strategy_confidence,
                "ml_direction": 0,
                "ml_confidence": 0.0,
                "reason": "ML prediction unavailable, using strategy signal only",
            }

        # Meta-labeling: if meta model filtered out the trade, veto it
        if ml_pred.get("meta_filtered"):
            return {
                "approved": False,
                "combined_confidence": 0.0,
                "ml_direction": 0,
                "ml_confidence": ml_pred.get("meta_confidence", 0),
                "reason": f"Meta model filtered trade (meta_conf={ml_pred.get('meta_confidence', 0):.1%})",
            }

        ml_dir = ml_pred["direction"]
        ml_conf = ml_pred["confidence"]
        agrees = (ml_dir == strategy_direction)

        if self.mode == "veto":
            # Both must agree
            if agrees:
                combined = 0.6 * strategy_confidence + 0.4 * ml_conf
                return {
                    "approved": True,
                    "combined_confidence": combined,
                    "ml_direction": ml_dir,
                    "ml_confidence": ml_conf,
                    "reason": f"Strategy + ML agree (ML conf={ml_conf:.1%})",
                }
            else:
                return {
                    "approved": False,
                    "combined_confidence": 0.0,
                    "ml_direction": ml_dir,
                    "ml_confidence": ml_conf,
                    "reason": f"ML disagrees (pred={ml_dir}, conf={ml_conf:.1%})",
                }

        elif self.mode == "filter":
            # Skip only when ML strongly disagrees
            if not agrees and ml_conf > 0.55:
                return {
                    "approved": False,
                    "combined_confidence": 0.0,
                    "ml_direction": ml_dir,
                    "ml_confidence": ml_conf,
                    "reason": f"ML strongly disagrees (pred={ml_dir}, conf={ml_conf:.1%})",
                }
            combined = strategy_confidence if agrees else strategy_confidence * 0.8
            return {
                "approved": True,
                "combined_confidence": combined,
                "ml_direction": ml_dir,
                "ml_confidence": ml_conf,
                "reason": f"ML {'agrees' if agrees else 'weakly disagrees'} (conf={ml_conf:.1%})",
            }

        else:  # "enhance" (default)
            # Blend confidences, always proceed
            if agrees:
                combined = 0.6 * strategy_confidence + 0.4 * ml_conf
            else:
                combined = strategy_confidence * 0.7  # Penalize slightly
            return {
                "approved": True,
                "combined_confidence": combined,
                "ml_direction": ml_dir,
                "ml_confidence": ml_conf,
                "reason": f"ML {'confirms' if agrees else 'disagrees'} (conf={ml_conf:.1%})",
            }
