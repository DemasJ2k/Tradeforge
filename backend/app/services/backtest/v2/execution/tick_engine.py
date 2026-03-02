"""
Intra-bar tick engine for the V2 backtesting engine.

Replaces the simple OHLC-bar order matching in runner.py with a tick-by-tick
simulation that walks a synthetic (or real) tick path within each bar.

Responsibilities:
    1. Generate or accept tick paths for each bar
    2. Walk ticks in sequence, checking pending orders at each tick
    3. Apply fill model (spread, slippage, impact) to fill prices
    4. Detect gaps and delegate to gap_handler for special fill rules
    5. Return a list of fills (order, price, tick_index) for the bar

Fill Rules per Order Type:
    MARKET       → fill at first tick (bar open) + fill model adjustments
    LIMIT BUY    → fill when tick.price ≤ limit_price  (fill at limit_price)
    LIMIT SELL   → fill when tick.price ≥ limit_price  (fill at limit_price)
    STOP BUY     → trigger when tick.price ≥ stop_price; fill at stop + slip
    STOP SELL    → trigger when tick.price ≤ stop_price; fill at stop + slip
    STOP_LIMIT   → trigger when stop touched; fill when limit achievable
    Gap rule     → if bar opens beyond stop, fill at open (not stop)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence

from app.services.backtest.v2.engine.events import BarEvent
from app.services.backtest.v2.engine.order import Order, OrderSide, OrderType, OrderStatus
from app.services.backtest.v2.execution.fill_model import (
    FillModel, FillContext, CompositeFillModel, make_default_fill_model,
)
from app.services.backtest.v2.execution.synthetic_ticks import (
    SyntheticTick, synthesize_ticks_from_bar, five_tick_ohlc,
)
from app.services.backtest.v2.execution.gap_handler import GapDetector, GapInfo

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# Tick resolution mode
# ────────────────────────────────────────────────────────────────────

class TickMode(str, Enum):
    """How intra-bar ticks are generated."""
    OHLC_FIVE = "ohlc_five"           # Minimal 5-tick path (fastest)
    BROWNIAN = "brownian"              # Full Brownian bridge (most realistic)
    REAL_TICK = "real_tick"            # External tick data (pass-through)


# ────────────────────────────────────────────────────────────────────
# Pending fill result
# ────────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class TickFillResult:
    """Result of matching a single order against the tick path."""
    order: Order
    fill_price: float            # Final adjusted price after fill model
    raw_price: float             # Price before fill model adjustments
    tick_index: int              # Which tick triggered the fill
    timestamp_ns: int            # Tick timestamp
    is_gap_fill: bool = False    # True if filled due to gap-through


# ────────────────────────────────────────────────────────────────────
# Tick Engine Configuration
# ────────────────────────────────────────────────────────────────────

@dataclass
class TickEngineConfig:
    """Configuration for the tick engine."""
    mode: TickMode = TickMode.OHLC_FIVE
    ticks_per_segment: int = 10         # For BROWNIAN mode
    volatility_factor: float = 0.3      # For BROWNIAN mode
    base_seed: int = 42                 # For reproducibility
    # Per-symbol spread in price points
    spreads: dict[str, float] = field(default_factory=dict)
    default_spread: float = 0.0


# ────────────────────────────────────────────────────────────────────
# Tick Engine
# ────────────────────────────────────────────────────────────────────

class TickEngine:
    """Intra-bar order matching engine using synthetic or real ticks.

    Usage:
        engine = TickEngine(fill_model=my_fill_model, config=cfg)
        fills = engine.process_bar(bar, pending_orders,
                                   prev_bar=last_bar, atr=14.5)
    """

    def __init__(
        self,
        fill_model: FillModel | None = None,
        config: TickEngineConfig | None = None,
    ):
        self.fill_model = fill_model or make_default_fill_model()
        self.config = config or TickEngineConfig()
        self.gap_detector = GapDetector()

    def process_bar(
        self,
        bar: BarEvent,
        pending_orders: list[Order],
        prev_bar: BarEvent | None = None,
        atr: float = 0.0,
        avg_volume: float = 0.0,
    ) -> list[TickFillResult]:
        """Match pending orders against ticks within this bar.

        Parameters
        ----------
        bar : BarEvent
            Current OHLCV bar.
        pending_orders : list[Order]
            Active orders that need to be checked for fills.
        prev_bar : BarEvent or None
            Previous bar (for gap detection).
        atr : float
            Current ATR value (for volatility slippage).
        avg_volume : float
            Average volume (for volume impact model).

        Returns
        -------
        list[TickFillResult]
            Fills that occurred during this bar, in tick order.
        """
        if not pending_orders:
            return []

        # 1. Detect gaps
        gap = self.gap_detector.detect(prev_bar, bar) if prev_bar else None

        # 2. Generate tick path
        ticks = self._generate_ticks(bar)

        # 3. Build fill context template for this bar
        spread = self.config.spreads.get(bar.symbol, self.config.default_spread)
        base_ctx = FillContext(
            symbol=bar.symbol,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            bar_index=bar.bar_index,
            atr=atr,
            avg_volume=avg_volume,
            spread=spread,
            is_maker=False,
        )

        # 4. Walk ticks and match orders
        fills: list[TickFillResult] = []
        remaining_orders = list(pending_orders)

        for tick in ticks:
            if not remaining_orders:
                break

            newly_filled: list[Order] = []
            for order in remaining_orders:
                result = self._try_fill_order(
                    order, tick, bar, gap, base_ctx,
                )
                if result is not None:
                    fills.append(result)
                    newly_filled.append(order)

            # Remove filled orders from the working set
            for filled_order in newly_filled:
                remaining_orders.remove(filled_order)

        return fills

    def process_market_order(
        self,
        order: Order,
        bar: BarEvent,
        atr: float = 0.0,
        avg_volume: float = 0.0,
    ) -> TickFillResult:
        """Fill a market order immediately at bar open.

        Market orders always fill at the open price plus fill model.
        """
        spread = self.config.spreads.get(bar.symbol, self.config.default_spread)
        ctx = FillContext(
            symbol=bar.symbol,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            bar_index=bar.bar_index,
            atr=atr,
            avg_volume=avg_volume,
            spread=spread,
            is_maker=False,
        )
        raw_price = bar.open
        fill_price = self.fill_model.adjust_price(raw_price, order, ctx)

        return TickFillResult(
            order=order,
            fill_price=fill_price,
            raw_price=raw_price,
            tick_index=0,
            timestamp_ns=bar.timestamp_ns,
            is_gap_fill=False,
        )

    # ── Internal: Tick Generation ───────────────────────────────────

    def _generate_ticks(self, bar: BarEvent) -> list[SyntheticTick]:
        """Generate tick path based on configured mode."""
        if self.config.mode == TickMode.OHLC_FIVE:
            return five_tick_ohlc(bar)
        elif self.config.mode == TickMode.BROWNIAN:
            return synthesize_ticks_from_bar(
                bar=bar,
                ticks_per_segment=self.config.ticks_per_segment,
                volatility_factor=self.config.volatility_factor,
                seed=self.config.base_seed + bar.bar_index,
            )
        else:
            # REAL_TICK mode — ticks provided externally, not generated here
            # Fall back to 5-tick for safety
            return five_tick_ohlc(bar)

    # ── Internal: Order Matching ────────────────────────────────────

    def _try_fill_order(
        self,
        order: Order,
        tick: SyntheticTick,
        bar: BarEvent,
        gap: GapInfo | None,
        base_ctx: FillContext,
    ) -> TickFillResult | None:
        """Attempt to fill an order at the given tick price.

        Returns a TickFillResult if the order should fill, None otherwise.
        """
        price = tick.price

        if order.order_type == OrderType.LIMIT:
            return self._check_limit(order, tick, bar, base_ctx)
        elif order.order_type == OrderType.STOP:
            return self._check_stop(order, tick, bar, gap, base_ctx)
        elif order.order_type == OrderType.STOP_LIMIT:
            return self._check_stop_limit(order, tick, bar, gap, base_ctx)
        else:
            # MARKET orders should be handled by process_market_order
            return None

    def _check_limit(
        self,
        order: Order,
        tick: SyntheticTick,
        bar: BarEvent,
        base_ctx: FillContext,
    ) -> TickFillResult | None:
        """Check if a limit order can fill at this tick.

        Limit orders fill at the limit price (price improvement possible
        on gap opens, but we use the limit price as the canonical fill).
        Limit orders are maker orders → is_maker=True for rebate.
        """
        if order.limit_price is None or order.limit_price <= 0:
            return None

        triggered = False
        if order.side == OrderSide.BUY and tick.price <= order.limit_price:
            triggered = True
        elif order.side == OrderSide.SELL and tick.price >= order.limit_price:
            triggered = True

        if not triggered:
            return None

        # Fill at limit price (with price improvement on gaps)
        raw_price = order.limit_price
        if order.side == OrderSide.BUY:
            raw_price = min(order.limit_price, tick.price)  # Better price OK
        else:
            raw_price = max(order.limit_price, tick.price)  # Better price OK

        # Maker context for rebate
        ctx = FillContext(
            symbol=base_ctx.symbol,
            open=base_ctx.open,
            high=base_ctx.high,
            low=base_ctx.low,
            close=base_ctx.close,
            volume=base_ctx.volume,
            bar_index=base_ctx.bar_index,
            atr=base_ctx.atr,
            avg_volume=base_ctx.avg_volume,
            spread=base_ctx.spread,
            is_maker=True,
        )

        fill_price = self.fill_model.adjust_price(raw_price, order, ctx)

        return TickFillResult(
            order=order,
            fill_price=fill_price,
            raw_price=raw_price,
            tick_index=tick.tick_index,
            timestamp_ns=tick.timestamp_ns,
        )

    def _check_stop(
        self,
        order: Order,
        tick: SyntheticTick,
        bar: BarEvent,
        gap: GapInfo | None,
        base_ctx: FillContext,
    ) -> TickFillResult | None:
        """Check if a stop (market) order triggers at this tick.

        Stop orders trigger when price crosses the stop level.
        On gap-through: fill at bar open (not stop price).
        """
        if order.stop_price is None or order.stop_price <= 0:
            return None

        triggered = False
        if order.side == OrderSide.BUY and tick.price >= order.stop_price:
            triggered = True
        elif order.side == OrderSide.SELL and tick.price <= order.stop_price:
            triggered = True

        if not triggered:
            return None

        # Determine raw fill price
        is_gap_fill = False
        if gap and gap.is_gap and tick.tick_index == 0:
            # First tick of bar AND there's a gap → check gap-through
            if order.side == OrderSide.BUY and bar.open > order.stop_price:
                # Bar opened above stop → fill at open (gap slippage)
                raw_price = bar.open
                is_gap_fill = True
            elif order.side == OrderSide.SELL and bar.open < order.stop_price:
                # Bar opened below stop → fill at open (gap slippage)
                raw_price = bar.open
                is_gap_fill = True
            else:
                raw_price = order.stop_price
        else:
            raw_price = order.stop_price

        fill_price = self.fill_model.adjust_price(raw_price, order, base_ctx)

        return TickFillResult(
            order=order,
            fill_price=fill_price,
            raw_price=raw_price,
            tick_index=tick.tick_index,
            timestamp_ns=tick.timestamp_ns,
            is_gap_fill=is_gap_fill,
        )

    def _check_stop_limit(
        self,
        order: Order,
        tick: SyntheticTick,
        bar: BarEvent,
        gap: GapInfo | None,
        base_ctx: FillContext,
    ) -> TickFillResult | None:
        """Check if a stop-limit order triggers and fills at this tick.

        Two-stage process:
            1. Stop trigger: price crosses the stop level
            2. Limit fill: price must reach the limit level after trigger

        For simplicity in tick-mode, if the stop triggers at a tick,
        we check subsequent ticks in the same bar for the limit.
        If the stop and limit are both achievable at the same tick
        (e.g., on a gap), we fill immediately.

        On gap-through where price gaps past both stop AND limit:
            → no fill (order remains pending — price went too far).
        """
        if order.stop_price is None or order.limit_price is None:
            return None
        if order.stop_price <= 0 or order.limit_price <= 0:
            return None

        # Step 1: Check stop trigger
        stop_triggered = False
        if order.side == OrderSide.BUY and tick.price >= order.stop_price:
            stop_triggered = True
        elif order.side == OrderSide.SELL and tick.price <= order.stop_price:
            stop_triggered = True

        if not stop_triggered:
            return None

        # Step 2: Check limit achievability at this tick
        limit_ok = False
        if order.side == OrderSide.BUY and tick.price <= order.limit_price:
            limit_ok = True
        elif order.side == OrderSide.SELL and tick.price >= order.limit_price:
            limit_ok = True

        if not limit_ok:
            # Stop triggered but limit not achievable at this tick.
            # In real markets the stop converts to a limit order.
            # For bar-mode simplicity, we check if limit is achievable
            # within the bar's range.
            if order.side == OrderSide.BUY:
                # Need price ≤ limit after stop triggered
                if bar.low <= order.limit_price:
                    limit_ok = True
            else:
                # Need price ≥ limit after stop triggered
                if bar.high >= order.limit_price:
                    limit_ok = True

        if not limit_ok:
            return None

        # Fill at the limit price
        raw_price = order.limit_price

        # Maker order (limit component)
        ctx = FillContext(
            symbol=base_ctx.symbol,
            open=base_ctx.open,
            high=base_ctx.high,
            low=base_ctx.low,
            close=base_ctx.close,
            volume=base_ctx.volume,
            bar_index=base_ctx.bar_index,
            atr=base_ctx.atr,
            avg_volume=base_ctx.avg_volume,
            spread=base_ctx.spread,
            is_maker=True,
        )

        fill_price = self.fill_model.adjust_price(raw_price, order, ctx)

        # Check for gap-through: if bar gaps past BOTH stop and limit → no fill
        is_gap_fill = False
        if gap and gap.is_gap and tick.tick_index == 0:
            if order.side == OrderSide.BUY:
                if bar.open > order.limit_price:
                    return None  # Gapped past limit → no fill
                if bar.open > order.stop_price:
                    is_gap_fill = True
            else:
                if bar.open < order.limit_price:
                    return None  # Gapped past limit → no fill
                if bar.open < order.stop_price:
                    is_gap_fill = True

        return TickFillResult(
            order=order,
            fill_price=fill_price,
            raw_price=raw_price,
            tick_index=tick.tick_index,
            timestamp_ns=tick.timestamp_ns,
            is_gap_fill=is_gap_fill,
        )
