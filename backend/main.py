import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Configure root logger to show INFO for our application modules
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# Suppress noisy third-party loggers
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

from app.core.config import settings
from app.core.database import engine, Base
from app.api import auth, health
from app.api import datasource as datasource_api
from app.api import strategy as strategy_api
from app.api import backtest as backtest_api
from app.api import settings as settings_api
from app.api import llm as llm_api
from app.api import optimization as optimization_api
from app.api import broker as broker_api
from app.api import knowledge as knowledge_api
from app.api import ml as ml_api
from app.api import market as market_api
from app.api import websocket as ws_api
from app.api import agent as agent_api
from app.api import dashboard as dashboard_api
from app.api import recycle_bin as recycle_bin_api
from app.api import optimization_phase as optimization_phase_api
from app.core.websocket import manager as ws_manager
from app.services.market.mt5_stream import mt5_streamer
from app.services.market.aggregator import tick_aggregator
from app.services.market.broker_stream import broker_price_streamer
from app.services.agent.engine import algo_engine
from app.services.agent.trade_monitor import trade_monitor

# Import all models so Base.metadata knows about them
from app.models import user, strategy, backtest, optimization, trade, datasource, knowledge, settings as settings_model  # noqa: F401
from app.models import llm as llm_model  # noqa: F401
from app.models import ml as ml_model  # noqa: F401
from app.models import invitation  # noqa: F401
from app.models import agent as agent_model  # noqa: F401
from app.models import password_reset as password_reset_model  # noqa: F401
from app.models import optimization_phase as optimization_phase_model  # noqa: F401

# Ensure data directories exist
Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

# Create all tables
Base.metadata.create_all(bind=engine)


def _run_schema_migrations():
    """
    Idempotent column migrations for tables that existed before new columns
    were added to the SQLAlchemy models.  Safe for PostgreSQL and SQLite.
    """
    from sqlalchemy import text, inspect
    _log = logging.getLogger(__name__)

    migrations = [
        # (table, column, column_definition)
        ("strategies", "strategy_type",   "VARCHAR(20)  DEFAULT 'builder'"),
        ("strategies", "file_path",       "VARCHAR(500)"),
        ("strategies", "settings_schema", "TEXT         DEFAULT '[]'"),
        ("strategies", "settings_values", "TEXT         DEFAULT '{}'"),
        # Notification channel columns on user_settings
        ("user_settings", "notification_email",                   "VARCHAR(255)"),
        ("user_settings", "notification_smtp_host",               "VARCHAR(255)"),
        ("user_settings", "notification_smtp_port",               "INTEGER DEFAULT 587"),
        ("user_settings", "notification_smtp_user",               "VARCHAR(255)"),
        ("user_settings", "notification_smtp_pass_encrypted",     "TEXT"),
        ("user_settings", "notification_smtp_use_tls",            "INTEGER DEFAULT 1"),
        ("user_settings", "notification_telegram_bot_token_encrypted", "TEXT"),
        ("user_settings", "notification_telegram_chat_id",        "VARCHAR(100)"),
        # DataSource ownership columns
        ("datasources", "creator_id",  "INTEGER DEFAULT 1"),
        ("datasources", "is_public",   "BOOLEAN DEFAULT TRUE"),
        # DataSource instrument profile columns
        ("datasources", "pip_value",          "REAL DEFAULT 10.0"),
        ("datasources", "point_value",        "REAL DEFAULT 1.0"),
        ("datasources", "lot_size",           "REAL DEFAULT 100000.0"),
        ("datasources", "default_spread",     "REAL DEFAULT 0.3"),
        ("datasources", "commission_model",   "VARCHAR(20) DEFAULT 'per_lot'"),
        ("datasources", "default_commission", "REAL DEFAULT 7.0"),
        # Optimization datasource tracking
        ("optimizations", "datasource_id", "INTEGER"),
        # ML model ownership
        ("ml_models", "creator_id", "INTEGER"),
        # Trade ownership
        ("trades", "user_id", "INTEGER"),
        # Strategy folder grouping
        ("strategies", "folder", "VARCHAR(100)"),
        # Verified performance data for optimized system strategies
        ("strategies", "verified_performance", "TEXT"),
        # Soft-delete (recycle bin) columns
        ("strategies",           "deleted_at", "TIMESTAMP"),
        ("datasources",          "deleted_at", "TIMESTAMP"),
        ("backtests",            "deleted_at", "TIMESTAMP"),
        ("trading_agents",       "deleted_at", "TIMESTAMP"),
        ("ml_models",            "deleted_at", "TIMESTAMP"),
        ("knowledge_articles",   "deleted_at", "TIMESTAMP"),
        ("llm_conversations",    "deleted_at", "TIMESTAMP"),
    ]

    insp = inspect(engine)
    with engine.connect() as conn:
        for table, column, coldef in migrations:
            try:
                existing = [c["name"] for c in insp.get_columns(table)]
            except Exception:
                existing = []

            if column in existing:
                continue

            try:
                # PostgreSQL supports IF NOT EXISTS; SQLite does not but we
                # catch the duplicate-column error below.
                is_pg = engine.dialect.name == "postgresql"
                if is_pg:
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {coldef}"
                    ))
                else:
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN {column} {coldef}"
                    ))
                conn.commit()
                _log.info("Migration: added column %s.%s", table, column)
            except Exception as exc:
                # Already exists (SQLite raises OperationalError for duplicates)
                conn.rollback()
                _log.debug("Migration skipped %s.%s: %s", table, column, exc)


