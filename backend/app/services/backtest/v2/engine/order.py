"""
Order model and OrderBook for the V2 backtesting engine.

Implements the full order lifecycle:
  PENDING → SUBMITTED → PARTIALLY_FILLED / FILLED / CANCELLED / REJECTED / EXPIRED

Supports order types: MARKET, LIMIT, STOP, STOP_LIMIT
Supports time-in-force: GTC, GTD, IOC, FOK, DAY
Supports linked orders: OCO (one-cancels-other), bracket (entry + SL + TP)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ── Enums ───────────────────────────────────────────────────────────


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class TimeInForce(str, Enum):
    GTC = "GTC"     # Good till cancelled
    GTD = "GTD"     # Good till date/time
    IOC = "IOC"     # Immediate-or-cancel
    FOK = "FOK"     # Fill-or-kill
    DAY = "DAY"     # Day order — expires at session end


class OrderStatus(str, Enum):
    PENDING = "PENDING"             # Created but not yet submitted
    SUBMITTED = "SUBMITTED"         # Sent to execution engine
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"               # Fully filled
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class LinkedOrderType(str, Enum):
    """How this order is linked to another."""
    NONE = "NONE"
    OCO = "OCO"     # One-cancels-other (e.g., SL and TP for same position)
    OTO = "OTO"     # One-triggers-other (e.g., entry triggers SL/TP placement)
    BRACKET = "BRACKET"  # Entry + SL + TP as a unit


# ── Fill ────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Fill:
    """A single execution fill on an order."""
    fill_id: str
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    timestamp_ns: int
    commission: float = 0.0
    slippage: float = 0.0

    @property
    def cost(self) -> float:
        """Total cost impact of this fill (commission + slippage dollar value)."""
        return self.commission + abs(self.slippage * self.quantity)


# ── Order ───────────────────────────────────────────────────────────


@dataclass
class Order:
    """
    Represents a single order in the system.

    Supports the full lifecycle from creation through fill/cancellation.
    """
    # Identity
    order_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    symbol: str = ""

    # Core order spec
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.MARKET
    quantity: float = 0.0
    limit_price: float = 0.0       # For LIMIT and STOP_LIMIT orders
    stop_price: float = 0.0        # For STOP and STOP_LIMIT orders

    # Time management
    time_in_force: TimeInForce = TimeInForce.GTC
    expire_time_ns: int = 0        # For GTD orders

    # Order state
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    fills: list[Fill] = field(default_factory=list)

    # Timestamps
    created_ns: int = 0
    submitted_ns: int = 0
    last_updated_ns: int = 0

    # Linked orders (OCO/bracket)
    linked_type: LinkedOrderType = LinkedOrderType.NONE
    linked_order_ids: list[str] = field(default_factory=list)
    parent_order_id: str = ""      # For OTO: the order that triggered this one

    # Strategy metadata
    tag: str = ""                   # User-defined label (e.g., "SL", "TP1", "TP2")
    strategy_id: str = ""

    @property
    def remaining_quantity(self) -> float:
        return self.quantity - self.filled_quantity

    @property
    def is_active(self) -> bool:
        return self.status in (
            OrderStatus.PENDING,
            OrderStatus.SUBMITTED,
            OrderStatus.PARTIALLY_FILLED,
        )

    @property
    def is_buy(self) -> bool:
        return self.side == OrderSide.BUY

    @property
    def is_sell(self) -> bool:
        return self.side == OrderSide.SELL

    @property
    def is_market(self) -> bool:
        return self.order_type == OrderType.MARKET

    @property
    def is_limit(self) -> bool:
        return self.order_type == OrderType.LIMIT

    @property
    def is_stop(self) -> bool:
        return self.order_type == OrderType.STOP

    @property
    def is_stop_limit(self) -> bool:
        return self.order_type == OrderType.STOP_LIMIT

    @property
    def total_commission(self) -> float:
        return sum(f.commission for f in self.fills)

    @property
    def total_slippage(self) -> float:
        return sum(f.slippage for f in self.fills)

    def apply_fill(self, fill: Fill) -> None:
        """Apply a fill to this order, updating state."""
        if not self.is_active:
            raise ValueError(
                f"Cannot fill order {self.order_id} in status {self.status}"
            )
        if fill.quantity > self.remaining_quantity + 1e-10:
            raise ValueError(
                f"Fill qty {fill.quantity} exceeds remaining {self.remaining_quantity}"
            )

        # Update average fill price (weighted average)
        total_filled_value = self.avg_fill_price * self.filled_quantity
        total_filled_value += fill.price * fill.quantity
        self.filled_quantity += fill.quantity
        self.avg_fill_price = total_filled_value / self.filled_quantity

        self.fills.append(fill)
        self.last_updated_ns = fill.timestamp_ns

        # Update status
        if abs(self.filled_quantity - self.quantity) < 1e-10:
            self.status = OrderStatus.FILLED
        else:
            self.status = OrderStatus.PARTIALLY_FILLED

    def cancel(self, timestamp_ns: int, reason: str = "") -> None:
        """Cancel this order."""
        if not self.is_active:
            return  # Already terminal
        self.status = OrderStatus.CANCELLED
        self.last_updated_ns = timestamp_ns
        self.tag = reason if reason else self.tag

    def reject(self, timestamp_ns: int, reason: str = "") -> None:
        """Reject this order."""
        self.status = OrderStatus.REJECTED
        self.last_updated_ns = timestamp_ns
        self.tag = reason if reason else self.tag

    def submit(self, timestamp_ns: int) -> None:
        """Mark order as submitted."""
        self.status = OrderStatus.SUBMITTED
        self.submitted_ns = timestamp_ns
        self.last_updated_ns = timestamp_ns

    def to_dict(self) -> dict:
        """Serialize to dict for API/storage."""
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "quantity": self.quantity,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "time_in_force": self.time_in_force.value,
            "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "avg_fill_price": self.avg_fill_price,
            "created_ns": self.created_ns,
            "submitted_ns": self.submitted_ns,
            "tag": self.tag,
            "linked_type": self.linked_type.value,
            "linked_order_ids": self.linked_order_ids,
            "total_commission": self.total_commission,
            "total_slippage": self.total_slippage,
        }


# ── Order Factory ───────────────────────────────────────────────────


def market_order(
    symbol: str,
    side: OrderSide,
    quantity: float,
    timestamp_ns: int = 0,
    tag: str = "",
    strategy_id: str = "",
) -> Order:
    """Create a market order."""
    return Order(
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        created_ns=timestamp_ns,
        tag=tag,
        strategy_id=strategy_id,
    )


def limit_order(
    symbol: str,
    side: OrderSide,
    quantity: float,
    limit_price: float,
    time_in_force: TimeInForce = TimeInForce.GTC,
    timestamp_ns: int = 0,
    tag: str = "",
    strategy_id: str = "",
) -> Order:
    """Create a limit order."""
    return Order(
        symbol=symbol,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=limit_price,
        time_in_force=time_in_force,
        created_ns=timestamp_ns,
        tag=tag,
        strategy_id=strategy_id,
    )


def stop_order(
    symbol: str,
    side: OrderSide,
    quantity: float,
    stop_price: float,
    time_in_force: TimeInForce = TimeInForce.GTC,
    timestamp_ns: int = 0,
    tag: str = "",
    strategy_id: str = "",
) -> Order:
    """Create a stop (market) order."""
    return Order(
        symbol=symbol,
        side=side,
        order_type=OrderType.STOP,
        quantity=quantity,
        stop_price=stop_price,
        time_in_force=time_in_force,
        created_ns=timestamp_ns,
        tag=tag,
        strategy_id=strategy_id,
    )


def stop_limit_order(
    symbol: str,
    side: OrderSide,
    quantity: float,
    stop_price: float,
    limit_price: float,
    time_in_force: TimeInForce = TimeInForce.GTC,
    timestamp_ns: int = 0,
    tag: str = "",
    strategy_id: str = "",
) -> Order:
    """Create a stop-limit order."""
    return Order(
        symbol=symbol,
        side=side,
        order_type=OrderType.STOP_LIMIT,
        quantity=quantity,
        stop_price=stop_price,
        limit_price=limit_price,
        time_in_force=time_in_force,
        created_ns=timestamp_ns,
        tag=tag,
        strategy_id=strategy_id,
    )


def bracket_order(
    symbol: str,
    side: OrderSide,
    quantity: float,
    entry_price: float = 0.0,
    stop_loss_price: float = 0.0,
    take_profit_price: float = 0.0,
    take_profit_2_price: float = 0.0,
    lot_split: tuple[float, float] | None = None,
    timestamp_ns: int = 0,
    tag: str = "",
    strategy_id: str = "",
) -> list[Order]:
    """Create a bracket order: entry + stop loss + take profit(s).

    Returns a list of orders linked via OCO/OTO relationships:
      - Entry order (MARKET at entry_price, or MARKET if entry_price=0)
      - SL order (STOP) — linked OCO with TP
      - TP1 order (LIMIT) — linked OCO with SL
      - TP2 order (LIMIT, optional) — if take_profit_2_price and lot_split provided

    The SL and TP orders are PENDING until the entry fills (OTO relationship),
    then they become SUBMITTED and are linked as OCO (one cancels the other).
    """
    # Entry order
    if entry_price > 0:
        entry = limit_order(
            symbol=symbol, side=side, quantity=quantity,
            limit_price=entry_price, timestamp_ns=timestamp_ns,
            tag=tag or "ENTRY", strategy_id=strategy_id,
        )
    else:
        entry = market_order(
            symbol=symbol, side=side, quantity=quantity,
            timestamp_ns=timestamp_ns, tag=tag or "ENTRY",
            strategy_id=strategy_id,
        )
    entry.linked_type = LinkedOrderType.BRACKET

    # Exit side is opposite of entry
    exit_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY

    orders = [entry]

    # Determine quantities for TP1 and TP2
    if lot_split and take_profit_2_price > 0:
        qty1 = round(quantity * lot_split[0], 8)
        qty2 = round(quantity * lot_split[1], 8)
    else:
        qty1 = quantity
        qty2 = 0.0

    # Stop loss
    if stop_loss_price > 0:
        sl = stop_order(
            symbol=symbol, side=exit_side, quantity=quantity,
            stop_price=stop_loss_price, timestamp_ns=timestamp_ns,
            tag="SL", strategy_id=strategy_id,
        )
        sl.linked_type = LinkedOrderType.OCO
        sl.parent_order_id = entry.order_id
        orders.append(sl)

    # Take profit 1
    if take_profit_price > 0:
        tp1 = limit_order(
            symbol=symbol, side=exit_side, quantity=qty1,
            limit_price=take_profit_price, timestamp_ns=timestamp_ns,
            tag="TP1", strategy_id=strategy_id,
        )
        tp1.linked_type = LinkedOrderType.OCO
        tp1.parent_order_id = entry.order_id
        orders.append(tp1)

    # Take profit 2
    if take_profit_2_price > 0 and qty2 > 0:
        tp2 = limit_order(
            symbol=symbol, side=exit_side, quantity=qty2,
            limit_price=take_profit_2_price, timestamp_ns=timestamp_ns,
            tag="TP2", strategy_id=strategy_id,
        )
        tp2.linked_type = LinkedOrderType.OCO
        tp2.parent_order_id = entry.order_id
        orders.append(tp2)

    # Link all exit orders as OCO group
    exit_ids = [o.order_id for o in orders[1:]]
    for o in orders[1:]:
        o.linked_order_ids = [oid for oid in exit_ids if oid != o.order_id]

    # Entry triggers exits (OTO)
    entry.linked_order_ids = exit_ids

    return orders


# ── OrderBook ───────────────────────────────────────────────────────


class OrderBook:
    """
    Manages all orders in the system.

    Provides lookup by ID, filtering by status/symbol, and OCO cancellation.
    """

    def __init__(self):
        self._orders: dict[str, Order] = {}
        self._active_by_symbol: dict[str, list[str]] = {}

    @property
    def all_orders(self) -> list[Order]:
        return list(self._orders.values())

    @property
    def active_orders(self) -> list[Order]:
        return [o for o in self._orders.values() if o.is_active]

    def add(self, order: Order) -> None:
        """Add an order to the book."""
        self._orders[order.order_id] = order
        if order.symbol not in self._active_by_symbol:
            self._active_by_symbol[order.symbol] = []
        self._active_by_symbol[order.symbol].append(order.order_id)

    def get(self, order_id: str) -> Optional[Order]:
        """Get an order by ID."""
        return self._orders.get(order_id)

    def get_active_for_symbol(self, symbol: str) -> list[Order]:
        """Get all active orders for a symbol."""
        ids = self._active_by_symbol.get(symbol, [])
        return [
            self._orders[oid] for oid in ids
            if oid in self._orders and self._orders[oid].is_active
        ]

    def get_active_by_tag(self, symbol: str, tag: str) -> list[Order]:
        """Get active orders for a symbol with a specific tag."""
        return [
            o for o in self.get_active_for_symbol(symbol)
            if o.tag == tag
        ]

    def cancel_linked(self, order: Order, timestamp_ns: int) -> list[Order]:
        """Cancel all OCO-linked orders when one fills or cancels.

        Returns the list of orders that were cancelled.
        """
        cancelled = []
        for linked_id in order.linked_order_ids:
            linked = self.get(linked_id)
            if linked and linked.is_active:
                linked.cancel(timestamp_ns, reason=f"OCO: {order.order_id} filled")
                cancelled.append(linked)
        return cancelled

    def activate_oto_children(self, parent_order: Order, timestamp_ns: int) -> list[Order]:
        """When a parent (entry) order fills, activate its OTO children.

        Returns the list of newly activated orders.
        """
        activated = []
        for child_id in parent_order.linked_order_ids:
            child = self.get(child_id)
            if child and child.status == OrderStatus.PENDING:
                child.submit(timestamp_ns)
                activated.append(child)
        return activated

    def cancel_all_for_symbol(self, symbol: str, timestamp_ns: int) -> list[Order]:
        """Cancel all active orders for a symbol."""
        cancelled = []
        for order in self.get_active_for_symbol(symbol):
            order.cancel(timestamp_ns, reason="cancel_all")
            cancelled.append(order)
        return cancelled

    def cleanup_inactive(self) -> None:
        """Remove inactive order IDs from the per-symbol active index."""
        for symbol in self._active_by_symbol:
            self._active_by_symbol[symbol] = [
                oid for oid in self._active_by_symbol[symbol]
                if oid in self._orders and self._orders[oid].is_active
            ]

    def count_active(self, symbol: str = "") -> int:
        """Count active orders, optionally filtered by symbol."""
        if symbol:
            return len(self.get_active_for_symbol(symbol))
        return len(self.active_orders)

    def to_dict_list(self) -> list[dict]:
        """Serialize all orders for API/storage."""
        return [o.to_dict() for o in self._orders.values()]
