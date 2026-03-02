"""
Phase-based optimization API.

A "chain" is a series of sequential optimization phases:
  - Phase 1: optimize entry params  (e.g. indicator periods, entry method)
  - Phase 2: freeze Phase 1 best_params, optimize exit/risk params
  - Phase N: freeze all previous best params, optimize remaining params

Each phase is a row in `optimization_phases` with a shared `chain_id`.
"""
import copy
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db, SessionLocal
from app.core.auth import get_current_user
from app.models.user import User
from app.models.strategy import Strategy
from app.models.datasource import DataSource
from app.models.optimization_phase import OptimizationPhase
from app.services.optimize.engine import OptimizerEngine, ParamSpec, Bar
from app.api.backtest import _load_bars_from_csv

router = APIRouter(prefix="/api/optimize/phase", tags=["optimization-phase"])

# ── Pydantic schemas ──────────────────────────────────────────────────────────

class PhaseParamSpec(BaseModel):
    param_path: str
    param_type: str = "float"
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    step: Optional[float] = None
    label: str = ""


class PhaseRunRequest(BaseModel):
    """Start the very first phase of a new chain."""
    strategy_id: int
    datasource_id: int
    param_space: list[PhaseParamSpec]
    objective: str = "sharpe_ratio"
    n_trials: int = 50
    method: str = "bayesian"
    min_trades: int = 30
    initial_balance: float = 10000.0
    spread_points: float = 0.0
    commission_per_lot: float = 0.0
    point_value: float = 1.0
    # Optionally supply frozen params for phase 1 (rare, but allowed)
    frozen_params: Optional[dict] = None


class PhaseNextRequest(BaseModel):
    """Start the next phase in an existing chain."""
    param_space: list[PhaseParamSpec]
    objective: str = "sharpe_ratio"
    n_trials: int = 50
    method: str = "bayesian"
    min_trades: int = 30
    # Which best_params from previous phases to freeze
    # If None, automatically freeze ALL best_params from all previous phases
    extra_frozen: Optional[dict] = None


class PhaseTrialItem(BaseModel):
    trial_number: int
    params: dict
    score: float
    stats: dict


class PhaseResponse(BaseModel):
    id: int
    chain_id: str
    phase_number: int
    strategy_id: Optional[int]
    datasource_id: Optional[int]
    objective: str
    n_trials: int
    method: str
    min_trades: int
    param_space: Optional[list]
    frozen_params: Optional[dict]
    status: str
    best_params: Optional[dict]
    best_score: Optional[float]
    param_importance: Optional[dict]
    history: Optional[list]
    created_at: str
    completed_at: Optional[str]


# ── In-memory progress tracking ───────────────────────────────────────────────

_running_phases: dict[int, dict] = {}


# ── Background thread ─────────────────────────────────────────────────────────

def _run_phase_thread(phase_id: int):
    """Background thread that runs a single phase's optimization."""
    db: Session = SessionLocal()
    try:
        phase = db.query(OptimizationPhase).filter(OptimizationPhase.id == phase_id).first()
        if not phase:
            return

        # Load bars
        ds = db.query(DataSource).filter(DataSource.id == phase.datasource_id).first()
        if not ds:
            _update_phase_status(db, phase, "failed")
            return

        bars = _load_bars_from_csv(ds.filepath)
        if not bars:
            _update_phase_status(db, phase, "failed")
            return

        # Load strategy config
        strat = db.query(Strategy).filter(Strategy.id == phase.strategy_id).first()
        if not strat:
            _update_phase_status(db, phase, "failed")
            return
        strategy_config = _build_strategy_config(strat)

        # Build param specs
        param_specs = []
        for spec_dict in (phase.param_space or []):
            param_specs.append(ParamSpec(
                param_path=spec_dict["param_path"],
                param_type=spec_dict.get("param_type", "float"),
                min_val=spec_dict.get("min_val"),
                max_val=spec_dict.get("max_val"),
                step=spec_dict.get("step"),
                label=spec_dict.get("label", spec_dict["param_path"]),
            ))

        # Progress callback
        progress_state = {"trial": 0}

        def progress_cb(trial_num: int, total: int, best: float, params: dict):
            progress_state["trial"] = trial_num
            _running_phases[phase_id] = {
                "current_trial": trial_num,
                "total_trials": total,
                "best_score": best,
                "progress": trial_num / max(total, 1) * 100,
            }

        engine = OptimizerEngine(
            bars=bars,
            strategy_config=strategy_config,
            param_specs=param_specs,
            objective=phase.objective,
            n_trials=phase.n_trials,
            method=phase.method,
            initial_balance=phase.initial_balance,
            spread_points=phase.spread_points,
            commission_per_lot=phase.commission_per_lot,
            point_value=phase.point_value,
            progress_callback=progress_cb,
            min_trades=phase.min_trades,
            frozen_params=phase.frozen_params or {},
        )

        result = engine.run()

        # Persist results
        phase.best_params = result.best_params
        phase.best_score = result.best_score
        phase.param_importance = result.param_importance
        phase.history = [
            {"trial_number": t.trial_number, "params": t.params, "score": t.score, "stats": t.stats}
            for t in result.history
        ]
        phase.status = "completed"
        phase.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception(f"Phase {phase_id} failed: {exc}")
        try:
            phase2 = db.query(OptimizationPhase).filter(OptimizationPhase.id == phase_id).first()
            if phase2:
                phase2.status = "failed"
                db.commit()
        except Exception:
            pass
    finally:
        _running_phases.pop(phase_id, None)
        db.close()


