"""
Abstract base class for V2 backtesting strategies.

All user strategies inherit from StrategyBase and implement the event hooks.
The runner calls these hooks during the event loop.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from app.services.backtest.v2.engine.events import BarEvent, FillEvent, TickEvent
from app.services.backtest.v2.engine.order import (
    Order,
    OrderSide,
    OrderType,
    TimeInForce,
    market_order,
    limit_order,
    stop_order,
    stop_limit_order,
    bracket_order,
)

logger = logging.getLogger(__name__)


class StrategyContext:
    """
    Provides the strategy with controlled access to engine internals.

    The strategy never accesses the portfolio, order book, or data handler
    directly — it goes through this context (dependency injection). This
    keeps strategies testable and prevents unintended side-effects.
    """

    def __init__(self):
        # These are wired by the Runner at startup
        self._data_handler = None
        self._portfolio = None
        self._position_sizer = None  # PositionSizer (wired by Runner)
        self._order_queue: list[Order] = []  # Pending orders for this bar
        self._bar_index: int = 0

    # ── Read-only accessors ─────────────────────────────────────────

    @property
    def bar_index(self) -> int:
        return self._bar_index

    def get_value(self, symbol: str, field_id: str, bars_ago: int = 0) -> Optional[float]:
        """Get data value: price field, indicator, or numeric literal.

        Examples:
            ctx.get_value("XAUUSD", "price.close")
            ctx.get_value("XAUUSD", "sma_20", bars_ago=1)
        """
        if self._data_handler is None:
            return None
        idx = self._bar_index - bars_ago
        return self._data_handler.get_value(symbol, field_id, idx)

    def get_bar(self, symbol: str, bars_ago: int = 0):
        """Get a BarData object (OHLCV + indicators)."""
        if self._data_handler is None:
            return None
        idx = self._bar_index - bars_ago
        return self._data_handler.get_bar(symbol, idx)

    # ── Higher-Timeframe Access (Phase 1E) ──────────────────────────

    def get_htf_value(
        self,
        symbol: str,
        tf_label: str,
        field_id: str,
        bars_ago: int = 0,
    ) -> Optional[float]:
        """Get a value from a higher-timeframe series (no look-ahead).

        Must call ``DataHandler.add_htf(symbol, tf_label, ...)``
        during setup before using this method.

        Parameters
        ----------
        symbol : str
        tf_label : str
            E.g. "H1", "D1".
        field_id : str
            E.g. "price.close", "sma_20".
        bars_ago : int
            Additional HTF bars to look back (0 = most recent completed).
        """
        if self._data_handler is None:
            return None
        base_idx = self._bar_index
        # First get the aligned HTF bar index
        sd = self._data_handler.get_symbol_data(symbol)
        if sd is None:
            return None
        htf_sd = sd.htf_data.get(tf_label.upper())
        if htf_sd is None:
            return None
        htf_idx = sd.htf_bar_index_for(base_idx, tf_label)
        if htf_idx < 0:
            return None
        htf_idx -= bars_ago
        if htf_idx < 0 or htf_idx >= htf_sd.bar_count:
            return None
        return htf_sd.get_value(field_id, htf_idx)

    def get_htf_bar(
        self,
        symbol: str,
        tf_label: str,
        bars_ago: int = 0,
    ):
        """Get a complete HTF BarData (OHLCV + indicators), no look-ahead.

        Parameters
        ----------
        symbol : str
        tf_label : str
            E.g. "H1", "D1".
        bars_ago : int
            HTF bars to look back from the most recent completed bar.
        """
        if self._data_handler is None:
            return None
        sd = self._data_handler.get_symbol_data(symbol)
        if sd is None:
            return None
        htf_sd = sd.htf_data.get(tf_label.upper())
        if htf_sd is None:
            return None
        htf_idx = sd.htf_bar_index_for(self._bar_index, tf_label)
        if htf_idx < 0:
            return None
        htf_idx -= bars_ago
        if htf_idx < 0 or htf_idx >= htf_sd.bar_count:
            return None
        return htf_sd.get_bar(htf_idx)

    def get_position(self, symbol: str):
        """Get the current position for a symbol."""
        if self._portfolio is None:
            return None
        return self._portfolio.get_position(symbol)

    def get_equity(self) -> float:
        """Current equity (last snapshot or initial cash)."""
        if self._portfolio is None:
            return 0.0
        ec = self._portfolio.equity_curve
        return ec[-1] if ec else self._portfolio.initial_cash

    def get_cash(self) -> float:
        """Available cash."""
        if self._portfolio is None:
            return 0.0
        return self._portfolio.available_cash()

    def get_initial_capital(self) -> float:
        """Initial capital."""
        if self._portfolio is None:
            return 0.0
        return self._portfolio.initial_cash

    def get_position_count(self) -> int:
        """Number of open positions."""
        if self._portfolio is None:
            return 0
        return self._portfolio.open_position_count()

    def compute_position_size(
        self,
        symbol: str,
        entry_price: float,
        stop_loss: float = 0.0,
        direction: str = "long",
    ) -> float:
        """Compute lot size using the configured position sizing method.

        Delegates to the PositionSizer attached by the Runner.  If no sizer
        is configured, returns the fixed lot default (0.01).

        Parameters
        ----------
        symbol : str
            Instrument symbol (for contract_size lookup).
        entry_price : float
            Expected entry price.
        stop_loss : float
            Stop-loss price (required for PERCENT_RISK / KELLY).
        direction : str
            "long" or "short" — unused currently but reserved for asymmetric sizing.
        """
        if self._position_sizer is None:
            return 0.01  # safe fallback

        equity = self.get_equity()
        # Resolve instrument specs
        from app.services.backtest.v2.engine.instrument import get_instrument_spec
        spec = get_instrument_spec(symbol)
        return self._position_sizer.compute(
            equity=equity,
            entry_price=entry_price,
            stop_loss=stop_loss,
            contract_size=spec.contract_size,
            point_value=spec.point_value,
        )

    # ── Order submission ────────────────────────────────────────────

    def buy_market(
        self,
        symbol: str,
        quantity: float,
        tag: str = "",
        point_value: float = 1.0,
    ) -> Order:
        """Place a market BUY order."""
        order = market_order(symbol=symbol, side=OrderSide.BUY, quantity=quantity, tag=tag)
        self._order_queue.append(order)
        return order

    def sell_market(
        self,
        symbol: str,
        quantity: float,
        tag: str = "",
        point_value: float = 1.0,
    ) -> Order:
        """Place a market SELL order."""
        order = market_order(symbol=symbol, side=OrderSide.SELL, quantity=quantity, tag=tag)
        self._order_queue.append(order)
        return order

    def buy_limit(
        self,
        symbol: str,
        quantity: float,
        limit_price: float,
        tag: str = "",
        point_value: float = 1.0,
    ) -> Order:
        """Place a limit BUY order."""
        order = limit_order(symbol=symbol, side=OrderSide.BUY, quantity=quantity, limit_price=limit_price, tag=tag)
        self._order_queue.append(order)
        return order

    def sell_limit(
        self,
        symbol: str,
        quantity: float,
        limit_price: float,
        tag: str = "",
        point_value: float = 1.0,
    ) -> Order:
        """Place a limit SELL order."""
        order = limit_order(symbol=symbol, side=OrderSide.SELL, quantity=quantity, limit_price=limit_price, tag=tag)
        self._order_queue.append(order)
        return order

    def buy_stop(
        self,
        symbol: str,
        quantity: float,
        stop_price: float,
        tag: str = "",
        point_value: float = 1.0,
    ) -> Order:
        """Place a stop BUY order."""
        order = stop_order(symbol=symbol, side=OrderSide.BUY, quantity=quantity, stop_price=stop_price, tag=tag)
        self._order_queue.append(order)
        return order

    def sell_stop(
        self,
        symbol: str,
        quantity: float,
        stop_price: float,
        tag: str = "",
        point_value: float = 1.0,
    ) -> Order:
        """Place a stop SELL order."""
        order = stop_order(symbol=symbol, side=OrderSide.SELL, quantity=quantity, stop_price=stop_price, tag=tag)
        self._order_queue.append(order)
        return order

    def buy_bracket(
        self,
        symbol: str,
        quantity: float,
        entry_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        take_profit_2: Optional[float] = None,
        lot_split: tuple[float, float] = (1.0, 0.0),
        tag: str = "",
        point_value: float = 1.0,
    ) -> list[Order]:
        """Place a bracket BUY order (entry + SL + TP).

        If entry_price is None, uses market order for entry.
        """
        orders = bracket_order(
            symbol=symbol,
            side=OrderSide.BUY,
            quantity=quantity,
            entry_price=entry_price or 0.0,
            stop_loss_price=stop_loss or 0.0,
            take_profit_price=take_profit or 0.0,
            take_profit_2_price=take_profit_2 or 0.0,
            lot_split=lot_split if take_profit_2 else None,
            tag=tag,
        )
        self._order_queue.extend(orders)
        return orders

    def sell_bracket(
        self,
        symbol: str,
        quantity: float,
        entry_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        take_profit_2: Optional[float] = None,
        lot_split: tuple[float, float] = (1.0, 0.0),
        tag: str = "",
        point_value: float = 1.0,
    ) -> list[Order]:
        """Place a bracket SELL order (entry + SL + TP)."""
        orders = bracket_order(
            symbol=symbol,
            side=OrderSide.SELL,
            quantity=quantity,
            entry_price=entry_price or 0.0,
            stop_loss_price=stop_loss or 0.0,
            take_profit_price=take_profit or 0.0,
            take_profit_2_price=take_profit_2 or 0.0,
            lot_split=lot_split if take_profit_2 else None,
            tag=tag,
        )
        self._order_queue.extend(orders)
        return orders

    def cancel_order(self, order_id: str) -> None:
        """Request cancellation of an order."""
        # The runner processes this at the end of the bar
        self._cancel_requests.append(order_id)

    def close_position(self, symbol: str, tag: str = "") -> Optional[Order]:
        """Close the current position for a symbol with a market order."""
        pos = self.get_position(symbol)
        if pos is None or pos.is_flat:
            return None
        side = OrderSide.SELL if pos.is_long else OrderSide.BUY
        order = market_order(symbol=symbol, side=side, quantity=abs(pos.quantity), tag=tag or "close")
        self._order_queue.append(order)
        return order

    def close_all_positions(self, tag: str = "") -> list[Order]:
        """Close all open positions."""
        orders = []
        if self._portfolio is None:
            return orders
        for symbol, pos in self._portfolio.position_book.positions.items():
            if not pos.is_flat:
                o = self.close_position(symbol, tag)
                if o:
                    orders.append(o)
        return orders

    # ── Internal ────────────────────────────────────────────────────

    def _drain_orders(self) -> list[Order]:
        """Pop all pending orders (called by Runner)."""
        orders = self._order_queue.copy()
        self._order_queue.clear()
        return orders

    def _drain_cancel_requests(self) -> list[str]:
        """Pop all cancel requests (called by Runner)."""
        reqs = getattr(self, "_cancel_requests", []).copy()
        self._cancel_requests = []
        return reqs

    def _init_cancel_requests(self):
        """Ensure cancel list exists."""
        if not hasattr(self, "_cancel_requests"):
            self._cancel_requests: list[str] = []


class StrategyBase(ABC):
    """
    Abstract base for all V2 strategies.

    Lifecycle:
        1. Runner creates context, wires data_handler/portfolio
        2. Runner calls strategy.initialize(ctx)
        3. For each bar: Runner calls strategy.on_bar(event)
        4. When fills occur: strategy.on_fill(event)
        5. At end: strategy.on_end()

    Strategies submit orders by calling self.ctx.buy_market(...), etc.
    """

    def __init__(self, name: str = "", params: dict[str, Any] | None = None):
        self.name = name or self.__class__.__name__
        self.params: dict[str, Any] = params or {}
        self.ctx: StrategyContext = StrategyContext()

    def initialize(self, ctx: StrategyContext) -> None:
        """Called once before backtesting begins.

        Override to set up indicators, subscribe to symbols, etc.
        """
        self.ctx = ctx
        self.ctx._init_cancel_requests()
        self.on_init()

    def on_init(self) -> None:
        """User override point — called once at start."""
        pass

    @abstractmethod
    def on_bar(self, event: BarEvent) -> None:
        """Called on every new bar. Must be implemented by the strategy.

        Access data via self.ctx.get_value(), self.ctx.get_bar().
        Place orders via self.ctx.buy_market(), self.ctx.sell_bracket(), etc.
        """
        ...

    def on_tick(self, event: TickEvent) -> None:
        """Called on every tick (when tick data is available)."""
        pass

    def on_fill(self, event: FillEvent) -> None:
        """Called when an order is filled."""
        pass

    def on_order_rejected(self, order: Order, reason: str) -> None:
        """Called when a submitted order is rejected by risk manager."""
        pass

    def on_end(self) -> None:
        """Called once at the end of the backtest."""
        pass

    def __repr__(self) -> str:
        return f"Strategy({self.name}, params={self.params})"
