"""
Recycle Bin API — list, restore, and permanently delete soft-deleted items.
"""

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User
from app.models.strategy import Strategy
from app.models.datasource import DataSource
from app.models.backtest import Backtest
from app.models.agent import TradingAgent, AgentLog, AgentTrade
from app.models.ml import MLModel, MLPrediction
from app.models.knowledge import KnowledgeArticle, QuizAttempt
from app.models.llm import LLMConversation, LLMUsage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recycle-bin", tags=["recycle-bin"])

# Map entity_type strings to (Model, name_field, owner_field)
_ENTITY_MAP = {
    "strategy":     (Strategy,          "name",     "creator_id"),
    "datasource":   (DataSource,        "filename", "creator_id"),
    "backtest":     (Backtest,          "symbol",   "creator_id"),
    "agent":        (TradingAgent,      "name",     "created_by"),
    "ml_model":     (MLModel,           "name",     "creator_id"),
    "knowledge":    (KnowledgeArticle,  "title",    "author_id"),
    "conversation": (LLMConversation,   "title",    "user_id"),
}


def _get_display_name(obj, name_field: str, entity_type: str) -> str:
    """Get a human-readable name for a recycle bin item."""
    value = getattr(obj, name_field, None) or ""
    if entity_type == "backtest":
        # For backtests, show symbol + timeframe
        tf = getattr(obj, "timeframe", "")
        return f"{value} {tf}".strip() if tf else value
    return value


def _check_ownership(obj, owner_field: str, user_id: int) -> bool:
    """Check if the current user owns this object."""
    owner_id = getattr(obj, owner_field, None)
    if owner_id is None:
        return True  # No owner restriction
    return owner_id == user_id


# ── List all soft-deleted items ──────────────────────────────────────

