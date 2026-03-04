import csv
import json
import logging
import math
import threading
import time
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
from app.services.backtest.engine import Bar  # Bar dataclass still used for CSV parsing
# V1 imports deprecated — Phase 1C: all strategies route through V2 unified runner


def _fire_notification(user_id: int, subject: str, body: str):
    """Send notification in background thread (fire-and-forget)."""
    def _run():
        try:
            import asyncio
            from app.services.notification import notify
            _db = SessionLocal()
            try:
                asyncio.run(notify(_db, user_id, subject, body))
            finally:
                _db.close()
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()
# from app.services.backtest.engine import BacktestEngine
# from app.services.backtest.strategy_backtester import backtest_mss, backtest_gold_bt

logger = logging.getLogger(__name__)

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

# Phase 1E: use robust timezone-aware parser
from app.services.backtest.v2.engine.data_validation import (
    parse_timestamp as _parse_ts_v2,
    validate_and_clean as _validate_bars,
    ValidationReport,
)


def _parse_datetime(val: str) -> float:
    """Try multiple datetime formats, return unix timestamp.

    Phase 1E: delegates to robust parse_timestamp() which handles
    timezone offsets, ISO 8601, Z suffix, and 11+ naive formats.
    Falls back to legacy loop for edge cases.
    """
    ts = _parse_ts_v2(val)
    if not math.isnan(ts):
        return ts
    # Legacy fallback (should rarely be needed)
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


def _resolve_csv_path(datasource) -> Path:
    """Resolve the CSV file path for a datasource.

    Handles:
      1. Original filepath (works locally)
      2. Fallback to UPLOAD_DIR / filename (original upload name)
      3. Search for files ending with filename in UPLOAD_DIR
         (handles timestamp-prefixed filenames on Render)
    """
    # Try original filepath
    fp = Path(datasource.filepath)
    if fp.exists():
        return fp

    upload_dir = Path(settings.UPLOAD_DIR)

    # Try UPLOAD_DIR / original filename
    fp = upload_dir / datasource.filename
    if fp.exists():
        return fp

    # Search for timestamp-prefixed files ending with original filename
    if upload_dir.exists():
        for f in upload_dir.iterdir():
            if f.is_file() and f.name.endswith(datasource.filename):
                return f

    raise FileNotFoundError(f"CSV file not found for datasource {datasource.id}: {datasource.filename}")


