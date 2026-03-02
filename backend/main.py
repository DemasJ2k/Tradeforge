import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
        ("datasources", "is_public",   "INTEGER DEFAULT 1"),
        # DataSource instrument profile columns
        ("datasources", "pip_value",          "REAL DEFAULT 10.0"),
        ("datasources", "is_jpy_pair",        "INTEGER DEFAULT 0"),
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

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
)

# CORS — production uses FRONTEND_URL env var; dev adds localhost origins
_cors_origins = [settings.FRONTEND_URL]
if settings.DEBUG:
    _cors_origins += ["http://localhost:3000", "http://127.0.0.1:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
        ]

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
