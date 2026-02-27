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
from app.core.websocket import manager as ws_manager
from app.services.market.mt5_stream import mt5_streamer
from app.services.market.aggregator import tick_aggregator
from app.services.agent.engine import algo_engine
from app.services.agent.trade_monitor import trade_monitor

# Import all models so Base.metadata knows about them
from app.models import user, strategy, backtest, optimization, trade, datasource, knowledge, settings as settings_model  # noqa: F401
from app.models import llm as llm_model  # noqa: F401
from app.models import ml as ml_model  # noqa: F401
from app.models import invitation  # noqa: F401
from app.models import agent as agent_model  # noqa: F401

# Ensure data directories exist
Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

# Create all tables
Base.metadata.create_all(bind=engine)

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


def _seed_mss_strategy():
    """Seed the MSS system strategy into the database if it doesn't exist."""
    from app.core.database import SessionLocal
    from app.models.strategy import Strategy
    from app.models.user import User
    from app.services.strategy.mss_engine import DEFAULT_MSS_CONFIG

    db = SessionLocal()
    try:
        existing = db.query(Strategy).filter(Strategy.is_system == True, Strategy.name == "MSS – Market Structure Shift").first()
        if existing:
            return

        # Use the first admin as the owner (system strategies still need a creator_id for FK)
        admin = db.query(User).filter(User.is_admin == True).first()
        if not admin:
            admin = db.query(User).first()
        if not admin:
            import logging
            logging.getLogger(__name__).warning("Cannot seed MSS strategy: no users in DB")
            return

        mss = Strategy(
            name="MSS – Market Structure Shift",
            description=(
                "Market Structure Shift strategy. Detects Break of Structure (BOS) and "
                "Change of Character (CHoCH) patterns using pivot high/low analysis with "
                "a 42-bar lookback. Entries use pullback-adjusted limit orders with ADR10-based "
                "TP1 (15%), TP2 (25%), and SL (25%). 60/40 lot split with breakeven management."
            ),
            indicators=[
                {"id": "pivot_high", "type": "PivotHigh", "params": {"lookback": 42}, "overlay": True},
                {"id": "pivot_low", "type": "PivotLow", "params": {"lookback": 42}, "overlay": True},
                {"id": "adr10", "type": "ADR", "params": {"period": 10}, "overlay": False},
            ],
            entry_rules=[
                {"left": "price.close", "operator": "crosses_above", "right": "pivot_high", "logic": "OR"},
                {"left": "price.close", "operator": "crosses_below", "right": "pivot_low", "logic": "OR"},
            ],
            exit_rules=[
                {"left": "pnl", "operator": ">=", "right": "tp1", "logic": "OR"},
                {"left": "pnl", "operator": ">=", "right": "tp2", "logic": "OR"},
                {"left": "pnl", "operator": "<=", "right": "sl", "logic": "OR"},
                {"left": "signal", "operator": "==", "right": "reversal", "logic": "OR"},
            ],
            risk_params={
                "position_size_type": "percent_risk",
                "position_size_value": 1.0,
                "stop_loss_type": "adr_pct",
                "stop_loss_value": 25.0,
                "take_profit_type": "adr_pct",
                "take_profit_value": 15.0,
                "trailing_stop": False,
                "max_positions": 2,
                "lot_split": [0.6, 0.4],
                "breakeven_on_tp1": True,
            },
            filters={
                "mss_config": DEFAULT_MSS_CONFIG,
            },
            is_system=True,
            creator_id=admin.id,
        )
        db.add(mss)
        db.commit()
        import logging
        logging.getLogger(__name__).info("Seeded MSS system strategy (id=%d)", mss.id)
    finally:
        db.close()


