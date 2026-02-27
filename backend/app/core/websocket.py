"""
WebSocket Connection Manager.

Handles WebSocket connections, channel subscriptions, and message broadcasting.
Channels follow the pattern: "ticks:{symbol}", "bars:{symbol}:{timeframe}", "agent:{id}", "system"
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class WSConnection:
    """Represents a single WebSocket connection."""
    websocket: WebSocket
    user_id: int
    subscriptions: set[str] = field(default_factory=set)
    connected_at: float = field(default_factory=time.time)
    last_pong: float = field(default_factory=time.time)


class ConnectionManager:
    """
    Manages WebSocket connections and channel-based message routing.

    Protocol (JSON messages):
      Client → Server:
        { "type": "subscribe",   "channel": "ticks:XAUUSD" }
        { "type": "unsubscribe", "channel": "ticks:XAUUSD" }
        { "type": "pong" }

      Server → Client:
        { "type": "tick",       "channel": "ticks:XAUUSD", "data": {...}, "ts": 1234567890.123 }
        { "type": "bar",        "channel": "bars:XAUUSD:M5", "data": {...}, "ts": ... }
        { "type": "bar_update", "channel": "bars:XAUUSD:M5", "data": {...}, "ts": ... }
        { "type": "agent",      "channel": "agent:1", "data": {...}, "ts": ... }
        { "type": "ping" }
        { "type": "subscribed", "channel": "ticks:XAUUSD" }
        { "type": "unsubscribed", "channel": "ticks:XAUUSD" }
        { "type": "error",      "message": "..." }
    """

    def __init__(self):
        self._connections: dict[int, list[WSConnection]] = {}  # user_id -> connections
        self._channels: dict[str, set[int]] = {}  # channel -> set of connection ids
        self._conn_by_id: dict[int, WSConnection] = {}  # id(ws) -> WSConnection
        self._lock = asyncio.Lock()
        self._heartbeat_task: Optional[asyncio.Task] = None
        # Callbacks for when channels gain/lose subscribers
        self._on_subscribe: list = []  # callbacks: (channel, first_subscriber: bool)
        self._on_unsubscribe: list = []  # callbacks: (channel, last_subscriber: bool)

    async def start(self):
        """Start the heartbeat task."""
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            logger.info("WebSocket heartbeat started")

    async def stop(self):
        """Stop the heartbeat task and close all connections."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

    # ── Connection lifecycle ───────────────────────────

    async def connect(self, websocket: WebSocket, user_id: int) -> WSConnection:
        """Accept a new WebSocket connection."""
        await websocket.accept()
        conn = WSConnection(websocket=websocket, user_id=user_id)
        conn_id = id(websocket)

        async with self._lock:
            if user_id not in self._connections:
                self._connections[user_id] = []
            self._connections[user_id].append(conn)
            self._conn_by_id[conn_id] = conn

        logger.info("WebSocket connected: user=%d, conn=%d", user_id, conn_id)
        return conn

    async def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection and clean up subscriptions."""
        conn_id = id(websocket)

        async with self._lock:
            conn = self._conn_by_id.pop(conn_id, None)
            if conn is None:
                return

            # Remove from user connections
            user_conns = self._connections.get(conn.user_id, [])
            self._connections[conn.user_id] = [c for c in user_conns if id(c.websocket) != conn_id]
            if not self._connections[conn.user_id]:
                del self._connections[conn.user_id]

            # Remove from all channel subscriptions
            channels_to_notify = []
            for channel in list(conn.subscriptions):
                if channel in self._channels:
                    self._channels[channel].discard(conn_id)
                    if not self._channels[channel]:
                        del self._channels[channel]
                        # Only notify "last subscriber" if no internal subs either
                        has_internal = bool(getattr(self, "_internal_subs", {}).get(channel))
                        if not has_internal:
                            channels_to_notify.append(channel)

        # Notify about empty channels outside lock
        for channel in channels_to_notify:
            for cb in self._on_unsubscribe:
                try:
                    await cb(channel, True)
                except Exception as e:
                    logger.error("Unsubscribe callback error: %s", e)

        logger.info("WebSocket disconnected: user=%d, conn=%d", conn.user_id, conn_id)

    # ── Channel management ─────────────────────────────

    async def subscribe(self, websocket: WebSocket, channel: str):
        """Subscribe a connection to a channel."""
        conn_id = id(websocket)
        first_subscriber = False

        async with self._lock:
            conn = self._conn_by_id.get(conn_id)
            if conn is None:
                return

            conn.subscriptions.add(channel)

            if channel not in self._channels:
                self._channels[channel] = set()
                # Only "first" if no internal subs either
                has_internal = bool(getattr(self, "_internal_subs", {}).get(channel))
                if not has_internal:
                    first_subscriber = True
            self._channels[channel].add(conn_id)

        # Confirm subscription
        await self._send(websocket, {"type": "subscribed", "channel": channel})

        # Notify callbacks
        if first_subscriber:
            for cb in self._on_subscribe:
                try:
                    await cb(channel, True)
                except Exception as e:
                    logger.error("Subscribe callback error: %s", e)

        logger.debug("Subscribed conn=%d to channel=%s (first=%s)", conn_id, channel, first_subscriber)

    async def unsubscribe(self, websocket: WebSocket, channel: str):
        """Unsubscribe a connection from a channel."""
        conn_id = id(websocket)
        last_subscriber = False

        async with self._lock:
            conn = self._conn_by_id.get(conn_id)
            if conn is None:
                return

            conn.subscriptions.discard(channel)

            if channel in self._channels:
                self._channels[channel].discard(conn_id)
                if not self._channels[channel]:
                    del self._channels[channel]
                    # Only "last" if no internal subs either
                    has_internal = bool(getattr(self, "_internal_subs", {}).get(channel))
                    if not has_internal:
                        last_subscriber = True

        await self._send(websocket, {"type": "unsubscribed", "channel": channel})

        if last_subscriber:
            for cb in self._on_unsubscribe:
                try:
                    await cb(channel, True)
                except Exception as e:
                    logger.error("Unsubscribe callback error: %s", e)

    def on_subscribe(self, callback):
        """Register a callback for channel subscription events: async (channel, first) -> None."""
        self._on_subscribe.append(callback)

    def on_unsubscribe(self, callback):
        """Register a callback for channel unsubscription events: async (channel, last) -> None."""
        self._on_unsubscribe.append(callback)

    def get_channel_subscribers(self, channel: str) -> int:
        """Get number of subscribers for a channel (WebSocket + internal)."""
        ws_count = len(self._channels.get(channel, set()))
        internal_count = len(getattr(self, "_internal_subs", {}).get(channel, []))
        return ws_count + internal_count

    def get_subscribed_channels(self, prefix: str = "") -> list[str]:
        """Get all channels with subscribers (WebSocket + internal), optionally filtered by prefix."""
        all_channels = set(self._channels.keys())
        all_channels.update(getattr(self, "_internal_subs", {}).keys())
        if prefix:
            return [ch for ch in all_channels if ch.startswith(prefix)]
        return list(all_channels)

    # ── Internal subscriptions (for backend services) ───

    async def subscribe_internal_async(self, channel: str, callback) -> callable:
        """
        Subscribe a backend service to a channel. The callback receives each
        message dict broadcast to the channel.

        This async version triggers on_subscribe callbacks so that the
        TickAggregator creates BarBuilders and starts tick streaming.

        Returns an unsubscribe callable.
        """
        if not hasattr(self, "_internal_subs"):
            self._internal_subs: dict[str, list] = {}

        # Check if this is the first subscriber (internal or external)
        has_ws_subs = bool(self._channels.get(channel))
        has_internal_subs = bool(self._internal_subs.get(channel))
        first_subscriber = not has_ws_subs and not has_internal_subs

        if channel not in self._internal_subs:
            self._internal_subs[channel] = []
        self._internal_subs[channel].append(callback)

        # Notify on_subscribe callbacks (e.g., TickAggregator) if first subscriber
        if first_subscriber:
            for cb in self._on_subscribe:
                try:
                    await cb(channel, True)
                except Exception as e:
                    logger.error("Internal subscribe callback error: %s", e)

        logger.info("Internal subscription (async) to %s (first=%s, callbacks=%d)",
                    channel, first_subscriber, len(self._on_subscribe))

        def unsub():
            subs = self._internal_subs.get(channel, [])
            if callback in subs:
                subs.remove(callback)
            if not subs and channel in self._internal_subs:
                del self._internal_subs[channel]
                # Check if this was the last subscriber of any kind
                has_ws = bool(self._channels.get(channel))
                if not has_ws:
                    for ucb in self._on_unsubscribe:
                        try:
                            asyncio.get_event_loop().create_task(ucb(channel, True))
                        except Exception as e:
                            logger.error("Internal unsubscribe callback error: %s", e)

        return unsub

    def subscribe_internal(self, channel: str, callback) -> callable:
        """
        Synchronous version of subscribe_internal (legacy).
        Does NOT trigger on_subscribe callbacks.
        Use subscribe_internal_async() for full integration with aggregator.
        """
        if not hasattr(self, "_internal_subs"):
            self._internal_subs: dict[str, list] = {}

        if channel not in self._internal_subs:
            self._internal_subs[channel] = []
        self._internal_subs[channel].append(callback)

        def unsub():
            subs = self._internal_subs.get(channel, [])
            if callback in subs:
                subs.remove(callback)
            if not subs and channel in self._internal_subs:
                del self._internal_subs[channel]

        logger.debug("Internal subscription to %s", channel)
        return unsub

    # ── Broadcasting ───────────────────────────────────

    async def broadcast_to_channel(self, channel: str, message: dict):
        """Send a message to all connections subscribed to a channel."""
        message["ts"] = time.time()

        async with self._lock:
            conn_ids = list(self._channels.get(channel, set()))

        stale = []
        for conn_id in conn_ids:
            conn = self._conn_by_id.get(conn_id)
            if conn is None:
                stale.append(conn_id)
                continue
            try:
                await conn.websocket.send_json(message)
            except Exception:
                stale.append(conn_id)

        # Clean up stale connections
        if stale:
            async with self._lock:
                for conn_id in stale:
                    if channel in self._channels:
                        self._channels[channel].discard(conn_id)

        # Dispatch to internal (backend) subscribers
        internal_subs = getattr(self, "_internal_subs", {}).get(channel, [])
        for cb in internal_subs:
            try:
                cb(message)
            except Exception as e:
                logger.error("Internal subscriber error on %s: %s", channel, e)

    async def send_to_user(self, user_id: int, message: dict):
        """Send a message to all connections of a specific user."""
        message["ts"] = time.time()

        async with self._lock:
            conns = list(self._connections.get(user_id, []))

        for conn in conns:
            try:
                await conn.websocket.send_json(message)
            except Exception:
                pass

    # ── Message handling ───────────────────────────────

    async def handle_message(self, websocket: WebSocket, raw: str):
        """Process an incoming WebSocket message."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await self._send(websocket, {"type": "error", "message": "Invalid JSON"})
            return

        msg_type = msg.get("type")

        if msg_type == "subscribe":
            channel = msg.get("channel", "")
            if channel:
                await self.subscribe(websocket, channel)
            else:
                await self._send(websocket, {"type": "error", "message": "Missing channel"})

        elif msg_type == "unsubscribe":
            channel = msg.get("channel", "")
            if channel:
                await self.unsubscribe(websocket, channel)

        elif msg_type == "pong":
            conn_id = id(websocket)
            conn = self._conn_by_id.get(conn_id)
            if conn:
                conn.last_pong = time.time()

        else:
            await self._send(websocket, {"type": "error", "message": f"Unknown type: {msg_type}"})

    # ── Internal helpers ───────────────────────────────

    async def _send(self, websocket: WebSocket, data: dict):
        """Send JSON to a single WebSocket, ignoring failures."""
        try:
            await websocket.send_json(data)
        except Exception:
            pass

    async def _heartbeat_loop(self):
        """Send pings every 30 seconds, disconnect unresponsive clients."""
        while True:
            try:
                await asyncio.sleep(30)

                now = time.time()
                stale_websockets = []

                async with self._lock:
                    for conn_id, conn in list(self._conn_by_id.items()):
                        # If no pong in 60 seconds, mark as stale
                        if now - conn.last_pong > 60:
                            stale_websockets.append(conn.websocket)
                        else:
                            try:
                                await conn.websocket.send_json({"type": "ping"})
                            except Exception:
                                stale_websockets.append(conn.websocket)

                for ws in stale_websockets:
                    logger.info("Disconnecting stale WebSocket")
                    await self.disconnect(ws)
                    try:
                        await ws.close()
                    except Exception:
                        pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat error: %s", e)

    # ── Stats ──────────────────────────────────────────

    def stats(self) -> dict:
        """Get current connection statistics."""
        return {
            "total_connections": len(self._conn_by_id),
            "total_users": len(self._connections),
            "total_channels": len(self._channels),
            "channels": {ch: len(subs) for ch, subs in self._channels.items()},
        }


# Singleton instance
manager = ConnectionManager()
