import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.config import settings
from app.models.user import User
from app.models.strategy import Strategy
from app.models.datasource import DataSource
from app.models.backtest import Backtest
from app.schemas.backtest import (
    BacktestRequest,
    BacktestResponse,
    BacktestStats,
    TradeResult,
    WalkForwardRequest,
    WalkForwardResponse,
    WFWindowStats,
)
from app.services.backtest.engine import BacktestEngine, Bar
from app.services.backtest.strategy_backtester import backtest_mss, backtest_gold_bt

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

# Column alias sets for CSV parsing (same as datasource.py)
DATETIME_ALIASES = {"time", "date", "datetime", "timestamp", "<time>"}
OPEN_ALIASES = {"open", "o", "<open>"}
HIGH_ALIASES = {"high", "h", "<high>"}
LOW_ALIASES = {"low", "l", "<low>"}
CLOSE_ALIASES = {"close", "c", "<close>"}
VOLUME_ALIASES = {"volume", "vol", "v", "tick_volume", "<vol>", "<tickvol>", "<real_vol>"}

DATETIME_FORMATS = [
    "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
    "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
]


def _parse_datetime(val: str) -> float:
    """Try multiple datetime formats, return unix timestamp."""
    val = val.strip()
    try:
        return float(val)
    except ValueError:
        pass
    for fmt in DATETIME_FORMATS:
        try:
            dt = datetime.strptime(val, fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {val}")


def _load_bars_from_csv(file_path: str) -> list[Bar]:
    """Load bars from a CSV file."""
    bars = []
    with open(file_path, "r", encoding="utf-8-sig") as f:
        # Detect delimiter
        sample = f.read(4096)
        f.seek(0)

        delimiter = ","
        if sample.count("\t") > sample.count(","):
            delimiter = "\t"
        elif sample.count(";") > sample.count(","):
            delimiter = ";"

        reader = csv.DictReader(f, delimiter=delimiter)
        if not reader.fieldnames:
            return bars

        headers = {h.strip().lower(): h.strip() for h in reader.fieldnames}

        col_time = next((headers[k] for k in headers if k in DATETIME_ALIASES), None)
        col_open = next((headers[k] for k in headers if k in OPEN_ALIASES), None)
        col_high = next((headers[k] for k in headers if k in HIGH_ALIASES), None)
        col_low = next((headers[k] for k in headers if k in LOW_ALIASES), None)
        col_close = next((headers[k] for k in headers if k in CLOSE_ALIASES), None)
        col_vol = next((headers[k] for k in headers if k in VOLUME_ALIASES), None)

        if not all([col_time, col_open, col_high, col_low, col_close]):
            raise ValueError("CSV missing required OHLC columns")

        for row in reader:
            try:
                bars.append(Bar(
                    time=_parse_datetime(row[col_time]),
                    open=float(row[col_open]),
                    high=float(row[col_high]),
                    low=float(row[col_low]),
                    close=float(row[col_close]),
                    volume=float(row[col_vol]) if col_vol and row.get(col_vol) else 0.0,
                ))
            except (ValueError, KeyError):
                continue

    return bars


@router.post("/run", response_model=BacktestResponse)
def run_backtest(
    payload: BacktestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
        # Fallback: try UPLOAD_DIR / filename
        file_path = Path(settings.UPLOAD_DIR) / datasource.filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="CSV file not found on disk")

    # Load bars
    bars = _load_bars_from_csv(str(file_path))
    if len(bars) < 50:
        raise HTTPException(status_code=400, detail=f"Not enough data: {len(bars)} bars (need 50+)")

    # Route to appropriate backtest engine based on strategy type
    strategy_type = getattr(strategy, "strategy_type", "builder") or "builder"
    filters = strategy.filters or {}
    mss_config = filters.get("mss_config")
    gold_bt_config = filters.get("gold_bt_config")

    t0 = time.time()

    if strategy_type in ("python", "json") and getattr(strategy, "file_path", None):
        # File-based strategy — run via file_runner
        from app.services.strategy.file_runner import run_file_strategy
        result = run_file_strategy(
            strategy_type=strategy_type,
            file_path=strategy.file_path,
            settings_values=getattr(strategy, "settings_values", None) or {},
            bars_raw=bars,
            initial_balance=payload.initial_balance,
            spread_points=payload.spread_points,
            commission_per_lot=payload.commission_per_lot,
            point_value=payload.point_value,
        )
    elif mss_config:
        # Use dedicated MSS backtester (exact same logic as optimization script)
        result = backtest_mss(
            bars_raw=bars,
            mss_config=mss_config,
            initial_balance=payload.initial_balance,
            spread_points=payload.spread_points,
            commission_per_lot=payload.commission_per_lot,
            point_value=payload.point_value,
        )
    elif gold_bt_config:
        # Use dedicated Gold BT backtester (exact same logic as optimization script)
        result = backtest_gold_bt(
            bars_raw=bars,
            gold_config=gold_bt_config,
            initial_balance=payload.initial_balance,
            spread_points=payload.spread_points,
            commission_per_lot=payload.commission_per_lot,
            point_value=payload.point_value,
        )
    else:
        # Generic rule-based engine for user-created strategies
        strategy_config = {
            "indicators": strategy.indicators or [],
            "entry_rules": strategy.entry_rules or [],
            "exit_rules": strategy.exit_rules or [],
            "risk_params": strategy.risk_params or {},
            "filters": filters,
        }
        engine = BacktestEngine(
            bars=bars,
            strategy_config=strategy_config,
            initial_balance=payload.initial_balance,
            spread_points=payload.spread_points,
            commission_per_lot=payload.commission_per_lot,
            point_value=payload.point_value,
        )
        result = engine.run()

    elapsed = time.time() - t0

    # Save to DB
    bt = Backtest(
        strategy_id=strategy.id,
        symbol=datasource.symbol or "UNKNOWN",
        timeframe=datasource.timeframe or "",
        date_from=datasource.date_from or "",
        date_to=datasource.date_to or "",
        initial_balance=payload.initial_balance,
        status="completed",
        results={
            "stats": {
                "total_trades": result.total_trades,
                "winning_trades": result.winning_trades,
                "losing_trades": result.losing_trades,
                "win_rate": round(result.win_rate, 2),
                "gross_profit": round(result.gross_profit, 2),
                "gross_loss": round(result.gross_loss, 2),
                "net_profit": round(result.net_profit, 2),
                "profit_factor": round(result.profit_factor, 4),
                "max_drawdown": round(result.max_drawdown, 2),
                "max_drawdown_pct": round(result.max_drawdown_pct, 2),
                "avg_win": round(result.avg_win, 2),
                "avg_loss": round(result.avg_loss, 2),
                "largest_win": round(result.largest_win, 2),
                "largest_loss": round(result.largest_loss, 2),
                "avg_trade": round(result.avg_trade, 2),
                "sharpe_ratio": round(result.sharpe_ratio, 4),
                "expectancy": round(result.expectancy, 2),
                "total_bars": result.total_bars,
            },
            "elapsed_seconds": round(elapsed, 3),
        },
        creator_id=current_user.id,
    )
    db.add(bt)
    db.commit()
    db.refresh(bt)

    # Build response
    trades_out = [
        TradeResult(
            entry_bar=t.entry_bar,
            entry_time=t.entry_time,
            entry_price=round(t.entry_price, 5),
            direction=t.direction,
            size=t.size,
            stop_loss=round(t.stop_loss, 5),
            take_profit=round(t.take_profit, 5),
            exit_bar=t.exit_bar,
            exit_time=t.exit_time,
            exit_price=round(t.exit_price, 5) if t.exit_price else None,
            exit_reason=t.exit_reason,
            pnl=round(t.pnl, 2),
            pnl_pct=round(t.pnl_pct, 2),
        )
        for t in result.trades
    ]

    # Downsample equity curve if too large
    eq = result.equity_curve
    if len(eq) > 2000:
        step = len(eq) // 2000
        eq = eq[::step] + [eq[-1]]

    stats = BacktestStats(**bt.results["stats"])

    return BacktestResponse(
        id=bt.id,
        strategy_id=bt.strategy_id,
        datasource_id=payload.datasource_id,
        status="completed",
        stats=stats,
        trades=trades_out,
        equity_curve=[round(v, 2) for v in eq],
    )


@router.post("/walk-forward", response_model=WalkForwardResponse)
def run_walk_forward(
    payload: WalkForwardRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run walk-forward validation for realistic OOS performance."""
    from app.services.backtest.walk_forward import walk_forward_backtest

    # Load strategy
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

    # Determine strategy type
    filters = strategy.filters or {}
    mss_config = filters.get("mss_config")
    gold_bt_config = filters.get("gold_bt_config")

    if mss_config:
        strategy_type = "mss"
        config = mss_config
    elif gold_bt_config:
        strategy_type = "gold_bt"
        config = gold_bt_config
    else:
        raise HTTPException(
            status_code=400,
            detail="Walk-forward validation only supports MSS and Gold BT strategies",
        )

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
    if len(bars) < 200:
        raise HTTPException(status_code=400, detail=f"Need 200+ bars for walk-forward, got {len(bars)}")

    # Run walk-forward
    wf_result = walk_forward_backtest(
        bars=bars,
        strategy_type=strategy_type,
        strategy_config=config,
        n_folds=payload.n_folds,
        train_pct=payload.train_pct,
        mode=payload.mode,
        initial_balance=payload.initial_balance,
        spread_points=payload.spread_points,
        commission_per_lot=payload.commission_per_lot,
        point_value=payload.point_value,
    )

    # Build response
    window_stats = [
        WFWindowStats(
            fold=w.fold,
            train_bars=w.train_end - w.train_start,
            test_bars=w.test_end - w.test_start,
            train_stats=w.train_stats or {},
            test_stats=w.test_stats or {},
        )
        for w in wf_result.windows
    ]

    trades_out = [
        TradeResult(
            entry_bar=t.entry_bar,
            entry_time=t.entry_time,
            entry_price=round(t.entry_price, 5),
            direction=t.direction,
            size=t.size,
            stop_loss=round(t.stop_loss, 5),
            take_profit=round(t.take_profit, 5),
            exit_bar=t.exit_bar,
            exit_time=t.exit_time,
            exit_price=round(t.exit_price, 5) if t.exit_price else None,
            exit_reason=t.exit_reason,
            pnl=round(t.pnl, 2),
            pnl_pct=round(t.pnl_pct, 2),
        )
        for t in wf_result.oos_trades
    ]

    # Downsample equity
    eq = wf_result.oos_equity_curve
    if len(eq) > 2000:
        step = len(eq) // 2000
        eq = eq[::step] + [eq[-1]]

    return WalkForwardResponse(
        strategy_id=payload.strategy_id,
        datasource_id=payload.datasource_id,
        n_folds=wf_result.n_folds,
        mode=payload.mode,
        oos_total_trades=wf_result.oos_total_trades,
        oos_win_rate=wf_result.oos_win_rate,
        oos_net_profit=wf_result.oos_net_profit,
        oos_profit_factor=wf_result.oos_profit_factor,
        oos_max_drawdown=wf_result.oos_max_drawdown,
        oos_max_drawdown_pct=wf_result.oos_max_drawdown_pct,
        oos_sharpe_ratio=wf_result.oos_sharpe_ratio,
        oos_expectancy=wf_result.oos_expectancy,
        oos_avg_win=wf_result.oos_avg_win,
        oos_avg_loss=wf_result.oos_avg_loss,
        windows=window_stats,
        fold_win_rates=wf_result.fold_win_rates,
        fold_profit_factors=wf_result.fold_profit_factors,
        fold_net_profits=[round(p, 2) for p in wf_result.fold_net_profits],
        consistency_score=wf_result.consistency_score,
        oos_equity_curve=[round(v, 2) for v in eq],
        trades=trades_out,
    )


@router.get("", response_model=list[dict])
def list_backtests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    backtests = (
        db.query(Backtest)
        .filter(Backtest.creator_id == current_user.id)
        .order_by(Backtest.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": bt.id,
            "strategy_id": bt.strategy_id,
            "symbol": bt.symbol,
            "timeframe": bt.timeframe,
            "status": bt.status,
            "stats": bt.results.get("stats", {}) if bt.results else {},
            "created_at": bt.created_at.isoformat() if bt.created_at else "",
        }
        for bt in backtests
    ]