def _seed_gold_breakout_strategy():
    """Seed the Gold Breakout system strategy into the database if it doesn't exist."""
    from app.core.database import SessionLocal
    from app.models.strategy import Strategy
    from app.models.user import User
    from app.services.strategy.gold_bt_engine import DEFAULT_GOLD_BT_CONFIG

    db = SessionLocal()
    try:
        existing = db.query(Strategy).filter(Strategy.is_system == True, Strategy.name == "Gold Breakout").first()
        if existing:
            return

        admin = db.query(User).filter(User.is_admin == True).first()
        if not admin:
            admin = db.query(User).first()
        if not admin:
            import logging
            logging.getLogger(__name__).warning("Cannot seed Gold Breakout strategy: no users in DB")
            return

        gold = Strategy(
            name="Gold Breakout",
            description=(
                "Gold Breakout Trader strategy. Every N hours, captures a reference price and builds "
                "a gray box zone (±boxHeight/2). Buy Stop is placed above the box, Sell Stop below. "
                "Entries trigger on price crossover of those stops. TP1/TP2/TP3 stacked above/below "
                "with configurable zone heights and gaps. SL defaults to the opposite stop level."
            ),
            indicators=[
                {"id": "box_high", "type": "GoldBTBox", "params": {"side": "top"}, "overlay": True},
                {"id": "box_low", "type": "GoldBTBox", "params": {"side": "bottom"}, "overlay": True},
                {"id": "buy_stop", "type": "GoldBTStop", "params": {"direction": "buy"}, "overlay": True},
                {"id": "sell_stop", "type": "GoldBTStop", "params": {"direction": "sell"}, "overlay": True},
            ],
            entry_rules=[
                {"left": "price.close", "operator": "crosses_above", "right": "buy_stop", "logic": "OR", "direction": "long"},
                {"left": "price.close", "operator": "crosses_below", "right": "sell_stop", "logic": "OR", "direction": "short"},
            ],
            exit_rules=[
                {"left": "pnl", "operator": ">=", "right": "tp1", "logic": "OR"},
                {"left": "pnl", "operator": ">=", "right": "tp2", "logic": "OR"},
                {"left": "pnl", "operator": "<=", "right": "sl", "logic": "OR"},
                {"left": "signal", "operator": "==", "right": "reversal", "logic": "OR"},
            ],
            risk_params={
                "position_size_type": "percent_risk",
                "position_size_value": 1.0,
                "stop_loss_type": "opposite_stop",
                "take_profit_type": "zone",
                "trailing_stop": False,
                "max_positions": 2,
                "lot_split": [0.5, 0.5],
                "breakeven_on_tp1": True,
            },
            filters={
                "gold_bt_config": DEFAULT_GOLD_BT_CONFIG,
            },
            is_system=True,
            creator_id=admin.id,
        )
        db.add(gold)
        db.commit()
        import logging
        logging.getLogger(__name__).info("Seeded Gold Breakout system strategy (id=%d)", gold.id)
    finally:
        db.close()


