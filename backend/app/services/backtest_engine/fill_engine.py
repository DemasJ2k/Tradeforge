"""
Fill Engine — Intra-bar tick synthesis and order fill simulation.

Generates synthetic tick sequences from OHLCV bars to determine
accurate SL/TP fill order within a single bar.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .bar import Bar
from .order import Order, OrderType, OrderSide, OrderRole
from .instrument import Instrument


class TickMode(str, Enum):
    """How to synthesize ticks within a bar."""
    OHLC_4 = "ohlc_4"                 # O→H→L→C or O→L→H→C (pessimistic)
    OHLC_PESSIMISTIC = "ohlc_pessimistic"  # Always hit SL before TP
    BROWNIAN = "brownian"             # Random walk between OHLC extremes
    CLOSE_ONLY = "close_only"         # Only check at close (fastest, least accurate)


@dataclass
class FillResult:
    """Result of attempting to fill an order."""
    order: Order
    filled: bool = False
    fill_price: float = 0.0
    slippage: float = 0.0
    commission: float = 0.0
    tick_index: int = 0   # Which synthetic tick triggered the fill


class FillEngine:
    """Simulates order fills using intra-bar tick synthesis."""

    def __init__(
        self,
        tick_mode: TickMode = TickMode.OHLC_PESSIMISTIC,
        slippage_pct: float = 0.0,
        spread_points: float = 0.0,
    ):
        self.tick_mode = tick_mode
        self.slippage_pct = slippage_pct
        self.spread_points = spread_points

    def fill_market_order(self, order: Order, bar: Bar,
                          instrument: Instrument) -> FillResult:
        """Fill a market order at bar open with slippage."""
        fill_price = bar.open

        # Apply spread: buys fill at ask (open + half spread), sells at bid
        half_spread = self.spread_points * instrument.point_value / 2
        if order.is_buy:
            fill_price += half_spread
        else:
            fill_price -= half_spread

        # Apply slippage
        slippage = 0.0
        if self.slippage_pct > 0:
            slippage = fill_price * self.slippage_pct / 100.0
            if order.is_buy:
                fill_price += slippage
            else:
                fill_price -= slippage

        fill_price = instrument.round_price(fill_price)
        commission = instrument.compute_commission(order.quantity, fill_price)

        return FillResult(
            order=order,
            filled=True,
            fill_price=fill_price,
            slippage=slippage,
            commission=commission,
            tick_index=0,
        )

    def check_pending_orders(
        self, orders: list[Order], bar: Bar, prev_bar: Optional[Bar],
        instrument: Instrument, position_side: Optional[str] = None,
    ) -> list[FillResult]:
        """Check pending stop/limit orders against intra-bar tick sequence.

        Returns fills in the order they would occur within the bar.
        Uses pessimistic ordering when both SL and TP trigger in same bar.
        """
        if not orders:
            return []

        # Generate synthetic tick sequence
        ticks = self._generate_ticks(bar, prev_bar, orders, position_side)

        fills: list[FillResult] = []
        filled_ids: set[str] = set()

        for tick_idx, tick_price in enumerate(ticks):
            for order in orders:
                if order.id in filled_ids:
                    continue
                if not order.is_active:
                    continue

                triggered = self._check_trigger(order, tick_price, bar)
                if triggered:
                    fill_price = self._compute_fill_price(
                        order, tick_price, instrument
                    )
                    commission = instrument.compute_commission(
                        order.quantity, fill_price
                    )
                    slippage = abs(fill_price - tick_price)

                    fills.append(FillResult(
                        order=order,
                        filled=True,
                        fill_price=instrument.round_price(fill_price),
                        slippage=slippage,
                        commission=commission,
                        tick_index=tick_idx,
                    ))
                    filled_ids.add(order.id)

                    # If this order has an OCO partner, mark it for skip
                    if order.oco_id:
                        filled_ids.add(order.oco_id)

        return fills

    def _generate_ticks(
        self, bar: Bar, prev_bar: Optional[Bar],
        orders: list[Order], position_side: Optional[str],
    ) -> list[float]:
        """Generate synthetic tick prices within a bar."""

        if self.tick_mode == TickMode.CLOSE_ONLY:
            return [bar.close]

        if self.tick_mode == TickMode.BROWNIAN:
            return self._brownian_ticks(bar, num_ticks=10)

        if self.tick_mode in (TickMode.OHLC_4, TickMode.OHLC_PESSIMISTIC):
            return self._ohlc_ticks(bar, orders, position_side)

        return [bar.open, bar.high, bar.low, bar.close]

    def _ohlc_ticks(
        self, bar: Bar, orders: list[Order],
        position_side: Optional[str],
    ) -> list[float]:
        """Generate OHLC tick sequence with pessimistic SL/TP ordering.

        For a long position: O → L → H → C (hit SL first, then TP)
        For a short position: O → H → L → C (hit SL first, then TP)
        Neutral: O → H → L → C (default)
        """
        if self.tick_mode == TickMode.OHLC_PESSIMISTIC and position_side:
            if position_side == "long":
                # Long position: check low first (SL), then high (TP)
                return [bar.open, bar.low, bar.high, bar.close]
            elif position_side == "short":
                # Short position: check high first (SL), then low (TP)
                return [bar.open, bar.high, bar.low, bar.close]

        # Default OHLC-4: if close > open (bullish), go low first
        if bar.close >= bar.open:
            return [bar.open, bar.low, bar.high, bar.close]
        else:
            return [bar.open, bar.high, bar.low, bar.close]

    def _brownian_ticks(self, bar: Bar, num_ticks: int = 10) -> list[float]:
        """Generate Brownian motion ticks between OHLC extremes."""
        ticks = [bar.open]
        price = bar.open
        bar_range = bar.range
        if bar_range <= 0:
            return [bar.open, bar.close]

        for i in range(1, num_ticks - 1):
            step = random.gauss(0, bar_range / num_ticks)
            price = max(bar.low, min(bar.high, price + step))
            ticks.append(price)

        ticks.append(bar.close)
        return ticks

    def _check_trigger(self, order: Order, tick_price: float, bar: Bar) -> bool:
        """Check if a tick price triggers an order."""

        if order.order_type == OrderType.STOP:
            # Stop order: triggers when price crosses the stop price
            if order.is_buy:
                return tick_price >= order.price  # Buy stop: price rises to level
            else:
                return tick_price <= order.price  # Sell stop: price falls to level

        elif order.order_type == OrderType.LIMIT:
            # Limit order: triggers when price reaches or passes the limit
            if order.is_buy:
                return tick_price <= order.price  # Buy limit: price falls to level
            else:
                return tick_price >= order.price  # Sell limit: price rises to level

        elif order.order_type == OrderType.STOP_LIMIT:
            # First check stop trigger, then limit
            if order.is_buy:
                if tick_price >= order.stop_price:
                    return tick_price <= order.price
            else:
                if tick_price <= order.stop_price:
                    return tick_price >= order.price

        return False

    def _compute_fill_price(
        self, order: Order, trigger_price: float, instrument: Instrument,
    ) -> float:
        """Compute actual fill price with slippage."""
        fill_price = trigger_price

        # For stop orders, apply slippage in the adverse direction
        if order.order_type == OrderType.STOP and self.slippage_pct > 0:
            slip = fill_price * self.slippage_pct / 100.0
            if order.is_buy:
                fill_price += slip
            else:
                fill_price -= slip

        # For gap fills (price jumps past the order), fill at open
        if order.order_type == OrderType.STOP:
            if order.is_buy and fill_price > order.price:
                fill_price = max(fill_price, order.price)
            elif order.is_sell and fill_price < order.price:
                fill_price = min(fill_price, order.price)

        return fill_price

    def update_trailing_stop(
        self, order: Order, current_price: float, position_side: str,
    ) -> bool:
        """Update trailing stop trigger price. Returns True if trigger moved."""
        if order.trail_offset <= 0:
            return False

        if position_side == "long":
            new_trigger = current_price - order.trail_offset
            if new_trigger > order.trail_trigger:
                order.trail_trigger = new_trigger
                order.price = new_trigger
                return True
        elif position_side == "short":
            new_trigger = current_price + order.trail_offset
            if order.trail_trigger == 0 or new_trigger < order.trail_trigger:
                order.trail_trigger = new_trigger
                order.price = new_trigger
                return True

        return False
