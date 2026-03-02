"""
Monte Carlo simulation for the V2 backtesting engine.

Resamples closed trades to generate thousands of alternative equity paths,
then computes:
  - Bust probability (chance of drawdown exceeding threshold)
  - Goal probability (chance of achieving target return)
  - Equity fan chart data (percentile bands)
  - Distribution statistics of terminal equity
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ────────────────────────────────────────────────────────────────────
# Configuration & Result
# ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MonteCarloConfig:
    """Parameters for Monte Carlo simulation."""
    n_simulations: int = 1000
    seed: Optional[int] = 42
    bust_threshold: float = 0.50      # 50% drawdown = bust
    goal_return: float = 0.50         # 50% return = goal
    percentiles: tuple = (5, 10, 25, 50, 75, 90, 95)
    resample_method: str = "trade"    # "trade" or "block"
    block_size: int = 5               # For block bootstrap


@dataclass
class MonteCarloResult:
    """Output of a Monte Carlo simulation run."""
    n_simulations: int
    n_trades: int
    bust_probability: float            # 0–1
    goal_probability: float            # 0–1
    median_return: float               # Decimal
    mean_return: float                 # Decimal
    terminal_equity_mean: float
    terminal_equity_median: float
    terminal_equity_std: float
    terminal_equity_percentiles: dict[int, float]  # {5: ..., 95: ...}
    max_drawdown_mean: float           # Positive pct
    max_drawdown_median: float
    max_drawdown_95th: float           # 95th percentile of max DD
    equity_fan: dict[int, list[float]] # {percentile: [equity_at_trade_0, ...]}
    terminal_equities: list[float]     # Raw terminal equity array for histograms


def run_monte_carlo(
    closed_trades: list[dict],
    initial_capital: float,
    config: Optional[MonteCarloConfig] = None,
) -> MonteCarloResult:
    """Run Monte Carlo simulation by resampling trade PnLs.

    Parameters
    ----------
    closed_trades : list[dict]
        Each trade dict must have 'pnl' key.
    initial_capital : float
        Starting capital.
    config : MonteCarloConfig, optional
        Simulation parameters.  Defaults used if None.

    Returns
    -------
    MonteCarloResult
    """
    if config is None:
        config = MonteCarloConfig()

    n_trades = len(closed_trades)
    if n_trades == 0:
        return _empty_result(initial_capital, config)

    rng = np.random.default_rng(config.seed)
    pnls = np.array([t["pnl"] for t in closed_trades], dtype=np.float64)

    n_sim = config.n_simulations
    n_steps = n_trades

    # ── Resample trade sequences ────────────────────────────────────
    if config.resample_method == "block":
        sim_pnls = _block_bootstrap(pnls, n_sim, n_steps, config.block_size, rng)
    else:
        # Standard trade-level resample (with replacement)
        indices = rng.integers(0, n_trades, size=(n_sim, n_steps))
        sim_pnls = pnls[indices]  # (n_sim, n_steps)

    # ── Build equity curves ─────────────────────────────────────────
    cum_pnl = np.cumsum(sim_pnls, axis=1)                    # (n_sim, n_steps)
    equity_curves = initial_capital + cum_pnl                 # (n_sim, n_steps)

    # Prepend initial capital column
    init_col = np.full((n_sim, 1), initial_capital)
    equity_full = np.hstack([init_col, equity_curves])        # (n_sim, n_steps+1)

    terminal = equity_full[:, -1]

    # ── Terminal equity stats ───────────────────────────────────────
    terminal_returns = terminal / initial_capital - 1.0

    # ── Drawdown analysis per simulation ────────────────────────────
    peak = np.maximum.accumulate(equity_full, axis=1)
    peak = np.where(peak > 0, peak, 1.0)
    dd = 1.0 - equity_full / peak                             # Positive pct
    max_dd_per_sim = np.max(dd, axis=1)

    # ── Bust / Goal ─────────────────────────────────────────────────
    bust_count = int(np.sum(max_dd_per_sim >= config.bust_threshold))
    goal_count = int(np.sum(terminal_returns >= config.goal_return))

    # ── Equity fan (percentile bands at each trade step) ────────────
    equity_fan = {}
    for p in config.percentiles:
        equity_fan[p] = np.percentile(equity_full, p, axis=0).tolist()

    # ── Terminal equity percentiles ─────────────────────────────────
    terminal_pctls = {}
    for p in config.percentiles:
        terminal_pctls[p] = round(float(np.percentile(terminal, p)), 2)

    return MonteCarloResult(
        n_simulations=n_sim,
        n_trades=n_trades,
        bust_probability=round(bust_count / n_sim, 4),
        goal_probability=round(goal_count / n_sim, 4),
        median_return=round(float(np.median(terminal_returns)), 4),
        mean_return=round(float(np.mean(terminal_returns)), 4),
        terminal_equity_mean=round(float(np.mean(terminal)), 2),
        terminal_equity_median=round(float(np.median(terminal)), 2),
        terminal_equity_std=round(float(np.std(terminal)), 2),
        terminal_equity_percentiles=terminal_pctls,
        max_drawdown_mean=round(float(np.mean(max_dd_per_sim)) * 100, 2),
        max_drawdown_median=round(float(np.median(max_dd_per_sim)) * 100, 2),
        max_drawdown_95th=round(float(np.percentile(max_dd_per_sim, 95)) * 100, 2),
        equity_fan=equity_fan,
        terminal_equities=[round(float(t), 2) for t in terminal.tolist()],
    )


# ────────────────────────────────────────────────────────────────────
# Block bootstrap
# ────────────────────────────────────────────────────────────────────

def _block_bootstrap(
    pnls: np.ndarray,
    n_sim: int,
    n_steps: int,
    block_size: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Block bootstrap — preserves serial correlation within blocks."""
    n = len(pnls)
    if block_size < 1:
        block_size = 1
    blocks_needed = math.ceil(n_steps / block_size)

    result = np.empty((n_sim, n_steps), dtype=np.float64)
    for i in range(n_sim):
        start_indices = rng.integers(0, n - block_size + 1, size=blocks_needed)
        sequence = np.concatenate([pnls[s:s + block_size] for s in start_indices])
        result[i] = sequence[:n_steps]
    return result


# ────────────────────────────────────────────────────────────────────
# Empty result helper
# ────────────────────────────────────────────────────────────────────

def _empty_result(initial_capital: float, config: MonteCarloConfig) -> MonteCarloResult:
    """Return a zeroed-out result when there are no trades."""
    empty_fan = {p: [initial_capital] for p in config.percentiles}
    empty_pctls = {p: initial_capital for p in config.percentiles}
    return MonteCarloResult(
        n_simulations=config.n_simulations,
        n_trades=0,
        bust_probability=0.0,
        goal_probability=0.0,
        median_return=0.0,
        mean_return=0.0,
        terminal_equity_mean=initial_capital,
        terminal_equity_median=initial_capital,
        terminal_equity_std=0.0,
        terminal_equity_percentiles=empty_pctls,
        max_drawdown_mean=0.0,
        max_drawdown_median=0.0,
        max_drawdown_95th=0.0,
        equity_fan=empty_fan,
        terminal_equities=[initial_capital],
    )