_run_schema_migrations()


def _fix_boolean_columns():
    """Fix INTEGER columns that should be BOOLEAN (PostgreSQL strict typing).

    On PostgreSQL, inserting Python True into an INTEGER column fails with
    'column "is_public" is of type integer but expression is of type boolean'.
    This migration converts such columns to proper BOOLEAN type.
    """
    from sqlalchemy import text
    _log = logging.getLogger(__name__)

    if engine.dialect.name != "postgresql":
        _log.info("Not PostgreSQL (%s) — skipping boolean fix", engine.dialect.name)
        return

    # (table, column, default_value)
    fixes = [
        ("datasources", "is_public", "TRUE"),
    ]

    for table, column, default in fixes:
        try:
            with engine.begin() as conn:  # auto-commit on success, rollback on error
                result = conn.execute(text(
                    "SELECT data_type FROM information_schema.columns "
                    f"WHERE table_name = :tbl AND column_name = :col"
                ), {"tbl": table, "col": column})
                row = result.fetchone()
                if not row:
                    _log.info("Column %s.%s does not exist, skipping", table, column)
                    continue
                dtype = row[0].lower()
                if dtype == 'boolean':
                    _log.info("Column %s.%s is already BOOLEAN ✓", table, column)
                    continue

                _log.warning("Column %s.%s is '%s' — converting to BOOLEAN", table, column, dtype)
                # Drop default, alter type, re-add default
                conn.execute(text(
                    f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT"
                ))
                conn.execute(text(
                    f"ALTER TABLE {table} ALTER COLUMN {column} "
                    f"TYPE BOOLEAN USING CASE WHEN {column}::int = 0 THEN FALSE ELSE TRUE END"
                ))
                conn.execute(text(
                    f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT {default}"
                ))
                _log.info("Fixed %s.%s → BOOLEAN ✓", table, column)
        except Exception as exc:
            _log.error("Failed to fix %s.%s: %s", table, column, exc, exc_info=True)


_fix_boolean_columns()


def _remove_incompatible_strategies():
    """Remove strategies that use unsupported indicator types or are python-file
    strategies without V3 engine support.  Also cleans up orphaned agents,
    agent logs, agent trades, and backtests that referenced them.

    This runs once at startup and is idempotent (no-op if already cleaned).
    """
    import json
    from sqlalchemy import text
    _log = logging.getLogger(__name__)

    SUPPORTED_INDICATORS = {
        "sma", "ema", "wma", "rsi", "atr", "adx", "macd", "bollinger",
        "bbands", "stochastic", "vwap", "supertrend", "pivot", "adr",
        "volume_sma", "obv", "cci", "williams_r", "mfi", "ichimoku",
    }

    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, strategy_type, file_path, indicators, entry_rules, is_system FROM strategies"
        )).fetchall()

        ids_to_remove = []
        for r in rows:
            sid, stype, fpath, ind_json, rules_json, is_system = r
            stype = stype or "builder"
            fpath = fpath or ""

            try:
                indicators = json.loads(ind_json) if ind_json else []
            except Exception:
                indicators = []
            try:
                entry_rules = json.loads(rules_json) if rules_json else []
            except Exception:
                entry_rules = []

            # Python-file strategies are not V3-engine compatible
            # BUT keep system strategies — they must still appear in the UI
            if stype == "python" and fpath and not is_system:
                ids_to_remove.append(sid)
                continue

            # Builder strategies must have indicators and entry rules
            if stype == "builder":
                if not indicators or not entry_rules:
                    ids_to_remove.append(sid)
                    continue
                # Check for unsupported indicator types
                for ind in indicators:
                    itype = (ind.get("type", "") or "").lower().strip()
                    if itype and itype not in SUPPORTED_INDICATORS:
                        ids_to_remove.append(sid)
                        break

        if not ids_to_remove:
            _log.info("No incompatible strategies to remove")
            return

        id_list = ",".join(str(i) for i in ids_to_remove)
        _log.info("Removing %d incompatible strategies: %s", len(ids_to_remove), id_list)

        # Delete orphaned agents first (FK to strategies)
        conn.execute(text(
            f"DELETE FROM agent_logs WHERE agent_id IN "
            f"(SELECT id FROM trading_agents WHERE strategy_id IN ({id_list}))"
        ))
        conn.execute(text(
            f"DELETE FROM agent_trades WHERE agent_id IN "
            f"(SELECT id FROM trading_agents WHERE strategy_id IN ({id_list}))"
        ))
        conn.execute(text(
            f"DELETE FROM trading_agents WHERE strategy_id IN ({id_list})"
        ))
        # Delete orphaned backtests
        conn.execute(text(
            f"DELETE FROM backtests WHERE strategy_id IN ({id_list})"
        ))
        # Delete the strategies
        result = conn.execute(text(
            f"DELETE FROM strategies WHERE id IN ({id_list})"
        ))
        conn.commit()
        _log.info("Removed %d incompatible strategies and orphaned records", result.rowcount)


