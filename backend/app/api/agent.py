"""
Algo Trading Agent API endpoints.

CRUD for agents, start/stop/pause controls, trade confirmation, logs.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user

logger = logging.getLogger(__name__)
from app.models.user import User
from app.models.agent import TradingAgent, AgentLog, AgentTrade
from app.schemas.agent import (
    AgentCreate,
    AgentUpdate,
    AgentResponse,
    AgentLogResponse,
    AgentTradeResponse,
)
from app.services.agent.engine import algo_engine

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _agent_to_response(a: TradingAgent) -> AgentResponse:
    return AgentResponse(
        id=a.id,
        name=a.name,
        strategy_id=a.strategy_id,
        broker_name=a.broker_name or "",
        symbol=a.symbol,
        timeframe=a.timeframe,
        mode=a.mode,
        status=a.status,
        risk_config=a.risk_config or {},
        performance_stats=a.performance_stats or {},
        ml_model_id=a.ml_model_id,
        prop_firm_account_id=a.prop_firm_account_id,
        created_by=a.created_by,
        created_at=a.created_at.isoformat() if a.created_at else "",
        updated_at=a.updated_at.isoformat() if a.updated_at else "",
    )


# ── CRUD ─────────────────────────────────────────────

@router.get("")
def list_agents(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agents = (
        db.query(TradingAgent)
        .filter(TradingAgent.created_by == user.id)
        .filter(TradingAgent.deleted_at.is_(None))
        .order_by(TradingAgent.created_at.desc())
        .all()
    )
    return {"items": [_agent_to_response(a) for a in agents], "total": len(agents)}


def _trade_to_response(t: AgentTrade) -> dict:
    return AgentTradeResponse(
        id=t.id,
        agent_id=t.agent_id,
        symbol=t.symbol,
        direction=t.direction,
        entry_price=t.entry_price,
        exit_price=t.exit_price,
        lot_size=t.lot_size or 0.01,
        stop_loss=t.stop_loss,
        take_profit_1=t.take_profit_1,
        take_profit_2=t.take_profit_2,
        pnl=t.pnl or 0.0,
        pnl_pct=t.pnl_pct or 0.0,
        status=t.status,
        signal_type=t.signal_type,
        signal_reason=t.signal_reason,
        signal_confidence=t.signal_confidence or 0.0,
        broker_ticket=t.broker_ticket,
        filled_price=getattr(t, "filled_price", None),
        filled_time=t.filled_time.isoformat() if getattr(t, "filled_time", None) else None,
        broker_trade_id=getattr(t, "broker_trade_id", None),
        broker_pnl=getattr(t, "broker_pnl", None),
        broker_name=getattr(t, "broker_name", None),
        exit_reason=getattr(t, "exit_reason", None),
        opened_at=t.opened_at.isoformat() if t.opened_at else "",
        closed_at=t.closed_at.isoformat() if t.closed_at else None,
        created_at=t.created_at.isoformat() if t.created_at else "",
    ).model_dump()


# ── Cross-agent queries (MUST be before /{agent_id} routes) ──


@router.get("/all-trades")
def get_all_agent_trades(
    status: str = Query("paper,executed"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get trades from ALL user's agents, filtered by status."""
    from sqlalchemy import literal_column

    statuses = [s.strip() for s in status.split(",")]
    rows = (
        db.query(AgentTrade, TradingAgent.name.label("agent_name"))
        .join(TradingAgent, AgentTrade.agent_id == TradingAgent.id)
        .filter(
            TradingAgent.created_by == user.id,
            TradingAgent.deleted_at.is_(None),
            AgentTrade.status.in_(statuses),
        )
        .order_by(AgentTrade.created_at.desc())
        .limit(limit)
        .all()
    )
    items = []
    for trade, agent_name in rows:
        d = _trade_to_response(trade)
        d["agent_name"] = agent_name
        items.append(d)
    return {"items": items, "total": len(items)}


