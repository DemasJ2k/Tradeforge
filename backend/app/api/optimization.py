"""
Optimization API endpoints.
Runs optimization in background threads with progress tracking.
"""
import time
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import get_db, SessionLocal
from app.core.auth import get_current_user
from app.core.config import settings
from app.models.user import User
from app.models.strategy import Strategy
from app.models.datasource import DataSource
from app.models.optimization import Optimization
from app.schemas.optimization import (
    OptimizationRequest,
    OptimizationResponse,
    OptimizationStatus,
    OptimizationListItem,
    TrialResult,
)
from app.services.optimize.engine import (
    OptimizerEngine, ParamSpec, Bar,
)
from app.api.backtest import _load_bars_from_csv

router = APIRouter(prefix="/api/optimize", tags=["optimization"])

# In-memory progress tracking
_running_optimizations: dict[int, dict] = {}


def _run_optimization_thread(
    opt_id: int,
    bars: list[Bar],
    strategy_config: dict,
    param_specs: list[ParamSpec],
    objective: str,
    n_trials: int,
    method: str,
    initial_balance: float,
    spread: float,
    commission: float,
    point_value: float,
    walk_forward: bool,
    wf_pct: float,
    secondary_objective: str = None,
    secondary_threshold: float = None,
    secondary_operator: str = None,
):
    """Background thread that runs optimization and updates DB on complete."""
    _running_optimizations[opt_id] = {
        "status": "running",
        "progress": 0.0,
        "current_trial": 0,
        "total_trials": n_trials,
        "best_score": 0.0,
        "best_params": {},
        "start_time": time.time(),
    }

    def progress_cb(current, total, best_score, best_params):
        if opt_id in _running_optimizations:
            _running_optimizations[opt_id].update({
                "progress": round(current / total * 100, 1),
                "current_trial": current,
                "best_score": best_score,
                "best_params": best_params,
            })

    try:
        engine = OptimizerEngine(
            bars=bars,
            strategy_config=strategy_config,
            param_specs=param_specs,
            objective=objective,
            n_trials=n_trials,
            method=method,
            initial_balance=initial_balance,
            spread_points=spread,
            commission_per_lot=commission,
            point_value=point_value,
            walk_forward=walk_forward,
            wf_in_sample_pct=wf_pct,
            progress_callback=progress_cb,
            secondary_objective=secondary_objective,
            secondary_threshold=secondary_threshold,
            secondary_operator=secondary_operator,
        )
        result = engine.run()

        # Update DB
        db = SessionLocal()
        try:
            opt = db.query(Optimization).filter(Optimization.id == opt_id).first()
            if opt:
                opt.status = "completed"
                opt.best_params = result.best_params
                opt.best_score = result.best_score
                opt.history = [
                    {
                        "trial_number": t.trial_number,
                        "params": t.params,
                        "score": t.score,
                        "stats": t.stats,
                    }
                    for t in result.history
                ]
                db.commit()
        finally:
            db.close()

        if opt_id in _running_optimizations:
            _running_optimizations[opt_id]["status"] = "completed"
            _running_optimizations[opt_id]["progress"] = 100.0
            _running_optimizations[opt_id]["param_importance"] = result.param_importance

    except Exception as e:
        # Update status to failed
        db = SessionLocal()
        try:
            opt = db.query(Optimization).filter(Optimization.id == opt_id).first()
            if opt:
                opt.status = "failed"
                db.commit()
        finally:
            db.close()

        if opt_id in _running_optimizations:
            _running_optimizations[opt_id]["status"] = "failed"
            _running_optimizations[opt_id]["error"] = str(e)[:300]