def _load_bars_from_csv(file_path: str, validate: bool = True) -> list[Bar]:
    """Load bars from a CSV file.

    Phase 1E: After loading, runs data validation to remove duplicates,
    fix OHLC violations, detect gaps, and ensure monotonic timestamps.
    """
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

    # Phase 1E: validate and clean
    if validate and bars:
        report = _validate_bars(bars)
        if not report.is_clean:
            logger.info(
                "CSV %s validation: %s",
                file_path.split("/")[-1].split("\\")[-1],
                report.summary(),
            )

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

    try:
        file_path = _resolve_csv_path(datasource)
    except FileNotFoundError:
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
    engine_version = getattr(payload, "engine_version", "v1") or "v1"

    t0 = time.time()

    # ── V2 Engine Path (always used — V1 redirects here too) ────────
    if True:  # Phase 1C: always route through V2 unified runner
        from app.services.backtest.v2_adapter import (
            run_v2_backtest, run_unified_backtest, v2_result_to_api_response,
            run_v2_portfolio_backtest, v2_portfolio_result_to_api_response,
        )

        # Build strategy config (same shape for all builder-type strategies)
        strategy_config = {
            "indicators": strategy.indicators or [],
            "entry_rules": strategy.entry_rules or [],
            "exit_rules": strategy.exit_rules or [],
            "risk_params": strategy.risk_params or {},
            "filters": {k: v for k, v in filters.items()
                        if k not in ("mss_config", "gold_bt_config")},
            # Python strategy support — pass type, file path, and settings
            "strategy_type": getattr(strategy, "strategy_type", "builder") or "builder",
            "file_path": getattr(strategy, "file_path", "") or "",
            "settings_values": getattr(strategy, "settings_values", {}) or {},
        }

        # If MSS/Gold BT, merge their config into risk_params/filters
        if mss_config:
            strategy_config["filters"]["mss_config"] = mss_config
        if gold_bt_config:
            strategy_config["filters"]["gold_bt_config"] = gold_bt_config

        # ── Check for multi-symbol portfolio mode (Phase 4) ─────────
        ds_ids = getattr(payload, "datasource_ids", None)
        is_portfolio = ds_ids and len(ds_ids) > 1

        if is_portfolio:
            # Load all datasources
            datasources_multi = (
                db.query(DataSource)
                .filter(DataSource.id.in_(ds_ids))
                .all()
            )
            if len(datasources_multi) < 2:
                raise HTTPException(status_code=400, detail="Need at least 2 datasources for portfolio mode")

            symbols_data = []
            total_bars_all = 0
            sym_names = []
            for ds in datasources_multi:
                try:
                    fp = _resolve_csv_path(ds)
                except FileNotFoundError:
                    raise HTTPException(status_code=404, detail=f"CSV not found: {ds.filename}")

                ds_bars = _load_bars_from_csv(str(fp))
                if len(ds_bars) < 50:
                    raise HTTPException(status_code=400, detail=f"Not enough data for {ds.symbol}: {len(ds_bars)} bars")

                pv = ds.point_value if ds.point_value else payload.point_value
                symbols_data.append({
                    "symbol": ds.symbol or f"SYM_{ds.id}",
                    "bars": ds_bars,
                    "point_value": pv,
                })
                total_bars_all = max(total_bars_all, len(ds_bars))
                sym_names.append(ds.symbol or f"SYM_{ds.id}")

            try:
                v2_result, portfolio_analytics = run_v2_portfolio_backtest(
                    symbols_data=symbols_data,
                    strategy_config=strategy_config,
                    initial_balance=payload.initial_balance,
                    spread_points=payload.spread_points,
                    commission_per_lot=payload.commission_per_lot,
                    slippage_pct=payload.slippage_pct,
                    commission_pct=payload.commission_pct,
                    margin_rate=payload.margin_rate,
                    use_fast_core=payload.use_fast_core,
                    bars_per_day=payload.bars_per_day,
                    tick_mode=payload.tick_mode,
                )
            except Exception as e:
                logger.exception("V2 portfolio backtest failed")
                raise HTTPException(status_code=500, detail=f"V2 portfolio error: {str(e)}")

            elapsed = time.time() - t0
            api_data = v2_portfolio_result_to_api_response(
                v2_result, portfolio_analytics, payload.initial_balance, total_bars_all,
            )

            bt = Backtest(
                strategy_id=strategy.id,
                symbol=",".join(sym_names),
                timeframe=datasources_multi[0].timeframe or "",
                date_from=datasources_multi[0].date_from or "",
                date_to=datasources_multi[0].date_to or "",
                initial_balance=payload.initial_balance,
                status="completed",
                results={
                    "engine_version": "v2",
                    "mode": "portfolio",
                    "symbols": sym_names,
                    "stats": api_data["stats"],
                    "v2_stats": api_data["v2_stats"],
                    "elapsed_seconds": round(elapsed, 3),
                },
                creator_id=current_user.id,
            )
            db.add(bt)
            db.commit()
            db.refresh(bt)

            stats = BacktestStats(**api_data["stats"])
            trades_out = [TradeResult(**t) for t in api_data["trades"]]

            return BacktestResponse(
                id=bt.id,
                strategy_id=bt.strategy_id,
                datasource_id=payload.datasource_id,
                status="completed",
                stats=stats,
                trades=trades_out,
                equity_curve=api_data["equity_curve"],
                engine_version="v2",
                v2_stats=api_data["v2_stats"],
                tearsheet=api_data["tearsheet"],
                elapsed_seconds=api_data["elapsed_seconds"],
                portfolio_analytics=api_data.get("portfolio_analytics"),
                symbols=sym_names,
            )

        # ── Single-symbol V2 (unified — handles builder, MSS, Gold BT) ─
        symbol = datasource.symbol or "ASSET"

        try:
            v2_result = run_unified_backtest(
                bars=bars,
                strategy_config=strategy_config,
                symbol=symbol,
                initial_balance=payload.initial_balance,
                spread_points=payload.spread_points,
                commission_per_lot=payload.commission_per_lot,
                point_value=payload.point_value,
                slippage_pct=payload.slippage_pct,
                commission_pct=payload.commission_pct,
                margin_rate=payload.margin_rate,
                use_fast_core=payload.use_fast_core,
                bars_per_day=payload.bars_per_day,
                tick_mode=payload.tick_mode,
            )
        except Exception as e:
            logger.exception("V2 backtest failed")
            raise HTTPException(status_code=500, detail=f"V2 engine error: {str(e)}")

        elapsed = time.time() - t0
        api_data = v2_result_to_api_response(v2_result, payload.initial_balance, len(bars))

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
                "engine_version": "v2",
                "stats": api_data["stats"],
                "v2_stats": api_data["v2_stats"],
                "trades": api_data["trades"],
                "equity_curve": api_data["equity_curve"],
                "elapsed_seconds": round(elapsed, 3),
            },
            creator_id=current_user.id,
        )
        db.add(bt)
        db.commit()
        db.refresh(bt)

        stats = BacktestStats(**api_data["stats"])
        trades_out = [TradeResult(**t) for t in api_data["trades"]]

        # Fire notification
        _fire_notification(
            current_user.id,
            f"Backtest completed – {symbol}",
            f"Backtest on {symbol} finished in {round(elapsed, 1)}s. "
            f"Net P/L: {api_data['stats'].get('net_profit', 0):.2f}, "
            f"Win rate: {api_data['stats'].get('win_rate', 0):.1f}%, "
            f"Trades: {api_data['stats'].get('total_trades', 0)}",
        )

        return BacktestResponse(
            id=bt.id,
            strategy_id=bt.strategy_id,
            datasource_id=payload.datasource_id,
            status="completed",
            stats=stats,
            trades=trades_out,
            equity_curve=api_data["equity_curve"],
            engine_version="v2",
            v2_stats=api_data["v2_stats"],
            tearsheet=api_data["tearsheet"],
            elapsed_seconds=api_data["elapsed_seconds"],
        )

    # V1 engine path removed — Phase 1C: all strategies route via V2 unified runner.
    # If we somehow reach here, it means the `if True:` block above didn't return.
    raise HTTPException(status_code=500, detail="Unexpected routing error")


