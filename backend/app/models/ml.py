"""SQLAlchemy models for ML pipeline."""

from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Float, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class MLModel(Base):
    """Stores trained ML model metadata and serialized model bytes."""
    __tablename__ = "ml_models"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    level = Column(Integer, default=1)  # 1=adaptive params, 2=signal, 3=RL
    model_type = Column(String(50), default="random_forest")  # random_forest, xgboost, lstm, etc.
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=True)
    symbol = Column(String(50), default="")
    timeframe = Column(String(10), default="H1")
    # Training config
    features_config = Column(JSON, default=dict)   # which features were used
    target_config = Column(JSON, default=dict)      # prediction target config
    hyperparams = Column(JSON, default=dict)        # model hyperparameters
    # Results
    train_metrics = Column(JSON, default=dict)      # accuracy, f1, etc. on train
    val_metrics = Column(JSON, default=dict)         # accuracy, f1 on validation
    feature_importance = Column(JSON, default=dict)  # feature name → importance
    # Status
    status = Column(String(20), default="pending")   # pending, training, ready, failed
    model_path = Column(Text, default="")             # path to serialized model file
    error_message = Column(Text, default="")
    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    trained_at = Column(DateTime, nullable=True)

    predictions = relationship("MLPrediction", back_populates="model", cascade="all, delete-orphan")


class MLPrediction(Base):
    """Stores ML model predictions for analysis."""
    __tablename__ = "ml_predictions"

    id = Column(Integer, primary_key=True, index=True)
    model_id = Column(Integer, ForeignKey("ml_models.id"), nullable=False)
    symbol = Column(String(50), default="")
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    # Prediction
    prediction = Column(Float, default=0)          # predicted value or class
    confidence = Column(Float, default=0)          # model confidence 0-1
    features_snapshot = Column(JSON, default=dict) # input features at prediction time
    # Actual outcome (filled later)
    actual = Column(Float, nullable=True)
    correct = Column(Integer, nullable=True)        # 1=correct, 0=wrong, null=pending

    model = relationship("MLModel", back_populates="predictions")
