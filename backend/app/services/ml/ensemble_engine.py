"""
Ensemble Signal Engine — combines multiple ML models for high-conviction trading.

Expert traders don't rely on a single indicator. This engine requires agreement
between multiple independent models before generating a signal:

  1. XGBoost classifier — direction prediction + probability
  2. LightGBM classifier — independent direction prediction
  3. LSTM forecaster — predicted return distribution

Voting rules:
  - Minimum 2/3 models must agree on direction
  - Combined confidence is the weighted average of agreeing models
  - Meta-labeler acts as final filter: "should I take this trade?"

This approach dramatically reduces false signals compared to single-model systems.
"""

import logging
import math
import os
import json
import numpy as np
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class EnsembleSignalEngine:
    """
    Multi-model ensemble for high-confidence trade signals.

    Each model votes independently. Only when sufficient agreement
    exists does the engine produce a signal.
    """

    def __init__(
        self,
        symbol: str,
        timeframe: str = "M5",
        model_dir: Optional[str] = None,
        min_agreement: int = 2,        # minimum models that must agree
        min_confidence: float = 0.55,   # minimum confidence threshold
        weights: Optional[dict] = None, # model weights for confidence blending
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.model_dir = model_dir or str(Path("data/ml_models"))
        self.min_agreement = min_agreement
        self.min_confidence = min_confidence
        self.weights = weights or {
            "xgboost": 0.40,
            "lightgbm": 0.35,
            "lstm": 0.25,
        }

        # Models loaded on first use
        self._xgb_model = None
        self._lgb_model = None
        self._lstm_session = None
        self._meta_model = None
        self._feature_names: list[str] = []
        self._lstm_scaler = None
        self._loaded = False

    def load_models(self) -> bool:
        """
        Load all ensemble models from disk.

        Expects files named:
          expert_{symbol}_{timeframe}_xgboost.joblib
          expert_{symbol}_{timeframe}_lightgbm.joblib
          expert_{symbol}_{timeframe}_lstm.onnx
          expert_{symbol}_{timeframe}_meta.joblib (optional)

        Returns True if at least 2 models loaded successfully.
        """
        if self._loaded:
            return True

        loaded_count = 0
        prefix = f"expert_{self.symbol}_{self.timeframe}"

        # XGBoost
        xgb_path = os.path.join(self.model_dir, f"{prefix}_xgboost.joblib")
        if os.path.exists(xgb_path):
            try:
                import joblib
                saved = joblib.load(xgb_path)
                self._xgb_model = saved["model"]
                self._feature_names = saved.get("feature_names", [])
                loaded_count += 1
                logger.info("[Ensemble] Loaded XGBoost model: %s", xgb_path)
            except Exception as e:
                logger.error("[Ensemble] Failed to load XGBoost: %s", e)

        # LightGBM
        lgb_path = os.path.join(self.model_dir, f"{prefix}_lightgbm.joblib")
        if os.path.exists(lgb_path):
            try:
                import joblib
                saved = joblib.load(lgb_path)
                self._lgb_model = saved["model"]
                if not self._feature_names:
                    self._feature_names = saved.get("feature_names", [])
                loaded_count += 1
                logger.info("[Ensemble] Loaded LightGBM model: %s", lgb_path)
            except Exception as e:
                logger.error("[Ensemble] Failed to load LightGBM: %s", e)

        # LSTM (ONNX)
        lstm_path = os.path.join(self.model_dir, f"{prefix}_lstm.onnx")
        if os.path.exists(lstm_path):
            try:
                import onnxruntime as ort
                self._lstm_session = ort.InferenceSession(lstm_path)
                # Load scaler if available
                scaler_path = os.path.join(self.model_dir, f"{prefix}_lstm_scaler.npz")
                if os.path.exists(scaler_path):
                    data = np.load(scaler_path)
                    self._lstm_scaler = {"mean": data["mean"], "std": data["std"]}
                loaded_count += 1
                logger.info("[Ensemble] Loaded LSTM model: %s", lstm_path)
            except Exception as e:
                logger.error("[Ensemble] Failed to load LSTM: %s", e)

        # Meta-labeler (optional)
        meta_path = os.path.join(self.model_dir, f"{prefix}_meta.joblib")
        if os.path.exists(meta_path):
            try:
                import joblib
                saved = joblib.load(meta_path)
                self._meta_model = saved["model"]
                logger.info("[Ensemble] Loaded meta-labeler: %s", meta_path)
            except Exception as e:
                logger.warning("[Ensemble] Meta-labeler not loaded: %s", e)

        self._loaded = loaded_count >= 2
        if self._loaded:
            logger.info("[Ensemble] %d/%d models loaded for %s %s",
                        loaded_count, 3, self.symbol, self.timeframe)
        else:
            logger.warning("[Ensemble] Only %d models loaded (need >=2) for %s %s",
                           loaded_count, self.symbol, self.timeframe)

        return self._loaded

    def predict(
        self,
        feature_vector: np.ndarray,
        feature_sequence: Optional[np.ndarray] = None,
    ) -> Optional[dict]:
        """
        Run ensemble prediction.

        Args:
            feature_vector: 1D array of features for the latest bar
                           (used by XGBoost and LightGBM)
            feature_sequence: 2D array (seq_len, n_features) for LSTM
                             (last N bars of features)

        Returns:
            Dict with:
                direction: int (1=bullish, -1=bearish, 0=no signal)
                confidence: float (0-1)
                agreement: int (how many models agree)
                votes: dict of individual model predictions
                meta_approved: bool (if meta-labeler approves)
                reason: str
            None if prediction fails.
        """
        if not self._loaded and not self.load_models():
            return None

        # Check for NaN in features
        if np.any(~np.isfinite(feature_vector)):
            return None

        votes = {}
        directions = []
        confidences = []

        # ── XGBoost vote ──
        if self._xgb_model is not None:
            try:
                xgb_pred = float(self._xgb_model.predict([feature_vector])[0])
                xgb_dir = 1 if xgb_pred >= 0.5 else -1
                xgb_conf = 0.5
                if hasattr(self._xgb_model, "predict_proba"):
                    proba = self._xgb_model.predict_proba([feature_vector])
                    xgb_conf = float(max(proba[0]))
                votes["xgboost"] = {"direction": xgb_dir, "confidence": xgb_conf}
                directions.append(xgb_dir)
                confidences.append(xgb_conf)
            except Exception as e:
                logger.warning("[Ensemble] XGBoost prediction failed: %s", e)

        # ── LightGBM vote ──
        if self._lgb_model is not None:
            try:
                lgb_pred = float(self._lgb_model.predict([feature_vector])[0])
                lgb_dir = 1 if lgb_pred >= 0.5 else -1
                lgb_conf = 0.5
                if hasattr(self._lgb_model, "predict_proba"):
                    proba = self._lgb_model.predict_proba([feature_vector])
                    lgb_conf = float(max(proba[0]))
                votes["lightgbm"] = {"direction": lgb_dir, "confidence": lgb_conf}
                directions.append(lgb_dir)
                confidences.append(lgb_conf)
            except Exception as e:
                logger.warning("[Ensemble] LightGBM prediction failed: %s", e)

        # ── LSTM vote ──
        if self._lstm_session is not None and feature_sequence is not None:
            try:
                seq = feature_sequence.astype(np.float32)
                if self._lstm_scaler:
                    seq = (seq - self._lstm_scaler["mean"]) / (self._lstm_scaler["std"] + 1e-8)
                # Add batch dimension: (1, seq_len, features)
                seq = seq.reshape(1, *seq.shape)
                input_name = self._lstm_session.get_inputs()[0].name
                result = self._lstm_session.run(None, {input_name: seq})
                # LSTM output: [predicted_return, predicted_std, pct_20, pct_80]
                lstm_return = float(result[0].flatten()[0])
                lstm_dir = 1 if lstm_return > 0 else -1
                # Confidence from distance of predicted return from zero
                lstm_conf = min(abs(lstm_return) * 50 + 0.5, 0.95)
                votes["lstm"] = {
                    "direction": lstm_dir,
                    "confidence": lstm_conf,
                    "predicted_return": lstm_return,
                }
                directions.append(lstm_dir)
                confidences.append(lstm_conf)
            except Exception as e:
                logger.warning("[Ensemble] LSTM prediction failed: %s", e)

        # ── Voting logic ──
        if len(directions) < 2:
            return {
                "direction": 0,
                "confidence": 0.0,
                "agreement": 0,
                "votes": votes,
                "meta_approved": False,
                "reason": f"Insufficient models for vote ({len(directions)}/2 minimum)",
            }

        # Count votes for each direction
        bull_votes = sum(1 for d in directions if d == 1)
        bear_votes = sum(1 for d in directions if d == -1)

        # Determine majority direction
        if bull_votes >= self.min_agreement:
            consensus_dir = 1
            agreement = bull_votes
        elif bear_votes >= self.min_agreement:
            consensus_dir = -1
            agreement = bear_votes
        else:
            return {
                "direction": 0,
                "confidence": 0.0,
                "agreement": max(bull_votes, bear_votes),
                "votes": votes,
                "meta_approved": False,
                "reason": f"No consensus: {bull_votes} bullish, {bear_votes} bearish (need {self.min_agreement})",
            }

        # Compute weighted confidence from agreeing models
        weighted_conf = 0.0
        total_weight = 0.0
        for model_name, vote in votes.items():
            if vote["direction"] == consensus_dir:
                w = self.weights.get(model_name, 0.33)
                weighted_conf += vote["confidence"] * w
                total_weight += w

        if total_weight > 0:
            combined_confidence = weighted_conf / total_weight
        else:
            combined_confidence = sum(confidences) / len(confidences)

        # Check minimum confidence threshold
        if combined_confidence < self.min_confidence:
            return {
                "direction": 0,
                "confidence": combined_confidence,
                "agreement": agreement,
                "votes": votes,
                "meta_approved": False,
                "reason": f"Confidence too low: {combined_confidence:.1%} < {self.min_confidence:.1%}",
            }

        # ── Meta-labeler filter ──
        meta_approved = True
        if self._meta_model is not None:
            try:
                # Meta model input: original features + primary prediction info
                meta_features = np.append(feature_vector, [
                    float(consensus_dir),
                    combined_confidence,
                    float(agreement) / len(directions),
                ])
                meta_pred = float(self._meta_model.predict([meta_features])[0])
                meta_approved = meta_pred >= 0.5

                if hasattr(self._meta_model, "predict_proba"):
                    meta_proba = self._meta_model.predict_proba([meta_features])
                    meta_conf = float(max(meta_proba[0]))
                    # Adjust confidence based on meta approval
                    if meta_approved:
                        combined_confidence *= meta_conf
                    else:
                        combined_confidence *= (1 - meta_conf)
            except Exception as e:
                logger.warning("[Ensemble] Meta-labeler failed: %s", e)
                meta_approved = True  # fail open

        if not meta_approved:
            return {
                "direction": 0,
                "confidence": combined_confidence,
                "agreement": agreement,
                "votes": votes,
                "meta_approved": False,
                "reason": "Meta-labeler rejected trade",
            }

        return {
            "direction": consensus_dir,
            "confidence": combined_confidence,
            "agreement": agreement,
            "votes": votes,
            "meta_approved": True,
            "reason": f"{agreement}/{len(directions)} models agree ({'BUY' if consensus_dir == 1 else 'SELL'}, conf={combined_confidence:.1%})",
        }

    def get_feature_names(self) -> list[str]:
        """Return the feature names expected by the ensemble models."""
        return self._feature_names

    def get_status(self) -> dict:
        """Return current ensemble status for monitoring."""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "loaded": self._loaded,
            "models": {
                "xgboost": self._xgb_model is not None,
                "lightgbm": self._lgb_model is not None,
                "lstm": self._lstm_session is not None,
                "meta_labeler": self._meta_model is not None,
            },
            "min_agreement": self.min_agreement,
            "min_confidence": self.min_confidence,
            "weights": self.weights,
        }
