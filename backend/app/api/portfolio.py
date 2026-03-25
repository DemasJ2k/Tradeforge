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

@router.get("")
def get_portfolio(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Root portfolio endpoint — returns summary redirect info."""
    pm = db.query(PortfolioManager).filter(PortfolioManager.user_id == user.id).first()
    if not pm:
        return {"has_portfolio": False, "message": "No portfolio created yet. Use POST /api/portfolio/create."}
    return {
        "has_portfolio": True,
        "portfolio_id": pm.id,
        "name": pm.name,
        "mode": pm.mode,
        "paused": pm.paused,
        "links": {
            "summary": "/api/portfolio/summary",
            "broker_portfolios": "/api/portfolio/broker-portfolios",
            "settings": "/api/portfolio/settings",
        },
    }


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
async def get_portfolio_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get portfolio summary with REAL broker data + agent P&L from DB."""
    from sqlalchemy import func, case
    from app.models.agent import AgentTrade
    from app.services.broker.manager import broker_manager
    from app.services.fx_rates import convert_to_usd

    pm_db = db.query(PortfolioManager).filter(
        PortfolioManager.user_id == user.id
    ).first()

    if not pm_db:
        pm_db = PortfolioManager(user_id=user.id, name="Default Portfolio")
        db.add(pm_db)
        db.commit()
        db.refresh(pm_db)

    # ── Real broker equity ──
    total_equity_usd = 0.0
    total_balance_usd = 0.0
    for bname, adapter in broker_manager.get_user_adapters(user.id).items():
        if not adapter:
            continue
        try:
            info = await adapter.get_account_info()
            if info:
                currency = getattr(info, "currency", "USD") if not isinstance(info, dict) else info.get("currency", "USD")
                equity = getattr(info, "equity", 0) if not isinstance(info, dict) else info.get("equity", 0)
                balance = getattr(info, "balance", 0) if not isinstance(info, dict) else info.get("balance", 0)
                total_equity_usd += await convert_to_usd(equity, currency)
                total_balance_usd += await convert_to_usd(balance, currency)
        except Exception:
            pass

    # ── Agent P&L from DB (reliable, survives restarts) ──
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    agents = db.query(TradingAgent).filter(
        TradingAgent.created_by == user.id,
        TradingAgent.deleted_at.is_(None),
    ).all()
    agent_ids = [a.id for a in agents]

    total_pnl = 0.0
    daily_pnl = 0.0
    if agent_ids:
        total_pnl = db.query(func.coalesce(func.sum(AgentTrade.pnl), 0)).filter(
            AgentTrade.agent_id.in_(agent_ids),
            AgentTrade.status.in_(["executed", "paper", "closed"]),
        ).scalar() or 0.0

        daily_pnl = db.query(func.coalesce(func.sum(AgentTrade.pnl), 0)).filter(
            AgentTrade.agent_id.in_(agent_ids),
            AgentTrade.status.in_(["executed", "paper", "closed"]),
            AgentTrade.created_at >= today_start,
        ).scalar() or 0.0

    # Drawdown: use peak equity from PM DB or current equity as peak
    peak_equity = max(pm_db.peak_equity or total_equity_usd, total_equity_usd) if total_equity_usd > 0 else pm_db.peak_equity or 0
    drawdown_pct = ((peak_equity - total_equity_usd) / peak_equity * 100) if peak_equity > 0 and total_equity_usd < peak_equity else 0.0
    daily_loss_pct = (abs(min(daily_pnl, 0)) / total_balance_usd * 100) if total_balance_usd > 0 and daily_pnl < 0 else 0.0

    # Update PM DB with real values
    pm_db.current_equity = total_equity_usd
    if total_equity_usd > (pm_db.peak_equity or 0):
        pm_db.peak_equity = total_equity_usd
    pm_db.daily_pnl = float(daily_pnl)
    pm_db.total_pnl = float(total_pnl)
    pm_db.current_drawdown_pct = drawdown_pct
    db.commit()

    # Count open positions across brokers
    open_positions = 0
    for bname, adapter in broker_manager.get_user_adapters(user.id).items():
        if adapter:
            try:
                pos = await adapter.get_positions()
                open_positions += len(pos or [])
            except Exception:
                pass

    summary = {
        "portfolio_id": pm_db.id,
        "mode": pm_db.mode,
        "status": pm_db.status,
        "current_equity": round(total_equity_usd, 2),
        "peak_equity": round(peak_equity, 2),
        "daily_pnl": round(float(daily_pnl), 2),
        "total_pnl": round(float(total_pnl), 2),
        "drawdown_pct": round(drawdown_pct, 2),
        "daily_loss_pct": round(daily_loss_pct, 2),
        "max_daily_loss_pct": pm_db.max_daily_loss_pct,
        "max_total_drawdown_pct": pm_db.max_total_drawdown_pct,
        "open_positions": open_positions,
        "max_concurrent_positions": pm_db.max_concurrent_positions,
        "agents": {},
    }

    # Enrich with agent details + real P&L from AgentTrade table
    agent_pnl_map = {}
    if agent_ids:
        pnl_rows = (
            db.query(
                AgentTrade.agent_id,
                func.coalesce(func.sum(AgentTrade.pnl), 0).label("total_pnl"),
                func.count(AgentTrade.id).label("total_trades"),
                func.sum(case((AgentTrade.pnl > 0, 1), else_=0)).label("wins"),
            )
            .filter(
                AgentTrade.agent_id.in_(agent_ids),
                AgentTrade.status.in_(["executed", "paper", "closed"]),
            )
            .group_by(AgentTrade.agent_id)
            .all()
        )
        for row in pnl_rows:
            total_trades = row.total_trades or 0
            wins = row.wins or 0
            agent_pnl_map[row.agent_id] = {
                "total_pnl": round(float(row.total_pnl), 2),
                "total_trades": total_trades,
                "wins": wins,
                "win_rate": round(wins / total_trades * 100, 1) if total_trades > 0 else 0,
            }

    # Daily P&L per agent
    agent_daily_map = {}
    if agent_ids:
        daily_rows = (
            db.query(
                AgentTrade.agent_id,
                func.coalesce(func.sum(AgentTrade.pnl), 0).label("daily_pnl"),
            )
            .filter(
                AgentTrade.agent_id.in_(agent_ids),
                AgentTrade.status.in_(["executed", "paper", "closed"]),
                AgentTrade.created_at >= today_start,
            )
            .group_by(AgentTrade.agent_id)
            .all()
        )
        for row in daily_rows:
            agent_daily_map[row.agent_id] = round(float(row.daily_pnl), 2)

    summary["agents_detail"] = [
        {
            "id": a.id,
            "name": a.name,
            "symbol": a.symbol,
            "timeframe": a.timeframe,
            "status": a.status,
            "mode": a.mode,
            "strategy_id": a.strategy_id,
            "broker_name": a.broker_name or "",
            "total_pnl": agent_pnl_map.get(a.id, {}).get("total_pnl", 0),
            "total_trades": agent_pnl_map.get(a.id, {}).get("total_trades", 0),
            "wins": agent_pnl_map.get(a.id, {}).get("wins", 0),
            "win_rate": agent_pnl_map.get(a.id, {}).get("win_rate", 0),
            "daily_pnl": agent_daily_map.get(a.id, 0),
        }
        for a in agents
    ]

    return summary


@router.get("/broker-portfolios")
async def get_broker_portfolios(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get portfolio data split by broker — each broker is a separate portfolio section."""
    from sqlalchemy import func, case
    from app.models.agent import AgentTrade
    from app.services.broker.manager import broker_manager
    from app.services.fx_rates import convert_to_usd

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    agents = db.query(TradingAgent).filter(
        TradingAgent.created_by == user.id,
        TradingAgent.deleted_at.is_(None),
    ).all()
    agent_ids = [a.id for a in agents]

    # Agent P&L from DB
    agent_pnl_map = {}
    agent_daily_map = {}
    if agent_ids:
        pnl_rows = (
            db.query(
                AgentTrade.agent_id,
                func.coalesce(func.sum(AgentTrade.pnl), 0).label("total_pnl"),
                func.count(AgentTrade.id).label("total_trades"),
                func.sum(case((AgentTrade.pnl > 0, 1), else_=0)).label("wins"),
            )
            .filter(
                AgentTrade.agent_id.in_(agent_ids),
                AgentTrade.status.in_(["executed", "paper", "closed"]),
            )
            .group_by(AgentTrade.agent_id)
            .all()
        )
        for row in pnl_rows:
            total_trades = row.total_trades or 0
            wins = row.wins or 0
            agent_pnl_map[row.agent_id] = {
                "total_pnl": round(float(row.total_pnl), 2),
                "total_trades": total_trades,
                "wins": wins,
                "win_rate": round(wins / total_trades * 100, 1) if total_trades > 0 else 0,
            }

        daily_rows = (
            db.query(
                AgentTrade.agent_id,
                func.coalesce(func.sum(AgentTrade.pnl), 0).label("daily_pnl"),
            )
            .filter(
                AgentTrade.agent_id.in_(agent_ids),
                AgentTrade.status.in_(["executed", "paper", "closed"]),
                AgentTrade.created_at >= today_start,
            )
            .group_by(AgentTrade.agent_id)
            .all()
        )
        for row in daily_rows:
            agent_daily_map[row.agent_id] = round(float(row.daily_pnl), 2)

    # Group agents by broker
    broker_agent_map: dict[str, list] = {}
    for a in agents:
        bname = a.broker_name or "unassigned"
        if bname not in broker_agent_map:
            broker_agent_map[bname] = []
        broker_agent_map[bname].append({
            "id": a.id,
            "name": a.name,
            "symbol": a.symbol,
            "timeframe": a.timeframe,
            "status": a.status,
            "mode": a.mode,
            "strategy_id": a.strategy_id,
            "total_pnl": agent_pnl_map.get(a.id, {}).get("total_pnl", 0),
            "total_trades": agent_pnl_map.get(a.id, {}).get("total_trades", 0),
            "wins": agent_pnl_map.get(a.id, {}).get("wins", 0),
            "win_rate": agent_pnl_map.get(a.id, {}).get("win_rate", 0),
            "daily_pnl": agent_daily_map.get(a.id, 0),
        })

    # Build broker sections with real account data
    brokers = []
    combined_balance_usd = 0.0
    combined_equity_usd = 0.0
    combined_daily_pnl = 0.0

    # Collect all broker names: both connected adapters and brokers with agents
    user_adapters = broker_manager.get_user_adapters(user.id)
    all_broker_names = set(user_adapters.keys()) | set(broker_agent_map.keys())
    all_broker_names.discard("unassigned")  # handled separately below

    for bname in sorted(all_broker_names):
        adapter = user_adapters.get(bname)
        broker_data = {
            "broker": bname,
            "currency": "USD",
            "balance": 0.0,
            "equity": 0.0,
            "balance_usd": 0.0,
            "equity_usd": 0.0,
            "daily_pnl": 0.0,
            "drawdown_pct": 0.0,
            "agents": broker_agent_map.get(bname, []),
        }

        if adapter:
            try:
                info = await adapter.get_account_info()
                if info:
                    currency = getattr(info, "currency", "USD") if not isinstance(info, dict) else info.get("currency", "USD")
                    balance = getattr(info, "balance", 0) if not isinstance(info, dict) else info.get("balance", 0)
                    equity = getattr(info, "equity", 0) if not isinstance(info, dict) else info.get("equity", 0)
                    balance_usd = await convert_to_usd(balance, currency)
                    equity_usd = await convert_to_usd(equity, currency)

                    # Broker-level daily PnL from its agents
                    broker_daily = sum(a["daily_pnl"] for a in broker_data["agents"])

                    broker_data.update({
                        "currency": currency,
                        "balance": balance,
                        "equity": equity,
                        "balance_usd": balance_usd,
                        "equity_usd": equity_usd,
                        "daily_pnl": broker_daily,
                        "drawdown_pct": round(((balance - equity) / balance * 100) if balance > 0 and equity < balance else 0, 2),
                    })

                    combined_balance_usd += balance_usd
                    combined_equity_usd += equity_usd
                    combined_daily_pnl += broker_daily
            except Exception:
                pass

        brokers.append(broker_data)

    # Add unassigned agents if any
    if "unassigned" in broker_agent_map:
        brokers.append({
            "broker": "unassigned",
            "currency": "USD",
            "balance": 0.0, "equity": 0.0,
            "balance_usd": 0.0, "equity_usd": 0.0,
            "daily_pnl": 0.0, "drawdown_pct": 0.0,
            "agents": broker_agent_map["unassigned"],
        })

    return {
        "brokers": brokers,
        "combined": {
            "total_balance_usd": round(combined_balance_usd, 2),
            "total_equity_usd": round(combined_equity_usd, 2),
            "total_daily_pnl": round(combined_daily_pnl, 2),
        },
    }


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

    # Validate allocations: no negative values and sum <= 1.0
    values = req.capital_allocation.values()
    if any(v < 0 for v in values):
        raise HTTPException(400, "Allocation values must be non-negative")
    total = sum(values)
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
async def pause_all_agents(
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
            await algo_engine.pause_agent(a.id)
            paused += 1
        except Exception as e:
            logger.error("Failed to pause agent %s: %s", a.id, e)

    # Pause PM
    pm = get_portfolio_manager(user.id)
    if pm:
        pm._paused = True

    # Persist paused status to DB
    pm_db = db.query(PortfolioManager).filter(
        PortfolioManager.user_id == user.id
    ).first()
    if pm_db:
        pm_db.status = "paused"
        db.commit()

    return {"status": "paused", "agents_paused": paused}


@router.post("/unpause")
async def unpause_portfolio(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Resume portfolio after circuit breaker or manual pause — restarts paused agents."""
    from app.services.agent.engine import algo_engine

    pm = get_portfolio_manager(user.id)
    if pm:
        pm.unpause()

    pm_db = db.query(PortfolioManager).filter(
        PortfolioManager.user_id == user.id
    ).first()
    if pm_db:
        pm_db.status = "active"
        db.commit()

    # Restart all paused agents
    paused_agents = db.query(TradingAgent).filter(
        TradingAgent.created_by == user.id,
        TradingAgent.status == "paused",
        TradingAgent.deleted_at.is_(None),
    ).all()

    resumed = 0
    for a in paused_agents:
        try:
            await algo_engine.start_agent(a.id)
            resumed += 1
        except Exception as e:
            logger.error("Failed to resume agent %s: %s", a.id, e)

    return {"status": "unpaused", "agents_resumed": resumed}


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


@router.get("/settings")
def get_portfolio_settings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Read current portfolio settings."""
    pm = db.query(PortfolioManager).filter(PortfolioManager.user_id == user.id).first()
    if not pm:
        raise HTTPException(404, "No portfolio manager found")
    return {
        "name": pm.name,
        "mode": pm.mode,
        "max_daily_loss_pct": pm.max_daily_loss_pct,
        "max_total_drawdown_pct": pm.max_total_drawdown_pct,
        "max_portfolio_risk_pct": pm.max_portfolio_risk_pct,
        "correlation_threshold": pm.correlation_threshold,
        "max_concurrent_positions": pm.max_concurrent_positions,
        "paused": pm.paused,
    }


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

    # Validate percentage ranges
    updates = req.model_dump(exclude_none=True)
    for pct_field in ("max_daily_loss_pct", "max_total_drawdown_pct", "max_portfolio_risk_pct", "correlation_threshold"):
        if pct_field in updates:
            val = updates[pct_field]
            if not isinstance(val, (int, float)) or val < 0 or val > 100:
                raise HTTPException(400, f"{pct_field} must be between 0 and 100")
    if "max_concurrent_positions" in updates:
        val = updates["max_concurrent_positions"]
        if not isinstance(val, int) or val < 1 or val > 100:
            raise HTTPException(400, "max_concurrent_positions must be between 1 and 100")

    for field, value in updates.items():
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
