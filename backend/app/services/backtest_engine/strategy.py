"""
Strategy Base & Context — Strategy API for the backtesting engine.

Strategies inherit from StrategyBase and use StrategyContext to:
- Place orders (buy, sell, bracket)
- Access indicators and bar data
- Query position state
- Set SL/TP/trailing stops
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

from .bar import Bar
from .order import (
    Order, BracketOrder, OrderSide, OrderType, OrderRole,
)
from .instrument import Instrument
from .position_sizer import SizingMethod, compute_size

if TYPE_CHECKING:
    from .data_feed import DataFeed
    from .position import Position, Portfolio


@dataclass
class TradeRecord:
    """Completed trade record for analytics."""
    entry_bar: int
    entry_time: float
    entry_price: float
    direction: str         # "long" or "short"
    size: float
    stop_loss: float = 0.0
    take_profit: float = 0.0
    exit_bar: int = -1
    exit_time: float = 0.0
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0
    commission: float = 0.0
    tag: str = ""
    bars_held: int = 0

    def to_dict(self) -> dict:
        return {
            "entry_bar": self.entry_bar,
            "entry_time": self.entry_time,
            "entry_price": round(self.entry_price, 5),
            "direction": self.direction,
            "size": self.size,
            "stop_loss": round(self.stop_loss, 5),
            "take_profit": round(self.take_profit, 5),
            "exit_bar": self.exit_bar,
            "exit_time": self.exit_time,
            "exit_price": round(self.exit_price, 5) if self.exit_price else 0,
            "exit_reason": self.exit_reason,
            "pnl": round(self.pnl, 2),
            "pnl_pct": round(self.pnl_pct, 4),
            "commission": round(self.commission, 2),
            "tag": self.tag,
            "bars_held": self.bars_held,
        }


class StrategyContext:
    """API object passed to strategies for interacting with the engine."""

    def __init__(
        self,
        data_feed: DataFeed,
        portfolio: Portfolio,
        instrument: Instrument,
        sizing_method: SizingMethod = SizingMethod.RISK_PERCENT,
        sizing_params: dict = None,
    ):
        self._feed = data_feed
        self._portfolio = portfolio
        self._instrument = instrument
        self._sizing_method = sizing_method
        self._sizing_params = sizing_params or {}
        self._bar_index: int = 0
        self._current_bar: Optional[Bar] = None
        self._pending_orders: list[Order] = []
        self._pending_brackets: list[BracketOrder] = []
        self._trade_records: list[TradeRecord] = []
        self._open_trade_map: dict[str, TradeRecord] = {}  # bracket_id -> TradeRecord

    @property
    def bar_index(self) -> int:
        return self._bar_index

    @property
    def bar(self) -> Optional[Bar]:
        return self._current_bar

    @property
    def balance(self) -> float:
        return self._portfolio.balance

    @property
    def equity(self) -> float:
        prices = {}
        symbol = self._instrument.symbol
        if self._current_bar:
            prices[symbol] = self._current_bar.close
        return self._portfolio.equity(prices)

    @property
    def trades(self) -> list[TradeRecord]:
        return self._trade_records

    # ── Data Access ─────────────────────────────────────────────────

    def get_bar(self, symbol: str = "", bars_ago: int = 0,
                timeframe: str = "primary") -> Optional[Bar]:
        """Get a bar. bars_ago=0 is current, 1 is previous, etc."""
        sym = symbol or self._instrument.symbol
        idx = self._bar_index - bars_ago
        return self._feed.get_bar(sym, idx, timeframe)

    def get_indicator(self, name: str, symbol: str = "", bars_ago: int = 0,
                      timeframe: str = "primary") -> float:
        """Get an indicator value. bars_ago=0 is current."""
        sym = symbol or self._instrument.symbol
        idx = self._bar_index - bars_ago
        return self._feed.get_indicator(sym, name, idx, timeframe)

    def get_close(self, bars_ago: int = 0) -> float:
        bar = self.get_bar(bars_ago=bars_ago)
        return bar.close if bar else float("nan")

    def get_high(self, bars_ago: int = 0) -> float:
        bar = self.get_bar(bars_ago=bars_ago)
        return bar.high if bar else float("nan")

    def get_low(self, bars_ago: int = 0) -> float:
        bar = self.get_bar(bars_ago=bars_ago)
        return bar.low if bar else float("nan")

    def get_open(self, bars_ago: int = 0) -> float:
        bar = self.get_bar(bars_ago=bars_ago)
        return bar.open if bar else float("nan")

    # ── Position Access ─────────────────────────────────────────────

    def get_position(self, symbol: str = "") -> Optional[Position]:
        sym = symbol or self._instrument.symbol
        return self._portfolio.get_position(sym)

    def is_flat(self, symbol: str = "") -> bool:
        pos = self.get_position(symbol)
        return pos is None or pos.is_flat

    def is_long(self, symbol: str = "") -> bool:
        pos = self.get_position(symbol)
        return pos is not None and pos.is_long

    def is_short(self, symbol: str = "") -> bool:
        pos = self.get_position(symbol)
        return pos is not None and pos.is_short

    def position_size(self, symbol: str = "") -> float:
        pos = self.get_position(symbol)
        return pos.quantity if pos and not pos.is_flat else 0.0

    # ── Order Placement ─────────────────────────────────────────────

    def buy(self, size: float = 0, symbol: str = "", tag: str = "") -> Order:
        """Place a market buy order."""
        sym = symbol or self._instrument.symbol
        qty = size or self._default_size()
        order = Order(
            symbol=sym, side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=qty, role=OrderRole.ENTRY,
            created_bar_index=self._bar_index, tag=tag,
        )
        self._pending_orders.append(order)
        return order

    def sell(self, size: float = 0, symbol: str = "", tag: str = "") -> Order:
        """Place a market sell order."""
        sym = symbol or self._instrument.symbol
        qty = size or self._default_size()
        order = Order(
            symbol=sym, side=OrderSide.SELL, order_type=OrderType.MARKET,
            quantity=qty, role=OrderRole.ENTRY,
            created_bar_index=self._bar_index, tag=tag,
        )
        self._pending_orders.append(order)
        return order

    def buy_bracket(
        self, size: float = 0, stop_loss: float = 0, take_profit: float = 0,
        trail_offset: float = 0, symbol: str = "", tag: str = "",
    ) -> BracketOrder:
        """Place a bracket buy: market entry + stop-loss + take-profit."""
        sym = symbol or self._instrument.symbol
        qty = size or self._compute_size(stop_loss, "long")

        entry = Order(
            symbol=sym, side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=qty, role=OrderRole.ENTRY,
            created_bar_index=self._bar_index, tag=tag,
        )

        sl_order = None
        if stop_loss > 0:
            sl_order = Order(
                symbol=sym, side=OrderSide.SELL, order_type=OrderType.STOP,
                quantity=qty, price=stop_loss, role=OrderRole.STOP_LOSS,
                created_bar_index=self._bar_index, tag=f"sl_{tag}",
            )

        tp_order = None
        if take_profit > 0:
            tp_order = Order(
                symbol=sym, side=OrderSide.SELL, order_type=OrderType.LIMIT,
                quantity=qty, price=take_profit, role=OrderRole.TAKE_PROFIT,
                created_bar_index=self._bar_index, tag=f"tp_{tag}",
            )

        trail_order = None
        if trail_offset > 0:
            current_price = self._current_bar.close if self._current_bar else 0
            trail_order = Order(
                symbol=sym, side=OrderSide.SELL, order_type=OrderType.STOP,
                quantity=qty, price=current_price - trail_offset,
                role=OrderRole.TRAILING_STOP,
                trail_offset=trail_offset, trail_trigger=current_price - trail_offset,
                created_bar_index=self._bar_index, tag=f"trail_{tag}",
            )

        bracket = BracketOrder(
            entry=entry, stop_loss=sl_order,
            take_profit=tp_order, trailing_stop=trail_order,
        )
        self._pending_brackets.append(bracket)
        return bracket

    def sell_bracket(
        self, size: float = 0, stop_loss: float = 0, take_profit: float = 0,
        trail_offset: float = 0, symbol: str = "", tag: str = "",
    ) -> BracketOrder:
        """Place a bracket sell: market entry + stop-loss + take-profit."""
        sym = symbol or self._instrument.symbol
        qty = size or self._compute_size(stop_loss, "short")

        entry = Order(
            symbol=sym, side=OrderSide.SELL, order_type=OrderType.MARKET,
            quantity=qty, role=OrderRole.ENTRY,
            created_bar_index=self._bar_index, tag=tag,
        )

        sl_order = None
        if stop_loss > 0:
            sl_order = Order(
                symbol=sym, side=OrderSide.BUY, order_type=OrderType.STOP,
                quantity=qty, price=stop_loss, role=OrderRole.STOP_LOSS,
                created_bar_index=self._bar_index, tag=f"sl_{tag}",
            )

        tp_order = None
        if take_profit > 0:
            tp_order = Order(
                symbol=sym, side=OrderSide.BUY, order_type=OrderType.LIMIT,
                quantity=qty, price=take_profit, role=OrderRole.TAKE_PROFIT,
                created_bar_index=self._bar_index, tag=f"tp_{tag}",
            )

        trail_order = None
        if trail_offset > 0:
            current_price = self._current_bar.close if self._current_bar else 0
            trail_order = Order(
                symbol=sym, side=OrderSide.BUY, order_type=OrderType.STOP,
                quantity=qty, price=current_price + trail_offset,
                role=OrderRole.TRAILING_STOP,
                trail_offset=trail_offset, trail_trigger=current_price + trail_offset,
                created_bar_index=self._bar_index, tag=f"trail_{tag}",
            )

        bracket = BracketOrder(
            entry=entry, stop_loss=sl_order,
            take_profit=tp_order, trailing_stop=trail_order,
        )
        self._pending_brackets.append(bracket)
        return bracket

    def close_position(self, symbol: str = "", tag: str = "exit") -> Optional[Order]:
        """Close entire position with a market order."""
        sym = symbol or self._instrument.symbol
        pos = self._portfolio.get_position(sym)
        if not pos or pos.is_flat:
            return None

        side = OrderSide.SELL if pos.is_long else OrderSide.BUY
        order = Order(
            symbol=sym, side=side, order_type=OrderType.MARKET,
            quantity=pos.quantity, role=OrderRole.EXIT,
            created_bar_index=self._bar_index, tag=tag,
        )
        self._pending_orders.append(order)
        return order

    # ── Internal ────────────────────────────────────────────────────

    def _drain_orders(self) -> tuple[list[Order], list[BracketOrder]]:
        """Drain pending orders (called by engine after on_bar)."""
        orders = self._pending_orders.copy()
        brackets = self._pending_brackets.copy()
        self._pending_orders.clear()
        self._pending_brackets.clear()
        return orders, brackets

    def _set_bar(self, index: int, bar: Bar) -> None:
        """Set current bar (called by engine)."""
        self._bar_index = index
        self._current_bar = bar

    def _default_size(self) -> float:
        """Get default position size from sizing config."""
        return self._sizing_params.get("fixed_lot", 0.01)

    def _compute_size(self, stop_loss: float, direction: str) -> float:
        """Compute size using position sizer."""
        if not self._current_bar:
            return self._default_size()

        entry_price = self._current_bar.close
        sl_price = stop_loss if stop_loss > 0 else entry_price

        return compute_size(
            method=self._sizing_method,
            balance=self._portfolio.balance,
            entry_price=entry_price,
            stop_loss_price=sl_price,
            instrument=self._instrument,
            **self._sizing_params,
        )

    def _record_trade_open(self, bracket_id: str, entry_order: Order,
                           sl: float = 0, tp: float = 0) -> None:
        """Record a trade opening."""
        record = TradeRecord(
            entry_bar=entry_order.fill_bar_index,
            entry_time=entry_order.fill_timestamp,
            entry_price=entry_order.fill_price,
            direction="long" if entry_order.is_buy else "short",
            size=entry_order.fill_quantity,
            stop_loss=sl,
            take_profit=tp,
            commission=entry_order.commission,
            tag=entry_order.tag,
        )
        self._open_trade_map[bracket_id] = record

    def _record_trade_close(self, bracket_id: str, exit_order: Order,
                            pnl: float) -> None:
        """Record a trade closing."""
        record = self._open_trade_map.pop(bracket_id, None)
        if record is None:
            # Standalone order (no bracket) — create minimal record
            record = TradeRecord(
                entry_bar=exit_order.created_bar_index,
                entry_time=exit_order.created_timestamp if exit_order.created_timestamp else exit_order.fill_timestamp,
                entry_price=0,
                direction="long" if exit_order.is_sell else "short",
                size=exit_order.fill_quantity,
            )

        record.exit_bar = exit_order.fill_bar_index
        record.exit_time = exit_order.fill_timestamp
        record.exit_price = exit_order.fill_price
        record.exit_reason = exit_order.role.value
        record.pnl = pnl
        record.commission += exit_order.commission
        record.bars_held = record.exit_bar - record.entry_bar

        if record.entry_price > 0 and record.size > 0:
            entry_value = record.entry_price * record.size * self._instrument.point_value
            if entry_value > 0:
                record.pnl_pct = pnl / entry_value * 100

        self._trade_records.append(record)


class StrategyBase(ABC):
    """Abstract base class for all backtesting strategies."""

    def __init__(self, name: str = "Strategy", params: dict | None = None):
        self.name = name
        self.params = params or {}
        self.ctx: Optional[StrategyContext] = None

    def _set_context(self, ctx: StrategyContext) -> None:
        self.ctx = ctx

    def on_init(self) -> None:
        """Called once before the backtest starts. Override to set up state."""
        pass

    @abstractmethod
    def on_bar(self, bar: Bar) -> None:
        """Called on each new bar. Place orders via self.ctx."""
        pass

    def on_order_filled(self, order: Order) -> None:
        """Called when an order is filled. Override for custom logic."""
        pass

    def on_position_closed(self, symbol: str, pnl: float) -> None:
        """Called when a position is fully closed."""
        pass

    def on_end(self) -> None:
        """Called after the backtest finishes. Override for cleanup."""
        pass
