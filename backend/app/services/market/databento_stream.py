"""
Databento Live Streamer.

Manages a single Databento Live TCP connection for real-time CME futures data.
Subscribes to symbols when WebSocket channels gain their first subscriber,
converts Databento records to tick format, and broadcasts via the existing
WebSocket infrastructure + TickAggregator callbacks.

Architecture:
  - Singleton DabentoStreamer hooks into ws_manager on_subscribe/on_unsubscribe
  - When ticks:{SYMBOL} channel gains first subscriber, maps to CME symbol
  - Background thread consumes Databento Live TCP stream
  - Ticks are broadcast to ws_manager and fed to _tick_callbacks (bar aggregation)
  - Single connection shared by all ~40 users
"""

import asyncio
import logging
import threading
import time as _time
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# Reuse same symbol map as DabentoProvider
_SYMBOL_MAP: dict[str, tuple[str, str]] = {
    "XAUUSD":  ("GLBX.MDP3", "GC.FUT"),
    "XAGUSD":  ("GLBX.MDP3", "SI.FUT"),
    "US30":    ("GLBX.MDP3", "YM.FUT"),
    "NAS100":  ("GLBX.MDP3", "NQ.FUT"),
    "BTCUSD":  ("GLBX.MDP3", "BTC.FUT"),
    "BTC":     ("GLBX.MDP3", "BTC.FUT"),
    "EURUSD":  ("GLBX.MDP3", "6E.FUT"),
    "ES":      ("GLBX.MDP3", "ES.FUT"),
    "NQ":      ("GLBX.MDP3", "NQ.FUT"),
    "YM":      ("GLBX.MDP3", "YM.FUT"),
    "GC":      ("GLBX.MDP3", "GC.FUT"),
    "SI":      ("GLBX.MDP3", "SI.FUT"),
}

# Reverse map: Databento parent symbol → FlowrexAlgo symbol
_REVERSE_MAP: dict[str, str] = {}
for _tf_sym, (_, _db_sym) in _SYMBOL_MAP.items():
    if _db_sym not in _REVERSE_MAP:
        _REVERSE_MAP[_db_sym] = _tf_sym


