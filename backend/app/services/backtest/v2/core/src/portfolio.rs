// tradeforge_core/src/portfolio.rs
// ─────────────────────────────────────────────────────────────
// Position tracking, PnL calculation, and portfolio mark-to-market.
//
// This is called on every fill and every bar (for equity snapshot),
// making it the second-hottest path after the event queue.
// ─────────────────────────────────────────────────────────────

use pyo3::prelude::*;

use crate::types::{
    EngineConfig, OrderSide, PositionSide, RustClosedTrade, RustFill, SymbolConfig,
};

// ── Position ──────────────────────────────────────────────────

/// A single-symbol position (net).
#[derive(Clone, Debug)]
pub(crate) struct Position {
    pub symbol_idx: u32,
    pub side: PositionSide,
    pub quantity: f64,        // absolute, ≥ 0
    pub avg_entry_price: f64,
    pub realized_pnl: f64,
    pub total_commission: f64,
    pub total_slippage: f64,
    pub first_entry_bar: u32,
    pub point_value: f64,
    pub margin_rate: f64,
}

impl Position {
    pub fn new(symbol_idx: u32, point_value: f64, margin_rate: f64) -> Self {
        Self {
            symbol_idx,
            side: PositionSide::Flat,
            quantity: 0.0,
            avg_entry_price: 0.0,
            realized_pnl: 0.0,
            total_commission: 0.0,
            total_slippage: 0.0,
            first_entry_bar: 0,
            point_value,
            margin_rate,
        }
    }

    #[inline(always)]
    pub fn is_flat(&self) -> bool {
        self.quantity < 1e-10
    }

    #[inline(always)]
    pub fn is_long(&self) -> bool {
        self.side == PositionSide::Long && !self.is_flat()
    }

    #[inline(always)]
    pub fn is_short(&self) -> bool {
        self.side == PositionSide::Short && !self.is_flat()
    }

    #[inline(always)]
    pub fn unrealized_pnl(&self, current_price: f64) -> f64 {
        if self.is_flat() {
            return 0.0;
        }
        let diff = if self.side == PositionSide::Long {
            current_price - self.avg_entry_price
        } else {
            self.avg_entry_price - current_price
        };
        diff * self.quantity * self.point_value
    }

    #[inline(always)]
    pub fn notional(&self) -> f64 {
        self.quantity * self.avg_entry_price * self.point_value
    }

    #[inline(always)]
    pub fn margin_required(&self, price: f64) -> f64 {
        self.quantity * price * self.point_value * self.margin_rate
    }

    /// Apply a fill. Returns Some(ClosedTrade) if position was reduced/closed.
    pub fn apply_fill(&mut self, fill: &RustFill) -> Option<RustClosedTrade> {
        let is_increasing = self.is_increasing(fill.side);

        if self.is_flat() {
            // Opening new position
            self.open(fill);
            return None;
        }

        if is_increasing {
            // Adding to position — update weighted average
            let total_cost =
                self.avg_entry_price * self.quantity + fill.price * fill.quantity;
            self.quantity += fill.quantity;
            self.avg_entry_price = total_cost / self.quantity;
            self.total_commission += fill.commission;
            self.total_slippage += fill.slippage.abs();
            return None;
        }

        // Reducing / closing / flipping
        let close_qty = fill.quantity.min(self.quantity);
        let remaining = fill.quantity - close_qty;

        let closed = self.close_portion(fill, close_qty);

        self.quantity -= close_qty;
        if self.quantity < 1e-10 {
            self.quantity = 0.0;
            self.side = PositionSide::Flat;
            self.avg_entry_price = 0.0;
        }

        // Flip if fill quantity exceeds position
        if remaining > 1e-10 {
            let flip = RustFill {
                order_idx: fill.order_idx,
                symbol_idx: fill.symbol_idx,
                side: fill.side,
                quantity: remaining,
                price: fill.price,
                commission: 0.0,
                slippage: 0.0,
                timestamp_ns: fill.timestamp_ns,
                bar_index: fill.bar_index,
                is_gap_fill: false,
            };
            self.open(&flip);
        }

        Some(closed)
    }

    /// Force-close at a given price.
    pub fn force_close(&mut self, price: f64, bar_index: u32) -> Option<RustClosedTrade> {
        if self.is_flat() {
            return None;
        }
        let exit_side = if self.is_long() {
            OrderSide::Sell
        } else {
            OrderSide::Buy
        };
        let fill = RustFill {
            order_idx: u32::MAX,
            symbol_idx: self.symbol_idx,
            side: exit_side,
            quantity: self.quantity,
            price,
            commission: 0.0,
            slippage: 0.0,
            timestamp_ns: 0,
            bar_index,
            is_gap_fill: false,
        };
        self.apply_fill(&fill)
    }

    // ── helpers ────────────────────────────────────────────────

