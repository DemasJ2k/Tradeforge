// tradeforge_core/src/runner.rs
// ─────────────────────────────────────────────────────────────
// Fast event-loop runner that executes the full backtest in Rust,
// calling back into Python only for strategy.on_bar() / on_fill().
//
// The main loop lives entirely in Rust:
//   1. Pop bar event from the queue
//   2. Update last price
//   3. Match pending limit/stop orders against tick path
//   4. Execute fills → update portfolio
//   5. Call Python strategy.on_bar(bar_dict) → get back orders
//   6. Submit new orders (market orders fill immediately)
//   7. Snapshot equity
//   8. Check drawdown halt
//
// Strategy callbacks cross the FFI boundary, but all the heavy
// numeric work (queue, matching, fills, equity) stays in Rust.
// ─────────────────────────────────────────────────────────────

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

use crate::event_queue::FastEventQueue;
use crate::indicators::IndicatorSet;
use crate::portfolio::FastPortfolio;
use crate::tick_matcher::{fill_market_order, match_orders_against_bar, MatchResult};
use crate::types::*;

// ── BacktestResult ────────────────────────────────────────────

#[pyclass]
#[derive(Clone, Debug)]
pub struct BacktestResult {
    #[pyo3(get)]
    pub equity_curve: Vec<f64>,
    #[pyo3(get)]
    pub bars_processed: u32,
    #[pyo3(get)]
    pub elapsed_ms: f64,
    #[pyo3(get)]
    pub halted: bool,
    #[pyo3(get)]
    pub halt_reason: String,
    #[pyo3(get)]
    pub n_trades: u32,
    #[pyo3(get)]
    pub n_fills: u32,
}

#[pymethods]
impl BacktestResult {
    /// Get closed trades as list of dicts.
    pub fn get_trades<'py>(&self, py: Python<'py>, portfolio: &FastPortfolio) -> PyResult<Bound<'py, PyList>> {
        let trades = PyList::empty(py);
        for t in &portfolio.closed_trades {
            let d = PyDict::new(py);
            d.set_item("symbol_idx", t.symbol_idx)?;
            d.set_item("side", if t.side == OrderSide::Buy { "long" } else { "short" })?;
            d.set_item("quantity", t.quantity)?;
            d.set_item("entry_price", t.entry_price)?;
            d.set_item("exit_price", t.exit_price)?;
            d.set_item("pnl", t.pnl)?;
            d.set_item("pnl_pct", t.pnl_pct)?;
            d.set_item("commission", t.commission)?;
            d.set_item("slippage", t.slippage)?;
            d.set_item("entry_bar", t.entry_bar)?;
            d.set_item("exit_bar", t.exit_bar)?;
            d.set_item("duration_bars", t.duration_bars)?;
            d.set_item("is_winner", t.pnl > 0.0)?;
            trades.append(d)?;
        }
        Ok(trades)
    }
}

// ── FastRunner ────────────────────────────────────────────────

/// The Rust-native backtest runner.
///
/// Usage from Python:
/// ```python
/// runner = FastRunner(config, symbols, bars_flat)
/// result = runner.run(strategy_callback)
/// ```
#[pyclass]
pub struct FastRunner {
    config: EngineConfig,
    symbols: Vec<SymbolConfig>,
    /// Flat bar array: all bars for all symbols, sorted by timestamp.
    bars: Vec<Bar>,
    /// Pending orders (limit/stop) awaiting fill.
    pending_orders: Vec<RustOrder>,
    /// Order counter for unique indices.
    next_order_idx: u32,
    /// Previous close per symbol (for gap detection).
    prev_close: Vec<f64>,
    /// Indicator sets per symbol.
    indicators: Vec<IndicatorSet>,
}

#[pymethods]
impl FastRunner {
    /// Create a new runner.
    ///
    /// `bars_flat` is a list of Bar objects, pre-sorted by timestamp.
    #[new]
    pub fn new(config: EngineConfig, symbols: Vec<SymbolConfig>, bars_flat: Vec<Bar>) -> Self {
        let n_sym = symbols.len();
        Self {
            config,
            symbols,
            bars: bars_flat,
            pending_orders: Vec::with_capacity(64),
            next_order_idx: 0,
            prev_close: vec![0.0; n_sym],
            indicators: vec![IndicatorSet::empty(); n_sym],
        }
    }

