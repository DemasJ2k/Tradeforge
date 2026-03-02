"""
Comprehensive metrics for the V2 backtesting engine tearsheet.

Computes 30+ metrics from equity curve and closed trades, organized into:
  - Return metrics (CAGR, annualized return/vol, CAGR/vol ratio)
  - Risk-adjusted ratios (Calmar, Sortino, Omega, Gain-to-Pain, Ulcer)
  - Risk metrics (VaR, CVaR, max DD duration, avg DD, risk of ruin)
  - Trade-level stats (Kelly, exposure, streaks, avg win/loss duration)
  - Basic stats (win rate, profit factor, expectancy, SQN)

All functions are pure — they accept numpy arrays or lists and return floats/dicts.
No side effects, no state.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np


# ────────────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────────────

TRADING_DAYS_PER_YEAR = 252
BARS_PER_DAY_DEFAULT = 1  # Adjusted by caller if intraday


# ════════════════════════════════════════════════════════════════════
#  RETURN METRICS
# ════════════════════════════════════════════════════════════════════

def total_return(equity_curve: np.ndarray) -> float:
    """Total return as a decimal (e.g. 0.15 = 15%)."""
    if len(equity_curve) < 2 or equity_curve[0] <= 0:
        return 0.0
    return (equity_curve[-1] / equity_curve[0]) - 1.0


def cagr(
    equity_curve: np.ndarray,
    bars_per_day: float = BARS_PER_DAY_DEFAULT,
    timestamps: Optional[np.ndarray] = None,
) -> float:
    """Compound Annual Growth Rate.

    CAGR = (final / initial) ^ (1 / years) - 1

    If *timestamps* (Unix seconds) are provided, calendar days are computed
    directly from the first and last timestamp.  Otherwise bar-count is
    converted: ``trading_days * 365 / TRADING_DAYS_PER_YEAR``.
    """
    n = len(equity_curve)
    if n < 2 or equity_curve[0] <= 0:
        return 0.0

    # --- derive calendar days ---
    if timestamps is not None and len(timestamps) >= 2:
        span_sec = float(timestamps[-1] - timestamps[0])
        calendar_days = span_sec / 86_400.0
    else:
        trading_days = (n - 1) / bars_per_day
        calendar_days = trading_days * 365.0 / TRADING_DAYS_PER_YEAR

    if calendar_days <= 0:
        return 0.0
    years = calendar_days / 365.0
    ratio = equity_curve[-1] / equity_curve[0]
    if ratio <= 0:
        return -1.0
    return ratio ** (1.0 / years) - 1.0


def annualized_return(
    equity_curve: np.ndarray,
    bars_per_day: float = BARS_PER_DAY_DEFAULT,
    timestamps: Optional[np.ndarray] = None,
) -> float:
    """Annualized return — alias for CAGR."""
    return cagr(equity_curve, bars_per_day, timestamps=timestamps)


def annualized_volatility(
    returns: np.ndarray,
    bars_per_day: float = BARS_PER_DAY_DEFAULT,
) -> float:
    """Annualized volatility of bar-level returns.

    ann_vol = std(returns) × sqrt(bars_per_year)
    """
    if len(returns) < 2:
        return 0.0
    bars_per_year = bars_per_day * TRADING_DAYS_PER_YEAR
    return float(np.std(returns, ddof=1) * math.sqrt(bars_per_year))


def cagr_over_volatility(
    equity_curve: np.ndarray,
    returns: np.ndarray,
    bars_per_day: float = BARS_PER_DAY_DEFAULT,
    timestamps: Optional[np.ndarray] = None,
) -> float:
    """CAGR / Annualized Volatility — quick risk-adjusted measure."""
    vol = annualized_volatility(returns, bars_per_day)
    if vol <= 0:
        return 0.0
    return cagr(equity_curve, bars_per_day, timestamps=timestamps) / vol


# ════════════════════════════════════════════════════════════════════
#  DRAWDOWN ANALYSIS
# ════════════════════════════════════════════════════════════════════

def drawdown_series(equity_curve: np.ndarray) -> np.ndarray:
    """Compute per-bar drawdown percentage (0 to -1 scale).

    DD(t) = equity(t) / peak(t) - 1
    """
    if len(equity_curve) < 1:
        return np.array([])
    peak = np.maximum.accumulate(equity_curve)
    peak = np.where(peak > 0, peak, 1.0)  # Avoid division by zero
    return equity_curve / peak - 1.0


def max_drawdown(equity_curve: np.ndarray) -> float:
    """Maximum drawdown as a positive percentage (e.g. 0.20 = 20%)."""
    dd = drawdown_series(equity_curve)
    if len(dd) == 0:
        return 0.0
    return float(-np.min(dd))


def max_drawdown_duration(equity_curve: np.ndarray) -> int:
    """Maximum drawdown duration in bars (peak to recovery)."""
    if len(equity_curve) < 2:
        return 0
    peak = equity_curve[0]
    max_dur = 0
    current_dur = 0
    for val in equity_curve:
        if val >= peak:
            peak = val
            max_dur = max(max_dur, current_dur)
            current_dur = 0
        else:
            current_dur += 1
    max_dur = max(max_dur, current_dur)  # In case still in drawdown at end
    return max_dur


def avg_drawdown(equity_curve: np.ndarray) -> float:
    """Average drawdown depth across all drawdown periods."""
    dd = drawdown_series(equity_curve)
    if len(dd) == 0:
        return 0.0
    in_dd = dd[dd < 0]
    if len(in_dd) == 0:
        return 0.0
    return float(-np.mean(in_dd))


def avg_drawdown_duration(equity_curve: np.ndarray) -> float:
    """Average drawdown duration in bars."""
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    durations = []
    current_dur = 0
    for val in equity_curve:
        if val >= peak:
            peak = val
            if current_dur > 0:
                durations.append(current_dur)
            current_dur = 0
        else:
            current_dur += 1
    if current_dur > 0:
        durations.append(current_dur)
    return float(np.mean(durations)) if durations else 0.0


# ════════════════════════════════════════════════════════════════════
#  RISK-ADJUSTED RATIOS
# ════════════════════════════════════════════════════════════════════

def sharpe_ratio(
    returns: np.ndarray,
    risk_free_rate: float = 0.0,
    bars_per_day: float = BARS_PER_DAY_DEFAULT,
) -> float:
    """Annualized Sharpe Ratio.

    Sharpe = (mean(R) - Rf_bar) / std(R) × sqrt(bars_per_year)
    """
    if len(returns) < 2:
        return 0.0
    bars_per_year = bars_per_day * TRADING_DAYS_PER_YEAR
    rf_per_bar = risk_free_rate / bars_per_year
    excess = returns - rf_per_bar
    std = float(np.std(excess, ddof=1))
    if std <= 0:
        return 0.0
    return float(np.mean(excess) / std * math.sqrt(bars_per_year))


def sortino_ratio(
    returns: np.ndarray,
    risk_free_rate: float = 0.0,
    bars_per_day: float = BARS_PER_DAY_DEFAULT,
) -> float:
    """Annualized Sortino Ratio — penalises only downside volatility.

    Sortino = (mean(R) - Rf_bar) / downside_std × sqrt(bars_per_year)
    """
    if len(returns) < 2:
        return 0.0
    bars_per_year = bars_per_day * TRADING_DAYS_PER_YEAR
    rf_per_bar = risk_free_rate / bars_per_year
    excess = returns - rf_per_bar
    downside = excess[excess < 0]
    if len(downside) < 1:
        return float("inf") if float(np.mean(excess)) > 0 else 0.0
    downside_std = float(np.std(downside, ddof=1))
    if downside_std <= 0:
        return 0.0
    return float(np.mean(excess) / downside_std * math.sqrt(bars_per_year))


def calmar_ratio(
    equity_curve: np.ndarray,
    bars_per_day: float = BARS_PER_DAY_DEFAULT,
    timestamps: Optional[np.ndarray] = None,
) -> float:
    """Calmar Ratio = CAGR / |Max Drawdown|.

    The most respected single ratio in managed futures.
    """
    mdd = max_drawdown(equity_curve)
    if mdd <= 0:
        return 0.0
    return cagr(equity_curve, bars_per_day, timestamps=timestamps) / mdd


def omega_ratio(
    returns: np.ndarray,
    threshold: float = 0.0,
) -> float:
    """Omega Ratio — probability-weighted upside / downside.

    Omega = sum(max(R - threshold, 0)) / sum(max(threshold - R, 0))
    """
    if len(returns) < 1:
        return 0.0
    excess = returns - threshold
    gains = float(np.sum(np.maximum(excess, 0)))
    losses = float(np.sum(np.maximum(-excess, 0)))
    if losses <= 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def gain_to_pain_ratio(returns: np.ndarray) -> float:
    """Gain-to-Pain Ratio (Schwager).

    GtP = sum(all returns) / sum(|negative returns|)
    """
    if len(returns) < 1:
        return 0.0
    total = float(np.sum(returns))
    pain = float(np.sum(np.abs(returns[returns < 0])))
    if pain <= 0:
        return float("inf") if total > 0 else 0.0
    return total / pain


def ulcer_index(equity_curve: np.ndarray) -> float:
    """Ulcer Index — RMS of drawdown depth.

    UI = sqrt(mean(DD² ))   where DD is percentage drawdown from peak.
    """
    dd = drawdown_series(equity_curve)
    if len(dd) == 0:
        return 0.0
    return float(np.sqrt(np.mean(dd ** 2)))


def ulcer_performance_index(
    equity_curve: np.ndarray,
    risk_free_rate: float = 0.0,
    bars_per_day: float = BARS_PER_DAY_DEFAULT,
    timestamps: Optional[np.ndarray] = None,
) -> float:
    """Ulcer Performance Index = (annualized_return - Rf) / Ulcer Index."""
    ui = ulcer_index(equity_curve)
    if ui <= 0:
        return 0.0
    ann_ret = annualized_return(equity_curve, bars_per_day, timestamps=timestamps)
    return (ann_ret - risk_free_rate) / ui


# ════════════════════════════════════════════════════════════════════
#  RISK METRICS (VaR, CVaR, Risk of Ruin)
# ════════════════════════════════════════════════════════════════════

def value_at_risk(
    returns: np.ndarray,
    confidence: float = 0.95,
) -> float:
    """Historical Value at Risk (VaR).

    Returns the loss threshold at the given confidence level (positive number).
    VaR_95 means: "95% of the time, daily loss will not exceed this value."
    """
    if len(returns) < 1:
        return 0.0
    percentile = (1.0 - confidence) * 100
    return float(-np.percentile(returns, percentile))


def conditional_var(
    returns: np.ndarray,
    confidence: float = 0.95,
) -> float:
    """Conditional VaR (Expected Shortfall / CVaR).

    Mean of returns below the VaR threshold.
    """
    if len(returns) < 1:
        return 0.0
    var = value_at_risk(returns, confidence)
    tail = returns[returns <= -var]
    if len(tail) == 0:
        return var
    return float(-np.mean(tail))


def risk_of_ruin(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    risk_per_trade: float = 0.02,
    ruin_threshold: float = 0.50,
) -> float:
    """Approximate probability of drawdown exceeding ruin_threshold.

    Uses the simplified gambler's ruin formula:
        RoR = ((1 - edge) / (1 + edge)) ^ units_to_ruin
    where edge = win_rate × (avg_win/avg_loss) - (1-win_rate).
    """
    if avg_loss <= 0 or risk_per_trade <= 0:
        return 0.0
    payoff = avg_win / avg_loss if avg_loss > 0 else 0
    edge = win_rate * payoff - (1 - win_rate)
    if edge <= 0:
        return 1.0  # Negative expectancy → eventual ruin
    advantage = edge / (1 + edge) if (1 + edge) > 0 else 0
    if advantage <= 0 or advantage >= 1:
        return 0.0
    units_to_ruin = ruin_threshold / risk_per_trade
    return float((1 - advantage) ** units_to_ruin)


# ════════════════════════════════════════════════════════════════════
#  TRADE-LEVEL METRICS
# ════════════════════════════════════════════════════════════════════

def kelly_criterion(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Kelly Criterion — optimal fraction of capital to risk.

    Kelly% = W - (1-W)/R   where W=win_rate, R=avg_win/avg_loss
    """
    if avg_loss <= 0:
        return 0.0
    R = avg_win / avg_loss
    if R <= 0:
        return 0.0
    return win_rate - (1 - win_rate) / R


