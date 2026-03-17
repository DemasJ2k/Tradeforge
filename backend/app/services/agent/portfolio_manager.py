"""
Portfolio Manager Service
=========================
Coordinates multiple AgentRunners for a single user with:
- Portfolio-level drawdown circuit breakers (daily + total)
- Correlation-aware position management (indices are ~85% correlated)
- Capital allocation and risk budgeting per agent
- Regime-aware agent activation
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

_log = logging.getLogger(__name__)

# ── Correlation Groups ──────────────────────────────────────────────────
# Instruments within a group are assumed highly correlated.
# When the PM sees exposure in one, it discounts new positions in the same group.
CORRELATION_GROUPS = {
    "indices":  ["US30", "NAS100", "US500", "US100"],
    "metals":   ["XAUUSD", "XAGUSD"],
    "crypto":   ["BTCUSD", "ETHUSD", "SOLUSD"],
}

# Default correlation within a group (used when no live correlation data)
DEFAULT_INTRA_GROUP_CORR = 0.85


@dataclass
class TradeValidation:
    """Result of portfolio-level trade validation."""
    approved: bool
    reason: str = ""
    adjusted_lot_size: Optional[float] = None


@dataclass
class AgentState:
    """Tracks live state of an agent within the portfolio."""
    agent_id: int
    symbol: str
    direction: Optional[str] = None   # "long" | "short" | None
    entry_price: float = 0.0
    current_pnl: float = 0.0
    lot_size: float = 0.0
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    trades_today: int = 0


class PortfolioManagerService:
    """
    Coordinates multiple agents for a single user.

    Usage:
        pm = PortfolioManagerService(config)
        # Before each trade in AgentRunner:
        result = pm.validate_trade(agent_id, symbol, direction, ...)
        if not result.approved:
            log("Blocked by PM: " + result.reason)
            return
    """

    def __init__(
        self,
        portfolio_id: int,
        user_id: int,
        max_daily_loss_pct: float = 5.0,
        max_total_drawdown_pct: float = 10.0,
        max_portfolio_risk_pct: float = 2.0,
        correlation_threshold: float = 0.85,
        max_concurrent_positions: int = 6,
        capital_allocation: dict | None = None,
        mode: str = "balanced",
    ):
        self.portfolio_id = portfolio_id
        self.user_id = user_id
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_total_drawdown_pct = max_total_drawdown_pct
        self.max_portfolio_risk_pct = max_portfolio_risk_pct
        self.correlation_threshold = correlation_threshold
        self.max_concurrent_positions = max_concurrent_positions
        self.capital_allocation = capital_allocation or {}
        self.mode = mode

        # Live state
        self._agents: dict[int, AgentState] = {}
        self._starting_equity: float = 0.0
        self._peak_equity: float = 0.0
        self._current_equity: float = 0.0
        self._daily_pnl: float = 0.0
        self._daily_reset_date: str = ""
        self._paused: bool = False

    # ── Public API ───────────────────────────────────────────────────

    def register_agent(self, agent_id: int, symbol: str) -> None:
        """Register an agent for portfolio tracking."""
        self._agents[agent_id] = AgentState(agent_id=agent_id, symbol=symbol)
        _log.info("PM[%s] registered agent %s for %s", self.portfolio_id, agent_id, symbol)

    def set_equity(self, equity: float) -> None:
        """Update current equity (called on broker balance refresh)."""
        if self._starting_equity == 0:
            self._starting_equity = equity
        self._current_equity = equity
        if equity > self._peak_equity:
            self._peak_equity = equity

    def validate_trade(
        self,
        agent_id: int,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        lot_size: float,
    ) -> TradeValidation:
        """
        Validate a trade against portfolio-level constraints.
        Called by AgentRunner BEFORE creating a trade.
        """
        # Reset daily P&L at midnight UTC
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._daily_reset_date:
            self._daily_pnl = 0.0
            self._daily_reset_date = today
            for a in self._agents.values():
                a.daily_pnl = 0.0
                a.trades_today = 0

        # 1. Portfolio paused?
        if self._paused:
            return TradeValidation(False, "Portfolio paused — circuit breaker active")

        # 2. Daily loss limit
        if self._current_equity > 0:
            daily_loss_pct = abs(min(self._daily_pnl, 0)) / self._current_equity * 100
            if daily_loss_pct >= self.max_daily_loss_pct:
                self._paused = True
                _log.warning("PM[%s] DAILY LOSS BREACHED: %.2f%% >= %.2f%%",
                             self.portfolio_id, daily_loss_pct, self.max_daily_loss_pct)
                return TradeValidation(False, f"Daily loss limit breached ({daily_loss_pct:.1f}%)")

        # 3. Total drawdown limit
        if self._peak_equity > 0:
            dd_pct = (self._peak_equity - self._current_equity) / self._peak_equity * 100
            if dd_pct >= self.max_total_drawdown_pct:
                self._paused = True
                _log.warning("PM[%s] MAX DRAWDOWN BREACHED: %.2f%% >= %.2f%%",
                             self.portfolio_id, dd_pct, self.max_total_drawdown_pct)
                return TradeValidation(False, f"Max drawdown limit breached ({dd_pct:.1f}%)")

        # 4. Max concurrent positions
        open_positions = sum(1 for a in self._agents.values() if a.direction is not None)
        if open_positions >= self.max_concurrent_positions:
            return TradeValidation(False, f"Max positions reached ({open_positions}/{self.max_concurrent_positions})")

        # 5. Correlation check
        corr_result = self._check_correlation(symbol, direction)
        if not corr_result.approved:
            return corr_result

        # 6. Portfolio risk budget
        risk_result = self._check_risk_budget(agent_id, entry_price, stop_loss, lot_size)
        if not risk_result.approved:
            return risk_result

        return TradeValidation(True, "approved", adjusted_lot_size=risk_result.adjusted_lot_size)

    def on_trade_opened(self, agent_id: int, direction: str, entry_price: float, lot_size: float) -> None:
        """Called when a trade is opened (agent notifies PM)."""
        if agent_id in self._agents:
            a = self._agents[agent_id]
            a.direction = direction
            a.entry_price = entry_price
            a.lot_size = lot_size
            a.trades_today += 1

    def on_trade_closed(self, agent_id: int, pnl: float) -> None:
        """Called when a trade is closed (agent notifies PM)."""
        if agent_id in self._agents:
            a = self._agents[agent_id]
            a.direction = None
            a.entry_price = 0.0
            a.lot_size = 0.0
            a.current_pnl = 0.0
            a.daily_pnl += pnl
            a.total_pnl += pnl
        self._daily_pnl += pnl
        self._current_equity += pnl

    def get_summary(self) -> dict:
        """Return portfolio summary for the API."""
        dd_pct = 0.0
        if self._peak_equity > 0:
            dd_pct = (self._peak_equity - self._current_equity) / self._peak_equity * 100

        daily_loss_pct = 0.0
        if self._current_equity > 0:
            daily_loss_pct = abs(min(self._daily_pnl, 0)) / self._current_equity * 100

        return {
            "portfolio_id": self.portfolio_id,
            "mode": self.mode,
            "status": "paused" if self._paused else "active",
            "current_equity": round(self._current_equity, 2),
            "peak_equity": round(self._peak_equity, 2),
            "daily_pnl": round(self._daily_pnl, 2),
            "drawdown_pct": round(dd_pct, 2),
            "daily_loss_pct": round(daily_loss_pct, 2),
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_total_drawdown_pct": self.max_total_drawdown_pct,
            "open_positions": sum(1 for a in self._agents.values() if a.direction is not None),
            "max_concurrent_positions": self.max_concurrent_positions,
            "agents": {
                str(aid): {
                    "symbol": a.symbol,
                    "direction": a.direction,
                    "daily_pnl": round(a.daily_pnl, 2),
                    "total_pnl": round(a.total_pnl, 2),
                    "trades_today": a.trades_today,
                }
                for aid, a in self._agents.items()
            },
        }

    def unpause(self) -> None:
        """Manually unpause the portfolio (admin action)."""
        self._paused = False
        _log.info("PM[%s] manually unpaused", self.portfolio_id)

    # ── Private Helpers ──────────────────────────────────────────────

    def _get_correlation_group(self, symbol: str) -> Optional[str]:
        """Find which correlation group a symbol belongs to."""
        for group, symbols in CORRELATION_GROUPS.items():
            if symbol in symbols:
                return group
        return None

    def _check_correlation(self, symbol: str, direction: str) -> TradeValidation:
        """
        Check if adding a position would create excessive correlated exposure.
        E.g., going long US30 when already long NAS100 = ~1.7x exposure.
        """
        group = self._get_correlation_group(symbol)
        if group is None:
            return TradeValidation(True)  # Uncorrelated instrument, OK

        # Count same-direction positions in this correlation group
        same_dir_count = 0
        for a in self._agents.values():
            if a.direction is None:
                continue
            a_group = self._get_correlation_group(a.symbol)
            if a_group == group and a.direction == direction and a.symbol != symbol:
                same_dir_count += 1

        # Allow max 1 same-direction position per correlation group
        if same_dir_count >= 1:
            return TradeValidation(
                False,
                f"Correlated exposure: already {same_dir_count} {direction} in {group} group "
                f"(correlation >{self.correlation_threshold:.0%})"
            )

        return TradeValidation(True)

    def _check_risk_budget(
        self,
        agent_id: int,
        entry_price: float,
        stop_loss: float,
        lot_size: float,
    ) -> TradeValidation:
        """Check if the trade fits within the portfolio risk budget."""
        if self._current_equity <= 0 or entry_price <= 0:
            return TradeValidation(True)  # Can't validate without equity info

        # Calculate risk amount for this trade
        risk_per_unit = abs(entry_price - stop_loss)
        trade_risk = risk_per_unit * lot_size

        # Current total risk across all open positions
        total_risk = sum(
            abs(a.entry_price - (a.entry_price * 0.98 if a.direction == "long" else a.entry_price * 1.02)) * a.lot_size
            for a in self._agents.values()
            if a.direction is not None and a.lot_size > 0
        )

        # Check if adding this trade would exceed portfolio risk budget
        max_risk = self._current_equity * self.max_portfolio_risk_pct / 100
        if total_risk + trade_risk > max_risk:
            # Adjust lot size to fit
            remaining_risk = max(max_risk - total_risk, 0)
            if remaining_risk > 0 and risk_per_unit > 0:
                adjusted_lots = remaining_risk / risk_per_unit
                if adjusted_lots > 0.01:
                    return TradeValidation(True, "lot_size_adjusted", adjusted_lot_size=adjusted_lots)
            return TradeValidation(False, f"Portfolio risk budget exceeded ({total_risk + trade_risk:.2f} > {max_risk:.2f})")

        return TradeValidation(True)


# ── Global Registry ─────────────────────────────────────────────────
# Maps user_id → PortfolioManagerService instance (in-memory, per-process)
_portfolio_managers: dict[int, PortfolioManagerService] = {}


def get_portfolio_manager(user_id: int) -> Optional[PortfolioManagerService]:
    """Get the portfolio manager for a user (if one exists)."""
    return _portfolio_managers.get(user_id)


def create_portfolio_manager(
    portfolio_id: int,
    user_id: int,
    **kwargs,
) -> PortfolioManagerService:
    """Create and register a portfolio manager for a user."""
    pm = PortfolioManagerService(portfolio_id=portfolio_id, user_id=user_id, **kwargs)
    _portfolio_managers[user_id] = pm
    _log.info("Created PortfolioManager[%s] for user %s", portfolio_id, user_id)
    return pm


def remove_portfolio_manager(user_id: int) -> None:
    """Remove a user's portfolio manager."""
    _portfolio_managers.pop(user_id, None)
