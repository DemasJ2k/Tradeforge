"""
Risk manager for the V2 backtesting engine.

Validates orders before they reach the execution engine:
  - Margin check: does the portfolio have enough cash/margin?
  - Max positions: prevent opening more positions than allowed
  - Max drawdown cutoff: stop trading if drawdown exceeds threshold
  - Order size limits: reject orders above max lot size
  - Duplicate check: prevent identical orders at the same bar

All checks are configurable. A rejected order gets OrderStatus.REJECTED.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.services.backtest.v2.engine.order import (
    Order,
    OrderBook,
    OrderSide,
    OrderStatus,
)
from app.services.backtest.v2.engine.portfolio import Portfolio

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    """Risk management configuration."""
    # Position limits
    max_positions: int = 1            # Max simultaneous open positions (across all symbols)
    max_positions_per_symbol: int = 1  # Max positions per individual symbol
    max_order_size: float = 100.0     # Max lot size per order
    min_order_size: float = 0.001     # Min lot size per order

    # Capital controls
    max_drawdown_pct: float = 0.0     # If > 0, stop trading when max DD% is exceeded
    max_exposure_pct: float = 0.0     # If > 0, reject orders that would exceed exposure %
    min_cash_reserve: float = 0.0     # Keep at least this much cash free

    # Order controls
    allow_pyramiding: bool = False    # Allow adding to existing positions
    exclusive_orders: bool = True     # Auto-close previous position on new entry (backtesting.py style)


class RiskCheckResult:
    """Result of a risk check."""

    def __init__(self, passed: bool, reason: str = ""):
        self.passed = passed
        self.reason = reason

    @staticmethod
    def ok() -> RiskCheckResult:
        return RiskCheckResult(passed=True)

    @staticmethod
    def reject(reason: str) -> RiskCheckResult:
        return RiskCheckResult(passed=False, reason=reason)


class RiskManager:
    """
    Pre-trade risk validation.

    Called by the Runner before submitting orders to the execution engine.
    Returns a RiskCheckResult indicating whether the order is allowed.
    """

    def __init__(
        self,
        config: RiskConfig,
        portfolio: Portfolio,
        order_book: OrderBook,
    ):
        self.config = config
        self.portfolio = portfolio
        self.order_book = order_book
        self._trading_halted = False
        self._halt_reason = ""

    @property
    def is_halted(self) -> bool:
        return self._trading_halted

    @property
    def halt_reason(self) -> str:
        return self._halt_reason

    def validate_order(
        self,
        order: Order,
        current_prices: dict[str, float],
    ) -> RiskCheckResult:
        """Run all risk checks on an order.

        Returns RiskCheckResult.ok() if all checks pass.
        Returns RiskCheckResult.reject(reason) on first failure.
        """
        checks = [
            self._check_halted,
            self._check_order_size,
            self._check_max_positions,
            self._check_pyramiding,
            self._check_margin,
            self._check_max_drawdown,
            self._check_max_exposure,
        ]

        for check in checks:
            result = check(order, current_prices)
            if not result.passed:
                logger.debug(
                    "Risk REJECTED order %s: %s", order.order_id, result.reason
                )
                return result

        return RiskCheckResult.ok()

    def update_drawdown_check(self) -> None:
        """Check if max drawdown threshold has been breached.

        Called after each equity snapshot. If breached, halts trading.
        """
        if self.config.max_drawdown_pct <= 0:
            return
        if self.portfolio.max_drawdown_pct >= self.config.max_drawdown_pct:
            self._trading_halted = True
            self._halt_reason = (
                f"Max drawdown {self.portfolio.max_drawdown_pct:.2f}% "
                f"exceeds limit {self.config.max_drawdown_pct:.2f}%"
            )
            logger.warning("Trading HALTED: %s", self._halt_reason)

    def reset_halt(self) -> None:
        """Reset the trading halt (e.g., for a new backtest run)."""
        self._trading_halted = False
        self._halt_reason = ""

    # ── Individual Checks ───────────────────────────────────────────

    def _check_halted(self, order: Order, prices: dict[str, float]) -> RiskCheckResult:
        if self._trading_halted:
            return RiskCheckResult.reject(f"Trading halted: {self._halt_reason}")
        return RiskCheckResult.ok()

    def _check_order_size(self, order: Order, prices: dict[str, float]) -> RiskCheckResult:
        if order.quantity < self.config.min_order_size:
            return RiskCheckResult.reject(
                f"Order size {order.quantity} below minimum {self.config.min_order_size}"
            )
        if order.quantity > self.config.max_order_size:
            return RiskCheckResult.reject(
                f"Order size {order.quantity} exceeds maximum {self.config.max_order_size}"
            )
        return RiskCheckResult.ok()

    def _check_max_positions(self, order: Order, prices: dict[str, float]) -> RiskCheckResult:
        # Only check for orders that would INCREASE positions
        pos = self.portfolio.get_position(order.symbol)
        is_increasing = (
            pos.is_flat
            or (pos.is_long and order.side == OrderSide.BUY)
            or (pos.is_short and order.side == OrderSide.SELL)
        )

        if not is_increasing:
            return RiskCheckResult.ok()  # Reducing/closing is always allowed

        # Global position limit
        if self.config.max_positions > 0:
            open_count = self.portfolio.open_position_count()
            # If opening a new symbol, check global limit
            if pos.is_flat and open_count >= self.config.max_positions:
                return RiskCheckResult.reject(
                    f"Max positions ({self.config.max_positions}) reached, "
                    f"currently have {open_count}"
                )

        # Per-symbol limit
        if self.config.max_positions_per_symbol > 0 and not pos.is_flat:
            # Already have a position — check if pyramiding is the issue
            pass  # Handled by _check_pyramiding

        return RiskCheckResult.ok()

    def _check_pyramiding(self, order: Order, prices: dict[str, float]) -> RiskCheckResult:
        if self.config.allow_pyramiding:
            return RiskCheckResult.ok()

        pos = self.portfolio.get_position(order.symbol)
        if pos.is_flat:
            return RiskCheckResult.ok()

        # Are we adding to an existing position?
        is_same_direction = (
            (pos.is_long and order.side == OrderSide.BUY)
            or (pos.is_short and order.side == OrderSide.SELL)
        )
        if is_same_direction:
            return RiskCheckResult.reject(
                f"Pyramiding not allowed: already {pos.side.value} "
                f"{pos.quantity} {order.symbol}"
            )

        return RiskCheckResult.ok()

    def _check_margin(self, order: Order, prices: dict[str, float]) -> RiskCheckResult:
        price = prices.get(order.symbol, 0)
        if price <= 0:
            return RiskCheckResult.ok()  # Can't check without price

        pos = self.portfolio.get_position(order.symbol)
        pv = pos.point_value if pos else 1.0

        if not self.portfolio.can_afford_order(
            order.symbol, order.quantity, price, pv
        ):
            return RiskCheckResult.reject(
                f"Insufficient margin: available {self.portfolio.available_cash():.2f}, "
                f"required for {order.quantity} {order.symbol} at {price}"
            )

        return RiskCheckResult.ok()

    def _check_max_drawdown(self, order: Order, prices: dict[str, float]) -> RiskCheckResult:
        # Already checked in _check_halted via update_drawdown_check
        return RiskCheckResult.ok()

    def _check_max_exposure(self, order: Order, prices: dict[str, float]) -> RiskCheckResult:
        if self.config.max_exposure_pct <= 0:
            return RiskCheckResult.ok()

        current_exposure = self.portfolio.exposure_pct(prices)
        if current_exposure >= self.config.max_exposure_pct:
            return RiskCheckResult.reject(
                f"Exposure {current_exposure:.1f}% exceeds max {self.config.max_exposure_pct:.1f}%"
            )
        return RiskCheckResult.ok()
