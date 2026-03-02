"""
Tearsheet assembler for the V2 backtesting engine.

Combines all analytics modules into a single comprehensive report dict
suitable for API responses and frontend rendering.

Modules consumed:
  - metrics.py      → 30+ core metrics
  - monte_carlo.py  → trade-resample simulation
  - benchmark.py    → buy-and-hold comparison
  - rolling.py      → rolling windowed stats
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

import numpy as np

from .metrics import compute_all_metrics, equity_to_returns, drawdown_series
from .monte_carlo import run_monte_carlo, MonteCarloConfig, MonteCarloResult
from .benchmark import compute_benchmark, BenchmarkResult
from .rolling import compute_rolling, RollingConfig, RollingResult


# ────────────────────────────────────────────────────────────────────
# Tearsheet Config
# ────────────────────────────────────────────────────────────────────

@dataclass
class TearsheetConfig:
    """Controls which sections are computed."""
    bars_per_day: float = 1.0
    risk_free_rate: float = 0.0

    # Monte Carlo
    enable_monte_carlo: bool = True
    monte_carlo: MonteCarloConfig = field(default_factory=MonteCarloConfig)

    # Benchmark
    enable_benchmark: bool = True   # Requires close_prices

    # Rolling
    enable_rolling: bool = True
    rolling: RollingConfig = field(default_factory=RollingConfig)


# ────────────────────────────────────────────────────────────────────
# Tearsheet Result
# ────────────────────────────────────────────────────────────────────

@dataclass
class TearsheetResult:
    """Complete tearsheet output, serialisable to JSON."""
    metrics: dict[str, Any]
    equity_curve: list[dict]
    drawdown_curve: list[float]
    monte_carlo: Optional[dict] = None
    benchmark: Optional[dict] = None
    rolling: Optional[dict] = None

    def to_dict(self) -> dict:
        """Flatten to a plain dict for JSON serialisation."""
        result = {
            "metrics": self.metrics,
            "equity_curve": self.equity_curve,
            "drawdown_curve": self.drawdown_curve,
        }
        if self.monte_carlo is not None:
            result["monte_carlo"] = self.monte_carlo
        if self.benchmark is not None:
            result["benchmark"] = self.benchmark
        if self.rolling is not None:
            result["rolling"] = self.rolling
        return result


# ════════════════════════════════════════════════════════════════════
# Main Assembler
# ════════════════════════════════════════════════════════════════════

def build_tearsheet(
    equity_curve: list[dict],
    closed_trades: list[dict],
    initial_capital: float,
    total_bars: int,
    close_prices: Optional[np.ndarray] = None,
    config: Optional[TearsheetConfig] = None,
) -> TearsheetResult:
    """Build a full analytics tearsheet.

    Parameters
    ----------
    equity_curve : list[dict]
        From RunResult.equity_curve — each with 'equity', 'timestamp', etc.
    closed_trades : list[dict]
        From RunResult.closed_trades — each with 'pnl', 'pnl_pct', etc.
    initial_capital : float
    total_bars : int
    close_prices : np.ndarray, optional
        Close prices of primary instrument for benchmark comparison.
    config : TearsheetConfig, optional

    Returns
    -------
    TearsheetResult
    """
    if config is None:
        config = TearsheetConfig()

    # ── Core Metrics ────────────────────────────────────────────────
    metrics = compute_all_metrics(
        equity_curve=equity_curve,
        closed_trades=closed_trades,
        initial_capital=initial_capital,
        total_bars=total_bars,
        bars_per_day=config.bars_per_day,
        risk_free_rate=config.risk_free_rate,
    )

    # ── Drawdown curve for charting ─────────────────────────────────
    eq_arr = np.array([e["equity"] for e in equity_curve], dtype=np.float64) if equity_curve else np.array([initial_capital])
    dd = drawdown_series(eq_arr)
    dd_list = [round(float(v) * 100, 2) for v in dd]  # Percentage

    # ── Monte Carlo ─────────────────────────────────────────────────
    mc_result = None
    if config.enable_monte_carlo and closed_trades:
        mc = run_monte_carlo(
            closed_trades=closed_trades,
            initial_capital=initial_capital,
            config=config.monte_carlo,
        )
        mc_result = _mc_to_dict(mc)

    # ── Benchmark ───────────────────────────────────────────────────
    bm_result = None
    if config.enable_benchmark and close_prices is not None and len(close_prices) > 1:
        bm = compute_benchmark(
            strategy_equity=equity_curve,
            close_prices=close_prices,
            initial_capital=initial_capital,
            bars_per_day=config.bars_per_day,
        )
        bm_result = _bm_to_dict(bm)
        # Add benchmark metrics to main metrics
        metrics["benchmark_alpha"] = bm.alpha
        metrics["benchmark_beta"] = bm.beta
        metrics["benchmark_information_ratio"] = bm.information_ratio
        metrics["benchmark_correlation"] = bm.correlation
        metrics["buy_and_hold_return_pct"] = bm.buy_and_hold_return_pct
        metrics["buy_and_hold_cagr"] = bm.buy_and_hold_cagr

    # ── Rolling ─────────────────────────────────────────────────────
    roll_result = None
    if config.enable_rolling:
        # Synchronise bars_per_day into rolling config
        r_config = RollingConfig(
            window=config.rolling.window,
            min_periods=config.rolling.min_periods,
            bars_per_day=config.bars_per_day,
            risk_free_rate=config.risk_free_rate,
        )
        roll = compute_rolling(
            equity_curve=equity_curve,
            closed_trades=closed_trades,
            benchmark_prices=close_prices,
            initial_capital=initial_capital,
            config=r_config,
        )
        roll_result = _roll_to_dict(roll)

    return TearsheetResult(
        metrics=metrics,
        equity_curve=equity_curve,
        drawdown_curve=dd_list,
        monte_carlo=mc_result,
        benchmark=bm_result,
        rolling=roll_result,
    )


# ────────────────────────────────────────────────────────────────────
# Serialisation helpers
# ────────────────────────────────────────────────────────────────────

def _mc_to_dict(mc: MonteCarloResult) -> dict:
    """Convert MonteCarloResult to a JSON-safe dict."""
    return {
        "n_simulations": mc.n_simulations,
        "n_trades": mc.n_trades,
        "bust_probability": mc.bust_probability,
        "goal_probability": mc.goal_probability,
        "median_return": mc.median_return,
        "mean_return": mc.mean_return,
        "terminal_equity_mean": mc.terminal_equity_mean,
        "terminal_equity_median": mc.terminal_equity_median,
        "terminal_equity_std": mc.terminal_equity_std,
        "terminal_equity_percentiles": mc.terminal_equity_percentiles,
        "max_drawdown_mean": mc.max_drawdown_mean,
        "max_drawdown_median": mc.max_drawdown_median,
        "max_drawdown_95th": mc.max_drawdown_95th,
        "equity_fan": {str(k): v for k, v in mc.equity_fan.items()},
        # Don't include raw terminal_equities in API (too large)
    }


def _bm_to_dict(bm: BenchmarkResult) -> dict:
    """Convert BenchmarkResult to a JSON-safe dict."""
    return {
        "buy_and_hold_return_pct": bm.buy_and_hold_return_pct,
        "buy_and_hold_cagr": bm.buy_and_hold_cagr,
        "alpha": bm.alpha,
        "beta": bm.beta,
        "information_ratio": bm.information_ratio,
        "correlation": bm.correlation,
        "r_squared": bm.r_squared,
        "tracking_error": bm.tracking_error,
        "benchmark_equity": bm.benchmark_equity,
    }


def _roll_to_dict(roll: RollingResult) -> dict:
    """Convert RollingResult to a JSON-safe dict."""
    d = {
        "window": roll.window,
        "bars_per_day": roll.bars_per_day,
        "sharpe": roll.sharpe,
        "sortino": roll.sortino,
        "volatility": roll.volatility,
        "drawdown": roll.drawdown,
    }
    if roll.beta is not None:
        d["beta"] = roll.beta
    if roll.win_rate is not None:
        d["win_rate"] = roll.win_rate
    return d
