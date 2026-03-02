// tradeforge_core/src/event_queue.rs
// ─────────────────────────────────────────────────────────────
// Heap-based priority event queue.
//
// Events are ordered by:
//   1. timestamp_ns (earlier first)
//   2. event_type priority (lower enum value = higher priority)
//   3. sequence number (FIFO tie-break)
//
// This is the single most-called component — millions of push/pop
// operations per optimisation run make it the #1 Rust candidate.
// ─────────────────────────────────────────────────────────────

use std::cmp::Ordering;
use std::collections::BinaryHeap;
use pyo3::prelude::*;

use crate::types::{Bar, EventType};

// ── Internal event entry ──────────────────────────────────────

/// A lightweight event reference stored in the heap.
/// We only need (timestamp, priority, seq, bar_index, symbol_idx)
/// for bars — other event types are indices into external buffers.
#[derive(Clone, Debug)]
pub(crate) struct QueueEntry {
    pub timestamp_ns: i64,
    pub event_type: EventType,
    pub seq: u64,
    /// For BAR events: the bar_index into the bar buffer.
    /// For other events: a generic payload index.
    pub payload_idx: u32,
    pub symbol_idx: u32,
}

impl Eq for QueueEntry {}
impl PartialEq for QueueEntry {
    fn eq(&self, other: &Self) -> bool {
        self.timestamp_ns == other.timestamp_ns
            && self.event_type == other.event_type
            && self.seq == other.seq
    }
}

impl PartialOrd for QueueEntry {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

// BinaryHeap is a max-heap — we reverse the ordering so that
// the *smallest* (earliest timestamp, highest priority) pops first.
impl Ord for QueueEntry {
    fn cmp(&self, other: &Self) -> Ordering {
        // Primary: timestamp ascending (reverse for max-heap)
        other.timestamp_ns.cmp(&self.timestamp_ns)
            .then_with(|| {
                // Secondary: event type ascending (lower = higher priority)
                (other.event_type as u8).cmp(&(self.event_type as u8))
            })
            .then_with(|| {
                // Tertiary: sequence ascending (FIFO)
                other.seq.cmp(&self.seq)
            })
    }
}

// ── Event Queue ───────────────────────────────────────────────

/// Fast priority queue for backtesting events.
///
/// Exposed to Python via PyO3 so bars can be fed from Python and
/// popped from the Rust event loop.
#[pyclass]
pub struct FastEventQueue {
    heap: BinaryHeap<QueueEntry>,
    seq: u64,
}

#[pymethods]
impl FastEventQueue {
    #[new]
    pub fn new() -> Self {
        Self {
            heap: BinaryHeap::with_capacity(65_536),
            seq: 0,
        }
    }

    /// Push a bar event into the queue.
    pub fn push_bar(&mut self, timestamp_ns: i64, bar_index: u32, symbol_idx: u32) {
        let entry = QueueEntry {
            timestamp_ns,
            event_type: EventType::Bar,
            seq: self.seq,
            payload_idx: bar_index,
            symbol_idx,
        };
        self.seq += 1;
        self.heap.push(entry);
    }

    /// Number of events in the queue.
    pub fn __len__(&self) -> usize {
        self.heap.len()
    }

    /// Whether the queue is empty.
    pub fn is_empty(&self) -> bool {
        self.heap.is_empty()
    }

    /// Clear all events.
    pub fn clear(&mut self) {
        self.heap.clear();
        self.seq = 0;
    }
}

impl FastEventQueue {
    /// Pop the highest-priority event (Rust-only — not exposed to Python).
    #[inline(always)]
    pub(crate) fn pop(&mut self) -> Option<QueueEntry> {
        self.heap.pop()
    }

    /// Peek without removing.
    #[inline(always)]
    pub(crate) fn peek(&self) -> Option<&QueueEntry> {
        self.heap.peek()
    }

    /// Push a generic event entry (Rust-only).
    #[inline(always)]
    pub(crate) fn push_entry(&mut self, mut entry: QueueEntry) {
        entry.seq = self.seq;
        self.seq += 1;
        self.heap.push(entry);
    }

    /// Number of entries.
    #[inline(always)]
    pub(crate) fn len(&self) -> usize {
        self.heap.len()
    }
}

// ── Tests ─────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ordering_by_timestamp() {
        let mut q = FastEventQueue::new();
        q.push_bar(200, 1, 0);
        q.push_bar(100, 0, 0);
        q.push_bar(300, 2, 0);

        let e1 = q.pop().unwrap();
        assert_eq!(e1.timestamp_ns, 100);
        let e2 = q.pop().unwrap();
        assert_eq!(e2.timestamp_ns, 200);
        let e3 = q.pop().unwrap();
        assert_eq!(e3.timestamp_ns, 300);
        assert!(q.pop().is_none());
    }

    #[test]
    fn test_ordering_same_timestamp_by_type() {
        let mut q = FastEventQueue::new();
        // Bar event (priority 5)
        q.push_entry(QueueEntry {
            timestamp_ns: 100,
            event_type: EventType::Bar,
            seq: 0,
            payload_idx: 0,
            symbol_idx: 0,
        });
        // Fill event (priority 0) — should come first
        q.push_entry(QueueEntry {
            timestamp_ns: 100,
            event_type: EventType::Fill,
            seq: 0,
            payload_idx: 0,
            symbol_idx: 0,
        });

        let e1 = q.pop().unwrap();
        assert_eq!(e1.event_type, EventType::Fill);
        let e2 = q.pop().unwrap();
        assert_eq!(e2.event_type, EventType::Bar);
    }

    #[test]
    fn test_fifo_same_timestamp_same_type() {
        let mut q = FastEventQueue::new();
        q.push_bar(100, 0, 0); // seq 0
        q.push_bar(100, 1, 1); // seq 1

        let e1 = q.pop().unwrap();
        assert_eq!(e1.payload_idx, 0); // first pushed
        let e2 = q.pop().unwrap();
        assert_eq!(e2.payload_idx, 1); // second pushed
    }
}
