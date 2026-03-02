"""
Strategy Robustness Scoring for the V2 backtesting engine.

Evaluates how robust a strategy is by running walk-forward analysis
across multiple time windows and computing a composite score (0–100).

Components of the score:
  1. Window Profitability  — % of OOS windows that are profitable
  2. Sharpe Consistency    — % of windows with positive Sharpe ratio
  3. CAGR Stability        — 1 - normalised variance of per-window CAGR
  4. Drawdown Resilience   — penalty for extreme OOS drawdowns
  5. Trade Count Stability — penalty if some windows have too few trades

The final score is a weighted average of these components.

Also provides:
  - Per-window detailed statistics
  - Aggregated OOS equity curve
  - Overfit probability estimate (IS vs OOS performance gap)
  - Human-readable assessment
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from app.services.backtest.v2.engine.data_handler import DataHandler
from app.services.backtest.v2.engine.strategy_base import StrategyBase
from app.services.backtest.v2.engine.runner import Runner, RunConfig, RunResult

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RobustnessConfig:
    """Parameters for robustness scoring."""
    n_folds: int = 6                     # Number of walk-forward folds
    train_pct: float = 70.0              # % of each fold for in-sample
    mode: str = "anchored"               # "anchored" or "rolling"
    min_bars_per_fold: int = 100         # Minimum bars in OOS segment

    # Score weights (must sum to 1.0)
    w_profitability: float = 0.30
    w_sharpe_consistency: float = 0.25
    w_cagr_stability: float = 0.20
    w_drawdown_resilience: float = 0.15
    w_trade_count: float = 0.10

    # Thresholds
    max_dd_penalty_threshold: float = 30.0   # DD% above which penalty kicks in
    min_trades_per_window: int = 5           # Below this → penalty
    overfit_gap_threshold: float = 0.50      # IS/OOS gap > 50% → likely overfit


# ────────────────────────────────────────────────────────────────────
# Result Types
# ────────────────────────────────────────────────────────────────────

@dataclass
class WindowResult:
    """Stats for a single walk-forward window."""
    fold: int
    train_bars: int
    test_bars: int
    # In-sample stats
    is_net_profit: float = 0.0
    is_sharpe: float = 0.0
    is_win_rate: float = 0.0
    is_max_dd_pct: float = 0.0
    is_total_trades: int = 0
    is_cagr: float = 0.0
    # Out-of-sample stats
    oos_net_profit: float = 0.0
    oos_sharpe: float = 0.0
    oos_win_rate: float = 0.0
    oos_max_dd_pct: float = 0.0
    oos_total_trades: int = 0
    oos_cagr: float = 0.0
    oos_return_pct: float = 0.0
    # Equity curve (OOS only)
    oos_equity: list[float] = field(default_factory=list)
    oos_trades: list[dict] = field(default_factory=list)


@dataclass
class RobustnessResult:
    """Complete robustness scoring result."""
    score: float                           # 0–100 composite score
    grade: str                             # A/B/C/D/F
    n_folds: int
    windows: list[WindowResult]

    # Component scores (0–100 each)
    profitability_score: float
    sharpe_consistency_score: float
    cagr_stability_score: float
    drawdown_resilience_score: float
    trade_count_score: float

    # Aggregated OOS stats
    oos_total_trades: int
    oos_net_profit: float
    oos_win_rate: float
    oos_sharpe: float
    oos_max_dd_pct: float
    oos_equity_curve: list[float]

    # Overfit detection
    overfit_probability: float             # 0–1 estimate
    is_vs_oos_gap: float                   # IS mean return - OOS mean return (%)
    is_likely_overfit: bool

    # Timing
    elapsed_seconds: float
    summary: str


# ────────────────────────────────────────────────────────────────────
# Window Splitting
# ────────────────────────────────────────────────────────────────────

def _calculate_windows(
    n_bars: int,
    n_folds: int,
    train_pct: float,
    mode: str,
    min_bars_per_fold: int,
) -> list[tuple[int, int, int, int]]:
    """Calculate (train_start, train_end, test_start, test_end) for each fold."""
    windows = []

    if mode == "anchored":
        segment_size = n_bars // (n_folds + 1)
        if segment_size < min_bars_per_fold:
            # Reduce folds to respect minimum
            n_folds = max(1, n_bars // min_bars_per_fold - 1)
            segment_size = n_bars // (n_folds + 1)

        for fold in range(n_folds):
            train_start = 0
            train_end = segment_size * (fold + 1)
            test_start = train_end
            test_end = min(train_end + segment_size, n_bars)
            if test_end - test_start < min_bars_per_fold // 2:
                continue
            windows.append((train_start, train_end, test_start, test_end))
    else:
        # Rolling
        total_per_fold = n_bars // n_folds
        train_size = int(total_per_fold * train_pct / 100)
        test_size = total_per_fold - train_size

        if test_size < min_bars_per_fold // 2:
            test_size = min_bars_per_fold // 2
            train_size = total_per_fold - test_size

        for fold in range(n_folds):
            train_start = fold * test_size
            train_end = train_start + train_size
            test_start = train_end
            test_end = min(test_start + test_size, n_bars)
            if test_end <= test_start or train_end > n_bars:
                continue
            windows.append((train_start, train_end, test_start, test_end))

    return windows


# ────────────────────────────────────────────────────────────────────
# Core Robustness Scorer
# ────────────────────────────────────────────────────────────────────

def score_robustness(
    bars_dict: dict[str, list],
    strategy_factory,
    run_config: Optional[RunConfig] = None,
    config: Optional[RobustnessConfig] = None,
    indicator_configs: Optional[dict] = None,
) -> RobustnessResult:
    """Run walk-forward validation and compute robustness score.

    Parameters
    ----------
    bars_dict : dict[str, list]
        Mapping of symbol → list of bar dicts.
    strategy_factory : callable
        Zero-argument callable returning a fresh StrategyBase instance.
    run_config : RunConfig, optional
        Backtest configuration.
    config : RobustnessConfig, optional
        Scoring parameters.
    indicator_configs : dict, optional
        Indicator configs for DataHandler.

    Returns
    -------
    RobustnessResult
    """
    if config is None:
        config = RobustnessConfig()
    if run_config is None:
        run_config = RunConfig()
    # Disable heavy analytics for sub-runs
    from app.services.backtest.v2.analytics.tearsheet import TearsheetConfig
    fast_tearsheet = TearsheetConfig(
        enable_monte_carlo=False,
        enable_benchmark=False,
        enable_rolling=False,
        bars_per_day=run_config.bars_per_day,
    )
    run_config.tearsheet = fast_tearsheet

    t0 = time.perf_counter()

    primary_sym = next(iter(bars_dict))
    all_bars = bars_dict[primary_sym]
    n_total = len(all_bars)

    # Calculate windows
    win_specs = _calculate_windows(
        n_total, config.n_folds, config.train_pct, config.mode, config.min_bars_per_fold,
    )
    n_folds = len(win_specs)

    if n_folds == 0:
        return _empty_result(config, n_total, time.perf_counter() - t0)

    # ── Run each fold ───────────────────────────────────────────────
    window_results: list[WindowResult] = []
    all_oos_trades: list[dict] = []
    oos_equity: list[float] = [run_config.initial_cash]
    running_balance = run_config.initial_cash

    for fold_idx, (ts, te, os_s, os_e) in enumerate(win_specs):
        fold = fold_idx + 1
        logger.info(
            "Robustness fold %d/%d: train[%d:%d] → test[%d:%d]",
            fold, n_folds, ts, te, os_s, os_e,
        )

        # -- In-sample run --
        is_result = _run_fold(
            bars_dict, ts, te, strategy_factory, run_config,
            indicator_configs, run_config.initial_cash,
        )

        # -- Out-of-sample run --
        oos_result = _run_fold(
            bars_dict, os_s, os_e, strategy_factory, run_config,
            indicator_configs, running_balance,
        )

        # Extract stats
        wr = WindowResult(
            fold=fold,
            train_bars=te - ts,
            test_bars=os_e - os_s,
            # IS
            is_net_profit=is_result.stats.get("net_profit", 0),
            is_sharpe=is_result.stats.get("sharpe_ratio", 0),
            is_win_rate=is_result.stats.get("win_rate", 0),
            is_max_dd_pct=is_result.stats.get("max_drawdown_pct", 0),
            is_total_trades=is_result.stats.get("total_trades", 0),
            is_cagr=is_result.stats.get("cagr", 0),
            # OOS
            oos_net_profit=oos_result.stats.get("net_profit", 0),
            oos_sharpe=oos_result.stats.get("sharpe_ratio", 0),
            oos_win_rate=oos_result.stats.get("win_rate", 0),
            oos_max_dd_pct=oos_result.stats.get("max_drawdown_pct", 0),
            oos_total_trades=oos_result.stats.get("total_trades", 0),
            oos_cagr=oos_result.stats.get("cagr", 0),
            oos_return_pct=oos_result.stats.get("total_return_pct", 0),
            oos_equity=[e["equity"] for e in oos_result.equity_curve],
            oos_trades=oos_result.closed_trades,
        )
        window_results.append(wr)
        all_oos_trades.extend(oos_result.closed_trades)

        # Track running equity
        if oos_result.equity_curve:
            oos_start_eq = oos_result.equity_curve[0]["equity"]
            for e in oos_result.equity_curve[1:]:
                delta = e["equity"] - oos_start_eq
                oos_equity.append(running_balance + delta)
            running_balance += wr.oos_net_profit

    # ── Compute component scores ────────────────────────────────────
    prof_score = _profitability_score(window_results)
    sharpe_score = _sharpe_consistency_score(window_results)
    cagr_score = _cagr_stability_score(window_results)
    dd_score = _drawdown_resilience_score(window_results, config)
    tc_score = _trade_count_score(window_results, config)

    # ── Composite score ─────────────────────────────────────────────
    composite = (
        config.w_profitability * prof_score
        + config.w_sharpe_consistency * sharpe_score
        + config.w_cagr_stability * cagr_score
        + config.w_drawdown_resilience * dd_score
        + config.w_trade_count * tc_score
    )
    composite = round(max(0, min(100, composite)), 1)

    # ── Overfit detection ───────────────────────────────────────────
    is_returns = [w.is_cagr for w in window_results if w.is_cagr != 0]
    oos_returns = [w.oos_cagr for w in window_results if w.oos_cagr != 0]
    is_mean = np.mean(is_returns) if is_returns else 0
    oos_mean = np.mean(oos_returns) if oos_returns else 0
    gap = float(is_mean - oos_mean) if (is_mean != 0 or oos_mean != 0) else 0
    overfit_prob = min(1.0, max(0.0, abs(gap) / max(abs(is_mean), 0.01)))

    # ── Aggregated OOS stats ────────────────────────────────────────
    oos_total_trades = sum(w.oos_total_trades for w in window_results)
    oos_net_profit = sum(w.oos_net_profit for w in window_results)
    oos_win_rates = [w.oos_win_rate for w in window_results if w.oos_total_trades > 0]
    oos_wr = float(np.mean(oos_win_rates)) if oos_win_rates else 0
    oos_sharpes = [w.oos_sharpe for w in window_results]
    oos_sharpe_avg = float(np.mean(oos_sharpes)) if oos_sharpes else 0
    oos_max_dds = [w.oos_max_dd_pct for w in window_results]
    oos_worst_dd = max(oos_max_dds) if oos_max_dds else 0

    grade = _score_to_grade(composite)
    elapsed = time.perf_counter() - t0
    summary = _build_summary(composite, grade, n_folds, prof_score, sharpe_score,
                             gap, overfit_prob > config.overfit_gap_threshold)

    return RobustnessResult(
        score=composite,
        grade=grade,
        n_folds=n_folds,
        windows=window_results,
        profitability_score=round(prof_score, 1),
        sharpe_consistency_score=round(sharpe_score, 1),
        cagr_stability_score=round(cagr_score, 1),
        drawdown_resilience_score=round(dd_score, 1),
        trade_count_score=round(tc_score, 1),
        oos_total_trades=oos_total_trades,
        oos_net_profit=round(oos_net_profit, 2),
        oos_win_rate=round(oos_wr, 4),
        oos_sharpe=round(oos_sharpe_avg, 4),
        oos_max_dd_pct=round(oos_worst_dd, 2),
        oos_equity_curve=oos_equity,
        overfit_probability=round(overfit_prob, 4),
        is_vs_oos_gap=round(gap, 4),
        is_likely_overfit=overfit_prob > config.overfit_gap_threshold,
        elapsed_seconds=round(elapsed, 3),
        summary=summary,
    )


# ────────────────────────────────────────────────────────────────────
# Fold Runner
# ────────────────────────────────────────────────────────────────────

def _run_fold(
    bars_dict: dict[str, list],
    start: int,
    end: int,
    strategy_factory,
    run_config: RunConfig,
    indicator_configs: Optional[dict],
    initial_cash: float,
) -> RunResult:
    """Run a single fold (IS or OOS) and return the result."""
    data = DataHandler()
    for sym, bars in bars_dict.items():
        segment = bars[start:end]
        pv = run_config.point_values.get(sym, 1.0)
        data.add_symbol(sym, segment, indicator_configs=indicator_configs, point_value=pv)

    strategy = strategy_factory()
    # Override initial cash for this fold
    import copy
    fold_config = copy.copy(run_config)
    fold_config.initial_cash = initial_cash

    runner = Runner(data_handler=data, strategy=strategy, config=fold_config)
    return runner.run()


# ────────────────────────────────────────────────────────────────────
# Component Scorers (each returns 0–100)
# ────────────────────────────────────────────────────────────────────

def _profitability_score(windows: list[WindowResult]) -> float:
    """% of OOS windows with positive net profit × 100."""
    if not windows:
        return 0.0
    profitable = sum(1 for w in windows if w.oos_net_profit > 0)
    return profitable / len(windows) * 100


def _sharpe_consistency_score(windows: list[WindowResult]) -> float:
    """% of OOS windows with positive Sharpe × 100."""
    if not windows:
        return 0.0
    positive = sum(1 for w in windows if w.oos_sharpe > 0)
    return positive / len(windows) * 100


def _cagr_stability_score(windows: list[WindowResult]) -> float:
    """Score based on coefficient of variation of OOS CAGR.

    Low variance = high score.
    Score = max(0, 100 × (1 - CV))  where CV = std/|mean|
    """
    cagrs = [w.oos_cagr for w in windows if w.oos_total_trades > 0]
    if len(cagrs) < 2:
        return 50.0  # Neutral if insufficient data
    arr = np.array(cagrs)
    mean = abs(float(np.mean(arr)))
    std = float(np.std(arr, ddof=1))
    if mean <= 1e-9:
        return 50.0
    cv = std / mean
    return max(0.0, min(100.0, 100 * (1 - cv)))


def _drawdown_resilience_score(
    windows: list[WindowResult],
    config: RobustnessConfig,
) -> float:
    """Score based on max DD across OOS windows.

    100 if all DDs ≤ threshold, linearly penalised beyond.
    """
    if not windows:
        return 100.0
    max_dds = [w.oos_max_dd_pct for w in windows]
    worst = max(max_dds)
    if worst <= config.max_dd_penalty_threshold:
        return 100.0
    # Linear penalty: 0 at 100% DD
    penalty_range = 100 - config.max_dd_penalty_threshold
    excess = worst - config.max_dd_penalty_threshold
    return max(0.0, 100 * (1 - excess / penalty_range))


def _trade_count_score(
    windows: list[WindowResult],
    config: RobustnessConfig,
) -> float:
    """Penalty if OOS windows have too few trades.

    Score = 100 if all windows ≥ min_trades, scales down linearly.
    """
    if not windows:
        return 0.0
    counts = [w.oos_total_trades for w in windows]
    above = sum(1 for c in counts if c >= config.min_trades_per_window)
    return above / len(windows) * 100


# ────────────────────────────────────────────────────────────────────
# Grading
# ────────────────────────────────────────────────────────────────────

def _score_to_grade(score: float) -> str:
    """Convert 0–100 score to letter grade."""
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    if score >= 35:
        return "D"
    return "F"


# ────────────────────────────────────────────────────────────────────
# Summary
# ────────────────────────────────────────────────────────────────────

def _build_summary(
    score: float,
    grade: str,
    n_folds: int,
    prof_score: float,
    sharpe_score: float,
    is_oos_gap: float,
    is_overfit: bool,
) -> str:
    """Build a human-readable summary."""
    parts = [f"Robustness Score: {score}/100 (Grade {grade}) across {n_folds} folds."]

    if prof_score >= 80:
        parts.append(f"Strong profitability consistency ({prof_score:.0f}% windows profitable).")
    elif prof_score >= 50:
        parts.append(f"Moderate profitability consistency ({prof_score:.0f}% windows profitable).")
    else:
        parts.append(f"Weak profitability — only {prof_score:.0f}% of windows profitable.")

    if sharpe_score >= 80:
        parts.append(f"Sharpe ratio consistently positive ({sharpe_score:.0f}%).")
    elif sharpe_score < 50:
        parts.append(f"Warning: Sharpe inconsistent — only {sharpe_score:.0f}% positive.")

    if is_overfit:
        parts.append(
            f"⚠ LIKELY OVERFIT — IS vs OOS gap: {is_oos_gap:.4f}. "
            "Strategy performed significantly better in-sample than out-of-sample."
        )

    return " ".join(parts)


# ────────────────────────────────────────────────────────────────────
# Empty result
# ────────────────────────────────────────────────────────────────────

def _empty_result(
    config: RobustnessConfig,
    n_total: int,
    elapsed: float,
) -> RobustnessResult:
    """Return when there aren't enough bars for any folds."""
    return RobustnessResult(
        score=0.0,
        grade="F",
        n_folds=0,
        windows=[],
        profitability_score=0.0,
        sharpe_consistency_score=0.0,
        cagr_stability_score=0.0,
        drawdown_resilience_score=0.0,
        trade_count_score=0.0,
        oos_total_trades=0,
        oos_net_profit=0.0,
        oos_win_rate=0.0,
        oos_sharpe=0.0,
        oos_max_dd_pct=0.0,
        oos_equity_curve=[],
        overfit_probability=0.0,
        is_vs_oos_gap=0.0,
        is_likely_overfit=False,
        elapsed_seconds=round(elapsed, 3),
        summary=f"Insufficient data ({n_total} bars) for {config.n_folds}-fold walk-forward.",
    )
