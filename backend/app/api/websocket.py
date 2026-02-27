"""
WebSocket API endpoint.

Handles WebSocket connections with JWT authentication.
"""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt

from app.core.config import settings
from app.core.websocket import manager

logger = logging.getLogger(__name__)

router = APIRouter()


def _authenticate_ws(token: str) -> int | None:
    """Validate JWT token and return user_id, or None on failure."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id_str = payload.get("sub")
        if user_id_str is None:
            return None
        return int(user_id_str)
    except (JWTError, ValueError):
        return None


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Main WebSocket endpoint.

    Connect with: ws://localhost:8000/ws?token=<jwt>

    Messages (JSON):
      → { "type": "subscribe", "channel": "ticks:XAUUSD" }
      → { "type": "unsubscribe", "channel": "ticks:XAUUSD" }
      → { "type": "pong" }
    """
    # Authenticate via query param
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    user_id = _authenticate_ws(token)
    if user_id is None:
        await websocket.close(code=4001, reason="Invalid token")
        return

    # Accept and register connection
    conn = await manager.connect(websocket, user_id)

    try:
        while True:
            raw = await websocket.receive_text()
            await manager.handle_message(websocket, raw)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("WebSocket error for user %d: %s", user_id, e)
    finally:
        await manager.disconnect(websocket)


@router.get("/api/ws/stats")
async def ws_stats():
    """Get WebSocket connection statistics (debug endpoint)."""
    return manager.stats()