    /// Run the full backtest.
    ///
    /// `strategy_cb` is a Python callable:
    ///     strategy_cb(bar_dict, indicator_vals) -> list[order_dict]
    ///
    /// Each order_dict has keys: side, order_type, quantity, limit_price, stop_price, tag
    ///
    /// Returns (BacktestResult, FastPortfolio).
    pub fn run(
        &mut self,
        py: Python<'_>,
        strategy_cb: PyObject,
    ) -> PyResult<(BacktestResult, FastPortfolio)> {
        let start = std::time::Instant::now();

        let mut portfolio = FastPortfolio::new(self.config.clone(), self.symbols.clone());
        let warm_up = self.config.warm_up_bars;
        let mut bars_processed: u32 = 0;
        let mut halted = false;
        let halt_reason;

        // ── Feed bars into queue ──────────────────────────────
        let mut queue = FastEventQueue::new();
        for bar in &self.bars {
            queue.push_bar(bar.timestamp_ns, bar.bar_index, bar.symbol_idx);
        }

        // ── Main event loop ───────────────────────────────────
        while let Some(entry) = queue.pop() {
            let bar_idx = entry.payload_idx;
            let sym_idx = entry.symbol_idx as usize;

            // Safety: bar_idx must index into self.bars
            let bar = if (bar_idx as usize) < self.bars.len() {
                &self.bars[bar_idx as usize]
            } else {
                continue;
            };

            // Update price
            portfolio.update_price(bar.symbol_idx, bar.close);

            // Skip warm-up
            if bar.bar_index < warm_up {
                if sym_idx < self.prev_close.len() {
                    self.prev_close[sym_idx] = bar.close;
                }
                continue;
            }

            bars_processed += 1;

            // 1. Update indicators
            let ind_vals = if sym_idx < self.indicators.len() {
                self.indicators[sym_idx].update(bar.open, bar.high, bar.low, bar.close)
            } else {
                crate::indicators::IndicatorValues {
                    sma_fast: f64::NAN, sma_slow: f64::NAN,
                    ema_fast: f64::NAN, ema_slow: f64::NAN,
                    atr: f64::NAN,
                    bb_upper: f64::NAN, bb_middle: f64::NAN, bb_lower: f64::NAN,
                }
            };

            // 2. Process pending limit/stop orders
            let prev_cl = if sym_idx < self.prev_close.len() {
                self.prev_close[sym_idx]
            } else {
                0.0
            };
            let spread = if sym_idx < self.symbols.len() {
                self.symbols[sym_idx].spread
            } else {
                self.config.spread
            };

            let pending_for_sym: Vec<RustOrder> = self.pending_orders
                .iter()
                .filter(|o| o.symbol_idx == bar.symbol_idx && o.is_active)
                .cloned()
                .collect();

            if !pending_for_sym.is_empty() {
                let matches = match_orders_against_bar(
                    bar, &pending_for_sym, prev_cl, spread, self.config.slippage_pct,
                );
                for m in &matches {
                    let fill = self.create_fill(m, bar, &portfolio);
                    portfolio.apply_fill(&fill);
                    // Cancel OCO siblings
                    self.cancel_linked(m.order_idx);
                    // Mark filled
                    self.mark_filled(m.order_idx);
                }
            }

            // 3. Call Python strategy callback
            let bar_dict = self.bar_to_pydict(py, bar)?;
            let ind_obj = Py::new(py, ind_vals)?;

            let result = strategy_cb.call(py, (bar_dict, ind_obj), None)?;

            // 4. Process returned orders
            let orders_list = result.downcast_bound::<PyList>(py)?;
            for item in orders_list.iter() {
                let order_dict = item.downcast::<PyDict>()?;
                let order = self.parse_order(py, order_dict, bar)?;

                if order.order_type == OrderType::Market {
                    // Fill immediately
                    let m = fill_market_order(&order, bar, spread, self.config.slippage_pct);
                    let fill = self.create_fill(&m, bar, &portfolio);
                    portfolio.apply_fill(&fill);
                } else {
                    // Add to pending
                    self.pending_orders.push(order);
                }
            }

            // 5. Cleanup filled/cancelled orders
            self.pending_orders.retain(|o| o.is_active);

            // 6. Equity snapshot
            portfolio.snapshot_equity();

            // 7. Drawdown halt check
            if portfolio.is_halted() {
                halted = true;
                break;
            }

            // 8. Track previous close
            if sym_idx < self.prev_close.len() {
                self.prev_close[sym_idx] = bar.close;
            }
        }

        // ── Finalize ──────────────────────────────────────────
        halt_reason = if halted {
            format!("Max drawdown {:.2}% exceeded", self.config.max_drawdown_pct)
        } else {
            String::new()
        };

        // Force close all positions
        let last_bar_idx = self.bars.last().map_or(0, |b| b.bar_index);
        portfolio.force_close_all(last_bar_idx);

        let elapsed = start.elapsed();
        let result = BacktestResult {
            equity_curve: portfolio.equity_curve.clone(),
            bars_processed,
            elapsed_ms: elapsed.as_secs_f64() * 1000.0,
            halted,
            halt_reason,
            n_trades: portfolio.closed_trades.len() as u32,
            n_fills: portfolio.total_fills,
        };

        Ok((result, portfolio))
    }
}

