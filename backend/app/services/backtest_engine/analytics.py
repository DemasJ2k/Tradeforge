"""
Analytics Module — Computes all backtest performance metrics.

Produces: win rate, profit factor, Sharpe, Sortino, Calmar, SQN,
expectancy, drawdown, monthly returns, consecutive streaks, etc.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .strategy import TradeRecord

# ── Annualisation ───────────────────────────────────────────────────
TRADING_DAYS = 252
RISK_FREE_RATE = 0.0  # Assume 0 for simplicity


def compute_analytics(
    trades: list[TradeRecord],
    equity_curve: list[float],
    initial_balance: float,
) -> dict:
    """Compute all analytics from completed trades + equity curve.

    Returns a flat dict of metric names → values, matching the
    BacktestResult dataclass fields.
    """
    result: dict = {}

    # ── Basic counts ────────────────────────────────────────────
    n = len(trades)
    result["total_trades"] = n

    if n == 0:
        return _zero_result(initial_balance, equity_curve)

    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    commissions = sum(t.commission for t in trades)

    result["winning_trades"] = len(wins)
    result["losing_trades"] = len(losses)
    result["win_rate"] = len(wins) / n * 100 if n > 0 else 0.0

    result["gross_profit"] = sum(wins)
    result["gross_loss"] = abs(sum(losses))
    result["net_profit"] = sum(pnls)

    result["profit_factor"] = (
        result["gross_profit"] / result["gross_loss"]
        if result["gross_loss"] > 0 else
        float("inf") if result["gross_profit"] > 0 else 0.0
    )

    result["avg_win"] = sum(wins) / len(wins) if wins else 0.0
    result["avg_loss"] = abs(sum(losses) / len(losses)) if losses else 0.0
    result["largest_win"] = max(wins) if wins else 0.0
    result["largest_loss"] = abs(min(losses)) if losses else 0.0
    result["avg_trade"] = sum(pnls) / n

    result["payoff_ratio"] = (
        result["avg_win"] / result["avg_loss"]
        if result["avg_loss"] > 0 else float("inf") if result["avg_win"] > 0 else 0.0
    )

    # ── Expectancy ──────────────────────────────────────────────
    wr = result["win_rate"] / 100
    result["expectancy"] = (
        wr * result["avg_win"] - (1 - wr) * result["avg_loss"]
    )

    # ── Bars held ───────────────────────────────────────────────
    bars_held = [t.bars_held for t in trades if t.bars_held > 0]
    result["avg_bars_held"] = sum(bars_held) / len(bars_held) if bars_held else 0.0

    # ── Consecutive streaks ─────────────────────────────────────
    result["max_consecutive_wins"] = _max_consecutive(pnls, positive=True)
    result["max_consecutive_losses"] = _max_consecutive(pnls, positive=False)

    # ── Drawdown from equity curve ──────────────────────────────
    dd, dd_pct = _max_drawdown(equity_curve)
    result["max_drawdown"] = dd
    result["max_drawdown_pct"] = dd_pct

    # ── Risk-adjusted returns ───────────────────────────────────
    result["sharpe_ratio"] = _sharpe(pnls, initial_balance)
    result["sortino_ratio"] = _sortino(pnls, initial_balance)
    result["calmar_ratio"] = _calmar(result["net_profit"], dd, equity_curve)
    result["sqn"] = _sqn(pnls)

    # ── Recovery factor ─────────────────────────────────────────
    result["recovery_factor"] = (
        result["net_profit"] / dd if dd > 0 else
        float("inf") if result["net_profit"] > 0 else 0.0
    )

    # ── Balance ─────────────────────────────────────────────────
    result["initial_balance"] = initial_balance
    result["final_balance"] = equity_curve[-1] if equity_curve else initial_balance

    # ── Monthly returns ─────────────────────────────────────────
    monthly, yearly = _monthly_returns(trades, initial_balance)
    result["monthly_returns"] = monthly
    result["yearly_pnl"] = yearly

    return result


# ── Private Helpers ─────────────────────────────────────────────────

def _zero_result(initial_balance: float, equity_curve: list[float]) -> dict:
    """Return a zeroed-out result dict when no trades."""
    return {
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "win_rate": 0.0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
        "net_profit": 0.0,
        "profit_factor": 0.0,
        "max_drawdown": 0.0,
        "max_drawdown_pct": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "largest_win": 0.0,
        "largest_loss": 0.0,
        "avg_trade": 0.0,
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "calmar_ratio": 0.0,
        "sqn": 0.0,
        "expectancy": 0.0,
        "recovery_factor": 0.0,
        "payoff_ratio": 0.0,
        "max_consecutive_wins": 0,
        "max_consecutive_losses": 0,
        "avg_bars_held": 0.0,
        "initial_balance": initial_balance,
        "final_balance": equity_curve[-1] if equity_curve else initial_balance,
        "monthly_returns": {},
        "yearly_pnl": {},
    }


def _max_consecutive(pnls: list[float], positive: bool) -> int:
    """Count max consecutive wins (positive=True) or losses."""
    max_streak = 0
    streak = 0
    for p in pnls:
        if (positive and p > 0) or (not positive and p < 0):
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


def _max_drawdown(equity_curve: list[float]) -> tuple[float, float]:
    """Return (max_drawdown_absolute, max_drawdown_pct) from equity curve."""
    if len(equity_curve) < 2:
        return 0.0, 0.0

    peak = equity_curve[0]
    max_dd = 0.0
    max_dd_pct = 0.0

    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = peak - eq
        dd_pct = dd / peak * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

    return max_dd, max_dd_pct


def _sharpe(pnls: list[float], initial_balance: float) -> float:
    """Annualised Sharpe ratio from trade PnLs."""
    if len(pnls) < 2:
        return 0.0

    # Convert to returns
    returns = [p / initial_balance for p in pnls]
    mean_r = sum(returns) / len(returns)
    var_r = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
    std_r = math.sqrt(var_r) if var_r > 0 else 0.0

    if std_r == 0:
        return 0.0

    # Annualise: assume each trade is ~1 day
    trades_per_year = min(len(pnls), TRADING_DAYS)
    annualised_mean = mean_r * trades_per_year
    annualised_std = std_r * math.sqrt(trades_per_year)

    return (annualised_mean - RISK_FREE_RATE) / annualised_std


def _sortino(pnls: list[float], initial_balance: float) -> float:
    """Annualised Sortino ratio (downside deviation only)."""
    if len(pnls) < 2:
        return 0.0

    returns = [p / initial_balance for p in pnls]
    mean_r = sum(returns) / len(returns)
    downside = [r for r in returns if r < 0]

    if not downside:
        return float("inf") if mean_r > 0 else 0.0

    downside_var = sum(r ** 2 for r in downside) / len(downside)
    downside_std = math.sqrt(downside_var) if downside_var > 0 else 0.0

    if downside_std == 0:
        return 0.0

    trades_per_year = min(len(pnls), TRADING_DAYS)
    annualised_mean = mean_r * trades_per_year
    annualised_dd_std = downside_std * math.sqrt(trades_per_year)

    return (annualised_mean - RISK_FREE_RATE) / annualised_dd_std


def _calmar(
    net_profit: float, max_drawdown: float, equity_curve: list[float],
) -> float:
    """Calmar ratio = annualised return / max drawdown."""
    if max_drawdown <= 0:
        return float("inf") if net_profit > 0 else 0.0
    if len(equity_curve) < 2:
        return 0.0

    # Rough annualisation: assume daily bars
    n_bars = len(equity_curve)
    years = max(n_bars / TRADING_DAYS, 1 / TRADING_DAYS)
    annual_return = net_profit / years

    return annual_return / max_drawdown


def _sqn(pnls: list[float]) -> float:
    """System Quality Number = sqrt(N) * mean(pnl) / std(pnl)."""
    n = len(pnls)
    if n < 2:
        return 0.0

    mean_p = sum(pnls) / n
    var_p = sum((p - mean_p) ** 2 for p in pnls) / (n - 1)
    std_p = math.sqrt(var_p) if var_p > 0 else 0.0

    if std_p == 0:
        return 0.0

    return math.sqrt(n) * mean_p / std_p


def _monthly_returns(
    trades: list[TradeRecord], initial_balance: float,
) -> tuple[dict, dict]:
    """Group trade PnL by month and year.

    Returns:
        monthly: { "2024-01": 2.5, "2024-02": -1.3, ... }  (pct of initial)
        yearly:  { "2024": 5.2, "2025": -0.8, ... }
    """
    monthly: dict[str, float] = defaultdict(float)
    yearly: dict[str, float] = defaultdict(float)

    for t in trades:
        if not t.exit_time or (isinstance(t.exit_time, (int, float)) and t.exit_time <= 0):
            continue
        try:
            exit_ts = float(t.exit_time) if isinstance(t.exit_time, (int, float)) else 0.0
            if exit_ts <= 0:
                continue
            dt = datetime.fromtimestamp(exit_ts, tz=timezone.utc)
        except (OSError, ValueError):
            continue

        month_key = dt.strftime("%Y-%m")
        year_key = dt.strftime("%Y")
        pnl_pct = t.pnl / initial_balance * 100 if initial_balance > 0 else 0.0

        monthly[month_key] += pnl_pct
        yearly[year_key] += pnl_pct

    # Round values
    monthly = {k: round(v, 2) for k, v in sorted(monthly.items())}
    yearly = {k: round(v, 2) for k, v in sorted(yearly.items())}

    return dict(monthly), dict(yearly)
