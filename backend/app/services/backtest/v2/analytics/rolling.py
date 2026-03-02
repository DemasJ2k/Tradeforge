"""
Rolling statistics for the V2 backtesting engine.

Computes windowed rolling metrics over the equity curve:
  - Rolling Sharpe Ratio
  - Rolling Sortino Ratio
  - Rolling Volatility
  - Rolling Beta (vs benchmark)
  - Rolling Drawdown
  - Rolling Win Rate (over trades)

All outputs are aligned arrays suitable for charting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .metrics import TRADING_DAYS_PER_YEAR


# ────────────────────────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RollingConfig:
    """Parameters for rolling window computations."""
    window: int = 60                  # Bars in window
    min_periods: int = 20             # Minimum valid observations
    bars_per_day: float = 1.0
    risk_free_rate: float = 0.0


# ────────────────────────────────────────────────────────────────────
# Core rolling helpers (vectorised via stride tricks)
# ────────────────────────────────────────────────────────────────────

def _rolling_windows(arr: np.ndarray, window: int) -> np.ndarray:
    """Create a view of rolling windows using stride tricks.

    Returns shape (n - window + 1, window).
    """
    if len(arr) < window:
        return np.empty((0, window), dtype=arr.dtype)
    shape = (len(arr) - window + 1, window)
    strides = (arr.strides[0], arr.strides[0])
    return np.lib.stride_tricks.as_strided(arr, shape=shape, strides=strides)


def _pad_left(arr: np.ndarray, total_length: int) -> np.ndarray:
    """Pad array with NaN on the left to match total_length."""
    pad = total_length - len(arr)
    if pad <= 0:
        return arr
    return np.concatenate([np.full(pad, np.nan), arr])


# ────────────────────────────────────────────────────────────────────
# Rolling Sharpe
# ────────────────────────────────────────────────────────────────────

def rolling_sharpe(
    returns: np.ndarray,
    config: Optional[RollingConfig] = None,
) -> np.ndarray:
    """Rolling annualized Sharpe Ratio.

    Returns array of same length as `returns`, NaN-padded at start.
    """
    if config is None:
        config = RollingConfig()

    n = len(returns)
    bars_per_year = config.bars_per_day * TRADING_DAYS_PER_YEAR
    rf_per_bar = config.risk_free_rate / bars_per_year
    scale = math.sqrt(bars_per_year)

    windows = _rolling_windows(returns, config.window)
    if len(windows) == 0:
        return np.full(n, np.nan)

    excess = windows - rf_per_bar
    means = np.mean(excess, axis=1)
    stds = np.std(excess, axis=1, ddof=1)

    with np.errstate(divide="ignore", invalid="ignore"):
        sharpe = np.where(stds > 0, means / stds * scale, 0.0)

    # Mask windows with < min_periods
    if config.min_periods > config.window:
        sharpe[:] = np.nan
    elif config.min_periods > 1:
        # All windows have exactly config.window elements, so all valid
        pass

    return _pad_left(sharpe, n)


# ────────────────────────────────────────────────────────────────────
# Rolling Sortino
# ────────────────────────────────────────────────────────────────────

def rolling_sortino(
    returns: np.ndarray,
    config: Optional[RollingConfig] = None,
) -> np.ndarray:
    """Rolling annualized Sortino Ratio."""
    if config is None:
        config = RollingConfig()

    n = len(returns)
    bars_per_year = config.bars_per_day * TRADING_DAYS_PER_YEAR
    rf_per_bar = config.risk_free_rate / bars_per_year
    scale = math.sqrt(bars_per_year)

    windows = _rolling_windows(returns, config.window)
    if len(windows) == 0:
        return np.full(n, np.nan)

    excess = windows - rf_per_bar
    means = np.mean(excess, axis=1)

    # Downside deviation per window
    downside = np.where(excess < 0, excess, 0.0)
    dd_std = np.sqrt(np.mean(downside ** 2, axis=1))

    with np.errstate(divide="ignore", invalid="ignore"):
        sortino = np.where(dd_std > 0, means / dd_std * scale, 0.0)

    return _pad_left(sortino, n)


# ────────────────────────────────────────────────────────────────────
# Rolling Volatility
# ────────────────────────────────────────────────────────────────────

def rolling_volatility(
    returns: np.ndarray,
    config: Optional[RollingConfig] = None,
) -> np.ndarray:
    """Rolling annualized volatility."""
    if config is None:
        config = RollingConfig()

    n = len(returns)
    bars_per_year = config.bars_per_day * TRADING_DAYS_PER_YEAR

    windows = _rolling_windows(returns, config.window)
    if len(windows) == 0:
        return np.full(n, np.nan)

    vol = np.std(windows, axis=1, ddof=1) * math.sqrt(bars_per_year)
    return _pad_left(vol, n)


# ────────────────────────────────────────────────────────────────────
# Rolling Beta (vs benchmark)
# ────────────────────────────────────────────────────────────────────

def rolling_beta(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    config: Optional[RollingConfig] = None,
) -> np.ndarray:
    """Rolling Beta (OLS slope of strategy vs benchmark returns)."""
    if config is None:
        config = RollingConfig()

    n = min(len(strategy_returns), len(benchmark_returns))
    sr = strategy_returns[:n]
    br = benchmark_returns[:n]

    s_windows = _rolling_windows(sr, config.window)
    b_windows = _rolling_windows(br, config.window)

    if len(s_windows) == 0:
        return np.full(n, np.nan)

    # Beta = Cov(S, B) / Var(B)
    s_mean = np.mean(s_windows, axis=1, keepdims=True)
    b_mean = np.mean(b_windows, axis=1, keepdims=True)
    cov = np.mean((s_windows - s_mean) * (b_windows - b_mean), axis=1)
    var_b = np.mean((b_windows - b_mean) ** 2, axis=1)

    with np.errstate(divide="ignore", invalid="ignore"):
        beta = np.where(var_b > 0, cov / var_b, 0.0)

    return _pad_left(beta, n)


# ────────────────────────────────────────────────────────────────────
# Rolling Drawdown
# ────────────────────────────────────────────────────────────────────

def rolling_drawdown(
    equity_curve: np.ndarray,
    config: Optional[RollingConfig] = None,
) -> np.ndarray:
    """Rolling max drawdown over window (positive pct)."""
    if config is None:
        config = RollingConfig()

    n = len(equity_curve)
    windows = _rolling_windows(equity_curve, config.window)
    if len(windows) == 0:
        return np.full(n, np.nan)

    # Per window: max drawdown
    result = np.empty(len(windows))
    for i in range(len(windows)):
        w = windows[i]
        peak = np.maximum.accumulate(w)
        peak = np.where(peak > 0, peak, 1.0)
        dd = 1.0 - w / peak
        result[i] = float(np.max(dd))

    return _pad_left(result, n)


# ────────────────────────────────────────────────────────────────────
# Rolling Win Rate (trade-level)
# ────────────────────────────────────────────────────────────────────

def rolling_win_rate(
    trade_pnls: np.ndarray,
    window: int = 20,
) -> np.ndarray:
    """Rolling win rate over last `window` trades.

    Returns array of same length as trade_pnls, NaN-padded.
    """
    n = len(trade_pnls)
    if n == 0:
        return np.array([])

    wins = (trade_pnls > 0).astype(np.float64)
    windows = _rolling_windows(wins, window)
    if len(windows) == 0:
        return np.full(n, np.nan)

    wr = np.mean(windows, axis=1)
    return _pad_left(wr, n)


# ════════════════════════════════════════════════════════════════════
# Master Rolling Computation
# ════════════════════════════════════════════════════════════════════

@dataclass
class RollingResult:
    """Complete rolling stats output."""
    sharpe: list[Optional[float]]
    sortino: list[Optional[float]]
    volatility: list[Optional[float]]
    drawdown: list[Optional[float]]
    beta: Optional[list[Optional[float]]]       # None if no benchmark
    win_rate: Optional[list[Optional[float]]]    # None if no trades
    window: int
    bars_per_day: float


def compute_rolling(
    equity_curve: list[dict],
    closed_trades: list[dict],
    benchmark_prices: Optional[np.ndarray] = None,
    initial_capital: float = 10000.0,
    config: Optional[RollingConfig] = None,
) -> RollingResult:
    """Compute all rolling stats.

    Parameters
    ----------
    equity_curve : list[dict]
        Each entry with 'equity' key.
    closed_trades : list[dict]
        Each trade with 'pnl' key.
    benchmark_prices : np.ndarray, optional
        Close prices of benchmark instrument.
    initial_capital : float
    config : RollingConfig, optional

    Returns
    -------
    RollingResult
    """
    if config is None:
        config = RollingConfig()

    eq = np.array([e["equity"] for e in equity_curve], dtype=np.float64) if equity_curve else np.array([initial_capital])
    from .metrics import equity_to_returns
    returns = equity_to_returns(eq)

    # Sharpe / Sortino / Volatility / Drawdown
    _sharpe = rolling_sharpe(returns, config)
    _sortino = rolling_sortino(returns, config)
    _vol = rolling_volatility(returns, config)
    _dd = rolling_drawdown(eq, config)

    def to_list(arr):
        return [None if np.isnan(v) else round(float(v), 4) for v in arr]

    # Beta (optional)
    _beta = None
    if benchmark_prices is not None and len(benchmark_prices) > 1:
        from .benchmark import buy_and_hold_equity
        bh_eq = buy_and_hold_equity(benchmark_prices, initial_capital)
        bh_ret = equity_to_returns(bh_eq)
        _beta_arr = rolling_beta(returns, bh_ret, config)
        _beta = to_list(_beta_arr)

    # Win rate (trade-level)
    _win_rate = None
    if closed_trades:
        pnls = np.array([t["pnl"] for t in closed_trades], dtype=np.float64)
        _wr = rolling_win_rate(pnls, min(config.window, len(pnls)))
        _win_rate = to_list(_wr)

    return RollingResult(
        sharpe=to_list(_sharpe),
        sortino=to_list(_sortino),
        volatility=to_list(_vol),
        drawdown=to_list(_dd),
        beta=_beta,
        win_rate=_win_rate,
        window=config.window,
        bars_per_day=config.bars_per_day,
    )
