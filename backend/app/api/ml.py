"""
ML Lab API endpoints.

Manages ML model training, prediction, and model lifecycle.
"""

import csv
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.auth import get_current_user
from app.models.user import User
from app.models.datasource import DataSource
from app.models.ml import MLModel, MLPrediction
from app.schemas.ml import (
    MLTrainRequest,
    MLModelResponse,
    MLModelListItem,
    MLPredictRequest,
    MLPredictionResponse,
    FeatureListResponse,
    ModelCompareResponse,
)
from app.services.ml.features import _DEFAULT_FEATURES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ml", tags=["ml"])


# ── Feature catalogue ─────────────────────────────────

FEATURE_DESCRIPTIONS = {
    "returns": "1-bar price return",
    "returns_multi": "Multi-bar returns (2, 3, 5, 10 bars)",
    "volatility": "Rolling volatility (5, 10, 20 bar windows)",
    "candle_patterns": "Candle body ratio, upper/lower wick, range",
    "sma": "Distance from SMA (10, 20, 50 periods)",
    "ema": "Distance from EMA (10, 20, 50 periods)",
    "rsi": "RSI normalized (7, 14, 21 periods)",
    "atr": "ATR normalized by price (7, 14 periods)",
    "macd": "MACD line and histogram (normalized)",
    "bollinger": "Bollinger Band position and width",
    "adx": "Average Directional Index (14 period)",
    "stochastic": "Stochastic %K and %D",
    "volume": "Volume ratio vs 20-bar SMA",
}


@router.get("/features")
async def get_available_features(user: User = Depends(get_current_user)):
    """Get list of available ML features."""
    return FeatureListResponse(
        available_features=_DEFAULT_FEATURES,
        descriptions=FEATURE_DESCRIPTIONS,
    )


# ── Model CRUD ────────────────────────────────────────

