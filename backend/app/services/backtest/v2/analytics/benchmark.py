"""
Benchmark comparison for the V2 backtesting engine.

Computes buy-and-hold return from the same price data and derives:
  - Alpha (excess return over benchmark)
  - Beta  (OLS regression slope vs benchmark returns)
  - Information Ratio (active return / tracking error)
  - Correlation with benchmark

All functions are pure and accept numpy arrays.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .metrics import (
    TRADING_DAYS_PER_YEAR,
    cagr as compute_cagr,
    equity_to_returns,
    annualized_volatility,
)


# ────────────────────────────────────────────────────────────────────
# Buy-and-Hold Equity Curve
# ────────────────────────────────────────────────────────────────────

def buy_and_hold_equity(
    close_prices: np.ndarray,
    initial_capital: float,
) -> np.ndarray:
    """Build a buy-and-hold equity curve from close prices.

    Assumes we buy at first close and track mark-to-market.
    """
    if len(close_prices) < 1 or close_prices[0] <= 0:
        return np.full(max(len(close_prices), 1), initial_capital)
    return initial_capital * (close_prices / close_prices[0])


# ────────────────────────────────────────────────────────────────────
# OLS Alpha & Beta
# ────────────────────────────────────────────────────────────────────

def ols_alpha_beta(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
) -> tuple[float, float]:
    """Compute Alpha and Beta via OLS regression.

    strategy_returns = alpha + beta × benchmark_returns + epsilon

    Returns (alpha, beta).
    """
    n = min(len(strategy_returns), len(benchmark_returns))
    if n < 2:
        return 0.0, 0.0

    y = strategy_returns[:n]
    x = benchmark_returns[:n]

    x_mean = np.mean(x)
    y_mean = np.mean(y)

    cov_xy = np.sum((x - x_mean) * (y - y_mean))
    var_x = np.sum((x - x_mean) ** 2)

    if var_x <= 0:
        return float(y_mean), 0.0

    beta = float(cov_xy / var_x)
    alpha = float(y_mean - beta * x_mean)
    return alpha, beta


def annualized_alpha(
    per_bar_alpha: float,
    bars_per_day: float = 1,
) -> float:
    """Annualize per-bar alpha.

    Annualized alpha ≈ per_bar_alpha × bars_per_year
    """
    bars_per_year = bars_per_day * TRADING_DAYS_PER_YEAR
    return per_bar_alpha * bars_per_year


# ────────────────────────────────────────────────────────────────────
# Information Ratio
# ────────────────────────────────────────────────────────────────────

def information_ratio(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    bars_per_day: float = 1,
) -> float:
    """Information Ratio = annualized active return / tracking error.

    IR = mean(active) / std(active) × sqrt(bars_per_year)
    """
    n = min(len(strategy_returns), len(benchmark_returns))
    if n < 2:
        return 0.0

    active = strategy_returns[:n] - benchmark_returns[:n]
    std = float(np.std(active, ddof=1))
    if std <= 0:
        return 0.0

    bars_per_year = bars_per_day * TRADING_DAYS_PER_YEAR
    return float(np.mean(active) / std * math.sqrt(bars_per_year))


# ────────────────────────────────────────────────────────────────────
# Correlation
# ────────────────────────────────────────────────────────────────────

def correlation(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
) -> float:
    """Pearson correlation between strategy and benchmark returns."""
    n = min(len(strategy_returns), len(benchmark_returns))
    if n < 2:
        return 0.0
    corr = np.corrcoef(strategy_returns[:n], benchmark_returns[:n])
    r = float(corr[0, 1])
    if math.isnan(r):
        return 0.0
    return r


# ────────────────────────────────────────────────────────────────────
# R-Squared
# ────────────────────────────────────────────────────────────────────

def r_squared(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
) -> float:
    """R² — proportion of strategy variance explained by benchmark."""
    c = correlation(strategy_returns, benchmark_returns)
    return c ** 2


# ════════════════════════════════════════════════════════════════════
# Master Benchmark Computation
# ════════════════════════════════════════════════════════════════════

@dataclass
class BenchmarkResult:
    """Results of benchmark comparison."""
    buy_and_hold_return_pct: float
    buy_and_hold_cagr: float
    alpha: float           # Annualized
    beta: float
    information_ratio: float
    correlation: float
    r_squared: float
    tracking_error: float  # Annualized
    benchmark_equity: list[float]  # For overlay chart


def compute_benchmark(
    strategy_equity: list[dict],
    close_prices: np.ndarray,
    initial_capital: float,
    bars_per_day: float = 1,
) -> BenchmarkResult:
    """Compute all benchmark metrics.

    Parameters
    ----------
    strategy_equity : list[dict]
        Strategy equity curve dicts (each with 'equity' key).
    close_prices : np.ndarray
        Close prices of the primary instrument (same length as equity curve).
    initial_capital : float
    bars_per_day : float

    Returns
    -------
    BenchmarkResult
    """
    strat_eq = np.array([e["equity"] for e in strategy_equity], dtype=np.float64) if strategy_equity else np.array([initial_capital])

    # Build buy-and-hold
    if len(close_prices) == 0:
        close_prices = np.array([1.0])
    bh_eq = buy_and_hold_equity(close_prices, initial_capital)

    # Align lengths
    min_len = min(len(strat_eq), len(bh_eq))
    strat_eq = strat_eq[:min_len]
    bh_eq = bh_eq[:min_len]

    strat_ret = equity_to_returns(strat_eq)
    bh_ret = equity_to_returns(bh_eq)

    # OLS
    per_bar_alpha, beta = ols_alpha_beta(strat_ret, bh_ret)
    ann_alpha = annualized_alpha(per_bar_alpha, bars_per_day)

    # IR
    ir = information_ratio(strat_ret, bh_ret, bars_per_day)

    # Correlation / R²
    corr = correlation(strat_ret, bh_ret)
    r2 = corr ** 2

    # Tracking error
    bars_per_year = bars_per_day * TRADING_DAYS_PER_YEAR
    active = strat_ret - bh_ret
    te = float(np.std(active, ddof=1) * math.sqrt(bars_per_year)) if len(active) > 1 else 0.0

    # Buy-and-hold stats
    bh_total_ret = (bh_eq[-1] / bh_eq[0] - 1.0) * 100 if bh_eq[0] > 0 else 0.0
    bh_cagr = compute_cagr(bh_eq, bars_per_day)

    def r(v, d=4):
        if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
            return 0.0
        return round(v, d)

    return BenchmarkResult(
        buy_and_hold_return_pct=r(bh_total_ret, 2),
        buy_and_hold_cagr=r(bh_cagr),
        alpha=r(ann_alpha),
        beta=r(beta),
        information_ratio=r(ir),
        correlation=r(corr),
        r_squared=r(r2),
        tracking_error=r(te),
        benchmark_equity=[round(float(v), 2) for v in bh_eq.tolist()],
    )
