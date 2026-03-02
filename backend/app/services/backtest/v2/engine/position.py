"""
Position and PositionBook for the V2 backtesting engine.

A Position represents an open (or closed) directional exposure in a symbol.
It tracks multiple fills, computes average entry, realized/unrealized PnL,
and supports partial closes.

Key differences from V1:
  - Proper multi-fill tracking (V1 had a flat entry_price)
  - Partial close support (V1 was all-or-nothing)
  - Position aggregation by symbol (V1 tracked individual Trade objects)
  - Separate realized vs unrealized PnL accounting
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app.services.backtest.v2.engine.order import Fill, OrderSide


class PositionSide(str, Enum):
    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class ClosedTrade:
    """A completed round-trip trade (entry → exit).

    Produced when a position is partially or fully closed.
    This is the V2 equivalent of V1's Trade dataclass,
    but enriched with fill-level detail.
    """
    trade_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    symbol: str = ""
    side: str = ""           # "long" or "short"
    quantity: float = 0.0
    entry_price: float = 0.0
    exit_price: float = 0.0
    entry_time_ns: int = 0
    exit_time_ns: int = 0
    entry_bar_index: int = 0
    exit_bar_index: int = 0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    commission: float = 0.0
    slippage: float = 0.0
    exit_reason: str = ""    # "stop_loss", "take_profit", "exit_signal", "end_of_data", etc.
    duration_bars: int = 0

    @property
    def is_winner(self) -> bool:
        return self.pnl > 0

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "entry_price": round(self.entry_price, 6),
            "exit_price": round(self.exit_price, 6),
            "entry_time_ns": self.entry_time_ns,
            "exit_time_ns": self.exit_time_ns,
            "entry_bar_index": self.entry_bar_index,
            "exit_bar_index": self.exit_bar_index,
            "pnl": round(self.pnl, 4),
            "pnl_pct": round(self.pnl_pct, 4),
            "commission": round(self.commission, 4),
            "slippage": round(self.slippage, 4),
            "exit_reason": self.exit_reason,
            "duration_bars": self.duration_bars,
        }


@dataclass
class Position:
    """
    An open position in a single symbol.

    Tracks the net exposure, average entry price, and all fills.
    Supports partial closes and computes realized/unrealized PnL.
    """
    symbol: str = ""
    side: PositionSide = PositionSide.FLAT
    quantity: float = 0.0          # Absolute (always positive), 0 = flat
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0     # Accumulated PnL from closed portions
    total_commission: float = 0.0
    total_slippage: float = 0.0

    # Tracking
    entry_fills: list[Fill] = field(default_factory=list)
    exit_fills: list[Fill] = field(default_factory=list)
    first_entry_ns: int = 0        # Timestamp of first fill
    first_entry_bar: int = 0       # Bar index of first fill
    last_update_ns: int = 0

    # Point value for PnL calculation (e.g., 100 for gold futures)
    point_value: float = 1.0

    @property
    def is_flat(self) -> bool:
        return self.quantity < 1e-10

    @property
    def is_long(self) -> bool:
        return self.side == PositionSide.LONG and not self.is_flat

    @property
    def is_short(self) -> bool:
        return self.side == PositionSide.SHORT and not self.is_flat

    @property
    def signed_quantity(self) -> float:
        """Positive for long, negative for short."""
        if self.side == PositionSide.LONG:
            return self.quantity
        elif self.side == PositionSide.SHORT:
            return -self.quantity
        return 0.0

    @property
    def notional_value(self) -> float:
        """Total notional = qty * avg_entry * point_value."""
        return self.quantity * self.avg_entry_price * self.point_value

    def unrealized_pnl(self, current_price: float) -> float:
        """Compute unrealized PnL at a given market price."""
        if self.is_flat:
            return 0.0
        if self.side == PositionSide.LONG:
            return (current_price - self.avg_entry_price) * self.quantity * self.point_value
        else:
            return (self.avg_entry_price - current_price) * self.quantity * self.point_value

    def unrealized_pnl_pct(self, current_price: float) -> float:
        """Unrealized PnL as percentage of entry notional."""
        if self.is_flat or self.avg_entry_price == 0:
            return 0.0
        return self.unrealized_pnl(current_price) / self.notional_value * 100

    def apply_fill(
        self,
        fill: Fill,
        bar_index: int = 0,
    ) -> Optional[ClosedTrade]:
        """Apply a fill to this position.

        If the fill increases the position → updates avg entry.
        If the fill reduces the position → produces a ClosedTrade.
        If the fill flips the position → produces a ClosedTrade for the close,
            then starts a new position in the opposite direction.

        Returns a ClosedTrade if any portion was closed, else None.
        """
        is_increasing = self._is_increasing_fill(fill)
        closed_trade = None

        if self.is_flat:
            # Opening a new position
            self._open(fill, bar_index)

        elif is_increasing:
            # Adding to existing position — update weighted avg entry
            total_cost = self.avg_entry_price * self.quantity + fill.price * fill.quantity
            self.quantity += fill.quantity
            self.avg_entry_price = total_cost / self.quantity
            self.entry_fills.append(fill)
            self.total_commission += fill.commission
            self.total_slippage += abs(fill.slippage)

        else:
            # Reducing or closing or flipping
            close_qty = min(fill.quantity, self.quantity)
            remaining_fill_qty = fill.quantity - close_qty

            # Produce ClosedTrade for the closed portion
            closed_trade = self._close_portion(fill, close_qty, bar_index)

            # Reduce position
            self.quantity -= close_qty
            if self.quantity < 1e-10:
                self.quantity = 0.0
                self.side = PositionSide.FLAT
                self.avg_entry_price = 0.0

            # If fill quantity exceeds position → flip
            if remaining_fill_qty > 1e-10:
                # Create synthetic fill for the flip portion
                flip_fill = Fill(
                    fill_id=fill.fill_id + "_flip",
                    order_id=fill.order_id,
                    symbol=fill.symbol,
                    side=fill.side,
                    quantity=remaining_fill_qty,
                    price=fill.price,
                    timestamp_ns=fill.timestamp_ns,
                    commission=0.0,  # commission already accounted
                    slippage=0.0,
                )
                self._open(flip_fill, bar_index)

        self.last_update_ns = fill.timestamp_ns
        return closed_trade

    def force_close(
        self,
        price: float,
        timestamp_ns: int,
        bar_index: int,
        reason: str = "end_of_data",
    ) -> Optional[ClosedTrade]:
        """Force-close the entire position at a given price.

        Used at end of backtest or for forced liquidation.
        """
        if self.is_flat:
            return None

        exit_side = OrderSide.SELL if self.is_long else OrderSide.BUY
        fill = Fill(
            fill_id=str(uuid.uuid4())[:12],
            order_id="force_close",
            symbol=self.symbol,
            side=exit_side,
            quantity=self.quantity,
            price=price,
            timestamp_ns=timestamp_ns,
            commission=0.0,
            slippage=0.0,
        )
        return self.apply_fill(fill, bar_index)

    def _is_increasing_fill(self, fill: Fill) -> bool:
        """Does this fill add to the current position direction?"""
        if self.is_flat:
            return True
        if self.is_long and fill.side == OrderSide.BUY:
            return True
        if self.is_short and fill.side == OrderSide.SELL:
            return True
        return False

    def _open(self, fill: Fill, bar_index: int) -> None:
        """Open a new position from flat."""
        self.side = PositionSide.LONG if fill.side == OrderSide.BUY else PositionSide.SHORT
        self.quantity = fill.quantity
        self.avg_entry_price = fill.price
        self.entry_fills = [fill]
        self.exit_fills = []
        self.first_entry_ns = fill.timestamp_ns
        self.first_entry_bar = bar_index
        self.total_commission = fill.commission
        self.total_slippage = abs(fill.slippage)
        self.realized_pnl = 0.0

    def _close_portion(
        self, fill: Fill, close_qty: float, bar_index: int
    ) -> ClosedTrade:
        """Close a portion of the position and produce a ClosedTrade."""
        if self.side == PositionSide.LONG:
            pnl = (fill.price - self.avg_entry_price) * close_qty * self.point_value
            side_str = "long"
        else:
            pnl = (self.avg_entry_price - fill.price) * close_qty * self.point_value
            side_str = "short"

        # Proportional commission
        portion_ratio = close_qty / (self.quantity if self.quantity > 0 else 1)
        close_commission = fill.commission
        close_slippage = abs(fill.slippage)

        pnl -= close_commission

        self.realized_pnl += pnl
        self.total_commission += close_commission
        self.total_slippage += close_slippage
        self.exit_fills.append(fill)

        entry_notional = self.avg_entry_price * close_qty * self.point_value
        pnl_pct = (pnl / entry_notional * 100) if entry_notional > 0 else 0.0

        return ClosedTrade(
            symbol=self.symbol,
            side=side_str,
            quantity=close_qty,
            entry_price=self.avg_entry_price,
            exit_price=fill.price,
            entry_time_ns=self.first_entry_ns,
            exit_time_ns=fill.timestamp_ns,
            entry_bar_index=self.first_entry_bar,
            exit_bar_index=bar_index,
            pnl=pnl,
            pnl_pct=pnl_pct,
            commission=close_commission,
            slippage=close_slippage,
            exit_reason=fill.order_id,  # Will be overridden by runner
            duration_bars=bar_index - self.first_entry_bar,
        )

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "avg_entry_price": round(self.avg_entry_price, 6),
            "realized_pnl": round(self.realized_pnl, 4),
            "total_commission": round(self.total_commission, 4),
            "first_entry_ns": self.first_entry_ns,
        }


# ── PositionBook ────────────────────────────────────────────────────


class PositionBook:
    """
    Manages positions across all symbols.

    Each symbol has at most one Position (net). Closed trades are accumulated.
    """

    def __init__(self, point_values: Optional[dict[str, float]] = None):
        """
        Args:
            point_values: Optional map of symbol → point value.
                          Defaults to 1.0 for all symbols.
        """
        self._positions: dict[str, Position] = {}
        self._closed_trades: list[ClosedTrade] = []
        self._point_values = point_values or {}

    @property
    def positions(self) -> dict[str, Position]:
        return self._positions

    @property
    def closed_trades(self) -> list[ClosedTrade]:
        return self._closed_trades

    @property
    def open_symbols(self) -> list[str]:
        """Symbols with non-flat positions."""
        return [s for s, p in self._positions.items() if not p.is_flat]

    def get_position(self, symbol: str) -> Position:
        """Get or create a position for a symbol."""
        if symbol not in self._positions:
            pv = self._point_values.get(symbol, 1.0)
            self._positions[symbol] = Position(symbol=symbol, point_value=pv)
        return self._positions[symbol]

    def apply_fill(
        self,
        fill: Fill,
        bar_index: int = 0,
        exit_reason: str = "",
    ) -> Optional[ClosedTrade]:
        """Apply a fill to the appropriate position.

        Returns a ClosedTrade if any portion was closed.
        """
        position = self.get_position(fill.symbol)
        closed = position.apply_fill(fill, bar_index)
        if closed:
            if exit_reason:
                closed.exit_reason = exit_reason
            self._closed_trades.append(closed)
        return closed

    def force_close_all(
        self,
        prices: dict[str, float],
        timestamp_ns: int,
        bar_index: int,
        reason: str = "end_of_data",
    ) -> list[ClosedTrade]:
        """Force-close all open positions at given prices."""
        closed_list = []
        for symbol, position in self._positions.items():
            if not position.is_flat and symbol in prices:
                closed = position.force_close(
                    prices[symbol], timestamp_ns, bar_index, reason
                )
                if closed:
                    closed.exit_reason = reason
                    self._closed_trades.append(closed)
                    closed_list.append(closed)
        return closed_list

    def total_unrealized_pnl(self, prices: dict[str, float]) -> float:
        """Sum of unrealized PnL across all positions."""
        total = 0.0
        for symbol, position in self._positions.items():
            if not position.is_flat and symbol in prices:
                total += position.unrealized_pnl(prices[symbol])
        return total

    def total_notional(self) -> float:
        """Sum of absolute notional values across all positions."""
        return sum(p.notional_value for p in self._positions.values() if not p.is_flat)

    def total_realized_pnl(self) -> float:
        """Sum of realized PnL from all closed trades."""
        return sum(t.pnl for t in self._closed_trades)

    def to_dict(self) -> dict:
        return {
            "positions": {s: p.to_dict() for s, p in self._positions.items() if not p.is_flat},
            "closed_trades_count": len(self._closed_trades),
            "total_realized_pnl": round(self.total_realized_pnl(), 4),
        }
