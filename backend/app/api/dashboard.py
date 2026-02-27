"""
Dashboard API — aggregated summary data for the main dashboard.
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.api.auth import get_current_user
from app.models.user import User
from app.models.strategy import Strategy
from app.models.backtest import Backtest
from app.models.trade import Trade
from app.models.agent import TradingAgent, AgentTrade
from app.models.datasource import DataSource
from app.services.broker.manager import broker_manager
from app.core.websocket import manager as ws_manager

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return all dashboard data in a single response."""

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # ── Broker / account ──────────────────────────────────
    broker_connected = False
    broker_name = None
    account = {
        "balance": 0.0,
        "equity": 0.0,
        "unrealized_pnl": 0.0,
        "currency": "USD",
        "open_positions": 0,
        "open_orders": 0,
        "margin_used": 0.0,
    }
    positions = []

    default_adapter = broker_manager.get_adapter()
    if default_adapter:
        broker_connected = True
        broker_name = broker_manager.default_broker
        try:
            info = default_adapter.get_account_info()
            if info:
                account = {
                    "balance": info.get("balance", 0),
                    "equity": info.get("equity", 0),
                    "unrealized_pnl": info.get("unrealized_pnl", 0),
                    "currency": info.get("currency", "USD"),
                    "open_positions": info.get("open_positions", 0),
                    "open_orders": info.get("open_orders", 0),
                    "margin_used": info.get("margin_used", 0),
                }
        except Exception:
            pass

        try:
            raw_positions = default_adapter.get_positions()
            positions = [
                {
                    "position_id": str(p.get("position_id", "")),
                    "symbol": p.get("symbol", ""),
                    "side": p.get("side", ""),
                    "size": p.get("size", 0),
                    "entry_price": p.get("entry_price", 0),
                    "current_price": p.get("current_price", 0),
                    "unrealized_pnl": p.get("unrealized_pnl", 0),
                }
                for p in (raw_positions or [])
            ]
        except Exception:
            pass

    # ── Strategies ────────────────────────────────────────
    total_strategies = db.query(func.count(Strategy.id)).scalar() or 0
    system_strategies = (
        db.query(func.count(Strategy.id))
        .filter(Strategy.is_system == True)  # noqa: E712
        .scalar() or 0
    )
    user_strategies = total_strategies - system_strategies

    # ── Agents ────────────────────────────────────────────
    agents_query = db.query(TradingAgent).filter(TradingAgent.created_by == user.id)
    agents = agents_query.all()
    running_agents = sum(1 for a in agents if a.status == "running")
    paused_agents = sum(1 for a in agents if a.status == "paused")
    paper_agents = sum(1 for a in agents if a.mode == "paper")

    agent_list = [
        {
            "id": a.id,
            "name": a.name,
            "symbol": a.symbol,
            "timeframe": a.timeframe,
            "mode": a.mode,
            "status": a.status,
            "strategy_id": a.strategy_id,
        }
        for a in agents
    ]

    # ── Today's trades (agent trades + broker trades) ─────
    today_agent_trades = (
        db.query(AgentTrade)
        .join(TradingAgent)
        .filter(
            TradingAgent.created_by == user.id,
            AgentTrade.created_at >= today_start,
            AgentTrade.status.in_(["executed", "paper", "closed"]),
        )
        .all()
    )

    today_pnl = sum(t.pnl or 0 for t in today_agent_trades)
    today_wins = sum(1 for t in today_agent_trades if (t.pnl or 0) > 0)
    today_losses = sum(1 for t in today_agent_trades if (t.pnl or 0) < 0)
    today_total = len(today_agent_trades)
    today_win_rate = (today_wins / today_total * 100) if today_total > 0 else 0

    # ── Recent trades (last 10) ───────────────────────────
    recent_agent_trades = (
        db.query(AgentTrade)
        .join(TradingAgent)
        .filter(
            TradingAgent.created_by == user.id,
            AgentTrade.status.in_(["executed", "paper", "closed"]),
        )
        .order_by(AgentTrade.created_at.desc())
        .limit(10)
        .all()
    )

    recent_broker_trades = (
        db.query(Trade)
        .order_by(Trade.created_at.desc())
        .limit(10)
        .all()
    )

    recent_trades = []
    for t in recent_agent_trades:
        recent_trades.append({
            "id": t.id,
            "source": "agent",
            "symbol": t.symbol,
            "direction": t.direction,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "lot_size": t.lot_size,
            "pnl": t.pnl or 0,
            "status": t.status,
            "time": t.created_at.isoformat() if t.created_at else "",
        })
    for t in recent_broker_trades:
        recent_trades.append({
            "id": t.id,
            "source": "broker",
            "symbol": t.symbol,
            "direction": t.direction,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "lot_size": t.lot_size,
            "pnl": t.pnl or 0,
            "status": t.status,
            "time": t.created_at.isoformat() if t.created_at else "",
        })

    # Sort combined by time desc, take 10
    recent_trades.sort(key=lambda x: x["time"], reverse=True)
    recent_trades = recent_trades[:10]

    # ── Backtests ─────────────────────────────────────────
    total_backtests = (
        db.query(func.count(Backtest.id))
        .filter(Backtest.creator_id == user.id)
        .scalar() or 0
    )
    last_backtest = (
        db.query(Backtest)
        .filter(Backtest.creator_id == user.id)
        .order_by(Backtest.created_at.desc())
        .first()
    )

    # ── Data sources ──────────────────────────────────────
    total_datasources = db.query(func.count(DataSource.id)).scalar() or 0

    # ── Pending confirmations ─────────────────────────────
    pending_confirmations = (
        db.query(func.count(AgentTrade.id))
        .join(TradingAgent)
        .filter(
            TradingAgent.created_by == user.id,
            AgentTrade.status == "pending_confirmation",
        )
        .scalar() or 0
    )

    # ── WebSocket clients ─────────────────────────────────
    ws_clients = sum(len(v) for v in ws_manager._connections.values())

    return {
        "account": {
            **account,
            "broker_connected": broker_connected,
            "broker_name": broker_name,
        },
        "positions": positions,
        "strategies": {
            "total": total_strategies,
            "system": system_strategies,
            "user": user_strategies,
        },
        "agents": {
            "total": len(agents),
            "running": running_agents,
            "paused": paused_agents,
            "paper": paper_agents,
            "items": agent_list,
        },
        "today": {
            "pnl": round(today_pnl, 2),
            "trades": today_total,
            "wins": today_wins,
            "losses": today_losses,
            "win_rate": round(today_win_rate, 1),
        },
        "recent_trades": recent_trades,
        "backtests": {
            "total": total_backtests,
            "last_run": last_backtest.created_at.isoformat() if last_backtest and last_backtest.created_at else None,
            "last_status": last_backtest.status if last_backtest else None,
        },
        "data_sources": total_datasources,
        "pending_confirmations": pending_confirmations,
        "ws_clients": ws_clients,
    }
