"""
Walk-Forward Validation Engine.

Splits data into rolling windows, runs backtests on each out-of-sample
segment, and aggregates results for realistic performance estimates.

Two modes:
  1. Anchored: train window always starts at bar 0, expanding forward
  2. Rolling:  train window slides forward with fixed size

This provides the most realistic estimate of live performance because
no bar is ever tested on data it was optimized on.
"""

import math
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.services.backtest.engine import Bar, Trade, BacktestResult
from app.services.backtest.strategy_backtester import (
    backtest_mss,
    backtest_gold_bt,
    _build_result,
)

logger = logging.getLogger(__name__)


@dataclass
class WFWindow:
    """A single walk-forward window."""
    fold: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    # Results
    train_stats: Optional[dict] = None
    test_stats: Optional[dict] = None
    test_trades: list = field(default_factory=list)
    test_equity: list = field(default_factory=list)


@dataclass
class WFResult:
    """Walk-forward validation result."""
    n_folds: int = 0
    windows: list[WFWindow] = field(default_factory=list)
    # Aggregated OOS stats
    oos_total_trades: int = 0
    oos_winning_trades: int = 0
    oos_losing_trades: int = 0
    oos_win_rate: float = 0.0
    oos_net_profit: float = 0.0
    oos_profit_factor: float = 0.0
    oos_max_drawdown: float = 0.0
    oos_max_drawdown_pct: float = 0.0
    oos_sharpe_ratio: float = 0.0
    oos_expectancy: float = 0.0
    oos_avg_win: float = 0.0
    oos_avg_loss: float = 0.0
    # Combined equity curve (all OOS segments concatenated)
    oos_equity_curve: list[float] = field(default_factory=list)
    oos_trades: list = field(default_factory=list)
    # Consistency metrics
    fold_win_rates: list[float] = field(default_factory=list)
    fold_profit_factors: list[float] = field(default_factory=list)
    fold_net_profits: list[float] = field(default_factory=list)
    consistency_score: float = 0.0  # % of folds that are profitable


