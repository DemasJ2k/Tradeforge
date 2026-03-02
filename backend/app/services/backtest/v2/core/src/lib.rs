// tradeforge_core/src/lib.rs
// ─────────────────────────────────────────────────────────────
// PyO3 module entry point.
//
// Exposes all Rust types and functions to Python as the
// `tradeforge_core` native module.
// ─────────────────────────────────────────────────────────────

mod event_queue;
mod indicators;
mod portfolio;
mod runner;
mod tick_matcher;
mod types;

use pyo3::prelude::*;

use event_queue::FastEventQueue;
use indicators::{
    sma_array, ema_array, atr_array,
    SMA, EMA, ATR, BollingerBands, IndicatorValues,
};
use portfolio::FastPortfolio;
use runner::{BacktestResult, FastRunner};
use types::*;

/// The tradeforge_core Python module.
#[pymodule]
fn tradeforge_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // ── Enums ──────────────────────────────────────────────
    m.add_class::<OrderSide>()?;
    m.add_class::<OrderType>()?;
    m.add_class::<OrderStatus>()?;
    m.add_class::<EventType>()?;
    m.add_class::<PositionSide>()?;

    // ── Data types ─────────────────────────────────────────
    m.add_class::<Bar>()?;
    m.add_class::<RustFill>()?;
    m.add_class::<RustOrder>()?;
    m.add_class::<RustClosedTrade>()?;
    m.add_class::<EngineConfig>()?;
    m.add_class::<SymbolConfig>()?;

    // ── Event queue ────────────────────────────────────────
    m.add_class::<FastEventQueue>()?;

    // ── Portfolio ──────────────────────────────────────────
    m.add_class::<FastPortfolio>()?;

    // ── Runner ─────────────────────────────────────────────
    m.add_class::<FastRunner>()?;
    m.add_class::<BacktestResult>()?;

    // ── Indicators ─────────────────────────────────────────
    m.add_class::<SMA>()?;
    m.add_class::<EMA>()?;
    m.add_class::<ATR>()?;
    m.add_class::<BollingerBands>()?;
    m.add_class::<IndicatorValues>()?;

    // ── Vectorised functions ───────────────────────────────
    m.add_function(wrap_pyfunction!(sma_array, m)?)?;
    m.add_function(wrap_pyfunction!(ema_array, m)?)?;
    m.add_function(wrap_pyfunction!(atr_array, m)?)?;

    Ok(())
}
