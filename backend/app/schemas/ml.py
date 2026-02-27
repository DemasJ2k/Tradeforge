"""Pydantic schemas for ML Lab endpoints."""

from typing import Optional
from pydantic import BaseModel


# ── Training ──────────────────────────────────────────

class MLTrainRequest(BaseModel):
    name: str
    level: int = 1                           # 1, 2, 3
    model_type: str = "random_forest"        # random_forest, xgboost, gradient_boosting
    datasource_id: int                       # CSV data source ID
    strategy_id: Optional[int] = None
    symbol: str = ""
    timeframe: str = "H1"
    # Feature config
    features: list[str] = []                 # empty = use all defaults
    # Target config
    target_type: str = "direction"           # direction, return, volatility
    target_horizon: int = 1                  # bars ahead to predict
    # Hyperparameters (common)
    n_estimators: int = 100
    max_depth: int = 10
    learning_rate: float = 0.1
    # XGBoost regularization
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    reg_alpha: float = 0.0              # L1 regularization
    reg_lambda: float = 1.0             # L2 regularization
    min_child_weight: int = 1
    gamma: float = 0.0                  # Min loss reduction for split
    early_stopping_rounds: int = 0      # 0 = disabled
    # Random Forest specific
    min_samples_split: int = 5
    min_samples_leaf: int = 2
    # Train/val split
    train_ratio: float = 0.8


class MLModelResponse(BaseModel):
    id: int
    name: str
    level: int
    model_type: str
    symbol: str
    timeframe: str
    status: str
    # Training config
    features_config: dict
    target_config: dict
    hyperparams: dict
    # Results
    train_metrics: dict
    val_metrics: dict
    feature_importance: dict
    # Meta
    created_at: str
    trained_at: Optional[str] = None
    error_message: str = ""


class MLModelListItem(BaseModel):
    id: int
    name: str
    level: int
    model_type: str
    symbol: str
    timeframe: str
    status: str
    train_accuracy: Optional[float] = None
    val_accuracy: Optional[float] = None
    n_features: int = 0
    created_at: str


# ── Prediction ────────────────────────────────────────

class MLPredictRequest(BaseModel):
    model_id: int
    datasource_id: int                       # Data to predict on
    last_n_bars: int = 50                    # Only predict on last N bars


class MLPredictionResponse(BaseModel):
    model_id: int
    model_name: str
    predictions: list[dict]                  # [{bar_index, prediction, confidence, features}]
    total_predictions: int
    avg_confidence: float


# ── Feature inspection ────────────────────────────────

class FeatureListResponse(BaseModel):
    available_features: list[str]
    descriptions: dict                       # feature_name → description


# ── Model comparison ─────────────────────────────────

class ModelCompareResponse(BaseModel):
    models: list[dict]                       # [{id, name, train_metrics, val_metrics}]
