import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User
from app.models.strategy import Strategy
from app.schemas.strategy import (
    StrategyCreate,
    StrategyUpdate,
    StrategySettingsUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


def _to_response(s: Strategy) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description or "",
        "indicators": s.indicators or [],
        "entry_rules": s.entry_rules or [],
        "exit_rules": s.exit_rules or [],
        "risk_params": s.risk_params or {},
        "filters": s.filters or {},
        "creator_id": s.creator_id,
        "is_system": bool(s.is_system),
        "strategy_type": s.strategy_type or "builder",
        "file_path": s.file_path,
        "settings_schema": s.settings_schema or [],
        "settings_values": s.settings_values or {},
        "created_at": s.created_at.isoformat() if s.created_at else "",
        "updated_at": s.updated_at.isoformat() if s.updated_at else "",
    }


@router.get("")
def list_strategies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    strategies = (
        db.query(Strategy)
        .filter(or_(Strategy.creator_id == current_user.id, Strategy.is_system == True))
        .order_by(Strategy.is_system.desc(), Strategy.updated_at.desc())
        .all()
    )
    return JSONResponse(content={
        "items": [_to_response(s) for s in strategies],
        "total": len(strategies),
    })


@router.post("", status_code=status.HTTP_201_CREATED)
def create_strategy(
    payload: StrategyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    strat = Strategy(
        name=payload.name,
        description=payload.description,
        indicators=payload.indicators,
        entry_rules=payload.entry_rules,
        exit_rules=payload.exit_rules,
        risk_params=payload.risk_params,
        filters=payload.filters,
        strategy_type=payload.strategy_type,
        settings_schema=payload.settings_schema,
        settings_values=payload.settings_values,
        creator_id=current_user.id,
    )
    db.add(strat)
    db.commit()
    db.refresh(strat)
    return JSONResponse(content=_to_response(strat), status_code=201)


@router.get("/{strategy_id}")
def get_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    strat = (
        db.query(Strategy)
        .filter(
            Strategy.id == strategy_id,
            or_(Strategy.creator_id == current_user.id, Strategy.is_system == True),
        )
        .first()
    )
    if not strat:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return JSONResponse(content=_to_response(strat))


@router.put("/{strategy_id}")
def update_strategy(
    strategy_id: int,
    payload: StrategyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    strat = (
        db.query(Strategy)
        .filter(
            Strategy.id == strategy_id,
            or_(Strategy.creator_id == current_user.id, Strategy.is_system == True),
        )
        .first()
    )
    if not strat:
        raise HTTPException(status_code=404, detail="Strategy not found")
    if strat.is_system:
        raise HTTPException(status_code=403, detail="System strategies cannot be modified")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(strat, key, value)

    db.commit()
    db.refresh(strat)
    return JSONResponse(content=_to_response(strat))


@router.delete("/{strategy_id}")
def delete_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.backtest import Backtest
    from app.models.optimization import Optimization
    from app.models.trade import Trade
    from app.models.agent import TradingAgent, AgentLog, AgentTrade
    from app.models.ml import MLModel

    strat = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strat:
        raise HTTPException(status_code=404, detail="Strategy not found")
    if strat.is_system:
        raise HTTPException(status_code=403, detail="System strategies cannot be deleted")
    if strat.creator_id != current_user.id:
        raise HTTPException(status_code=404, detail="Strategy not found")

    # Clean up all related records to avoid FK constraint errors
    # 1. Agent logs and trades (FK → agents), then agents
    agent_ids = [a.id for a in db.query(TradingAgent.id).filter(TradingAgent.strategy_id == strategy_id).all()]
    if agent_ids:
        db.query(AgentLog).filter(AgentLog.agent_id.in_(agent_ids)).delete(synchronize_session=False)
        db.query(AgentTrade).filter(AgentTrade.agent_id.in_(agent_ids)).delete(synchronize_session=False)
        db.query(TradingAgent).filter(TradingAgent.id.in_(agent_ids)).delete(synchronize_session=False)

    # 2. Backtests, optimizations, trades, ML models
    db.query(Backtest).filter(Backtest.strategy_id == strategy_id).delete(synchronize_session=False)
    db.query(Optimization).filter(Optimization.strategy_id == strategy_id).delete(synchronize_session=False)
    db.query(Trade).filter(Trade.strategy_id == strategy_id).delete(synchronize_session=False)
    db.query(MLModel).filter(MLModel.strategy_id == strategy_id).delete(synchronize_session=False)

    db.delete(strat)
    db.commit()
    return {"detail": "Strategy deleted"}


@router.post("/{strategy_id}/duplicate", status_code=status.HTTP_201_CREATED)
def duplicate_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    strat = (
        db.query(Strategy)
        .filter(
            Strategy.id == strategy_id,
            or_(Strategy.creator_id == current_user.id, Strategy.is_system == True),
        )
        .first()
    )
    if not strat:
        raise HTTPException(status_code=404, detail="Strategy not found")

    new_strat = Strategy(
        name=f"{strat.name} (copy)",
        description=strat.description,
        indicators=strat.indicators,
        entry_rules=strat.entry_rules,
        exit_rules=strat.exit_rules,
        risk_params=strat.risk_params,
        filters=strat.filters,
        strategy_type=strat.strategy_type,
        file_path=strat.file_path,
        settings_schema=strat.settings_schema,
        settings_values=strat.settings_values,
        creator_id=current_user.id,
    )
    db.add(new_strat)
    db.commit()
    db.refresh(new_strat)
    return JSONResponse(content=_to_response(new_strat), status_code=201)


# ── File-based strategy upload ─────────────────────────────────────

UPLOAD_EXTENSIONS = {"py", "json", "pine", "pinescript"}


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_strategy_file(
    file: UploadFile = File(...),
    name: Optional[str] = Form(default=""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a strategy file (.py, .json, .pine) and create a strategy record."""
    import os
    from app.services.strategy.file_parser import parse_strategy_file

    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if ext not in UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '.{ext}'. Allowed: {', '.join(sorted(UPLOAD_EXTENSIONS))}",
        )

    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 5 MB)")

    content = raw.decode("utf-8", errors="replace")

    # Parse to extract settings schema
    try:
        parsed = parse_strategy_file(content, ext)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Save file to disk
    upload_dir = os.path.join("data", "strategies")
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = file.filename.replace(" ", "_").replace("..", "_") if file.filename else f"strategy.{ext}"
    # Deduplicate filename
    base, fext = os.path.splitext(safe_name)
    dest = os.path.join(upload_dir, safe_name)
    counter = 1
    while os.path.exists(dest):
        dest = os.path.join(upload_dir, f"{base}_{counter}{fext}")
        counter += 1

    with open(dest, "w", encoding="utf-8") as f:
        f.write(content)

    strat_name = name or parsed.get("name", base)
    strategy_type_map = {"py": "python", "json": "json", "pine": "pinescript", "pinescript": "pinescript"}

    strat = Strategy(
        name=strat_name,
        description=parsed.get("description", f"Uploaded {ext} strategy"),
        strategy_type=strategy_type_map.get(ext, ext),
        file_path=dest,
        settings_schema=parsed.get("settings_schema", []),
        settings_values=parsed.get("settings_values", {}),
        indicators=[],
        entry_rules=[],
        exit_rules=[],
        risk_params={},
        filters={},
        creator_id=current_user.id,
    )
    db.add(strat)
    db.commit()
    db.refresh(strat)
    return JSONResponse(content=_to_response(strat), status_code=201)


@router.put("/{strategy_id}/settings")
def update_strategy_settings(
    strategy_id: int,
    payload: StrategySettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update settings_values for a file-based strategy."""
    strat = (
        db.query(Strategy)
        .filter(
            Strategy.id == strategy_id,
            or_(Strategy.creator_id == current_user.id, Strategy.is_system == True),
        )
        .first()
    )
    if not strat:
        raise HTTPException(status_code=404, detail="Strategy not found")
    if strat.is_system:
        raise HTTPException(status_code=403, detail="System strategies cannot be modified")

    strat.settings_values = payload.settings_values
    db.commit()
    db.refresh(strat)
    return JSONResponse(content=_to_response(strat))


# ── AI-powered strategy generation ─────────────────────────────────

ALLOWED_EXTENSIONS = {"txt", "pine", "md", "pdf", "text", "pinescript"}
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB


@router.post("/ai-generate")
async def ai_generate_strategy(
    file: UploadFile = File(...),
    prompt: Optional[str] = Form(default=""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a trading document and let the LLM convert it into a strategy JSON."""
    from app.services.strategy.ai_parser import parse_trading_document

    # Validate extension
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '.{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # Read file
    raw = await file.read()
    if len(raw) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 2 MB)")

    # Parse
    try:
        strategy_json = await parse_trading_document(
            db=db,
            user_id=current_user.id,
            file_content=raw if ext == "pdf" else raw.decode("utf-8", errors="replace"),
            filename=file.filename or "strategy.txt",
            user_prompt=prompt or "",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("AI strategy generation failed")
        raise HTTPException(status_code=500, detail=f"AI generation failed: {str(e)[:300]}")

    return JSONResponse(content=strategy_json)
