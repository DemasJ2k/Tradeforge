"""
Broker connection manager — per-user broker adapter storage.

Each user has their own set of broker connections, keyed by (user_id, broker_name).
This prevents cross-user data leakage in multi-user deployments.
"""

import logging
from typing import Optional

from .base import BrokerAdapter

logger = logging.getLogger(__name__)


class BrokerManager:
    """
    Per-user broker connection manager.
    Stores active broker adapters keyed by (user_id, broker_name).
    """

    def __init__(self):
        # Key: (user_id, broker_name) -> adapter
        self._adapters: dict[tuple[int, str], BrokerAdapter] = {}
        # Per-user default broker
        self._default_broker: dict[int, str] = {}

    @property
    def active_brokers(self) -> list[str]:
        """All unique broker names across all users (for backward compat)."""
        return list(set(name for _, name in self._adapters.keys()))

    @property
    def default_broker(self) -> Optional[str]:
        """Default broker name (first user's default, for backward compat)."""
        if self._default_broker:
            return next(iter(self._default_broker.values()), None)
        return None

    def get_default_broker_for_user(self, user_id: int) -> Optional[str]:
        """Get default broker name for a specific user."""
        return self._default_broker.get(user_id)

    def get_adapter(self, broker_name: Optional[str] = None, user_id: Optional[int] = None) -> Optional[BrokerAdapter]:
        """Get adapter by broker name and user_id.

        Falls back to any matching broker_name if user_id not provided
        (backward compat for agent engine which may not have user context).
        """
        if user_id is not None:
            name = broker_name or self._default_broker.get(user_id)
            if not name:
                return None
            return self._adapters.get((user_id, name))

        # Fallback: search all adapters for this broker name (backward compat)
        logger.warning("get_adapter() called without user_id for broker=%s — "
                        "falling back to first matching adapter (cross-user risk)", broker_name)
        name = broker_name
        if not name:
            # Try the first available default
            if self._default_broker:
                first_uid = next(iter(self._default_broker))
                name = self._default_broker[first_uid]
            if not name:
                return None
        for (uid, bname), adapter in self._adapters.items():
            if bname == name:
                return adapter
        return None

    async def connect_broker(self, broker_name: str, adapter: BrokerAdapter, user_id: int = 0) -> bool:
        """Connect a broker adapter and store it for a specific user."""
        success = await adapter.connect()
        if success:
            self._adapters[(user_id, broker_name)] = adapter
            if user_id not in self._default_broker:
                self._default_broker[user_id] = broker_name
            logger.info("Broker %s connected for user %d", broker_name, user_id)

            # Notify broker price streamer
            try:
                from app.services.market.broker_stream import broker_price_streamer
                await broker_price_streamer.notify_broker_connected(broker_name)
            except Exception as e:
                logger.warning("Failed to notify broker_price_streamer: %s", e)

        return success

    async def disconnect_broker(self, broker_name: str, user_id: int = 0) -> None:
        """Disconnect and remove a broker adapter for a specific user."""
        key = (user_id, broker_name)
        adapter = self._adapters.pop(key, None)
        if adapter:
            await adapter.disconnect()
            if self._default_broker.get(user_id) == broker_name:
                # Find another broker for this user
                user_brokers = [n for (u, n) in self._adapters if u == user_id]
                self._default_broker[user_id] = user_brokers[0] if user_brokers else None
                if not self._default_broker[user_id]:
                    del self._default_broker[user_id]
            logger.info("Broker %s disconnected for user %d", broker_name, user_id)

    async def disconnect_all(self) -> None:
        """Disconnect all brokers for all users."""
        for key in list(self._adapters.keys()):
            user_id, broker_name = key
            await self.disconnect_broker(broker_name, user_id)

    async def get_status(self, user_id: Optional[int] = None) -> dict:
        """Get connection status for a user's brokers (or all if user_id=None)."""
        status = {}
        default = self._default_broker.get(user_id, "") if user_id is not None else ""
        for (uid, name), adapter in self._adapters.items():
            if user_id is not None and uid != user_id:
                continue
            try:
                connected = await adapter.is_connected()
            except Exception:
                connected = False
            status[name] = {
                "connected": connected,
                "broker_name": adapter.broker_name,
                "is_default": name == default,
            }
        return status

    def get_user_adapters(self, user_id: int) -> dict[str, BrokerAdapter]:
        """Get all adapters for a specific user."""
        return {
            name: adapter
            for (uid, name), adapter in self._adapters.items()
            if uid == user_id
        }


# Global singleton
broker_manager = BrokerManager()
