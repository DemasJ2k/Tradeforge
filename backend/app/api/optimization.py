"""
Optimization API endpoints.
Runs optimization in background threads with progress tracking.
"""
import copy
import time
import threading
from datetime import datetime, timezone
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
    RobustnessRequest,
    RobustnessResponse,
    RobustnessWindowResult,
    TradeLogResponse,
    TradeLogEntry,
    TradeAnalysis,
)
from app.services.optimize.engine import (
    OptimizerEngine, ParamSpec, Bar, _set_nested,
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
    min_trades: int = 30,
    # Phase 6 params
    symbol: str = "UNKNOWN",
    max_workers: int = 0,
    early_stop_patience: int = 0,
    time_budget_seconds: float = 0,
    max_dd_abort: float = 0,
    user_id: int = 0,
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
            min_trades=min_trades,
            # Phase 6 params
            symbol=symbol,
            max_workers=max_workers,
            early_stop_patience=early_stop_patience,
            time_budget_seconds=time_budget_seconds,
            max_dd_abort=max_dd_abort,
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
                opt.param_importance = result.param_importance
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

        # Fire notification
        if user_id:
            try:
                import asyncio
                from app.services.notification import notify
                elapsed = time.time() - _running_optimizations.get(opt_id, {}).get("start_time", time.time())
                _ndb = SessionLocal()
                try:
                    asyncio.run(notify(
                        _ndb, user_id,
                        f"Optimization completed – {n_trials} trials",
                        f"Optimization finished in {elapsed:.0f}s. "
                        f"Best {objective}: {result.best_score:.4f}",
                    ))
                finally:
                    _ndb.close()
            except Exception:
                pass

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
        datasource_id=payload.datasource_id,
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
        method=payload.method,
        walk_forward=payload.walk_forward,
        min_trades=payload.min_trades,
        status="running",
    )
    db.add(opt)
    db.commit()
    db.refresh(opt)

    # Resolve symbol from datasource
    symbol = getattr(datasource, "symbol", None) or "UNKNOWN"

    # Phase 6 optional params from payload (with safe defaults)
    max_workers = getattr(payload, "max_workers", 0)
    early_stop_patience = getattr(payload, "early_stop_patience", 0)
    time_budget_seconds = getattr(payload, "time_budget_seconds", 0)
    max_dd_abort = getattr(payload, "max_dd_abort", 0)

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
            payload.secondary_operator, payload.min_trades,
            # Phase 6 params
            symbol, max_workers, early_stop_patience,
            time_budget_seconds, max_dd_abort,
            current_user.id,
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

    # Sync mss_config params back to settings_values
    mss = config.get("filters", {}).get("mss_config")
    if mss:
        sv = dict(strategy.settings_values or {})
        sv.update({k: v for k, v in mss.items()})
        strategy.settings_values = sv

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


# ─── Robustness Test ────────────────────────────────────────