def walk_forward_backtest(
    bars: list[Bar],
    strategy_type: str,
    strategy_config: dict,
    n_folds: int = 5,
    train_pct: float = 70.0,
    mode: str = "anchored",
    initial_balance: float = 10000.0,
    spread_points: float = 0.0,
    commission_per_lot: float = 0.0,
    point_value: float = 1.0,
) -> WFResult:
    """
    Run walk-forward validation.

    Args:
        bars: Full bar dataset
        strategy_type: "mss" or "gold_bt"
        strategy_config: Strategy-specific config (mss_config or gold_bt_config)
        n_folds: Number of walk-forward folds (default 5)
        train_pct: % of each fold used for training/in-sample (default 70)
        mode: "anchored" (expanding window) or "rolling" (fixed window)
        initial_balance: Starting balance
        spread_points, commission_per_lot, point_value: Cost parameters

    Returns:
        WFResult with per-fold and aggregated OOS statistics
    """
    N = len(bars)
    if N < 200:
        raise ValueError(f"Need at least 200 bars for walk-forward, got {N}")

    # Calculate window boundaries
    windows = _calculate_windows(N, n_folds, train_pct, mode)

    result = WFResult(n_folds=n_folds)
    all_oos_trades: list[Trade] = []
    running_balance = initial_balance
    oos_equity = [initial_balance]

    peak_balance = initial_balance
    max_dd = 0.0
    max_dd_pct = 0.0

    for w in windows:
        logger.info(
            "WF Fold %d: train[%d:%d] (%d bars) → test[%d:%d] (%d bars)",
            w.fold, w.train_start, w.train_end, w.train_end - w.train_start,
            w.test_start, w.test_end, w.test_end - w.test_start,
        )

        train_bars = bars[w.train_start:w.train_end]
        test_bars = bars[w.test_start:w.test_end]

        # Run in-sample backtest (for reference stats only)
        train_result = _run_backtest(
            train_bars, strategy_type, strategy_config,
            initial_balance, spread_points, commission_per_lot, point_value,
        )
        w.train_stats = _result_to_stats(train_result)

        # Run out-of-sample backtest (this is the real test)
        test_result = _run_backtest(
            test_bars, strategy_type, strategy_config,
            running_balance, spread_points, commission_per_lot, point_value,
        )
        w.test_stats = _result_to_stats(test_result)
        w.test_trades = test_result.trades
        w.test_equity = test_result.equity_curve

        # Accumulate OOS trades
        all_oos_trades.extend(test_result.trades)

        # Track running balance and equity
        if test_result.equity_curve:
            for eq_val in test_result.equity_curve[1:]:
                delta = eq_val - test_result.equity_curve[0]
                current = running_balance + delta
                oos_equity.append(current)

                if current > peak_balance:
                    peak_balance = current
                dd = peak_balance - current
                dd_pct = dd / peak_balance * 100 if peak_balance > 0 else 0
                if dd > max_dd:
                    max_dd = dd
                if dd_pct > max_dd_pct:
                    max_dd_pct = dd_pct

            running_balance += test_result.net_profit

        # Per-fold metrics
        result.fold_win_rates.append(w.test_stats.get("win_rate", 0))
        result.fold_profit_factors.append(w.test_stats.get("profit_factor", 0))
        result.fold_net_profits.append(w.test_stats.get("net_profit", 0))

        result.windows.append(w)

    # Aggregate OOS statistics
    result.oos_equity_curve = oos_equity
    result.oos_trades = all_oos_trades
    result.oos_max_drawdown = round(max_dd, 2)
    result.oos_max_drawdown_pct = round(max_dd_pct, 2)

    if all_oos_trades:
        wins = [t for t in all_oos_trades if t.pnl > 0]
        losses = [t for t in all_oos_trades if t.pnl <= 0]

        result.oos_total_trades = len(all_oos_trades)
        result.oos_winning_trades = len(wins)
        result.oos_losing_trades = len(losses)
        result.oos_win_rate = round(len(wins) / len(all_oos_trades) * 100, 2)

        gross_profit = sum(t.pnl for t in wins) if wins else 0
        gross_loss = abs(sum(t.pnl for t in losses)) if losses else 0
        result.oos_net_profit = round(gross_profit - gross_loss, 2)
        result.oos_profit_factor = round(
            gross_profit / gross_loss if gross_loss > 0 else 999.0, 4
        )

        result.oos_avg_win = round(gross_profit / len(wins), 2) if wins else 0
        result.oos_avg_loss = round(-gross_loss / len(losses), 2) if losses else 0
        result.oos_expectancy = round(result.oos_net_profit / len(all_oos_trades), 2)

        # Sharpe
        if len(all_oos_trades) > 1:
            pnls = [t.pnl for t in all_oos_trades]
            mean_pnl = sum(pnls) / len(pnls)
            variance = sum((p - mean_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
            std = math.sqrt(variance) if variance > 0 else 1
            result.oos_sharpe_ratio = round((mean_pnl / std) * math.sqrt(252), 4) if std > 0 else 0

    # Consistency: % of folds with positive net profit
    profitable_folds = sum(1 for p in result.fold_net_profits if p > 0)
    result.consistency_score = round(profitable_folds / n_folds * 100, 1) if n_folds > 0 else 0

    logger.info(
        "Walk-Forward complete: %d folds, %d OOS trades, %.1f%% WR, PF %.2f, consistency %.0f%%",
        n_folds, result.oos_total_trades, result.oos_win_rate,
        result.oos_profit_factor, result.consistency_score,
    )

    return result


def _calculate_windows(
    n_bars: int, n_folds: int, train_pct: float, mode: str
) -> list[WFWindow]:
    """Calculate train/test window boundaries for each fold."""
    windows = []

    if mode == "anchored":
        # Anchored: train always starts at 0, test window slides forward
        # Total data split into n_folds+1 equal segments
        # Fold 1: train on seg[0:1], test on seg[1:2]
        # Fold 2: train on seg[0:2], test on seg[2:3]
        # etc.
        segment_size = n_bars // (n_folds + 1)
        for fold in range(n_folds):
            train_start = 0
            train_end = segment_size * (fold + 1)
            test_start = train_end
            test_end = min(train_end + segment_size, n_bars)
            if test_end <= test_start:
                continue
            windows.append(WFWindow(
                fold=fold + 1,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            ))
    else:
        # Rolling: fixed-size train window slides forward
        total_per_fold = n_bars // n_folds
        train_size = int(total_per_fold * train_pct / 100)
        test_size = total_per_fold - train_size

        for fold in range(n_folds):
            train_start = fold * test_size
            train_end = train_start + train_size
            test_start = train_end
            test_end = min(test_start + test_size, n_bars)
            if test_end <= test_start or train_end > n_bars:
                continue
            windows.append(WFWindow(
                fold=fold + 1,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            ))

    return windows


def _run_backtest(
    bars: list[Bar],
    strategy_type: str,
    config: dict,
    initial_balance: float,
    spread_points: float,
    commission_per_lot: float,
    point_value: float,
) -> BacktestResult:
    """Run a single backtest segment."""
    if strategy_type == "mss":
        return backtest_mss(
            bars_raw=bars,
            mss_config=config,
            initial_balance=initial_balance,
            spread_points=spread_points,
            commission_per_lot=commission_per_lot,
            point_value=point_value,
        )
    elif strategy_type == "gold_bt":
        return backtest_gold_bt(
            bars_raw=bars,
            gold_config=config,
            initial_balance=initial_balance,
            spread_points=spread_points,
            commission_per_lot=commission_per_lot,
            point_value=point_value,
        )
    else:
        # Fallback: empty result
        return BacktestResult(total_bars=len(bars))


def _result_to_stats(result: BacktestResult) -> dict:
    """Convert BacktestResult to a stats dict."""
    return {
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "losing_trades": result.losing_trades,
        "win_rate": round(result.win_rate, 2),
        "net_profit": round(result.net_profit, 2),
        "profit_factor": round(result.profit_factor, 4),
        "max_drawdown": round(result.max_drawdown, 2),
        "max_drawdown_pct": round(result.max_drawdown_pct, 2),
        "sharpe_ratio": round(result.sharpe_ratio, 4),
        "expectancy": round(result.expectancy, 2),
    }