@router.post("/run-v3", response_model=BacktestResponse)
def run_backtest_v3(
    payload: BacktestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run a backtest using the V3 engine (hybrid architecture)."""
    from app.services.backtest_engine.v3_adapter import (
        run_v3_backtest, v3_result_to_api_response,
    )

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

    try:
        file_path = _resolve_csv_path(datasource)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="CSV file not found on disk")

    bars = _load_bars_from_csv(str(file_path))
    if len(bars) < 50:
        raise HTTPException(status_code=400, detail=f"Not enough data: {len(bars)} bars (need 50+)")

    # Build strategy config
    filters = strategy.filters or {}
    strategy_config = {
        "indicators": strategy.indicators or [],
        "entry_rules": strategy.entry_rules or [],
        "exit_rules": strategy.exit_rules or [],
        "risk_params": strategy.risk_params or {},
        "filters": filters,
        # Python strategy support — pass type, file path, and settings
        "strategy_type": getattr(strategy, "strategy_type", "builder") or "builder",
        "file_path": getattr(strategy, "file_path", "") or "",
        "settings_values": getattr(strategy, "settings_values", {}) or {},
    }

    symbol = datasource.symbol or "ASSET"

    try:
        v3_result = run_v3_backtest(
            bars=bars,
            strategy_config=strategy_config,
            symbol=symbol,
            initial_balance=payload.initial_balance,
            spread_points=payload.spread_points,
            commission_per_lot=payload.commission_per_lot,
            point_value=payload.point_value,
            slippage_pct=payload.slippage_pct,
            margin_rate=payload.margin_rate,
            tick_mode=getattr(payload, "tick_mode", "ohlc_pessimistic"),
        )
    except Exception as e:
        logger.exception("V3 backtest failed")
        raise HTTPException(status_code=500, detail=f"V3 engine error: {str(e)}")

    elapsed = v3_result.execution_time_ms / 1000
    api_data = v3_result_to_api_response(v3_result, payload.initial_balance, len(bars))

    # Save to DB
    bt = Backtest(
        strategy_id=strategy.id,
        symbol=symbol,
        timeframe=datasource.timeframe or "",
        date_from=datasource.date_from or "",
        date_to=datasource.date_to or "",
        initial_balance=payload.initial_balance,
        status="completed",
        results={
            "engine_version": "v3",
            "stats": api_data["stats"],
            "v2_stats": api_data["v2_stats"],
            "trades": api_data["trades"],
            "equity_curve": api_data["equity_curve"],
            "elapsed_seconds": round(elapsed, 3),
        },
        creator_id=current_user.id,
    )
    db.add(bt)
    db.commit()
    db.refresh(bt)

    stats = BacktestStats(**api_data["stats"])
    trades_out = [TradeResult(**t) for t in api_data["trades"]]

    _fire_notification(
        current_user.id,
        f"Backtest completed – {symbol}",
        f"V3 backtest on {symbol} finished in {round(elapsed, 1)}s. "
        f"Net P/L: {api_data['stats'].get('net_profit', 0):.2f}, "
        f"Win rate: {api_data['stats'].get('win_rate', 0):.1f}%, "
        f"Trades: {api_data['stats'].get('total_trades', 0)}",
    )

    return BacktestResponse(
        id=bt.id,
        strategy_id=bt.strategy_id,
        datasource_id=payload.datasource_id,
        status="completed",
        stats=stats,
        trades=trades_out,
        equity_curve=api_data["equity_curve"],
        engine_version="v3",
        v2_stats=api_data["v2_stats"],
        tearsheet=api_data["tearsheet"],
        elapsed_seconds=api_data["elapsed_seconds"],
    )


@router.post("/walk-forward-v3", response_model=WalkForwardResponse)
def run_walk_forward_v3(
    payload: WalkForwardRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run walk-forward validation using V3 engine."""
    from app.services.backtest_engine.v3_adapter import run_v3_walk_forward

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

    strategy_config = {
        "indicators": strategy.indicators or [],
        "entry_rules": strategy.entry_rules or [],
        "exit_rules": strategy.exit_rules or [],
        "risk_params": strategy.risk_params or {},
        "filters": strategy.filters or {},
    }

    datasource = db.query(DataSource).filter(DataSource.id == payload.datasource_id).first()
    if not datasource:
        raise HTTPException(status_code=404, detail="Data source not found")

    try:
        file_path = _resolve_csv_path(datasource)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="CSV file not found on disk")

    bars = _load_bars_from_csv(str(file_path))
    if len(bars) < 200:
        raise HTTPException(status_code=400, detail=f"Need 200+ bars for walk-forward, got {len(bars)}")

    symbol = getattr(datasource, "symbol", None) or "UNKNOWN"

    wf_result = run_v3_walk_forward(
        bars=bars,
        strategy_config=strategy_config,
        symbol=symbol,
        n_folds=payload.n_folds,
        train_pct=payload.train_pct,
        mode=payload.mode,
        initial_balance=payload.initial_balance,
        spread_points=payload.spread_points,
        commission_per_lot=payload.commission_per_lot,
        point_value=payload.point_value,
    )

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
        TradeResult(**t) for t in wf_result.oos_trades
    ]

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


