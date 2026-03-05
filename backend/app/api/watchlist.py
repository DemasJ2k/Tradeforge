"""
Watchlist API endpoints — symbol watchlists and price alerts.

Endpoints:
  GET    /api/watchlist              — list user’s watchlists
  POST   /api/watchlist              — create a watchlist
  PUT    /api/watchlist/{id}         — update watchlist (name, symbols)
  DELETE /api/watchlist/{id}         — delete a watchlist
  POST   /api/watchlist/{id}/symbol  — add symbol to watchlist
  DELETE /api/watchlist/{id}/symbol/{sym} — remove symbol from watchlist
  GET    /api/watchlist/alerts       — list price alerts
  POST   /api/watchlist/alerts       — create price alert
  PUT    /api/watchlist/alerts/{id}  — update alert
  DELETE /api/watchlist/alerts/{id}  — delete alert
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.watchlist import Watchlist, WatchlistAlert

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/watchlists", tags=["watchlist"])


# ── Schemas ──────────────────────────────────────────────────────────────────────────────

class WatchlistCreate(BaseModel):
    name: str = "Default"
    symbols: list[str] = []

class WatchlistUpdate(BaseModel):
    name: Optional[str] = None
    symbols: Optional[list[str]] = None

class SymbolAdd(BaseModel):
    symbol: str

class AlertCreate(BaseModel):
    symbol: str
    condition: str  # price_above, price_below, pct_change
    threshold: float
    message: str = ""

class AlertUpdate(BaseModel):
    condition: Optional[str] = None
    threshold: Optional[float] = None
    message: Optional[str] = None
    active: Optional[bool] = None


# ── Watchlists ───────────────────────────────────────────────────────────────────────────

@router.get("")
async def list_watchlists(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all user watchlists."""
    watchlists = db.query(Watchlist).filter(Watchlist.user_id == user.id).all()
    return {
        "watchlists": [
            {
                "id": w.id,
                "name": w.name,
                "symbols": w.symbols or [],
                "created_at": w.created_at.isoformat() if w.created_at else None,
                "updated_at": w.updated_at.isoformat() if w.updated_at else None,
            }
            for w in watchlists
        ]
    }


@router.post("")
async def create_watchlist(
    body: WatchlistCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new watchlist."""
    wl = Watchlist(
        user_id=user.id,
        name=body.name,
        symbols=[s.upper() for s in body.symbols],
    )
    db.add(wl)
    db.commit()
    db.refresh(wl)
    return {"id": wl.id, "name": wl.name, "symbols": wl.symbols}


@router.put("/{watchlist_id}")
async def update_watchlist(
    watchlist_id: int,
    body: WatchlistUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a watchlist."""
    wl = db.query(Watchlist).filter(
        Watchlist.id == watchlist_id, Watchlist.user_id == user.id
    ).first()
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    if body.name is not None:
        wl.name = body.name
    if body.symbols is not None:
        wl.symbols = [s.upper() for s in body.symbols]

    db.commit()
    return {"id": wl.id, "name": wl.name, "symbols": wl.symbols}


@router.delete("/{watchlist_id}")
async def delete_watchlist(
    watchlist_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a watchlist."""
    wl = db.query(Watchlist).filter(
        Watchlist.id == watchlist_id, Watchlist.user_id == user.id
    ).first()
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    db.delete(wl)
    db.commit()
    return {"message": "Watchlist deleted"}


@router.post("/{watchlist_id}/symbols")
async def add_symbol(
    watchlist_id: int,
    body: SymbolAdd,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a symbol to a watchlist."""
    wl = db.query(Watchlist).filter(
        Watchlist.id == watchlist_id, Watchlist.user_id == user.id
    ).first()
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    symbols = list(wl.symbols or [])
    sym = body.symbol.upper()
    if sym not in symbols:
        symbols.append(sym)
        wl.symbols = symbols
        db.commit()

    return {"symbols": wl.symbols}


@router.delete("/{watchlist_id}/symbols/{symbol}")
async def remove_symbol(
    watchlist_id: int,
    symbol: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a symbol from a watchlist."""
    wl = db.query(Watchlist).filter(
        Watchlist.id == watchlist_id, Watchlist.user_id == user.id
    ).first()
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    symbols = list(wl.symbols or [])
    sym = symbol.upper()
    if sym in symbols:
        symbols.remove(sym)
        wl.symbols = symbols
        db.commit()

    return {"symbols": wl.symbols}


# ── Alerts ─────────────────────────────────────────────────────────────────────────────

@router.get("/alerts")
async def list_alerts(
    active_only: bool = Query(False, description="Only show active alerts"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List user's price alerts."""
    q = db.query(WatchlistAlert).filter(WatchlistAlert.user_id == user.id)
    if active_only:
        q = q.filter(WatchlistAlert.active == True)
    alerts = q.order_by(WatchlistAlert.created_at.desc()).all()
    return {
        "alerts": [
            {
                "id": a.id,
                "symbol": a.symbol,
                "condition": a.condition,
                "threshold": a.threshold,
                "message": a.message,
                "triggered": a.triggered,
                "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None,
                "active": a.active,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in alerts
        ]
    }


@router.post("/alerts")
async def create_alert(
    body: AlertCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a price alert."""
    valid_conditions = {"price_above", "price_below", "pct_change"}
    if body.condition not in valid_conditions:
        raise HTTPException(status_code=400, detail=f"Invalid condition. Must be: {valid_conditions}")

    alert = WatchlistAlert(
        user_id=user.id,
        symbol=body.symbol.upper(),
        condition=body.condition,
        threshold=body.threshold,
        message=body.message,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return {"id": alert.id, "symbol": alert.symbol, "condition": alert.condition, "threshold": alert.threshold}


@router.put("/alerts/{alert_id}")
async def update_alert(
    alert_id: int,
    body: AlertUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a price alert."""
    alert = db.query(WatchlistAlert).filter(
        WatchlistAlert.id == alert_id, WatchlistAlert.user_id == user.id
    ).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if body.condition is not None:
        alert.condition = body.condition
    if body.threshold is not None:
        alert.threshold = body.threshold
    if body.message is not None:
        alert.message = body.message
    if body.active is not None:
        alert.active = body.active

    db.commit()
    return {"id": alert.id, "message": "Alert updated"}


@router.delete("/alerts/{alert_id}")
async def delete_alert(
    alert_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a price alert."""
    alert = db.query(WatchlistAlert).filter(
        WatchlistAlert.id == alert_id, WatchlistAlert.user_id == user.id
    ).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    db.delete(alert)
    db.commit()
    return {"message": "Alert deleted"}
