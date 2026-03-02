// tradeforge_core/src/types.rs
// ─────────────────────────────────────────────────────────────
// Shared types mirroring the Python V2 engine data model.
// These are the Rust-native counterparts passed across the FFI
// boundary via PyO3 into / out of Python.
// ─────────────────────────────────────────────────────────────

use pyo3::prelude::*;

// ── Enums ──────────────────────────────────────────────────────

#[pyclass(eq, eq_int)]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum OrderSide {
    Buy = 0,
    Sell = 1,
}

#[pyclass(eq, eq_int)]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum OrderType {
    Market = 0,
    Limit = 1,
    Stop = 2,
    StopLimit = 3,
}

#[pyclass(eq, eq_int)]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum OrderStatus {
    Pending = 0,
    Submitted = 1,
    PartiallyFilled = 2,
    Filled = 3,
    Cancelled = 4,
    Rejected = 5,
    Expired = 6,
}

#[pyclass(eq, eq_int)]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum EventType {
    Fill = 0,
    Cancel = 1,
    Order = 2,
    Signal = 3,
    Tick = 4,
    Bar = 5,
    Timer = 6,
}

#[pyclass(eq, eq_int)]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum PositionSide {
    Flat = 0,
    Long = 1,
    Short = 2,
}

// ── Bar ────────────────────────────────────────────────────────

/// OHLCV bar — the primary market-data struct fed into the engine.
#[pyclass]
#[derive(Clone, Debug)]
pub struct Bar {
    #[pyo3(get)]
    pub timestamp_ns: i64,
    #[pyo3(get)]
    pub symbol_idx: u32,   // index into the symbol table (not a string — fast)
    #[pyo3(get)]
    pub bar_index: u32,
    #[pyo3(get)]
    pub open: f64,
    #[pyo3(get)]
    pub high: f64,
    #[pyo3(get)]
    pub low: f64,
    #[pyo3(get)]
    pub close: f64,
    #[pyo3(get)]
    pub volume: f64,
}

#[pymethods]
impl Bar {
    #[new]
    #[pyo3(signature = (timestamp_ns, symbol_idx, bar_index, open, high, low, close, volume))]
    pub fn new(
        timestamp_ns: i64,
        symbol_idx: u32,
        bar_index: u32,
        open: f64,
        high: f64,
        low: f64,
        close: f64,
        volume: f64,
    ) -> Self {
        Self { timestamp_ns, symbol_idx, bar_index, open, high, low, close, volume }
    }
}

// ── Fill ───────────────────────────────────────────────────────

/// A single execution fill.
#[pyclass]
#[derive(Clone, Debug)]
pub struct RustFill {
    #[pyo3(get)]
    pub order_idx: u32,
    #[pyo3(get)]
    pub symbol_idx: u32,
    #[pyo3(get)]
    pub side: OrderSide,
    #[pyo3(get)]
    pub quantity: f64,
    #[pyo3(get)]
    pub price: f64,
    #[pyo3(get)]
    pub commission: f64,
    #[pyo3(get)]
    pub slippage: f64,
    #[pyo3(get)]
    pub timestamp_ns: i64,
    #[pyo3(get)]
    pub bar_index: u32,
    #[pyo3(get)]
    pub is_gap_fill: bool,
}

// ── Order (Rust-side lightweight copy) ─────────────────────────

/// Compact order representation for in-engine matching.
/// The full Order object lives in Python; this is the fast copy.
#[pyclass]
#[derive(Clone, Debug)]
pub struct RustOrder {
    #[pyo3(get)]
    pub idx: u32,
    #[pyo3(get)]
    pub symbol_idx: u32,
    #[pyo3(get)]
    pub side: OrderSide,
    #[pyo3(get)]
    pub order_type: OrderType,
    #[pyo3(get)]
    pub quantity: f64,
    #[pyo3(get)]
    pub filled_quantity: f64,
    #[pyo3(get)]
    pub limit_price: f64,
    #[pyo3(get)]
    pub stop_price: f64,
    #[pyo3(get)]
    pub status: OrderStatus,
    #[pyo3(get)]
    pub tag: String,
    // Linked order indices (OCO group)
    #[pyo3(get)]
    pub linked_indices: Vec<u32>,
    #[pyo3(get)]
    pub parent_idx: i32,  // -1 = no parent
}

