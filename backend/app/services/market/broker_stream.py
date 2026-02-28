"""
Broker Price Streamer.

Polls connected non-MT5 brokers (Oanda, Coinbase, Tradovate, etc.) for live
prices and broadcasts them to the WebSocket + TickAggregator pipeline.

This gives non-MT5 brokers near-real-time chart updates (~1-2 seconds) using
the same bar_update/tick pathways as the MT5 streamer, without needing any
frontend changes.

Architecture:
  BrokerPricePoller      — polls one symbol via adapter.get_price() every N seconds
  BrokerPriceStreamer    — manages pollers, auto-creates on WebSocket subscription
"""

import asyncio
import logging
import time
from typing import Optional

from app.core.websocket import manager as ws_manager

logger = logging.getLogger(__name__)

# Poll interval (seconds) for each broker type
_POLL_INTERVALS: dict[str, float] = {
    "oanda": 1.0,
    "coinbase": 2.0,
    "tradovate": 1.5,
}
_DEFAULT_POLL_INTERVAL = 2.0


class BrokerPricePoller:
    """
    Polls a single symbol via the broker adapter and broadcasts ticks to:
      - WebSocket channel:  ticks:{symbol}
      - TickAggregator callbacks (via mt5_stream._tick_callbacks)
    """

    def __init__(self, symbol: str, broker_name: str, poll_interval: float = 1.0):
        self.symbol = symbol
        self.broker_name = broker_name
        self.poll_interval = poll_interval
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._consecutive_errors = 0

    async def start(self):
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("BrokerPricePoller started: %s/%s (%.1fs)", self.broker_name, self.symbol, self.poll_interval)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("BrokerPricePoller stopped: %s/%s", self.broker_name, self.symbol)

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None

    async def _poll_loop(self):
        from app.services.broker.manager import broker_manager
        from app.services.market.mt5_stream import _tick_callbacks

        while self._running:
            try:
                adapter = broker_manager.get_adapter(self.broker_name)
                if not adapter:
                    await asyncio.sleep(5.0)
                    continue

                tick = await adapter.get_price(self.symbol)

                # Normalize timestamp
                ts = (
                    tick.timestamp.timestamp()
                    if hasattr(tick.timestamp, "timestamp")
                    else float(tick.timestamp) if tick.timestamp
                    else time.time()
                )

                tick_data = {
                    "symbol": self.symbol,
                    "bid": float(tick.bid),
                    "ask": float(tick.ask),
                    "spread": float(tick.ask - tick.bid),
                    "volume": 1.0,       # Brokers don't always give tick volume
                    "timestamp": ts,
                    "flags": 0,
                    "broker": self.broker_name,
                }

                # Broadcast to ticks WebSocket channel (for toolbar display)
                await ws_manager.broadcast_to_channel(
                    f"ticks:{self.symbol}",
                    {
                        "type": "tick",
                        "channel": f"ticks:{self.symbol}",
                        "data": tick_data,
                    },
                )

                # Notify TickAggregator callbacks (builds OHLCV bars → bar_update events)
                for cb in _tick_callbacks:
                    try:
                        await cb(self.symbol, tick_data)
                    except Exception as e:
                        logger.error("TickCallback error for %s/%s: %s", self.broker_name, self.symbol, e)

                self._consecutive_errors = 0

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._consecutive_errors += 1
                backoff = min(30.0, 2.0 * self._consecutive_errors)
                logger.warning(
                    "BrokerPricePoller error #%d for %s/%s: %s (retry in %.0fs)",
                    self._consecutive_errors, self.broker_name, self.symbol, e, backoff,
                )
                await asyncio.sleep(backoff)
                continue

            await asyncio.sleep(self.poll_interval)


class BrokerPriceStreamer:
    """
    Manages BrokerPricePoller instances.

    Auto-starts a poller when:
      - A client subscribes to ticks:{symbol}
      - MT5 is NOT already streaming that symbol

    Auto-stops when the channel loses all subscribers.
    """

    def __init__(self):
        self._pollers: dict[str, BrokerPricePoller] = {}

    async def start(self):
        ws_manager.on_subscribe(self._on_channel_subscribe)
        ws_manager.on_unsubscribe(self._on_channel_unsubscribe)
        logger.info("BrokerPriceStreamer registered with WebSocket manager")

    async def stop(self):
        for poller in list(self._pollers.values()):
            await poller.stop()
        self._pollers.clear()
        logger.info("BrokerPriceStreamer stopped")

    async def _on_channel_subscribe(self, channel: str, first: bool):
        if not first:
            return
        if not channel.startswith("ticks:"):
            return

        symbol = channel.split(":", 1)[1]

        # If MT5 streamer is already handling this symbol, skip
        try:
            from app.services.market.mt5_stream import mt5_streamer, _MT5_AVAILABLE
            if _MT5_AVAILABLE and symbol in mt5_streamer.get_active_symbols():
                logger.debug("BrokerPriceStreamer: MT5 already streaming %s, skipping", symbol)
                return
        except Exception:
            pass

        # If already polling, skip
        if symbol in self._pollers and self._pollers[symbol].is_running:
            return

        # Find a connected non-MT5 broker
        from app.services.broker.manager import broker_manager
        broker_name = self._pick_broker(broker_manager)
        if not broker_name:
            logger.debug("BrokerPriceStreamer: no non-MT5 broker connected for %s", symbol)
            return

        poll_interval = _POLL_INTERVALS.get(broker_name, _DEFAULT_POLL_INTERVAL)
        poller = BrokerPricePoller(symbol, broker_name, poll_interval=poll_interval)
        self._pollers[symbol] = poller
        await poller.start()

    async def _on_channel_unsubscribe(self, channel: str, last: bool):
        if not last:
            return
        if not channel.startswith("ticks:"):
            return

        symbol = channel.split(":", 1)[1]
        poller = self._pollers.pop(symbol, None)
        if poller:
            await poller.stop()

    @staticmethod
    def _pick_broker(broker_manager) -> Optional[str]:
        """Pick the best available non-MT5 broker."""
        # Prefer non-MT5 brokers in priority order
        preferred = ["oanda", "coinbase", "tradovate"]
        for name in preferred:
            if broker_manager.get_adapter(name):
                return name
        # Fallback: any non-MT5 broker
        for name in broker_manager.active_brokers:
            if name != "mt5":
                return name
        return None

    def get_active_symbols(self) -> list[str]:
        return [s for s, p in self._pollers.items() if p.is_running]


# Singleton instance
broker_price_streamer = BrokerPriceStreamer()