def exposure_time(
    trade_durations: np.ndarray,
    total_bars: int,
) -> float:
    """Fraction of time the strategy was in a position (0–1)."""
    if total_bars <= 0:
        return 0.0
    return float(min(np.sum(trade_durations) / total_bars, 1.0))


def consecutive_wins(trade_results: np.ndarray) -> int:
    """Maximum consecutive winning trades."""
    return _max_streak(trade_results > 0)


def consecutive_losses(trade_results: np.ndarray) -> int:
    """Maximum consecutive losing trades."""
    return _max_streak(trade_results <= 0)


def _max_streak(mask: np.ndarray) -> int:
    """Maximum consecutive True values in a boolean array."""
    if len(mask) == 0:
        return 0
    max_s = 0
    current = 0
    for v in mask:
        if v:
            current += 1
            max_s = max(max_s, current)
        else:
            current = 0
    return max_s


def avg_win_duration(
    trade_pnls: np.ndarray,
    trade_durations: np.ndarray,
) -> float:
    """Average duration of winning trades in bars."""
    mask = trade_pnls > 0
    if not np.any(mask):
        return 0.0
    return float(np.mean(trade_durations[mask]))


def avg_loss_duration(
    trade_pnls: np.ndarray,
    trade_durations: np.ndarray,
) -> float:
    """Average duration of losing trades in bars."""
    mask = trade_pnls <= 0
    if not np.any(mask):
        return 0.0
    return float(np.mean(trade_durations[mask]))


