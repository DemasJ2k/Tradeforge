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
from app.models.agent import TradingAgent, AgentTrade, AgentLog
from app.models.datasource import DataSource
from app.models.prop_firm import PropFirmAccount, PropFirmTrade
from app.services.broker.manager import broker_manager
from app.core.websocket import manager as ws_manager

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
async def dashboard_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return all dashboard data in a single response."""

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # ── Broker / account — aggregate ALL connected brokers ──
    from app.services.fx_rates import convert_to_usd

    def _attr(obj, key, default=0):
        """Safely extract attribute from object or dict."""
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    broker_accounts = []
    positions = []
    combined_balance_usd = 0.0
    combined_equity_usd = 0.0
    combined_unrealized_pnl_usd = 0.0
    combined_open_positions = 0
    combined_open_orders = 0
    combined_margin_used = 0.0

    user_adapters = broker_manager.get_user_adapters(user.id)
    for bname, adapter in user_adapters.items():
        if not adapter:
            continue

        broker_info = {
            "broker": bname,
            "connected": True,
            "is_default": bname == broker_manager.get_default_broker_for_user(user.id),
            "currency": "USD",
            "balance": 0.0,
            "equity": 0.0,
            "unrealized_pnl": 0.0,
            "balance_usd": 0.0,
            "equity_usd": 0.0,
            "open_positions": 0,
            "open_orders": 0,
            "margin_used": 0.0,
        }

        try:
            info = await adapter.get_account_info()
            if info:
                currency = _attr(info, "currency", "USD")
                balance = _attr(info, "balance", 0)
                equity = _attr(info, "equity", 0)
                unrealized = _attr(info, "unrealized_pnl", 0)
                positions_count = _attr(info, "open_positions", 0)
                orders_count = _attr(info, "open_orders", 0)
                margin = _attr(info, "margin_used", 0)

                balance_usd = await convert_to_usd(balance, currency)
                equity_usd = await convert_to_usd(equity, currency)
                unrealized_usd = await convert_to_usd(unrealized, currency)

                broker_info.update({
                    "currency": currency,
                    "balance": balance,
                    "equity": equity,
                    "unrealized_pnl": unrealized,
                    "balance_usd": balance_usd,
                    "equity_usd": equity_usd,
                    "open_positions": positions_count,
                    "open_orders": orders_count,
                    "margin_used": margin,
                })

                combined_balance_usd += balance_usd
                combined_equity_usd += equity_usd
                combined_unrealized_pnl_usd += unrealized_usd
                combined_open_positions += positions_count
                combined_open_orders += orders_count
                combined_margin_used += await convert_to_usd(margin, currency)
        except Exception:
            pass

        # Positions from this broker
        try:
            raw_positions = await adapter.get_positions()
            for p in (raw_positions or []):
                positions.append({
                    "position_id": str(_attr(p, "position_id", "")),
                    "symbol": _attr(p, "symbol", ""),
                    "side": str(_attr(p, "side", "")),
                    "size": _attr(p, "size", 0),
                    "entry_price": _attr(p, "entry_price", 0),
                    "current_price": _attr(p, "current_price", 0),
                    "unrealized_pnl": _attr(p, "unrealized_pnl", 0),
                    "broker": bname,
                })
        except Exception:
            pass

        broker_accounts.append(broker_info)

    broker_connected = len(broker_accounts) > 0
    broker_name = broker_manager.get_default_broker_for_user(user.id)

    account = {
        "balance": round(combined_balance_usd, 2),
        "equity": round(combined_equity_usd, 2),
        "unrealized_pnl": round(combined_unrealized_pnl_usd, 2),
        "currency": "USD",
        "open_positions": combined_open_positions,
        "open_orders": combined_open_orders,
        "margin_used": round(combined_margin_used, 2),
    }

    # ── Strategies ────────────────────────────────────────
    from sqlalchemy import or_
    total_strategies = (
        db.query(func.count(Strategy.id))
        .filter(or_(Strategy.creator_id == user.id, Strategy.is_system == True))  # noqa: E712
        .scalar() or 0
    )
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

    # ── Today's trades — PRIMARY: broker closed trades, FALLBACK: agent DB ──
    broker_closed_trades = []
    for bname, adapter in broker_manager.get_user_adapters(user.id).items():
        if not adapter:
            continue
        try:
            trades = await adapter.get_closed_trades(since=today_start, limit=200)
            if trades:
                broker_closed_trades.extend(trades)
        except Exception:
            pass

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

    # Use broker trades when available (real data), fall back to agent DB
    if broker_closed_trades:
        today_pnl = sum(t.pnl for t in broker_closed_trades)
        today_wins = sum(1 for t in broker_closed_trades if t.pnl > 0)
        today_losses = sum(1 for t in broker_closed_trades if t.pnl < 0)
        today_total = len(broker_closed_trades)
    else:
        today_pnl = sum(t.pnl or 0 for t in today_agent_trades)
        today_wins = sum(1 for t in today_agent_trades if (t.pnl or 0) > 0)
        today_losses = sum(1 for t in today_agent_trades if (t.pnl or 0) < 0)
        today_total = len(today_agent_trades)
    today_win_rate = (today_wins / today_total * 100) if today_total > 0 else 0

    # ── Recent trades (last 10) — broker trades + agent trades ────
    recent_trades = []

    # Add broker closed trades (real broker history)
    for bt in broker_closed_trades[:10]:
        recent_trades.append({
            "id": bt.trade_id,
            "source": "broker",
            "symbol": bt.symbol,
            "direction": bt.side,
            "entry_price": bt.entry_price if bt.entry_price else None,
            "exit_price": bt.exit_price,
            "lot_size": bt.size,
            "pnl": bt.pnl,
            "status": "closed",
            "time": bt.close_time.isoformat() if bt.close_time else "",
        })

    # Add agent trades from DB
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

    # Deduplicate by trade_id, sort by time desc, take 10
    seen_ids = set()
    unique_trades = []
    for tr in recent_trades:
        tid = str(tr["id"])
        if tid not in seen_ids:
            seen_ids.add(tid)
            unique_trades.append(tr)
    unique_trades.sort(key=lambda x: x["time"], reverse=True)
    recent_trades = unique_trades[:10]

    # ── Equity curve (last 30 days, daily aggregated) ─────
    thirty_days_ago = now - timedelta(days=30)
    equity_trades = (
        db.query(AgentTrade.created_at, AgentTrade.pnl)
        .join(TradingAgent)
        .filter(
            TradingAgent.created_by == user.id,
            AgentTrade.status.in_(["executed", "paper", "closed"]),
            AgentTrade.created_at >= thirty_days_ago,
            AgentTrade.pnl.isnot(None),
        )
        .order_by(AgentTrade.created_at)
        .all()
    )
    # Group by date, cumulate
    daily_pnl: dict[str, float] = {}
    for t_time, t_pnl in equity_trades:
        if t_time:
            day = t_time.strftime("%Y-%m-%d")
            daily_pnl[day] = daily_pnl.get(day, 0) + (t_pnl or 0)

    equity_curve = []
    cumulative = 0.0
    for day in sorted(daily_pnl.keys()):
        cumulative += daily_pnl[day]
        equity_curve.append({"date": day, "pnl": round(cumulative, 2)})

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

    # ── Prop firm accounts ─────────────────────────────────
    prop_firm_accounts = (
        db.query(PropFirmAccount)
        .filter(PropFirmAccount.user_id == user.id, PropFirmAccount.status == "active")
        .all()
    )
    prop_firm_cards = []
    for pf in prop_firm_accounts:
        size = pf.account_size or 0
        balance = pf.current_balance or size
        peak = pf.peak_balance or size

        # Reset daily P&L if stale
        today = now.strftime("%Y-%m-%d")
        today_pnl_pf = pf.today_pnl or 0.0
        if pf.today_pnl_date != today:
            today_pnl_pf = 0.0

        daily_limit = size * (pf.max_daily_loss_pct / 100) if pf.max_daily_loss_pct else 0
        dd_limit = size * (pf.max_total_loss_pct / 100) if pf.max_total_loss_pct else 0
        daily_used = abs(min(today_pnl_pf, 0))
        current_dd = max(peak - balance, 0)

        profit_target = size * (pf.profit_target_pct / 100) if pf.profit_target_pct else 0
        profit_made = max(balance - size, 0)

        open_trades = db.query(func.count(PropFirmTrade.id)).filter(
            PropFirmTrade.account_id == pf.id, PropFirmTrade.status == "open"
        ).scalar() or 0

        prop_firm_cards.append({
            "id": pf.id,
            "name": pf.account_name,
            "firm": pf.firm_name,
            "phase": pf.phase,
            "account_size": size,
            "balance": round(balance, 2),
            "daily_loss_used": round(daily_used, 2),
            "daily_loss_limit": round(daily_limit, 2),
            "daily_loss_pct": round((daily_used / daily_limit * 100) if daily_limit else 0, 1),
            "drawdown_used": round(current_dd, 2),
            "drawdown_limit": round(dd_limit, 2),
            "drawdown_pct": round((current_dd / dd_limit * 100) if dd_limit else 0, 1),
            "profit_target": round(profit_target, 2),
            "profit_made": round(profit_made, 2),
            "profit_pct": round((profit_made / profit_target * 100) if profit_target else 0, 1),
            "open_trades": open_trades,
            "days_left": (pf.max_trading_days - (pf.trading_days or 0)) if pf.max_trading_days else None,
        })

    # ── WebSocket clients ─────────────────────────────────
    ws_clients = sum(len(v) for v in ws_manager._connections.values())

    return {
        "account": {
            **account,
            "broker_connected": broker_connected,
            "broker_name": broker_name,
        },
        "broker_accounts": broker_accounts,
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
        "equity_curve": equity_curve,
        "backtests": {
            "total": total_backtests,
            "last_run": last_backtest.created_at.isoformat() if last_backtest and last_backtest.created_at else None,
            "last_status": last_backtest.status if last_backtest else None,
        },
        "data_sources": total_datasources,
        "pending_confirmations": pending_confirmations,
        "ws_clients": ws_clients,
        "prop_firm_accounts": prop_firm_cards,
    }


@router.get("/activity")
def get_recent_activity(
    limit: int = 15,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return recent agent activity logs across all agents for the activity feed."""
    agent_ids = [
        a.id for a in
        db.query(TradingAgent.id).filter(TradingAgent.created_by == user.id).all()
    ]
    if not agent_ids:
        return {"items": []}

    logs = (
        db.query(AgentLog)
        .filter(AgentLog.agent_id.in_(agent_ids))
        .order_by(AgentLog.created_at.desc())
        .limit(min(limit, 50))
        .all()
    )

    # Build agent name map
    agents = db.query(TradingAgent.id, TradingAgent.name).filter(
        TradingAgent.id.in_(agent_ids)
    ).all()
    name_map = {a.id: a.name for a in agents}

    return {
        "items": [
            {
                "id": log.id,
                "agent_id": log.agent_id,
                "agent_name": name_map.get(log.agent_id, "Unknown"),
                "level": log.level,
                "message": log.message,
                "created_at": log.created_at.isoformat() if log.created_at else "",
            }
            for log in logs
        ]
    }