@router.get("/pnl-summary")
def get_pnl_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get P&L summary for each agent."""
    from sqlalchemy import func, case

    results = (
        db.query(
            TradingAgent.id,
            TradingAgent.name,
            TradingAgent.symbol,
            TradingAgent.timeframe,
            TradingAgent.status,
            TradingAgent.mode,
            func.coalesce(func.sum(AgentTrade.pnl), 0).label("total_pnl"),
            func.count(AgentTrade.id).label("total_trades"),
            func.sum(case((AgentTrade.pnl > 0, 1), else_=0)).label("wins"),
        )
        .outerjoin(
            AgentTrade,
            (AgentTrade.agent_id == TradingAgent.id)
            & AgentTrade.status.in_(["paper", "executed", "closed"]),
        )
        .filter(
            TradingAgent.created_by == user.id,
            TradingAgent.deleted_at.is_(None),
        )
        .group_by(
            TradingAgent.id,
            TradingAgent.name,
            TradingAgent.symbol,
            TradingAgent.timeframe,
            TradingAgent.status,
            TradingAgent.mode,
        )
        .all()
    )

    items = []
    for r in results:
        total = r.total_trades or 0
        wins = r.wins or 0
        items.append({
            "agent_id": r.id,
            "agent_name": r.name,
            "symbol": r.symbol,
            "timeframe": r.timeframe,
            "status": r.status,
            "mode": r.mode,
            "total_pnl": round(float(r.total_pnl), 2),
            "total_trades": total,
            "wins": wins,
            "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
        })
    return {"items": items}


@router.post("/recalculate-pnl")
def recalculate_pnl(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Recalculate P&L for all existing trades using correct instrument specs."""
    if user.username not in ("FlowrexAdmin", "admin"):
        raise HTTPException(403, "Admin only")

    from app.services.agent.instrument_specs import calc_pnl_dollars

    trades = (
        db.query(AgentTrade)
        .join(TradingAgent, AgentTrade.agent_id == TradingAgent.id)
        .filter(
            TradingAgent.created_by == user.id,
            AgentTrade.entry_price.isnot(None),
            AgentTrade.exit_price.isnot(None),
        )
        .all()
    )

    updated = 0
    samples = []
    for t in trades:
        broker = getattr(t, "broker_name", None) or "oanda"
        new_pnl = calc_pnl_dollars(
            symbol=t.symbol,
            direction=t.direction,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            lot_size=t.lot_size or 0.01,
            broker_name=broker,
        )
        if abs((t.pnl or 0) - new_pnl) > 0.001:
            old_pnl = t.pnl
            t.pnl = round(new_pnl, 4)
            updated += 1
            if len(samples) < 5:
                samples.append({
                    "trade_id": t.id, "symbol": t.symbol,
                    "old_pnl": old_pnl, "new_pnl": round(new_pnl, 4),
                })

    db.commit()
    return {"updated": updated, "total": len(trades), "samples": samples}