_remove_incompatible_strategies()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
)

# CORS — allow all origins.  Auth is via JWT Bearer tokens (not cookies),
# so wildcard CORS is safe and avoids env-var misconfiguration on Render.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global exception handler — ensures unhandled errors return JSON (visible
# through CORS) instead of opaque 500 pages, and logs the full traceback.
@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    import traceback
    logging.getLogger(__name__).error(
        "Unhandled %s on %s %s:\n%s",
        type(exc).__name__, request.method, request.url.path,
        traceback.format_exc(),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {type(exc).__name__}: {str(exc)[:300]}"},
    )

# Routes
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(datasource_api.router)
app.include_router(strategy_api.router)
app.include_router(backtest_api.router)
app.include_router(settings_api.router)
app.include_router(llm_api.router)
app.include_router(optimization_api.router)
app.include_router(optimization_phase_api.router)
app.include_router(broker_api.router)
app.include_router(knowledge_api.router)
app.include_router(ml_api.router)
app.include_router(market_api.router)
app.include_router(ws_api.router)
app.include_router(agent_api.router)
app.include_router(dashboard_api.router)
app.include_router(recycle_bin_api.router)


def _seed_admin_user():
    """Create the default admin user if the database is empty (fresh deployment)."""
    from app.core.database import SessionLocal
    from app.models.user import User
    from app.core.auth import hash_password

    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            return  # users already exist, nothing to do
        admin = User(
            username="TradeforgeAdmin",
            password_hash=hash_password("admin123"),
            email="",
            is_admin=True,
            must_change_password=False,
        )
        db.add(admin)
        db.commit()
        logging.getLogger(__name__).info("Default admin user 'TradeforgeAdmin' created")
    except Exception as e:
        db.rollback()
        logging.getLogger(__name__).error("Failed to seed admin user: %s", e)
    finally:
        db.close()


