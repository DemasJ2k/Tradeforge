"""V2 Analytics — metrics, Monte Carlo, tearsheet, benchmark, rolling stats."""

from .metrics import compute_all_metrics, equity_to_returns, drawdown_series
from .monte_carlo import run_monte_carlo, MonteCarloConfig, MonteCarloResult
from .benchmark import compute_benchmark, BenchmarkResult
from .rolling import compute_rolling, RollingConfig, RollingResult
from .tearsheet import build_tearsheet, TearsheetConfig, TearsheetResult

__all__ = [
    # Metrics
    "compute_all_metrics",
    "equity_to_returns",
    "drawdown_series",
    # Monte Carlo
    "run_monte_carlo",
    "MonteCarloConfig",
    "MonteCarloResult",
    # Benchmark
    "compute_benchmark",
    "BenchmarkResult",
    # Rolling
    "compute_rolling",
    "RollingConfig",
    "RollingResult",
    # Tearsheet
    "build_tearsheet",
    "TearsheetConfig",
    "TearsheetResult",
]