def _seed_system_strategies():
    """Seed the 4 system trading strategies from strategies.txt if they don't exist."""
    from app.core.database import SessionLocal
    from app.models.strategy import Strategy
    from app.models.user import User

    SYSTEM_STRATEGIES = [
        {
            "name": "VWAP + MACD Breakout Scalper",
            "description": (
                "Momentum breakout strategy. Trades above/below VWAP confirmed by MACD crossovers. "
                "Best on 1m/5m timeframes for XAUUSD. Uses ATR-based stops and MACD signal-cross exits."
            ),
            "indicators": [
                {"id": "vwap_1", "type": "VWAP", "params": {}, "overlay": True},
                {"id": "macd_1", "type": "MACD", "params": {"fast": 12, "slow": 26, "signal": 9, "source": "close"}, "overlay": False},
                {"id": "atr_1", "type": "ATR", "params": {"period": 14}, "overlay": False},
            ],
            "entry_rules": [
                {"left": "price.close", "operator": "crosses_above", "right": "vwap_1", "logic": "AND", "direction": "long"},
                {"left": "macd_1", "operator": "crosses_above", "right": "macd_1_signal", "logic": "AND", "direction": "long"},
                {"left": "price.close", "operator": "crosses_below", "right": "vwap_1", "logic": "OR", "direction": "short"},
                {"left": "macd_1", "operator": "crosses_below", "right": "macd_1_signal", "logic": "AND", "direction": "short"},
            ],
            "exit_rules": [
                {"left": "macd_1", "operator": "crosses_below", "right": "macd_1_signal", "logic": "OR", "direction": "long"},
                {"left": "macd_1", "operator": "crosses_above", "right": "macd_1_signal", "logic": "OR", "direction": "short"},
            ],
            "risk_params": {
                "position_size_type": "fixed_lot",
                "position_size_value": 0.01,
                "stop_loss_type": "atr_multiple",
                "stop_loss_value": 1.5,
                "take_profit_type": "atr_multiple",
                "take_profit_value": 2.0,
                "trailing_stop": True,
                "trailing_stop_type": "atr_multiple",
                "trailing_stop_value": 1.0,
                "max_positions": 1,
                "max_drawdown_pct": 5.0,
            },
            "filters": {
                "time_start": "08:00",
                "time_end": "17:00",
                "days_of_week": [0, 1, 2, 3, 4],
            },
        },
        {
            "name": "RSI + Bollinger Band Reversal",
            "description": (
                "Mean-reversion scalper. Enters when price touches outer Bollinger Band with RSI "
                "confirming oversold/overbought reversal. ADX filter ensures range-bound conditions. "
                "Best on 1m for XAUUSD."
            ),
            "indicators": [
                {"id": "rsi_1", "type": "RSI", "params": {"period": 14, "source": "close"}, "overlay": False},
                {"id": "bb_1", "type": "Bollinger", "params": {"period": 20, "std_dev": 2, "source": "close"}, "overlay": True},
                {"id": "atr_1", "type": "ATR", "params": {"period": 14}, "overlay": False},
                {"id": "adx_1", "type": "ADX", "params": {"period": 14}, "overlay": False},
            ],
            "entry_rules": [
                {"left": "price.close", "operator": "<=", "right": "bb_1_lower", "logic": "AND", "direction": "long"},
                {"left": "rsi_1", "operator": "crosses_above", "right": "30", "logic": "AND", "direction": "long"},
                {"left": "price.close", "operator": ">=", "right": "bb_1_upper", "logic": "OR", "direction": "short"},
                {"left": "rsi_1", "operator": "crosses_below", "right": "70", "logic": "AND", "direction": "short"},
            ],
            "exit_rules": [
                {"left": "price.close", "operator": ">=", "right": "bb_1", "logic": "OR", "direction": "long"},
                {"left": "price.close", "operator": "<=", "right": "bb_1", "logic": "OR", "direction": "short"},
            ],
            "risk_params": {
                "position_size_type": "fixed_lot",
                "position_size_value": 0.01,
                "stop_loss_type": "atr_multiple",
                "stop_loss_value": 1.0,
                "take_profit_type": "atr_multiple",
                "take_profit_value": 1.5,
                "trailing_stop": True,
                "trailing_stop_type": "atr_multiple",
                "trailing_stop_value": 1.0,
                "max_positions": 1,
                "max_drawdown_pct": 5.0,
            },
            "filters": {
                "time_start": "08:00",
                "time_end": "17:00",
                "days_of_week": [0, 1, 2, 3, 4],
                "min_adx": 0,
                "max_adx": 25,
            },
        },
        {
            "name": "200-EMA + VWAP Trend Scalper",
            "description": (
                "Multi-timeframe trend scalper. Uses 200-EMA as trend filter and VWAP for intraday "
                "entries. Trades pullbacks to VWAP in the direction of the 200-EMA trend. "
                "Best on 1m/5m with 15m trend confirmation."
            ),
            "indicators": [
                {"id": "ema200", "type": "EMA", "params": {"period": 200, "source": "close"}, "overlay": True},
                {"id": "vwap_1", "type": "VWAP", "params": {}, "overlay": True},
                {"id": "atr_1", "type": "ATR", "params": {"period": 14}, "overlay": False},
            ],
            "entry_rules": [
                {"left": "price.close", "operator": ">", "right": "ema200", "logic": "AND", "direction": "long"},
                {"left": "price.close", "operator": "crosses_above", "right": "vwap_1", "logic": "AND", "direction": "long"},
                {"left": "price.close", "operator": "<", "right": "ema200", "logic": "OR", "direction": "short"},
                {"left": "price.close", "operator": "crosses_below", "right": "vwap_1", "logic": "AND", "direction": "short"},
            ],
            "exit_rules": [
                {"left": "price.close", "operator": "crosses_below", "right": "vwap_1", "logic": "OR", "direction": "long"},
                {"left": "price.close", "operator": "crosses_above", "right": "vwap_1", "logic": "OR", "direction": "short"},
            ],
            "risk_params": {
                "position_size_type": "fixed_lot",
                "position_size_value": 0.01,
                "stop_loss_type": "atr_multiple",
                "stop_loss_value": 1.5,
                "take_profit_type": "fixed_pips",
                "take_profit_value": 15,
                "trailing_stop": True,
                "trailing_stop_type": "atr_multiple",
                "trailing_stop_value": 1.0,
                "max_positions": 1,
                "max_drawdown_pct": 5.0,
            },
            "filters": {
                "time_start": "08:00",
                "time_end": "17:00",
                "days_of_week": [0, 1, 2, 3, 4],
            },
        },
        {
            "name": "Pivot Point Breakout/Reversal",
            "description": (
                "Dual-mode pivot strategy. In trending markets (ADX>20), trades breakouts through "
                "the daily central pivot targeting R1/S1. In ranging markets (ADX<20), trades bounces "
                "off pivot support/resistance with Stochastic confirmation. Best on 5m/15m."
            ),
            "indicators": [
                {"id": "pivots", "type": "Pivot", "params": {"type": "standard"}, "overlay": True},
                {"id": "adx_1", "type": "ADX", "params": {"period": 14}, "overlay": False},
                {"id": "stoch_1", "type": "Stochastic", "params": {"k_period": 14, "d_period": 3, "smooth": 3}, "overlay": False},
                {"id": "atr_1", "type": "ATR", "params": {"period": 14}, "overlay": False},
            ],
            "entry_rules": [
                {"left": "price.close", "operator": "crosses_above", "right": "pivots_pp", "logic": "AND", "direction": "long"},
                {"left": "stoch_1", "operator": "crosses_above", "right": "20", "logic": "AND", "direction": "long"},
                {"left": "price.close", "operator": "crosses_below", "right": "pivots_pp", "logic": "OR", "direction": "short"},
                {"left": "stoch_1", "operator": "crosses_below", "right": "80", "logic": "AND", "direction": "short"},
            ],
            "exit_rules": [
                {"left": "price.close", "operator": ">=", "right": "pivots_r1", "logic": "OR", "direction": "long"},
                {"left": "price.close", "operator": "<=", "right": "pivots_s1", "logic": "OR", "direction": "short"},
            ],
            "risk_params": {
                "position_size_type": "fixed_lot",
                "position_size_value": 0.01,
                "stop_loss_type": "atr_multiple",
                "stop_loss_value": 1.0,
                "take_profit_type": "pivot_level",
                "take_profit_value": 1.0,
                "take_profit_2_type": "pivot_level",
                "take_profit_2_value": 2.0,
                "lot_split": [0.5, 0.5],
                "breakeven_on_tp1": True,
                "trailing_stop": False,
                "max_positions": 1,
                "max_drawdown_pct": 5.0,
            },
            "filters": {
                "time_start": "08:00",
                "time_end": "17:00",
                "days_of_week": [0, 1, 2, 3, 4],
                "min_adx": 0,
                "max_adx": 0,
            },
        },
    ]

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.is_admin == True).first()
        if not admin:
            admin = db.query(User).first()
        if not admin:
            return

        for cfg in SYSTEM_STRATEGIES:
            existing = db.query(Strategy).filter(
                Strategy.is_system == True,
                Strategy.name == cfg["name"],
            ).first()
            if existing:
                continue

            strat = Strategy(
                name=cfg["name"],
                description=cfg["description"],
                indicators=cfg["indicators"],
                entry_rules=cfg["entry_rules"],
                exit_rules=cfg["exit_rules"],
                risk_params=cfg["risk_params"],
                filters=cfg["filters"],
                is_system=True,
                creator_id=admin.id,
            )
            db.add(strat)

        db.commit()
        import logging
        logging.getLogger(__name__).info("System strategies seeded successfully")
    finally:
        db.close()


@app.on_event("startup")
async def startup_event():
    _seed_admin_user()
    _seed_mss_strategy()
    _seed_gold_breakout_strategy()
    _seed_system_strategies()
    await ws_manager.start()
    await tick_aggregator.start()
    try:
        await mt5_streamer.start()
    except Exception as e:
        logging.getLogger(__name__).warning("MT5 streamer start skipped: %s", e)
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
    await ws_manager.stop()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