#[pymethods]
impl RustOrder {
    #[new]
    #[pyo3(signature = (idx, symbol_idx, side, order_type, quantity, limit_price=0.0, stop_price=0.0, tag=String::new()))]
    pub fn new(
        idx: u32,
        symbol_idx: u32,
        side: OrderSide,
        order_type: OrderType,
        quantity: f64,
        limit_price: f64,
        stop_price: f64,
        tag: String,
    ) -> Self {
        Self {
            idx,
            symbol_idx,
            side,
            order_type,
            quantity,
            filled_quantity: 0.0,
            limit_price,
            stop_price,
            status: OrderStatus::Pending,
            tag,
            linked_indices: Vec::new(),
            parent_idx: -1,
        }
    }

    #[getter]
    pub fn remaining_quantity(&self) -> f64 {
        self.quantity - self.filled_quantity
    }

    #[getter]
    pub fn is_active(&self) -> bool {
        matches!(
            self.status,
            OrderStatus::Pending | OrderStatus::Submitted | OrderStatus::PartiallyFilled
        )
    }
}

// ── Closed Trade ──────────────────────────────────────────────

/// A completed round-trip trade.
#[pyclass]
#[derive(Clone, Debug)]
pub struct RustClosedTrade {
    #[pyo3(get)]
    pub symbol_idx: u32,
    #[pyo3(get)]
    pub side: OrderSide,   // entry side
    #[pyo3(get)]
    pub quantity: f64,
    #[pyo3(get)]
    pub entry_price: f64,
    #[pyo3(get)]
    pub exit_price: f64,
    #[pyo3(get)]
    pub pnl: f64,
    #[pyo3(get)]
    pub pnl_pct: f64,
    #[pyo3(get)]
    pub commission: f64,
    #[pyo3(get)]
    pub slippage: f64,
    #[pyo3(get)]
    pub entry_bar: u32,
    #[pyo3(get)]
    pub exit_bar: u32,
    #[pyo3(get)]
    pub duration_bars: u32,
}

// ── Config ────────────────────────────────────────────────────

/// Engine configuration passed once at init.
#[pyclass]
#[derive(Clone, Debug)]
pub struct EngineConfig {
    #[pyo3(get, set)]
    pub initial_cash: f64,
    #[pyo3(get, set)]
    pub commission_per_lot: f64,
    #[pyo3(get, set)]
    pub commission_pct: f64,
    #[pyo3(get, set)]
    pub spread: f64,
    #[pyo3(get, set)]
    pub slippage_pct: f64,
    #[pyo3(get, set)]
    pub default_margin_rate: f64,
    #[pyo3(get, set)]
    pub max_drawdown_pct: f64,     // 0 = no halt
    #[pyo3(get, set)]
    pub max_positions: u32,        // 0 = unlimited
    #[pyo3(get, set)]
    pub exclusive_orders: bool,
    #[pyo3(get, set)]
    pub warm_up_bars: u32,
    #[pyo3(get, set)]
    pub bars_per_day: f64,
}

#[pymethods]
impl EngineConfig {
    #[new]
    #[pyo3(signature = (
        initial_cash = 10_000.0,
        commission_per_lot = 0.0,
        commission_pct = 0.0,
        spread = 0.0,
        slippage_pct = 0.0,
        default_margin_rate = 0.01,
        max_drawdown_pct = 0.0,
        max_positions = 0,
        exclusive_orders = false,
        warm_up_bars = 0,
        bars_per_day = 1.0,
    ))]
    pub fn new(
        initial_cash: f64,
        commission_per_lot: f64,
        commission_pct: f64,
        spread: f64,
        slippage_pct: f64,
        default_margin_rate: f64,
        max_drawdown_pct: f64,
        max_positions: u32,
        exclusive_orders: bool,
        warm_up_bars: u32,
        bars_per_day: f64,
    ) -> Self {
        Self {
            initial_cash,
            commission_per_lot,
            commission_pct,
            spread,
            slippage_pct,
            default_margin_rate,
            max_drawdown_pct,
            max_positions,
            exclusive_orders,
            warm_up_bars,
            bars_per_day,
        }
    }
}

// ── Per-symbol config ──────────────────────────────────────────

#[pyclass]
#[derive(Clone, Debug)]
pub struct SymbolConfig {
    #[pyo3(get)]
    pub symbol_idx: u32,
    #[pyo3(get)]
    pub name: String,
    #[pyo3(get)]
    pub point_value: f64,
    #[pyo3(get)]
    pub margin_rate: f64,
    #[pyo3(get)]
    pub spread: f64,
}

#[pymethods]
impl SymbolConfig {
    #[new]
    #[pyo3(signature = (symbol_idx, name, point_value = 1.0, margin_rate = 0.01, spread = 0.0))]
    pub fn new(symbol_idx: u32, name: String, point_value: f64, margin_rate: f64, spread: f64) -> Self {
        Self { symbol_idx, name, point_value, margin_rate, spread }
    }
}
