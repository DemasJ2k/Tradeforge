"""
Pure-Python fallback for the Rust core engine.

This module provides identical logic to tradeforge_core (the Rust/PyO3 crate)
but implemented in pure Python.  It is used when the Rust extension is not
compiled or not available on the current platform.

Performance: ~50-100x slower than Rust, but functionally identical.

Every class and function here mirrors the Rust counterpart 1:1 so that
`python_bindings.py` can import from either without changing call sites.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Optional
import heapq


# ════════════════════════════════════════════════════════════════
# Enums — mirror Rust IntEnums
# ════════════════════════════════════════════════════════════════

class OrderSide(IntEnum):
    Buy = 0
    Sell = 1

class OrderType(IntEnum):
    Market = 0
    Limit = 1
    Stop = 2
    StopLimit = 3

class OrderStatus(IntEnum):
    Pending = 0
    Submitted = 1
    PartiallyFilled = 2
    Filled = 3
    Cancelled = 4
    Rejected = 5
    Expired = 6

class EventType(IntEnum):
    Fill = 0
    Cancel = 1
    Order = 2
    Signal = 3
    Tick = 4
    Bar = 5
    Timer = 6

class PositionSide(IntEnum):
    Flat = 0
    Long = 1
    Short = 2


# ════════════════════════════════════════════════════════════════
# Data Types
# ════════════════════════════════════════════════════════════════

@dataclass(slots=True)
class Bar:
    timestamp_ns: int
    symbol_idx: int
    bar_index: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(slots=True)
class RustFill:
    order_idx: int
    symbol_idx: int
    side: OrderSide
    quantity: float
    price: float
    commission: float
    slippage: float
    timestamp_ns: int
    bar_index: int
    is_gap_fill: bool = False


@dataclass(slots=True)
class RustClosedTrade:
    symbol_idx: int
    side: OrderSide
    quantity: float
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float
    commission: float
    slippage: float
    entry_bar: int
    exit_bar: int
    duration_bars: int


class RustOrder:
    __slots__ = (
        "idx", "symbol_idx", "side", "order_type", "quantity",
        "filled_quantity", "limit_price", "stop_price", "status",
        "tag", "linked_indices", "parent_idx",
    )

    def __init__(
        self,
        idx: int,
        symbol_idx: int,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        limit_price: float = 0.0,
        stop_price: float = 0.0,
        tag: str = "",
    ):
        self.idx = idx
        self.symbol_idx = symbol_idx
        self.side = side
        self.order_type = order_type
        self.quantity = quantity
        self.filled_quantity = 0.0
        self.limit_price = limit_price
        self.stop_price = stop_price
        self.status = OrderStatus.Pending
        self.tag = tag
        self.linked_indices: list[int] = []
        self.parent_idx: int = -1

    @property
    def remaining_quantity(self) -> float:
        return self.quantity - self.filled_quantity

    @property
    def is_active(self) -> bool:
        return self.status in (
            OrderStatus.Pending, OrderStatus.Submitted, OrderStatus.PartiallyFilled,
        )


@dataclass
class EngineConfig:
    initial_cash: float = 10_000.0
    commission_per_lot: float = 0.0
    commission_pct: float = 0.0
    spread: float = 0.0
    slippage_pct: float = 0.0
    default_margin_rate: float = 0.01
    max_drawdown_pct: float = 0.0
    max_positions: int = 0
    exclusive_orders: bool = False
    warm_up_bars: int = 0
    bars_per_day: float = 1.0


@dataclass
class SymbolConfig:
    symbol_idx: int
    name: str
    point_value: float = 1.0
    margin_rate: float = 0.01
    spread: float = 0.0


# ════════════════════════════════════════════════════════════════
# Event Queue
# ════════════════════════════════════════════════════════════════

class FastEventQueue:
    def __init__(self):
        self._heap: list[tuple] = []
        self._seq: int = 0

    def push_bar(self, timestamp_ns: int, bar_index: int, symbol_idx: int):
        entry = (timestamp_ns, EventType.Bar, self._seq, bar_index, symbol_idx)
        self._seq += 1
        heapq.heappush(self._heap, entry)

    def pop(self) -> Optional[tuple]:
        if self._heap:
            return heapq.heappop(self._heap)
        return None

    def is_empty(self) -> bool:
        return len(self._heap) == 0

    def len(self) -> int:
        return len(self._heap)

    def __len__(self) -> int:
        return len(self._heap)

    def clear(self):
        self._heap.clear()
        self._seq = 0


# ════════════════════════════════════════════════════════════════
# Indicators
# ════════════════════════════════════════════════════════════════

class SMA:
    __slots__ = ("period", "_buf", "_pos", "_sum", "_count")

    def __init__(self, period: int):
        self.period = period
        self._buf = [0.0] * period
        self._pos = 0
        self._sum = 0.0
        self._count = 0

    def push(self, value: float) -> float:
        if self._count >= self.period:
            self._sum -= self._buf[self._pos]
        self._buf[self._pos] = value
        self._sum += value
        self._pos = (self._pos + 1) % self.period
        self._count += 1
        if self._count >= self.period:
            return self._sum / self.period
        return float("nan")

    @property
    def value(self) -> float:
        if self._count >= self.period:
            return self._sum / self.period
        return float("nan")

    @property
    def ready(self) -> bool:
        return self._count >= self.period

    def reset(self):
        self._buf = [0.0] * self.period
        self._pos = 0
        self._sum = 0.0
        self._count = 0


class EMA:
    __slots__ = ("period", "_alpha", "_value", "_count", "_seed_sum")

    def __init__(self, period: int, smoothing: float = 2.0):
        self.period = period
        self._alpha = smoothing / (period + 1.0)
        self._value = float("nan")
        self._count = 0
        self._seed_sum = 0.0

    def push(self, value: float) -> float:
        self._count += 1
        if self._count < self.period:
            self._seed_sum += value
            self._value = float("nan")
            return float("nan")
        if self._count == self.period:
            self._seed_sum += value
            self._value = self._seed_sum / self.period
            return self._value
        self._value = self._alpha * value + (1.0 - self._alpha) * self._value
        return self._value

    @property
    def value(self) -> float:
        return self._value

    @property
    def ready(self) -> bool:
        return self._count >= self.period

    def reset(self):
        self._value = float("nan")
        self._count = 0
        self._seed_sum = 0.0


class ATR:
    __slots__ = ("period", "_value", "_count", "_prev_close", "_seed_sum")

    def __init__(self, period: int):
        self.period = period
        self._value = float("nan")
        self._count = 0
        self._prev_close = float("nan")
        self._seed_sum = 0.0

    def push(self, high: float, low: float, close: float) -> float:
        if math.isnan(self._prev_close):
            tr = high - low
        else:
            hl = high - low
            hpc = abs(high - self._prev_close)
            lpc = abs(low - self._prev_close)
            tr = max(hl, hpc, lpc)
        self._prev_close = close
        self._count += 1

        if self._count < self.period:
            self._seed_sum += tr
            self._value = float("nan")
            return float("nan")
        if self._count == self.period:
            self._seed_sum += tr
            self._value = self._seed_sum / self.period
            return self._value
        # Wilder smoothing
        self._value = (self._value * (self.period - 1) + tr) / self.period
        return self._value

    @property
    def value(self) -> float:
        return self._value

    @property
    def ready(self) -> bool:
        return self._count >= self.period

    def reset(self):
        self._value = float("nan")
        self._count = 0
        self._prev_close = float("nan")
        self._seed_sum = 0.0


class BollingerBands:
    __slots__ = (
        "period", "k", "_buf", "_pos", "_sum", "_sum_sq",
        "_count", "upper", "middle", "lower",
    )

    def __init__(self, period: int, k: float = 2.0):
        self.period = period
        self.k = k
        self._buf = [0.0] * period
        self._pos = 0
        self._sum = 0.0
        self._sum_sq = 0.0
        self._count = 0
        self.upper = float("nan")
        self.middle = float("nan")
        self.lower = float("nan")

    def push(self, value: float) -> tuple[float, float, float]:
        if self._count >= self.period:
            old = self._buf[self._pos]
            self._sum -= old
            self._sum_sq -= old * old
        self._buf[self._pos] = value
        self._sum += value
        self._sum_sq += value * value
        self._pos = (self._pos + 1) % self.period
        self._count += 1

        if self._count < self.period:
            self.upper = self.middle = self.lower = float("nan")
            return (float("nan"), float("nan"), float("nan"))

        n = self.period
        mean = self._sum / n
        variance = (self._sum_sq / n) - (mean * mean)
        std = math.sqrt(variance) if variance > 0 else 0.0
        self.middle = mean
        self.upper = mean + self.k * std
        self.lower = mean - self.k * std
        return (self.upper, self.middle, self.lower)

    @property
    def ready(self) -> bool:
        return self._count >= self.period

    def reset(self):
        self._buf = [0.0] * self.period
        self._pos = 0
        self._sum = 0.0
        self._sum_sq = 0.0
        self._count = 0
        self.upper = self.middle = self.lower = float("nan")


@dataclass(slots=True)
class IndicatorValues:
    sma_fast: float = float("nan")
    sma_slow: float = float("nan")
    ema_fast: float = float("nan")
    ema_slow: float = float("nan")
    atr: float = float("nan")
    bb_upper: float = float("nan")
    bb_middle: float = float("nan")
    bb_lower: float = float("nan")


def sma_array(values: list[float], period: int) -> list[float]:
    out = [float("nan")] * len(values)
    if period == 0 or not values:
        return out
    ind = SMA(period)
    for i, v in enumerate(values):
        out[i] = ind.push(v)
    return out


def ema_array(values: list[float], period: int, smoothing: float = 2.0) -> list[float]:
    out = [float("nan")] * len(values)
    if period == 0 or not values:
        return out
    ind = EMA(period, smoothing)
    for i, v in enumerate(values):
        out[i] = ind.push(v)
    return out


def atr_array(high: list[float], low: list[float], close: list[float], period: int) -> list[float]:
    n = min(len(high), len(low), len(close))
    out = [float("nan")] * n
    if period == 0 or n == 0:
        return out
    ind = ATR(period)
    for i in range(n):
        out[i] = ind.push(high[i], low[i], close[i])
    return out


# ════════════════════════════════════════════════════════════════
# Position
# ════════════════════════════════════════════════════════════════

class _Position:
    __slots__ = (
        "symbol_idx", "side", "quantity", "avg_entry_price",
        "realized_pnl", "total_commission", "total_slippage",
        "first_entry_bar", "point_value", "margin_rate",
    )

    def __init__(self, symbol_idx: int, point_value: float, margin_rate: float):
        self.symbol_idx = symbol_idx
        self.side = PositionSide.Flat
        self.quantity = 0.0
        self.avg_entry_price = 0.0
        self.realized_pnl = 0.0
        self.total_commission = 0.0
        self.total_slippage = 0.0
        self.first_entry_bar = 0
        self.point_value = point_value
        self.margin_rate = margin_rate

    def is_flat(self) -> bool:
        return self.quantity < 1e-10

    def is_long(self) -> bool:
        return self.side == PositionSide.Long and not self.is_flat()

    def is_short(self) -> bool:
        return self.side == PositionSide.Short and not self.is_flat()

    def unrealized_pnl(self, price: float) -> float:
        if self.is_flat():
            return 0.0
        if self.side == PositionSide.Long:
            return (price - self.avg_entry_price) * self.quantity * self.point_value
        return (self.avg_entry_price - price) * self.quantity * self.point_value

    def apply_fill(self, fill: RustFill) -> Optional[RustClosedTrade]:
        is_inc = self._is_increasing(fill.side)

        if self.is_flat():
            self._open(fill)
            return None

        if is_inc:
            total_cost = self.avg_entry_price * self.quantity + fill.price * fill.quantity
            self.quantity += fill.quantity
            self.avg_entry_price = total_cost / self.quantity
            self.total_commission += fill.commission
            self.total_slippage += abs(fill.slippage)
            return None

        close_qty = min(fill.quantity, self.quantity)
        remaining = fill.quantity - close_qty
        closed = self._close_portion(fill, close_qty)

        self.quantity -= close_qty
        if self.quantity < 1e-10:
            self.quantity = 0.0
            self.side = PositionSide.Flat
            self.avg_entry_price = 0.0

        if remaining > 1e-10:
            flip = RustFill(
                order_idx=fill.order_idx, symbol_idx=fill.symbol_idx,
                side=fill.side, quantity=remaining, price=fill.price,
                commission=0.0, slippage=0.0, timestamp_ns=fill.timestamp_ns,
                bar_index=fill.bar_index,
            )
            self._open(flip)

        return closed

    def force_close(self, price: float, bar_index: int) -> Optional[RustClosedTrade]:
        if self.is_flat():
            return None
        exit_side = OrderSide.Sell if self.is_long() else OrderSide.Buy
        fill = RustFill(
            order_idx=0xFFFFFFFF, symbol_idx=self.symbol_idx,
            side=exit_side, quantity=self.quantity, price=price,
            commission=0.0, slippage=0.0, timestamp_ns=0,
            bar_index=bar_index,
        )
        return self.apply_fill(fill)

    def _is_increasing(self, side: OrderSide) -> bool:
        if self.is_flat():
            return True
        return (
            (self.side == PositionSide.Long and side == OrderSide.Buy)
            or (self.side == PositionSide.Short and side == OrderSide.Sell)
        )

    def _open(self, fill: RustFill):
        self.side = PositionSide.Long if fill.side == OrderSide.Buy else PositionSide.Short
        self.quantity = fill.quantity
        self.avg_entry_price = fill.price
        self.first_entry_bar = fill.bar_index
        self.total_commission = fill.commission
        self.total_slippage = abs(fill.slippage)
        self.realized_pnl = 0.0

    def _close_portion(self, fill: RustFill, close_qty: float) -> RustClosedTrade:
        if self.side == PositionSide.Long:
            pnl_raw = (fill.price - self.avg_entry_price) * close_qty * self.point_value
            side = OrderSide.Buy
        else:
            pnl_raw = (self.avg_entry_price - fill.price) * close_qty * self.point_value
            side = OrderSide.Sell
        pnl = pnl_raw - fill.commission
        self.realized_pnl += pnl
        self.total_commission += fill.commission
        self.total_slippage += abs(fill.slippage)

        entry_notional = self.avg_entry_price * close_qty * self.point_value
        pnl_pct = (pnl / entry_notional * 100) if entry_notional > 0 else 0.0

        return RustClosedTrade(
            symbol_idx=self.symbol_idx, side=side, quantity=close_qty,
            entry_price=self.avg_entry_price, exit_price=fill.price,
            pnl=pnl, pnl_pct=pnl_pct,
            commission=fill.commission, slippage=abs(fill.slippage),
            entry_bar=self.first_entry_bar, exit_bar=fill.bar_index,
            duration_bars=fill.bar_index - self.first_entry_bar,
        )


# ════════════════════════════════════════════════════════════════
# Portfolio
# ════════════════════════════════════════════════════════════════

class FastPortfolio:
    __slots__ = (
        "config", "symbols", "positions", "cash",
        "equity_curve", "closed_trades", "peak_equity",
        "max_dd", "max_dd_pct", "total_commission",
        "total_slippage", "total_fills", "last_prices",
    )

    def __init__(self, config: EngineConfig, symbols: list[SymbolConfig]):
        self.config = config
        self.symbols = symbols
        self.positions = [
            _Position(s.symbol_idx, s.point_value, s.margin_rate)
            for s in symbols
        ]
        self.cash = config.initial_cash
        self.equity_curve: list[float] = [config.initial_cash]
        self.closed_trades: list[RustClosedTrade] = []
        self.peak_equity = config.initial_cash
        self.max_dd = 0.0
        self.max_dd_pct = 0.0
        self.total_commission = 0.0
        self.total_slippage = 0.0
        self.total_fills = 0
        self.last_prices = [0.0] * len(symbols)

    @property
    def n_closed_trades(self) -> int:
        return len(self.closed_trades)

    @property
    def max_drawdown_pct(self) -> float:
        return self.max_dd_pct

    def get_closed_trades(self) -> list[RustClosedTrade]:
        return self.closed_trades

    def apply_fill(self, fill: RustFill):
        self.total_commission += fill.commission
        self.total_slippage += abs(fill.slippage)
        self.total_fills += 1

        idx = fill.symbol_idx
        if idx >= len(self.positions):
            return

        closed = self.positions[idx].apply_fill(fill)
        if closed:
            # pnl in closed trade already includes exit commission
            self.cash += closed.pnl
            self.closed_trades.append(closed)
        else:
            # Opening/increasing: deduct commission from cash
            self.cash -= fill.commission

    def snapshot_equity(self):
        unrealized = sum(
            p.unrealized_pnl(self.last_prices[i])
            for i, p in enumerate(self.positions)
            if not p.is_flat() and self.last_prices[i] > 0
        )
        total = self.cash + unrealized
        self.equity_curve.append(total)

        if total > self.peak_equity:
            self.peak_equity = total
        dd = self.peak_equity - total
        dd_pct = (dd / self.peak_equity * 100) if self.peak_equity > 0 else 0.0
        if dd > self.max_dd:
            self.max_dd = dd
        if dd_pct > self.max_dd_pct:
            self.max_dd_pct = dd_pct

    def update_price(self, symbol_idx: int, price: float):
        if symbol_idx < len(self.last_prices):
            self.last_prices[symbol_idx] = price

    def force_close_all(self, bar_index: int):
        for i, pos in enumerate(self.positions):
            price = self.last_prices[i]
            if price <= 0 or pos.is_flat():
                continue
            closed = pos.force_close(price, bar_index)
            if closed:
                self.cash += closed.pnl
                self.closed_trades.append(closed)

    def is_halted(self) -> bool:
        return self.config.max_drawdown_pct > 0 and self.max_dd_pct >= self.config.max_drawdown_pct

    def is_flat(self, symbol_idx: int = -1) -> bool:
        """Check if a position (or all positions) is flat."""
        if symbol_idx < 0:
            return all(p.is_flat() for p in self.positions)
        if symbol_idx < len(self.positions):
            return self.positions[symbol_idx].is_flat()
        return True

    def get_trades(self) -> list[dict]:
        """Return closed trades as list of dicts."""
        out = []
        for t in self.closed_trades:
            sd = "long" if t.side == OrderSide.Buy or (isinstance(t.side, int) and t.side == 1) else "short"
            out.append({
                "symbol_idx": t.symbol_idx,
                "side": sd,
                "quantity": t.quantity,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "commission": t.commission,
                "slippage": t.slippage,
                "entry_bar": t.entry_bar,
                "exit_bar": t.exit_bar,
                "duration_bars": t.duration_bars,
                "is_winner": t.pnl > 0,
            })
        return out


# ════════════════════════════════════════════════════════════════
# Tick Matcher
# ════════════════════════════════════════════════════════════════

@dataclass(slots=True)
class _MatchResult:
    order_idx: int
    fill_price: float
    raw_price: float
    is_gap_fill: bool
    tick_index: int
    timestamp_ns: int


def _adjust_price(raw: float, side: OrderSide, spread: float, slippage_pct: float, is_maker: bool) -> float:
    half_spread = 0.0 if is_maker else spread / 2.0
    slip = raw * slippage_pct
    if side == OrderSide.Buy:
        return max(raw + half_spread + slip, 0.0001)
    return max(raw - half_spread - slip, 0.0001)


def _is_gap(prev_close: float, curr_open: float) -> bool:
    if prev_close <= 0:
        return False
    return abs(curr_open - prev_close) / prev_close > 0.001


def _five_tick_ohlc(bar: Bar) -> list[tuple[float, int]]:
    bullish = bar.close >= bar.open
    if bullish:
        return [
            (bar.open, 0), (bar.high, 1), (bar.low, 2),
            (bar.close, 3), (bar.close, 4),
        ]
    return [
        (bar.open, 0), (bar.low, 1), (bar.high, 2),
        (bar.close, 3), (bar.close, 4),
    ]


def _match_orders_against_bar(
    bar: Bar,
    pending: list[RustOrder],
    prev_close: float,
    spread: float,
    slippage_pct: float,
) -> list[_MatchResult]:
    if not pending:
        return []

    ticks = _five_tick_ohlc(bar)
    gap = _is_gap(prev_close, bar.open)
    fills: list[_MatchResult] = []
    filled = set()

    for price, tidx in ticks:
        for i, order in enumerate(pending):
            if i in filled:
                continue
            result = None

            if order.order_type == OrderType.Limit:
                result = _try_limit(order, price, tidx, bar, spread, slippage_pct)
            elif order.order_type == OrderType.Stop:
                result = _try_stop(order, price, tidx, bar, gap, spread, slippage_pct)
            elif order.order_type == OrderType.StopLimit:
                result = _try_stop_limit(order, price, tidx, bar, gap, spread, slippage_pct)

            if result is not None:
                fills.append(result)
                filled.add(i)

    return fills


def _try_limit(order, price, tidx, bar, spread, slippage_pct):
    if order.limit_price <= 0:
        return None
    if order.side == OrderSide.Buy and price <= order.limit_price:
        raw = min(order.limit_price, price)
    elif order.side == OrderSide.Sell and price >= order.limit_price:
        raw = max(order.limit_price, price)
    else:
        return None
    fp = _adjust_price(raw, order.side, spread, slippage_pct, True)
    return _MatchResult(order.idx, fp, raw, False, tidx, bar.timestamp_ns)


def _try_stop(order, price, tidx, bar, gap, spread, slippage_pct):
    if order.stop_price <= 0:
        return None
    if order.side == OrderSide.Buy and price >= order.stop_price:
        pass
    elif order.side == OrderSide.Sell and price <= order.stop_price:
        pass
    else:
        return None

    raw = order.stop_price
    gap_fill = False
    if gap and tidx == 0:
        if order.side == OrderSide.Buy and bar.open > order.stop_price:
            raw = bar.open
            gap_fill = True
        elif order.side == OrderSide.Sell and bar.open < order.stop_price:
            raw = bar.open
            gap_fill = True

    fp = _adjust_price(raw, order.side, spread, slippage_pct, False)
    return _MatchResult(order.idx, fp, raw, gap_fill, tidx, bar.timestamp_ns)


def _try_stop_limit(order, price, tidx, bar, gap, spread, slippage_pct):
    if order.stop_price <= 0 or order.limit_price <= 0:
        return None
    # Stop trigger
    if order.side == OrderSide.Buy and price < order.stop_price:
        return None
    if order.side == OrderSide.Sell and price > order.stop_price:
        return None

    # Limit check
    limit_ok = False
    if order.side == OrderSide.Buy and price <= order.limit_price:
        limit_ok = True
    elif order.side == OrderSide.Sell and price >= order.limit_price:
        limit_ok = True
    if not limit_ok:
        if order.side == OrderSide.Buy and bar.low <= order.limit_price:
            limit_ok = True
        elif order.side == OrderSide.Sell and bar.high >= order.limit_price:
            limit_ok = True
    if not limit_ok:
        return None

    gap_fill = False
    if gap and tidx == 0:
        if order.side == OrderSide.Buy:
            if bar.open > order.limit_price:
                return None
            if bar.open > order.stop_price:
                gap_fill = True
        else:
            if bar.open < order.limit_price:
                return None
            if bar.open < order.stop_price:
                gap_fill = True

    raw = order.limit_price
    fp = _adjust_price(raw, order.side, spread, slippage_pct, True)
    return _MatchResult(order.idx, fp, raw, gap_fill, tidx, bar.timestamp_ns)


def _fill_market_order(order: RustOrder, bar: Bar, spread: float, slippage_pct: float) -> _MatchResult:
    raw = bar.open
    fp = _adjust_price(raw, order.side, spread, slippage_pct, False)
    return _MatchResult(order.idx, fp, raw, False, 0, bar.timestamp_ns)


# ════════════════════════════════════════════════════════════════
# Runner Result
# ════════════════════════════════════════════════════════════════

@dataclass
class BacktestResult:
    equity_curve: list[float]
    bars_processed: int
    elapsed_ms: float
    halted: bool
    halt_reason: str
    n_trades: int
    n_fills: int

    def get_trades(self, py=None, portfolio: FastPortfolio = None) -> list[dict]:
        """Mimics the Rust get_trades API."""
        if portfolio is None:
            return []
        out = []
        for t in portfolio.closed_trades:
            out.append({
                "symbol_idx": t.symbol_idx,
                "side": "long" if t.side == OrderSide.Buy else "short",
                "quantity": t.quantity,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "commission": t.commission,
                "slippage": t.slippage,
                "entry_bar": t.entry_bar,
                "exit_bar": t.exit_bar,
                "duration_bars": t.duration_bars,
                "is_winner": t.pnl > 0,
            })
        return out


# ════════════════════════════════════════════════════════════════
# Fast Runner
# ════════════════════════════════════════════════════════════════

class FastRunner:
    def __init__(
        self,
        config: EngineConfig,
        symbols: list[SymbolConfig],
        bars_flat: list[Bar],
    ):
        self.config = config
        self.symbols = symbols
        self.bars = bars_flat
        self.pending_orders: list[RustOrder] = []
        self.next_order_idx = 0
        self.prev_close = [0.0] * len(symbols)
        # Indicator sets (optional)
        self._ind_sma_fast: list[Optional[SMA]] = [None] * len(symbols)
        self._ind_sma_slow: list[Optional[SMA]] = [None] * len(symbols)
        self._ind_ema_fast: list[Optional[EMA]] = [None] * len(symbols)
        self._ind_ema_slow: list[Optional[EMA]] = [None] * len(symbols)
        self._ind_atr: list[Optional[ATR]] = [None] * len(symbols)
        self._ind_bb: list[Optional[BollingerBands]] = [None] * len(symbols)

    def run(self, strategy_cb: Callable) -> tuple[BacktestResult, FastPortfolio]:
        t0 = time.perf_counter()

        portfolio = FastPortfolio(self.config, self.symbols)
        warm_up = self.config.warm_up_bars
        bars_processed = 0
        halted = False

        # Feed bars
        queue = FastEventQueue()
        for bar in self.bars:
            queue.push_bar(bar.timestamp_ns, bar.bar_index, bar.symbol_idx)

        # Main loop
        while not queue.is_empty():
            entry = queue.pop()
            if entry is None:
                break

            _, _, _, bar_idx, sym_idx = entry
            if bar_idx >= len(self.bars):
                continue
            bar = self.bars[bar_idx]

            portfolio.update_price(bar.symbol_idx, bar.close)

            if bar.bar_index < warm_up:
                if sym_idx < len(self.prev_close):
                    self.prev_close[sym_idx] = bar.close
                continue

            bars_processed += 1

            # 1. Indicators
            ind_vals = self._update_indicators(sym_idx, bar)

            # 2. Pending orders
            prev_cl = self.prev_close[sym_idx] if sym_idx < len(self.prev_close) else 0.0
            spread = self.symbols[sym_idx].spread if sym_idx < len(self.symbols) else self.config.spread
            pending_sym = [o for o in self.pending_orders if o.symbol_idx == bar.symbol_idx and o.is_active]

            if pending_sym:
                matches = _match_orders_against_bar(bar, pending_sym, prev_cl, spread, self.config.slippage_pct)
                for m in matches:
                    fill = self._create_fill(m, bar, portfolio)
                    portfolio.apply_fill(fill)
                    self._cancel_linked(m.order_idx)
                    self._mark_filled(m.order_idx)

            # 3. Strategy callback
            bar_dict = {
                "timestamp_ns": bar.timestamp_ns,
                "symbol_idx": bar.symbol_idx,
                "bar_index": bar.bar_index,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
            if sym_idx < len(self.symbols):
                bar_dict["symbol"] = self.symbols[sym_idx].name

            orders_list = strategy_cb(bar_dict, ind_vals)

            # 4. Process orders
            for od in (orders_list or []):
                order = self._parse_order(od, bar)
                if order.order_type == OrderType.Market:
                    m = _fill_market_order(order, bar, spread, self.config.slippage_pct)
                    fill = self._create_fill(m, bar, portfolio)
                    portfolio.apply_fill(fill)
                else:
                    self.pending_orders.append(order)

            # 5. Cleanup
            self.pending_orders = [o for o in self.pending_orders if o.is_active]

            # 6. Equity snapshot
            portfolio.snapshot_equity()

            # 7. Halt check
            if portfolio.is_halted():
                halted = True
                break

            # 8. Previous close
            if sym_idx < len(self.prev_close):
                self.prev_close[sym_idx] = bar.close

        # Finalize
        halt_reason = f"Max drawdown {self.config.max_drawdown_pct:.2f}% exceeded" if halted else ""
        last_bar_idx = self.bars[-1].bar_index if self.bars else 0
        portfolio.force_close_all(last_bar_idx)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        result = BacktestResult(
            equity_curve=portfolio.equity_curve,
            bars_processed=bars_processed,
            elapsed_ms=elapsed_ms,
            halted=halted,
            halt_reason=halt_reason,
            n_trades=len(portfolio.closed_trades),
            n_fills=portfolio.total_fills,
        )
        return result, portfolio

    def _update_indicators(self, sym_idx: int, bar: Bar) -> IndicatorValues:
        iv = IndicatorValues()
        if sym_idx < len(self._ind_sma_fast) and self._ind_sma_fast[sym_idx]:
            iv.sma_fast = self._ind_sma_fast[sym_idx].push(bar.close)
        if sym_idx < len(self._ind_sma_slow) and self._ind_sma_slow[sym_idx]:
            iv.sma_slow = self._ind_sma_slow[sym_idx].push(bar.close)
        if sym_idx < len(self._ind_ema_fast) and self._ind_ema_fast[sym_idx]:
            iv.ema_fast = self._ind_ema_fast[sym_idx].push(bar.close)
        if sym_idx < len(self._ind_ema_slow) and self._ind_ema_slow[sym_idx]:
            iv.ema_slow = self._ind_ema_slow[sym_idx].push(bar.close)
        if sym_idx < len(self._ind_atr) and self._ind_atr[sym_idx]:
            iv.atr = self._ind_atr[sym_idx].push(bar.high, bar.low, bar.close)
        if sym_idx < len(self._ind_bb) and self._ind_bb[sym_idx]:
            u, m, l = self._ind_bb[sym_idx].push(bar.close)
            iv.bb_upper = u
            iv.bb_middle = m
            iv.bb_lower = l
        return iv

    def _create_fill(self, m: _MatchResult, bar: Bar, portfolio: FastPortfolio) -> RustFill:
        order = next((o for o in self.pending_orders if o.idx == m.order_idx), None)
        qty = order.remaining_quantity if order else 1.0
        side = order.side if order else OrderSide.Buy

        commission = (
            self.config.commission_per_lot * qty
            + self.config.commission_pct * m.fill_price * qty
        )
        return RustFill(
            order_idx=m.order_idx, symbol_idx=bar.symbol_idx,
            side=side, quantity=qty, price=m.fill_price,
            commission=commission,
            slippage=abs(m.fill_price - m.raw_price),
            timestamp_ns=m.timestamp_ns, bar_index=bar.bar_index,
            is_gap_fill=m.is_gap_fill,
        )

    def _mark_filled(self, order_idx: int):
        for o in self.pending_orders:
            if o.idx == order_idx:
                o.status = OrderStatus.Filled
                o.filled_quantity = o.quantity
                break

    def _cancel_linked(self, filled_idx: int):
        linked = []
        for o in self.pending_orders:
            if o.idx == filled_idx:
                linked = o.linked_indices[:]
                break
        for li in linked:
            for o in self.pending_orders:
                if o.idx == li:
                    o.status = OrderStatus.Cancelled
                    break

    def _parse_order(self, d: dict, bar: Bar) -> RustOrder:
        # Side: accept int (1=Buy, 2=Sell) or string ("BUY"/"SELL")
        raw_side = d.get("side", "BUY")
        if isinstance(raw_side, int):
            side = OrderSide.Buy if raw_side == 1 else OrderSide.Sell
        else:
            side = OrderSide.Buy if str(raw_side).upper() in ("BUY", "1") else OrderSide.Sell

        # Order type: accept int (1=Market, 2=Limit, 3=Stop, 4=StopLimit) or string
        raw_otype = d.get("order_type", "MARKET")
        if isinstance(raw_otype, int):
            otype_int_map = {1: OrderType.Market, 2: OrderType.Limit, 3: OrderType.Stop, 4: OrderType.StopLimit}
            order_type = otype_int_map.get(raw_otype, OrderType.Market)
        else:
            otype_map = {
                "MARKET": OrderType.Market,
                "LIMIT": OrderType.Limit,
                "STOP": OrderType.Stop,
                "STOP_LIMIT": OrderType.StopLimit,
            }
            order_type = otype_map.get(str(raw_otype).upper(), OrderType.Market)

        # Symbol index: prefer explicit, fall back to bar's symbol
        sym_idx = d.get("symbol_idx", bar.symbol_idx)

        idx = self.next_order_idx
        self.next_order_idx += 1

        order = RustOrder(
            idx=idx,
            symbol_idx=sym_idx,
            side=side,
            order_type=order_type,
            quantity=d.get("quantity", 1.0),
            limit_price=d.get("limit_price", 0.0),
            stop_price=d.get("stop_price", 0.0),
            tag=d.get("tag", ""),
        )
        order.status = OrderStatus.Submitted
        return order