@router.post("/{opt_id}/robustness", response_model=RobustnessResponse)
def run_robustness_test(
    opt_id: int,
    payload: RobustnessRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run the best params across N sliding windows to test robustness."""
    opt = db.query(Optimization).filter(Optimization.id == opt_id).first()
    if not opt or opt.status != "completed":
        raise HTTPException(status_code=404, detail="Completed optimization not found")
    if not opt.best_params:
        raise HTTPException(status_code=400, detail="No best params to test")

    # Resolve strategy + datasource
    strategy = db.query(Strategy).filter(Strategy.id == opt.strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    # Use the datasource stored on the optimization record
    datasource = None
    if getattr(opt, "datasource_id", None):
        datasource = db.query(DataSource).filter(DataSource.id == opt.datasource_id).first()
    if not datasource:
        # Fallback: try first datasource matching the strategy's recent optimizations
        datasource = db.query(DataSource).order_by(DataSource.created_at.desc()).first()
    if not datasource:
        raise HTTPException(status_code=404, detail="No data source found for this optimization")

    p = Path(datasource.filepath)
    if not p.exists():
        p = Path(settings.UPLOAD_DIR) / datasource.filename
    if not p.exists():
        raise HTTPException(status_code=404, detail="CSV file not found on disk")

    bars_all = _load_bars_from_csv(str(p))
    symbol = datasource.symbol or "UNKNOWN"

    if len(bars_all) < 200:
        raise HTTPException(status_code=400, detail="Not enough data for robustness test")

    # Build strategy config with best params applied
    strategy_type = getattr(strategy, "strategy_type", "builder") or "builder"
    base_config = {
        "indicators": copy.deepcopy(strategy.indicators or []),
        "entry_rules": copy.deepcopy(strategy.entry_rules or []),
        "exit_rules": copy.deepcopy(strategy.exit_rules or []),
        "risk_params": copy.deepcopy(strategy.risk_params or {}),
        "filters": copy.deepcopy(strategy.filters or {}),
    }
    if strategy_type in ("python", "json") and getattr(strategy, "file_path", None):
        base_config["_file_strategy"] = {
            "strategy_type": strategy_type,
            "file_path": strategy.file_path,
            "settings_values": getattr(strategy, "settings_values", None) or {},
        }
    for path, value in (opt.best_params or {}).items():
        try:
            _set_nested(base_config, path, value)
        except Exception:
            pass

    n = len(bars_all)
    window_size = max(100, int(n * payload.window_pct / 100))
    step = max(1, (n - window_size) // max(1, payload.n_windows - 1))

    # Criteria
    criteria = {
        "min_trades": payload.min_trades,
        "min_profit_factor": payload.min_profit_factor,
        "min_sharpe": payload.min_sharpe,
        "profitable": True,  # net_profit > 0
    }

    windows: list[RobustnessWindowResult] = []
    from app.services.backtest.v2_adapter import run_unified_backtest, v2_result_to_v1

    for i in range(payload.n_windows):
        start = i * step
        end = start + window_size
        if end > n:
            end = n
            start = max(0, end - window_size)
        if end - start < 50:
            break

        window_bars = bars_all[start:end]
        config = copy.deepcopy(base_config)

        try:
            if config.get("_file_strategy"):
                from app.services.strategy.file_runner import run_file_strategy
                fi = config["_file_strategy"]
                bars_raw = [
                    {"time": b.time, "open": b.open, "high": b.high,
                     "low": b.low, "close": b.close, "volume": b.volume}
                    for b in window_bars
                ]
                result = run_file_strategy(
                    strategy_type=fi["strategy_type"],
                    file_path=fi["file_path"],
                    settings_values=fi.get("settings_values", {}),
                    bars_raw=bars_raw,
                    initial_balance=payload.initial_balance,
                    spread_points=payload.spread_points,
                    commission_per_lot=payload.commission_per_lot,
                    point_value=payload.point_value,
                )
            else:
                # V2 unified backtest handles builder, gold_bt, and mss strategies
                v2_run = run_unified_backtest(
                    bars=window_bars,
                    strategy_config=config,
                    symbol=symbol,
                    initial_balance=payload.initial_balance,
                    spread_points=payload.spread_points,
                    commission_per_lot=payload.commission_per_lot,
                    point_value=payload.point_value,
                )
                result = v2_result_to_v1(v2_run, payload.initial_balance, len(window_bars))
        except Exception as exc:
            result = None

        if result is None:
            continue

        dt_from = datetime.fromtimestamp(window_bars[0].time, tz=timezone.utc).strftime("%Y-%m-%d") if window_bars else ""
        dt_to = datetime.fromtimestamp(window_bars[-1].time, tz=timezone.utc).strftime("%Y-%m-%d") if window_bars else ""

        passed = (
            result.total_trades >= payload.min_trades
            and result.net_profit > 0
            and result.profit_factor >= payload.min_profit_factor
            and result.sharpe_ratio >= payload.min_sharpe
        )

        windows.append(RobustnessWindowResult(
            window_index=i,
            date_from=dt_from,
            date_to=dt_to,
            n_bars=end - start,
            total_trades=result.total_trades,
            net_profit=round(result.net_profit, 2),
            sharpe_ratio=round(result.sharpe_ratio, 4),
            profit_factor=round(result.profit_factor if result.profit_factor < 100 else 0, 4),
            win_rate=round(result.win_rate, 2),
            max_drawdown_pct=round(result.max_drawdown_pct, 2),
            sqn=round(getattr(result, "sqn", 0.0), 4),
            passed=passed,
        ))

    passed_count = sum(1 for w in windows if w.passed)
    pass_rate = round(passed_count / len(windows) * 100, 1) if windows else 0.0

    # Persist robustness result
    try:
        opt.robustness_result = {
            "n_windows": len(windows),
            "windows_passed": passed_count,
            "pass_rate": pass_rate,
            "windows": [w.model_dump() for w in windows],
            "criteria": criteria,
        }
        db.commit()
    except Exception:
        pass

    return RobustnessResponse(
        opt_id=opt_id,
        n_windows=len(windows),
        windows_passed=passed_count,
        pass_rate=pass_rate,
        windows=windows,
        criteria=criteria,
    )


# ─── Trade Log Export ───────────────────────────────────────

@router.get("/{opt_id}/trades", response_model=TradeLogResponse)
def get_trade_log(
    opt_id: int,
    top_n: int = 1,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return trade log for the top_n-th best trial with by-hour/day analysis."""
    opt = db.query(Optimization).filter(Optimization.id == opt_id).first()
    if not opt or opt.status != "completed":
        raise HTTPException(status_code=404, detail="Completed optimization not found")

    history = opt.history or []
    if not history:
        raise HTTPException(status_code=400, detail="No trial history")

    sorted_trials = sorted(history, key=lambda t: t.get("score", -1e18), reverse=True)
    top_n = max(1, min(top_n, len(sorted_trials)))
    trial = sorted_trials[top_n - 1]

    # Replay the trial to get individual trades
    strategy = db.query(Strategy).filter(Strategy.id == opt.strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    # Use the datasource stored on the optimization record
    trade_ds = None
    if getattr(opt, "datasource_id", None):
        trade_ds = db.query(DataSource).filter(DataSource.id == opt.datasource_id).first()
    if not trade_ds:
        trade_ds = db.query(DataSource).order_by(DataSource.created_at.desc()).first()
    if not trade_ds:
        raise HTTPException(status_code=400, detail="No data available to replay")

    tp = Path(trade_ds.filepath)
    if not tp.exists():
        tp = Path(settings.UPLOAD_DIR) / trade_ds.filename
    if not tp.exists():
        raise HTTPException(status_code=400, detail="CSV file not found on disk")

    bars_all = _load_bars_from_csv(str(tp))
    trade_symbol = trade_ds.symbol or "UNKNOWN"

    if not bars_all:
        raise HTTPException(status_code=400, detail="No data available to replay")

    strategy_type = getattr(strategy, "strategy_type", "builder") or "builder"
    config = {
        "indicators": copy.deepcopy(strategy.indicators or []),
        "entry_rules": copy.deepcopy(strategy.entry_rules or []),
        "exit_rules": copy.deepcopy(strategy.exit_rules or []),
        "risk_params": copy.deepcopy(strategy.risk_params or {}),
        "filters": copy.deepcopy(strategy.filters or {}),
    }
    if strategy_type in ("python", "json") and getattr(strategy, "file_path", None):
        config["_file_strategy"] = {
            "strategy_type": strategy_type,
            "file_path": strategy.file_path,
            "settings_values": getattr(strategy, "settings_values", None) or {},
        }
    for path, value in (trial.get("params") or {}).items():
        try:
            _set_nested(config, path, value)
        except Exception:
            pass

    from app.services.backtest.v2_adapter import run_unified_backtest, v2_result_to_v1
    try:
        if config.get("_file_strategy"):
            from app.services.strategy.file_runner import run_file_strategy
            fi = config["_file_strategy"]
            bars_raw = [
                {"time": b.time, "open": b.open, "high": b.high,
                 "low": b.low, "close": b.close, "volume": b.volume}
                for b in bars_all
            ]
            result = run_file_strategy(
                strategy_type=fi["strategy_type"],
                file_path=fi["file_path"],
                settings_values=fi.get("settings_values", {}),
                bars_raw=bars_raw,
                initial_balance=10000.0,
                spread_points=0.0,
                commission_per_lot=0.0,
                point_value=1.0,
            )
        else:
            # V2 unified backtest handles builder, gold_bt, and mss strategies
            v2_run = run_unified_backtest(
                bars=bars_all,
                strategy_config=config,
                symbol=trade_symbol,
            )
            result = v2_result_to_v1(v2_run, 10000.0, len(bars_all))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Replay failed: {exc}")

    trades = result.trades or []

    # Build by-hour analysis
    hour_data: dict[str, dict] = {}
    day_data: dict[str, dict] = {}
    dir_data: dict[str, dict] = {}
    weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    for t in trades:
        if not t.exit_time:
            continue
        dt = datetime.fromtimestamp(t.exit_time, tz=timezone.utc)
        h = str(dt.hour)
        d = weekday_names[dt.weekday()]
        dir_key = t.direction

        for bucket, key in [(hour_data, h), (day_data, d), (dir_data, dir_key)]:
            if key not in bucket:
                bucket[key] = {"trades": 0, "net_profit": 0.0, "wins": 0}
            bucket[key]["trades"] += 1
            bucket[key]["net_profit"] = round(bucket[key]["net_profit"] + t.pnl, 2)
            if t.pnl > 0:
                bucket[key]["wins"] += 1

    def _summarise(bucket: dict) -> dict:
        return {
            k: {
                "trades": v["trades"],
                "net_profit": v["net_profit"],
                "win_rate": round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0,
            }
            for k, v in bucket.items()
        }

    return TradeLogResponse(
        opt_id=opt_id,
        trial_number=trial.get("trial_number", 0),
        params=trial.get("params", {}),
        score=trial.get("score", 0.0),
        total_trades=len(trades),
        trades=[
            TradeLogEntry(
                entry_time=t.entry_time,
                exit_time=t.exit_time,
                direction=t.direction,
                entry_price=t.entry_price,
                exit_price=t.exit_price,
                pnl=round(t.pnl, 2),
                exit_reason=t.exit_reason,
            )
            for t in trades
        ],
        analysis=TradeAnalysis(
            by_hour=_summarise(hour_data),
            by_day=_summarise(day_data),
            by_direction=_summarise(dir_data),
        ),
    )
