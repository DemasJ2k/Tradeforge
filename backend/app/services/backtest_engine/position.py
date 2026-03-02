"""
Position — Tracks open positions and computes PnL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .instrument import Instrument


@dataclass
class Position:
    """Tracks a single position in one instrument."""
    symbol: str
    instrument: Instrument
    side: str = ""           # "long" or "short" or "" (flat)
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    total_commission: float = 0.0
    entry_bar_index: int = -1
    entry_timestamp: float = 0.0
    realized_pnl: float = 0.0

    # Bracket tracking
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0
    trailing_stop_offset: float = 0.0

    @property
    def is_flat(self) -> bool:
        return self.quantity == 0.0 or self.side == ""

    @property
    def is_long(self) -> bool:
        return self.side == "long" and self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.side == "short" and self.quantity > 0

    def unrealized_pnl(self, current_price: float) -> float:
        """Compute unrealized P&L at current price."""
        if self.is_flat:
            return 0.0

        pv = self.instrument.point_value
        if self.is_long:
            return (current_price - self.avg_entry_price) * self.quantity * pv
        else:
            return (self.avg_entry_price - current_price) * self.quantity * pv

    def margin_required(self) -> float:
        """Compute margin required for this position."""
        if self.is_flat:
            return 0.0
        notional = self.quantity * self.instrument.lot_size * self.avg_entry_price
        return notional * self.instrument.margin_rate

    def add(self, quantity: float, price: float, commission: float = 0.0) -> None:
        """Add to existing position (or open new)."""
        if self.is_flat:
            self.avg_entry_price = price
            self.quantity = quantity
        else:
            # Average in
            total_cost = self.avg_entry_price * self.quantity + price * quantity
            self.quantity += quantity
            if self.quantity > 0:
                self.avg_entry_price = total_cost / self.quantity
        self.total_commission += commission

    def reduce(self, quantity: float, price: float, commission: float = 0.0) -> float:
        """Reduce position and return realized PnL from the reduction."""
        if self.is_flat:
            return 0.0

        reduce_qty = min(quantity, self.quantity)
        pv = self.instrument.point_value

        if self.is_long:
            pnl = (price - self.avg_entry_price) * reduce_qty * pv
        else:
            pnl = (self.avg_entry_price - price) * reduce_qty * pv

        pnl -= commission
        self.realized_pnl += pnl
        self.total_commission += commission
        self.quantity -= reduce_qty

        if self.quantity <= 1e-10:
            self.quantity = 0.0
            self.side = ""
            self.avg_entry_price = 0.0

        return pnl

    def close(self, price: float, commission: float = 0.0) -> float:
        """Close entire position. Returns realized PnL."""
        return self.reduce(self.quantity, price, commission)

    def flip(self, new_side: str, quantity: float, price: float,
             commission: float = 0.0) -> float:
        """Close current position and open opposite. Returns PnL from close."""
        pnl = self.close(price, commission / 2)
        self.side = new_side
        self.quantity = quantity
        self.avg_entry_price = price
        self.total_commission += commission / 2
        self.entry_bar_index = -1  # Will be set by engine
        return pnl


@dataclass
class Portfolio:
    """Manages overall account balance, equity, and multiple positions."""
    initial_balance: float = 10_000.0
    balance: float = 0.0          # Cash balance (realized)
    _positions: dict[str, Position] = field(default_factory=dict)
    equity_curve: list[float] = field(default_factory=list)
    _peak_equity: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0

    def __post_init__(self):
        if self.balance == 0.0:
            self.balance = self.initial_balance
        self._peak_equity = self.balance

    def get_position(self, symbol: str) -> Optional[Position]:
        return self._positions.get(symbol)

    def get_or_create_position(self, symbol: str, instrument: Instrument) -> Position:
        if symbol not in self._positions:
            self._positions[symbol] = Position(symbol=symbol, instrument=instrument)
        return self._positions[symbol]

    @property
    def positions(self) -> dict[str, Position]:
        return self._positions

    def equity(self, prices: dict[str, float]) -> float:
        """Current equity = balance + sum of unrealized PnL."""
        unrealized = sum(
            pos.unrealized_pnl(prices.get(pos.symbol, pos.avg_entry_price))
            for pos in self._positions.values()
            if not pos.is_flat
        )
        return self.balance + unrealized

    def total_margin(self) -> float:
        """Total margin used across all positions."""
        return sum(pos.margin_required() for pos in self._positions.values())

    def free_margin(self, prices: dict[str, float]) -> float:
        """Available margin for new trades."""
        return self.equity(prices) - self.total_margin()

    def snapshot(self, prices: dict[str, float]) -> float:
        """Take equity snapshot and update drawdown tracking."""
        eq = self.equity(prices)
        self.equity_curve.append(eq)

        if eq > self._peak_equity:
            self._peak_equity = eq

        if self._peak_equity > 0:
            dd = self._peak_equity - eq
            dd_pct = dd / self._peak_equity * 100
            if dd > self.max_drawdown:
                self.max_drawdown = dd
            if dd_pct > self.max_drawdown_pct:
                self.max_drawdown_pct = dd_pct

        return eq

    def apply_pnl(self, pnl: float) -> None:
        """Apply realized PnL to balance."""
        self.balance += pnl

    def reset(self) -> None:
        """Reset portfolio to initial state."""
        self.balance = self.initial_balance
        self._positions.clear()
        self.equity_curve.clear()
        self._peak_equity = self.initial_balance
        self.max_drawdown = 0.0
        self.max_drawdown_pct = 0.0
