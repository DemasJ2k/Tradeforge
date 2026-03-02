"""
Position sizing module for the V2 backtesting engine.

Provides multiple position sizing methods that compute the optimal
lot size given account state, risk parameters, and instrument specs.

Methods:
    FIXED_LOT      – Always use the same lot size (default, legacy behaviour)
    PERCENT_RISK   – Risk a fixed % of equity per trade based on SL distance
    FIXED_FRACTIONAL – Allocate a fixed % of equity as position notional
    KELLY          – Kelly criterion: f* = (p · b − q) / b
                     where p = win rate, b = avg_win / avg_loss, q = 1 − p

Usage in strategies:
    lots = self.ctx.compute_position_size(
        symbol="XAUUSD",
        entry_price=2000.0,
        stop_loss=1990.0,
        direction="long",
    )

All sizing results are clamped to [min_lot, max_lot] and rounded to
the instrument's lot_step.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# Enums & Config
# ────────────────────────────────────────────────────────────────────

class SizingMethod(str, Enum):
    """Position sizing method identifiers."""
    FIXED_LOT = "fixed_lot"
    PERCENT_RISK = "percent_risk"
    FIXED_FRACTIONAL = "fixed_fractional"
    KELLY = "kelly"


@dataclass
class SizingConfig:
    """Configuration for position sizing.

    Attributes
    ----------
    method : SizingMethod
        Which sizing algorithm to use.
    fixed_lots : float
        Lot size for FIXED_LOT method (default 0.01).
    risk_pct : float
        Percentage of equity to risk per trade (PERCENT_RISK).
        E.g. 1.0 means risk 1% of equity.
    fractional_pct : float
        Percentage of equity to allocate (FIXED_FRACTIONAL).
        E.g. 5.0 means allocate 5% of equity as notional.
    kelly_fraction : float
        Kelly scaling factor (0.0–1.0).  1.0 = full Kelly, 0.5 = half Kelly.
        Half-Kelly is recommended to reduce volatility.
    kelly_win_rate : float | None
        Override win rate for Kelly.  If None, uses rolling stats from
        closed trades (requires trade history).
    kelly_avg_rr : float | None
        Override average reward/risk ratio.  If None, uses rolling stats.
    kelly_lookback : int
        Number of most recent trades to use for rolling Kelly stats.
    max_lots : float
        Hard cap on lot size (safety limit).
    min_lots : float
        Minimum lot size (typically 0.01).
    lot_step : float
        Lot size rounding increment (typically 0.01).
    max_risk_pct : float
        Safety cap: never risk more than this % of equity, regardless of method.
    """
    method: SizingMethod = SizingMethod.FIXED_LOT
    fixed_lots: float = 0.01
    risk_pct: float = 1.0
    fractional_pct: float = 5.0
    kelly_fraction: float = 0.5
    kelly_win_rate: Optional[float] = None
    kelly_avg_rr: Optional[float] = None
    kelly_lookback: int = 50
    max_lots: float = 100.0
    min_lots: float = 0.01
    lot_step: float = 0.01
    max_risk_pct: float = 10.0


def sizing_config_from_risk_params(risk_params: dict[str, Any]) -> SizingConfig:
    """Build a SizingConfig from the strategy's risk_params dict.

    Supports both the new ``position_size_method`` key and the legacy
    ``position_size_value`` (treated as fixed lot).
    """
    method_str = risk_params.get("position_size_method", "fixed_lot")
    try:
        method = SizingMethod(method_str)
    except ValueError:
        method = SizingMethod.FIXED_LOT

    return SizingConfig(
        method=method,
        fixed_lots=float(risk_params.get("position_size_value", 0.01)),
        risk_pct=float(risk_params.get("risk_pct", 1.0)),
        fractional_pct=float(risk_params.get("fractional_pct", 5.0)),
        kelly_fraction=float(risk_params.get("kelly_fraction", 0.5)),
        kelly_win_rate=risk_params.get("kelly_win_rate"),
        kelly_avg_rr=risk_params.get("kelly_avg_rr"),
        kelly_lookback=int(risk_params.get("kelly_lookback", 50)),
        max_lots=float(risk_params.get("max_lots", 100.0)),
        min_lots=float(risk_params.get("min_lots", 0.01)),
        lot_step=float(risk_params.get("lot_step", 0.01)),
        max_risk_pct=float(risk_params.get("max_risk_pct", 10.0)),
    )


# ────────────────────────────────────────────────────────────────────
# Position Sizer
# ────────────────────────────────────────────────────────────────────

class PositionSizer:
    """Computes lot sizes using the configured sizing method.

    Integration points:
        - Created by the Runner at startup, attached to StrategyContext.
        - Strategies call ``ctx.compute_position_size(...)`` which
          delegates to this object.
        - After each closed trade, Runner calls ``update_trade_stats()``
          so Kelly criterion can use rolling win rate / R:R.
    """

    def __init__(self, config: SizingConfig):
        self.config = config

        # Rolling trade stats for Kelly
        self._wins: int = 0
        self._losses: int = 0
        self._total_win_pnl: float = 0.0
        self._total_loss_pnl: float = 0.0
        # Recent trades ring-buffer for lookback window
        self._recent_pnls: list[float] = []

    # ── Public API ──────────────────────────────────────────────────

    def compute(
        self,
        equity: float,
        entry_price: float,
        stop_loss: float,
        contract_size: float = 100_000.0,
        point_value: float = 1.0,
    ) -> float:
        """Compute the lot size for a new trade.

        Parameters
        ----------
        equity : float
            Current account equity (cash + unrealised PnL).
        entry_price : float
            Expected entry price.
        stop_loss : float
            Stop-loss price (required for PERCENT_RISK; ignored for FIXED_LOT).
        contract_size : float
            From InstrumentSpec.contract_size (e.g. 100 for gold).
        point_value : float
            From InstrumentSpec.point_value.

        Returns
        -------
        float
            Lot size clamped to [min_lots, max_lots] and rounded to lot_step.
        """
        method = self.config.method

        if method == SizingMethod.FIXED_LOT:
            lots = self._fixed_lot()
        elif method == SizingMethod.PERCENT_RISK:
            lots = self._percent_risk(equity, entry_price, stop_loss, contract_size)
        elif method == SizingMethod.FIXED_FRACTIONAL:
            lots = self._fixed_fractional(equity, entry_price, contract_size)
        elif method == SizingMethod.KELLY:
            lots = self._kelly(equity, entry_price, stop_loss, contract_size)
        else:
            lots = self._fixed_lot()

        return self._clamp_and_round(lots, equity, entry_price, stop_loss, contract_size)

    def update_trade_stats(self, pnl: float) -> None:
        """Record a closed trade's PnL for rolling Kelly computation.

        Called by the Runner after each trade closes.
        """
        self._recent_pnls.append(pnl)
        if len(self._recent_pnls) > self.config.kelly_lookback:
            removed = self._recent_pnls.pop(0)
            # Adjust running totals
            if removed > 0:
                self._wins -= 1
                self._total_win_pnl -= removed
            elif removed < 0:
                self._losses -= 1
                self._total_loss_pnl -= abs(removed)

        if pnl > 0:
            self._wins += 1
            self._total_win_pnl += pnl
        elif pnl < 0:
            self._losses += 1
            self._total_loss_pnl += abs(pnl)

    @property
    def rolling_win_rate(self) -> float:
        total = self._wins + self._losses
        return self._wins / total if total > 0 else 0.0

    @property
    def rolling_avg_rr(self) -> float:
        """Average reward-to-risk ratio from recent trades."""
        avg_win = self._total_win_pnl / self._wins if self._wins > 0 else 0.0
        avg_loss = self._total_loss_pnl / self._losses if self._losses > 0 else 1.0
        return avg_win / avg_loss if avg_loss > 0 else 0.0

    # ── Sizing Methods ──────────────────────────────────────────────

    def _fixed_lot(self) -> float:
        """Always return the configured fixed lot size."""
        return self.config.fixed_lots

    def _percent_risk(
        self,
        equity: float,
        entry_price: float,
        stop_loss: float,
        contract_size: float,
    ) -> float:
        """Risk a fixed % of equity per trade.

        Formula:
            risk_amount = equity × risk_pct / 100
            sl_distance = |entry_price − stop_loss|
            lots = risk_amount / (sl_distance × contract_size)

        If SL distance is zero or negative, falls back to fixed lot.
        """
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance < 1e-10 or contract_size <= 0:
            logger.warning(
                "PERCENT_RISK: SL distance %.6f too small, falling back to fixed lot",
                sl_distance,
            )
            return self.config.fixed_lots

        risk_amount = equity * self.config.risk_pct / 100.0
        lots = risk_amount / (sl_distance * contract_size)
        return lots

    def _fixed_fractional(
        self,
        equity: float,
        entry_price: float,
        contract_size: float,
    ) -> float:
        """Allocate a fixed % of equity as position notional.

        Formula:
            notional = equity × fractional_pct / 100
            lots = notional / (entry_price × contract_size)

        For instruments where entry_price is small (e.g. FX pip-quoted),
        this naturally produces larger lot sizes.
        """
        if entry_price <= 0 or contract_size <= 0:
            return self.config.fixed_lots

        notional = equity * self.config.fractional_pct / 100.0
        lots = notional / (entry_price * contract_size)
        return lots

    def _kelly(
        self,
        equity: float,
        entry_price: float,
        stop_loss: float,
        contract_size: float,
    ) -> float:
        """Kelly criterion position sizing.

        Formula:
            f* = (p × b − q) / b
        where:
            p = win rate
            b = average win / average loss (reward-to-risk ratio)
            q = 1 − p

        The fraction f* is then applied to equity (after kelly_fraction scaling)
        and converted to lots via percent_risk logic.

        If not enough trades have been recorded, uses configured overrides
        or falls back to fixed lot.
        """
        # Get win rate and R:R
        win_rate = self.config.kelly_win_rate
        avg_rr = self.config.kelly_avg_rr

        # Use rolling stats if no manual overrides
        if win_rate is None:
            win_rate = self.rolling_win_rate
        if avg_rr is None:
            avg_rr = self.rolling_avg_rr

        # Need enough data
        total = self._wins + self._losses
        if total < 10 and self.config.kelly_win_rate is None:
            # Not enough trades — fall back to fixed lot
            return self.config.fixed_lots

        if win_rate <= 0 or avg_rr <= 0:
            return self.config.fixed_lots

        p = win_rate
        q = 1.0 - p
        b = avg_rr

        kelly_f = (p * b - q) / b
        if kelly_f <= 0:
            # Negative Kelly → don't trade (edge is negative)
            return self.config.min_lots

        # Scale by kelly_fraction (half-Kelly etc.)
        effective_risk_pct = kelly_f * 100.0 * self.config.kelly_fraction

        # Cap at max_risk_pct
        effective_risk_pct = min(effective_risk_pct, self.config.max_risk_pct)

        # Now compute lots like percent_risk
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance < 1e-10 or contract_size <= 0:
            return self.config.fixed_lots

        risk_amount = equity * effective_risk_pct / 100.0
        lots = risk_amount / (sl_distance * contract_size)
        return lots

    # ── Helpers ─────────────────────────────────────────────────────

    def _clamp_and_round(
        self,
        lots: float,
        equity: float,
        entry_price: float,
        stop_loss: float,
        contract_size: float,
    ) -> float:
        """Clamp to [min_lots, max_lots], enforce max_risk_pct cap, round to lot_step."""
        # Safety cap: ensure risk doesn't exceed max_risk_pct
        if self.config.method != SizingMethod.FIXED_LOT and self.config.max_risk_pct > 0:
            sl_distance = abs(entry_price - stop_loss)
            if sl_distance > 1e-10 and contract_size > 0:
                max_risk_amount = equity * self.config.max_risk_pct / 100.0
                max_lots_by_risk = max_risk_amount / (sl_distance * contract_size)
                lots = min(lots, max_lots_by_risk)

        # Clamp
        lots = max(self.config.min_lots, min(lots, self.config.max_lots))

        # Round to lot_step
        if self.config.lot_step > 0:
            lots = math.floor(lots / self.config.lot_step) * self.config.lot_step

        # Final min check after rounding
        if lots < self.config.min_lots:
            lots = self.config.min_lots

        return round(lots, 8)  # avoid float artifacts
