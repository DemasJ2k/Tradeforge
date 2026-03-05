"""
ML Lab API endpoints.

Manages ML model training, prediction, and model lifecycle.
"""

import asyncio
import csv
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db, SessionLocal
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

# Thread pool for CPU-bound training (1 worker to stay within 2GB RAM)
_train_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ml_train")


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
    "time": "Cyclical hour-of-day and day-of-week (sin/cos encoded)",
    "regime": "Market regime: ATR ratio, return autocorrelation, volatility clustering",
    "momentum": "Rate of change (5/10/20) and price acceleration",
}


_ALL_FEATURES = _DEFAULT_FEATURES + ["time", "regime", "momentum"]


@router.get("/features")
async def get_available_features(user: User = Depends(get_current_user)):
    """Get list of available ML features."""
    return FeatureListResponse(
        available_features=_ALL_FEATURES,
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
    from sqlalchemy import or_
    q = db.query(MLModel).filter(
        or_(MLModel.creator_id == user.id, MLModel.creator_id == None)  # noqa: E711
    ).filter(MLModel.deleted_at.is_(None))
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
    """Soft-delete an ML model (move to recycle bin)."""
    m = db.query(MLModel).filter(MLModel.id == model_id).first()
    if not m:
        raise HTTPException(404, "Model not found")
    if m.creator_id and m.creator_id != user.id:
        raise HTTPException(403, "Not your model")

    # Soft-delete: mark as deleted, don't delete the model file yet
    m.deleted_at = datetime.now(timezone.utc)
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
    if payload.normalize != "none":
        features_config["normalize"] = payload.normalize
        features_config["zscore_window"] = payload.zscore_window
    target_config = {"type": payload.target_type, "horizon": payload.target_horizon}
    if payload.target_type == "triple_barrier":
        target_config["sl_atr_mult"] = payload.sl_atr_mult
        target_config["tp_atr_mult"] = payload.tp_atr_mult
        target_config["max_holding_bars"] = payload.max_holding_bars
    if payload.level == 3:
        hyperparams = {
            "sub_type": payload.sub_type or "ensemble",
            "seq_len": payload.seq_len or 20,
            "hidden_units": payload.hidden_units or 64,
        }
    else:
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

    # For level 3, store the sub_type as model_type for display purposes
    effective_model_type = (
        (payload.sub_type or "lstm") if payload.level == 3 else payload.model_type
    )

    model_record = MLModel(
        name=payload.name,
        level=payload.level,
        model_type=effective_model_type,
        strategy_id=payload.strategy_id,        creator_id=user.id,        symbol=payload.symbol or ds.symbol or "",
        timeframe=payload.timeframe or ds.timeframe or "H1",
        features_config=features_config,
        target_config=target_config,
        hyperparams=hyperparams,
        status="training",
    )
    db.add(model_record)
    db.commit()
    db.refresh(model_record)

    # Launch background training task
    model_id = model_record.id
    level = payload.level
    model_type = payload.model_type
    sub_type = payload.sub_type or "ensemble"
    seq_len = payload.seq_len or 20
    hidden_units = payload.hidden_units or 64

    asyncio.get_event_loop().run_in_executor(
        _train_pool,
        _run_training,
        model_id, ohlcv_data, level, model_type, sub_type,
        seq_len, hidden_units, features_config, target_config, hyperparams,
    )

    # Return immediately with "training" status
    return {
        "id": model_record.id,
        "name": model_record.name,
        "status": "training",
        "message": "Training started in background. Poll GET /api/ml/models/{id} for status.",
    }


# ── Background training runner ────────────────────────

def _run_training(
    model_id: int,
    ohlcv_data: list[dict],
    level: int,
    model_type: str,
    sub_type: str,
    seq_len: int,
    hidden_units: int,
    features_config: dict,
    target_config: dict,
    hyperparams: dict,
):
    """Run ML training in a background thread. Updates DB when done."""
    db = SessionLocal()
    try:
        from app.services.ml.trainer import MLTrainer

        model_record = db.query(MLModel).filter(MLModel.id == model_id).first()
        if not model_record:
            logger.error("Background train: model %d not found", model_id)
            return

        if level == 3:
            result = MLTrainer.train_level3(
                ohlcv_data=ohlcv_data,
                sub_type=sub_type,
                seq_len=seq_len,
                hidden_units=hidden_units,
                features_config=features_config,
                target_config=target_config,
                model_id=model_id,
            )
        else:
            result = MLTrainer.train_model(
                ohlcv_data=ohlcv_data,
                model_type=model_type,
                features_config=features_config,
                target_config=target_config,
                hyperparams=hyperparams,
                model_id=model_id,
            )

        model_record.train_metrics = result["train_metrics"]
        model_record.val_metrics = result["val_metrics"]
        model_record.feature_importance = result["feature_importance"]
        model_record.model_path = result["model_path"]
        model_record.status = "ready"
        model_record.trained_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("Background train complete: model %d → ready", model_id)

    except Exception as e:
        try:
            model_record = db.query(MLModel).filter(MLModel.id == model_id).first()
            if model_record:
                model_record.status = "failed"
                model_record.error_message = str(e)[:500]
                db.commit()
        except Exception:
            pass
        logger.error("Background train failed for model %d: %s", model_id, e)
    finally:
        db.close()


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


@router.post("/retrain-purged/{model_id}")
async def retrain_purged_kfold(
    model_id: int,
    n_folds: int = 5,
    embargo_pct: float = 0.02,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrain using purged k-fold CV with embargo (gold standard for financial ML)."""
    model_record = db.query(MLModel).filter(MLModel.id == model_id).first()
    if not model_record:
        raise HTTPException(404, "Model not found")

    ds = None
    if model_record.symbol and model_record.timeframe:
        ds = db.query(DataSource).filter(
            DataSource.symbol == model_record.symbol,
            DataSource.timeframe == model_record.timeframe,
        ).first()
    if not ds and model_record.symbol:
        ds = db.query(DataSource).filter(DataSource.symbol == model_record.symbol).first()
    if not ds:
        raise HTTPException(404, "No data source found for this model")

    ohlcv_data = _load_csv_ohlcv(ds.filepath)
    if len(ohlcv_data) < 200:
        raise HTTPException(400, f"Need 200+ bars for purged k-fold, got {len(ohlcv_data)}")

    model_record.status = "training"
    db.commit()

    try:
        from app.services.ml.trainer import MLTrainer
        result = MLTrainer.train_purged_kfold(
            ohlcv_data=ohlcv_data,
            model_type=model_record.model_type,
            features_config=model_record.features_config,
            target_config=model_record.target_config,
            hyperparams=model_record.hyperparams,
            model_id=model_record.id,
            n_folds=n_folds,
            embargo_pct=embargo_pct,
        )

        model_record.train_metrics = result["train_metrics"]
        model_record.val_metrics = result["val_metrics"]
        if result.get("purged_kfold"):
            model_record.val_metrics["purged_kfold"] = result["purged_kfold"]
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
        logger.error("Purged KF retrain failed for model %d: %s", model_id, e)
        raise HTTPException(500, f"Purged k-fold retrain failed: {str(e)}")


@router.post("/train-meta")
async def train_meta_label(
    payload: MLTrainRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Train a meta-labeling model that filters signals from a primary model.

    Requires payload.primary_model_id pointing to an existing trained model.
    The meta model learns which signals from the primary model are profitable.
    """
    if not payload.primary_model_id:
        raise HTTPException(400, "primary_model_id is required for meta-labeling")

    primary_record = db.query(MLModel).filter(MLModel.id == payload.primary_model_id).first()
    if not primary_record:
        raise HTTPException(404, f"Primary model {payload.primary_model_id} not found")
    if primary_record.status != "ready":
        raise HTTPException(400, f"Primary model not ready (status: {primary_record.status})")
    if not primary_record.model_path:
        raise HTTPException(400, "Primary model has no saved model file")

    ds = db.query(DataSource).filter(DataSource.id == payload.datasource_id).first()
    if not ds:
        raise HTTPException(404, f"Data source {payload.datasource_id} not found")

    ohlcv_data = _load_csv_ohlcv(ds.filepath)
    if len(ohlcv_data) < 200:
        raise HTTPException(400, f"Need at least 200 bars for meta-labeling, got {len(ohlcv_data)}")

    features_config = {"features": payload.features or _DEFAULT_FEATURES}
    if payload.normalize != "none":
        features_config["normalize"] = payload.normalize
        features_config["zscore_window"] = payload.zscore_window
    target_config = {"type": payload.target_type, "horizon": payload.target_horizon}
    if payload.target_type == "triple_barrier":
        target_config["sl_atr_mult"] = payload.sl_atr_mult
        target_config["tp_atr_mult"] = payload.tp_atr_mult
        target_config["max_holding_bars"] = payload.max_holding_bars
    hyperparams = {
        "n_estimators": payload.n_estimators,
        "max_depth": payload.max_depth,
        "learning_rate": payload.learning_rate,
        "early_stopping_rounds": payload.early_stopping_rounds,
    }

    model_record = MLModel(
        name=payload.name,
        level=2,
        model_type=payload.model_type,
        creator_id=user.id,
        symbol=payload.symbol or ds.symbol or "",
        timeframe=payload.timeframe or ds.timeframe or "H1",
        features_config={
            **features_config,
            "is_meta_model": True,
            "primary_model_id": payload.primary_model_id,
        },
        target_config=target_config,
        hyperparams=hyperparams,
        status="training",
    )
    db.add(model_record)
    db.commit()
    db.refresh(model_record)

    meta_model_id = model_record.id
    primary_model_path = primary_record.model_path
    model_type = payload.model_type

    asyncio.get_event_loop().run_in_executor(
        _train_pool,
        _run_meta_training,
        meta_model_id, ohlcv_data, primary_model_path, model_type,
        features_config, target_config, hyperparams,
    )

    return {
        "id": model_record.id,
        "name": model_record.name,
        "status": "training",
        "message": "Meta-labeling training started. Poll GET /api/ml/models/{id} for status.",
    }


def _run_meta_training(
    model_id: int,
    ohlcv_data: list[dict],
    primary_model_path: str,
    model_type: str,
    features_config: dict,
    target_config: dict,
    hyperparams: dict,
):
    """Run meta-labeling training in a background thread."""
    db = SessionLocal()
    try:
        from app.services.ml.meta_labeler import train_meta_model

        model_record = db.query(MLModel).filter(MLModel.id == model_id).first()
        if not model_record:
            logger.error("Meta train: model %d not found", model_id)
            return

        result = train_meta_model(
            ohlcv_data=ohlcv_data,
            primary_model_path=primary_model_path,
            model_type=model_type,
            features_config=features_config,
            target_config=target_config,
            hyperparams=hyperparams,
            model_id=model_id,
        )

        model_record.train_metrics = result["train_metrics"]
        model_record.val_metrics = result["val_metrics"]
        model_record.feature_importance = result["feature_importance"]
        model_record.model_path = result["model_path"]
        model_record.status = "ready"
        model_record.trained_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("Meta train complete: model %d → ready", model_id)

    except Exception as e:
        try:
            model_record = db.query(MLModel).filter(MLModel.id == model_id).first()
            if model_record:
                model_record.status = "failed"
                model_record.error_message = str(e)[:500]
                db.commit()
        except Exception:
            pass
        logger.error("Meta train failed for model %d: %s", model_id, e)
    finally:
        db.close()


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

    # Store predictions (include bar_index for accuracy tracking)
    for p in predictions[-20:]:  # Store last 20 in DB
        snap = p.get("features", {})
        snap["_bar_index"] = p.get("bar_index")  # For update-actuals tracking
        db.add(MLPrediction(
            model_id=model_record.id,
            symbol=model_record.symbol,
            prediction=p["prediction"],
            confidence=p["confidence"],
            features_snapshot=snap,
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


# ── Prediction accuracy tracking ─────────────────────

@router.post("/predictions/update-actuals")
async def update_prediction_actuals(
    model_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update prediction actual values from latest datasource data.
    Compares stored predictions against actual price movement
    and populates the 'actual' and 'correct' fields.
    """
    model_record = db.query(MLModel).filter(MLModel.id == model_id).first()
    if not model_record:
        raise HTTPException(404, "Model not found")

    target_config = model_record.target_config or {}
    target_type = target_config.get("type", "direction")
    horizon = target_config.get("horizon", 1)

    # Find datasource
    ds = None
    if model_record.symbol and model_record.timeframe:
        ds = db.query(DataSource).filter(
            DataSource.symbol == model_record.symbol,
            DataSource.timeframe == model_record.timeframe,
        ).first()
    if not ds:
        ds = db.query(DataSource).filter(DataSource.symbol == model_record.symbol).first()
    if not ds:
        raise HTTPException(404, "No data source found for this model")

    ohlcv_data = _load_csv_ohlcv(ds.filepath)
    if len(ohlcv_data) < horizon + 1:
        raise HTTPException(400, "Not enough data to compute actuals")

    closes = [d["close"] for d in ohlcv_data]

    # Get predictions that haven't been evaluated yet
    pending = (
        db.query(MLPrediction)
        .filter(MLPrediction.model_id == model_id, MLPrediction.actual.is_(None))
        .all()
    )

    updated = 0
    for pred in pending:
        # Use features_snapshot to find the bar index if available
        snap = pred.features_snapshot or {}
        bar_idx = snap.get("_bar_index")
        if bar_idx is None:
            continue
        if bar_idx + horizon >= len(closes):
            continue  # Not enough future data yet

        if target_type == "direction":
            actual_ret = (closes[bar_idx + horizon] - closes[bar_idx]) / closes[bar_idx] if closes[bar_idx] > 0 else 0
            actual_dir = 1.0 if actual_ret > 0 else 0.0
            pred.actual = actual_dir
            pred.correct = 1 if pred.prediction == actual_dir else 0
        elif target_type == "return":
            actual_ret = (closes[bar_idx + horizon] - closes[bar_idx]) / closes[bar_idx] if closes[bar_idx] > 0 else 0
            pred.actual = actual_ret
            # For regression, "correct" means same direction
            pred.correct = 1 if (pred.prediction > 0) == (actual_ret > 0) else 0
        else:
            continue

        updated += 1

    db.commit()
    return {"model_id": model_id, "updated": updated, "total_pending": len(pending)}


# ── Helpers ───────────────────────────────────────────

def _load_csv_ohlcv(file_path: str) -> list[dict]:
    """Load OHLCV data from a CSV file, including timestamps when available."""
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
                    # Try to parse datetime from known column names
                    dt_str = (
                        row.get("datetime") or row.get("Datetime") or row.get("date")
                        or row.get("Date") or row.get("time") or row.get("Time")
                        or row.get("<DATE>") or row.get("timestamp") or ""
                    )
                    rec["datetime"] = _parse_csv_datetime(dt_str) if dt_str.strip() else None
                    data.append(rec)
            except (ValueError, TypeError):
                continue
    return data


def _parse_csv_datetime(dt_str: str) -> datetime | None:
    """Parse datetime from common CSV formats."""
    dt_str = dt_str.strip()
    if not dt_str:
        return None

    # Try common formats
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",          # ISO
        "%Y-%m-%d %H:%M:%S",           # Standard
        "%Y.%m.%d %H:%M:%S",           # MT5 dot format
        "%Y-%m-%d %H:%M",              # No seconds
        "%Y.%m.%d %H:%M",              # MT5 no seconds
        "%Y-%m-%d",                     # Date only
        "%m/%d/%Y %H:%M:%S",           # US format
        "%m/%d/%Y %H:%M",              # US no seconds
        "%d/%m/%Y %H:%M:%S",           # EU format
    ):
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue

    return None