def sqn(sharpe: float, n_trades: int) -> float:
    """System Quality Number — Van Tharp's metric.

    SQN = Sharpe × sqrt(min(n_trades, 100))
    """
    return sharpe * math.sqrt(min(n_trades, 100))


# ════════════════════════════════════════════════════════════════════
#  MONTHLY / PERIODIC RETURNS
# ════════════════════════════════════════════════════════════════════

def monthly_returns(
    equity_curve: np.ndarray,
    timestamps: np.ndarray,
) -> dict[str, list]:
    """Compute monthly return table from equity curve + timestamps.

    Returns dict with keys: 'year', 'month', 'return_pct'
    Timestamps should be Unix seconds.
    """
    import datetime

    if len(equity_curve) < 2 or len(timestamps) < 2:
        return {"year": [], "month": [], "return_pct": []}

    years, months, rets = [], [], []
    prev_equity = equity_curve[0]
    prev_dt = datetime.datetime.fromtimestamp(float(timestamps[0]))
    current_month = (prev_dt.year, prev_dt.month)

    for i in range(1, len(equity_curve)):
        dt = datetime.datetime.fromtimestamp(float(timestamps[i]))
        m = (dt.year, dt.month)
        if m != current_month:
            ret = (equity_curve[i - 1] / prev_equity - 1) * 100 if prev_equity > 0 else 0
            years.append(current_month[0])
            months.append(current_month[1])
            rets.append(round(float(ret), 4))
            prev_equity = equity_curve[i - 1]
            current_month = m

    # Final partial month
    ret = (equity_curve[-1] / prev_equity - 1) * 100 if prev_equity > 0 else 0
    years.append(current_month[0])
    months.append(current_month[1])
    rets.append(round(float(ret), 4))

    return {"year": years, "month": months, "return_pct": rets}