    #[inline(always)]
    fn is_increasing(&self, fill_side: OrderSide) -> bool {
        if self.is_flat() {
            return true;
        }
        (self.side == PositionSide::Long && fill_side == OrderSide::Buy)
            || (self.side == PositionSide::Short && fill_side == OrderSide::Sell)
    }

    fn open(&mut self, fill: &RustFill) {
        self.side = if fill.side == OrderSide::Buy {
            PositionSide::Long
        } else {
            PositionSide::Short
        };
        self.quantity = fill.quantity;
        self.avg_entry_price = fill.price;
        self.first_entry_bar = fill.bar_index;
        self.total_commission = fill.commission;
        self.total_slippage = fill.slippage.abs();
        self.realized_pnl = 0.0;
    }

    fn close_portion(&mut self, fill: &RustFill, close_qty: f64) -> RustClosedTrade {
        let (pnl_raw, side) = if self.side == PositionSide::Long {
            (
                (fill.price - self.avg_entry_price) * close_qty * self.point_value,
                OrderSide::Buy,
            )
        } else {
            (
                (self.avg_entry_price - fill.price) * close_qty * self.point_value,
                OrderSide::Sell,
            )
        };
        let pnl = pnl_raw - fill.commission;
        self.realized_pnl += pnl;
        self.total_commission += fill.commission;
        self.total_slippage += fill.slippage.abs();

        let entry_notional = self.avg_entry_price * close_qty * self.point_value;
        let pnl_pct = if entry_notional > 0.0 {
            pnl / entry_notional * 100.0
        } else {
            0.0
        };

        RustClosedTrade {
            symbol_idx: self.symbol_idx,
            side,
            quantity: close_qty,
            entry_price: self.avg_entry_price,
            exit_price: fill.price,
            pnl,
            pnl_pct,
            commission: fill.commission,
            slippage: fill.slippage.abs(),
            entry_bar: self.first_entry_bar,
            exit_bar: fill.bar_index,
            duration_bars: fill.bar_index.saturating_sub(self.first_entry_bar),
        }
    }
}

// ── Portfolio ─────────────────────────────────────────────────

/// The central portfolio — manages cash, positions, equity curve.
#[pyclass]
pub struct FastPortfolio {
    pub(crate) config: EngineConfig,
    pub(crate) symbols: Vec<SymbolConfig>,
    pub(crate) positions: Vec<Position>,
    pub(crate) cash: f64,
    pub(crate) equity_curve: Vec<f64>,
    pub(crate) closed_trades: Vec<RustClosedTrade>,
    pub(crate) peak_equity: f64,
    pub(crate) max_dd: f64,
    pub(crate) max_dd_pct: f64,
    pub(crate) total_commission: f64,
    pub(crate) total_slippage: f64,
    pub(crate) total_fills: u32,
    // Last known price per symbol (for M2M)
    pub(crate) last_prices: Vec<f64>,
}

#[pymethods]
impl FastPortfolio {
    #[new]
    pub fn new(config: EngineConfig, symbols: Vec<SymbolConfig>) -> Self {
        let n = symbols.len();
        let cash = config.initial_cash;
        let positions: Vec<Position> = symbols
            .iter()
            .map(|s| Position::new(s.symbol_idx, s.point_value, s.margin_rate))
            .collect();

        Self {
            config,
            symbols,
            positions,
            cash,
            equity_curve: vec![cash],
            closed_trades: Vec::new(),
            peak_equity: cash,
            max_dd: 0.0,
            max_dd_pct: 0.0,
            total_commission: 0.0,
            total_slippage: 0.0,
            total_fills: 0,
            last_prices: vec![0.0; n],
        }
    }

    /// Current cash balance.
    #[getter]
    pub fn cash(&self) -> f64 {
        self.cash
    }

    /// Equity curve as a list of floats.
    #[getter]
    pub fn equity_curve(&self) -> Vec<f64> {
        self.equity_curve.clone()
    }

    /// Number of closed trades.
    #[getter]
    pub fn n_closed_trades(&self) -> usize {
        self.closed_trades.len()
    }

    /// Max drawdown %.
    #[getter]
    pub fn max_drawdown_pct(&self) -> f64 {
        self.max_dd_pct
    }

    /// Get closed trades as Python list.
    pub fn get_closed_trades(&self) -> Vec<RustClosedTrade> {
        self.closed_trades.clone()
    }
}

impl FastPortfolio {
    /// Apply a fill: update position, cash, track costs.
    #[inline]
    pub(crate) fn apply_fill(&mut self, fill: &RustFill) {
        self.total_commission += fill.commission;
        self.total_slippage += fill.slippage.abs();
        self.total_fills += 1;

        let sym_idx = fill.symbol_idx as usize;
        if sym_idx >= self.positions.len() {
            return; // safety
        }

        let closed = self.positions[sym_idx].apply_fill(fill);
        if let Some(ct) = closed {
            self.cash += ct.pnl;
            self.closed_trades.push(ct);
        }
        self.cash -= fill.commission;
    }

