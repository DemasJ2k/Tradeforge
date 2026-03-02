// tradeforge_core/src/tick_matcher.rs
// ─────────────────────────────────────────────────────────────
// Intra-bar tick generation and order matching.
//
// Replaces Python tick_engine.py with a tight Rust loop that:
//   1. Generates a 5-tick OHLC path per bar
//   2. Walks ticks, checking pending orders at each tick
//   3. Applies spread + slippage to compute final fill price
//   4. Detects gap-through fills
//
// This is the innermost hot loop — called for every bar for
// every pending order.  In a multi-symbol parameter sweep
// with bracket orders this can be 10M+ calls.
// ─────────────────────────────────────────────────────────────

use pyo3::prelude::*;

use crate::types::{Bar, EngineConfig, OrderSide, OrderStatus, OrderType, RustFill, RustOrder};

// ── Synthetic tick ────────────────────────────────────────────

#[derive(Clone, Copy, Debug)]
pub(crate) struct Tick {
    pub price: f64,
    pub index: u8,
    pub timestamp_ns: i64,
}

/// Generate the deterministic 5-tick OHLC path:
/// Open→High→Low→Close (bullish) or Open→Low→High→Close (bearish).
#[inline]
pub(crate) fn five_tick_ohlc(bar: &Bar) -> [Tick; 5] {
    let ts = bar.timestamp_ns;
    let bullish = bar.close >= bar.open;

    if bullish {
        // Open → Low → High → Low(mid) → Close
        // Simplified: Open, High, Low, Close, Close
        // Canonical 5-tick: Open → extreme1 → extreme2 → mid → Close
        [
            Tick { price: bar.open,  index: 0, timestamp_ns: ts },
            Tick { price: bar.high,  index: 1, timestamp_ns: ts },
            Tick { price: bar.low,   index: 2, timestamp_ns: ts },
            Tick { price: bar.close, index: 3, timestamp_ns: ts },
            Tick { price: bar.close, index: 4, timestamp_ns: ts },
        ]
    } else {
        // Bearish: Open → Low → High → Close
        [
            Tick { price: bar.open,  index: 0, timestamp_ns: ts },
            Tick { price: bar.low,   index: 1, timestamp_ns: ts },
            Tick { price: bar.high,  index: 2, timestamp_ns: ts },
            Tick { price: bar.close, index: 3, timestamp_ns: ts },
            Tick { price: bar.close, index: 4, timestamp_ns: ts },
        ]
    }
}

// ── Fill price adjustment ─────────────────────────────────────

/// Apply spread + slippage to a raw fill price.
#[inline(always)]
fn adjust_price(
    raw: f64,
    side: OrderSide,
    spread: f64,
    slippage_pct: f64,
    is_maker: bool,
) -> f64 {
    let half_spread = if is_maker { 0.0 } else { spread / 2.0 };
    let slip = raw * slippage_pct;

    match side {
        OrderSide::Buy => (raw + half_spread + slip).max(0.0001),
        OrderSide::Sell => (raw - half_spread - slip).max(0.0001),
    }
}

// ── Gap detection ─────────────────────────────────────────────

#[inline(always)]
fn is_gap(prev_close: f64, curr_open: f64) -> bool {
    if prev_close <= 0.0 {
        return false;
    }
    let ratio = (curr_open - prev_close).abs() / prev_close;
    ratio > 0.001 // 0.1% gap threshold
}

// ── Order Matching ────────────────────────────────────────────

/// Result of matching a single order against a bar's tick path.
#[derive(Clone, Debug)]
pub(crate) struct MatchResult {
    pub order_idx: u32,
    pub fill_price: f64,
    pub raw_price: f64,
    pub is_gap_fill: bool,
    pub tick_index: u8,
    pub timestamp_ns: i64,
}

/// Try to fill a single limit order at a tick.
#[inline]
fn try_limit(order: &RustOrder, tick: &Tick, spread: f64, slippage_pct: f64) -> Option<MatchResult> {
    if order.limit_price <= 0.0 {
        return None;
    }
    let triggered = match order.side {
        OrderSide::Buy => tick.price <= order.limit_price,
        OrderSide::Sell => tick.price >= order.limit_price,
    };
    if !triggered {
        return None;
    }

    // Price improvement OK for limits
    let raw = match order.side {
        OrderSide::Buy => order.limit_price.min(tick.price),
        OrderSide::Sell => order.limit_price.max(tick.price),
    };
    let fill_price = adjust_price(raw, order.side, spread, slippage_pct, true);

    Some(MatchResult {
        order_idx: order.idx,
        fill_price,
        raw_price: raw,
        is_gap_fill: false,
        tick_index: tick.index,
        timestamp_ns: tick.timestamp_ns,
    })
}

