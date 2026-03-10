"""
RL Inference Agent — loads ONNX policy for lightweight Render deployment.

No gymnasium or stable-baselines3 required.
Uses only onnxruntime + numpy for inference.
"""

import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

ACTION_NAMES = {0: "wait", 1: "buy", 2: "sell", 3: "close", 4: "trail"}


class RLInferenceAgent:
    """
    Loads a trained RL policy (ONNX) and provides trading decisions.

    Lightweight — only needs onnxruntime and numpy.
    """

    def __init__(self, onnx_path: str, stats_path: Optional[str] = None):
        self.onnx_path = onnx_path
        self.stats_path = stats_path or onnx_path.replace(".onnx", "_stats.npz")
        self._session = None
        self._obs_mean = None
        self._obs_var = None
        self._clip_obs = 10.0
        self._loaded = False

    def load(self) -> bool:
        """Load ONNX model and normalization stats."""
        if not os.path.exists(self.onnx_path):
            logger.warning("[RLAgent] ONNX model not found: %s", self.onnx_path)
            return False

        try:
            import onnxruntime as ort
            self._session = ort.InferenceSession(self.onnx_path)

            # Load normalization stats
            if os.path.exists(self.stats_path):
                stats = np.load(self.stats_path)
                self._obs_mean = stats.get("obs_mean")
                self._obs_var = stats.get("obs_var")
                if "clip_obs" in stats:
                    self._clip_obs = float(stats["clip_obs"])
                logger.info("[RLAgent] Loaded normalization stats from %s", self.stats_path)

            self._loaded = True
            logger.info("[RLAgent] Loaded ONNX model: %s", self.onnx_path)
            return True

        except ImportError:
            logger.error("[RLAgent] onnxruntime not installed")
            return False
        except Exception as e:
            logger.error("[RLAgent] Failed to load: %s", e)
            return False

    def decide(
        self,
        features: np.ndarray,
        position_dir: int = 0,
        position_pnl: float = 0.0,
        unrealized_return: float = 0.0,
        drawdown: float = 0.0,
        bars_in_trade: int = 0,
        bars_since_close: int = 0,
        regime_id: int = 0,
        max_hold: int = 100,
    ) -> dict:
        """
        Get trading decision from RL policy.

        Args:
            features: Technical feature vector (from compute_features)
            position_dir: Current position direction (-1, 0, 1)
            position_pnl: Unrealized P&L as fraction of balance
            unrealized_return: Price change since entry
            drawdown: Current drawdown from peak
            bars_in_trade: Bars since entry
            bars_since_close: Bars since last close
            regime_id: Current regime (0-3)
            max_hold: Max bars to hold

        Returns:
            Dict with action, action_name, confidence, logits
        """
        if not self._loaded:
            return {"action": 0, "action_name": "wait", "confidence": 0.0}

        try:
            # Build context features (same order as env)
            context = np.array([
                float(regime_id),
                float(position_dir),
                position_pnl,
                unrealized_return,
                drawdown,
                min(bars_in_trade / max_hold, 1.0),
                min(bars_since_close / 50.0, 1.0),
            ], dtype=np.float32)

            obs = np.concatenate([features, context]).astype(np.float32)

            # Normalize
            if self._obs_mean is not None and self._obs_var is not None:
                obs = (obs - self._obs_mean) / np.sqrt(self._obs_var + 1e-8)
                obs = np.clip(obs, -self._clip_obs, self._clip_obs)

            # Run inference
            input_name = self._session.get_inputs()[0].name
            result = self._session.run(None, {input_name: obs.reshape(1, -1)})
            logits = result[0][0]

            # Softmax for probabilities
            exp_logits = np.exp(logits - np.max(logits))
            probs = exp_logits / exp_logits.sum()

            action = int(np.argmax(probs))
            confidence = float(probs[action])

            return {
                "action": action,
                "action_name": ACTION_NAMES.get(action, f"action_{action}"),
                "confidence": round(confidence, 4),
                "probabilities": {
                    ACTION_NAMES.get(i, f"a{i}"): round(float(p), 4)
                    for i, p in enumerate(probs)
                },
            }

        except Exception as e:
            logger.error("[RLAgent] Decision failed: %s", e)
            return {"action": 0, "action_name": "wait", "confidence": 0.0}