    /// Snapshot equity at the current bar.
    /// Updates the equity curve, drawdown tracking, and last_prices.
    #[inline]
    pub(crate) fn snapshot_equity(&mut self) {
        let unrealized: f64 = self
            .positions
            .iter()
            .enumerate()
            .map(|(i, p)| {
                if p.is_flat() || self.last_prices[i] <= 0.0 {
                    0.0
                } else {
                    p.unrealized_pnl(self.last_prices[i])
                }
            })
            .sum();

        let total = self.cash + unrealized;
        self.equity_curve.push(total);

        if total > self.peak_equity {
            self.peak_equity = total;
        }
        let dd = self.peak_equity - total;
        let dd_pct = if self.peak_equity > 0.0 {
            dd / self.peak_equity * 100.0
        } else {
            0.0
        };
        if dd > self.max_dd {
            self.max_dd = dd;
        }
        if dd_pct > self.max_dd_pct {
            self.max_dd_pct = dd_pct;
        }
    }

    /// Update last price for a symbol.
    #[inline(always)]
    pub(crate) fn update_price(&mut self, symbol_idx: u32, price: f64) {
        let idx = symbol_idx as usize;
        if idx < self.last_prices.len() {
            self.last_prices[idx] = price;
        }
    }

    /// Force-close all open positions.
    pub(crate) fn force_close_all(&mut self, bar_index: u32) {
        for i in 0..self.positions.len() {
            let price = self.last_prices[i];
            if price <= 0.0 || self.positions[i].is_flat() {
                continue;
            }
            if let Some(ct) = self.positions[i].force_close(price, bar_index) {
                self.cash += ct.pnl;
                self.closed_trades.push(ct);
            }
        }
    }

    /// Check drawdown halt condition.
    #[inline(always)]
    pub(crate) fn is_halted(&self) -> bool {
        self.config.max_drawdown_pct > 0.0 && self.max_dd_pct >= self.config.max_drawdown_pct
    }

    /// Is the position for a given symbol flat?
    #[inline(always)]
    pub(crate) fn is_flat(&self, symbol_idx: u32) -> bool {
        let idx = symbol_idx as usize;
        idx < self.positions.len() && self.positions[idx].is_flat()
    }

    /// Get position side for a symbol.
    #[inline(always)]
    pub(crate) fn position_side(&self, symbol_idx: u32) -> PositionSide {
        let idx = symbol_idx as usize;
        if idx < self.positions.len() {
            self.positions[idx].side
        } else {
            PositionSide::Flat
        }
    }
}

// ── Tests ─────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::*;

    fn make_config() -> EngineConfig {
        EngineConfig {
            initial_cash: 10000.0,
            commission_per_lot: 0.0,
            commission_pct: 0.0,
            spread: 0.0,
            slippage_pct: 0.0,
            default_margin_rate: 0.01,
            max_drawdown_pct: 0.0,
            max_positions: 0,
            exclusive_orders: false,
            warm_up_bars: 0,
            bars_per_day: 1.0,
        }
    }

    fn make_sym() -> Vec<SymbolConfig> {
        vec![SymbolConfig {
            symbol_idx: 0,
            name: "TEST".into(),
            point_value: 1.0,
            margin_rate: 0.01,
            spread: 0.0,
        }]
    }

    #[test]
    fn test_open_close_position() {
        let mut port = FastPortfolio::new(make_config(), make_sym());

        // Open long
        let entry = RustFill {
            order_idx: 0,
            symbol_idx: 0,
            side: OrderSide::Buy,
            quantity: 1.0,
            price: 100.0,
            commission: 1.0,
            slippage: 0.0,
            timestamp_ns: 0,
            bar_index: 0,
            is_gap_fill: false,
        };
        port.apply_fill(&entry);
        assert!(!port.positions[0].is_flat());
        assert!(port.positions[0].is_long());

        // Close at profit
        let exit = RustFill {
            order_idx: 1,
            symbol_idx: 0,
            side: OrderSide::Sell,
            quantity: 1.0,
            price: 110.0,
            commission: 1.0,
            slippage: 0.0,
            timestamp_ns: 0,
            bar_index: 10,
            is_gap_fill: false,
        };
        port.apply_fill(&exit);
        assert!(port.positions[0].is_flat());
        assert_eq!(port.closed_trades.len(), 1);
        // PnL = (110-100)*1*1 - 1 commission = 9.0
        assert!((port.closed_trades[0].pnl - 9.0).abs() < 0.01);
    }

    #[test]
    fn test_equity_snapshot() {
        let mut port = FastPortfolio::new(make_config(), make_sym());
        port.last_prices[0] = 100.0;
        port.snapshot_equity();
        assert_eq!(port.equity_curve.len(), 2); // initial + snapshot
        assert!((port.equity_curve[1] - 10000.0).abs() < 0.01);
    }
}
