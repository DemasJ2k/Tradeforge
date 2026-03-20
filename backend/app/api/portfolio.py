"""
Portfolio Manager API endpoints.

Portfolio-level risk management, drawdown monitoring, correlation tracking,
and multi-agent coordination.
"""

import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User
from app.models.portfolio import PortfolioManager, PortfolioSnapshot
from app.models.agent import TradingAgent
from app.services.agent.portfolio_manager import (
    get_portfolio_manager,
    create_portfolio_manager,
    remove_portfolio_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


# ── Schemas ──────────────────────────────────────────────────────────

class PortfolioCreate(BaseModel):
    name: str = "My Portfolio"
    mode: str = "balanced"
    max_daily_loss_pct: float = 5.0
    max_total_drawdown_pct: float = 10.0
    max_portfolio_risk_pct: float = 2.0
    correlation_threshold: float = 0.85
    max_concurrent_positions: int = 6


class PortfolioUpdate(BaseModel):
    name: Optional[str] = None
    mode: Optional[str] = None
    max_daily_loss_pct: Optional[float] = None
    max_total_drawdown_pct: Optional[float] = None
    max_portfolio_risk_pct: Optional[float] = None
    correlation_threshold: Optional[float] = None
    max_concurrent_positions: Optional[int] = None


class RebalanceRequest(BaseModel):
    capital_allocation: dict  # { agent_id: fraction }


# ── Endpoints ────────────────────────────────────────────────────────

@router.post("/create")
def create_portfolio(
    req: PortfolioCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a portfolio manager for the current user."""
    # Check if user already has a portfolio
    existing = db.query(PortfolioManager).filter(
        PortfolioManager.user_id == user.id
    ).first()
    if existing:
        raise HTTPException(400, "User already has a portfolio manager")

    pm_db = PortfolioManager(
        user_id=user.id,
        name=req.name,
        mode=req.mode,
        max_daily_loss_pct=req.max_daily_loss_pct,
        max_total_drawdown_pct=req.max_total_drawdown_pct,
        max_portfolio_risk_pct=req.max_portfolio_risk_pct,
        correlation_threshold=req.correlation_threshold,
        max_concurrent_positions=req.max_concurrent_positions,
    )
    db.add(pm_db)
    db.commit()
    db.refresh(pm_db)

    # Create in-memory PM service
    pm = create_portfolio_manager(
        portfolio_id=pm_db.id,
        user_id=user.id,
        max_daily_loss_pct=req.max_daily_loss_pct,
        max_total_drawdown_pct=req.max_total_drawdown_pct,
        max_portfolio_risk_pct=req.max_portfolio_risk_pct,
        correlation_threshold=req.correlation_threshold,
        max_concurrent_positions=req.max_concurrent_positions,
        mode=req.mode,
    )

    return {"id": pm_db.id, "status": "created", "message": "Portfolio manager created"}


@router.get("/summary")
def get_portfolio_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get portfolio summary including P&L, drawdown, agent states."""
    pm_db = db.query(PortfolioManager).filter(
        PortfolioManager.user_id == user.id
    ).first()

    if not pm_db:
        # Auto-create a default portfolio for the user
        pm_db = PortfolioManager(user_id=user.id, name="Default Portfolio")
        db.add(pm_db)
        db.commit()
        db.refresh(pm_db)

    # Get in-memory PM or create one
    pm = get_portfolio_manager(user.id)
    if pm:
        summary = pm.get_summary()
    else:
        summary = {
            "portfolio_id": pm_db.id,
            "mode": pm_db.mode,
            "status": pm_db.status,
            "current_equity": pm_db.current_equity,
            "peak_equity": pm_db.peak_equity,
            "daily_pnl": pm_db.daily_pnl,
            "total_pnl": pm_db.total_pnl,
            "drawdown_pct": pm_db.current_drawdown_pct,
            "daily_loss_pct": 0.0,
            "max_daily_loss_pct": pm_db.max_daily_loss_pct,
            "max_total_drawdown_pct": pm_db.max_total_drawdown_pct,
            "open_positions": 0,
            "max_concurrent_positions": pm_db.max_concurrent_positions,
            "agents": {},
        }

    # Enrich with agent details from DB
    agents = db.query(TradingAgent).filter(
        TradingAgent.created_by == user.id,
        TradingAgent.deleted_at.is_(None),
    ).all()

    summary["agents_detail"] = [
        {
            "id": a.id,
            "name": a.name,
            "symbol": a.symbol,
            "timeframe": a.timeframe,
            "status": a.status,
            "mode": a.mode,
            "strategy_id": a.strategy_id,
            "performance_stats": a.performance_stats or {},
            "portfolio_id": a.portfolio_id,
        }
        for a in agents
    ]

    return summary


@router.get("/equity-curve")
def get_equity_curve(
    days: int = 30,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get equity curve data from portfolio snapshots."""
    pm_db = db.query(PortfolioManager).filter(
        PortfolioManager.user_id == user.id
    ).first()

    if not pm_db:
        return {"snapshots": []}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    snapshots = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.portfolio_id == pm_db.id,
        PortfolioSnapshot.timestamp >= cutoff,
    ).order_by(PortfolioSnapshot.timestamp).all()

    return {
        "snapshots": [
            {
                "timestamp": s.timestamp.isoformat(),
                "equity": s.total_equity,
                "pnl": s.total_pnl,
                "daily_pnl": s.daily_pnl,
                "drawdown_pct": s.drawdown_pct,
            }
            for s in snapshots
        ]
    }


@router.get("/agents")
def get_portfolio_agents(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get all agents with their live P&L and status."""
    agents = db.query(TradingAgent).filter(
        TradingAgent.created_by == user.id,
        TradingAgent.deleted_at.is_(None),
    ).all()

    pm = get_portfolio_manager(user.id)

    result = []
    for a in agents:
        agent_data = {
            "id": a.id,
            "name": a.name,
            "symbol": a.symbol,
            "timeframe": a.timeframe,
            "status": a.status,
            "mode": a.mode,
            "strategy_id": a.strategy_id,
            "performance_stats": a.performance_stats or {},
        }

        # Add live PM data if available
        if pm and a.id in pm._agents:
            pm_state = pm._agents[a.id]
            agent_data["live"] = {
                "direction": pm_state.direction,
                "daily_pnl": round(pm_state.daily_pnl, 2),
                "total_pnl": round(pm_state.total_pnl, 2),
                "trades_today": pm_state.trades_today,
            }

        result.append(agent_data)

    return {"agents": result}


@router.post("/rebalance")
def rebalance_portfolio(
    req: RebalanceRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Adjust capital allocation across agents."""
    pm_db = db.query(PortfolioManager).filter(
        PortfolioManager.user_id == user.id
    ).first()

    if not pm_db:
        raise HTTPException(404, "No portfolio manager found")

    # Validate allocations sum to <= 1.0
    total = sum(req.capital_allocation.values())
    if total > 1.0:
        raise HTTPException(400, f"Allocation sum {total:.2f} exceeds 1.0")

    pm_db.capital_allocation = req.capital_allocation
    db.commit()

    # Update in-memory PM
    pm = get_portfolio_manager(user.id)
    if pm:
        pm.capital_allocation = req.capital_allocation

    return {"status": "rebalanced", "allocation": req.capital_allocation}


@router.post("/pause-all")
def pause_all_agents(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Emergency halt — pause all agents in the portfolio."""
    from app.services.agent.engine import algo_engine

    agents = db.query(TradingAgent).filter(
        TradingAgent.created_by == user.id,
        TradingAgent.status == "running",
        TradingAgent.deleted_at.is_(None),
    ).all()

    paused = 0
    for a in agents:
        try:
            algo_engine.stop_agent(a.id)
            a.status = "paused"
            paused += 1
        except Exception as e:
            logger.error("Failed to pause agent %s: %s", a.id, e)

    db.commit()

    # Pause PM
    pm = get_portfolio_manager(user.id)
    if pm:
        pm._paused = True

    return {"status": "paused", "agents_paused": paused}


@router.post("/unpause")
def unpause_portfolio(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Resume portfolio after circuit breaker or manual pause."""
    pm = get_portfolio_manager(user.id)
    if pm:
        pm.unpause()

    pm_db = db.query(PortfolioManager).filter(
        PortfolioManager.user_id == user.id
    ).first()
    if pm_db:
        pm_db.status = "active"
        db.commit()

    return {"status": "unpaused"}


@router.get("/correlation")
def get_correlation_matrix(
    user: User = Depends(get_current_user),
):
    """Get current correlation data between active symbols."""
    from app.services.agent.portfolio_manager import CORRELATION_GROUPS, DEFAULT_INTRA_GROUP_CORR

    pm = get_portfolio_manager(user.id)
    if not pm:
        return {"matrix": {}, "groups": CORRELATION_GROUPS}

    # Build correlation matrix from active agents
    active_symbols = [a.symbol for a in pm._agents.values() if a.direction is not None]
    matrix = {}
    for i, s1 in enumerate(active_symbols):
        for s2 in active_symbols[i + 1:]:
            g1 = pm._get_correlation_group(s1)
            g2 = pm._get_correlation_group(s2)
            corr = DEFAULT_INTRA_GROUP_CORR if (g1 and g1 == g2) else 0.1
            matrix[f"{s1}_{s2}"] = round(corr, 2)

    return {"matrix": matrix, "groups": CORRELATION_GROUPS, "active_symbols": active_symbols}


@router.put("/settings")
def update_portfolio_settings(
    req: PortfolioUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update portfolio manager settings."""
    pm_db = db.query(PortfolioManager).filter(
        PortfolioManager.user_id == user.id
    ).first()

    if not pm_db:
        raise HTTPException(404, "No portfolio manager found")

    for field, value in req.model_dump(exclude_none=True).items():
        setattr(pm_db, field, value)

    db.commit()

    # Update in-memory PM
    pm = get_portfolio_manager(user.id)
    if pm:
        for field, value in req.model_dump(exclude_none=True).items():
            if hasattr(pm, field):
                setattr(pm, field, value)
            elif hasattr(pm, f"max_{field}"):
                setattr(pm, f"max_{field}", value)

    return {"status": "updated"}


@router.get("/risk-presets")
def get_risk_presets():
    """List available risk management presets (prop firm, conservative, etc.)."""
    from app.services.agent.risk_manager import list_risk_presets
    return {"presets": list_risk_presets()}