/// Try to fill a single stop order at a tick.
#[inline]
fn try_stop(
    order: &RustOrder,
    tick: &Tick,
    bar: &Bar,
    has_gap: bool,
    spread: f64,
    slippage_pct: f64,
) -> Option<MatchResult> {
    if order.stop_price <= 0.0 {
        return None;
    }
    let triggered = match order.side {
        OrderSide::Buy => tick.price >= order.stop_price,
        OrderSide::Sell => tick.price <= order.stop_price,
    };
    if !triggered {
        return None;
    }

    let mut raw = order.stop_price;
    let mut gap_fill = false;

    // Gap-through: fill at open instead of stop
    if has_gap && tick.index == 0 {
        match order.side {
            OrderSide::Buy => {
                if bar.open > order.stop_price {
                    raw = bar.open;
                    gap_fill = true;
                }
            }
            OrderSide::Sell => {
                if bar.open < order.stop_price {
                    raw = bar.open;
                    gap_fill = true;
                }
            }
        }
    }

    let fill_price = adjust_price(raw, order.side, spread, slippage_pct, false);

    Some(MatchResult {
        order_idx: order.idx,
        fill_price,
        raw_price: raw,
        is_gap_fill: gap_fill,
        tick_index: tick.index,
        timestamp_ns: tick.timestamp_ns,
    })
}

/// Try to fill a stop-limit order at a tick.
#[inline]
fn try_stop_limit(
    order: &RustOrder,
    tick: &Tick,
    bar: &Bar,
    has_gap: bool,
    spread: f64,
    slippage_pct: f64,
) -> Option<MatchResult> {
    if order.stop_price <= 0.0 || order.limit_price <= 0.0 {
        return None;
    }
    // Step 1: stop trigger
    let stop_triggered = match order.side {
        OrderSide::Buy => tick.price >= order.stop_price,
        OrderSide::Sell => tick.price <= order.stop_price,
    };
    if !stop_triggered {
        return None;
    }

    // Step 2: limit achievability
    let mut limit_ok = match order.side {
        OrderSide::Buy => tick.price <= order.limit_price,
        OrderSide::Sell => tick.price >= order.limit_price,
    };
    if !limit_ok {
        // Check bar range
        limit_ok = match order.side {
            OrderSide::Buy => bar.low <= order.limit_price,
            OrderSide::Sell => bar.high >= order.limit_price,
        };
    }
    if !limit_ok {
        return None;
    }

    // Gap-through past both stop AND limit → no fill
    let mut gap_fill = false;
    if has_gap && tick.index == 0 {
        match order.side {
            OrderSide::Buy => {
                if bar.open > order.limit_price {
                    return None;
                }
                if bar.open > order.stop_price {
                    gap_fill = true;
                }
            }
            OrderSide::Sell => {
                if bar.open < order.limit_price {
                    return None;
                }
                if bar.open < order.stop_price {
                    gap_fill = true;
                }
            }
        }
    }

    let raw = order.limit_price;
    let fill_price = adjust_price(raw, order.side, spread, slippage_pct, true);

    Some(MatchResult {
        order_idx: order.idx,
        fill_price,
        raw_price: raw,
        is_gap_fill: gap_fill,
        tick_index: tick.index,
        timestamp_ns: tick.timestamp_ns,
    })
}

// ── Public API ────────────────────────────────────────────────

