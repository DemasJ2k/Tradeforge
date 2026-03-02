"""
Pluggable fill-price models for the V2 backtesting engine.

Fill price formula:
    fill_price = signal_price
               + spread_half          (half-spread charged on the filled side)
               + slippage             (configurable model)
               + market_impact        (for large orders relative to volume)
               - rebate               (maker rebate for limit orders)

Models:
    FixedSlippage        – constant slippage in price points
    VolatilitySlippage   – ATR-scaled slippage (pct of recent volatility)
    VolumeImpact         – linear impact proportional to size / avg_volume
    CompositeFillModel   – pipeline of multiple models applied sequentially
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app.services.backtest.v2.engine.order import Order, OrderSide, OrderType


# ────────────────────────────────────────────────────────────────────
# Bar context passed to the fill model so it can make vol/volume decisions
# ────────────────────────────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class FillContext:
    """Market state snapshot at the moment of a potential fill.

    This is assembled by the tick engine / runner from bar data and
    indicator caches so the fill model can remain stateless.
    """
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float           # Bar volume (0 if unavailable)
    bar_index: int
    # Recent ATR value (rolling window) — 0 means unknown
    atr: float = 0.0
    # Average daily volume (rolling window) — 0 means unknown
    avg_volume: float = 0.0
    # Spread in price points (configured per-symbol)
    spread: float = 0.0
    # Whether this order is a maker (limit fill) or taker (market/stop)
    is_maker: bool = False


# ────────────────────────────────────────────────────────────────────
# Base class
# ────────────────────────────────────────────────────────────────────

class FillModel(ABC):
    """Abstract base for fill-price adjustment models."""

    @abstractmethod
    def adjust_price(
        self,
        raw_price: float,
        order: Order,
        ctx: FillContext,
    ) -> float:
        """Return an adjusted fill price given the raw (signal) price.

        Parameters
        ----------
        raw_price : float
            The theoretical fill price before any adjustments
            (e.g. limit price, stop trigger price, bar open).
        order : Order
            The order being filled — provides side, type, quantity.
        ctx : FillContext
            Current bar/market snapshot — provides spread, ATR, volume.

        Returns
        -------
        float
            The final adjusted price the order will fill at.
        """
        ...


# ────────────────────────────────────────────────────────────────────
# Spread model (applied first in the pipeline)
# ────────────────────────────────────────────────────────────────────

class SpreadModel(FillModel):
    """Apply half-spread to the fill price.

    Buys fill at ask (raw + half_spread).
    Sells fill at bid (raw - half_spread).
    Limit (maker) orders can receive a rebate instead.
    """

    def __init__(self, maker_rebate_pct: float = 0.0):
        self.maker_rebate_pct = maker_rebate_pct

    def adjust_price(
        self, raw_price: float, order: Order, ctx: FillContext,
    ) -> float:
        half_spread = ctx.spread / 2.0

        if ctx.is_maker and self.maker_rebate_pct > 0:
            # Maker orders can get a rebate (reduce cost)
            rebate = half_spread * self.maker_rebate_pct
            half_spread -= rebate

        if order.side == OrderSide.BUY:
            return raw_price + half_spread
        else:
            return raw_price - half_spread


# ────────────────────────────────────────────────────────────────────
# Slippage models
# ────────────────────────────────────────────────────────────────────

class FixedSlippage(FillModel):
    """Constant slippage in price points, regardless of volatility.

    Parameters
    ----------
    points : float
        Slippage in absolute price points (e.g. 0.5 for XAUUSD).
    """

    def __init__(self, points: float = 0.0):
        self.points = abs(points)

    def adjust_price(
        self, raw_price: float, order: Order, ctx: FillContext,
    ) -> float:
        if self.points == 0:
            return raw_price
        if order.side == OrderSide.BUY:
            return raw_price + self.points
        else:
            return raw_price - self.points


class VolatilitySlippage(FillModel):
    """ATR-scaled slippage — slippage = pct × ATR.

    More realistic for volatile instruments: slippage grows with
    current market volatility.

    Parameters
    ----------
    pct_of_atr : float
        Fraction of ATR to use as slippage (e.g. 0.1 = 10% of ATR).
    min_points : float
        Floor slippage in absolute price points.
    max_points : float
        Cap slippage in absolute price points (0 = no cap).
    """

    def __init__(
        self,
        pct_of_atr: float = 0.1,
        min_points: float = 0.0,
        max_points: float = 0.0,
    ):
        self.pct_of_atr = abs(pct_of_atr)
        self.min_points = abs(min_points)
        self.max_points = abs(max_points) if max_points > 0 else float("inf")

    def adjust_price(
        self, raw_price: float, order: Order, ctx: FillContext,
    ) -> float:
        if ctx.atr <= 0:
            # No ATR available — fall back to min_points
            slip = self.min_points
        else:
            slip = self.pct_of_atr * ctx.atr
            slip = max(slip, self.min_points)
            slip = min(slip, self.max_points)

        if slip == 0:
            return raw_price
        if order.side == OrderSide.BUY:
            return raw_price + slip
        else:
            return raw_price - slip


class VolumeImpact(FillModel):
    """Market-impact model: slippage proportional to size / avg_volume.

    For large orders: impact = impact_coeff × (quantity / avg_volume).
    This is applied as a fraction of price.

    Parameters
    ----------
    impact_coeff : float
        Scaling coefficient.  impact_pct = coeff × (qty / avg_vol).
        Typical values: 0.05 – 0.20 for liquid FX, higher for small caps.
    max_impact_pct : float
        Maximum impact as a fraction of price (e.g. 0.01 = 1%).
    """

    def __init__(
        self,
        impact_coeff: float = 0.1,
        max_impact_pct: float = 0.01,
    ):
        self.impact_coeff = abs(impact_coeff)
        self.max_impact_pct = abs(max_impact_pct)

    def adjust_price(
        self, raw_price: float, order: Order, ctx: FillContext,
    ) -> float:
        if ctx.avg_volume <= 0 or order.quantity <= 0:
            return raw_price  # No volume data — no impact

        participation = order.quantity / ctx.avg_volume
        impact_pct = self.impact_coeff * participation
        impact_pct = min(impact_pct, self.max_impact_pct)

        impact_points = raw_price * impact_pct
        if order.side == OrderSide.BUY:
            return raw_price + impact_points
        else:
            return raw_price - impact_points


# ────────────────────────────────────────────────────────────────────
# Composite model — chains multiple models together
# ────────────────────────────────────────────────────────────────────

class CompositeFillModel(FillModel):
    """Pipeline of fill models applied in sequence.

    Typical chain:
        SpreadModel → VolatilitySlippage → VolumeImpact

    Each model receives the output of the previous one as raw_price.
    """

    def __init__(self, models: list[FillModel] | None = None):
        self.models: list[FillModel] = models or []

    def add(self, model: FillModel) -> CompositeFillModel:
        """Append a model to the pipeline and return self for chaining."""
        self.models.append(model)
        return self

    def adjust_price(
        self, raw_price: float, order: Order, ctx: FillContext,
    ) -> float:
        price = raw_price
        for model in self.models:
            price = model.adjust_price(price, order, ctx)
        return max(price, 1e-8)  # Price floor


# ────────────────────────────────────────────────────────────────────
# Factory helpers
# ────────────────────────────────────────────────────────────────────

def make_default_fill_model(
    spread: float = 0.0,
    slippage_pct: float = 0.0,
    maker_rebate_pct: float = 0.0,
) -> CompositeFillModel:
    """Build a reasonable default fill model chain.

    Parameters
    ----------
    spread : float
        Full spread in price points (will be halved internally).
    slippage_pct : float
        Slippage as fraction of price (0.001 = 0.1%).
    maker_rebate_pct : float
        Fraction of half-spread returned on limit fills (0–1).
    """
    return CompositeFillModel([
        SpreadModel(maker_rebate_pct=maker_rebate_pct),
        FixedSlippage(points=0.0),  # Placeholder — replaced by vol or user config
    ])


def make_realistic_fill_model(
    spread: float = 0.0,
    atr_slip_pct: float = 0.1,
    min_slip_pts: float = 0.0,
    max_slip_pts: float = 0.0,
    impact_coeff: float = 0.1,
    max_impact_pct: float = 0.01,
    maker_rebate_pct: float = 0.0,
) -> CompositeFillModel:
    """Build a realistic fill model with spread + vol-slippage + volume impact.

    Parameters
    ----------
    spread : float
        Full spread in price points.
    atr_slip_pct : float
        Fraction of ATR used as slippage.
    min_slip_pts : float
        Minimum slippage in price points.
    max_slip_pts : float
        Maximum slippage in price points.
    impact_coeff : float
        Volume-impact scaling coefficient.
    max_impact_pct : float
        Cap on volume impact as fraction of price.
    maker_rebate_pct : float
        Fraction of half-spread returned on limit fills.
    """
    return CompositeFillModel([
        SpreadModel(maker_rebate_pct=maker_rebate_pct),
        VolatilitySlippage(
            pct_of_atr=atr_slip_pct,
            min_points=min_slip_pts,
            max_points=max_slip_pts,
        ),
        VolumeImpact(
            impact_coeff=impact_coeff,
            max_impact_pct=max_impact_pct,
        ),
    ])
