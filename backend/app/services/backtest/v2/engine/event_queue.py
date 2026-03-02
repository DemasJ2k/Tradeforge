"""
Priority event queue for the V2 backtesting engine.

Heap-based queue ordered by:
  1. timestamp_ns (nanosecond precision — earlier first)
  2. event_type priority (lower = higher priority at same timestamp)
  3. sequence number (FIFO tie-break for identical timestamp + type)

This ensures deterministic event ordering:
  - Fills process before new bars (so positions are up-to-date)
  - Cancels process before new orders
  - At the same timestamp, events are processed in insertion order
"""

from __future__ import annotations

import heapq
from typing import Optional

from app.services.backtest.v2.engine.events import Event


class EventQueue:
    """
    Heap-based priority queue for events.

    Thread-safe is NOT required for backtesting (single-threaded).
    If needed for live trading, wrap with a Lock.
    """

    def __init__(self):
        self._heap: list[Event] = []
        self._seq: int = 0

    def push(self, event: Event) -> None:
        """Add an event to the queue. Assigns a monotonic sequence number."""
        event._seq = self._seq
        self._seq += 1
        heapq.heappush(self._heap, event)

    def push_batch(self, events: list[Event]) -> None:
        """Add multiple events at once (slightly more efficient than individual pushes)."""
        for event in events:
            self.push(event)

    def pop(self) -> Optional[Event]:
        """Remove and return the highest-priority event, or None if empty."""
        if self._heap:
            return heapq.heappop(self._heap)
        return None

    def peek(self) -> Optional[Event]:
        """Look at the next event without removing it."""
        if self._heap:
            return self._heap[0]
        return None

    @property
    def is_empty(self) -> bool:
        return len(self._heap) == 0

    def __len__(self) -> int:
        return len(self._heap)

    def __bool__(self) -> bool:
        return not self.is_empty

    def clear(self) -> None:
        """Remove all events from the queue."""
        self._heap.clear()
        self._seq = 0

    def drain(self, max_events: int = -1) -> list[Event]:
        """Pop up to max_events (or all if -1). Returns list in priority order."""
        if max_events < 0:
            result = []
            while self._heap:
                result.append(heapq.heappop(self._heap))
            return result
        else:
            result = []
            for _ in range(max_events):
                if not self._heap:
                    break
                result.append(heapq.heappop(self._heap))
            return result
