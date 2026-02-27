"""
Broker connection manager — singleton that holds active broker adapters.

One adapter per broker per user (for now, single-user = global singleton).
"""

import asyncio
import logging
from typing import Optional

from .base import BrokerAdapter

logger = logging.getLogger(__name__)


class BrokerManager:
    """
    Global broker connection manager.
    Stores active broker adapters keyed by broker name.
    """

    def __init__(self):
        self._adapters: dict[str, BrokerAdapter] = {}
        self._default_broker: Optional[str] = None

    @property
    def active_brokers(self) -> list[str]:
        return list(self._adapters.keys())

    @property
    def default_broker(self) -> Optional[str]:
        return self._default_broker

    def get_adapter(self, broker_name: Optional[str] = None) -> Optional[BrokerAdapter]:
        """Get adapter by name, or the default one."""
        name = broker_name or self._default_broker
        if not name:
            return None
        return self._adapters.get(name)

    async def connect_broker(self, broker_name: str, adapter: BrokerAdapter) -> bool:
        """Connect a broker adapter and store it."""
        success = await adapter.connect()
        if success:
            self._adapters[broker_name] = adapter
            if self._default_broker is None:
                self._default_broker = broker_name
            logger.info("Broker %s connected and registered", broker_name)
        return success

    async def disconnect_broker(self, broker_name: str) -> None:
        """Disconnect and remove a broker adapter."""
        adapter = self._adapters.pop(broker_name, None)
        if adapter:
            await adapter.disconnect()
            if self._default_broker == broker_name:
                self._default_broker = self.active_brokers[0] if self.active_brokers else None
            logger.info("Broker %s disconnected", broker_name)

    async def disconnect_all(self) -> None:
        """Disconnect all brokers."""
        for name in list(self._adapters.keys()):
            await self.disconnect_broker(name)

    async def get_status(self) -> dict:
        """Get connection status for all brokers."""
        status = {}
        for name, adapter in self._adapters.items():
            try:
                connected = await adapter.is_connected()
            except Exception:
                connected = False
            status[name] = {
                "connected": connected,
                "broker_name": adapter.broker_name,
                "is_default": name == self._default_broker,
            }
        return status


# Global singleton
broker_manager = BrokerManager()
