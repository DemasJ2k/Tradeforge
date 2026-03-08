import json
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


# ── Pre-built strategy templates ──────────────────────────────────
STRATEGY_TEMPLATES = [
    {
        "id": "sma_crossover",
        "name": "SMA Crossover",
        "description": "Classic trend-following strategy. Buy when fast SMA crosses above slow SMA, sell on the opposite cross. Works best on trending markets (H1/H4/D1).",
        "category": "trend",
        "indicators": [
            {"id": "sma_fast", "type": "SMA", "params": {"period": 20, "source": "close"}, "overlay": True},
            {"id": "sma_slow", "type": "SMA", "params": {"period": 50, "source": "close"}, "overlay": True},
        ],
        "entry_rules": [
            {"left": "sma_fast", "operator": "crosses_above", "right": "sma_slow", "logic": "AND", "direction": "long"},
            {"left": "sma_fast", "operator": "crosses_below", "right": "sma_slow", "logic": "AND", "direction": "short"},
        ],
        "exit_rules": [
            {"left": "sma_fast", "operator": "crosses_below", "right": "sma_slow", "logic": "AND", "direction": "long"},
            {"left": "sma_fast", "operator": "crosses_above", "right": "sma_slow", "logic": "AND", "direction": "short"},
        ],
        "risk_params": {
            "stop_loss_type": "atr_multiple",
            "stop_loss_value": 2.0,
            "take_profit_type": "rr_ratio",
            "take_profit_value": 2.0,
            "position_size_type": "percent_risk",
            "position_size_value": 1.0,
            "trailing_stop": False,
            "max_positions": 1,
        },
        "filters": {
            "min_adx": 20,
        },
    },
    {
        "id": "rsi_mean_reversion",
        "name": "RSI Mean Reversion",
        "description": "Counter-trend strategy buying oversold and selling overbought conditions. Best on ranging markets or lower timeframes (M15/H1). Uses RSI with trend filter.",
        "category": "mean_reversion",
        "indicators": [
            {"id": "rsi_14", "type": "RSI", "params": {"period": 14, "source": "close"}, "overlay": False},
            {"id": "ema_200", "type": "EMA", "params": {"period": 200, "source": "close"}, "overlay": True},
        ],
        "entry_rules": [
            {"left": "rsi_14", "operator": "crosses_above", "right": "30", "logic": "AND", "direction": "long"},
            {"left": "rsi_14", "operator": "crosses_below", "right": "70", "logic": "AND", "direction": "short"},
        ],
        "exit_rules": [
            {"left": "rsi_14", "operator": ">", "right": "65", "logic": "AND", "direction": "long"},
            {"left": "rsi_14", "operator": "<", "right": "35", "logic": "AND", "direction": "short"},
        ],
        "risk_params": {
            "stop_loss_type": "atr_multiple",
            "stop_loss_value": 1.5,
            "take_profit_type": "rr_ratio",
            "take_profit_value": 1.5,
            "position_size_type": "percent_risk",
            "position_size_value": 0.5,
            "trailing_stop": False,
            "max_positions": 2,
        },
        "filters": {
            "max_adx": 30,
        },
    },
    {
        "id": "bollinger_breakout",
        "name": "Bollinger Band Breakout",
        "description": "Volatility breakout strategy. Enters when price closes outside Bollinger Bands with strong momentum (ATR filter). Best on H1/H4 with volatile instruments.",
        "category": "breakout",
        "indicators": [
            {"id": "bb_20", "type": "Bollinger", "params": {"period": 20, "std_dev": 2.0, "source": "close"}, "overlay": True},
            {"id": "atr_14", "type": "ATR", "params": {"period": 14}, "overlay": False},
        ],
        "entry_rules": [
            {"left": "price.close", "operator": ">", "right": "bb_20.upper", "logic": "AND", "direction": "long"},
            {"left": "price.close", "operator": "<", "right": "bb_20.lower", "logic": "AND", "direction": "short"},
        ],
        "exit_rules": [
            {"left": "price.close", "operator": "<", "right": "bb_20.middle", "logic": "AND", "direction": "long"},
            {"left": "price.close", "operator": ">", "right": "bb_20.middle", "logic": "AND", "direction": "short"},
        ],
        "risk_params": {
            "stop_loss_type": "atr_multiple",
            "stop_loss_value": 2.0,
            "take_profit_type": "atr_multiple",
            "take_profit_value": 3.0,
            "position_size_type": "percent_risk",
            "position_size_value": 1.0,
            "trailing_stop": True,
            "trailing_stop_type": "atr_multiple",
            "trailing_stop_value": 1.5,
            "max_positions": 1,
        },
        "filters": {},
    },
    {
        "id": "macd_rsi_confirm",
        "name": "MACD + RSI Confirmation",
        "description": "Dual-confirmation momentum strategy. Enters on MACD crossover confirmed by RSI direction. Reduces false signals versus single-indicator approaches. Best on H1/H4.",
        "category": "momentum",
        "indicators": [
            {"id": "macd_12_26_9", "type": "MACD", "params": {"fast": 12, "slow": 26, "signal": 9, "source": "close"}, "overlay": False},
            {"id": "rsi_14", "type": "RSI", "params": {"period": 14, "source": "close"}, "overlay": False},
        ],
        "entry_rules": [
            {"left": "macd_12_26_9.macd", "operator": "crosses_above", "right": "macd_12_26_9.signal", "logic": "AND", "direction": "long"},
            {"left": "rsi_14", "operator": ">", "right": "50", "logic": "AND", "direction": "long"},
            {"left": "macd_12_26_9.macd", "operator": "crosses_below", "right": "macd_12_26_9.signal", "logic": "AND", "direction": "short"},
            {"left": "rsi_14", "operator": "<", "right": "50", "logic": "AND", "direction": "short"},
        ],
        "exit_rules": [
            {"left": "macd_12_26_9.macd", "operator": "crosses_below", "right": "macd_12_26_9.signal", "logic": "AND", "direction": "long"},
            {"left": "macd_12_26_9.macd", "operator": "crosses_above", "right": "macd_12_26_9.signal", "logic": "AND", "direction": "short"},
        ],
        "risk_params": {
            "stop_loss_type": "atr_multiple",
            "stop_loss_value": 2.0,
            "take_profit_type": "rr_ratio",
            "take_profit_value": 2.5,
            "position_size_type": "percent_risk",
            "position_size_value": 1.0,
            "trailing_stop": False,
            "max_positions": 1,
        },
        "filters": {
            "min_adx": 20,
        },
    },
    {
        "id": "atr_trailing_momentum",
        "name": "ATR Trailing Momentum",
        "description": "Trend-riding strategy with ATR-based trailing stop. Enters on EMA alignment + ADX strength, rides the trend with a dynamic trailing stop. Best on trending pairs (H1/H4/D1).",
        "category": "trend",
        "indicators": [
            {"id": "ema_20", "type": "EMA", "params": {"period": 20, "source": "close"}, "overlay": True},
            {"id": "ema_50", "type": "EMA", "params": {"period": 50, "source": "close"}, "overlay": True},
            {"id": "adx_14", "type": "ADX", "params": {"period": 14}, "overlay": False},
            {"id": "atr_14", "type": "ATR", "params": {"period": 14}, "overlay": False},
        ],
        "entry_rules": [
            {"left": "ema_20", "operator": "crosses_above", "right": "ema_50", "logic": "AND", "direction": "long"},
            {"left": "adx_14", "operator": ">", "right": "25", "logic": "AND", "direction": "long"},
            {"left": "ema_20", "operator": "crosses_below", "right": "ema_50", "logic": "AND", "direction": "short"},
            {"left": "adx_14", "operator": ">", "right": "25", "logic": "AND", "direction": "short"},
        ],
        "exit_rules": [],
        "risk_params": {
            "stop_loss_type": "atr_multiple",
            "stop_loss_value": 2.0,
            "take_profit_type": "atr_multiple",
            "take_profit_value": 4.0,
            "position_size_type": "percent_risk",
            "position_size_value": 1.0,
            "trailing_stop": True,
            "trailing_stop_type": "atr_multiple",
            "trailing_stop_value": 2.5,
            "max_positions": 1,
        },
        "filters": {
            "min_adx": 20,
        },
    },
]


