"""
Event types for the V2 backtesting engine.

All events flow through the EventQueue and are dispatched by the Runner.
Events are ordered by timestamp_ns (nanosecond precision) in a heap.

Event hierarchy:
  Event (base)
  ├── BarEvent        — new OHLCV bar available for a symbol
  ├── TickEvent       — new tick (bid/ask) available for a symbol
  ├── SignalEvent     — strategy generated a trade signal
  ├── OrderEvent      — order submitted to execution engine
  ├── FillEvent       — order fill (full or partial)
  ├── CancelEvent     — order cancelled
  └── TimerEvent      — scheduled callback (e.g., end-of-day, rebalance)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Optional


class EventType(IntEnum):
    """Event type identifiers, ordered by processing priority.

    Lower value = higher priority when timestamps are equal.
    Fill events process before new bar events to ensure position state
    is up to date before the strategy sees the next bar.
    """
    FILL = 0
    CANCEL = 1
    ORDER = 2
    SIGNAL = 3
    TICK = 4
    BAR = 5
    TIMER = 6


@dataclass(slots=True)
class Event:
    """Base event. All events carry a nanosecond timestamp and type."""
    timestamp_ns: int
    event_type: EventType
    # Monotonic sequence number to break ties in the queue.
    # Assigned by EventQueue on push.
    _seq: int = field(default=0, repr=False, compare=False)

    def __lt__(self, other: Event) -> bool:
        """Comparison for heap ordering: timestamp first, then priority, then seq."""
        if self.timestamp_ns != other.timestamp_ns:
            return self.timestamp_ns < other.timestamp_ns
        if self.event_type != other.event_type:
            return self.event_type < other.event_type
        return self._seq < other._seq


# ── Market Data Events ──────────────────────────────────────────────


@dataclass(slots=True)
class BarEvent(Event):
    """A new OHLCV bar is available for a symbol."""
    symbol: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    bar_index: int = 0

    def __post_init__(self):
        self.event_type = EventType.BAR


@dataclass(slots=True)
class TickEvent(Event):
    """A new tick (bid/ask or last price) is available for a symbol."""
    symbol: str = ""
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    volume: float = 0.0
    tick_index: int = 0

    def __post_init__(self):
        self.event_type = EventType.TICK


# ── Strategy Events ─────────────────────────────────────────────────


@dataclass(slots=True)
class SignalEvent(Event):
    """Strategy generated a trade signal."""
    symbol: str = ""
    direction: str = ""      # "long" or "short"
    strength: float = 1.0    # signal confidence 0..1
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        self.event_type = EventType.SIGNAL


# ── Order Events ────────────────────────────────────────────────────


@dataclass(slots=True)
class OrderEvent(Event):
    """An order has been submitted to the execution engine."""
    order_id: str = ""
    symbol: str = ""
    side: str = ""           # "BUY" or "SELL"
    order_type: str = ""     # "MARKET", "LIMIT", "STOP", "STOP_LIMIT"
    quantity: float = 0.0
    limit_price: float = 0.0
    stop_price: float = 0.0
    time_in_force: str = "GTC"  # GTC, GTD, IOC, FOK, DAY
    linked_orders: list[str] = field(default_factory=list)  # OCO bracket IDs

    def __post_init__(self):
        self.event_type = EventType.ORDER


@dataclass(slots=True)
class FillEvent(Event):
    """An order has been filled (fully or partially)."""
    order_id: str = ""
    fill_id: str = ""
    symbol: str = ""
    side: str = ""           # "BUY" or "SELL"
    quantity: float = 0.0
    price: float = 0.0
    commission: float = 0.0
    slippage: float = 0.0

    def __post_init__(self):
        self.event_type = EventType.FILL


@dataclass(slots=True)
class CancelEvent(Event):
    """An order has been cancelled."""
    order_id: str = ""
    reason: str = ""

    def __post_init__(self):
        self.event_type = EventType.CANCEL


# ── Utility Events ──────────────────────────────────────────────────


@dataclass(slots=True)
class TimerEvent(Event):
    """A scheduled timer callback (e.g., end-of-day settlement, rebalance)."""
    timer_name: str = ""
    payload: Any = None

    def __post_init__(self):
        self.event_type = EventType.TIMER


# ── Helpers ─────────────────────────────────────────────────────────


def timestamp_ns_from_unix(unix_ts: float) -> int:
    """Convert a Unix timestamp (seconds, float) to nanoseconds (int)."""
    return int(unix_ts * 1_000_000_000)


def unix_from_timestamp_ns(ts_ns: int) -> float:
    """Convert nanoseconds back to Unix seconds float."""
    return ts_ns / 1_000_000_000


def now_ns() -> int:
    """Current time in nanoseconds (for live mode)."""
    return int(time.time() * 1_000_000_000)