# ════════════════════════════════════════════════════════════════════
#  HELPER — returns from equity curve
# ════════════════════════════════════════════════════════════════════

def equity_to_returns(equity_curve: np.ndarray) -> np.ndarray:
    """Convert equity curve to bar-over-bar percentage returns."""
    if len(equity_curve) < 2:
        return np.array([])
    shifted = np.roll(equity_curve, 1)
    shifted[0] = equity_curve[0]
    with np.errstate(divide="ignore", invalid="ignore"):
        ret = np.where(shifted > 0, equity_curve / shifted - 1.0, 0.0)
    ret[0] = 0.0
    return ret


# ════════════════════════════════════════════════════════════════════
#  AUTO-DETECT — infer bars_per_day from equity-curve timestamps
# ════════════════════════════════════════════════════════════════════

def detect_bars_per_day(timestamps: np.ndarray) -> Optional[float]:
    """Infer the number of bars per trading day from timestamps (seconds).

    Uses the median inter-bar interval.  Returns ``None`` when detection
    fails (too few bars, zero-interval, etc.).
    """
    if len(timestamps) < 10:
        return None
    diffs = np.diff(timestamps)
    diffs = diffs[diffs > 0]                # drop duplicates / gaps
    if len(diffs) < 5:
        return None
    median_seconds = float(np.median(diffs))
    if median_seconds <= 0:
        return None
    bars_per_calendar_day = 86_400.0 / median_seconds
    # Trading day ≈ 24 h for Forex, ~6.5 h for equities.
    # We don't know the market, so return bars per 24 h.
    # Annualisation uses TRADING_DAYS_PER_YEAR, which already
    # accounts for weekends/holidays, so 24-h day is appropriate for
    # Forex-style continuous data.
    return round(bars_per_calendar_day, 2) if bars_per_calendar_day > 0.1 else None