impl FastRunner {
    /// Convert a MatchResult into a RustFill with commission.
    fn create_fill(&self, m: &MatchResult, bar: &Bar, _portfolio: &FastPortfolio) -> RustFill {
        let qty = self.pending_orders
            .iter()
            .find(|o| o.idx == m.order_idx)
            .map(|o| o.remaining_quantity())
            .unwrap_or(1.0);

        let side = self.pending_orders
            .iter()
            .find(|o| o.idx == m.order_idx)
            .map(|o| o.side)
            .unwrap_or(OrderSide::Buy);

        let commission = self.config.commission_per_lot * qty
            + self.config.commission_pct * m.fill_price * qty;

        RustFill {
            order_idx: m.order_idx,
            symbol_idx: bar.symbol_idx,
            side,
            quantity: qty,
            price: m.fill_price,
            commission,
            slippage: (m.fill_price - m.raw_price).abs(),
            timestamp_ns: m.timestamp_ns,
            bar_index: bar.bar_index,
            is_gap_fill: m.is_gap_fill,
        }
    }

    /// Mark an order as filled.
    fn mark_filled(&mut self, order_idx: u32) {
        if let Some(o) = self.pending_orders.iter_mut().find(|o| o.idx == order_idx) {
            o.status = OrderStatus::Filled;
            o.filled_quantity = o.quantity;
        }
    }

    /// Cancel OCO-linked orders.
    fn cancel_linked(&mut self, filled_idx: u32) {
        let linked: Vec<u32> = self.pending_orders
            .iter()
            .find(|o| o.idx == filled_idx)
            .map(|o| o.linked_indices.clone())
            .unwrap_or_default();

        for li in linked {
            if let Some(o) = self.pending_orders.iter_mut().find(|o| o.idx == li) {
                o.status = OrderStatus::Cancelled;
            }
        }
    }

    /// Convert a Python order dict to a RustOrder.
    fn parse_order(&mut self, py: Python<'_>, d: &Bound<'_, PyDict>, bar: &Bar) -> PyResult<RustOrder> {
        let side_str: String = d.get_item("side")?.unwrap().extract()?;
        let side = if side_str == "BUY" || side_str == "buy" {
            OrderSide::Buy
        } else {
            OrderSide::Sell
        };

        let otype_str: String = d.get_item("order_type")?.unwrap().extract()?;
        let order_type = match otype_str.to_uppercase().as_str() {
            "MARKET" => OrderType::Market,
            "LIMIT" => OrderType::Limit,
            "STOP" => OrderType::Stop,
            "STOP_LIMIT" => OrderType::StopLimit,
            _ => OrderType::Market,
        };

        let quantity: f64 = d.get_item("quantity")?.unwrap().extract()?;
        let limit_price: f64 = d.get_item("limit_price")
            .ok().and_then(|v| v.map(|v| v.extract().ok()).flatten())
            .unwrap_or(0.0);
        let stop_price: f64 = d.get_item("stop_price")
            .ok().and_then(|v| v.map(|v| v.extract().ok()).flatten())
            .unwrap_or(0.0);
        let tag: String = d.get_item("tag")
            .ok().and_then(|v| v.map(|v| v.extract().ok()).flatten())
            .unwrap_or_default();

        let idx = self.next_order_idx;
        self.next_order_idx += 1;

        // Check for linked orders (bracket SL/TP)
        let linked_str: Vec<String> = d.get_item("linked_tags")
            .ok().and_then(|v| v.map(|v| v.extract().ok()).flatten())
            .unwrap_or_default();

        let mut order = RustOrder {
            idx,
            symbol_idx: bar.symbol_idx,
            side,
            order_type,
            quantity,
            filled_quantity: 0.0,
            limit_price,
            stop_price,
            status: OrderStatus::Submitted,
            tag,
            linked_indices: Vec::new(),
            parent_idx: -1,
        };

        Ok(order)
    }

    /// Convert a Bar to a Python dict for the strategy callback.
    fn bar_to_pydict<'py>(&self, py: Python<'py>, bar: &Bar) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new(py);
        d.set_item("timestamp_ns", bar.timestamp_ns)?;
        d.set_item("symbol_idx", bar.symbol_idx)?;
        d.set_item("bar_index", bar.bar_index)?;
        d.set_item("open", bar.open)?;
        d.set_item("high", bar.high)?;
        d.set_item("low", bar.low)?;
        d.set_item("close", bar.close)?;
        d.set_item("volume", bar.volume)?;
        if bar.symbol_idx < self.symbols.len() as u32 {
            d.set_item("symbol", &self.symbols[bar.symbol_idx as usize].name)?;
        }
        Ok(d)
    }
}