@router.post("", status_code=201)
def create_agent(
    payload: AgentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Auto-detect broker from active connection when not explicitly set
    broker_name = payload.broker_name
    if not broker_name:
        from app.services.broker.manager import broker_manager
        broker_name = broker_manager.default_broker or ""

    agent = TradingAgent(
        name=payload.name,
        strategy_id=payload.strategy_id,
        symbol=payload.symbol,
        timeframe=payload.timeframe,
        broker_name=broker_name,
        mode=payload.mode,
        risk_config=payload.risk_config,
        ml_model_id=payload.ml_model_id,
        prop_firm_account_id=payload.prop_firm_account_id,
        created_by=user.id,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return _agent_to_response(agent)


@router.get("/{agent_id}")
def get_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = db.query(TradingAgent).filter(
        TradingAgent.id == agent_id, TradingAgent.created_by == user.id
    ).first()
    if not agent:
        raise HTTPException(404, "Agent not found")
    return _agent_to_response(agent)


@router.put("/{agent_id}")
def update_agent(
    agent_id: int,
    payload: AgentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = db.query(TradingAgent).filter(
        TradingAgent.id == agent_id, TradingAgent.created_by == user.id
    ).first()
    if not agent:
        raise HTTPException(404, "Agent not found")
    if agent.status == "running":
        raise HTTPException(400, "Cannot update a running agent. Stop it first.")

    for key, val in payload.model_dump(exclude_unset=True).items():
        setattr(agent, key, val)
    db.commit()
    db.refresh(agent)
    return _agent_to_response(agent)


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from datetime import datetime, timezone

    agent = db.query(TradingAgent).filter(
        TradingAgent.id == agent_id, TradingAgent.created_by == user.id
    ).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    # Stop if running
    if algo_engine.is_running(agent_id):
        await algo_engine.stop_agent(agent_id)

    # Soft-delete: mark as deleted, don't cascade-delete logs/trades
    agent.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"detail": "Agent moved to recycle bin"}


# ── Controls ─────────────────────────────────────────

@router.post("/{agent_id}/start")
async def start_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = db.query(TradingAgent).filter(
        TradingAgent.id == agent_id, TradingAgent.created_by == user.id
    ).first()
    if not agent:
        raise HTTPException(404, "Agent not found")
    if agent.status == "running":
        raise HTTPException(400, "Agent is already running")

    await algo_engine.start_agent(agent_id)
    db.refresh(agent)

    # Fire webhooks
    try:
        from app.services.webhook import fire_webhooks
        await fire_webhooks(db, user.id, "agent_started", {
            "agent_id": agent_id,
            "name": agent.name,
            "symbol": agent.symbol,
            "strategy_id": agent.strategy_id,
        })
    except Exception as e:
        logger.warning("Webhook fire failed (agent_started): %s", e)

    return _agent_to_response(agent)


@router.post("/{agent_id}/stop")
async def stop_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = db.query(TradingAgent).filter(
        TradingAgent.id == agent_id, TradingAgent.created_by == user.id
    ).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    await algo_engine.stop_agent(agent_id)
    db.refresh(agent)

    # Fire webhooks
    try:
        from app.services.webhook import fire_webhooks
        await fire_webhooks(db, user.id, "agent_stopped", {
            "agent_id": agent_id,
            "name": agent.name,
            "symbol": agent.symbol,
        })
    except Exception as e:
        logger.warning("Webhook fire failed (agent_stopped): %s", e)

    return _agent_to_response(agent)


@router.post("/{agent_id}/pause")
async def pause_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = db.query(TradingAgent).filter(
        TradingAgent.id == agent_id, TradingAgent.created_by == user.id
    ).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    await algo_engine.pause_agent(agent_id)
    db.refresh(agent)
    return _agent_to_response(agent)


# ── Logs ─────────────────────────────────────────────

@router.get("/{agent_id}/logs")
def get_agent_logs(
    agent_id: int,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    level: str = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = db.query(TradingAgent).filter(
        TradingAgent.id == agent_id, TradingAgent.created_by == user.id
    ).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    q = db.query(AgentLog).filter(AgentLog.agent_id == agent_id)
    if level:
        q = q.filter(AgentLog.level == level)
    total = q.count()
    logs = q.order_by(AgentLog.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "items": [
            AgentLogResponse(
                id=log.id,
                agent_id=log.agent_id,
                level=log.level,
                message=log.message,
                data=log.data or {},
                created_at=log.created_at.isoformat() if log.created_at else "",
            )
            for log in logs
        ],
        "total": total,
    }


# ── Trades ───────────────────────────────────────────

@router.get("/{agent_id}/trades")
def get_agent_trades(
    agent_id: int,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = db.query(TradingAgent).filter(
        TradingAgent.id == agent_id, TradingAgent.created_by == user.id
    ).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    q = db.query(AgentTrade).filter(AgentTrade.agent_id == agent_id)
    if status:
        q = q.filter(AgentTrade.status == status)
    total = q.count()
    trades = q.order_by(AgentTrade.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "items": [_trade_to_response(t) for t in trades],
        "total": total,
    }


@router.post("/{agent_id}/trades/{trade_id}/confirm")
async def confirm_trade(
    agent_id: int,
    trade_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Approve a pending trade for execution."""
    agent = db.query(TradingAgent).filter(
        TradingAgent.id == agent_id, TradingAgent.created_by == user.id
    ).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    trade = db.query(AgentTrade).filter(
        AgentTrade.id == trade_id, AgentTrade.agent_id == agent_id
    ).first()
    if not trade:
        raise HTTPException(404, "Trade not found")
    if trade.status != "pending_confirmation":
        raise HTTPException(400, f"Trade is not pending (status={trade.status})")

    # Execute via broker adapter if agent has a connected broker
    executed = False
    broker_ticket = None
    try:
        from app.services.broker.manager import broker_manager
        from app.services.broker.base import OrderRequest, OrderSide, OrderType
        adapter = broker_manager.get_adapter(agent.broker_name)
        if adapter and await adapter.is_connected():
            side = OrderSide.BUY if trade.direction == "long" else OrderSide.SELL
            order_req = OrderRequest(
                symbol=trade.symbol,
                side=side,
                size=trade.lot_size,
                order_type=OrderType.MARKET,
                stop_loss=trade.stop_loss,
                take_profit=trade.take_profit_1,
                comment=f"FlowrexAlgo agent:{agent_id}",
            )
            order = await adapter.place_order(order_req)
            broker_ticket = order.order_id
            trade.broker_ticket = str(broker_ticket) if broker_ticket else None
            trade.broker_name = agent.broker_name
            if order.filled_price:
                trade.filled_price = order.filled_price
            if order.filled_time:
                trade.filled_time = order.filled_time
            executed = True
    except Exception as e:
        logger.warning("Broker execution failed for trade %d: %s", trade_id, e)

    trade.status = "executed" if executed else "confirmed"
    db.commit()

    return {
        "detail": "Trade executed" if executed else "Trade confirmed",
        "trade_id": trade_id,
        "status": trade.status,
        "broker_ticket": broker_ticket,
    }


@router.post("/{agent_id}/trades/{trade_id}/reject")
async def reject_trade(
    agent_id: int,
    trade_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Reject a pending trade."""
    agent = db.query(TradingAgent).filter(
        TradingAgent.id == agent_id, TradingAgent.created_by == user.id
    ).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    trade = db.query(AgentTrade).filter(
        AgentTrade.id == trade_id, AgentTrade.agent_id == agent_id
    ).first()
    if not trade:
        raise HTTPException(404, "Trade not found")
    if trade.status != "pending_confirmation":
        raise HTTPException(400, f"Trade is not pending (status={trade.status})")

    trade.status = "rejected"
    db.commit()

    return {"detail": "Trade rejected", "trade_id": trade_id, "status": "rejected"}


# ── Performance ──────────────────────────────────────

@router.get("/{agent_id}/performance")
def get_agent_performance(
    agent_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = db.query(TradingAgent).filter(
        TradingAgent.id == agent_id, TradingAgent.created_by == user.id
    ).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    trades = db.query(AgentTrade).filter(
        AgentTrade.agent_id == agent_id,
        AgentTrade.status.in_(["paper", "executed", "closed"]),
    ).all()

    total = len(trades)
    wins = sum(1 for t in trades if (t.pnl or 0) > 0)
    losses = sum(1 for t in trades if (t.pnl or 0) < 0)
    total_pnl = sum(t.pnl or 0 for t in trades)

    return {
        "agent_id": agent_id,
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": (wins / total * 100) if total > 0 else 0,
        "total_pnl": round(total_pnl, 2),
        "equity_curve": [
            {"time": t.opened_at.isoformat() if t.opened_at else "", "pnl": t.pnl or 0}
            for t in sorted(trades, key=lambda x: x.opened_at or x.created_at)
        ],
    }
