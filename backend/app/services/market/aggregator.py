"""
Tick Aggregator — builds OHLCV bars from incoming ticks.

BarBuilder: Accumulates ticks into a single bar for one timeframe.
TickAggregator: Manages multiple BarBuilders per symbol and routes ticks.
"""

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Optional

from app.core.websocket import manager as ws_manager

logger = logging.getLogger(__name__)

# Timeframe durations in seconds
_TF_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}

SUPPORTED_TIMEFRAMES = list(_TF_SECONDS.keys())


def _bar_start_time(timestamp: float, tf_seconds: int) -> int:
    """Calculate the bar open time for a given tick timestamp and timeframe."""
    return int(timestamp // tf_seconds) * tf_seconds


class BarBuilder:
    """
    Accumulates ticks into OHLCV bars for a single symbol and timeframe.

    Emits:
      - "bar_update" on every tick (live updating current bar)
      - "bar" when a bar closes (complete bar)
    """

    def __init__(self, symbol: str, timeframe: str):
        self.symbol = symbol
        self.timeframe = timeframe
        self.tf_seconds = _TF_SECONDS[timeframe]
        self.channel = f"bars:{symbol}:{timeframe}"

        # Current bar state
        self._bar_open_time: int = 0
        self._open: float = 0
        self._high: float = 0
        self._low: float = 0
        self._close: float = 0
        self._volume: float = 0
        self._tick_count: int = 0

    async def process_tick(self, tick: dict):
        """
        Process a new tick. Price used is the mid price (bid+ask)/2.

        tick: { bid, ask, volume, timestamp }
        """
        bid = tick["bid"]
        ask = tick["ask"]
        price = (bid + ask) / 2.0
        volume = tick.get("volume", 0)
        ts = tick["timestamp"]

        bar_start = _bar_start_time(ts, self.tf_seconds)

        # New bar period — close previous and start new
        if bar_start != self._bar_open_time and self._tick_count > 0:
            # Emit closed bar
            await self._emit_bar()

            # Reset for new bar
            self._bar_open_time = bar_start
            self._open = price
            self._high = price
            self._low = price
            self._close = price
            self._volume = volume
            self._tick_count = 1
        elif self._tick_count == 0:
            # First tick ever
            self._bar_open_time = bar_start
            self._open = price
            self._high = price
            self._low = price
            self._close = price
            self._volume = volume
            self._tick_count = 1
            logger.info("First tick for %s:%s — bar started at %s, price=%.5f",
                        self.symbol, self.timeframe, bar_start, price)
        else:
            # Update current bar
            self._high = max(self._high, price)
            self._low = min(self._low, price)
            self._close = price
            self._volume += volume
            self._tick_count += 1

        # Emit bar update (live updating bar)
        await self._emit_bar_update()

    async def _emit_bar(self):
        """Emit a closed bar to WebSocket."""
        bar_data = {
            "time": self._bar_open_time,
            "open": self._open,
            "high": self._high,
            "low": self._low,
            "close": self._close,
            "volume": self._volume,
        }
        logger.info("CLOSED BAR %s:%s time=%s O=%.2f H=%.2f L=%.2f C=%.2f (%d ticks)",
                    self.symbol, self.timeframe, self._bar_open_time,
                    self._open, self._high, self._low, self._close, self._tick_count)
        await ws_manager.broadcast_to_channel(
            self.channel,
            {"type": "bar", "channel": self.channel, "data": bar_data},
        )

    async def _emit_bar_update(self):
        """Emit a live bar update to WebSocket."""
        bar_data = {
            "time": self._bar_open_time,
            "open": self._open,
            "high": self._high,
            "low": self._low,
            "close": self._close,
            "volume": self._volume,
        }
        await ws_manager.broadcast_to_channel(
            self.channel,
            {"type": "bar_update", "channel": self.channel, "data": bar_data},
        )

    @property
    def current_bar(self) -> Optional[dict]:
        """Get the current incomplete bar, if any."""
        if self._tick_count == 0:
            return None
        return {
            "time": self._bar_open_time,
            "open": self._open,
            "high": self._high,
            "low": self._low,
            "close": self._close,
            "volume": self._volume,
        }


class TickAggregator:
    """
    Manages BarBuilder instances for all subscribed symbol+timeframe combos.

    Listens to tick events from MT5TickStreamer and routes them to the
    appropriate BarBuilders. Auto-creates/removes builders based on WebSocket
    channel subscriptions.
    """

    def __init__(self):
        # (symbol, timeframe) -> BarBuilder
        self._builders: dict[tuple[str, str], BarBuilder] = {}

    async def start(self):
        """Register callbacks for tick events and channel subscriptions."""
        from app.services.market.mt5_stream import on_tick

        on_tick(self._on_tick)
        ws_manager.on_subscribe(self._on_channel_subscribe)
        ws_manager.on_unsubscribe(self._on_channel_unsubscribe)
        logger.info("TickAggregator registered")

    async def _on_tick(self, symbol: str, tick_data: dict):
        """Called for every tick from MT5TickStreamer."""
        # Route to all BarBuilders for this symbol
        builders_hit = 0
        for (sym, tf), builder in list(self._builders.items()):
            if sym == symbol:
                builders_hit += 1
                try:
                    await builder.process_tick(tick_data)
                except Exception as e:
                    logger.error("BarBuilder error %s:%s: %s", sym, tf, e)
        if builders_hit == 0 and self._builders:
            logger.debug("Tick for %s but no matching BarBuilder (builders: %s)",
                        symbol, list(self._builders.keys()))

    async def _on_channel_subscribe(self, channel: str, first: bool):
        """Auto-create BarBuilder when a bars channel gets subscribers."""
        logger.info("TickAggregator._on_channel_subscribe(%s, first=%s)", channel, first)
        if not first:
            return
        if not channel.startswith("bars:"):
            return

        parts = channel.split(":")
        if len(parts) != 3:
            return

        _, symbol, timeframe = parts
        key = (symbol, timeframe)

        if key in self._builders:
            return

        if timeframe not in _TF_SECONDS:
            logger.warning("Unsupported timeframe: %s", timeframe)
            return

        builder = BarBuilder(symbol, timeframe)
        self._builders[key] = builder
        logger.info("Created BarBuilder for %s:%s", symbol, timeframe)

        # Ensure tick streaming is active for this symbol.
        # We check if the MT5 streamer is actually running (not just if there
        # are subscribers — TradeMonitor subscribes internally to tick channels
        # for price monitoring, but that doesn't start the MT5 streamer).
        from app.services.market.mt5_stream import mt5_streamer
        if symbol not in mt5_streamer.get_active_symbols():
            tick_channel = f"ticks:{symbol}"
            logger.info("Starting MT5 tick streamer for %s (needed by BarBuilder)", symbol)
            await mt5_streamer._on_channel_subscribe(tick_channel, True)

    async def _on_channel_unsubscribe(self, channel: str, last: bool):
        """Remove BarBuilder when a bars channel loses all subscribers."""
        if not last:
            return
        if not channel.startswith("bars:"):
            return

        parts = channel.split(":")
        if len(parts) != 3:
            return

        _, symbol, timeframe = parts
        key = (symbol, timeframe)
        self._builders.pop(key, None)
        logger.info("Removed BarBuilder for %s:%s", symbol, timeframe)

    def get_current_bar(self, symbol: str, timeframe: str) -> Optional[dict]:
        """Get the current incomplete bar for a symbol+timeframe."""
        builder = self._builders.get((symbol, timeframe))
        if builder:
            return builder.current_bar
        return None


# Singleton instance
tick_aggregator = TickAggregator()