@router.post("/run", response_model=dict)
def start_optimization(
    payload: OptimizationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start an optimization run (runs in background thread)."""
    # Load strategy (user-owned OR system)
    strategy = (
        db.query(Strategy)
        .filter(
            Strategy.id == payload.strategy_id,
            or_(Strategy.creator_id == current_user.id, Strategy.is_system == True),
        )
        .first()
    )
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    # Load datasource
    datasource = db.query(DataSource).filter(DataSource.id == payload.datasource_id).first()
    if not datasource:
        raise HTTPException(status_code=404, detail="Data source not found")

    file_path = Path(datasource.filepath)
    if not file_path.exists():
        file_path = Path(settings.UPLOAD_DIR) / datasource.filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="CSV file not found on disk")

    bars = _load_bars_from_csv(str(file_path))
    if len(bars) < 100:
        raise HTTPException(status_code=400, detail=f"Not enough data: {len(bars)} bars (need 100+)")

    # Build strategy config
    strategy_type = getattr(strategy, "strategy_type", "builder") or "builder"
    strategy_config = {
        "indicators": strategy.indicators or [],
        "entry_rules": strategy.entry_rules or [],
        "exit_rules": strategy.exit_rules or [],
        "risk_params": strategy.risk_params or {},
        "filters": strategy.filters or {},
    }
    # Add file strategy metadata for the optimizer engine
    if strategy_type in ("python", "json") and getattr(strategy, "file_path", None):
        strategy_config["_file_strategy"] = {
            "strategy_type": strategy_type,
            "file_path": strategy.file_path,
            "settings_values": getattr(strategy, "settings_values", None) or {},
        }

    # Convert param specs
    param_specs = [
        ParamSpec(
            param_path=p.param_path,
            param_type=p.param_type,
            min_val=p.min_val,
            max_val=p.max_val,
            step=p.step,
            choices=p.choices,
            label=p.label,
        )
        for p in payload.param_space
    ]

    if not param_specs:
        raise HTTPException(status_code=400, detail="No parameters to optimize")

    # Create DB record
    opt = Optimization(
        strategy_id=strategy.id,
        param_space=[
            {
                "param_path": p.param_path,
                "param_type": p.param_type,
                "min_val": p.min_val,
                "max_val": p.max_val,
                "step": p.step,
                "choices": p.choices,
                "label": p.label,
            }
            for p in payload.param_space
        ],
        objective=payload.objective,
        n_trials=payload.n_trials,
        status="running",
    )
    db.add(opt)
    db.commit()
    db.refresh(opt)

    # Start background thread
    thread = threading.Thread(
        target=_run_optimization_thread,
        args=(
            opt.id, bars, strategy_config, param_specs,
            payload.objective, payload.n_trials, payload.method,
            payload.initial_balance, payload.spread_points,
            payload.commission_per_lot, payload.point_value,
            payload.walk_forward, payload.wf_in_sample_pct,
            payload.secondary_objective, payload.secondary_threshold,
            payload.secondary_operator,
        ),
        daemon=True,
    )
    thread.start()

    return {"id": opt.id, "status": "running", "message": "Optimization started"}


@router.get("/status/{opt_id}", response_model=OptimizationStatus)
def get_optimization_status(
    opt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get real-time progress of a running optimization."""
    # Check in-memory first
    if opt_id in _running_optimizations:
        info = _running_optimizations[opt_id]
        return OptimizationStatus(
            id=opt_id,
            status=info["status"],
            progress=info["progress"],
            current_trial=info["current_trial"],
            total_trials=info["total_trials"],
            best_score=round(info["best_score"], 6),
            best_params=info["best_params"],
            elapsed_seconds=round(time.time() - info["start_time"], 1),
        )

    # Fall back to DB
    opt = db.query(Optimization).filter(Optimization.id == opt_id).first()
    if not opt:
        raise HTTPException(status_code=404, detail="Optimization not found")

    return OptimizationStatus(
        id=opt.id,
        status=opt.status,
        progress=100.0 if opt.status == "completed" else 0.0,
        current_trial=opt.n_trials if opt.status == "completed" else 0,
        total_trials=opt.n_trials,
        best_score=round(opt.best_score or 0, 6),
        best_params=opt.best_params or {},
        elapsed_seconds=0.0,
    )


@router.get("/{opt_id}", response_model=OptimizationResponse)
def get_optimization_result(
    opt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get full optimization results."""
    opt = db.query(Optimization).filter(Optimization.id == opt_id).first()
    if not opt:
        raise HTTPException(status_code=404, detail="Optimization not found")

    history = [
        TrialResult(
            trial_number=t.get("trial_number", i),
            params=t.get("params", {}),
            score=t.get("score", 0),
            stats=t.get("stats", {}),
        )
        for i, t in enumerate(opt.history or [])
    ]

    # Get param importance from in-memory if still cached
    importance = {}
    if opt_id in _running_optimizations:
        importance = _running_optimizations[opt_id].get("param_importance", {})

    return OptimizationResponse(
        id=opt.id,
        strategy_id=opt.strategy_id,
        status=opt.status,
        objective=opt.objective,
        n_trials=opt.n_trials,
        best_params=opt.best_params or {},
        best_score=round(opt.best_score or 0, 6),
        history=history,
        param_importance=importance,
    )


@router.post("/{opt_id}/apply", response_model=dict)
def apply_best_params(
    opt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Apply best optimization params back to the strategy."""
    opt = db.query(Optimization).filter(Optimization.id == opt_id).first()
    if not opt or opt.status != "completed":
        raise HTTPException(status_code=400, detail="Optimization not completed")

    strategy = (
        db.query(Strategy)
        .filter(
            Strategy.id == opt.strategy_id,
            or_(Strategy.creator_id == current_user.id, Strategy.is_system == True),
        )
        .first()
    )
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    # Apply best params to strategy config
    import copy
    from app.services.optimize.engine import _set_nested

    config = {
        "indicators": copy.deepcopy(strategy.indicators or []),
        "entry_rules": copy.deepcopy(strategy.entry_rules or []),
        "exit_rules": copy.deepcopy(strategy.exit_rules or []),
        "risk_params": copy.deepcopy(strategy.risk_params or {}),
        "filters": copy.deepcopy(strategy.filters or {}),
    }

    for path, value in (opt.best_params or {}).items():
        try:
            _set_nested(config, path, value)
        except (KeyError, IndexError, TypeError):
            continue

    strategy.indicators = config["indicators"]
    strategy.entry_rules = config["entry_rules"]
    strategy.exit_rules = config["exit_rules"]
    strategy.risk_params = config["risk_params"]
    strategy.filters = config["filters"]
    db.commit()

    return {"message": "Best parameters applied to strategy", "params": opt.best_params}


@router.delete("/{opt_id}")
def delete_optimization(
    opt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    opt = db.query(Optimization).filter(Optimization.id == opt_id).first()
    if not opt:
        raise HTTPException(status_code=404, detail="Optimization not found")
    db.delete(opt)
    db.commit()
    if opt_id in _running_optimizations:
        del _running_optimizations[opt_id]
    return {"message": "Deleted"}


@router.get("", response_model=list[OptimizationListItem])
def list_optimizations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all optimizations for the current user's strategies (including system)."""
    strategies = (
        db.query(Strategy)
        .filter(or_(Strategy.creator_id == current_user.id, Strategy.is_system == True))
        .all()
    )
    strategy_ids = [s.id for s in strategies]
    strategy_names = {s.id: s.name for s in strategies}

    if not strategy_ids:
        return []

    opts = (
        db.query(Optimization)
        .filter(Optimization.strategy_id.in_(strategy_ids))
        .order_by(Optimization.created_at.desc())
        .limit(50)
        .all()
    )

    return [
        OptimizationListItem(
            id=o.id,
            strategy_id=o.strategy_id,
            strategy_name=strategy_names.get(o.strategy_id, "Unknown"),
            objective=o.objective,
            n_trials=o.n_trials,
            status=o.status,
            best_score=round(o.best_score or 0, 6),
            created_at=o.created_at.isoformat() if o.created_at else "",
        )
        for o in opts
    ]