@router.get("/models")
async def list_models(
    level: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all ML models."""
    q = db.query(MLModel)
    if level:
        q = q.filter(MLModel.level == level)
    if status:
        q = q.filter(MLModel.status == status)

    models = q.order_by(MLModel.created_at.desc()).all()

    return [
        MLModelListItem(
            id=m.id,
            name=m.name,
            level=m.level,
            model_type=m.model_type,
            symbol=m.symbol,
            timeframe=m.timeframe,
            status=m.status,
            train_accuracy=m.train_metrics.get("accuracy") if m.train_metrics else None,
            val_accuracy=m.val_metrics.get("accuracy") if m.val_metrics else None,
            n_features=len(m.feature_importance) if m.feature_importance else 0,
            created_at=m.created_at.isoformat(),
        )
        for m in models
    ]


@router.get("/models/{model_id}")
async def get_model(
    model_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get detailed model info."""
    m = db.query(MLModel).filter(MLModel.id == model_id).first()
    if not m:
        raise HTTPException(404, "Model not found")

    return MLModelResponse(
        id=m.id,
        name=m.name,
        level=m.level,
        model_type=m.model_type,
        symbol=m.symbol,
        timeframe=m.timeframe,
        status=m.status,
        features_config=m.features_config or {},
        target_config=m.target_config or {},
        hyperparams=m.hyperparams or {},
        train_metrics=m.train_metrics or {},
        val_metrics=m.val_metrics or {},
        feature_importance=m.feature_importance or {},
        created_at=m.created_at.isoformat(),
        trained_at=m.trained_at.isoformat() if m.trained_at else None,
        error_message=m.error_message or "",
    )


@router.delete("/models/{model_id}")
async def delete_model(
    model_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete an ML model."""
    m = db.query(MLModel).filter(MLModel.id == model_id).first()
    if not m:
        raise HTTPException(404, "Model not found")

    # Delete model file
    if m.model_path:
        from app.services.ml.trainer import MLTrainer
        MLTrainer.delete_model(m.model_path)

    db.delete(m)
    db.commit()
    return {"status": "deleted", "model_id": model_id}


# ── Training ──────────────────────────────────────────

@router.post("/train")
async def train_model(
    payload: MLTrainRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Train a new ML model on uploaded data."""
    # Validate datasource
    ds = db.query(DataSource).filter(DataSource.id == payload.datasource_id).first()
    if not ds:
        raise HTTPException(404, f"Data source {payload.datasource_id} not found")

    # Load OHLCV data from CSV
    ohlcv_data = _load_csv_ohlcv(ds.filepath)
    if len(ohlcv_data) < 100:
        raise HTTPException(400, f"Need at least 100 bars, CSV has {len(ohlcv_data)}")

    # Create model record
    features_config = {"features": payload.features or _DEFAULT_FEATURES}
    target_config = {"type": payload.target_type, "horizon": payload.target_horizon}
    hyperparams = {
        "n_estimators": payload.n_estimators,
        "max_depth": payload.max_depth,
        "learning_rate": payload.learning_rate,
        "subsample": payload.subsample,
        "colsample_bytree": payload.colsample_bytree,
        "reg_alpha": payload.reg_alpha,
        "reg_lambda": payload.reg_lambda,
        "min_child_weight": payload.min_child_weight,
        "gamma": payload.gamma,
        "early_stopping_rounds": payload.early_stopping_rounds,
        "min_samples_split": payload.min_samples_split,
        "min_samples_leaf": payload.min_samples_leaf,
    }

    model_record = MLModel(
        name=payload.name,
        level=payload.level,
        model_type=payload.model_type,
        strategy_id=payload.strategy_id,
        symbol=payload.symbol or ds.symbol or "",
        timeframe=payload.timeframe or ds.timeframe or "H1",
        features_config=features_config,
        target_config=target_config,
        hyperparams=hyperparams,
        status="training",
    )
    db.add(model_record)
    db.commit()
    db.refresh(model_record)

    # Train the model
    try:
        from app.services.ml.trainer import MLTrainer
        result = MLTrainer.train_model(
            ohlcv_data=ohlcv_data,
            model_type=payload.model_type,
            features_config=features_config,
            target_config=target_config,
            hyperparams=hyperparams,
            model_id=model_record.id,
        )

        model_record.train_metrics = result["train_metrics"]
        model_record.val_metrics = result["val_metrics"]
        model_record.feature_importance = result["feature_importance"]
        model_record.model_path = result["model_path"]
        model_record.status = "ready"
        model_record.trained_at = datetime.now(timezone.utc)
        db.commit()

        return MLModelResponse(
            id=model_record.id,
            name=model_record.name,
            level=model_record.level,
            model_type=model_record.model_type,
            symbol=model_record.symbol,
            timeframe=model_record.timeframe,
            status="ready",
            features_config=model_record.features_config,
            target_config=model_record.target_config,
            hyperparams=model_record.hyperparams,
            train_metrics=result["train_metrics"],
            val_metrics=result["val_metrics"],
            feature_importance=result["feature_importance"],
            created_at=model_record.created_at.isoformat(),
            trained_at=model_record.trained_at.isoformat() if model_record.trained_at else None,
        )

    except Exception as e:
        model_record.status = "failed"
        model_record.error_message = str(e)
        db.commit()
        logger.error("ML training failed: %s", e)
        raise HTTPException(500, f"Training failed: {str(e)}")


# ── Walk-Forward Retrain ──────────────────────────────

@router.post("/retrain-wf/{model_id}")
async def retrain_walk_forward(
    model_id: int,
    n_folds: int = 5,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrain an existing model using walk-forward cross-validation."""
    model_record = db.query(MLModel).filter(MLModel.id == model_id).first()
    if not model_record:
        raise HTTPException(404, "Model not found")

    # Find the datasource from the model's symbol/timeframe
    ds = None
    if model_record.symbol and model_record.timeframe:
        ds = (
            db.query(DataSource)
            .filter(
                DataSource.symbol == model_record.symbol,
                DataSource.timeframe == model_record.timeframe,
            )
            .first()
        )
    if not ds:
        # Fallback: try any datasource with matching symbol
        ds = db.query(DataSource).filter(DataSource.symbol == model_record.symbol).first()
    if not ds:
        raise HTTPException(404, "No data source found for this model's symbol/timeframe")

    ohlcv_data = _load_csv_ohlcv(ds.filepath)
    if len(ohlcv_data) < 200:
        raise HTTPException(400, f"Need 200+ bars for walk-forward, got {len(ohlcv_data)}")

    model_record.status = "training"
    db.commit()

    try:
        from app.services.ml.trainer import MLTrainer
        result = MLTrainer.train_walk_forward(
            ohlcv_data=ohlcv_data,
            model_type=model_record.model_type,
            features_config=model_record.features_config,
            target_config=model_record.target_config,
            hyperparams=model_record.hyperparams,
            model_id=model_record.id,
            n_folds=n_folds,
        )

        model_record.train_metrics = result["train_metrics"]
        model_record.val_metrics = result["val_metrics"]
        # Store WF CV metrics alongside val_metrics
        if result.get("walk_forward"):
            model_record.val_metrics["walk_forward"] = result["walk_forward"]
        model_record.feature_importance = result["feature_importance"]
        model_record.model_path = result["model_path"]
        model_record.status = "ready"
        model_record.trained_at = datetime.now(timezone.utc)
        db.commit()

        return MLModelResponse(
            id=model_record.id,
            name=model_record.name,
            level=model_record.level,
            model_type=model_record.model_type,
            symbol=model_record.symbol,
            timeframe=model_record.timeframe,
            status="ready",
            features_config=model_record.features_config or {},
            target_config=model_record.target_config or {},
            hyperparams=model_record.hyperparams or {},
            train_metrics=result["train_metrics"],
            val_metrics=model_record.val_metrics,
            feature_importance=result["feature_importance"],
            created_at=model_record.created_at.isoformat(),
            trained_at=model_record.trained_at.isoformat(),
        )

    except Exception as e:
        model_record.status = "failed"
        model_record.error_message = str(e)
        db.commit()
        logger.error("WF retrain failed for model %d: %s", model_id, e)
        raise HTTPException(500, f"Walk-forward retrain failed: {str(e)}")


@router.post("/retrain-all-wf")
async def retrain_all_walk_forward(
    n_folds: int = 5,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrain ALL ready/failed models using walk-forward CV."""
    models = db.query(MLModel).filter(MLModel.status.in_(["ready", "failed"])).all()
    if not models:
        raise HTTPException(404, "No models to retrain")

    results = []
    for m in models:
        ds = None
        if m.symbol and m.timeframe:
            ds = db.query(DataSource).filter(
                DataSource.symbol == m.symbol,
                DataSource.timeframe == m.timeframe,
            ).first()
        if not ds and m.symbol:
            ds = db.query(DataSource).filter(DataSource.symbol == m.symbol).first()
        if not ds:
            results.append({"model_id": m.id, "name": m.name, "status": "skipped", "reason": "no data source"})
            continue

        ohlcv_data = _load_csv_ohlcv(ds.filepath)
        if len(ohlcv_data) < 200:
            results.append({"model_id": m.id, "name": m.name, "status": "skipped", "reason": "insufficient data"})
            continue

        m.status = "training"
        db.commit()

        try:
            from app.services.ml.trainer import MLTrainer
            result = MLTrainer.train_walk_forward(
                ohlcv_data=ohlcv_data,
                model_type=m.model_type,
                features_config=m.features_config,
                target_config=m.target_config,
                hyperparams=m.hyperparams,
                model_id=m.id,
                n_folds=n_folds,
            )

            m.train_metrics = result["train_metrics"]
            m.val_metrics = result["val_metrics"]
            if result.get("walk_forward"):
                m.val_metrics["walk_forward"] = result["walk_forward"]
            m.feature_importance = result["feature_importance"]
            m.model_path = result["model_path"]
            m.status = "ready"
            m.trained_at = datetime.now(timezone.utc)
            db.commit()

            wf = result.get("walk_forward", {})
            results.append({
                "model_id": m.id,
                "name": m.name,
                "status": "retrained",
                "val_accuracy": result["val_metrics"].get("accuracy"),
                "wf_avg_accuracy": wf.get("avg_accuracy"),
                "wf_std_accuracy": wf.get("std_accuracy"),
            })

        except Exception as e:
            m.status = "failed"
            m.error_message = str(e)
            db.commit()
            results.append({"model_id": m.id, "name": m.name, "status": "failed", "reason": str(e)})

    return {"total": len(models), "results": results}


# ── Prediction ────────────────────────────────────────

@router.post("/predict")
async def predict(
    payload: MLPredictRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run predictions using a trained model."""
    model_record = db.query(MLModel).filter(MLModel.id == payload.model_id).first()
    if not model_record:
        raise HTTPException(404, "Model not found")
    if model_record.status != "ready":
        raise HTTPException(400, f"Model not ready (status: {model_record.status})")

    ds = db.query(DataSource).filter(DataSource.id == payload.datasource_id).first()
    if not ds:
        raise HTTPException(404, f"Data source {payload.datasource_id} not found")

    ohlcv_data = _load_csv_ohlcv(ds.filepath)

    # Use last N bars
    if payload.last_n_bars and payload.last_n_bars < len(ohlcv_data):
        # But we need enough lookback for indicators — take extra
        lookback = min(len(ohlcv_data), payload.last_n_bars + 100)
        ohlcv_data = ohlcv_data[-lookback:]

    try:
        from app.services.ml.trainer import MLTrainer
        predictions = MLTrainer.predict(
            model_path=model_record.model_path,
            ohlcv_data=ohlcv_data,
            features_config=model_record.features_config,
        )
    except Exception as e:
        raise HTTPException(500, f"Prediction failed: {str(e)}")

    # Only return last N predictions
    if payload.last_n_bars:
        predictions = predictions[-payload.last_n_bars:]

    # Store predictions
    for p in predictions[-20:]:  # Store last 20 in DB
        db.add(MLPrediction(
            model_id=model_record.id,
            symbol=model_record.symbol,
            prediction=p["prediction"],
            confidence=p["confidence"],
            features_snapshot=p.get("features", {}),
        ))
    db.commit()

    avg_conf = sum(p["confidence"] for p in predictions) / len(predictions) if predictions else 0

    return MLPredictionResponse(
        model_id=model_record.id,
        model_name=model_record.name,
        predictions=predictions,
        total_predictions=len(predictions),
        avg_confidence=round(avg_conf, 4),
    )


# ── Model comparison ──────────────────────────────────

@router.get("/compare")
async def compare_models(
    model_ids: str = Query(..., description="Comma-separated model IDs"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Compare multiple models side by side."""
    ids = [int(x.strip()) for x in model_ids.split(",") if x.strip()]
    models = db.query(MLModel).filter(MLModel.id.in_(ids)).all()

    return ModelCompareResponse(
        models=[
            {
                "id": m.id,
                "name": m.name,
                "model_type": m.model_type,
                "level": m.level,
                "train_metrics": m.train_metrics or {},
                "val_metrics": m.val_metrics or {},
                "feature_importance": m.feature_importance or {},
                "hyperparams": m.hyperparams or {},
            }
            for m in models
        ]
    )


# ── Prediction history ────────────────────────────────

@router.get("/predictions/{model_id}")
async def get_predictions(
    model_id: int,
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get prediction history for a model."""
    preds = (
        db.query(MLPrediction)
        .filter(MLPrediction.model_id == model_id)
        .order_by(MLPrediction.timestamp.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": p.id,
            "prediction": p.prediction,
            "confidence": p.confidence,
            "actual": p.actual,
            "correct": p.correct,
            "timestamp": p.timestamp.isoformat(),
        }
        for p in preds
    ]


# ── Helpers ───────────────────────────────────────────

def _load_csv_ohlcv(file_path: str) -> list[dict]:
    """Load OHLCV data from a CSV file."""
    import os
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"CSV not found: {file_path}")

    data = []
    with open(file_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rec = {
                    "open": float(row.get("open") or row.get("Open") or row.get("o") or 0),
                    "high": float(row.get("high") or row.get("High") or row.get("h") or 0),
                    "low": float(row.get("low") or row.get("Low") or row.get("l") or 0),
                    "close": float(row.get("close") or row.get("Close") or row.get("c") or 0),
                    "volume": float(row.get("volume") or row.get("Volume") or row.get("v") or 0),
                }
                if rec["close"] > 0:
                    data.append(rec)
            except (ValueError, TypeError):
                continue
    return data
