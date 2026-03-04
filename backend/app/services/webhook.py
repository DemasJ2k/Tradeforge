"""
Webhook dispatch service — sends HTTP POST notifications to configured endpoints.

Usage:
    from app.services.webhook import fire_webhooks

    # Fire webhooks for all users who subscribed to "trade_opened"
    await fire_webhooks(db, user_id, "trade_opened", {"symbol": "XAUUSD", "direction": "long", ...})
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.models.watchlist import WebhookEndpoint, WebhookLog

_log = logging.getLogger(__name__)

WEBHOOK_TIMEOUT = 10  # seconds


async def dispatch_webhook(
    db: Session,
    endpoint: WebhookEndpoint,
    event_type: str,
    payload: dict,
) -> dict:
    """
    Send a single webhook POST request and log the result.
    Returns {success, status_code, message}.
    """
    # Build headers
    headers = {"Content-Type": "application/json", "User-Agent": "TradeForge-Webhook/1.0"}
    if endpoint.headers:
        headers.update(endpoint.headers)

    # Sign payload if secret is set
    body_bytes = json.dumps(payload).encode("utf-8")
    if endpoint.secret:
        signature = hmac.new(
            endpoint.secret.encode("utf-8"),
            body_bytes,
            hashlib.sha256,
        ).hexdigest()
        headers["X-TradeForge-Signature"] = f"sha256={signature}"

    # Add event type header
    headers["X-TradeForge-Event"] = event_type

    # Send request
    status_code = None
    response_body = ""
    success = False

    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT) as client:
            resp = await client.post(endpoint.url, content=body_bytes, headers=headers)
            status_code = resp.status_code
            response_body = resp.text[:500]  # Truncate response
            success = 200 <= status_code < 300

    except httpx.TimeoutException:
        response_body = "Request timed out"
        _log.warning("Webhook timeout: %s → %s", endpoint.name, endpoint.url)
    except Exception as e:
        response_body = str(e)[:500]
        _log.error("Webhook error: %s → %s: %s", endpoint.name, endpoint.url, e)

    # Log the delivery
    log_entry = WebhookLog(
        endpoint_id=endpoint.id,
        event_type=event_type,
        payload=payload,
        status_code=status_code,
        response_body=response_body,
        success=success,
    )
    db.add(log_entry)

    # Update endpoint status
    endpoint.last_triggered_at = datetime.now(timezone.utc)
    endpoint.last_status_code = status_code
    if success:
        endpoint.failure_count = 0
    else:
        endpoint.failure_count = (endpoint.failure_count or 0) + 1

    try:
        db.commit()
    except Exception:
        db.rollback()

    return {
        "success": success,
        "status_code": status_code,
        "message": "Delivered" if success else f"Failed: {response_body[:100]}",
    }


async def fire_webhooks(
    db: Session,
    user_id: int,
    event_type: str,
    payload: dict,
) -> int:
    """
    Fire webhooks for a specific user and event type.
    Returns the number of webhooks dispatched.
    """
    # Find all enabled endpoints for this user that subscribe to this event
    endpoints = db.query(WebhookEndpoint).filter(
        WebhookEndpoint.user_id == user_id,
        WebhookEndpoint.enabled == True,
    ).all()

    # Filter by event subscription
    matching = [
        ep for ep in endpoints
        if not ep.events or event_type in (ep.events or [])
    ]

    if not matching:
        return 0

    # Skip endpoints with too many consecutive failures
    MAX_FAILURES = 10
    healthy = [ep for ep in matching if (ep.failure_count or 0) < MAX_FAILURES]

    dispatched = 0
    for ep in healthy:
        try:
            await dispatch_webhook(db, ep, event_type, payload)
            dispatched += 1
        except Exception as e:
            _log.error("Failed to dispatch webhook %d: %s", ep.id, e)

    if len(matching) > len(healthy):
        _log.warning(
            "Skipped %d webhooks due to excessive failures (>%d consecutive)",
            len(matching) - len(healthy), MAX_FAILURES,
        )

    return dispatched
