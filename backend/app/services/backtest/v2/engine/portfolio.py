"""
Portfolio manager for the V2 backtesting engine.

Manages:
  - Cash balance and margin accounting
  - Position book (delegates to PositionBook)
  - Equity curve tracking
  - Multi-symbol capital allocation
  - Portfolio-level risk metrics (exposure, margin usage)

Key differences from V1:
  - V1 had a single `balance` float; V2 has proper cash/margin/equity separation
  - V1 tracked equity inline in the bar loop; V2 uses snapshot-on-demand
  - V2 supports multi-symbol from day one
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.services.backtest.v2.engine.order import Fill, OrderSide
from app.services.backtest.v2.engine.position import (
    ClosedTrade,
    Position,
    PositionBook,
)


# ── Margin Model ────────────────────────────────────────────────────


class MarginModel:
    """Computes margin requirements for positions.

    Default: CFD/Forex model where margin = notional * margin_rate.
    Override for equity model (margin = full notional).
    """

    def __init__(self, default_margin_rate: float = 0.01):
        """
        Args:
            default_margin_rate: Fraction of notional required as margin.
                e.g., 0.01 = 100:1 leverage (1% margin).
                     1.0 = no leverage (stocks).
        """
        self.default_margin_rate = default_margin_rate
        self._symbol_rates: dict[str, float] = {}

    def set_rate(self, symbol: str, rate: float) -> None:
        """Set a symbol-specific margin rate."""
        self._symbol_rates[symbol] = rate

    def required_margin(self, symbol: str, quantity: float, price: float, point_value: float = 1.0) -> float:
        """Calculate margin required to hold a position."""
        rate = self._symbol_rates.get(symbol, self.default_margin_rate)
        return abs(quantity) * price * point_value * rate

    def required_margin_for_order(
        self,
        symbol: str,
        quantity: float,
        price: float,
        point_value: float,
        current_position_qty: float,
    ) -> float:
        """Calculate additional margin required for a new order.

        If the order reduces the position, no additional margin is needed.
        If it increases or opens a new position, margin = incremental notional * rate.
        """
        new_qty = abs(current_position_qty + quantity)
        old_qty = abs(current_position_qty)
        incremental = max(0, new_qty - old_qty)
        return self.required_margin(symbol, incremental, price, point_value)


# ── Portfolio ───────────────────────────────────────────────────────


@dataclass
class EquitySnapshot:
    """A single point on the equity curve."""
    timestamp_ns: int = 0
    bar_index: int = 0
    cash: float = 0.0
    unrealized_pnl: float = 0.0
    total_equity: float = 0.0
    margin_used: float = 0.0


class Portfolio:
    """
    Central portfolio manager.

    Tracks cash, positions, margin, and equity over time.
    Multi-symbol ready: a single Portfolio manages positions across all symbols.
    """

    def __init__(
        self,
        initial_cash: float = 10000.0,
        margin_rate: float = 0.01,
        point_values: Optional[dict[str, float]] = None,
        commission_per_lot: float = 0.0,
        spread_points: float = 0.0,
    ):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.commission_per_lot = commission_per_lot
        self.spread_points = spread_points

        self.margin_model = MarginModel(default_margin_rate=margin_rate)
        self.position_book = PositionBook(point_values=point_values)

        # Equity tracking
        self._equity_snapshots: list[EquitySnapshot] = []
        self._equity_values: list[float] = [initial_cash]  # Simple float list for perf

        # Running stats
        self._peak_equity: float = initial_cash
        self._max_drawdown: float = 0.0
        self._max_drawdown_pct: float = 0.0
        self._total_commission: float = 0.0
        self._total_slippage: float = 0.0
        self._total_fills: int = 0

    # ── Properties ──────────────────────────────────────────────────

    @property
    def equity_curve(self) -> list[float]:
        """Simple equity curve as list of floats (one per bar)."""
        return self._equity_values

    @property
    def closed_trades(self) -> list[ClosedTrade]:
        return self.position_book.closed_trades

    @property
    def total_commission(self) -> float:
        return self._total_commission

    @property
    def total_slippage(self) -> float:
        return self._total_slippage

    @property
    def max_drawdown(self) -> float:
        return self._max_drawdown

    @property
    def max_drawdown_pct(self) -> float:
        return self._max_drawdown_pct

    @property
    def net_profit(self) -> float:
        return self.cash - self.initial_cash + self.position_book.total_realized_pnl()

    # ── Core Operations ─────────────────────────────────────────────

    def apply_fill(
        self,
        fill: Fill,
        bar_index: int = 0,
        exit_reason: str = "",
    ) -> Optional[ClosedTrade]:
        """Process a fill: update position, adjust cash, track costs.

        Returns a ClosedTrade if any portion of the position was closed.
        """
        # Track costs
        self._total_commission += fill.commission
        self._total_slippage += abs(fill.slippage)
        self._total_fills += 1

        # Delegate to position book
        closed = self.position_book.apply_fill(fill, bar_index, exit_reason)

        # Adjust cash for PnL from closed portion
        if closed:
            self.cash += closed.pnl

        # Deduct commission from cash (always)
        self.cash -= fill.commission

        return closed

    def calculate_commission(self, quantity: float) -> float:
        """Calculate round-trip commission for a given quantity."""
        return self.commission_per_lot * quantity * 2

    def calculate_spread_cost(self, quantity: float, point_value: float) -> float:
        """Calculate spread cost in cash terms."""
        return self.spread_points * point_value * quantity

    def snapshot_equity(
        self,
        prices: dict[str, float],
        timestamp_ns: int = 0,
        bar_index: int = 0,
    ) -> float:
        """Take an equity snapshot at the current bar.

        Calculates total equity = cash + unrealized PnL.
        Updates drawdown tracking.
        Returns total equity.
        """
        unrealized = self.position_book.total_unrealized_pnl(prices)
        total_equity = self.cash + unrealized

        # Calculate margin used
        margin_used = 0.0
        for symbol, pos in self.position_book.positions.items():
            if not pos.is_flat and symbol in prices:
                margin_used += self.margin_model.required_margin(
                    symbol, pos.quantity, prices[symbol], pos.point_value
                )

        # Store snapshot
        snap = EquitySnapshot(
            timestamp_ns=timestamp_ns,
            bar_index=bar_index,
            cash=self.cash,
            unrealized_pnl=unrealized,
            total_equity=total_equity,
            margin_used=margin_used,
        )
        self._equity_snapshots.append(snap)
        self._equity_values.append(total_equity)

        # Drawdown tracking
        if total_equity > self._peak_equity:
            self._peak_equity = total_equity
        dd = self._peak_equity - total_equity
        dd_pct = (dd / self._peak_equity * 100) if self._peak_equity > 0 else 0.0
        if dd > self._max_drawdown:
            self._max_drawdown = dd
        if dd_pct > self._max_drawdown_pct:
            self._max_drawdown_pct = dd_pct

        return total_equity

    def force_close_all(
        self,
        prices: dict[str, float],
        timestamp_ns: int,
        bar_index: int,
        reason: str = "end_of_data",
    ) -> list[ClosedTrade]:
        """Force-close all open positions. Returns list of closed trades."""
        closed_list = self.position_book.force_close_all(
            prices, timestamp_ns, bar_index, reason
        )
        for ct in closed_list:
            self.cash += ct.pnl
        return closed_list

    # ── Queries ─────────────────────────────────────────────────────

    def get_position(self, symbol: str) -> Position:
        """Get position for a symbol (creates flat if not exists)."""
        return self.position_book.get_position(symbol)

    def has_position(self, symbol: str) -> bool:
        """Check if there is a non-flat position for a symbol."""
        pos = self.position_book.positions.get(symbol)
        return pos is not None and not pos.is_flat

    def open_position_count(self) -> int:
        """Number of symbols with open positions."""
        return len(self.position_book.open_symbols)

    def total_exposure(self, prices: dict[str, float]) -> float:
        """Total notional exposure across all positions."""
        return self.position_book.total_notional()

    def exposure_pct(self, prices: dict[str, float]) -> float:
        """Total exposure as % of equity."""
        equity = self.cash + self.position_book.total_unrealized_pnl(prices)
        if equity <= 0:
            return 0.0
        return (self.position_book.total_notional() / equity) * 100

    def available_cash(self) -> float:
        """Cash available for new orders (cash minus margin held)."""
        margin_used = 0.0
        for symbol, pos in self.position_book.positions.items():
            if not pos.is_flat:
                margin_used += self.margin_model.required_margin(
                    symbol, pos.quantity, pos.avg_entry_price, pos.point_value
                )
        return max(0, self.cash - margin_used)

    def can_afford_order(
        self,
        symbol: str,
        quantity: float,
        price: float,
        point_value: float = 1.0,
    ) -> bool:
        """Check if there's enough cash/margin for an order."""
        pos = self.position_book.positions.get(symbol)
        current_qty = pos.signed_quantity if pos else 0.0

        additional_margin = self.margin_model.required_margin_for_order(
            symbol, quantity, price, point_value, current_qty
        )
        return self.available_cash() >= additional_margin

    # ── Serialization ───────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize for API/storage."""
        return {
            "initial_cash": self.initial_cash,
            "cash": round(self.cash, 4),
            "total_equity": round(self._equity_values[-1] if self._equity_values else self.initial_cash, 4),
            "max_drawdown": round(self._max_drawdown, 4),
            "max_drawdown_pct": round(self._max_drawdown_pct, 4),
            "total_commission": round(self._total_commission, 4),
            "total_slippage": round(self._total_slippage, 4),
            "total_fills": self._total_fills,
            "positions": self.position_book.to_dict(),
        }
