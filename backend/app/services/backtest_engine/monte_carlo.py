"""
Monte Carlo Simulation — V3 Engine.

Generates confidence intervals by reshuffling/resampling trade results:
  1. Trade Resampling:  Randomly reorder trades to produce alternate equity paths
  2. Return Shuffling:  Randomly shuffle bar-to-bar returns
  3. Data Perturbation: Add noise to bar data and re-run engine

Produces confidence bands (5th, 25th, 50th, 75th, 95th percentiles) for
key metrics: final equity, max drawdown, win rate, profit factor.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Callable, Optional

from .bar import Bar
from .engine import Engine, EngineConfig, BacktestResult
from .data_feed import DataFeed
from .instrument import Instrument, get_instrument
from .strategy import StrategyBase

logger = logging.getLogger(__name__)


@dataclass
class MCResult:
    """Monte Carlo simulation results."""
    n_simulations: int = 0
    method: str = "trade_resample"

    # Confidence intervals for final equity
    final_equity_p5: float = 0.0
    final_equity_p25: float = 0.0
    final_equity_p50: float = 0.0
    final_equity_p75: float = 0.0
    final_equity_p95: float = 0.0

    # Confidence intervals for max drawdown
    max_dd_p5: float = 0.0
    max_dd_p25: float = 0.0
    max_dd_p50: float = 0.0
    max_dd_p75: float = 0.0
    max_dd_p95: float = 0.0

    # Confidence intervals for max drawdown %
    max_dd_pct_p5: float = 0.0
    max_dd_pct_p25: float = 0.0
    max_dd_pct_p50: float = 0.0
    max_dd_pct_p75: float = 0.0
    max_dd_pct_p95: float = 0.0

    # Probability of ruin (equity dropping below threshold)
    prob_ruin: float = 0.0
    ruin_threshold: float = 0.0

    # All simulation equity curves (for charting)
    equity_paths: list[list[float]] = field(default_factory=list)

    # Distribution of final equities
    final_equities: list[float] = field(default_factory=list)
    max_drawdowns: list[float] = field(default_factory=list)
    max_drawdowns_pct: list[float] = field(default_factory=list)


def monte_carlo_trade_resample(
    trades: list[dict],
    initial_balance: float = 10_000.0,
    n_simulations: int = 1000,
    ruin_threshold_pct: float = 50.0,
    seed: Optional[int] = None,
) -> MCResult:
    """Monte Carlo via trade resampling (shuffle trade order).

    Takes completed trades from a backtest and randomly reorders them
    to generate alternate equity paths. Fast — no re-running the engine.

    Args:
        trades:             List of trade dicts with 'pnl' field
        initial_balance:    Starting balance
        n_simulations:      Number of random permutations
        ruin_threshold_pct: % of initial balance that defines ruin
        seed:               Random seed for reproducibility
    """
    if seed is not None:
        random.seed(seed)

    pnls = [t.get("pnl", 0.0) for t in trades]
    n_trades = len(pnls)

    if n_trades == 0:
        return MCResult(n_simulations=n_simulations, method="trade_resample")

    ruin_level = initial_balance * (1 - ruin_threshold_pct / 100)

    all_final_eq: list[float] = []
    all_max_dd: list[float] = []
    all_max_dd_pct: list[float] = []
    all_paths: list[list[float]] = []
    ruin_count = 0

    for _ in range(n_simulations):
        shuffled = pnls.copy()
        random.shuffle(shuffled)

        equity = [initial_balance]
        peak = initial_balance
        max_dd = 0.0
        max_dd_pct = 0.0
        hit_ruin = False

        balance = initial_balance
        for pnl in shuffled:
            balance += pnl
            equity.append(balance)

            if balance > peak:
                peak = balance
            dd = peak - balance
            dd_pct = dd / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)
            max_dd_pct = max(max_dd_pct, dd_pct)

            if balance <= ruin_level:
                hit_ruin = True

        all_final_eq.append(balance)
        all_max_dd.append(max_dd)
        all_max_dd_pct.append(max_dd_pct)
        all_paths.append(equity)
        if hit_ruin:
            ruin_count += 1

    # Compute percentiles
    result = MCResult(
        n_simulations=n_simulations,
        method="trade_resample",
        final_equities=sorted(all_final_eq),
        max_drawdowns=sorted(all_max_dd),
        max_drawdowns_pct=sorted(all_max_dd_pct),
        prob_ruin=round(ruin_count / n_simulations * 100, 2),
        ruin_threshold=ruin_level,
    )

    # Only store subset of paths for charting (max 100)
    step = max(1, n_simulations // 100)
    result.equity_paths = all_paths[::step]

    _fill_percentiles(result, all_final_eq, all_max_dd, all_max_dd_pct)

    logger.info(
        "Monte Carlo complete: %d sims, median final=%.2f, "
        "median DD=%.2f, P(ruin)=%.1f%%",
        n_simulations, result.final_equity_p50,
        result.max_dd_p50, result.prob_ruin,
    )

    return result


def monte_carlo_data_perturbation(
    bars: list[Bar],
    strategy_factory: Callable[[], StrategyBase],
    symbol: str = "ASSET",
    indicator_configs: list[dict] | None = None,
    engine_config: EngineConfig | None = None,
    n_simulations: int = 50,
    noise_pct: float = 0.5,
    ruin_threshold_pct: float = 50.0,
    seed: Optional[int] = None,
) -> MCResult:
    """Monte Carlo via data perturbation — add noise to bars and re-run.

    Slower but more realistic. Adds random noise to OHLC data and
    re-runs the full engine for each simulation.

    Args:
        bars:               Original bar data
        strategy_factory:   Creates a fresh strategy per simulation
        noise_pct:          Max % noise added to each bar (default 0.5%)
        n_simulations:      Number of simulations (keep low, ~50)
    """
    if seed is not None:
        random.seed(seed)

    cfg = engine_config or EngineConfig()
    instrument = get_instrument(symbol)
    ruin_level = cfg.initial_balance * (1 - ruin_threshold_pct / 100)

    all_final_eq: list[float] = []
    all_max_dd: list[float] = []
    all_max_dd_pct: list[float] = []
    all_paths: list[list[float]] = []
    ruin_count = 0

    for sim in range(n_simulations):
        # Perturb bars
        noisy_bars = _perturb_bars(bars, noise_pct)

        # Run engine
        strategy = strategy_factory()
        feed = DataFeed()
        feed.add_symbol(symbol, noisy_bars, indicator_configs=indicator_configs)

        engine = Engine(
            strategy=strategy, data_feed=feed,
            instrument=instrument, config=cfg,
        )
        result = engine.run(symbol)

        # Collect metrics
        eq = result.equity_curve
        final_eq = eq[-1] if eq else cfg.initial_balance
        all_final_eq.append(final_eq)
        all_max_dd.append(result.max_drawdown)
        all_max_dd_pct.append(result.max_drawdown_pct)
        all_paths.append(eq)

        if final_eq <= ruin_level:
            ruin_count += 1

    # Build result
    mc_result = MCResult(
        n_simulations=n_simulations,
        method="data_perturbation",
        final_equities=sorted(all_final_eq),
        max_drawdowns=sorted(all_max_dd),
        max_drawdowns_pct=sorted(all_max_dd_pct),
        prob_ruin=round(ruin_count / n_simulations * 100, 2),
        ruin_threshold=ruin_level,
    )

    step = max(1, n_simulations // 100)
    mc_result.equity_paths = all_paths[::step]

    _fill_percentiles(mc_result, all_final_eq, all_max_dd, all_max_dd_pct)

    logger.info(
        "Monte Carlo (data perturb) complete: %d sims, median final=%.2f, "
        "median DD=%.2f, P(ruin)=%.1f%%",
        n_simulations, mc_result.final_equity_p50,
        mc_result.max_dd_p50, mc_result.prob_ruin,
    )

    return mc_result


# ── Internals ───────────────────────────────────────────────────────

def _percentile(sorted_data: list[float], pct: float) -> float:
    """Get percentile from pre-sorted data."""
    if not sorted_data:
        return 0.0
    idx = pct / 100 * (len(sorted_data) - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return sorted_data[lo]
    frac = idx - lo
    return sorted_data[lo] * (1 - frac) + sorted_data[hi] * frac


def _fill_percentiles(
    result: MCResult,
    final_eq: list[float],
    max_dd: list[float],
    max_dd_pct: list[float],
) -> None:
    """Fill all percentile fields on MCResult."""
    feq = sorted(final_eq)
    mdd = sorted(max_dd)
    mddp = sorted(max_dd_pct)

    result.final_equity_p5 = round(_percentile(feq, 5), 2)
    result.final_equity_p25 = round(_percentile(feq, 25), 2)
    result.final_equity_p50 = round(_percentile(feq, 50), 2)
    result.final_equity_p75 = round(_percentile(feq, 75), 2)
    result.final_equity_p95 = round(_percentile(feq, 95), 2)

    result.max_dd_p5 = round(_percentile(mdd, 5), 2)
    result.max_dd_p25 = round(_percentile(mdd, 25), 2)
    result.max_dd_p50 = round(_percentile(mdd, 50), 2)
    result.max_dd_p75 = round(_percentile(mdd, 75), 2)
    result.max_dd_p95 = round(_percentile(mdd, 95), 2)

    result.max_dd_pct_p5 = round(_percentile(mddp, 5), 2)
    result.max_dd_pct_p25 = round(_percentile(mddp, 25), 2)
    result.max_dd_pct_p50 = round(_percentile(mddp, 50), 2)
    result.max_dd_pct_p75 = round(_percentile(mddp, 75), 2)
    result.max_dd_pct_p95 = round(_percentile(mddp, 95), 2)


def _perturb_bars(bars: list[Bar], noise_pct: float) -> list[Bar]:
    """Add random noise to bars while preserving OHLC validity."""
    noisy: list[Bar] = []
    for bar in bars:
        factor = 1 + random.uniform(-noise_pct, noise_pct) / 100
        o = bar.open * factor
        h = bar.high * (1 + random.uniform(0, noise_pct) / 100)
        l = bar.low * (1 - random.uniform(0, noise_pct) / 100)
        c = bar.close * (1 + random.uniform(-noise_pct, noise_pct) / 100)

        # Ensure OHLC validity
        h = max(h, o, c)
        l = min(l, o, c)

        noisy.append(Bar(
            timestamp=bar.timestamp,
            open=o, high=h, low=l, close=c,
            volume=bar.volume,
        ))
    return noisy
