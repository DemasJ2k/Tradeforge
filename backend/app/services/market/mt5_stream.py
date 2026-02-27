"""
MT5 Tick Streamer.

Background asyncio task that polls MT5 for new ticks and publishes them
to the WebSocket ConnectionManager. One streamer instance per subscribed symbol.

Uses copy_ticks_from() for efficient tick retrieval instead of symbol_info_tick().
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.core.websocket import manager as ws_manager

logger = logging.getLogger(__name__)

# Shared thread pool for MT5 sync calls
_mt5_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mt5-stream")

try:
    import MetaTrader5 as mt5
    _MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    _MT5_AVAILABLE = False


class SymbolStreamer:
    """Streams ticks for a single symbol from MT5."""

    def __init__(self, symbol: str, poll_interval_ms: int = 150):
        self.symbol = symbol
        self.poll_interval = poll_interval_ms / 1000.0
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_tick_time = 0  # Track last processed tick timestamp (ms)

    async def start(self):
        """Start the tick polling loop."""
        if self._task is not None:
            return
        self._running = True
        self._last_tick_time = 0
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Started tick streamer for %s", self.symbol)

    async def stop(self):
        """Stop the tick polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Stopped tick streamer for %s", self.symbol)

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None

    async def _poll_loop(self):
        """Main polling loop — fetch new ticks from MT5 and broadcast."""
        loop = asyncio.get_event_loop()

        # Ensure symbol is visible in MT5
        await loop.run_in_executor(_mt5_pool, mt5.symbol_select, self.symbol, True)

        while self._running:
            try:
                ticks = await loop.run_in_executor(_mt5_pool, self._fetch_ticks)

                if ticks is not None and len(ticks) > 0:
                    for tick in ticks:
                        tick_time_ms = int(tick['time_msc'])

                        # Only process new ticks
                        if tick_time_ms <= self._last_tick_time:
                            continue

                        self._last_tick_time = tick_time_ms

                        # numpy.void records don't support .get() — use try/except
                        try:
                            vol = float(tick['volume_real'])
                        except (ValueError, IndexError, KeyError):
                            try:
                                vol = float(tick['volume'])
                            except (ValueError, IndexError, KeyError):
                                vol = 0.0
                        try:
                            flags = int(tick['flags'])
                        except (ValueError, IndexError, KeyError):
                            flags = 0

                        tick_data = {
                            "symbol": self.symbol,
                            "bid": float(tick['bid']),
                            "ask": float(tick['ask']),
                            "spread": float(tick['ask'] - tick['bid']),
                            "volume": vol,
                            "timestamp": tick_time_ms / 1000.0,
                            "flags": flags,
                        }

                        # Broadcast to WebSocket channel
                        await ws_manager.broadcast_to_channel(
                            f"ticks:{self.symbol}",
                            {"type": "tick", "channel": f"ticks:{self.symbol}", "data": tick_data},
                        )

                        # Also notify aggregators via callback
                        for cb in _tick_callbacks:
                            try:
                                await cb(self.symbol, tick_data)
                            except Exception as e:
                                logger.error("Tick callback error: %s", e)

                await asyncio.sleep(self.poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Tick poll error for %s: %s", self.symbol, e)
                await asyncio.sleep(1)  # Back off on errors

    def _fetch_ticks(self):
        """Synchronous MT5 call — fetch recent ticks."""
        if not _MT5_AVAILABLE:
            return None

        # Fetch ticks from the last 2 seconds to ensure we don't miss any
        from_time = datetime.now(timezone.utc) - timedelta(seconds=2)
        ticks = mt5.copy_ticks_from(self.symbol, from_time, 100, mt5.COPY_TICKS_ALL)
        return ticks


# ── Tick callbacks (for aggregator) ────────────────────

_tick_callbacks: list = []


def on_tick(callback):
    """Register a callback for all ticks: async (symbol, tick_data) -> None."""
    _tick_callbacks.append(callback)


# ── MT5 Tick Streamer Manager ──────────────────────────

class MT5TickStreamer:
    """
    Manages SymbolStreamer instances. Auto-starts streamers when channels
    get subscribers, auto-stops when they lose all subscribers.
    """

    def __init__(self):
        self._streamers: dict[str, SymbolStreamer] = {}
        self._mt5_initialized = False

    async def start(self):
        """Register WebSocket subscription callbacks."""
        ws_manager.on_subscribe(self._on_channel_subscribe)
        ws_manager.on_unsubscribe(self._on_channel_unsubscribe)
        logger.info("MT5TickStreamer registered with WebSocket manager")

    async def stop(self):
        """Stop all active streamers."""
        for streamer in list(self._streamers.values()):
            await streamer.stop()
        self._streamers.clear()

    async def _ensure_mt5(self) -> bool:
        """Ensure MT5 is initialized."""
        if not _MT5_AVAILABLE:
            return False

        if self._mt5_initialized:
            return True

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_mt5_pool, mt5.initialize)
        if result:
            self._mt5_initialized = True
            logger.info("MT5 initialized for tick streaming")
        else:
            logger.warning("MT5 initialization failed for streaming")
        return result or False

    async def _on_channel_subscribe(self, channel: str, first: bool):
        """Called when a WebSocket channel gets its first subscriber."""
        if not first:
            return

        # Only handle tick channels: "ticks:XAUUSD"
        if not channel.startswith("ticks:"):
            return

        symbol = channel.split(":", 1)[1]

        if symbol in self._streamers and self._streamers[symbol].is_running:
            return

        if not await self._ensure_mt5():
            logger.warning("Cannot start streamer for %s — MT5 not available", symbol)
            return

        streamer = SymbolStreamer(symbol)
        self._streamers[symbol] = streamer
        await streamer.start()

    async def _on_channel_unsubscribe(self, channel: str, last: bool):
        """Called when a WebSocket channel loses its last subscriber."""
        if not last:
            return

        if not channel.startswith("ticks:"):
            return

        symbol = channel.split(":", 1)[1]

        # Check if any bar channels still need this symbol
        bar_channels = ws_manager.get_subscribed_channels(f"bars:{symbol}:")
        if bar_channels:
            return  # Bar subscribers still need ticks

        streamer = self._streamers.pop(symbol, None)
        if streamer:
            await streamer.stop()

    def get_active_symbols(self) -> list[str]:
        """Get list of symbols currently being streamed."""
        return [s for s, st in self._streamers.items() if st.is_running]


# Singleton instance
mt5_streamer = MT5TickStreamer()
