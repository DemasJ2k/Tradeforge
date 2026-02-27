"""
Algo Trading Agent API endpoints.

CRUD for agents, start/stop/pause controls, trade confirmation, logs.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
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
        broker_name=a.broker_name or "mt5",
        symbol=a.symbol,
        timeframe=a.timeframe,
        mode=a.mode,
        status=a.status,
        risk_config=a.risk_config or {},
        performance_stats=a.performance_stats or {},
        ml_model_id=a.ml_model_id,
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
        .order_by(TradingAgent.created_at.desc())
        .all()
    )
    return {"items": [_agent_to_response(a) for a in agents], "total": len(agents)}


@router.post("", status_code=201)
def create_agent(
    payload: AgentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = TradingAgent(
        name=payload.name,
        strategy_id=payload.strategy_id,
        symbol=payload.symbol,
        timeframe=payload.timeframe,
        broker_name=payload.broker_name,
        mode=payload.mode,
        risk_config=payload.risk_config,
        ml_model_id=payload.ml_model_id,
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
    agent = db.query(TradingAgent).filter(
        TradingAgent.id == agent_id, TradingAgent.created_by == user.id
    ).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    # Stop if running
    if algo_engine.is_running(agent_id):
        await algo_engine.stop_agent(agent_id)

    db.delete(agent)
    db.commit()
    return {"detail": "Agent deleted"}


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
        "items": [
            AgentTradeResponse(
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
                opened_at=t.opened_at.isoformat() if t.opened_at else "",
                closed_at=t.closed_at.isoformat() if t.closed_at else None,
                created_at=t.created_at.isoformat() if t.created_at else "",
            )
            for t in trades
        ],
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

    # TODO: Execute via broker adapter when auto mode is implemented
    trade.status = "confirmed"
    db.commit()

    return {"detail": "Trade confirmed", "trade_id": trade_id, "status": "confirmed"}


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
