"""
Webhook API endpoints — configure and manage webhook notifications.

Endpoints:
  GET    /api/webhooks              — list webhook endpoints
  POST   /api/webhooks              — create webhook endpoint
  PUT    /api/webhooks/{id}         — update webhook endpoint
  DELETE /api/webhooks/{id}         — delete webhook endpoint
  POST   /api/webhooks/{id}/test    — send test webhook
  GET    /api/webhooks/{id}/logs    — get delivery logs
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.watchlist import WebhookEndpoint, WebhookLog
from app.services.webhook import dispatch_webhook

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


# ── Schemas ──────────────────────────────────────────────────────────────────

VALID_EVENTS = {
    "trade_opened", "trade_closed", "signal_generated",
    "agent_started", "agent_stopped", "agent_error",
    "backtest_complete", "optimization_complete",
    "alert_triggered", "price_alert",
}

class WebhookCreate(BaseModel):
    name: str
    url: str
    events: list[str] = []
    headers: dict = {}
    secret: str = ""
    enabled: bool = True

class WebhookUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    events: Optional[list[str]] = None
    headers: Optional[dict] = None
    secret: Optional[str] = None
    enabled: Optional[bool] = None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
async def list_webhooks(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all configured webhook endpoints."""
    endpoints = db.query(WebhookEndpoint).filter(
        WebhookEndpoint.user_id == user.id
    ).order_by(WebhookEndpoint.created_at.desc()).all()

    return {
        "webhooks": [
            {
                "id": ep.id,
                "name": ep.name,
                "url": ep.url,
                "events": ep.events or [],
                "enabled": ep.enabled,
                "has_secret": bool(ep.secret),
                "last_triggered_at": ep.last_triggered_at.isoformat() if ep.last_triggered_at else None,
                "last_status_code": ep.last_status_code,
                "failure_count": ep.failure_count,
                "created_at": ep.created_at.isoformat() if ep.created_at else None,
            }
            for ep in endpoints
        ]
    }


@router.post("")
async def create_webhook(
    body: WebhookCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new webhook endpoint."""
    # Validate events
    invalid = set(body.events) - VALID_EVENTS
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid events: {invalid}. Valid: {VALID_EVENTS}"
        )

    # Validate URL
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    endpoint = WebhookEndpoint(
        user_id=user.id,
        name=body.name,
        url=body.url,
        events=body.events,
        headers=body.headers,
        secret=body.secret,
        enabled=body.enabled,
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)

    return {"id": endpoint.id, "name": endpoint.name, "message": "Webhook created"}


@router.put("/{webhook_id}")
async def update_webhook(
    webhook_id: int,
    body: WebhookUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a webhook endpoint."""
    endpoint = db.query(WebhookEndpoint).filter(
        WebhookEndpoint.id == webhook_id, WebhookEndpoint.user_id == user.id
    ).first()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook not found")

    if body.name is not None:
        endpoint.name = body.name
    if body.url is not None:
        endpoint.url = body.url
    if body.events is not None:
        invalid = set(body.events) - VALID_EVENTS
        if invalid:
            raise HTTPException(status_code=400, detail=f"Invalid events: {invalid}")
        endpoint.events = body.events
    if body.headers is not None:
        endpoint.headers = body.headers
    if body.secret is not None:
        endpoint.secret = body.secret
    if body.enabled is not None:
        endpoint.enabled = body.enabled

    db.commit()
    return {"id": endpoint.id, "message": "Webhook updated"}


@router.delete("/{webhook_id}")
async def delete_webhook(
    webhook_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a webhook endpoint."""
    endpoint = db.query(WebhookEndpoint).filter(
        WebhookEndpoint.id == webhook_id, WebhookEndpoint.user_id == user.id
    ).first()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook not found")

    # Delete associated logs
    db.query(WebhookLog).filter(WebhookLog.endpoint_id == webhook_id).delete()
    db.delete(endpoint)
    db.commit()
    return {"message": "Webhook deleted"}


@router.post("/{webhook_id}/test")
async def test_webhook(
    webhook_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a test webhook payload."""
    endpoint = db.query(WebhookEndpoint).filter(
        WebhookEndpoint.id == webhook_id, WebhookEndpoint.user_id == user.id
    ).first()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook not found")

    test_payload = {
        "event": "test",
        "message": "This is a test webhook from TradeForge",
        "webhook_id": webhook_id,
        "webhook_name": endpoint.name,
    }

    result = await dispatch_webhook(db, endpoint, "test", test_payload)
    return result


@router.get("/{webhook_id}/logs")
async def webhook_logs(
    webhook_id: int,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get delivery logs for a webhook endpoint."""
    # Verify ownership
    endpoint = db.query(WebhookEndpoint).filter(
        WebhookEndpoint.id == webhook_id, WebhookEndpoint.user_id == user.id
    ).first()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook not found")

    logs = (
        db.query(WebhookLog)
        .filter(WebhookLog.endpoint_id == webhook_id)
        .order_by(WebhookLog.delivered_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "logs": [
            {
                "id": log.id,
                "event_type": log.event_type,
                "payload": log.payload,
                "status_code": log.status_code,
                "success": log.success,
                "delivered_at": log.delivered_at.isoformat() if log.delivered_at else None,
            }
            for log in logs
        ]
    }