def _update_phase_status(db: Session, phase: OptimizationPhase, status: str):
    phase.status = status
    db.commit()


def _build_strategy_config(strat: Strategy) -> dict:
    """Build the strategy config dict from a Strategy ORM object."""
    return {
        "strategy_type": strat.strategy_type or "",
        "indicators": copy.deepcopy(strat.indicators or []),
        "entry_rules": copy.deepcopy(strat.entry_rules or []),
        "exit_rules": copy.deepcopy(strat.exit_rules or []),
        "filters": copy.deepcopy(strat.filters or {}),
        "risk_params": copy.deepcopy(strat.risk_params or {}),
        "settings_values": copy.deepcopy(strat.settings_values or {}),
        "settings_schema": copy.deepcopy(strat.settings_schema or []),
    }


def _phase_to_response(p: OptimizationPhase) -> PhaseResponse:
    return PhaseResponse(
        id=p.id,
        chain_id=p.chain_id,
        phase_number=p.phase_number,
        strategy_id=p.strategy_id,
        datasource_id=p.datasource_id,
        objective=p.objective,
        n_trials=p.n_trials,
        method=p.method,
        min_trades=p.min_trades,
        param_space=p.param_space,
        frozen_params=p.frozen_params,
        status=p.status,
        best_params=p.best_params,
        best_score=p.best_score,
        param_importance=p.param_importance,
        history=p.history,
        created_at=p.created_at.isoformat() if p.created_at else "",
        completed_at=p.completed_at.isoformat() if p.completed_at else None,
    )


# ── API Endpoints ─────────────────────────────────────────────────────────────

