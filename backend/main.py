import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.rate_limit import limiter

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
from app.api import news as news_api
from app.api import watchlist as watchlist_api
from app.api import webhook as webhook_api
from app.api import telegram_webhook as telegram_webhook_api
from app.api import prop_firm as prop_firm_api
from app.api import ctrader_oauth as ctrader_oauth_api
from app.api import broadcast as broadcast_api
from app.api import portfolio as portfolio_api
from app.core.websocket import manager as ws_manager
from app.services.market.mt5_stream import mt5_streamer
from app.services.market.aggregator import tick_aggregator
from app.services.market.broker_stream import broker_price_streamer
from app.services.market.databento_stream import databento_streamer
from app.services.agent.engine import algo_engine
from app.services.agent.trade_monitor import trade_monitor
from app.services.agent.broker_reconciler import broker_reconciler
from app.services.alert_checker import alert_checker

# Import all models so Base.metadata knows about them
from app.models import user, strategy, backtest, optimization, trade, datasource, knowledge, settings as settings_model  # noqa: F401
from app.models import llm as llm_model  # noqa: F401
from app.models import ml as ml_model  # noqa: F401
from app.models import invitation  # noqa: F401
from app.models import agent as agent_model  # noqa: F401
from app.models import password_reset as password_reset_model  # noqa: F401
from app.models import optimization_phase as optimization_phase_model  # noqa: F401
from app.models import news as news_model  # noqa: F401
from app.models import watchlist as watchlist_model  # noqa: F401
from app.models import prop_firm as prop_firm_model  # noqa: F401
from app.models import broadcast as broadcast_model  # noqa: F401
from app.models import portfolio as portfolio_model  # noqa: F401

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
        ("user_settings", "notification_telegram_username",       "VARCHAR(100)"),
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
        # Backtest datasource tracking
        ("backtests", "datasource_id", "INTEGER"),
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
        # AI Copilot settings
        ("user_settings", "copilot_enabled",     "INTEGER DEFAULT 1"),
        ("user_settings", "copilot_autonomy",    "VARCHAR(20) DEFAULT 'assisted'"),
        ("user_settings", "copilot_permissions", "TEXT"),
        # Trade SL/TP tracking
        ("trades", "stop_loss",   "REAL"),
        ("trades", "take_profit", "REAL"),
        # News AI analysis
        ("news_articles", "ai_analysis", "TEXT"),
        # 2FA Email OTP columns
        ("users", "otp_code",       "VARCHAR(10) DEFAULT ''"),
        ("users", "otp_expires_at", "TIMESTAMP"),
        # Prop firm account link on trading agents
        ("trading_agents", "prop_firm_account_id", "INTEGER"),
        # Broker fill data on agent trades
        ("agent_trades", "filled_price",     "REAL"),
        ("agent_trades", "filled_time",      "TIMESTAMP"),
        ("agent_trades", "broker_trade_id",  "VARCHAR(100)"),
        ("agent_trades", "broker_pnl",       "REAL"),
        ("agent_trades", "broker_name",      "VARCHAR(50)"),
        ("agent_trades", "exit_reason",      "VARCHAR(30)"),
        # User timezone preference
        ("user_settings", "timezone",          "VARCHAR(60) DEFAULT 'UTC'"),
        # Portfolio manager link on trading agents
        ("trading_agents", "portfolio_id", "INTEGER"),
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


def _create_indexes():
    """Create performance indexes on frequently queried columns (idempotent)."""
    from sqlalchemy import text
    _log = logging.getLogger(__name__)

    indexes = [
        ("idx_backtests_creator_created", "backtests", "creator_id, created_at DESC"),
        ("idx_backtests_strategy", "backtests", "strategy_id"),
        ("idx_prop_trades_account_status", "prop_firm_trades", "account_id, status"),
        ("idx_agents_creator_active", "trading_agents", "creator_id"),
        ("idx_strategies_creator", "strategies", "creator_id"),
        ("idx_datasources_creator", "datasources", "creator_id"),
        ("idx_trades_user", "trades", "user_id"),
        ("idx_agent_logs_agent_created", "agent_logs", "agent_id, created_at DESC"),
    ]

    with engine.connect() as conn:
        for idx_name, table, columns in indexes:
            try:
                conn.execute(text(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({columns})"
                ))
                conn.commit()
            except Exception:
                conn.rollback()
    logging.getLogger(__name__).info("Database indexes verified")


_create_indexes()


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


