"""
HMM Regime Detection.

Uses Hidden Markov Model with Gaussian emissions to classify market regime
into 4 states: trending_up, trending_down, ranging, volatile.

Observation vector: 1-bar return, 5-bar volatility, ATR(14)/price, autocorrelation(20).
"""

import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)

# Regime labels
REGIME_NAMES = {
    0: "trending_up",
    1: "trending_down",
    2: "ranging",
    3: "volatile",
}

_MODEL_DIR = Path(settings.UPLOAD_DIR).parent / "ml_models"
_MODEL_DIR.mkdir(parents=True, exist_ok=True)


class RegimeDetector:
    """
    HMM-based market regime classifier.

    States:
      0 = trending_up   (positive returns, moderate vol, high autocorrelation)
      1 = trending_down  (negative returns, moderate vol, high autocorrelation)
      2 = ranging         (near-zero returns, low vol, low autocorrelation)
      3 = volatile        (large absolute returns, high vol)
    """

    def __init__(self, model_id: int = 0):
        self.model_id = model_id
        self._model = None
        self._loaded = False
        self._model_path = str(_MODEL_DIR / f"regime_{model_id}.joblib")

    def train(self, ohlcv_data: list[dict], n_states: int = 4) -> dict:
        """
        Train HMM regime detector on OHLCV data.

        Returns dict with training stats and model_path.
        """
        try:
            from hmmlearn.hmm import GaussianHMM
        except ImportError:
            raise ImportError("hmmlearn not installed. pip install hmmlearn>=0.3.0")

        import joblib

        n = len(ohlcv_data)
        if n < 200:
            raise ValueError(f"Need at least 200 bars, got {n}")

        # Build observation matrix
        obs = self._build_observations(ohlcv_data)
        valid_mask = ~np.any(np.isnan(obs), axis=1)
        obs_clean = obs[valid_mask]

        if len(obs_clean) < 100:
            raise ValueError(f"Not enough valid observations: {len(obs_clean)}")

        # Fit HMM
        model = GaussianHMM(
            n_components=n_states,
            covariance_type="full",
            n_iter=200,
            random_state=42,
            tol=1e-4,
        )
        model.fit(obs_clean)

        # Predict regimes
        states = model.predict(obs_clean)

        # Relabel states based on mean returns so they map to our names
        state_means = {}
        for s in range(n_states):
            mask = states == s
            if np.any(mask):
                state_means[s] = {
                    "return_mean": float(np.mean(obs_clean[mask, 0])),
                    "vol_mean": float(np.mean(obs_clean[mask, 1])),
                    "count": int(np.sum(mask)),
                    "pct": round(float(np.sum(mask)) / len(states) * 100, 1),
                }

        # Remap states: sort by return_mean, then assign
        sorted_states = sorted(state_means.keys(), key=lambda s: state_means[s]["return_mean"])
        remap = {}
        if n_states >= 4:
            # Highest vol → volatile (3)
            vol_state = max(state_means.keys(), key=lambda s: state_means[s]["vol_mean"])
            remap[vol_state] = 3
            remaining = [s for s in sorted_states if s != vol_state]
            remap[remaining[0]] = 1   # most negative return → trending_down
            remap[remaining[-1]] = 0  # most positive return → trending_up
            for s in remaining[1:-1]:
                if s not in remap:
                    remap[s] = 2      # middle → ranging
        else:
            for i, s in enumerate(sorted_states):
                remap[s] = i

        # Save model + remap
        joblib.dump({
            "model": model,
            "remap": remap,
            "n_states": n_states,
        }, self._model_path)

        self._model = model
        self._remap = remap
        self._loaded = True

        # Stats per regime
        regime_stats = {}
        for orig, mapped in remap.items():
            name = REGIME_NAMES.get(mapped, f"state_{mapped}")
            regime_stats[name] = state_means.get(orig, {})

        logger.info(
            "RegimeDetector trained: %d bars, %d states, path=%s",
            len(obs_clean), n_states, self._model_path,
        )

        return {
            "model_path": self._model_path,
            "n_bars": len(obs_clean),
            "n_states": n_states,
            "regime_stats": regime_stats,
            "log_likelihood": float(model.score(obs_clean)),
        }

    def load(self, model_path: Optional[str] = None) -> bool:
        """Load a trained regime model."""
        path = model_path or self._model_path
        if not os.path.exists(path):
            logger.warning("Regime model not found: %s", path)
            return False

        try:
            import joblib
            data = joblib.load(path)
            self._model = data["model"]
            self._remap = data.get("remap", {})
            self._loaded = True
            self._model_path = path
            logger.info("RegimeDetector loaded from %s", path)
            return True
        except Exception as e:
            logger.error("Failed to load regime model: %s", e)
            return False

    def predict_regime(self, ohlcv_data: list[dict]) -> Optional[dict]:
        """
        Predict current market regime from recent bars.

        Returns dict with regime name, probabilities, and state index.
        """
        if not self._loaded:
            return None

        if len(ohlcv_data) < 50:
            return None

        try:
            obs = self._build_observations(ohlcv_data)
            # Use last valid observation
            valid_mask = ~np.any(np.isnan(obs), axis=1)
            obs_clean = obs[valid_mask]

            if len(obs_clean) < 1:
                return None

            # Get probabilities for the last observation
            proba = self._model.predict_proba(obs_clean[-5:])
            last_proba = proba[-1]

            raw_state = int(np.argmax(last_proba))
            mapped_state = self._remap.get(raw_state, raw_state)
            regime_name = REGIME_NAMES.get(mapped_state, f"state_{mapped_state}")

            # Build probability dict
            probabilities = {}
            for orig, mapped in self._remap.items():
                name = REGIME_NAMES.get(mapped, f"state_{mapped}")
                if orig < len(last_proba):
                    probabilities[name] = round(float(last_proba[orig]), 4)

            return {
                "regime": regime_name,
                "state_index": mapped_state,
                "probabilities": probabilities,
                "confidence": round(float(last_proba[raw_state]), 4),
            }

        except Exception as e:
            logger.error("Regime prediction failed: %s", e)
            return None

    def get_regime_history(self, ohlcv_data: list[dict]) -> list[dict]:
        """
        Get per-bar regime labels for visualization.

        Returns list of {bar_index, regime, probabilities}.
        """
        if not self._loaded:
            return []

        try:
            obs = self._build_observations(ohlcv_data)
            valid_mask = ~np.any(np.isnan(obs), axis=1)
            obs_clean = obs[valid_mask]

            if len(obs_clean) < 1:
                return []

            states = self._model.predict(obs_clean)
            probas = self._model.predict_proba(obs_clean)

            valid_indices = np.where(valid_mask)[0]
            history = []
            for i, (state, proba) in enumerate(zip(states, probas)):
                mapped = self._remap.get(int(state), int(state))
                probs = {}
                for orig, m in self._remap.items():
                    name = REGIME_NAMES.get(m, f"state_{m}")
                    if orig < len(proba):
                        probs[name] = round(float(proba[orig]), 4)

                bar_idx = int(valid_indices[i])
                entry = {
                    "bar_index": bar_idx,
                    "regime": REGIME_NAMES.get(mapped, f"state_{mapped}"),
                    "state_index": mapped,
                    "probabilities": probs,
                }
                # Include datetime if available
                if bar_idx < len(ohlcv_data) and ohlcv_data[bar_idx].get("datetime"):
                    dt = ohlcv_data[bar_idx]["datetime"]
                    entry["datetime"] = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)

                history.append(entry)

            return history

        except Exception as e:
            logger.error("Regime history failed: %s", e)
            return []

    @staticmethod
    def _build_observations(ohlcv_data: list[dict]) -> np.ndarray:
        """Build 4-feature observation matrix for HMM."""
        n = len(ohlcv_data)
        closes = np.array([d["close"] for d in ohlcv_data], dtype=np.float64)
        highs = np.array([d["high"] for d in ohlcv_data], dtype=np.float64)
        lows = np.array([d["low"] for d in ohlcv_data], dtype=np.float64)

        # Feature 1: 1-bar log return
        returns = np.full(n, np.nan)
        safe_c = np.maximum(closes, 1e-12)
        returns[1:] = np.log(safe_c[1:] / safe_c[:-1])

        # Feature 2: 5-bar rolling volatility
        vol5 = np.full(n, np.nan)
        for i in range(5, n):
            vol5[i] = np.std(returns[i-4:i+1])

        # Feature 3: ATR(14) / price (normalized range)
        tr = np.full(n, np.nan)
        tr[0] = highs[0] - lows[0]
        for i in range(1, n):
            tr[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1]),
            )
        atr14 = np.full(n, np.nan)
        # Wilder smoothing
        atr14[13] = np.mean(tr[:14])
        for i in range(14, n):
            atr14[i] = (atr14[i-1] * 13 + tr[i]) / 14
        atr_norm = np.full(n, np.nan)
        mask = closes > 0
        atr_norm[mask] = atr14[mask] / closes[mask]

        # Feature 4: Autocorrelation(20) of returns
        autocorr = np.full(n, np.nan)
        window = 20
        for i in range(window + 1, n):
            w = returns[i-window:i]
            if np.all(np.isfinite(w)):
                mean_w = np.mean(w)
                var_w = np.var(w)
                if var_w > 1e-12:
                    cov = np.mean((w[1:] - mean_w) * (w[:-1] - mean_w))
                    autocorr[i] = cov / var_w

        obs = np.column_stack([returns, vol5, atr_norm, autocorr])
        return obs
