"""
Risk Manager for the Algo Trading Engine.

Validates proposed trades against configurable risk limits before execution.
Includes prop firm presets for common challenge/funded account rules.
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ── Prop Firm Presets ──────────────────────────────────────────────────
# Pre-configured risk profiles matching common prop firm rules.

PROP_FIRM_PRESETS = {
    "prop_firm_conservative": {
        "max_daily_loss_pct": 4.0,       # 4% daily max loss
        "max_drawdown_pct": 8.0,         # 8% total max drawdown
        "max_open_positions": 3,         # Fewer concurrent positions
        "position_size_type": "percent_risk",
        "position_size_value": 0.005,    # 0.5% risk per trade
        "exposure_limit": 0.0,
        "label": "Prop Firm Conservative",
        "description": "Strict limits for prop firm challenges (4% daily, 8% total DD)",
    },
    "prop_firm_standard": {
        "max_daily_loss_pct": 5.0,       # 5% daily max loss (FTMO, MFF, etc.)
        "max_drawdown_pct": 10.0,        # 10% total max drawdown
        "max_open_positions": 5,
        "position_size_type": "percent_risk",
        "position_size_value": 0.01,     # 1% risk per trade
        "exposure_limit": 0.0,
        "label": "Prop Firm Standard",
        "description": "Standard prop firm limits (5% daily, 10% total DD)",
    },
    "prop_firm_aggressive": {
        "max_daily_loss_pct": 5.0,       # Same daily limit
        "max_drawdown_pct": 12.0,        # Slightly more room
        "max_open_positions": 6,
        "position_size_type": "percent_risk",
        "position_size_value": 0.015,    # 1.5% risk per trade
        "exposure_limit": 0.0,
        "label": "Prop Firm Aggressive",
        "description": "Aggressive within prop firm limits (5% daily, 12% total DD)",
    },
    "personal_conservative": {
        "max_daily_loss_pct": 2.0,
        "max_drawdown_pct": 5.0,
        "max_open_positions": 3,
        "position_size_type": "percent_risk",
        "position_size_value": 0.005,
        "exposure_limit": 0.0,
        "label": "Personal Conservative",
        "description": "Conservative personal trading (2% daily, 5% total DD)",
    },
    "no_limits": {
        "max_daily_loss_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "max_open_positions": 10,
        "position_size_type": "fixed_lot",
        "position_size_value": 0.01,
        "exposure_limit": 0.0,
        "label": "No Limits",
        "description": "No risk limits (not recommended for live trading)",
    },
}


def get_risk_preset(name: str) -> dict:
    """Get a risk management preset by name. Returns empty dict if not found."""
    preset = PROP_FIRM_PRESETS.get(name, {})
    # Return only the config keys (exclude label/description)
    return {k: v for k, v in preset.items() if k not in ("label", "description")}


def list_risk_presets() -> list[dict]:
    """List all available risk presets with their metadata."""
    return [
        {"id": name, "label": preset["label"], "description": preset["description"],
         "max_daily_loss_pct": preset["max_daily_loss_pct"],
         "max_drawdown_pct": preset["max_drawdown_pct"]}
        for name, preset in PROP_FIRM_PRESETS.items()
    ]


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
        broker_name: str = "oanda",
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
            from app.services.agent.instrument_specs import calc_lot_size
            risk_amount = balance * (self.position_size_value / 100.0)
            sl_distance = abs(entry_price - stop_loss)
            lot_size = calc_lot_size(symbol, risk_amount, sl_distance, broker_name)
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