@router.post("/run", response_model=PhaseResponse)
def start_phase_chain(
    payload: PhaseRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start a brand-new phase chain (Phase 1)."""
    # Validate datasource and strategy exist
    if not db.query(DataSource).filter(DataSource.id == payload.datasource_id).first():
        raise HTTPException(status_code=404, detail="DataSource not found")
    if not db.query(Strategy).filter(Strategy.id == payload.strategy_id).first():
        raise HTTPException(status_code=404, detail="Strategy not found")

    chain_id = str(uuid.uuid4())

    phase = OptimizationPhase(
        chain_id=chain_id,
        phase_number=1,
        strategy_id=payload.strategy_id,
        datasource_id=payload.datasource_id,
        objective=payload.objective,
        n_trials=payload.n_trials,
        method=payload.method,
        min_trades=payload.min_trades,
        param_space=[s.model_dump() for s in payload.param_space],
        frozen_params=payload.frozen_params or {},
        initial_balance=payload.initial_balance,
        spread_points=payload.spread_points,
        commission_per_lot=payload.commission_per_lot,
        point_value=payload.point_value,
        status="running",
    )
    db.add(phase)
    db.commit()
    db.refresh(phase)

    t = threading.Thread(target=_run_phase_thread, args=(phase.id,), daemon=True)
    t.start()

    return _phase_to_response(phase)


@router.get("/chain/{chain_id}", response_model=list[PhaseResponse])
def get_chain(
    chain_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all phases in a chain, ordered by phase_number."""
    phases = (
        db.query(OptimizationPhase)
        .filter(OptimizationPhase.chain_id == chain_id)
        .order_by(OptimizationPhase.phase_number)
        .all()
    )
    if not phases:
        raise HTTPException(status_code=404, detail="Chain not found")
    return [_phase_to_response(p) for p in phases]


@router.post("/chain/{chain_id}/next", response_model=PhaseResponse)
def add_next_phase(
    chain_id: str,
    payload: PhaseNextRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Add the next phase to an existing chain.

    Automatically collects ALL best_params from every completed previous phase
    and merges them into `frozen_params` for this new phase, ensuring previous
    discoveries are locked in. `payload.extra_frozen` can override or supplement.
    """
    phases = (
        db.query(OptimizationPhase)
        .filter(OptimizationPhase.chain_id == chain_id)
        .order_by(OptimizationPhase.phase_number)
        .all()
    )
    if not phases:
        raise HTTPException(status_code=404, detail="Chain not found")

    last_phase = phases[-1]
    if last_phase.status not in ("completed",):
        raise HTTPException(
            status_code=400,
            detail=f"Previous phase is '{last_phase.status}' — must be 'completed' before adding next phase.",
        )

    # Accumulate frozen params from ALL previous phases
    accumulated_frozen: dict = {}
    for p in phases:
        if p.best_params:
            accumulated_frozen.update(p.best_params)
    # Allow caller to add extra frozen or override
    if payload.extra_frozen:
        accumulated_frozen.update(payload.extra_frozen)

    new_phase = OptimizationPhase(
        chain_id=chain_id,
        phase_number=last_phase.phase_number + 1,
        strategy_id=last_phase.strategy_id,
        datasource_id=last_phase.datasource_id,
        objective=payload.objective,
        n_trials=payload.n_trials,
        method=payload.method,
        min_trades=payload.min_trades,
        param_space=[s.model_dump() for s in payload.param_space],
        frozen_params=accumulated_frozen,
        initial_balance=last_phase.initial_balance,
        spread_points=last_phase.spread_points,
        commission_per_lot=last_phase.commission_per_lot,
        point_value=last_phase.point_value,
        status="running",
    )
    db.add(new_phase)
    db.commit()
    db.refresh(new_phase)

    t = threading.Thread(target=_run_phase_thread, args=(new_phase.id,), daemon=True)
    t.start()

    return _phase_to_response(new_phase)


@router.get("/chain/{chain_id}/{phase_id}/status")
def get_phase_status(
    chain_id: str,
    phase_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return live progress for a running phase (polls every ~1s)."""
    phase = db.query(OptimizationPhase).filter(
        OptimizationPhase.id == phase_id,
        OptimizationPhase.chain_id == chain_id,
    ).first()
    if not phase:
        raise HTTPException(status_code=404, detail="Phase not found")

    live = _running_phases.get(phase_id, {})
    return {
        "id": phase.id,
        "status": phase.status if phase.status != "running" else "running",
        "progress": live.get("progress", 0.0),
        "current_trial": live.get("current_trial", 0),
        "total_trials": live.get("total_trials", phase.n_trials),
        "best_score": live.get("best_score", -1e18),
    }


@router.get("/chains", response_model=list[dict])
def list_chains(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a summary of all phase chains (latest phase per chain)."""
    phases = (
        db.query(OptimizationPhase)
        .order_by(OptimizationPhase.chain_id, OptimizationPhase.phase_number)
        .all()
    )
    # Group by chain_id
    chains: dict[str, list[OptimizationPhase]] = {}
    for p in phases:
        chains.setdefault(p.chain_id, []).append(p)

    result = []
    for cid, chain_phases in chains.items():
        last = chain_phases[-1]
        result.append({
            "chain_id": cid,
            "n_phases": len(chain_phases),
            "strategy_id": last.strategy_id,
            "datasource_id": last.datasource_id,
            "latest_phase": last.phase_number,
            "latest_status": last.status,
            "latest_score": last.best_score,
            "created_at": chain_phases[0].created_at.isoformat() if chain_phases[0].created_at else "",
        })

    return sorted(result, key=lambda x: x["created_at"], reverse=True)