# ════════════════════════════════════════════════════════════════════
#  MASTER COMPUTE — all metrics in one call
# ════════════════════════════════════════════════════════════════════

def compute_all_metrics(
    equity_curve: list[dict],
    closed_trades: list[dict],
    initial_capital: float,
    total_bars: int,
    bars_per_day: float = BARS_PER_DAY_DEFAULT,
    risk_free_rate: float = 0.0,
) -> dict:
    """Compute all 30+ metrics from equity curve and closed trades.

    Parameters
    ----------
    equity_curve : list[dict]
        From RunResult.equity_curve — each with 'equity', 'timestamp', etc.
    closed_trades : list[dict]
        From RunResult.closed_trades — each with 'pnl', 'pnl_pct',
        'duration_bars', 'commission', 'slippage', etc.
    initial_capital : float
        Starting capital.
    total_bars : int
        Total number of bars processed.
    bars_per_day : float
        How many bars per trading day (e.g. 1 for daily, 24 for hourly).
    risk_free_rate : float
        Annualized risk-free rate (e.g. 0.05 for 5%).

    Returns
    -------
    dict
        Comprehensive metrics dictionary.
    """
    # ── Prepare arrays ──────────────────────────────────────────────
    eq = np.array([e["equity"] for e in equity_curve], dtype=np.float64) if equity_curve else np.array([initial_capital])
    ts = np.array([e.get("timestamp", 0) for e in equity_curve], dtype=np.float64) if equity_curve else np.array([0.0])
    # Convert nanosecond timestamps to seconds if needed
    if len(ts) > 0 and ts[0] > 1e15:
        ts = ts / 1e9

    # Auto-detect bars_per_day from timestamps when caller left default
    if bars_per_day <= 1.0 and len(ts) >= 10:
        detected = detect_bars_per_day(ts)
        if detected is not None and detected > 1.0:
            bars_per_day = detected

    # Usable timestamps for CAGR (need at least 2 distinct values)
    _ts_valid = ts if (len(ts) >= 2 and ts[-1] > ts[0] > 0) else None

    returns = equity_to_returns(eq)

    trade_pnls = np.array([t["pnl"] for t in closed_trades], dtype=np.float64) if closed_trades else np.array([])
    trade_pnl_pcts = np.array([t.get("pnl_pct", 0) for t in closed_trades], dtype=np.float64) if closed_trades else np.array([])
    trade_durations = np.array([t.get("duration_bars", 0) for t in closed_trades], dtype=np.float64) if closed_trades else np.array([])
    n_trades = len(closed_trades)

    # ── Basic trade stats ───────────────────────────────────────────
    winners = [t for t in closed_trades if t["pnl"] > 0]
    losers = [t for t in closed_trades if t["pnl"] <= 0]
    n_winners = len(winners)
    n_losers = len(losers)

    gross_profit = sum(t["pnl"] for t in winners)
    gross_loss = abs(sum(t["pnl"] for t in losers))
    net_profit = gross_profit - gross_loss
    total_commission = sum(t.get("commission", 0) for t in closed_trades)
    total_slippage = sum(t.get("slippage", 0) for t in closed_trades)

    wr = n_winners / n_trades if n_trades > 0 else 0.0
    pf = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)

    a_win = gross_profit / n_winners if n_winners > 0 else 0.0
    a_loss = gross_loss / n_losers if n_losers > 0 else 0.0
    expectancy = (wr * a_win - (1 - wr) * a_loss) if n_trades > 0 else 0.0

    # ── Return metrics ──────────────────────────────────────────────
    _cagr = cagr(eq, bars_per_day, timestamps=_ts_valid)
    _ann_vol = annualized_volatility(returns, bars_per_day)
    _total_ret = total_return(eq)

    # ── Drawdown ────────────────────────────────────────────────────
    _max_dd = max_drawdown(eq)
    _max_dd_dur = max_drawdown_duration(eq)
    _avg_dd = avg_drawdown(eq)
    _avg_dd_dur = avg_drawdown_duration(eq)

    # ── Risk-adjusted ratios ────────────────────────────────────────
    _sharpe = sharpe_ratio(returns, risk_free_rate, bars_per_day)
    _sortino = sortino_ratio(returns, risk_free_rate, bars_per_day)
    _calmar = calmar_ratio(eq, bars_per_day, timestamps=_ts_valid)
    _omega = omega_ratio(returns)
    _gtp = gain_to_pain_ratio(returns)
    _ui = ulcer_index(eq)
    _upi = ulcer_performance_index(eq, risk_free_rate, bars_per_day, timestamps=_ts_valid)

    # ── Risk metrics ────────────────────────────────────────────────
    _var95 = value_at_risk(returns, 0.95)
    _var99 = value_at_risk(returns, 0.99)
    _cvar95 = conditional_var(returns, 0.95)
    _cvar99 = conditional_var(returns, 0.99)
    _ror = risk_of_ruin(wr, a_win, a_loss)

    # ── Trade-level ─────────────────────────────────────────────────
    _kelly = kelly_criterion(wr, a_win, a_loss)
    _exposure = exposure_time(trade_durations, total_bars)
    _consec_w = consecutive_wins(trade_pnls) if len(trade_pnls) > 0 else 0
    _consec_l = consecutive_losses(trade_pnls) if len(trade_pnls) > 0 else 0
    _avg_win_dur = avg_win_duration(trade_pnls, trade_durations) if len(trade_pnls) > 0 else 0
    _avg_loss_dur = avg_loss_duration(trade_pnls, trade_durations) if len(trade_pnls) > 0 else 0
    _sqn = sqn(_sharpe, n_trades)

    # ── Monthly returns ─────────────────────────────────────────────
    _monthly = monthly_returns(eq, ts)

    # ── Build result ────────────────────────────────────────────────
    def r(v, d=4):
        """Round helper, handles inf."""
        if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
            return 0.0
        return round(v, d)

    return {
        # Basic
        "total_trades": n_trades,
        "winning_trades": n_winners,
        "losing_trades": n_losers,
        "win_rate": r(wr),
        "profit_factor": r(pf),
        "expectancy": r(expectancy, 2),
        "net_profit": r(net_profit, 2),
        "gross_profit": r(gross_profit, 2),
        "gross_loss": r(gross_loss, 2),
        "avg_win": r(a_win, 2),
        "avg_loss": r(a_loss, 2),
        "largest_win": r(float(np.max(trade_pnls)), 2) if len(trade_pnls) > 0 else 0.0,
        "largest_loss": r(float(np.min(trade_pnls)), 2) if len(trade_pnls) > 0 else 0.0,
        # pnl_pct is already in percent (×100) from position.py / Rust core
        "best_trade_pct": r(float(np.max(trade_pnl_pcts)), 2) if len(trade_pnl_pcts) > 0 else 0.0,
        "worst_trade_pct": r(float(np.min(trade_pnl_pcts)), 2) if len(trade_pnl_pcts) > 0 else 0.0,

        # Capital
        "initial_capital": r(initial_capital, 2),
        "final_equity": r(float(eq[-1]), 2),
        "total_return_pct": r(_total_ret * 100, 2),

        # Return metrics
        "cagr": r(_cagr),
        "annualized_return": r(_cagr),
        "annualized_volatility": r(_ann_vol),
        "cagr_over_volatility": r(_cagr / _ann_vol if _ann_vol > 0 else 0.0),
        "bars_per_day_used": bars_per_day,  # diagnostic — what was actually used

        # Drawdown
        "max_drawdown_pct": r(_max_dd * 100, 2),
        "max_drawdown_duration_bars": _max_dd_dur,
        "avg_drawdown_pct": r(_avg_dd * 100, 2),
        "avg_drawdown_duration_bars": r(_avg_dd_dur, 1),

        # Risk-adjusted ratios
        "sharpe_ratio": r(_sharpe),
        "sortino_ratio": r(_sortino),
        "calmar_ratio": r(_calmar),
        "omega_ratio": r(_omega),
        "gain_to_pain_ratio": r(_gtp),
        "ulcer_index": r(_ui),
        "ulcer_performance_index": r(_upi),
        "sqn": r(_sqn),

        # Risk
        "var_95": r(_var95, 6),
        "var_99": r(_var99, 6),
        "cvar_95": r(_cvar95, 6),
        "cvar_99": r(_cvar99, 6),
        "risk_of_ruin": r(_ror),

        # Trade-level
        "kelly_criterion": r(_kelly),
        "exposure_time_pct": r(_exposure * 100, 2),
        "max_consecutive_wins": _consec_w,
        "max_consecutive_losses": _consec_l,
        "avg_win_duration_bars": r(_avg_win_dur, 1),
        "avg_loss_duration_bars": r(_avg_loss_dur, 1),
        "avg_trade_duration_bars": r(float(np.mean(trade_durations)), 1) if len(trade_durations) > 0 else 0.0,
        "avg_trade_duration_hours": r(
            float(np.mean(trade_durations)) * 24.0 / bars_per_day, 1
        ) if len(trade_durations) > 0 and bars_per_day > 0 else 0.0,
        "total_commission": r(total_commission, 2),
        "total_slippage": r(total_slippage, 2),
        "total_fees": r(total_commission + total_slippage, 2),

        # Monthly returns (for heatmap)
        "monthly_returns": _monthly,
    }