def _safe_json(val, fallback):
    """Ensure JSON column value is deserialized (SQLite stores JSON as TEXT)."""
    if val is None:
        return fallback
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (ValueError, TypeError):
            return fallback
    return val


def _to_response(s: Strategy) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description or "",
        "indicators": _safe_json(s.indicators, []),
        "entry_rules": _safe_json(s.entry_rules, []),
        "exit_rules": _safe_json(s.exit_rules, []),
        "risk_params": _safe_json(s.risk_params, {}),
        "filters": _safe_json(s.filters, {}),
        "creator_id": s.creator_id,
        "is_system": bool(s.is_system),
        "strategy_type": s.strategy_type or "builder",
        "file_path": s.file_path,
        "settings_schema": _safe_json(s.settings_schema, []),
        "settings_values": _safe_json(s.settings_values, {}),
        "folder": s.folder or None,
        "verified_performance": _safe_json(s.verified_performance, None),
        "created_at": s.created_at.isoformat() if s.created_at else "",
        "updated_at": s.updated_at.isoformat() if s.updated_at else "",
    }


@router.get("/templates")
def get_strategy_templates():
    """Return pre-built strategy templates that users can use as starting points."""
    return JSONResponse(content={"templates": STRATEGY_TEMPLATES})


@router.post("/templates/{template_id}/use", status_code=status.HTTP_201_CREATED)
def use_strategy_template(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new strategy from a template. User can then customize it."""
    template = next((t for t in STRATEGY_TEMPLATES if t["id"] == template_id), None)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    import copy as _copy

    strat = Strategy(
        name=template["name"],
        description=template["description"],
        indicators=_copy.deepcopy(template["indicators"]),
        entry_rules=_copy.deepcopy(template["entry_rules"]),
        exit_rules=_copy.deepcopy(template["exit_rules"]),
        risk_params=_copy.deepcopy(template["risk_params"]),
        filters=_copy.deepcopy(template["filters"]),
        strategy_type="builder",
        is_system=False,
        creator_id=current_user.id,
    )
    db.add(strat)
    db.commit()
    db.refresh(strat)
    return JSONResponse(content=_to_response(strat), status_code=201)


@router.get("")
def list_strategies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    strategies = (
        db.query(Strategy)
        .filter(or_(Strategy.creator_id == current_user.id, Strategy.is_system == True))
        .filter(Strategy.deleted_at.is_(None))
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
    from datetime import datetime, timezone

    strat = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strat:
        raise HTTPException(status_code=404, detail="Strategy not found")
    # Allow deleting system strategies (user can always re-create them)
    if not strat.is_system and strat.creator_id != current_user.id:
        raise HTTPException(status_code=404, detail="Strategy not found")

    # Soft-delete: just mark as deleted, don't cascade-delete related records
    strat.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"detail": "Strategy moved to recycle bin"}


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

    import copy as _copy
    new_strat = Strategy(
        name=f"{strat.name} (copy)",
        description=strat.description,
        indicators=_copy.deepcopy(strat.indicators),
        entry_rules=_copy.deepcopy(strat.entry_rules),
        exit_rules=_copy.deepcopy(strat.exit_rules),
        risk_params=_copy.deepcopy(strat.risk_params),
        filters=_copy.deepcopy(strat.filters),
        is_system=False,  # copies are always user-owned
        strategy_type=strat.strategy_type,
        file_path=strat.file_path,
        settings_schema=_copy.deepcopy(strat.settings_schema),
        settings_values=_copy.deepcopy(strat.settings_values),
        verified_performance=None,  # don't inherit verified badge
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

    # Allow updating settings_values for system strategies (user-tunable params)
    # but merge with defaults so missing keys are preserved
    if strat.settings_schema and isinstance(strat.settings_schema, list):
        defaults = {
            item["key"]: item["default"]
            for item in strat.settings_schema
            if isinstance(item, dict) and "key" in item and "default" in item
        }
        merged = {**defaults, **(payload.settings_values or {})}
        strat.settings_values = merged
    else:
        strat.settings_values = payload.settings_values
        merged = payload.settings_values or {}

    # Sync to mss_config if this is an MSS strategy
    if strat.filters and isinstance(strat.filters, dict) and "mss_config" in strat.filters:
        updated_filters = dict(strat.filters)
        updated_mss = dict(updated_filters["mss_config"])
        for k, v in (merged or {}).items():
            if k in updated_mss:
                updated_mss[k] = v
        updated_filters["mss_config"] = updated_mss
        strat.filters = updated_filters

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