@router.post("/monte-carlo")
def run_monte_carlo(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run Monte Carlo simulation on a completed backtest."""
    from app.services.backtest_engine.v3_adapter import run_v3_monte_carlo

    backtest_id = payload.get("backtest_id")
    n_simulations = payload.get("n_simulations", 1000)

    if not backtest_id:
        raise HTTPException(400, "backtest_id required")

    bt = db.query(Backtest).filter(
        Backtest.id == backtest_id,
        Backtest.creator_id == current_user.id,
    ).first()
    if not bt:
        raise HTTPException(404, "Backtest not found")

    results = bt.results or {}
    trades = results.get("trades", [])
    if not trades:
        raise HTTPException(400, "No trades in backtest to simulate")

    mc_result = run_v3_monte_carlo(
        trades=trades,
        initial_balance=bt.initial_balance or 10000,
        n_simulations=n_simulations,
    )

    return {
        "n_simulations": mc_result.n_simulations,
        "final_equity": {
            "p5": mc_result.final_equity_p5,
            "p25": mc_result.final_equity_p25,
            "p50": mc_result.final_equity_p50,
            "p75": mc_result.final_equity_p75,
            "p95": mc_result.final_equity_p95,
        },
        "max_drawdown": {
            "p5": mc_result.max_dd_p5,
            "p25": mc_result.max_dd_p25,
            "p50": mc_result.max_dd_p50,
            "p75": mc_result.max_dd_p75,
            "p95": mc_result.max_dd_p95,
        },
        "max_drawdown_pct": {
            "p5": mc_result.max_dd_pct_p5,
            "p25": mc_result.max_dd_pct_p25,
            "p50": mc_result.max_dd_pct_p50,
            "p75": mc_result.max_dd_pct_p75,
            "p95": mc_result.max_dd_pct_p95,
        },
        "prob_ruin": mc_result.prob_ruin,
        "equity_paths": mc_result.equity_paths[:20],  # Limit for API
    }


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

    # Determine strategy type and build full config for V2 routing (Phase 6D)
    filters = strategy.filters or {}
    mss_config = filters.get("mss_config")
    gold_bt_config = filters.get("gold_bt_config")

    if mss_config:
        strategy_type = "mss"
    elif gold_bt_config:
        strategy_type = "gold_bt"
    else:
        strategy_type = "builder"

    # Build full strategy config (V2 unified runner detects type from this)
    strategy_config = {
        "indicators": strategy.indicators or [],
        "entry_rules": strategy.entry_rules or [],
        "exit_rules": strategy.exit_rules or [],
        "risk_params": strategy.risk_params or {},
        "filters": filters,
    }

    # Load datasource
    datasource = db.query(DataSource).filter(DataSource.id == payload.datasource_id).first()
    if not datasource:
        raise HTTPException(status_code=404, detail="Data source not found")

    try:
        file_path = _resolve_csv_path(datasource)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="CSV file not found on disk")

    bars = _load_bars_from_csv(str(file_path))
    if len(bars) < 200:
        raise HTTPException(status_code=400, detail=f"Need 200+ bars for walk-forward, got {len(bars)}")

    # Run walk-forward (Phase 6D: all strategy types supported via V2)
    symbol = getattr(datasource, "symbol", None) or "UNKNOWN"
    wf_result = walk_forward_backtest(
        bars=bars,
        strategy_type=strategy_type,
        strategy_config=strategy_config,
        n_folds=payload.n_folds,
        train_pct=payload.train_pct,
        mode=payload.mode,
        initial_balance=payload.initial_balance,
        spread_points=payload.spread_points,
        commission_per_lot=payload.commission_per_lot,
        point_value=payload.point_value,
        symbol=symbol,
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
        .filter(Backtest.deleted_at.is_(None))
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


@router.get("/{backtest_id}")
def get_backtest(
    backtest_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return full stored results for a single backtest."""
    bt = db.query(Backtest).filter(
        Backtest.id == backtest_id,
        Backtest.creator_id == current_user.id,
    ).first()
    if not bt:
        raise HTTPException(404, "Backtest not found")
    return {
        "id": bt.id,
        "strategy_id": bt.strategy_id,
        "symbol": bt.symbol,
        "timeframe": bt.timeframe,
        "date_from": bt.date_from,
        "date_to": bt.date_to,
        "initial_balance": bt.initial_balance,
        "status": bt.status,
        "results": bt.results or {},
        "created_at": bt.created_at.isoformat() if bt.created_at else "",
    }


@router.delete("/{backtest_id}")
def delete_backtest(
    backtest_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Soft-delete a single backtest run (move to recycle bin)."""
    bt = db.query(Backtest).filter(
        Backtest.id == backtest_id,
        Backtest.creator_id == current_user.id,
    ).first()
    if not bt:
        raise HTTPException(404, "Backtest not found")
    bt.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"message": "Moved to recycle bin"}


# ── Phase 2C: Indicator Compute API ─────────────────────────────────

from pydantic import BaseModel as _PydanticBase
from typing import Any as _Any


class _IndicatorComputeRequest(_PydanticBase):
    datasource_id: int
    indicators: list[dict]  # [{id, type, params}]
    limit: int | None = None  # Optional: last N bars


class _IndicatorComputeResponse(_PydanticBase):
    timestamps: list[float]
    results: dict[str, list[float | None]]  # indicator_id → values


@router.post("/indicators/compute", response_model=_IndicatorComputeResponse)
def compute_indicators(
    req: _IndicatorComputeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Compute indicator values for a datasource without running a backtest.

    Useful for chart overlays and indicator preview.
    """
    from app.services.backtest.v2.engine.data_handler import SymbolData
    import app.services.backtest.indicators as ind_mod

    ds = db.query(DataSource).filter(
        DataSource.id == req.datasource_id,
        or_(DataSource.creator_id == current_user.id, DataSource.is_public == True),
    ).first()
    if not ds:
        raise HTTPException(404, "Data source not found")

    try:
        file_path = _resolve_csv_path(ds)
    except FileNotFoundError:
        raise HTTPException(404, "Data file not found on disk")

    bars = _load_bars_from_csv(str(file_path), validate=True)
    if not bars:
        raise HTTPException(400, "No valid bars in data source")

    if req.limit and req.limit < len(bars):
        bars = bars[-req.limit:]

    # Build SymbolData and compute indicators
    sd = SymbolData(symbol=ds.symbol or "UNKNOWN", timeframe_s=0)
    sd.load_bars(bars)

    # Normalise indicator dicts: callers may send {name, params} or {id, type, params}
    normalised: list[dict] = []
    for i, raw in enumerate(req.indicators):
        ind_type = raw.get("type") or raw.get("name") or "SMA"
        ind_id = raw.get("id") or f"{ind_type.lower()}_{i}"
        normalised.append({"id": ind_id, "type": ind_type, "params": raw.get("params", {})})

    sd.compute_indicators(normalised)

    # Collect results (replace NaN → None for JSON)
    results: dict[str, list[float | None]] = {}
    for key, arr in sd.indicator_arrays.items():
        results[key] = [None if (v != v) else v for v in arr]  # NaN check: v != v

    return _IndicatorComputeResponse(
        timestamps=sd.timestamps,
        results=results,
    )


# ── Phase 5C: Chart Data API ────────────────────────────────────────

class _ChartBar(_PydanticBase):
    time: float
    open: float
    high: float
    low: float
    close: float
    volume: float


class _TradeMark(_PydanticBase):
    time: float
    type: str  # entry_long, entry_short, exit_long, exit_short
    price: float
    pnl: float | None = None
    label: str | None = None


class _ChartDataResponse(_PydanticBase):
    bars: list[_ChartBar]
    indicators: dict[str, list[float | None]]
    timestamps: list[float]
    trade_marks: list[_TradeMark]
    equity_curve: list[float]


@router.get("/{backtest_id}/chart-data", response_model=_ChartDataResponse)
def get_backtest_chart_data(
    backtest_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return OHLCV bars, computed indicators, trade entry/exit marks,
    and equity curve for rendering a full backtest chart overlay.
    """
    from app.services.backtest.v2.engine.data_handler import SymbolData
    import app.services.backtest.indicators as ind_mod

    bt = db.query(Backtest).filter(
        Backtest.id == backtest_id,
        Backtest.creator_id == current_user.id,
    ).first()
    if not bt:
        raise HTTPException(404, "Backtest not found")

    strategy = db.query(Strategy).filter(Strategy.id == bt.strategy_id).first()
    if not strategy:
        raise HTTPException(404, "Strategy not found")

    # Find datasource from the symbol
    ds = (
        db.query(DataSource)
        .filter(
            DataSource.symbol == bt.symbol,
            or_(DataSource.creator_id == current_user.id, DataSource.is_public == True),
        )
        .first()
    )
    if not ds:
        raise HTTPException(404, "Data source not found for backtest symbol")

    try:
        file_path = _resolve_csv_path(ds)
    except FileNotFoundError:
        raise HTTPException(404, "Data file not found on disk")

    raw_bars = _load_bars_from_csv(str(file_path), validate=True)
    if not raw_bars:
        raise HTTPException(400, "No valid bars in data source")

    # Build OHLCV output
    chart_bars = [
        _ChartBar(
            time=b.time, open=b.open, high=b.high,
            low=b.low, close=b.close, volume=b.volume,
        )
        for b in raw_bars
    ]
    timestamps = [b.time for b in raw_bars]

    # Compute indicators from strategy config
    indicators_config = strategy.indicators or []
    indicator_results: dict[str, list[float | None]] = {}

    if indicators_config:
        sd = SymbolData(symbol=bt.symbol or "UNKNOWN", timeframe_s=0)
        sd.load_bars(raw_bars)
        sd.compute_indicators(indicators_config)
        for key, arr in sd.indicator_arrays.items():
            indicator_results[key] = [None if (v != v) else v for v in arr]

    # Build trade marks from stored results
    trade_marks: list[_TradeMark] = []
    stored_results = bt.results or {}
    stored_trades = stored_results.get("trades", [])
    # Also check if response was stored as stats + trades at top level
    if not stored_trades and "stats" in stored_results:
        stored_trades = stored_results.get("trades", [])

    # The backtest run returns trades in the response but they may not be
    # persisted in the DB results blob. Re-run a quick backtest if needed.
    # For now, extract from the stats we do have, or return empty marks.
    # (The frontend can always use trades from the backtest response itself)

    for t in stored_trades:
        entry_time = t.get("entry_time", 0)
        exit_time = t.get("exit_time", 0)
        direction = t.get("direction", "long")
        pnl = t.get("pnl", 0)

        if entry_time:
            trade_marks.append(_TradeMark(
                time=entry_time,
                type=f"entry_{direction}",
                price=t.get("entry_price", 0),
            ))
        if exit_time:
            trade_marks.append(_TradeMark(
                time=exit_time,
                type=f"exit_{direction}",
                price=t.get("exit_price", 0),
                pnl=pnl,
                label=f"{'+' if pnl >= 0 else ''}{pnl:.0f}",
            ))

    # Equity curve — from stored results
    equity_curve = stored_results.get("equity_curve", [])

    return _ChartDataResponse(
        bars=chart_bars,
        indicators=indicator_results,
        timestamps=timestamps,
        trade_marks=trade_marks,
        equity_curve=equity_curve,
    )