def _recalculate_agent_pnl():
    """One-time recalculation of all AgentTrade P&L using correct instrument specs.
    Fixes historical trades that used the broken raw-points formula."""
    from app.services.agent.instrument_specs import calc_pnl_dollars
    _log = logging.getLogger(__name__)

    with engine.connect() as conn:
        from sqlalchemy import text
        rows = conn.execute(text(
            "SELECT id, symbol, direction, entry_price, exit_price, lot_size, pnl, broker_name "
            "FROM agent_trades WHERE entry_price IS NOT NULL AND exit_price IS NOT NULL"
        )).fetchall()

        updated = 0
        for r in rows:
            tid, symbol, direction, entry, exit_p, lot, old_pnl, broker = r
            broker = broker or "oanda"
            lot = lot or 0.01
            new_pnl = calc_pnl_dollars(symbol, direction, entry, exit_p, lot, broker)
            if abs((old_pnl or 0) - new_pnl) > 0.001:
                conn.execute(text(
                    "UPDATE agent_trades SET pnl = :pnl WHERE id = :id"
                ), {"pnl": round(new_pnl, 4), "id": tid})
                updated += 1
        conn.commit()
        if updated > 0:
            _log.info("Recalculated P&L for %d/%d agent trades", updated, len(rows))


_recalculate_agent_pnl()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — explicit origins to avoid browser issues with wildcard + credentials.
_cors_origins = [
    settings.FRONTEND_URL,                   # local dev: http://localhost:3000
    "https://flowrexalgo.onrender.com",      # production frontend
    "https://tradeforge.onrender.com",       # legacy frontend URL
]
if settings.DEBUG:
    _cors_origins += ["http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,   # JWT Bearer tokens don't need credentials
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip compression for responses >500 bytes — reduces equity curve / trade list payloads
app.add_middleware(GZipMiddleware, minimum_size=500)


# Request timing middleware — logs slow requests (>2s) for performance monitoring
import time as _time


@app.middleware("http")
async def request_timing_middleware(request: Request, call_next):
    start = _time.perf_counter()
    response = await call_next(request)
    duration = _time.perf_counter() - start
    response.headers["X-Response-Time"] = f"{duration:.3f}s"
    if duration > 2.0:
        logging.getLogger("timing").warning(
            "SLOW %s %s took %.2fs", request.method, request.url.path, duration,
        )
    return response


# Request body size limit — reject oversized payloads before reading into memory
@app.middleware("http")
async def limit_request_body(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        return JSONResponse(
            status_code=413,
            content={"detail": f"Request too large (max {settings.MAX_UPLOAD_SIZE_MB}MB)"},
        )
    return await call_next(request)


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
    response = JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {type(exc).__name__}: {str(exc)[:300]}"},
    )
    # Ensure CORS headers are present on error responses so browsers don't
    # mask the real error message behind an opaque CORS failure.
    origin = request.headers.get("origin")
    if origin and origin in _cors_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
    return response

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
# app.include_router(knowledge_api.router)  # Removed in v2 — page deleted
app.include_router(ml_api.router)
app.include_router(market_api.router)
app.include_router(ws_api.router)
app.include_router(agent_api.router)
app.include_router(dashboard_api.router)
app.include_router(recycle_bin_api.router)
# app.include_router(news_api.router)  # Removed in v2 — page deleted
# app.include_router(watchlist_api.router)  # Removed in v2 — page deleted
app.include_router(webhook_api.router)
app.include_router(telegram_webhook_api.router)
app.include_router(prop_firm_api.router)
app.include_router(ctrader_oauth_api.router)
app.include_router(broadcast_api.router)
app.include_router(portfolio_api.router)


def _seed_admin_user():
    """Create or reset the default admin user."""
    from app.core.database import SessionLocal
    from app.models.user import User
    from app.core.auth import hash_password

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == "FlowrexAdmin").first()
        if existing:
            # Reset password to known value
            existing.password_hash = hash_password("Flowrex2025!")
            existing.must_change_password = False
            db.commit()
            logging.getLogger(__name__).info("Admin password reset to default")
            return
        admin = User(
            username="FlowrexAdmin",
            password_hash=hash_password("Flowrex2025!"),
            email="",
            is_admin=True,
            must_change_password=False,
        )
        db.add(admin)
        db.commit()
        logging.getLogger(__name__).info("Default admin user 'FlowrexAdmin' created")
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

        # Master strategy catalog — only active, verified strategies
        catalog = [
            {
                "name": "Smart Money Concepts (SMC)",
                "file": "s03_smart_money_concepts.py",
                "description": (
                    "Institutional Smart Money strategy. Detects liquidity sweeps, "
                    "order blocks, and market structure shifts. GOOD: PF 3.69, "
                    "WR 93.2%, MaxDD 0.86% on XAUUSD M5."
                ),
                "timeframes": "M5 / M15",
                "tags": ["smc", "liquidity", "order_block", "institutional"],
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
                "name": "TTM Squeeze Momentum",
                "file": "s10_ttm_squeeze.py",
                "description": (
                    "John Carter's TTM Squeeze. Bollinger Bands contracting inside "
                    "Keltner Channels signals volatility squeeze. When it fires, "
                    "enter in direction of Donchian momentum for explosive moves. "
                    "STRONG: PF 1.22, WR 45.1%, MaxDD 15.9% on XAUUSD H1."
                ),
                "timeframes": "15m / 1H / 4H / Daily",
                "tags": ["squeeze", "bollinger", "keltner", "momentum"],
            },
            {
                "name": "Woodies CCI Zero Line Reject",
                "file": "s13_woodies_cci.py",
                "description": (
                    "Ken Wood's highest-probability CCI pattern. CCI(14) trends on one "
                    "side of zero, pulls back to +/-50 zone, then resumes direction. "
                    "Turbo CCI(6) confirms timing."
                ),
                "timeframes": "5m / 15m / 1H",
                "tags": ["cci", "momentum", "intraday"],
            },
            {
                "name": "Bollinger Band Squeeze Breakout",
                "file": "s15_bb_squeeze_breakout.py",
                "description": (
                    "John Bollinger's bandwidth analysis. Detects when Bollinger Bandwidth "
                    "hits bottom-5% of its range (squeeze). Enters on expansion using "
                    "%%B for direction confirmation. "
                    "STRONG: PF 1.208, WR 38.1%, MaxDD 18.4% on US100 H1."
                ),
                "timeframes": "15m / 1H / 4H",
                "tags": ["bollinger", "squeeze", "breakout"],
            },
            {
                "name": "London Breakout Session",
                "file": "s25_london_breakout.py",
                "description": (
                    "Institutional London session strategy. Captures Asian range "
                    "(00-08 GMT) and trades the breakout at London open. Range-size "
                    "ATR filter to avoid false signals. Session-end auto-close. "
                    "STRONG: PF 1.260, WR 50.0%, MaxDD 4.8% on XAUUSD M15."
                ),
                "timeframes": "5m / 15m",
                "tags": ["session", "breakout", "intraday"],
            },
            {
                "name": "NAS100 Opening Range Breakout",
                "file": "s29_nas100_opening_range_breakout.py",
                "description": (
                    "Classic US equities ORB adapted for NAS100/US100 futures. "
                    "First 15 minutes (3x M5 bars) after the US cash open define the Opening Range. "
                    "Breakout beyond OR high/low with volume confirmation triggers entry."
                ),
                "timeframes": "M5",
                "tags": ["nas100", "breakout", "opening_range", "intraday"],
            },
            {
                "name": "BTCUSD RSI Micro Scalper",
                "file": "s41_btcusd_rsi_micro_scalper.py",
                "description": (
                    "Ultra-fast RSI(4) bounce scalp on Bitcoin M5. Catches short-term "
                    "mean-reversion moves when RSI reaches extreme levels (OS<32, OB>68), "
                    "filtered by a 42-period EMA to trade only in the prevailing direction. "
                    "Deep-optimized with 78.8% win rate and 9.9 trades/day."
                ),
                "timeframes": "M5",
                "tags": ["btcusd", "bitcoin", "rsi", "scalping", "mean_reversion"],
            },
            {
                "name": "XAUUSD RSI Micro Scalper",
                "file": "s42_xauusd_rsi_micro_scalper.py",
                "description": (
                    "Ultra-fast RSI(3) bounce scalp tuned for gold M5. Wider oversold "
                    "threshold (46) and shorter trend EMA (17) to capture gold's faster "
                    "mean-reversion dynamics. 100% robust across all time windows with "
                    "STRONG walk-forward validation."
                ),
                "timeframes": "M5",
                "tags": ["xauusd", "gold", "rsi", "scalping", "mean_reversion"],
            },
            {
                "name": "XAUUSD Momentum Burst Scalper",
                "file": "s43_xauusd_momentum_burst.py",
                "description": (
                    "Enters on large-body candles (body > 0.15x ATR) that signal a momentum "
                    "burst on gold M15, with RSI(6) confirmation to avoid chasing exhausted "
                    "moves. Captures follow-through from news events and session opens. "
                    "PF 1.194 with 14.9 trades/day, 100% robust."
                ),
                "timeframes": "M15",
                "tags": ["xauusd", "gold", "momentum", "scalping", "candle_pattern"],
            },
            {
                "name": "XAGUSD Stochastic Flip Scalper",
                "file": "s44_xagusd_stoch_flip_scalper.py",
                "description": (
                    "Trades Stochastic K/D crossovers in extreme zones on silver M5. "
                    "Silver's high beta and mean-reverting nature makes it ideal for "
                    "stochastic scalping. Deep-optimized PF 1.668 (+52% improvement), "
                    "100% robust with STRONG walk-forward validation."
                ),
                "timeframes": "M5",
                "tags": ["xagusd", "silver", "stochastic", "scalping", "mean_reversion"],
            },
            {
                "name": "Momentum ROC+SMA (Crypto)",
                "file": "s45_momentum_crypto.py",
                "description": (
                    "Walk-forward STRONG momentum strategy for crypto. ROC(10) + SMA(20) "
                    "trend filter + ATR rising volatility. BTCUSD D1 PF=1.374, "
                    "ETHUSD D1 PF=1.434. Best performing crypto strategy overall."
                ),
                "timeframes": "D1 / H4",
                "tags": ["momentum", "roc", "crypto", "trend_following"],
            },
            {
                "name": "TTM Squeeze Crypto",
                "file": "s46_ttm_squeeze_crypto.py",
                "description": (
                    "TTM Squeeze adapted for crypto 24/7 markets. BB/KC squeeze "
                    "detection with momentum breakout. Walk-forward STRONG on "
                    "BTCUSD H1 PF=1.310 with negative PF degradation (OOS > IS)."
                ),
                "timeframes": "H1 / H4",
                "tags": ["squeeze", "bollinger", "keltner", "crypto"],
            },
            {
                "name": "MACD+RSI Crypto",
                "file": "s47_macd_rsi_crypto.py",
                "description": (
                    "MACD signal cross confirmed by RSI momentum filter for crypto. "
                    "Walk-forward OK on BTCUSD H1 PF=1.166. Simple but effective "
                    "dual-confirmation entry."
                ),
                "timeframes": "H1 / H4",
                "tags": ["macd", "rsi", "crypto", "momentum"],
            },
            {
                "name": "Larry Williams V2 (Trend-Filtered)",
                "file": "s08c_larry_williams_v2.py",
                "description": (
                    "Optimized Larry Williams volatility breakout with SMA50 trend filter. "
                    "Wider TP (6x ATR) and SL (2x ATR) compensate for deferred entry. "
                    "PF 1.098, WR 27.9%, MaxDD 30.4% on US30 H1 over 12 years."
                ),
                "timeframes": "H1",
                "tags": ["volatility", "breakout", "trend_following", "williams"],
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
                "performance": {"profit_factor": 1.220, "win_rate": 45.1, "max_dd_pct": 15.9,
                                "sharpe": 1.5, "trades": 1204, "net_profit_pct": 428.4,
                                "wf_score": 85.0, "robustness": "STRONG", "symbol": "XAUUSD", "tf": "H1"},
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
                "performance": {"profit_factor": 1.208, "win_rate": 38.1, "max_dd_pct": 18.4,
                                "sharpe": 1.2, "trades": 727, "net_profit_pct": 161.9,
                                "wf_score": 80.0, "robustness": "STRONG", "symbol": "US100", "tf": "H1"},
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
                "performance": {"profit_factor": 1.260, "win_rate": 50.0, "max_dd_pct": 4.8,
                                "sharpe": 2.0, "trades": 96, "net_profit_pct": 6.7,
                                "wf_score": 75.0, "robustness": "STRONG", "symbol": "XAUUSD", "tf": "M15"},
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
            "s41_btcusd_rsi_micro_scalper.py": {
                "params": {"rsi_period": 4, "rsi_os": 32, "rsi_ob": 68, "trend_ema": 42,
                           "atr_period": 14, "atr_sl_mult": 2.25, "atr_tp_mult": 0.64,
                           "risk_per_trade": 0.005},
                "performance": {"profit_factor": 1.053, "win_rate": 78.8, "max_dd_pct": 12.3,
                                "sharpe": 0.14, "trades": 6399, "net_profit_pct": 30.5,
                                "trades_per_day": 9.9, "wf_score": 60.0, "robustness": "OK",
                                "symbol": "BTCUSD", "tf": "M5"},
            },
            "s42_xauusd_rsi_micro_scalper.py": {
                "params": {"rsi_period": 3, "rsi_os": 46, "rsi_ob": 86, "trend_ema": 17,
                           "atr_period": 14, "atr_sl_mult": 2.25, "atr_tp_mult": 1.02,
                           "risk_per_trade": 0.005},
                "performance": {"profit_factor": 1.053, "win_rate": 70.2, "max_dd_pct": 16.9,
                                "sharpe": 0.10, "trades": 9499, "net_profit_pct": 27.0,
                                "trades_per_day": 10.5, "wf_score": 80.0, "robustness": "STRONG",
                                "symbol": "XAUUSD", "tf": "M5"},
            },
            "s43_xauusd_momentum_burst.py": {
                "params": {"rsi_period": 6, "body_thresh": 0.15, "rsi_cap": 82,
                           "atr_period": 14, "atr_sl_mult": 1.93, "atr_tp_mult": 1.21,
                           "risk_per_trade": 0.005},
                "performance": {"profit_factor": 1.194, "win_rate": 66.3, "max_dd_pct": 10.7,
                                "sharpe": 0.20, "trades": 21424, "net_profit_pct": 180.5,
                                "trades_per_day": 14.9, "wf_score": 80.0, "robustness": "STRONG",
                                "symbol": "XAUUSD", "tf": "M15"},
            },
            "s44_xagusd_stoch_flip_scalper.py": {
                "params": {"stoch_k_period": 8, "stoch_d_period": 3, "stoch_os": 29,
                           "stoch_ob": 89, "trend_ema": 38, "use_trend_filter": False,
                           "atr_period": 14, "atr_sl_mult": 0.375, "atr_tp_mult": 0.93,
                           "risk_per_trade": 0.005},
                "performance": {"profit_factor": 1.668, "win_rate": 36.8, "max_dd_pct": 14.2,
                                "sharpe": 0.26, "trades": 10542, "net_profit_pct": 192.2,
                                "trades_per_day": 11.7, "wf_score": 80.0, "robustness": "STRONG",
                                "symbol": "XAGUSD", "tf": "M5"},
            },
            "s45_momentum_crypto.py": {
                "params": {"roc_period": 10, "sma_period": 20, "atr_period": 14,
                           "atr_slope_period": 5, "atr_sl_mult": 2.0, "atr_tp_mult": 4.0,
                           "cooldown_bars": 5, "risk_per_trade": 0.005},
                "performance": {"profit_factor": 1.374, "win_rate": 42.0, "max_dd_pct": 5.4,
                                "sharpe": 1.8, "trades": 54, "net_profit_pct": 65.0,
                                "wf_score": 87.0, "robustness": "STRONG", "symbol": "BTCUSD", "tf": "D1"},
            },
            "s46_ttm_squeeze_crypto.py": {
                "params": {"bb_period": 20, "bb_mult": 2.0, "kc_period": 20, "kc_mult": 1.5,
                           "mom_period": 12, "atr_period": 14, "atr_sl_mult": 1.5,
                           "atr_tp_mult": 6.0, "min_squeeze_bars": 3, "risk_per_trade": 0.005},
                "performance": {"profit_factor": 1.310, "win_rate": 20.0, "max_dd_pct": 19.5,
                                "sharpe": 1.2, "trades": 312, "net_profit_pct": 135.7,
                                "wf_score": 80.0, "robustness": "STRONG", "symbol": "BTCUSD", "tf": "H1"},
            },
            "s47_macd_rsi_crypto.py": {
                "params": {"macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
                           "rsi_period": 14, "rsi_bull_level": 50, "rsi_bear_level": 50,
                           "atr_period": 14, "atr_sl_mult": 2.0, "atr_tp_mult": 4.0,
                           "risk_per_trade": 0.005},
                "performance": {"profit_factor": 1.166, "win_rate": 29.7, "max_dd_pct": 14.2,
                                "sharpe": 0.9, "trades": 750, "net_profit_pct": 82.3,
                                "wf_score": 70.0, "robustness": "GOOD", "symbol": "BTCUSD", "tf": "H1"},
            },
            "s08c_larry_williams_v2.py": {
                "params": {"breakout_factor": 0.5, "atr_period": 14, "atr_sl_mult": 2.0,
                           "atr_tp_mult": 6.0, "cooldown_bars": 20, "risk_per_trade": 0.01,
                           "trend_sma_period": 50},
                "performance": {"profit_factor": 1.098, "win_rate": 27.9, "max_dd_pct": 30.4,
                                "sharpe": 0.43, "trades": 1380, "net_profit_pct": 297.5,
                                "wf_score": 70.0, "robustness": "GOOD", "symbol": "US30", "tf": "H1"},
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
                # Un-delete if it was soft-deleted
                if existing.deleted_at is not None:
                    existing.deleted_at = None
                    _log.info("Un-deleted strategy: %s", name)
                # Always sync settings_schema from strategy file (picks up explicit
                # SETTINGS list with groups, descriptions, proper ranges, etc.)
                if schema_list:
                    existing.settings_schema = schema_list
                    # Merge: keep user's current values, fill missing with defaults
                    cur_vals = existing.settings_values or {}
                    if isinstance(cur_vals, str):
                        try:
                            cur_vals = _json.loads(cur_vals)
                        except (ValueError, TypeError):
                            cur_vals = {}
                    merged = {**values_dict, **cur_vals}
                    existing.settings_values = merged
                    updated += 1
                # Always update verified_performance and optimized settings
                if opt_perf:
                    existing.verified_performance = opt_perf
                if opt_params:
                    existing.settings_values = values_dict
                    updated += 1
                # Sync description
                existing.description = entry["description"]
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

        # Soft-delete system strategies NOT in the catalog
        from datetime import datetime, timezone
        catalog_names = {e["name"] for e in catalog}
        catalog_names.add("Market Structure Signal (ADR)")  # Also keep MSS
        stale = db.query(Strategy).filter(
            Strategy.is_system == True,
            Strategy.deleted_at.is_(None),
            ~Strategy.name.in_(catalog_names),
        ).all()
        for s in stale:
            s.deleted_at = datetime.now(timezone.utc)
            _log.info("Soft-deleted stale strategy: %s (id=%s)", s.name, s.id)
        stale_count = len(stale)

        if added or updated or stale_count:
            db.commit()
            _log.info("Seeded %d new + updated %d + removed %d stale strategies (catalog: %d)",
                      added, updated, stale_count, len(catalog))

        # ── Seed V2-native Market Structure Signal (ADR) strategy ────────
        _log.info("Checking V2 MSS strategy seed...")
        MSS_NAME = "Market Structure Signal (ADR)"
        existing_mss = db.query(Strategy).filter(Strategy.name == MSS_NAME).first()
        if existing_mss:
            _log.info("V2 MSS already exists (id=%s)", existing_mss.id)
        if not existing_mss:
            mss_defaults = {
                "swing_lb": 42, "tp1_pct": 15.0, "tp2_pct": 25.0,
                "sl_pct": 25.0, "use_pullback": True, "pb_pct": 0.382, "confirm": "close",
            }
            mss_strat = Strategy(
                name=MSS_NAME,
                description=(
                    "V2 Market Structure Signal with ADR10-based TP/SL and Fibonacci "
                    "pullback entries. Detects swing pivot BOS/CHoCH breakouts and enters "
                    "with configurable pullback ratio. Universally profitable across "
                    "XAUUSD (PF=14.67), XAGUSD (PF=26.69), US30 (PF=11.86) on M10."
                ),
                indicators=[],
                entry_rules=[],
                exit_rules=[],
                risk_params={
                    "position_size_type": "fixed_lot",
                    "position_size_value": 0.01,
                    "max_positions": 1,
                    "max_drawdown_pct": 5.0,
                },
                filters={
                    "mss_config": dict(mss_defaults),
                    "tags": ["market_structure", "bos", "choch", "adr", "pullback"],
                    "timeframes": "M10 / M15 / H1",
                },
                is_system=True,
                strategy_type="builder",
                file_path="",
                settings_schema=[
                    {"key": "swing_lb",     "label": "Swing Lookback",       "type": "int",    "default": 42,    "min": 10,  "max": 100, "step": 1},
                    {"key": "tp1_pct",      "label": "TP1 (% of ADR10)",     "type": "float",  "default": 15.0,  "min": 5.0, "max": 60.0, "step": 0.5},
                    {"key": "tp2_pct",      "label": "TP2 (% of ADR10)",     "type": "float",  "default": 25.0,  "min": 5.0, "max": 80.0, "step": 0.5},
                    {"key": "sl_pct",       "label": "SL (% of ADR10)",      "type": "float",  "default": 25.0,  "min": 5.0, "max": 60.0, "step": 0.5},
                    {"key": "use_pullback", "label": "Use Pullback Entry",   "type": "bool",   "default": True},
                    {"key": "pb_pct",       "label": "Pullback Ratio (Fib)", "type": "float",  "default": 0.382, "min": 0.1, "max": 0.9,  "step": 0.01},
                    {"key": "confirm",      "label": "Confirmation Type",    "type": "select", "default": "close", "options": ["close", "wick"]},
                ],
                settings_values=dict(mss_defaults),
                verified_performance={
                    "profit_factor": 14.67, "win_rate": 94.8, "max_dd_pct": 0.5,
                    "sharpe": 5.0, "trades": 269, "net_profit_pct": 100.0,
                    "wf_score": 100.0, "robustness": "GOOD", "symbol": "XAUUSD", "tf": "M10",
                },
                creator_id=admin.id,
            )
            db.add(mss_strat)
            db.commit()
            _log.info("Seeded V2-native strategy: %s", MSS_NAME)
        # ─────────────────────────────────────────────────────────────────

    except Exception as e:
        import traceback
        db.rollback()
        _log.error("Failed to seed strategies: %s", e)
        _log.error("Traceback: %s", traceback.format_exc())
    finally:
        db.close()


def _register_rl_models():
    """Auto-register pre-trained RL ONNX models into the database on startup.

    Checks for ONNX files in data/ml_models/ and creates corresponding MLModel
    records if they don't already exist.  This ensures Render deployments
    automatically have RL models available in the UI without manual DB scripts.
    """
    from datetime import datetime, timezone
    from app.core.database import SessionLocal
    from app.models.ml import MLModel

    _log = logging.getLogger(__name__)

    # Master catalog of RL models shipped with the repo
    RL_CATALOG = [
        {
            "name": "RL LW US30 PPO",
            "symbol": "US30",
            "timeframe": "M5",
            "onnx_filename": "rl_lw_us30.onnx",
            "eval_avg_pnl": 640.44,
            "eval_avg_wr": 55.1,
            "eval_avg_trades": 563.7,
            "eval_avg_dd": 4.9,
            "timesteps": 500000,
            "feature_space": "lw_25",
        },
        {
            "name": "RL LW XAUUSD PPO",
            "symbol": "XAUUSD",
            "timeframe": "M5",
            "onnx_filename": "rl_lw_xauusd.onnx",
            "eval_avg_pnl": 29.04,
            "eval_avg_wr": 53.6,
            "eval_avg_trades": 587.4,
            "eval_avg_dd": 0.6,
            "timesteps": 500000,
            "feature_space": "lw_25",
        },
        {
            "name": "RL MB BTCUSD PPO",
            "symbol": "BTCUSD",
            "timeframe": "M5",
            "onnx_filename": "rl_mb_btcusd.onnx",
            "eval_avg_pnl": 335.73,
            "eval_avg_wr": 51.3,
            "eval_avg_trades": 225.0,
            "eval_avg_dd": 17.2,
            "timesteps": 1000000,
            "feature_space": "mb_25",
        },
    ]

    base_dir = os.path.join(os.path.dirname(__file__), "app", "data", "ml_models")
    # Also check the backend/data/ml_models path (Render working directory)
    alt_base_dir = os.path.join(os.path.dirname(__file__), "data", "ml_models")

    db = SessionLocal()
    try:
        registered = 0
        for m in RL_CATALOG:
            # Skip if already registered
            existing = db.query(MLModel).filter(
                MLModel.name == m["name"],
                MLModel.model_type == "rl_ppo",
            ).first()
            if existing:
                _log.debug("RL model already registered: %s (id=%d)", m["name"], existing.id)
                continue

            # Find the ONNX file on disk
            rel_path = os.path.join("data", "ml_models", m["onnx_filename"])
            abs_path = os.path.join(alt_base_dir, m["onnx_filename"])
            if not os.path.exists(abs_path):
                abs_path = os.path.join(base_dir, m["onnx_filename"])
            if not os.path.exists(abs_path):
                _log.info("RL ONNX file not found, skipping: %s", m["onnx_filename"])
                continue

            ml_record = MLModel(
                name=m["name"],
                level=3,
                model_type="rl_ppo",
                symbol=m["symbol"],
                timeframe=m["timeframe"],
                status="ready",
                model_path=rel_path,
                features_config={"feature_space": m["feature_space"], "obs_dims": 32},
                target_config={"action_space": 3, "actions": ["skip", "take", "close"]},
                hyperparams={
                    "algorithm": "PPO",
                    "timesteps": m["timesteps"],
                    "feature_space": m["feature_space"],
                },
                train_metrics={
                    "eval_avg_pnl": m["eval_avg_pnl"],
                    "eval_avg_wr": m["eval_avg_wr"],
                    "eval_avg_trades": m["eval_avg_trades"],
                    "eval_avg_dd": m["eval_avg_dd"],
                },
                val_metrics={},
                feature_importance={},
                trained_at=datetime.now(timezone.utc),
            )
            db.add(ml_record)
            db.flush()
            registered += 1
            _log.info("Registered RL model: %s (id=%d, symbol=%s)",
                       m["name"], ml_record.id, m["symbol"])

        db.commit()
        if registered:
            _log.info("Auto-registered %d new RL model(s)", registered)
    except Exception as e:
        db.rollback()
        _log.error("Failed to register RL models: %s", e)
    finally:
        db.close()


@app.on_event("startup")
async def startup_event():
    _seed_admin_user()
    _seed_all_strategies()
    _register_rl_models()
    _remove_incompatible_strategies()  # must run AFTER seeder to catch re-created python strategies
    _recalculate_agent_pnl()
    await ws_manager.start()
    try:
        await tick_aggregator.start()
    except Exception as e:
        logging.getLogger(__name__).warning("TickAggregator start skipped: %s", e)
    try:
        await mt5_streamer.start()
    except Exception as e:
        logging.getLogger(__name__).warning("MT5 streamer start skipped: %s", e)
    # Start broker price streamer (non-MT5 live tick data for Oanda/Coinbase/etc.)
    try:
        await broker_price_streamer.start()
    except Exception as e:
        logging.getLogger(__name__).warning("BrokerPriceStreamer start skipped: %s", e)
    # Start Databento live streamer (CME futures — if API key configured)
    try:
        await databento_streamer.start()
    except Exception as e:
        logging.getLogger(__name__).warning("DabentoStreamer start skipped: %s", e)
    # Register Databento as market data provider if API key is set
    if settings.DATABENTO_API_KEY:
        from app.services.market.provider import market_data, DabentoProvider
        market_data.register("databento", DabentoProvider(api_key=settings.DATABENTO_API_KEY))
        logging.getLogger(__name__).info("Databento registered as market data provider")
    try:
        await algo_engine.start()
    except Exception as e:
        logging.getLogger(__name__).warning("AlgoEngine start skipped: %s", e)
    # Start paper trade monitor (simulates SL/TP exits for paper agent trades)
    trade_monitor.subscribe_to_ticks(ws_manager)
    try:
        await trade_monitor.start()
    except Exception as e:
        logging.getLogger(__name__).warning("TradeMonitor start skipped: %s", e)
    # Start broker reconciler (syncs executed trades with broker state)
    try:
        await broker_reconciler.start()
    except Exception as e:
        logging.getLogger(__name__).warning("BrokerReconciler start skipped: %s", e)
    # Start watchlist alert checker (evaluates price alerts periodically)
    try:
        await alert_checker.start()
    except Exception as e:
        logging.getLogger(__name__).warning("AlertChecker start skipped: %s", e)
    # Register Telegram bot webhook (so /start commands auto-link users)
    if settings.TELEGRAM_BOT_TOKEN:
        from app.api.telegram_webhook import setup_telegram_webhook
        # Use the backend's own public URL (Render) for the webhook callback
        backend_url = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
        if not backend_url:
            # Fallback: derive from FRONTEND_URL (replace frontend host with API host)
            backend_url = "http://localhost:8000"
        try:
            await setup_telegram_webhook(backend_url)
        except Exception as e:
            logging.getLogger(__name__).warning("Telegram webhook setup skipped: %s", e)
    # Start news background refresh (economic calendar + market news)
    from app.services.news.aggregator import start_background_refresh as start_news_refresh
    try:
        await start_news_refresh()
    except Exception as e:
        logging.getLogger(__name__).warning("News refresh start skipped: %s", e)


@app.on_event("shutdown")
async def shutdown_event():
    await alert_checker.stop()
    await broker_reconciler.stop()
    await trade_monitor.stop()
    await algo_engine.stop()
    from app.services.news.aggregator import stop_background_refresh as stop_news_refresh
    try:
        await stop_news_refresh()
    except Exception:
        pass
    try:
        await mt5_streamer.stop()
    except Exception:
        pass
    try:
        await broker_price_streamer.stop()
    except Exception:
        pass
    try:
        await databento_streamer.stop()
    except Exception:
        pass
    await ws_manager.stop()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