class DabentoStreamer:
    """
    Manages Databento live data streaming for CME futures.

    Listens for WebSocket channel subscriptions (ticks:XAUUSD, etc.)
    and starts/stops Databento live subscriptions accordingly.
    One TCP connection serves all 40 users via broadcast.
    """

    def __init__(self):
        self._live_client = None
        self._thread: Optional[threading.Thread] = None
        self._subscribed_symbols: set[str] = set()  # FlowrexAlgo symbol names
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def start(self):
        """Register with WebSocket manager for auto-subscription."""
        if not settings.DATABENTO_API_KEY:
            logger.info("DabentoStreamer: no DATABENTO_API_KEY, skipping")
            return

        from app.core.websocket import manager as ws_manager
        self._loop = asyncio.get_event_loop()
        ws_manager.on_subscribe(self._on_channel_subscribe)
        ws_manager.on_unsubscribe(self._on_channel_unsubscribe)
        logger.info("DabentoStreamer registered with WebSocket manager")

    async def stop(self):
        """Stop the live client and clean up."""
        self._running = False
        if self._live_client:
            try:
                self._live_client.close()
            except Exception:
                pass
            self._live_client = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._subscribed_symbols.clear()
        logger.info("DabentoStreamer stopped")

    async def _on_channel_subscribe(self, channel: str, first: bool):
        """Called when a user subscribes to a WebSocket channel."""
        if not first or not channel.startswith("ticks:"):
            return

        symbol = channel.split(":", 1)[1].upper()
        mapping = _SYMBOL_MAP.get(symbol)
        if not mapping:
            return  # Not a Databento-supported symbol — let broker handle it

        if symbol not in self._subscribed_symbols:
            self._subscribed_symbols.add(symbol)
            logger.info("DabentoStreamer: subscribing to %s → %s", symbol, mapping[1])
            self._restart_live_client()

    async def _on_channel_unsubscribe(self, channel: str, last: bool):
        """Called when last user unsubscribes from a WebSocket channel."""
        if not last or not channel.startswith("ticks:"):
            return

        symbol = channel.split(":", 1)[1].upper()
        self._subscribed_symbols.discard(symbol)
        if not self._subscribed_symbols:
            logger.info("DabentoStreamer: no subscribers left, stopping")
            await self.stop()

    def _restart_live_client(self):
        """(Re)start the Databento live client with current symbol set."""
        if not self._subscribed_symbols or not settings.DATABENTO_API_KEY:
            return

        # Stop existing
        self._running = False
        if self._live_client:
            try:
                self._live_client.close()
            except Exception:
                pass

        # Collect unique Databento symbols and dataset
        db_symbols: set[str] = set()
        dataset: Optional[str] = None
        for tf_sym in self._subscribed_symbols:
            mapping = _SYMBOL_MAP.get(tf_sym)
            if mapping:
                dataset = mapping[0]
                db_symbols.add(mapping[1])

        if not dataset or not db_symbols:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._live_thread,
            args=(dataset, list(db_symbols)),
            daemon=True,
            name="databento-live",
        )
        self._thread.start()

    def _live_thread(self, dataset: str, symbols: list[str]):
        """Background thread consuming Databento Live TCP stream."""
        try:
            import databento as db

            client = db.Live(key=settings.DATABENTO_API_KEY)
            self._live_client = client

            client.subscribe(
                dataset=dataset,
                schema="mbp-1",  # Top-of-book bid/ask
                symbols=symbols,
                stype_in="parent",
            )

            logger.info("DabentoStreamer live thread started: %s", symbols)

            for rec in client:
                if not self._running:
                    break

                # Extract raw symbol from record
                raw_symbol = getattr(rec, "symbol", "") or ""

                # Map back to FlowrexAlgo symbol
                tf_symbol = None
                for db_sym, tf_sym_candidate in _REVERSE_MAP.items():
                    root = db_sym.split(".")[0]  # "GC" from "GC.FUT"
                    if raw_symbol.startswith(root):
                        tf_symbol = tf_sym_candidate
                        break

                if not tf_symbol:
                    continue

                # Extract bid/ask prices
                bid = 0.0
                ask = 0.0
                if hasattr(rec, "levels") and len(rec.levels) > 0:
                    bid = float(rec.levels[0].bid_px)
                    ask = float(rec.levels[0].ask_px)
                    # Databento fixed-point conversion
                    if bid > 1e12:
                        bid /= 1e9
                    if ask > 1e12:
                        ask /= 1e9

                ts = rec.ts_event / 1e9 if hasattr(rec, "ts_event") else _time.time()

                tick_data = {
                    "symbol": tf_symbol,
                    "bid": bid,
                    "ask": ask,
                    "spread": ask - bid,
                    "volume": 1.0,
                    "timestamp": ts,
                    "flags": 0,
                    "broker": "databento",
                }

                # Schedule broadcast on the asyncio event loop
                if self._loop and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._broadcast_tick(tf_symbol, tick_data),
                        self._loop,
                    )

        except Exception as e:
            logger.error("DabentoStreamer live thread error: %s", e)
        finally:
            self._running = False
            logger.info("DabentoStreamer live thread exited")

    async def _broadcast_tick(self, symbol: str, tick_data: dict):
        """Broadcast a tick to WebSocket + TickAggregator callbacks."""
        from app.core.websocket import manager as ws_manager
        from app.services.market.mt5_stream import _tick_callbacks

        await ws_manager.broadcast_to_channel(
            f"ticks:{symbol}",
            {"type": "tick", "channel": f"ticks:{symbol}", "data": tick_data},
        )

        for cb in _tick_callbacks:
            try:
                await cb(symbol, tick_data)
            except Exception as e:
                logger.error("DabentoStreamer tick callback error for %s: %s", symbol, e)


# Singleton
databento_streamer = DabentoStreamer()
