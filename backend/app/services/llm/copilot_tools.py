"""AI Copilot Tool Registry — Defines all actions the AI assistant can take.

Each tool is a decorated async function that:
  - Receives (db: Session, user_id: int, **kwargs)
  - Returns a dict with the result (serializable to JSON)
  - Has a permission level: "auto" (read-only), "confirm" (needs approval), "blocked"

Tool schemas follow JSON Schema format for LLM function calling.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ── Tool Registration ─────────────────────────────────────────────────

@dataclass
class CopilotTool:
    name: str
    description: str
    parameters: dict           # JSON Schema for arguments
    permission: str            # "auto" | "confirm" | "blocked"
    handler: Callable          # async (db, user_id, **kwargs) -> dict
    category: str = "general"  # UI grouping


TOOL_REGISTRY: dict[str, CopilotTool] = {}


def copilot_tool(
    name: str,
    description: str,
    parameters: dict,
    permission: str = "auto",
    category: str = "general",
):
    """Decorator to register a copilot tool."""
    def decorator(func):
        TOOL_REGISTRY[name] = CopilotTool(
            name=name,
            description=description,
            parameters=parameters,
            permission=permission,
            handler=func,
            category=category,
        )
        return func
    return decorator


# ── Format Conversion (provider-specific tool schemas) ────────────────

def tools_for_claude(tools: list[CopilotTool]) -> list[dict]:
    """Convert to Anthropic Claude tool format."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.parameters,
        }
        for t in tools
    ]