def _seed_all_strategies():
    """Seed all system Python strategies into the database."""
    import json as _json
    from app.core.database import SessionLocal
    from app.models.strategy import Strategy
    from app.models.user import User
    from app.services.strategy.file_parser import parse_python_strategy

    _log = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.is_admin == True).first()
        if not admin:
            admin = db.query(User).first()
        if not admin:
            _log.warning("Cannot seed strategies: no users in DB")
            return

        # Master strategy catalog — each entry becomes a system strategy
        catalog = [
            {
                "name": "Valentini Auction Market",
                "file": "s01_valentini_auction_market.py",
                "description": (
                    "Volume Profile + Order Flow strategy inspired by Fabio Valentini "
                    "(3x Robbins World Cup). Detects Point of Control, Value Area, and "
                    "volume-confirmed breakouts or mean-reversion setups."
                ),
                "timeframes": "4H / Daily",
                "tags": ["volume_profile", "order_flow", "swing"],
            },
            {
                "name": "ICT Silver Bullet",
                "file": "s02_ict_silver_bullet.py",
                "description": (
                    "ICT Silver Bullet time-based strategy. Trades Fair Value Gaps "
                    "during specific kill zones (3-4AM, 10-11AM, 2-3PM NY). Combines "
                    "FVG detection with liquidity sweep and market structure shift."
                ),
                "timeframes": "1m / 5m / 15m",
                "tags": ["ict", "smart_money", "scalping", "intraday"],
            },
            {
                "name": "Smart Money Concepts",
                "file": "s03_smart_money_concepts.py",
                "description": (
                    "Full ICT / Smart Money framework. Combines liquidity sweeps, "
                    "Fair Value Gaps, and Order Block detection for institutional-grade "
                    "entry points with break-of-structure confirmation."
                ),
                "timeframes": "15m / 1H / 4H",
                "tags": ["ict", "smart_money", "swing"],
            },
            {
                "name": "Triple EMA VWAP Scalper",
                "file": "s04_triple_ema_vwap_scalper.py",
                "description": (
                    "Intraday scalping strategy using 9/20/50 EMA crossovers confirmed "
                    "by VWAP position. 62% historical win rate. Trades only with "
                    "institutional flow (price above/below VWAP)."
                ),
                "timeframes": "1m / 5m / 15m",
                "tags": ["ema", "vwap", "scalping", "intraday"],
            },
            {
                "name": "Opening Range Breakout",
                "file": "s05_opening_range_breakout.py",
                "description": (
                    "Trades the breakout of the first 15-minute opening range. "
                    "Adapts target multiples based on market conditions. "
                    "Session-aware with volume confirmation."
                ),
                "timeframes": "5m / 15m",
                "tags": ["breakout", "intraday", "session"],
            },
            {
                "name": "Supertrend Trend Follower",
                "file": "s06_supertrend_follower.py",
                "description": (
                    "Oliver Seban's Supertrend indicator (11% avg gain/trade over 60 years). "
                    "ATR-based dynamic trailing stop with EMA trend filter and whipsaw protection."
                ),
                "timeframes": "1H / 4H / Daily",
                "tags": ["supertrend", "trend_following", "swing"],
            },
            {
                "name": "Turtle Trading (Donchian)",
                "file": "s07_turtle_trading.py",
                "description": (
                    "Richard Dennis Turtle Trading rules. 20-period Donchian channel "
                    "breakout with 55-period confirmation. Enhanced with Curtis Faith "
                    "SMA filter and ATR-based position sizing."
                ),
                "timeframes": "Daily / Weekly",
                "tags": ["donchian", "breakout", "trend_following", "position"],
            },
            {
                "name": "Larry Williams Volatility Breakout",
                "file": "s08_larry_williams_breakout.py",
                "description": (
                    "Inspired by Larry Williams (11,000% Robbins Cup return). "
                    "Uses previous day's range * factor to set breakout levels from "
                    "the open. Williams %R for exit confirmation."
                ),
                "timeframes": "Daily",
                "tags": ["volatility", "breakout", "swing"],
            },
            {
                "name": "Connors RSI(2) Mean Reversion",
                "file": "s09_connors_rsi2_mean_reversion.py",
                "description": (
                    "Larry Connors' RSI(2) mean reversion — 30%+ annual returns since 1999. "
                    "Ultra-short RSI(2) catches extreme conditions. 200-SMA trend filter, "
                    "cumulative RSI variation, and ADX choppy-market filter."
                ),
                "timeframes": "Daily",
                "tags": ["rsi", "mean_reversion", "swing"],
            },
            {
                "name": "TTM Squeeze Momentum",
                "file": "s10_ttm_squeeze.py",
                "description": (
                    "John Carter's TTM Squeeze. Bollinger Bands contracting inside "
                    "Keltner Channels signals volatility squeeze. When it fires, "
                    "enter in direction of Donchian momentum for explosive moves."
                ),
                "timeframes": "15m / 1H / 4H / Daily",
                "tags": ["squeeze", "bollinger", "keltner", "momentum"],
            },
            {
                "name": "Ichimoku Cloud Breakout",
                "file": "s11_ichimoku_cloud.py",
                "description": (
                    "Full Ichimoku Kinko Hyo system by Goichi Hosoda (30 years of dev). "
                    "Tenkan/Kijun cross above cloud with Chikou Span confirmation "
                    "and Kumo twist filter."
                ),
                "timeframes": "4H / Daily / Weekly",
                "tags": ["ichimoku", "trend_following", "swing", "position"],
            },
            {
                "name": "ADX + Parabolic SAR",
                "file": "s12_adx_parabolic_sar.py",
                "description": (
                    "Combining two J. Welles Wilder classics. ADX confirms strong trend "
                    "(> 25 and rising), Parabolic SAR provides entry on flip and "
                    "dynamic trailing exit. DI+/DI- directional confirmation."
                ),
                "timeframes": "1H / 4H / Daily",
                "tags": ["adx", "parabolic_sar", "trend_following"],
            },
            {
                "name": "Woodies CCI Zero Line Reject",
                "file": "s13_woodies_cci.py",
                "description": (
                    "Ken Wood's highest-probability CCI pattern. CCI(14) trends on one "
                    "side of zero, pulls back to ±50 zone, then resumes direction. "
                    "Turbo CCI(6) confirms timing."
                ),
                "timeframes": "5m / 15m / 1H",
                "tags": ["cci", "momentum", "intraday"],
            },
            {
                "name": "RSI Divergence Swing",
                "file": "s14_rsi_divergence.py",
                "description": (
                    "Andrew Cardwell-inspired RSI divergence detection. Identifies regular "
                    "and hidden divergences between price pivot points and RSI values. "
                    "50-SMA trend filter ensures alignment."
                ),
                "timeframes": "1H / 4H / Daily",
                "tags": ["rsi", "divergence", "swing"],
            },
            {
                "name": "Bollinger Band Squeeze Breakout",
                "file": "s15_bb_squeeze_breakout.py",
                "description": (
                    "John Bollinger's bandwidth analysis. Detects when Bollinger Bandwidth "
                    "hits bottom-5% of its range (squeeze). Enters on expansion using "
                    "%B for direction confirmation."
                ),
                "timeframes": "15m / 1H / 4H",
                "tags": ["bollinger", "squeeze", "breakout"],
            },
            {
                "name": "VWAP Mean Reversion Bands",
                "file": "s16_vwap_mean_reversion.py",
                "description": (
                    "Brian Shannon-inspired VWAP band strategy. Price reverts to "
                    "institutional fair value (VWAP). Trades bounces from ±2σ bands "
                    "with volume spike and reversal candle confirmation."
                ),
                "timeframes": "1m / 5m / 15m",
                "tags": ["vwap", "mean_reversion", "scalping", "intraday"],
            },
            {
                "name": "EMA Ribbon Momentum (Guppy)",
                "file": "s17_ema_ribbon.py",
                "description": (
                    "Daryl Guppy's Multiple Moving Average system. Ribbon of 6 EMAs "
                    "(8,13,21,34,55,89). Enters when short-term EMAs fan out from "
                    "long-term EMAs with expanding spread."
                ),
                "timeframes": "15m / 1H / 4H / Daily",
                "tags": ["ema", "guppy", "momentum", "trend_following"],
            },
            {
                "name": "Keltner Channel Breakout",
                "file": "s18_keltner_breakout.py",
                "description": (
                    "Chester Keltner / Linda Raschke modernized channel system. "
                    "EMA(20) ± 2.5×ATR(10) channels. Breakout entry + ADX filter "
                    "to avoid choppy markets. Exit on channel re-entry."
                ),
                "timeframes": "15m / 1H / 4H",
                "tags": ["keltner", "breakout", "momentum"],
            },
            {
                "name": "Stochastic RSI Momentum",
                "file": "s19_stoch_rsi_momentum.py",
                "description": (
                    "Chande & Kroll's Stochastic RSI. Applies stochastic formula to "
                    "RSI for faster oscillation. K/D crossovers in oversold/overbought "
                    "zones with EMA trend filter."
                ),
                "timeframes": "5m / 15m / 1H",
                "tags": ["stochastic_rsi", "momentum", "intraday"],
            },
            {
                "name": "Unger Multi-Strategy Rotation",
                "file": "s20_unger_rotation.py",
                "description": (
                    "Andrea Unger's approach (4x World Champion). Regime detection "
                    "using ADX + volatility. Switches between Donchian breakout "
                    "(trending) and RSI+BB mean reversion (ranging) automatically."
                ),
                "timeframes": "1H / 4H / Daily",
                "tags": ["rotation", "regime", "trend_following", "mean_reversion"],
            },
            {
                "name": "Hull MA Crossover",
                "file": "s21_hull_ma_crossover.py",
                "description": (
                    "Alan Hull's lag-reduced moving average. Dual HMA crossover "
                    "(fast 9 / slow 21) for minimal-lag momentum signals. "
                    "ADX filter ensures trend presence."
                ),
                "timeframes": "15m / 1H / 4H",
                "tags": ["hull_ma", "crossover", "momentum"],
            },
            {
                "name": "Nill Dual Momentum Swing",
                "file": "s22_nill_momentum_swing.py",
                "description": (
                    "Inspired by Patrick Nill (9x Robbins Cup, 70-200%/yr). "
                    "Dual ROC (fast 10, slow 30) alignment with MFI money flow "
                    "confirmation. Enters on momentum flip."
                ),
                "timeframes": "4H / Daily",
                "tags": ["roc", "mfi", "momentum", "swing"],
            },
            {
                "name": "Awesome Oscillator Saucer",
                "file": "s23_ao_saucer.py",
                "description": (
                    "Bill Williams Trading Chaos: AO Saucer pattern, Twin Peaks "
                    "divergence, and Zero Line Cross. Multiple confirmation modes "
                    "for trend continuation entries."
                ),
                "timeframes": "15m / 1H / 4H / Daily",
                "tags": ["awesome_oscillator", "williams", "momentum"],
            },
            {
                "name": "MACD Histogram Divergence",
                "file": "s24_macd_histogram_div.py",
                "description": (
                    "Alexander Elder's MACD histogram method. Detects divergence "
                    "between histogram peaks/troughs and price action. Early signal "
                    "before classic MACD cross. 50-SMA trend filter."
                ),
                "timeframes": "1H / 4H / Daily",
                "tags": ["macd", "divergence", "momentum", "swing"],
            },
            {
                "name": "London Breakout Session",
                "file": "s25_london_breakout.py",
                "description": (
                    "Institutional London session strategy. Captures Asian range "
                    "(00-08 GMT) and trades the breakout at London open. Range-size "
                    "ATR filter to avoid false signals. Session-end auto-close."
                ),
                "timeframes": "5m / 15m",
                "tags": ["session", "breakout", "intraday"],
            },
            {
                "name": "Market Structure Signals (BOS/CHoCH)",
                "file": "s26_market_structure_signals.py",
                "description": (
                    "Break of Structure (BOS) and Change of Character (CHoCH) "
                    "breakout strategy based on ProjectSyndicate's Market Structure "
                    "Signals indicator. Detects pivot highs/lows, classifies breakouts, "
                    "and uses ATR-based TP/SL with optional EMA trend filter."
                ),
                "timeframes": "15m / 1H / 4H",
                "tags": ["market_structure", "bos", "choch", "breakout"],
            },
            {
                "name": "Institutional Composite (ICT/SMC)",
                "file": "s27_institutional_composite.py",
                "description": (
                    "Research-based institutional strategy combining ICT, SMC, and "
                    "Wyckoff concepts. Uses Kill Zone timing, liquidity sweep detection, "
                    "Fair Value Gaps, Order Blocks, and Premium/Discount zones. Trades "
                    "where institutions trade, at institutional price levels."
                ),
                "timeframes": "M5 / M15 / 1H",
                "tags": ["institutional", "ict", "smc", "liquidity", "smart_money"],
            },
        ]

        # Optimized parameters and verified performance from Optuna + Walk-Forward validation
        # These are the best configurations found across all datasets (22 GOOD results)
        _OPTIMIZED_CONFIGS = {
            "s03_smart_money_concepts.py": {
                "params": {"atr_period": 11, "atr_sl_mult": 3.2, "atr_tp_mult": 1.0,
                           "swing_lookback": 17, "ob_lookback": 6, "risk_per_trade": 0.005},
                "performance": {"profit_factor": 3.69, "win_rate": 93.2, "max_dd_pct": 0.86,
                                "sharpe": 0.24, "trades": 44, "net_profit_pct": 4.25,
                                "wf_score": 80.0, "robustness": "GOOD", "symbol": "XAUUSD", "tf": "M5"},
            },
            "s07_turtle_trading.py": {
                "params": {"entry_period": 40, "exit_period": 15, "atr_period": 16,
                           "ma_fast": 47, "ma_slow": 233, "use_trend_filter": True,
                           "risk_per_trade": 0.005, "atr_stop_mult": 1.25},
                "performance": {"profit_factor": 1.79, "win_rate": 37.8, "max_dd_pct": 5.44,
                                "sharpe": 0.60, "trades": 111, "net_profit_pct": 30.8,
                                "wf_score": 60.0, "robustness": "GOOD", "symbol": "XAUUSD", "tf": "H1"},
            },
            "s10_ttm_squeeze.py": {
                "params": {"bb_period": 16, "bb_mult": 1.75, "kc_period": 18, "kc_mult": 1.7,
                           "mom_period": 9, "atr_period": 14, "atr_sl_mult": 1.0,
                           "atr_tp_mult": 6.5, "min_squeeze_bars": 2, "risk_per_trade": 0.005},
                "performance": {"profit_factor": 1.35, "win_rate": 18.7, "max_dd_pct": 14.52,
                                "sharpe": 0.27, "trades": 626, "net_profit_pct": 159.83,
                                "wf_score": 100.0, "robustness": "GOOD", "symbol": "XAUUSD", "tf": "H1"},
            },
            "s11_ichimoku_cloud.py": {
                "params": {"tenkan_period": 7, "kijun_period": 33, "senkou_b_period": 47,
                           "displacement": 30, "atr_period": 15, "atr_sl_mult": 2.35,
                           "atr_tp_mult": 5.25, "require_chikou": True,
                           "require_kumo_twist": False, "risk_per_trade": 0.005},
                "performance": {"profit_factor": 2.27, "win_rate": 51.6, "max_dd_pct": 2.54,
                                "sharpe": 0.66, "trades": 62, "net_profit_pct": 21.34,
                                "wf_score": 80.0, "robustness": "GOOD", "symbol": "EURUSD", "tf": "H1"},
            },
            "s13_woodies_cci.py": {
                "params": {"cci_period": 16, "cci_turbo": 4, "zlr_zone": 50, "trend_bars": 3,
                           "atr_period": 17, "atr_sl_mult": 1.5, "atr_tp_mult": 1.05,
                           "risk_per_trade": 0.005},
                "performance": {"profit_factor": 2.10, "win_rate": 75.4, "max_dd_pct": 1.86,
                                "sharpe": 0.84, "trades": 118, "net_profit_pct": 16.83,
                                "wf_score": 80.0, "robustness": "GOOD", "symbol": "XAUUSD", "tf": "H1"},
            },
            "s15_bb_squeeze_breakout.py": {
                "params": {"bb_period": 27, "bb_mult": 2.1, "bbw_lookback": 60,
                           "bbw_percentile": 0.25, "pct_b_entry": 0.9, "pct_b_short": 0.4,
                           "atr_period": 19, "atr_sl_mult": 1.35, "atr_tp_mult": 8.9,
                           "require_momentum": False, "exit_bb_revert": False,
                           "risk_per_trade": 0.005},
                "performance": {"profit_factor": 1.92, "win_rate": 23.4, "max_dd_pct": 3.98,
                                "sharpe": 0.45, "trades": 77, "net_profit_pct": 32.2,
                                "wf_score": 80.0, "robustness": "GOOD", "symbol": "XAUUSD", "tf": "H1"},
            },
            "s17_ema_ribbon.py": {
                "params": {"short_emas": [8, 13, 21], "long_emas": [34, 55, 89],
                           "expansion_bars": 3, "atr_period": 13, "atr_sl_mult": 1.7,
                           "atr_tp_mult": 2.35, "trail_ema": 14, "risk_per_trade": 0.005},
                "performance": {"profit_factor": 1.42, "win_rate": 51.0, "max_dd_pct": 3.67,
                                "sharpe": 0.61, "trades": 253, "net_profit_pct": 28.61,
                                "wf_score": 60.0, "robustness": "GOOD", "symbol": "XAUUSD", "tf": "H1"},
            },
            "s19_stoch_rsi_momentum.py": {
                "params": {"rsi_period": 20, "stoch_period": 20, "k_smooth": 2, "d_smooth": 3,
                           "ob_level": 73, "os_level": 29, "ema_trend_period": 52,
                           "atr_period": 15, "atr_sl_mult": 4.1, "atr_tp_mult": 1.6,
                           "risk_per_trade": 0.005},
                "performance": {"profit_factor": 1.81, "win_rate": 82.7, "max_dd_pct": 1.0,
                                "sharpe": 0.58, "trades": 98, "net_profit_pct": 7.18,
                                "wf_score": 100.0, "robustness": "GOOD", "symbol": "XAUUSD", "tf": "H1"},
            },
            "s22_nill_momentum_swing.py": {
                "params": {"roc_fast": 10, "roc_slow": 30, "mfi_period": 14, "mfi_bull": 50,
                           "mfi_bear": 50, "atr_period": 15, "atr_sl_mult": 1.25,
                           "atr_tp_mult": 2.45, "risk_per_trade": 0.005},
                "performance": {"profit_factor": 1.67, "win_rate": 46.5, "max_dd_pct": 6.46,
                                "sharpe": 0.63, "trades": 144, "net_profit_pct": 28.51,
                                "wf_score": 60.0, "robustness": "GOOD", "symbol": "XAUUSD", "tf": "H1"},
            },
            "s24_macd_histogram_div.py": {
                "params": {"fast_period": 15, "slow_period": 22, "signal_period": 6,
                           "div_lookback": 50, "sma_filter": 60, "atr_period": 18,
                           "atr_sl_mult": 2.05, "atr_tp_mult": 1.0, "risk_per_trade": 0.005},
                "performance": {"profit_factor": 5.15, "win_rate": 92.5, "max_dd_pct": 0.51,
                                "sharpe": 0.91, "trades": 40, "net_profit_pct": 6.61,
                                "wf_score": 100.0, "robustness": "GOOD", "symbol": "EURUSD", "tf": "H1"},
            },
            "s25_london_breakout.py": {
                "params": {"asia_start_hour": 0, "asia_end_hour": 8, "london_start_hour": 8,
                           "london_end_hour": 16, "breakout_buffer_pct": 0.0005,
                           "target_range_mult": 2.05, "sl_at_range_opposite": False,
                           "atr_period": 18, "atr_sl_mult": 3.55, "min_range_atr": 0.15,
                           "max_range_atr": 3.1, "risk_per_trade": 0.005, "max_daily_trades": 3},
                "performance": {"profit_factor": 1.62, "win_rate": 59.2, "max_dd_pct": 4.91,
                                "sharpe": 0.09, "trades": 76, "net_profit_pct": 10.16,
                                "wf_score": 80.0, "robustness": "GOOD", "symbol": "XAUUSD", "tf": "M1"},
            },
            "s26_market_structure_signals.py": {
                "params": {"swing_length": 12, "bos_confirm": "wick", "choch_only": False,
                           "atr_period": 19, "atr_sl_mult": 1.35, "atr_tp_mult": 8.5,
                           "ema_period": 82, "use_ema_filter": False, "cooldown_bars": 5,
                           "risk_per_trade": 0.005},
                "performance": {"profit_factor": 2.99, "win_rate": 32.9, "max_dd_pct": 4.96,
                                "sharpe": 0.75, "trades": 79, "net_profit_pct": 69.75,
                                "wf_score": 80.0, "robustness": "GOOD", "symbol": "XAUUSD", "tf": "H1"},
            },
        }

        strategies_dir = os.path.join(os.path.dirname(__file__), "data", "strategies")
        added = 0
        updated = 0

        for entry in catalog:
            name = entry["name"]
            file_path = os.path.join(strategies_dir, entry["file"])
            if not os.path.isfile(file_path):
                _log.warning("Strategy file missing: %s", file_path)
                continue

            # Auto-extract settings_schema from the strategy's DEFAULTS dict
            schema_list: list = []
            values_dict: dict = {}
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    source = f.read()
                parsed = parse_python_strategy(source)
                schema_list = parsed.get("settings_schema", [])
                values_dict = parsed.get("settings_values", {})
            except Exception as parse_err:
                _log.warning("Could not parse settings for %s: %s", entry["file"], parse_err)

            # Check for optimized config
            opt_config = _OPTIMIZED_CONFIGS.get(entry["file"])
            opt_params = opt_config["params"] if opt_config else None
            opt_perf = opt_config["performance"] if opt_config else None

            # If optimized params exist, merge them into values_dict
            if opt_params and values_dict:
                values_dict = {**values_dict, **opt_params}
            elif opt_params:
                values_dict = opt_params

            # Check if already exists
            existing = db.query(Strategy).filter(
                Strategy.is_system == True, Strategy.name == name
            ).first()
            if existing:
                # Back-fill settings_schema if it was previously empty
                cur_schema = existing.settings_schema
                is_empty = (
                    not cur_schema
                    or cur_schema == "[]" or cur_schema == []
                    or cur_schema == "null"
                    or (isinstance(cur_schema, str) and cur_schema.strip() in ("[]", "", "null"))
                )
                if is_empty and schema_list:
                    existing.settings_schema = schema_list
                    existing.settings_values = values_dict
                    updated += 1
                # Always update verified_performance and optimized settings
                if opt_perf:
                    existing.verified_performance = opt_perf
                if opt_params:
                    existing.settings_values = values_dict
                    updated += 1
                continue

            strat = Strategy(
                name=name,
                description=entry["description"],
                indicators=[],
                entry_rules=[],
                exit_rules=[],
                risk_params={"position_size_type": "percent_risk", "position_size_value": 1.0},
                filters={"tags": entry.get("tags", []), "timeframes": entry.get("timeframes", "")},
                is_system=True,
                strategy_type="python",
                file_path=file_path,
                settings_schema=schema_list,
                settings_values=values_dict,
                verified_performance=opt_perf,
                creator_id=admin.id,
            )
            db.add(strat)
            added += 1

        if added or updated:
            db.commit()
            _log.info("Seeded %d new + updated %d existing strategies (catalog: %d)", added, updated, len(catalog))
    except Exception as e:
        db.rollback()
        _log.error("Failed to seed strategies: %s", e)
    finally:
        db.close()


@app.on_event("startup")
async def startup_event():
    _seed_admin_user()
    _seed_all_strategies()
    _remove_incompatible_strategies()  # must run AFTER seeder to catch re-created python strategies
    await ws_manager.start()
    await tick_aggregator.start()
    try:
        await mt5_streamer.start()
    except Exception as e:
        logging.getLogger(__name__).warning("MT5 streamer start skipped: %s", e)
    # Start broker price streamer (non-MT5 live tick data for Oanda/Coinbase/etc.)
    try:
        await broker_price_streamer.start()
    except Exception as e:
        logging.getLogger(__name__).warning("BrokerPriceStreamer start skipped: %s", e)
    await algo_engine.start()
    # Start paper trade monitor (simulates SL/TP exits for agent trades)
    trade_monitor.subscribe_to_ticks(ws_manager)
    await trade_monitor.start()


@app.on_event("shutdown")
async def shutdown_event():
    await trade_monitor.stop()
    await algo_engine.stop()
    try:
        await mt5_streamer.stop()
    except Exception:
        pass
    try:
        await broker_price_streamer.stop()
    except Exception:
        pass
    await ws_manager.stop()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
