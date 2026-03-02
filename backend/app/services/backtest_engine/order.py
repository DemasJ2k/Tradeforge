"""
Order — Order types, lifecycle, and bracket (OCO) orders.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Optional


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"          # Fill at price or better
    STOP = "stop"            # Fill when price crosses trigger
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class OrderRole(str, Enum):
    """Role within a bracket group."""
    ENTRY = "entry"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    EXIT = "exit"


@dataclass
class Order:
    """A single order in the order book."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.MARKET
    quantity: float = 0.0
    price: float = 0.0              # Limit price or stop trigger
    stop_price: float = 0.0         # For stop_limit: trigger first, then limit at price
    status: OrderStatus = OrderStatus.PENDING
    role: OrderRole = OrderRole.ENTRY
    tag: str = ""                   # User-defined label

    # Bracket / OCO linking
    bracket_id: str = ""            # Group ID for bracket orders
    oco_id: str = ""                # OCO partner order ID

    # Fill info
    fill_price: float = 0.0
    fill_quantity: float = 0.0
    fill_bar_index: int = -1
    fill_timestamp: float = 0.0
    commission: float = 0.0
    slippage: float = 0.0

    # Timestamps
    created_bar_index: int = -1
    created_timestamp: float = 0.0

    # Trailing stop fields
    trail_offset: float = 0.0      # Distance from price to trail
    trail_trigger: float = 0.0     # Current trailing trigger price

    def fill(self, price: float, quantity: float, bar_index: int,
             timestamp: float, commission: float = 0.0, slippage: float = 0.0) -> None:
        self.fill_price = price
        self.fill_quantity = quantity
        self.fill_bar_index = bar_index
        self.fill_timestamp = timestamp
        self.commission = commission
        self.slippage = slippage
        self.status = OrderStatus.FILLED

    def cancel(self) -> None:
        if self.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED):
            self.status = OrderStatus.CANCELLED

    def reject(self, reason: str = "") -> None:
        self.status = OrderStatus.REJECTED
        self.tag = reason if reason else self.tag

    @property
    def is_active(self) -> bool:
        return self.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED)

    @property
    def is_buy(self) -> bool:
        return self.side == OrderSide.BUY

    @property
    def is_sell(self) -> bool:
        return self.side == OrderSide.SELL


@dataclass
class BracketOrder:
    """A bracket order group: entry + stop-loss + take-profit (OCO pair).

    When the entry fills, SL and TP are activated.
    When either SL or TP fills, the other is cancelled (OCO).
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    entry: Optional[Order] = None
    stop_loss: Optional[Order] = None
    take_profit: Optional[Order] = None
    trailing_stop: Optional[Order] = None

    def __post_init__(self):
        # Link all orders with the bracket ID
        for order in self.all_orders:
            order.bracket_id = self.id

        # Link SL and TP as OCO pair
        if self.stop_loss and self.take_profit:
            self.stop_loss.oco_id = self.take_profit.id
            self.take_profit.oco_id = self.stop_loss.id

        # Link trailing stop as OCO with TP if both exist
        if self.trailing_stop and self.take_profit:
            self.trailing_stop.oco_id = self.take_profit.id

    @property
    def all_orders(self) -> list[Order]:
        orders = []
        if self.entry:
            orders.append(self.entry)
        if self.stop_loss:
            orders.append(self.stop_loss)
        if self.take_profit:
            orders.append(self.take_profit)
        if self.trailing_stop:
            orders.append(self.trailing_stop)
        return orders

    @property
    def is_entry_filled(self) -> bool:
        return self.entry is not None and self.entry.status == OrderStatus.FILLED

    @property
    def is_closed(self) -> bool:
        """Bracket is closed when either SL or TP has filled."""
        if self.stop_loss and self.stop_loss.status == OrderStatus.FILLED:
            return True
        if self.take_profit and self.take_profit.status == OrderStatus.FILLED:
            return True
        if self.trailing_stop and self.trailing_stop.status == OrderStatus.FILLED:
            return True
        return False


class OrderBook:
    """Manages all active and historical orders."""

    def __init__(self):
        self._orders: dict[str, Order] = {}
        self._brackets: dict[str, BracketOrder] = {}
        self._filled_orders: list[Order] = []

    def add_order(self, order: Order) -> None:
        order.status = OrderStatus.SUBMITTED
        self._orders[order.id] = order

    def add_bracket(self, bracket: BracketOrder) -> None:
        self._brackets[bracket.id] = bracket
        # Add entry order immediately
        if bracket.entry:
            self.add_order(bracket.entry)
        # SL/TP are added after entry fills (see activate_bracket_exits)

    def activate_bracket_exits(self, bracket_id: str) -> list[Order]:
        """Activate SL/TP orders after entry fills. Returns activated orders."""
        bracket = self._brackets.get(bracket_id)
        if not bracket:
            return []

        activated = []
        for order in [bracket.stop_loss, bracket.take_profit, bracket.trailing_stop]:
            if order:
                order.status = OrderStatus.SUBMITTED
                self._orders[order.id] = order
                activated.append(order)
        return activated

    def get_active_orders(self, symbol: Optional[str] = None) -> list[Order]:
        """Get all active (pending/submitted) orders, optionally filtered by symbol."""
        orders = [o for o in self._orders.values() if o.is_active]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders

    def get_pending_stops_and_limits(self, symbol: str) -> list[Order]:
        """Get pending stop/limit orders for a symbol (SL/TP checking)."""
        return [
            o for o in self._orders.values()
            if o.is_active
            and o.symbol == symbol
            and o.order_type in (OrderType.STOP, OrderType.LIMIT, OrderType.STOP_LIMIT)
        ]

    def on_order_filled(self, order: Order) -> list[Order]:
        """Handle order fill: cancel OCO partners, activate bracket exits.
        Returns list of orders that were cancelled."""
        self._filled_orders.append(order)
        cancelled = []

        # Cancel OCO partner
        if order.oco_id and order.oco_id in self._orders:
            partner = self._orders[order.oco_id]
            if partner.is_active:
                partner.cancel()
                cancelled.append(partner)

        # If this was an entry order, activate the bracket's SL/TP
        if order.role == OrderRole.ENTRY and order.bracket_id:
            self.activate_bracket_exits(order.bracket_id)

        # If this was SL/TP, cancel all other exit orders in the bracket
        if order.bracket_id and order.role in (
            OrderRole.STOP_LOSS, OrderRole.TAKE_PROFIT, OrderRole.TRAILING_STOP
        ):
            bracket = self._brackets.get(order.bracket_id)
            if bracket:
                for sibling in bracket.all_orders:
                    if sibling.id != order.id and sibling.is_active:
                        if sibling.role in (OrderRole.STOP_LOSS, OrderRole.TAKE_PROFIT,
                                            OrderRole.TRAILING_STOP):
                            sibling.cancel()
                            cancelled.append(sibling)

        return cancelled

    def cancel_all(self, symbol: Optional[str] = None) -> list[Order]:
        """Cancel all active orders, optionally for a specific symbol."""
        cancelled = []
        for order in list(self._orders.values()):
            if order.is_active:
                if symbol is None or order.symbol == symbol:
                    order.cancel()
                    cancelled.append(order)
        return cancelled

    def get_bracket(self, bracket_id: str) -> Optional[BracketOrder]:
        return self._brackets.get(bracket_id)

    @property
    def filled_orders(self) -> list[Order]:
        return self._filled_orders.copy()

    def clear(self) -> None:
        self._orders.clear()
        self._brackets.clear()
        self._filled_orders.clear()