def tools_for_openai(tools: list[CopilotTool]) -> list[dict]:
    """Convert to OpenAI function calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def tools_for_gemini(tools: list[CopilotTool]) -> list[dict]:
    """Convert to Google Gemini function declaration format."""
    return [{
        "function_declarations": [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in tools
        ]
    }]


def get_tools_for_provider(provider_name: str, tools: list[CopilotTool]) -> list[dict]:
    """Get tool definitions formatted for the specified provider."""
    if provider_name == "claude":
        return tools_for_claude(tools)
    elif provider_name == "openai":
        return tools_for_openai(tools)
    elif provider_name == "gemini":
        return tools_for_gemini(tools)
    return tools_for_claude(tools)  # default


# ══════════════════════════════════════════════════════════════════════
#  AUTO TOOLS — Read-only, execute without asking
# ══════════════════════════════════════════════════════════════════════


@copilot_tool(
    name="list_strategies",
    description="List all trading strategies available to the user. Returns strategy name, ID, type (python/builder), and a short description for each.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    permission="auto",
    category="strategies",
)
async def list_strategies(db: Session, user_id: int, **kwargs) -> dict:
    from sqlalchemy import or_
    from app.models.strategy import Strategy

    strategies = (
        db.query(Strategy)
        .filter(or_(Strategy.creator_id == user_id, Strategy.is_system == True))
        .filter(Strategy.deleted_at.is_(None))
        .order_by(Strategy.is_system.desc(), Strategy.updated_at.desc())
        .all()
    )
    return {
        "strategies": [
            {
                "id": s.id,
                "name": s.name,
                "type": s.strategy_type or "builder",
                "is_system": bool(s.is_system),
                "description": (s.description or "")[:120],
            }
            for s in strategies
        ],
        "total": len(strategies),
    }


@copilot_tool(
    name="get_strategy",
    description="Get detailed information about a specific trading strategy by its ID. Returns indicators, entry/exit rules, risk parameters, and settings.",
    parameters={
        "type": "object",
        "properties": {
            "strategy_id": {"type": "integer", "description": "The strategy ID to look up"},
        },
        "required": ["strategy_id"],
    },
    permission="auto",
    category="strategies",
)
async def get_strategy(db: Session, user_id: int, strategy_id: int = 0, **kwargs) -> dict:
    from sqlalchemy import or_
    from app.models.strategy import Strategy

    s = db.query(Strategy).filter(
        Strategy.id == strategy_id,
        or_(Strategy.creator_id == user_id, Strategy.is_system == True),
        Strategy.deleted_at.is_(None),
    ).first()
    if not s:
        return {"error": f"Strategy {strategy_id} not found."}

    return {
        "id": s.id,
        "name": s.name,
        "type": s.strategy_type or "builder",
        "description": s.description or "",
        "indicators": s.indicators or [],
        "entry_rules": s.entry_rules or [],
        "exit_rules": s.exit_rules or [],
        "risk_params": s.risk_params or {},
        "settings_schema": s.settings_schema or {},
        "settings_values": s.settings_values or {},
        "verified_performance": s.verified_performance or {},
    }


@copilot_tool(
    name="list_data_sources",
    description="List all data sources (CSV datasets) available for backtesting. Returns symbol, timeframe, bar count, and date range for each.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    permission="auto",
    category="data",
)
async def list_data_sources(db: Session, user_id: int, **kwargs) -> dict:
    from app.models.datasource import DataSource

    sources = (
        db.query(DataSource)
        .filter(DataSource.deleted_at.is_(None))
        .order_by(DataSource.created_at.desc())
        .all()
    )
    return {
        "data_sources": [
            {
                "id": ds.id,
                "symbol": ds.symbol or "",
                "timeframe": ds.timeframe or "",
                "bars": ds.row_count or 0,
                "date_from": str(ds.date_from) if ds.date_from else "",
                "date_to": str(ds.date_to) if ds.date_to else "",
            }
            for ds in sources
        ],
        "total": len(sources),
    }


@copilot_tool(
    name="list_backtests",
    description="List recent backtest runs with their key stats (net profit, win rate, profit factor, max drawdown, trade count). Returns the most recent 20 backtests.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    permission="auto",
    category="backtesting",
)
async def list_backtests(db: Session, user_id: int, **kwargs) -> dict:
    from app.models.backtest import Backtest

    runs = (
        db.query(Backtest)
        .filter(Backtest.user_id == user_id)
        .order_by(Backtest.created_at.desc())
        .limit(20)
        .all()
    )
    items = []
    for r in runs:
        stats = r.stats if isinstance(r.stats, dict) else {}
        items.append({
            "id": r.id,
            "strategy_name": r.strategy_name or "",
            "symbol": r.symbol or "",
            "timeframe": r.timeframe or "",
            "net_profit": stats.get("net_profit", 0),
            "win_rate": stats.get("win_rate", 0),
            "profit_factor": stats.get("profit_factor", 0),
            "max_drawdown_pct": stats.get("max_drawdown_pct", 0),
            "total_trades": stats.get("total_trades", 0),
            "created_at": r.created_at.isoformat() if r.created_at else "",
        })
    return {"backtests": items, "total": len(items)}


@copilot_tool(
    name="get_backtest_results",
    description="Get detailed results for a specific backtest run. Returns full stats, trade list summary, and equity curve info.",
    parameters={
        "type": "object",
        "properties": {
            "backtest_id": {"type": "integer", "description": "The backtest ID to retrieve"},
        },
        "required": ["backtest_id"],
    },
    permission="auto",
    category="backtesting",
)
async def get_backtest_results(db: Session, user_id: int, backtest_id: int = 0, **kwargs) -> dict:
    from app.models.backtest import Backtest

    bt = db.query(Backtest).filter(
        Backtest.id == backtest_id,
        Backtest.user_id == user_id,
    ).first()
    if not bt:
        return {"error": f"Backtest {backtest_id} not found."}

    stats = bt.stats if isinstance(bt.stats, dict) else {}
    v2_stats = bt.v2_stats if isinstance(getattr(bt, 'v2_stats', None), dict) else {}
    trades = bt.trades if isinstance(bt.trades, list) else []

    return {
        "id": bt.id,
        "strategy_name": bt.strategy_name or "",
        "symbol": bt.symbol or "",
        "timeframe": bt.timeframe or "",
        "stats": stats,
        "extended_stats": v2_stats,
        "trade_count": len(trades),
        "first_5_trades": trades[:5],
        "last_5_trades": trades[-5:] if len(trades) > 5 else [],
    }


@copilot_tool(
    name="list_agents",
    description="List all trading agents with their status (running/stopped/paused), strategy, symbol, and mode (paper/live).",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    permission="auto",
    category="agents",
)
async def list_agents(db: Session, user_id: int, **kwargs) -> dict:
    from app.models.agent import TradingAgent

    agents = (
        db.query(TradingAgent)
        .filter(TradingAgent.created_by == user_id)
        .filter(TradingAgent.deleted_at.is_(None))
        .order_by(TradingAgent.updated_at.desc())
        .all()
    )
    return {
        "agents": [
            {
                "id": a.id,
                "name": a.name,
                "strategy_id": a.strategy_id,
                "symbol": a.symbol or "",
                "timeframe": a.timeframe or "",
                "mode": a.mode or "paper",
                "status": a.status or "stopped",
            }
            for a in agents
        ],
        "total": len(agents),
    }


@copilot_tool(
    name="get_agent_performance",
    description="Get performance metrics for a specific trading agent including P&L, win rate, and recent trades.",
    parameters={
        "type": "object",
        "properties": {
            "agent_id": {"type": "integer", "description": "The agent ID to check"},
        },
        "required": ["agent_id"],
    },
    permission="auto",
    category="agents",
)
async def get_agent_performance(db: Session, user_id: int, agent_id: int = 0, **kwargs) -> dict:
    from app.models.agent import TradingAgent, AgentTrade

    agent = db.query(TradingAgent).filter(
        TradingAgent.id == agent_id,
        TradingAgent.created_by == user_id,
    ).first()
    if not agent:
        return {"error": f"Agent {agent_id} not found."}

    perf = agent.performance_stats if isinstance(agent.performance_stats, dict) else {}
    trades = (
        db.query(AgentTrade)
        .filter(AgentTrade.agent_id == agent_id)
        .order_by(AgentTrade.created_at.desc())
        .limit(10)
        .all()
    )
    return {
        "agent_name": agent.name,
        "status": agent.status,
        "performance": perf,
        "recent_trades": [
            {
                "symbol": t.symbol,
                "direction": t.direction,
                "pnl": t.pnl,
                "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else "",
            }
            for t in trades
        ],
    }


@copilot_tool(
    name="get_account_info",
    description="Get trading account information from the connected broker: balance, equity, margin, unrealized P&L. Returns an error if no broker is connected.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    permission="auto",
    category="broker",
)
async def get_account_info(db: Session, user_id: int, **kwargs) -> dict:
    try:
        from app.services.broker.manager import broker_manager
        adapter = broker_manager.get_adapter()
        if not adapter:
            return {"error": "No broker connected. Connect a broker first in Settings → Brokers."}
        info = await adapter.get_account_info()
        return {
            "balance": getattr(info, "balance", 0),
            "equity": getattr(info, "equity", 0),
            "currency": getattr(info, "currency", "USD"),
            "unrealized_pnl": getattr(info, "unrealized_pnl", 0),
        }
    except Exception as e:
        return {"error": f"Could not get account info: {str(e)[:200]}"}


@copilot_tool(
    name="get_positions",
    description="Get all currently open positions from the connected broker. Shows symbol, direction, size, entry price, current P&L.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    permission="auto",
    category="broker",
)
async def get_positions(db: Session, user_id: int, **kwargs) -> dict:
    try:
        from app.services.broker.manager import broker_manager
        adapter = broker_manager.get_adapter()
        if not adapter:
            return {"error": "No broker connected."}
        positions = await adapter.get_positions()
        return {
            "positions": [
                {
                    "symbol": getattr(p, "symbol", ""),
                    "direction": getattr(p, "direction", ""),
                    "size": getattr(p, "size", 0),
                    "entry_price": getattr(p, "entry_price", 0),
                    "current_pnl": getattr(p, "pnl", 0),
                }
                for p in (positions or [])
            ],
            "total": len(positions or []),
        }
    except Exception as e:
        return {"error": f"Could not get positions: {str(e)[:200]}"}


@copilot_tool(
    name="get_orders",
    description="Get all pending orders from the connected broker.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    permission="auto",
    category="broker",
)
async def get_orders(db: Session, user_id: int, **kwargs) -> dict:
    try:
        from app.services.broker.manager import broker_manager
        adapter = broker_manager.get_adapter()
        if not adapter:
            return {"error": "No broker connected."}
        orders = await adapter.get_orders()
        return {
            "orders": [
                {
                    "id": getattr(o, "order_id", ""),
                    "symbol": getattr(o, "symbol", ""),
                    "side": getattr(o, "side", ""),
                    "size": getattr(o, "size", 0),
                    "type": getattr(o, "order_type", ""),
                    "price": getattr(o, "price", 0),
                }
                for o in (orders or [])
            ],
        }
    except Exception as e:
        return {"error": f"Could not get orders: {str(e)[:200]}"}


@copilot_tool(
    name="get_news_calendar",
    description="Get upcoming economic calendar events. Shows event name, date/time, impact level (high/medium/low), and relevant currency.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    permission="auto",
    category="news",
)
async def get_news_calendar(db: Session, user_id: int, **kwargs) -> dict:
    try:
        from app.services.news.aggregator import get_calendar_events
        events = await get_calendar_events()
        return {
            "events": events[:20] if events else [],
            "total": len(events or []),
        }
    except Exception:
        return {"events": [], "note": "News service not available."}


@copilot_tool(
    name="get_dashboard_summary",
    description="Get a dashboard overview: total strategies, data sources, recent backtests, active agents, and portfolio summary.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    permission="auto",
    category="general",
)
async def get_dashboard_summary(db: Session, user_id: int, **kwargs) -> dict:
    from sqlalchemy import or_, func
    from app.models.strategy import Strategy
    from app.models.datasource import DataSource
    from app.models.backtest import Backtest
    from app.models.agent import TradingAgent

    n_strategies = db.query(func.count(Strategy.id)).filter(
        or_(Strategy.creator_id == user_id, Strategy.is_system == True),
        Strategy.deleted_at.is_(None),
    ).scalar() or 0

    n_datasources = db.query(func.count(DataSource.id)).filter(
        DataSource.deleted_at.is_(None),
    ).scalar() or 0

    n_backtests = db.query(func.count(Backtest.id)).filter(
        Backtest.user_id == user_id,
    ).scalar() or 0

    n_agents = db.query(func.count(TradingAgent.id)).filter(
        TradingAgent.created_by == user_id,
        TradingAgent.deleted_at.is_(None),
    ).scalar() or 0

    running_agents = db.query(func.count(TradingAgent.id)).filter(
        TradingAgent.created_by == user_id,
        TradingAgent.status == "running",
        TradingAgent.deleted_at.is_(None),
    ).scalar() or 0

    return {
        "strategies": n_strategies,
        "data_sources": n_datasources,
        "backtests": n_backtests,
        "agents": n_agents,
        "running_agents": running_agents,
    }


# ══════════════════════════════════════════════════════════════════════
#  CONFIRM TOOLS — Side effects, require user approval
# ══════════════════════════════════════════════════════════════════════


@copilot_tool(
    name="run_backtest",
    description="Run a backtest using the V3 engine. Requires a strategy ID and data source ID. Optionally set initial balance, spread, and commission.",
    parameters={
        "type": "object",
        "properties": {
            "strategy_id": {"type": "integer", "description": "Strategy ID to backtest"},
            "datasource_id": {"type": "integer", "description": "Data source ID to use"},
            "initial_balance": {"type": "number", "description": "Starting balance (default 10000)", "default": 10000},
            "spread_points": {"type": "number", "description": "Spread in points (default 0)", "default": 0},
            "commission_per_lot": {"type": "number", "description": "Commission per lot (default 7)", "default": 7},
        },
        "required": ["strategy_id", "datasource_id"],
    },
    permission="confirm",
    category="backtesting",
)
async def run_backtest(
    db: Session, user_id: int,
    strategy_id: int = 0, datasource_id: int = 0,
    initial_balance: float = 10000, spread_points: float = 0,
    commission_per_lot: float = 7,
    **kwargs,
) -> dict:
    """Execute a V3 backtest and return results."""
    from app.models.strategy import Strategy
    from app.models.datasource import DataSource
    from app.models.backtest import Backtest
    from sqlalchemy import or_
    import time

    strategy = db.query(Strategy).filter(
        Strategy.id == strategy_id,
        or_(Strategy.creator_id == user_id, Strategy.is_system == True),
    ).first()
    if not strategy:
        return {"error": f"Strategy {strategy_id} not found."}

    datasource = db.query(DataSource).filter(DataSource.id == datasource_id).first()
    if not datasource:
        return {"error": f"Data source {datasource_id} not found."}

    # Load bars from CSV
    try:
        from app.api.backtest import _resolve_csv_path, _ensure_dict
        import csv as csv_mod

        csv_path = _resolve_csv_path(datasource.filepath)
        if not csv_path:
            return {"error": f"CSV file not found for data source {datasource_id}"}

        bars = []
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv_mod.DictReader(f)
            for row in reader:
                bars.append({
                    "time": row.get("time", row.get("timestamp", row.get("date", ""))),
                    "open": float(row.get("open", 0)),
                    "high": float(row.get("high", 0)),
                    "low": float(row.get("low", 0)),
                    "close": float(row.get("close", 0)),
                    "volume": float(row.get("volume", row.get("tick_volume", 0))),
                })

        # Build strategy config
        strategy_config = {
            "indicators": strategy.indicators or [],
            "entry_rules": strategy.entry_rules or [],
            "exit_rules": strategy.exit_rules or [],
            "risk_params": strategy.risk_params or {},
            "filters": strategy.filters or [],
            "strategy_type": strategy.strategy_type or "builder",
            "file_path": strategy.file_path or "",
            "settings_values": _ensure_dict(getattr(strategy, "settings_values", {}) or {}),
        }

        from app.services.backtest_engine.v3_adapter import run_v3_backtest, v3_result_to_api_response

        symbol = datasource.symbol or "ASSET"
        point_value = float(datasource.point_value or 1)

        t0 = time.time()
        result = run_v3_backtest(
            bars=bars,
            strategy_config=strategy_config,
            symbol=symbol,
            initial_balance=initial_balance,
            spread_points=spread_points,
            commission_per_lot=commission_per_lot,
            point_value=point_value,
        )
        elapsed = time.time() - t0

        api_resp = v3_result_to_api_response(result, initial_balance, len(bars))

        # Save to DB
        bt = Backtest(
            user_id=user_id,
            strategy_id=strategy.id,
            strategy_name=strategy.name,
            datasource_id=datasource.id,
            symbol=symbol,
            timeframe=datasource.timeframe or "",
            initial_balance=initial_balance,
            stats=api_resp.get("stats", {}),
            v2_stats=api_resp.get("v2_stats", {}),
            trades=api_resp.get("trades", []),
            equity_curve=api_resp.get("equity_curve", []),
            tearsheet=api_resp.get("tearsheet", {}),
            engine_version="v3",
        )
        db.add(bt)
        db.commit()
        db.refresh(bt)

        stats = api_resp.get("stats", {})
        return {
            "backtest_id": bt.id,
            "strategy": strategy.name,
            "symbol": symbol,
            "total_trades": stats.get("total_trades", 0),
            "net_profit": stats.get("net_profit", 0),
            "win_rate": stats.get("win_rate", 0),
            "profit_factor": stats.get("profit_factor", 0),
            "max_drawdown_pct": stats.get("max_drawdown_pct", 0),
            "sharpe_ratio": stats.get("sharpe_ratio", 0),
            "elapsed_seconds": round(elapsed, 2),
        }
    except Exception as e:
        logger.exception("Copilot run_backtest failed")
        return {"error": f"Backtest failed: {str(e)[:300]}"}


@copilot_tool(
    name="start_agent",
    description="Start a trading agent so it begins monitoring the market and executing trades according to its strategy.",
    parameters={
        "type": "object",
        "properties": {
            "agent_id": {"type": "integer", "description": "The agent ID to start"},
        },
        "required": ["agent_id"],
    },
    permission="confirm",
    category="agents",
)
async def start_agent(db: Session, user_id: int, agent_id: int = 0, **kwargs) -> dict:
    from app.models.agent import TradingAgent

    agent = db.query(TradingAgent).filter(
        TradingAgent.id == agent_id,
        TradingAgent.created_by == user_id,
    ).first()
    if not agent:
        return {"error": f"Agent {agent_id} not found."}
    if agent.status == "running":
        return {"message": f"Agent '{agent.name}' is already running."}

    agent.status = "running"
    db.commit()
    return {"message": f"Agent '{agent.name}' started successfully.", "status": "running"}


@copilot_tool(
    name="stop_agent",
    description="Stop a running trading agent. It will stop monitoring and won't place new trades.",
    parameters={
        "type": "object",
        "properties": {
            "agent_id": {"type": "integer", "description": "The agent ID to stop"},
        },
        "required": ["agent_id"],
    },
    permission="confirm",
    category="agents",
)
async def stop_agent(db: Session, user_id: int, agent_id: int = 0, **kwargs) -> dict:
    from app.models.agent import TradingAgent

    agent = db.query(TradingAgent).filter(
        TradingAgent.id == agent_id,
        TradingAgent.created_by == user_id,
    ).first()
    if not agent:
        return {"error": f"Agent {agent_id} not found."}

    agent.status = "stopped"
    db.commit()
    return {"message": f"Agent '{agent.name}' stopped.", "status": "stopped"}


@copilot_tool(
    name="place_order",
    description="Place a trading order through the connected broker. Specify symbol, direction (buy/sell), lot size, and optional SL/TP prices.",
    parameters={
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Trading symbol (e.g., XAUUSD, EURUSD)"},
            "side": {"type": "string", "enum": ["buy", "sell"], "description": "Order direction"},
            "size": {"type": "number", "description": "Lot size (e.g., 0.01, 0.1, 1.0)"},
            "stop_loss": {"type": "number", "description": "Stop loss price (optional)"},
            "take_profit": {"type": "number", "description": "Take profit price (optional)"},
        },
        "required": ["symbol", "side", "size"],
    },
    permission="confirm",
    category="broker",
)
async def place_order(
    db: Session, user_id: int,
    symbol: str = "", side: str = "", size: float = 0,
    stop_loss: float = 0, take_profit: float = 0,
    **kwargs,
) -> dict:
    try:
        from app.services.broker.manager import broker_manager
        adapter = broker_manager.get_adapter()
        if not adapter:
            return {"error": "No broker connected."}

        result = await adapter.place_order(
            symbol=symbol, side=side, size=size,
            order_type="market",
            stop_loss=stop_loss if stop_loss else None,
            take_profit=take_profit if take_profit else None,
        )
        return {
            "message": f"Order placed: {side} {size} {symbol}",
            "order_id": getattr(result, "order_id", ""),
        }
    except Exception as e:
        return {"error": f"Order failed: {str(e)[:200]}"}


@copilot_tool(
    name="close_position",
    description="Close an open position by symbol. Closes the full position size.",
    parameters={
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Symbol of the position to close"},
        },
        "required": ["symbol"],
    },
    permission="confirm",
    category="broker",
)
async def close_position(db: Session, user_id: int, symbol: str = "", **kwargs) -> dict:
    try:
        from app.services.broker.manager import broker_manager
        adapter = broker_manager.get_adapter()
        if not adapter:
            return {"error": "No broker connected."}

        result = await adapter.close_position(symbol=symbol)
        return {"message": f"Position on {symbol} closed.", "result": str(result)[:200]}
    except Exception as e:
        return {"error": f"Close failed: {str(e)[:200]}"}


@copilot_tool(
    name="create_agent",
    description="Create a new trading agent that will monitor the market using a specified strategy. Must specify strategy ID, symbol, and timeframe.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name for the agent"},
            "strategy_id": {"type": "integer", "description": "Strategy ID to use"},
            "symbol": {"type": "string", "description": "Trading symbol (e.g., XAUUSD)"},
            "timeframe": {"type": "string", "description": "Timeframe (e.g., M15, H1, H4)"},
            "mode": {"type": "string", "enum": ["paper", "confirmation", "auto"], "description": "Trading mode (default: paper)", "default": "paper"},
        },
        "required": ["name", "strategy_id", "symbol", "timeframe"],
    },
    permission="confirm",
    category="agents",
)
async def create_agent(
    db: Session, user_id: int,
    name: str = "", strategy_id: int = 0,
    symbol: str = "", timeframe: str = "H1",
    mode: str = "paper",
    **kwargs,
) -> dict:
    from app.models.agent import TradingAgent
    from app.services.broker.manager import broker_manager

    # Auto-detect broker from active connection
    broker_name = broker_manager.default_broker or ""

    agent = TradingAgent(
        name=name,
        strategy_id=strategy_id,
        symbol=symbol,
        timeframe=timeframe,
        broker_name=broker_name,
        mode=mode,
        status="stopped",
        created_by=user_id,
        risk_config={},
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return {
        "message": f"Agent '{name}' created (broker: {broker_name or 'auto'}).",
        "agent_id": agent.id,
        "broker_name": broker_name,
        "status": "stopped",
    }


# ══════════════════════════════════════════════════════════════════════
#  UTILITY TOOLS — Broker status, task queue, comparisons
# ══════════════════════════════════════════════════════════════════════


@copilot_tool(
    name="get_broker_status",
    description="Check which brokers are currently connected and which is the default.",
    parameters={"type": "object", "properties": {}, "required": []},
    permission="auto",
    category="broker",
)
async def get_broker_status(db: Session, user_id: int, **kwargs) -> dict:
    from app.services.broker.manager import broker_manager
    adapters_info = {}
    for name in broker_manager.active_brokers:
        adapter = broker_manager.get_adapter(name)
        connected = await adapter.is_connected() if adapter else False
        adapters_info[name] = {"connected": connected}
    return {
        "default_broker": broker_manager.default_broker,
        "active_brokers": adapters_info,
        "count": len(adapters_info),
    }


@copilot_tool(
    name="compare_backtests",
    description="Compare two or more backtest results side by side. Provide a list of backtest run IDs.",
    parameters={
        "type": "object",
        "properties": {
            "backtest_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "List of backtest run IDs to compare",
            },
        },
        "required": ["backtest_ids"],
    },
    permission="auto",
    category="backtests",
)
async def compare_backtests(db: Session, user_id: int, backtest_ids: list = None, **kwargs) -> dict:
    from app.models.backtest import BacktestRun
    if not backtest_ids or len(backtest_ids) < 2:
        return {"error": "Provide at least 2 backtest IDs to compare."}

    results = []
    for bid in backtest_ids[:5]:  # max 5
        run = db.query(BacktestRun).filter(
            BacktestRun.id == bid, BacktestRun.user_id == user_id
        ).first()
        if not run:
            results.append({"id": bid, "error": "Not found"})
            continue
        stats = run.results or {}
        results.append({
            "id": run.id,
            "strategy": run.strategy_name or f"Strategy #{run.strategy_id}",
            "symbol": stats.get("symbol", ""),
            "timeframe": stats.get("timeframe", ""),
            "net_profit": stats.get("net_profit", 0),
            "profit_factor": stats.get("profit_factor", 0),
            "win_rate": stats.get("win_rate", 0),
            "total_trades": stats.get("total_trades", 0),
            "max_drawdown_pct": stats.get("max_drawdown_pct", 0),
            "sharpe_ratio": stats.get("sharpe_ratio", 0),
        })
    return {"comparison": results, "count": len(results)}


@copilot_tool(
    name="check_task_status",
    description="Check the status of a background task (backtest, walk-forward, etc.) by its task ID.",
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "The task ID returned when the job was started"},
        },
        "required": ["task_id"],
    },
    permission="auto",
    category="general",
)
async def check_task_status_tool(db: Session, user_id: int, task_id: str = "", **kwargs) -> dict:
    from app.services.task_queue import get_task_status
    result = get_task_status(task_id)
    if not result:
        return {"error": f"Task '{task_id}' not found. It may have expired."}
    return result


@copilot_tool(
    name="list_tasks",
    description="List recent background tasks (backtests, walk-forwards) for the current user.",
    parameters={"type": "object", "properties": {}, "required": []},
    permission="auto",
    category="general",
)
async def list_tasks_tool(db: Session, user_id: int, **kwargs) -> dict:
    from app.services.task_queue import get_user_tasks
    tasks = get_user_tasks(user_id)
    return {"tasks": tasks, "count": len(tasks)}


# ══════════════════════════════════════════════════════════════════════
#  BLOCKED TOOLS — Registered for LLM awareness but never executed
# ══════════════════════════════════════════════════════════════════════


@copilot_tool(
    name="delete_strategy",
    description="Delete a strategy. This action is blocked for safety — the user must delete strategies manually.",
    parameters={
        "type": "object",
        "properties": {"strategy_id": {"type": "integer"}},
        "required": ["strategy_id"],
    },
    permission="blocked",
    category="strategies",
)
async def delete_strategy(db: Session, user_id: int, **kwargs) -> dict:
    return {"error": "Delete actions are blocked. Please delete strategies manually from the Strategies page."}


@copilot_tool(
    name="delete_data_source",
    description="Delete a data source. This action is blocked for safety — the user must delete data sources manually.",
    parameters={
        "type": "object",
        "properties": {"datasource_id": {"type": "integer"}},
        "required": ["datasource_id"],
    },
    permission="blocked",
    category="data",
)
async def delete_data_source(db: Session, user_id: int, **kwargs) -> dict:
    return {"error": "Delete actions are blocked. Please delete data sources manually from the Data page."}