@router.get("")
def list_recycle_bin(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all soft-deleted items across all entity types, grouped by type."""
    result = {}

    for entity_type, (model, name_field, owner_field) in _ENTITY_MAP.items():
        q = db.query(model).filter(model.deleted_at.isnot(None))

        # Filter by ownership
        owner_col = getattr(model, owner_field, None)
        if owner_col is not None:
            q = q.filter(owner_col == current_user.id)

        items = q.order_by(model.deleted_at.desc()).all()

        if items:
            result[entity_type] = [
                {
                    "id": item.id,
                    "name": _get_display_name(item, name_field, entity_type),
                    "entity_type": entity_type,
                    "deleted_at": item.deleted_at.isoformat() if item.deleted_at else "",
                }
                for item in items
            ]

    # Flatten into a single list as well for convenience
    all_items = []
    for entity_type, items in result.items():
        all_items.extend(items)

    # Sort all items by deleted_at descending
    all_items.sort(key=lambda x: x["deleted_at"], reverse=True)

    return {
        "items": all_items,
        "total": len(all_items),
        "by_type": result,
    }


# ── Restore a soft-deleted item ─────────────────────────────────────

@router.post("/{entity_type}/{entity_id}/restore")
def restore_item(
    entity_type: str,
    entity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Restore a soft-deleted item from the recycle bin."""
    if entity_type not in _ENTITY_MAP:
        raise HTTPException(400, f"Unknown entity type: {entity_type}")

    model, name_field, owner_field = _ENTITY_MAP[entity_type]
    obj = db.query(model).filter(model.id == entity_id).first()

    if not obj:
        raise HTTPException(404, f"{entity_type} not found")
    if not _check_ownership(obj, owner_field, current_user.id):
        raise HTTPException(403, "Not your item")
    if obj.deleted_at is None:
        raise HTTPException(400, "Item is not in the recycle bin")

    obj.deleted_at = None
    db.commit()

    return {
        "status": "restored",
        "entity_type": entity_type,
        "id": entity_id,
        "name": _get_display_name(obj, name_field, entity_type),
    }


# ── Permanently delete a single item ────────────────────────────────

@router.delete("/{entity_type}/{entity_id}")
def permanent_delete_item(
    entity_type: str,
    entity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently delete a soft-deleted item (original hard-delete logic)."""
    if entity_type not in _ENTITY_MAP:
        raise HTTPException(400, f"Unknown entity type: {entity_type}")

    model, name_field, owner_field = _ENTITY_MAP[entity_type]
    obj = db.query(model).filter(model.id == entity_id).first()

    if not obj:
        raise HTTPException(404, f"{entity_type} not found")
    if not _check_ownership(obj, owner_field, current_user.id):
        raise HTTPException(403, "Not your item")
    if obj.deleted_at is None:
        raise HTTPException(400, "Item is not in the recycle bin. Use the normal delete endpoint first.")

    _hard_delete(db, entity_type, obj)

    return {
        "status": "permanently_deleted",
        "entity_type": entity_type,
        "id": entity_id,
    }


# ── Clear entire recycle bin ─────────────────────────────────────────

@router.delete("/clear")
def clear_recycle_bin(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently delete ALL items in the recycle bin for the current user."""
    total_deleted = 0

    for entity_type, (model, name_field, owner_field) in _ENTITY_MAP.items():
        q = db.query(model).filter(model.deleted_at.isnot(None))

        owner_col = getattr(model, owner_field, None)
        if owner_col is not None:
            q = q.filter(owner_col == current_user.id)

        items = q.all()
        for obj in items:
            try:
                _hard_delete(db, entity_type, obj)
                total_deleted += 1
            except Exception as e:
                logger.error("Failed to permanently delete %s #%d: %s", entity_type, obj.id, e)
                db.rollback()

    return {
        "status": "cleared",
        "total_deleted": total_deleted,
    }


# ── Hard-delete logic (original cascade behavior) ───────────────────

def _hard_delete(db: Session, entity_type: str, obj) -> None:
    """Perform the original hard-delete logic including file cleanup and cascades."""

    if entity_type == "strategy":
        _hard_delete_strategy(db, obj)
    elif entity_type == "datasource":
        _hard_delete_datasource(db, obj)
    elif entity_type == "backtest":
        _hard_delete_backtest(db, obj)
    elif entity_type == "agent":
        _hard_delete_agent(db, obj)
    elif entity_type == "ml_model":
        _hard_delete_ml_model(db, obj)
    elif entity_type == "knowledge":
        _hard_delete_knowledge(db, obj)
    elif entity_type == "conversation":
        _hard_delete_conversation(db, obj)
    else:
        db.delete(obj)
        db.commit()


def _hard_delete_strategy(db: Session, strat: Strategy) -> None:
    """Original cascade-delete logic for strategies."""
    from app.models.optimization import Optimization
    from app.models.trade import Trade

    strategy_id = strat.id

    # 1. Agent logs and trades (FK -> agents), then agents
    agent_ids = [
        a.id for a in
        db.query(TradingAgent.id).filter(TradingAgent.strategy_id == strategy_id).all()
    ]
    if agent_ids:
        db.query(AgentLog).filter(AgentLog.agent_id.in_(agent_ids)).delete(synchronize_session=False)
        db.query(AgentTrade).filter(AgentTrade.agent_id.in_(agent_ids)).delete(synchronize_session=False)
        db.query(TradingAgent).filter(TradingAgent.id.in_(agent_ids)).delete(synchronize_session=False)

    # 2. Backtests, optimizations, trades, ML models
    db.query(Backtest).filter(Backtest.strategy_id == strategy_id).delete(synchronize_session=False)
    db.query(Optimization).filter(Optimization.strategy_id == strategy_id).delete(synchronize_session=False)
    db.query(Trade).filter(Trade.strategy_id == strategy_id).delete(synchronize_session=False)

    # ML models: delete model files first, then records
    ml_models = db.query(MLModel).filter(MLModel.strategy_id == strategy_id).all()
    for m in ml_models:
        if m.model_path:
            try:
                from app.services.ml.trainer import MLTrainer
                MLTrainer.delete_model(m.model_path)
            except Exception:
                pass
        # Delete predictions for this model
        db.query(MLPrediction).filter(MLPrediction.model_id == m.id).delete(synchronize_session=False)
    db.query(MLModel).filter(MLModel.strategy_id == strategy_id).delete(synchronize_session=False)

    db.delete(strat)
    db.commit()


def _hard_delete_datasource(db: Session, ds: DataSource) -> None:
    """Delete data source record and its file from disk."""
    # Delete file from disk
    try:
        if ds.filepath and os.path.exists(ds.filepath):
            os.remove(ds.filepath)
    except OSError:
        pass

    db.delete(ds)
    db.commit()


def _hard_delete_backtest(db: Session, bt: Backtest) -> None:
    """Delete a backtest record."""
    db.delete(bt)
    db.commit()


def _hard_delete_agent(db: Session, agent: TradingAgent) -> None:
    """Delete agent with its logs and trades (cascade)."""
    agent_id = agent.id
    db.query(AgentLog).filter(AgentLog.agent_id == agent_id).delete(synchronize_session=False)
    db.query(AgentTrade).filter(AgentTrade.agent_id == agent_id).delete(synchronize_session=False)
    db.delete(agent)
    db.commit()


def _hard_delete_ml_model(db: Session, m: MLModel) -> None:
    """Delete ML model record and its model file."""
    # Delete model file from disk
    if m.model_path:
        try:
            from app.services.ml.trainer import MLTrainer
            MLTrainer.delete_model(m.model_path)
        except Exception:
            pass

    # Delete predictions
    db.query(MLPrediction).filter(MLPrediction.model_id == m.id).delete(synchronize_session=False)
    db.delete(m)
    db.commit()


def _hard_delete_knowledge(db: Session, article: KnowledgeArticle) -> None:
    """Delete article and associated quiz attempts."""
    db.query(QuizAttempt).filter(QuizAttempt.article_id == article.id).delete()
    db.delete(article)
    db.commit()


def _hard_delete_conversation(db: Session, convo: LLMConversation) -> None:
    """Delete conversation and its usage records."""
    db.query(LLMUsage).filter(LLMUsage.conversation_id == convo.id).delete()
    db.delete(convo)
    db.commit()
