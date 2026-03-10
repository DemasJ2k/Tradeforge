"""
SHAP-based feature selection for ML models.

Uses TreeExplainer to rank features by importance and prune
low-value features to reduce overfitting and speed up inference.
"""

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class SHAPFeatureSelector:
    """Rank and select features using SHAP values."""

    @staticmethod
    def select_features(
        model,
        X_train: list[list[float]],
        feature_names: list[str],
        top_k: Optional[int] = None,
        min_importance: float = 0.01,
    ) -> tuple[list[str], list[int], dict]:
        """
        Select top features based on SHAP importance.

        Args:
            model: Trained tree-based model (sklearn, XGBoost, LightGBM, CatBoost)
            X_train: Training feature matrix
            feature_names: Feature names
            top_k: Keep top K features (if None, uses min_importance threshold)
            min_importance: Min normalized importance to keep (0-1)

        Returns:
            (selected_names, selected_indices, shap_summary)
        """
        try:
            import shap
        except ImportError:
            logger.warning("shap not installed — returning all features")
            return feature_names, list(range(len(feature_names))), {}

        X = np.array(X_train, dtype=np.float64)

        # Use a subsample for speed (max 2000 rows)
        if len(X) > 2000:
            rng = np.random.RandomState(42)
            idx = rng.choice(len(X), 2000, replace=False)
            X_sample = X[idx]
        else:
            X_sample = X

        try:
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X_sample)
        except Exception as e:
            logger.warning("SHAP TreeExplainer failed: %s — falling back to model importance", e)
            return feature_names, list(range(len(feature_names))), {}

        # Handle multi-class: shap_values is a list of arrays
        if isinstance(shap_values, list):
            # Use class 1 (positive class) for binary, or average across classes
            if len(shap_values) == 2:
                sv = np.abs(shap_values[1])
            else:
                sv = np.mean([np.abs(s) for s in shap_values], axis=0)
        else:
            sv = np.abs(shap_values)

        # Mean absolute SHAP per feature
        mean_shap = np.mean(sv, axis=0)
        total = np.sum(mean_shap)
        if total > 0:
            normalized = mean_shap / total
        else:
            normalized = np.ones(len(feature_names)) / len(feature_names)

        # Rank features
        ranking = sorted(
            zip(feature_names, normalized, range(len(feature_names))),
            key=lambda x: -x[1],
        )

        # Select features
        if top_k is not None:
            selected = ranking[:top_k]
        else:
            selected = [(name, imp, idx) for name, imp, idx in ranking if imp >= min_importance]

        # Ensure we keep at least 5 features
        if len(selected) < 5 and len(ranking) >= 5:
            selected = ranking[:5]

        selected_names = [s[0] for s in selected]
        selected_indices = [s[2] for s in selected]

        # Build summary
        shap_summary = {
            "total_features": len(feature_names),
            "selected_features": len(selected_names),
            "feature_ranking": [
                {"name": name, "importance": round(float(imp), 6), "selected": idx in selected_indices}
                for name, imp, idx in ranking
            ],
        }

        logger.info(
            "SHAP selection: %d → %d features (top importance: %s=%.4f)",
            len(feature_names), len(selected_names),
            selected_names[0] if selected_names else "?",
            selected[0][1] if selected else 0,
        )

        return selected_names, selected_indices, shap_summary

    @staticmethod
    def filter_matrix(
        X: list[list[float]],
        selected_indices: list[int],
    ) -> list[list[float]]:
        """Filter feature matrix to keep only selected columns."""
        arr = np.array(X, dtype=np.float64)
        filtered = arr[:, selected_indices]
        return filtered.tolist()