/// Process all pending orders against a bar's tick path.
/// Returns a list of fills (MatchResults).
pub(crate) fn match_orders_against_bar(
    bar: &Bar,
    pending: &[RustOrder],
    prev_close: f64,
    spread: f64,
    slippage_pct: f64,
) -> Vec<MatchResult> {
    if pending.is_empty() {
        return Vec::new();
    }

    let ticks = five_tick_ohlc(bar);
    let gap = is_gap(prev_close, bar.open);

    let mut fills: Vec<MatchResult> = Vec::with_capacity(pending.len());
    let mut filled_mask = vec![false; pending.len()];

    for tick in &ticks {
        for (i, order) in pending.iter().enumerate() {
            if filled_mask[i] {
                continue;
            }

            let result = match order.order_type {
                OrderType::Limit => try_limit(order, tick, spread, slippage_pct),
                OrderType::Stop => try_stop(order, tick, bar, gap, spread, slippage_pct),
                OrderType::StopLimit => try_stop_limit(order, tick, bar, gap, spread, slippage_pct),
                OrderType::Market => None, // markets handled separately
            };

            if let Some(r) = result {
                fills.push(r);
                filled_mask[i] = true;
            }
        }
    }

    fills
}

/// Fill a market order at bar open + adjustments.
#[inline]
pub(crate) fn fill_market_order(
    order: &RustOrder,
    bar: &Bar,
    spread: f64,
    slippage_pct: f64,
) -> MatchResult {
    let raw = bar.open;
    let fill_price = adjust_price(raw, order.side, spread, slippage_pct, false);
    MatchResult {
        order_idx: order.idx,
        fill_price,
        raw_price: raw,
        is_gap_fill: false,
        tick_index: 0,
        timestamp_ns: bar.timestamp_ns,
    }
}

// ── Tests ─────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::*;

    fn bar(o: f64, h: f64, l: f64, c: f64) -> Bar {
        Bar {
            timestamp_ns: 1000,
            symbol_idx: 0,
            bar_index: 5,
            open: o,
            high: h,
            low: l,
            close: c,
            volume: 100.0,
        }
    }

    #[test]
    fn test_five_tick_bullish() {
        let b = bar(100.0, 110.0, 95.0, 105.0);
        let ticks = five_tick_ohlc(&b);
        assert_eq!(ticks[0].price, 100.0); // open
        assert_eq!(ticks[1].price, 110.0); // high
        assert_eq!(ticks[2].price, 95.0);  // low
        assert_eq!(ticks[3].price, 105.0); // close
    }

    #[test]
    fn test_market_fill() {
        let b = bar(100.0, 110.0, 95.0, 105.0);
        let order = RustOrder {
            idx: 0,
            symbol_idx: 0,
            side: OrderSide::Buy,
            order_type: OrderType::Market,
            quantity: 1.0,
            filled_quantity: 0.0,
            limit_price: 0.0,
            stop_price: 0.0,
            status: OrderStatus::Submitted,
            tag: String::new(),
            linked_indices: Vec::new(),
            parent_idx: -1,
        };
        let r = fill_market_order(&order, &b, 0.0, 0.0);
        assert!((r.fill_price - 100.0).abs() < 0.01);
    }

    #[test]
    fn test_limit_buy_fills() {
        let b = bar(100.0, 110.0, 95.0, 105.0);
        let order = RustOrder {
            idx: 0,
            symbol_idx: 0,
            side: OrderSide::Buy,
            order_type: OrderType::Limit,
            quantity: 1.0,
            filled_quantity: 0.0,
            limit_price: 97.0,
            stop_price: 0.0,
            status: OrderStatus::Submitted,
            tag: String::new(),
            linked_indices: Vec::new(),
            parent_idx: -1,
        };
        let fills = match_orders_against_bar(&b, &[order], 99.0, 0.0, 0.0);
        assert_eq!(fills.len(), 1);
        // Should fill at low tick (95.0) at better price
        assert!(fills[0].fill_price <= 97.0);
    }

    #[test]
    fn test_stop_buy_fills() {
        let b = bar(100.0, 110.0, 95.0, 105.0);
        let order = RustOrder {
            idx: 0,
            symbol_idx: 0,
            side: OrderSide::Buy,
            order_type: OrderType::Stop,
            quantity: 1.0,
            filled_quantity: 0.0,
            limit_price: 0.0,
            stop_price: 108.0,
            status: OrderStatus::Submitted,
            tag: String::new(),
            linked_indices: Vec::new(),
            parent_idx: -1,
        };
        let fills = match_orders_against_bar(&b, &[order], 99.0, 0.0, 0.0);
        assert_eq!(fills.len(), 1);
        assert!((fills[0].fill_price - 108.0).abs() < 0.01);
    }
}
