"""
Portfolio-level analytics for multi-symbol backtesting (Phase 4).

Provides:
  - Per-symbol performance breakdown
  - Cross-symbol correlation matrix
  - Portfolio diversification metrics
  - Allocation / weight tracking
"""

from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np


# ────────────────────────────────────────────────────────────────────
# Per-Symbol Breakdown
# ────────────────────────────────────────────────────────────────────

def per_symbol_stats(
    closed_trades: list[dict],
    equity_snapshots: list[dict] | None = None,
) -> dict[str, dict[str, Any]]:
    """Compute key stats grouped by symbol.

    Returns {symbol: {total_trades, win_rate, net_profit, ...}}.
    """
    by_sym: dict[str, list[dict]] = {}
    for t in closed_trades:
        sym = t.get("symbol", "UNKNOWN")
        by_sym.setdefault(sym, []).append(t)

    result: dict[str, dict[str, Any]] = {}
    for sym, trades in by_sym.items():
        total = len(trades)
        winners = [t for t in trades if t.get("pnl", 0) > 0]
        losers = [t for t in trades if t.get("pnl", 0) <= 0]

        gross_profit = sum(t["pnl"] for t in winners)
        gross_loss = abs(sum(t["pnl"] for t in losers))
        net_profit = gross_profit - gross_loss

        win_rate = len(winners) / total if total > 0 else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        avg_win = gross_profit / len(winners) if winners else 0.0
        avg_loss = gross_loss / len(losers) if losers else 0.0

        pnls = [t.get("pnl", 0) for t in trades]
        avg_pnl = np.mean(pnls) if pnls else 0.0
        std_pnl = np.std(pnls, ddof=1) if len(pnls) > 1 else 0.0
        sharpe = float(avg_pnl / std_pnl) if std_pnl > 0 else 0.0

        result[sym] = {
            "total_trades": total,
            "winning_trades": len(winners),
            "losing_trades": len(losers),
            "win_rate": round(win_rate * 100, 2),
            "net_profit": round(net_profit, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "profit_factor": round(profit_factor, 4) if not math.isinf(profit_factor) else 999.99,
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "sharpe_per_trade": round(sharpe, 4),
            "total_commission": round(sum(t.get("commission", 0) for t in trades), 2),
        }

    return result


# ────────────────────────────────────────────────────────────────────
# Correlation Matrix
# ────────────────────────────────────────────────────────────────────

def correlation_matrix(
    symbol_returns: dict[str, np.ndarray],
) -> dict[str, Any]:
    """Compute pairwise correlation matrix from per-symbol return series.

    Args:
        symbol_returns: {symbol: 1D ndarray of bar-by-bar returns}

    Returns:
        {"symbols": [...], "matrix": [[float,...], ...], "avg_correlation": float}
    """
    symbols = sorted(symbol_returns.keys())
    n = len(symbols)

    if n < 2:
        return {
            "symbols": symbols,
            "matrix": [[1.0]] if n == 1 else [],
            "avg_correlation": 0.0,
        }

    # Align to common length (shortest series)
    min_len = min(len(symbol_returns[s]) for s in symbols)
    if min_len < 5:
        return {
            "symbols": symbols,
            "matrix": [[1.0] * n for _ in range(n)],
            "avg_correlation": 1.0,
        }

    # Build returns matrix: (n_symbols, min_len)
    mat = np.zeros((n, min_len))
    for i, sym in enumerate(symbols):
        arr = symbol_returns[sym]
        mat[i, :] = arr[:min_len]

    # Compute correlation matrix
    corr = np.corrcoef(mat)
    corr = np.nan_to_num(corr, nan=0.0)

    # Average off-diagonal correlation
    off_diag = []
    for i in range(n):
        for j in range(i + 1, n):
            off_diag.append(float(corr[i, j]))
    avg_corr = float(np.mean(off_diag)) if off_diag else 0.0

    return {
        "symbols": symbols,
        "matrix": [[round(float(corr[i, j]), 4) for j in range(n)] for i in range(n)],
        "avg_correlation": round(avg_corr, 4),
    }


def compute_symbol_returns(
    symbol_closes: dict[str, list[float]],
) -> dict[str, np.ndarray]:
    """Compute log-returns from close prices for each symbol.

    Args:
        symbol_closes: {symbol: [close_0, close_1, ...]}

    Returns:
        {symbol: ndarray of log-returns (length N-1)}
    """
    result: dict[str, np.ndarray] = {}
    for sym, closes in symbol_closes.items():
        if len(closes) < 2:
            result[sym] = np.array([0.0])
            continue
        arr = np.array(closes, dtype=np.float64)
        # Avoid log(0)
        arr = np.maximum(arr, 1e-10)
        rets = np.diff(np.log(arr))
        result[sym] = rets
    return result


# ────────────────────────────────────────────────────────────────────
# Diversification Ratio
# ────────────────────────────────────────────────────────────────────

def diversification_ratio(
    symbol_returns: dict[str, np.ndarray],
    weights: dict[str, float] | None = None,
) -> float:
    """Compute portfolio diversification ratio.

    DR = (sum of weighted individual volatilities) / portfolio volatility.
    DR > 1 means diversification is reducing risk.
    DR = 1 means perfectly correlated (no diversification benefit).

    Args:
        symbol_returns: {symbol: 1D ndarray of returns}
        weights: {symbol: weight}. If None, uses equal weights.

    Returns:
        Diversification ratio (float).
    """
    symbols = sorted(symbol_returns.keys())
    n = len(symbols)

    if n < 2:
        return 1.0

    # Equal weights if not specified
    if weights is None:
        w = np.ones(n) / n
    else:
        w = np.array([weights.get(s, 1.0 / n) for s in symbols])
        w = w / w.sum()  # Normalize

    min_len = min(len(symbol_returns[s]) for s in symbols)
    if min_len < 5:
        return 1.0

    # Build returns matrix
    mat = np.zeros((n, min_len))
    for i, sym in enumerate(symbols):
        mat[i, :] = symbol_returns[sym][:min_len]

    # Individual volatilities
    ind_vols = np.std(mat, axis=1, ddof=1)
    weighted_vol_sum = float(np.dot(w, ind_vols))

    # Portfolio volatility: sqrt(w^T * Cov * w)
    cov = np.cov(mat)
    port_var = float(np.dot(w, np.dot(cov, w)))
    port_vol = math.sqrt(max(port_var, 1e-20))

    if port_vol < 1e-12:
        return 1.0

    return round(weighted_vol_sum / port_vol, 4)


# ────────────────────────────────────────────────────────────────────
# Portfolio Allocation Tracking
# ────────────────────────────────────────────────────────────────────

def compute_allocation_over_time(
    equity_curve: list[dict],
    closed_trades: list[dict],
    symbols: list[str],
) -> list[dict]:
    """Compute approximate allocation weights over time.

    For each equity snapshot, determine what fraction of equity
    is allocated to each symbol based on open trades at that point.

    Returns list of {bar_index, allocations: {symbol: weight}}.
    """
    if not equity_curve or not symbols:
        return []

    # Build trade open/close intervals: (entry_bar, exit_bar, symbol, quantity, entry_price)
    intervals: list[tuple[int, int, str, float, float]] = []
    for t in closed_trades:
        eb = t.get("entry_bar", 0)
        xb = t.get("exit_bar", eb)
        sym = t.get("symbol", "UNKNOWN")
        qty = t.get("quantity", 0)
        ep = t.get("entry_price", 0)
        if xb is None:
            xb = eb
        intervals.append((eb, xb, sym, qty, ep))

    # Sample at regular intervals (every 50 bars or so)
    max_bar = max((e.get("bar_index", 0) for e in equity_curve), default=0)
    step = max(1, max_bar // 50)

    allocations = []
    for bar_idx in range(0, max_bar + 1, step):
        # Find all trades open at this bar
        open_by_sym: dict[str, float] = {s: 0.0 for s in symbols}
        for eb, xb, sym, qty, ep in intervals:
            if eb <= bar_idx <= xb and sym in open_by_sym:
                open_by_sym[sym] += qty * ep  # Notional exposure

        total_exp = sum(open_by_sym.values())
        if total_exp > 0:
            alloc = {s: round(v / total_exp, 4) for s, v in open_by_sym.items()}
        else:
            alloc = {s: 0.0 for s in symbols}

        allocations.append({"bar_index": bar_idx, "allocations": alloc})

    return allocations


# ────────────────────────────────────────────────────────────────────
# Master Function
# ────────────────────────────────────────────────────────────────────

def build_portfolio_analytics(
    closed_trades: list[dict],
    equity_curve: list[dict],
    symbol_closes: dict[str, list[float]],
    symbols: list[str],
) -> dict[str, Any]:
    """Build complete portfolio analytics bundle.

    Returns a dict suitable for API response.
    """
    # Per-symbol breakdown
    sym_stats = per_symbol_stats(closed_trades)

    # Symbol returns and correlation
    sym_returns = compute_symbol_returns(symbol_closes)
    corr = correlation_matrix(sym_returns)
    div_ratio = diversification_ratio(sym_returns)

    # Allocation over time
    alloc = compute_allocation_over_time(equity_curve, closed_trades, symbols)

    return {
        "per_symbol": sym_stats,
        "correlation": corr,
        "diversification_ratio": div_ratio,
        "allocation_over_time": alloc,
        "num_symbols": len(symbols),
        "symbols": symbols,
    }
