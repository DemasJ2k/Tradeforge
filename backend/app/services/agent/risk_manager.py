"""
Risk Manager for the Algo Trading Engine.

Validates proposed trades against configurable risk limits before execution.
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    adjusted_lot_size: Optional[float] = None


class RiskManager:
    """
    Evaluates whether a proposed trade passes risk checks.

    Config keys (from agent.risk_config JSON):
        max_daily_loss_pct:   Max daily loss as % of balance (0 = disabled)
        max_open_positions:   Max concurrent open positions
        max_drawdown_pct:     Circuit breaker — stop if drawdown exceeds this %
        position_size_type:   "fixed_lot" | "percent_risk"
        position_size_value:  Lot size or risk %
        exposure_limit:       Max total lots per symbol (0 = unlimited)
    """

    def __init__(self, config: dict):
        self.max_daily_loss_pct = config.get("max_daily_loss_pct", 0.0)
        self.max_open_positions = config.get("max_open_positions", 3)
        self.max_drawdown_pct = config.get("max_drawdown_pct", 0.0)
        self.position_size_type = config.get("position_size_type", "fixed_lot")
        self.position_size_value = config.get("position_size_value", 0.01)
        self.exposure_limit = config.get("exposure_limit", 0.0)

        # Tracked state
        self.daily_pnl = 0.0
        self.peak_balance = 0.0
        self.open_position_count = 0
        self.symbol_exposure: dict[str, float] = {}  # symbol -> total lots

    def reset_daily(self):
        """Call at start of each trading day."""
        self.daily_pnl = 0.0

    def update_balance(self, balance: float):
        """Track peak balance for drawdown calculation."""
        if balance > self.peak_balance:
            self.peak_balance = balance

    def record_pnl(self, pnl: float):
        """Record a closed trade's PnL."""
        self.daily_pnl += pnl

    def set_open_positions(self, count: int, exposure: Optional[dict[str, float]] = None):
        """Update current open position state."""
        self.open_position_count = count
        if exposure:
            self.symbol_exposure = exposure

    def evaluate(
        self,
        symbol: str,
        direction: str,
        balance: float,
        entry_price: float,
        stop_loss: float,
    ) -> RiskDecision:
        """
        Evaluate whether a proposed trade should be allowed.

        Returns RiskDecision with approval status and lot size.
        """
        self.update_balance(balance)

        # Check max open positions
        if self.max_open_positions > 0 and self.open_position_count >= self.max_open_positions:
            return RiskDecision(
                approved=False,
                reason=f"Max open positions reached ({self.max_open_positions})",
            )

        # Check daily loss limit
        if self.max_daily_loss_pct > 0 and balance > 0:
            max_loss = balance * (self.max_daily_loss_pct / 100.0)
            if abs(self.daily_pnl) >= max_loss and self.daily_pnl < 0:
                return RiskDecision(
                    approved=False,
                    reason=f"Daily loss limit reached ({self.max_daily_loss_pct}%)",
                )

        # Check drawdown circuit breaker
        if self.max_drawdown_pct > 0 and self.peak_balance > 0:
            current_dd = (self.peak_balance - balance) / self.peak_balance * 100
            if current_dd >= self.max_drawdown_pct:
                return RiskDecision(
                    approved=False,
                    reason=f"Max drawdown exceeded ({current_dd:.1f}% >= {self.max_drawdown_pct}%)",
                )

        # Calculate lot size
        if self.position_size_type == "percent_risk" and stop_loss and entry_price:
            risk_amount = balance * (self.position_size_value / 100.0)
            sl_distance = abs(entry_price - stop_loss)
            if sl_distance > 0:
                lot_size = risk_amount / (sl_distance * 100)  # simplified
                lot_size = max(0.01, round(lot_size, 2))
            else:
                lot_size = 0.01
        else:
            lot_size = self.position_size_value

        # Check exposure limit
        if self.exposure_limit > 0:
            current_exposure = self.symbol_exposure.get(symbol, 0.0)
            if current_exposure + lot_size > self.exposure_limit:
                remaining = self.exposure_limit - current_exposure
                if remaining < 0.01:
                    return RiskDecision(
                        approved=False,
                        reason=f"Exposure limit reached for {symbol} ({self.exposure_limit} lots)",
                    )
                lot_size = round(remaining, 2)

        logger.info(
            "[Risk] %s %s %.2f lots — APPROVED (open=%d, daily_pnl=%.2f)",
            direction, symbol, lot_size, self.open_position_count, self.daily_pnl,
        )

        return RiskDecision(
            approved=True,
            reason="Passed all risk checks",
            adjusted_lot_size=lot_size,
        )
