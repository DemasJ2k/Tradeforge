"""
Indicator Engine — Vectorized indicator computation using NumPy.

Computes all indicators upfront for the entire bar series.
This is the "vectorized" half of the hybrid architecture.
"""

from __future__ import annotations

import math
import numpy as np
from typing import Any, Optional


def compute_indicators(
    bars: list[dict],
    indicator_configs: list[dict],
) -> dict[str, np.ndarray]:
    """Compute all indicators for a bar series.

    Args:
        bars: List of bar dicts with keys: time, open, high, low, close, volume
        indicator_configs: List of indicator config dicts, e.g.:
            [{"type": "ema", "period": 20, "source": "close"}, ...]

    Returns:
        Dict mapping indicator name to numpy array of values.
    """
    n = len(bars)
    if n == 0:
        return {}

    # Build price arrays
    opens = np.array([b["open"] for b in bars], dtype=np.float64)
    highs = np.array([b["high"] for b in bars], dtype=np.float64)
    lows = np.array([b["low"] for b in bars], dtype=np.float64)
    closes = np.array([b["close"] for b in bars], dtype=np.float64)
    volumes = np.array([b.get("volume", 0) for b in bars], dtype=np.float64)

    source_map = {
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
        "hl2": (highs + lows) / 2,
        "hlc3": (highs + lows + closes) / 3,
        "ohlc4": (opens + highs + lows + closes) / 4,
    }

    results: dict[str, np.ndarray] = {
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    }

    for cfg in indicator_configs:
        ind_type = cfg.get("type", "").lower()
        period = int(cfg.get("period", 14))
        source_key = cfg.get("source", "close").lower()
        source = source_map.get(source_key, closes)
        name = cfg.get("name", f"{ind_type}_{period}")

        try:
            if ind_type == "sma":
                results[name] = _sma(source, period)
            elif ind_type == "ema":
                results[name] = _ema(source, period)
            elif ind_type == "wma":
                results[name] = _wma(source, period)
            elif ind_type == "rsi":
                results[name] = _rsi(source, period)
            elif ind_type == "atr":
                results[name] = _atr(highs, lows, closes, period)
            elif ind_type == "adx":
                adx, plus_di, minus_di = _adx(highs, lows, closes, period)
                results[name] = adx
                results[f"+di_{period}"] = plus_di
                results[f"-di_{period}"] = minus_di
            elif ind_type == "macd":
                fast = int(cfg.get("fast_period", 12))
                slow = int(cfg.get("slow_period", 26))
                signal = int(cfg.get("signal_period", 9))
                macd_line, signal_line, histogram = _macd(source, fast, slow, signal)
                results[f"macd_{fast}_{slow}"] = macd_line
                results[f"macd_signal_{signal}"] = signal_line
                results[f"macd_hist"] = histogram
            elif ind_type == "bollinger" or ind_type == "bbands":
                std_dev = float(cfg.get("std_dev", 2.0))
                upper, middle, lower = _bollinger(source, period, std_dev)
                results[f"bb_upper_{period}"] = upper
                results[f"bb_middle_{period}"] = middle
                results[f"bb_lower_{period}"] = lower
            elif ind_type == "stochastic":
                k_period = int(cfg.get("k_period", period))
                d_period = int(cfg.get("d_period", 3))
                k, d = _stochastic(highs, lows, closes, k_period, d_period)
                results[f"stoch_k_{k_period}"] = k
                results[f"stoch_d_{d_period}"] = d
            elif ind_type == "vwap":
                results[name] = _vwap(highs, lows, closes, volumes)
            elif ind_type == "supertrend":
                multiplier = float(cfg.get("multiplier", 3.0))
                st, direction = _supertrend(highs, lows, closes, period, multiplier)
                results[f"supertrend_{period}"] = st
                results[f"supertrend_dir_{period}"] = direction
            elif ind_type == "pivot":
                results[f"pivot"] = (highs + lows + closes) / 3
                results[f"pivot_r1"] = 2 * results["pivot"] - lows
                results[f"pivot_s1"] = 2 * results["pivot"] - highs
                results[f"pivot_r2"] = results["pivot"] + (highs - lows)
                results[f"pivot_s2"] = results["pivot"] - (highs - lows)
            elif ind_type == "adr":
                adr_period = int(cfg.get("adr_period", period))
                results[name] = _adr(highs, lows, bars, adr_period)
            elif ind_type == "volume_sma":
                results[name] = _sma(volumes, period)
            elif ind_type == "obv":
                results[name] = _obv(closes, volumes)
            elif ind_type == "cci":
                results[name] = _cci(highs, lows, closes, period)
            elif ind_type == "williams_r":
                results[name] = _williams_r(highs, lows, closes, period)
            elif ind_type == "mfi":
                results[name] = _mfi(highs, lows, closes, volumes, period)
            elif ind_type == "ichimoku":
                tenkan = int(cfg.get("tenkan", 9))
                kijun = int(cfg.get("kijun", 26))
                senkou_b = int(cfg.get("senkou_b", 52))
                t, k_, sa, sb, chikou = _ichimoku(highs, lows, closes, tenkan, kijun, senkou_b)
                results["ichimoku_tenkan"] = t
                results["ichimoku_kijun"] = k_
                results["ichimoku_senkou_a"] = sa
                results["ichimoku_senkou_b"] = sb
                results["ichimoku_chikou"] = chikou
            else:
                # Unknown indicator — skip
                pass
        except Exception:
            # If indicator computation fails, fill with NaN
            results[name] = np.full(n, np.nan)

    return results


# ── Moving Averages ────────────────────────────────────────────────

def _sma(data: np.ndarray, period: int) -> np.ndarray:
    n = len(data)
    result = np.full(n, np.nan)
    if period > n:
        return result
    cumsum = np.cumsum(data)
    result[period - 1:] = (cumsum[period - 1:] - np.concatenate([[0], cumsum[:-period]])) / period
    return result


def _ema(data: np.ndarray, period: int) -> np.ndarray:
    n = len(data)
    result = np.full(n, np.nan)
    if period > n:
        return result
    alpha = 2.0 / (period + 1)
    result[period - 1] = np.mean(data[:period])
    for i in range(period, n):
        result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
    return result


def _wma(data: np.ndarray, period: int) -> np.ndarray:
    n = len(data)
    result = np.full(n, np.nan)
    if period > n:
        return result
    weights = np.arange(1, period + 1, dtype=np.float64)
    weight_sum = weights.sum()
    for i in range(period - 1, n):
        result[i] = np.dot(data[i - period + 1:i + 1], weights) / weight_sum
    return result


# ── Oscillators ────────────────────────────────────────────────────

def _rsi(data: np.ndarray, period: int) -> np.ndarray:
    n = len(data)
    result = np.full(n, np.nan)
    if period + 1 > n:
        return result

    deltas = np.diff(data)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - 100.0 / (1.0 + rs)

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100.0 - 100.0 / (1.0 + rs)

    return result


def _stochastic(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
    k_period: int, d_period: int,
) -> tuple[np.ndarray, np.ndarray]:
    n = len(closes)
    k = np.full(n, np.nan)
    for i in range(k_period - 1, n):
        hh = np.max(highs[i - k_period + 1:i + 1])
        ll = np.min(lows[i - k_period + 1:i + 1])
        if hh - ll > 0:
            k[i] = (closes[i] - ll) / (hh - ll) * 100
        else:
            k[i] = 50.0
    d = _sma(k, d_period)
    return k, d


def _cci(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> np.ndarray:
    tp = (highs + lows + closes) / 3
    sma = _sma(tp, period)
    n = len(tp)
    result = np.full(n, np.nan)
    for i in range(period - 1, n):
        mean_dev = np.mean(np.abs(tp[i - period + 1:i + 1] - sma[i]))
        if mean_dev > 0:
            result[i] = (tp[i] - sma[i]) / (0.015 * mean_dev)
    return result


def _williams_r(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> np.ndarray:
    n = len(closes)
    result = np.full(n, np.nan)
    for i in range(period - 1, n):
        hh = np.max(highs[i - period + 1:i + 1])
        ll = np.min(lows[i - period + 1:i + 1])
        if hh - ll > 0:
            result[i] = -100 * (hh - closes[i]) / (hh - ll)
    return result


def _mfi(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
         volumes: np.ndarray, period: int) -> np.ndarray:
    n = len(closes)
    result = np.full(n, np.nan)
    tp = (highs + lows + closes) / 3
    mf = tp * volumes
    for i in range(period, n):
        pos_mf = 0.0
        neg_mf = 0.0
        for j in range(i - period + 1, i + 1):
            if tp[j] > tp[j - 1]:
                pos_mf += mf[j]
            elif tp[j] < tp[j - 1]:
                neg_mf += mf[j]
        if neg_mf > 0:
            ratio = pos_mf / neg_mf
            result[i] = 100.0 - 100.0 / (1.0 + ratio)
        else:
            result[i] = 100.0
    return result


# ── Volatility ─────────────────────────────────────────────────────

def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> np.ndarray:
    n = len(closes)
    result = np.full(n, np.nan)
    if n < 2:
        return result

    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1])
        )
    )
    tr = np.concatenate([[highs[0] - lows[0]], tr])

    if period > n:
        return result

    result[period - 1] = np.mean(tr[:period])
    alpha = 1.0 / period
    for i in range(period, n):
        result[i] = result[i - 1] + alpha * (tr[i] - result[i - 1])

    return result


def _adr(highs: np.ndarray, lows: np.ndarray, bars: list[dict], period: int) -> np.ndarray:
    """Average Daily Range — rolling average of daily high-low ranges."""
    from datetime import datetime, timezone
    n = len(highs)
    result = np.full(n, np.nan)

    daily_ranges: list[float] = []
    day_high = highs[0]
    day_low = lows[0]
    prev_day = -1

    for i in range(n):
        ts = int(bars[i].get("time", bars[i].get("timestamp", 0)))
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        day_ord = dt.toordinal()

        if prev_day == -1:
            prev_day = day_ord

        if day_ord != prev_day:
            daily_ranges.append(day_high - day_low)
            day_high = highs[i]
            day_low = lows[i]
            prev_day = day_ord
        else:
            day_high = max(day_high, highs[i])
            day_low = min(day_low, lows[i])

        if daily_ranges:
            last_n = daily_ranges[-period:] if len(daily_ranges) >= period else daily_ranges
            result[i] = sum(last_n) / len(last_n)

    return result


def _bollinger(data: np.ndarray, period: int, std_dev: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    middle = _sma(data, period)
    n = len(data)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    for i in range(period - 1, n):
        std = np.std(data[i - period + 1:i + 1], ddof=0)
        upper[i] = middle[i] + std_dev * std
        lower[i] = middle[i] - std_dev * std
    return upper, middle, lower


def _supertrend(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
    period: int, multiplier: float,
) -> tuple[np.ndarray, np.ndarray]:
    atr = _atr(highs, lows, closes, period)
    n = len(closes)
    st = np.full(n, np.nan)
    direction = np.zeros(n)  # 1 = up (bullish), -1 = down (bearish)

    hl2 = (highs + lows) / 2
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr

    for i in range(period, n):
        if np.isnan(atr[i]):
            continue

        if i == period:
            st[i] = upper[i] if closes[i] <= upper[i] else lower[i]
            direction[i] = -1 if closes[i] <= upper[i] else 1
            continue

        if direction[i - 1] == 1:  # Previous was bullish
            if closes[i] > lower[i]:
                st[i] = max(lower[i], st[i - 1]) if not np.isnan(st[i - 1]) else lower[i]
                direction[i] = 1
            else:
                st[i] = upper[i]
                direction[i] = -1
        else:  # Previous was bearish
            if closes[i] < upper[i]:
                st[i] = min(upper[i], st[i - 1]) if not np.isnan(st[i - 1]) else upper[i]
                direction[i] = -1
            else:
                st[i] = lower[i]
                direction[i] = 1

    return st, direction


# ── Trend ──────────────────────────────────────────────────────────

def _adx(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(closes)
    adx = np.full(n, np.nan)
    plus_di = np.full(n, np.nan)
    minus_di = np.full(n, np.nan)

    if n < period + 1:
        return adx, plus_di, minus_di

    # True Range
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1]))
    )

    # +DM / -DM
    up_move = highs[1:] - highs[:-1]
    down_move = lows[:-1] - lows[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # Smooth with Wilder's method
    atr_s = np.full(n - 1, np.nan)
    pdm_s = np.full(n - 1, np.nan)
    mdm_s = np.full(n - 1, np.nan)

    atr_s[period - 1] = np.sum(tr[:period])
    pdm_s[period - 1] = np.sum(plus_dm[:period])
    mdm_s[period - 1] = np.sum(minus_dm[:period])

    for i in range(period, len(tr)):
        atr_s[i] = atr_s[i - 1] - atr_s[i - 1] / period + tr[i]
        pdm_s[i] = pdm_s[i - 1] - pdm_s[i - 1] / period + plus_dm[i]
        mdm_s[i] = mdm_s[i - 1] - mdm_s[i - 1] / period + minus_dm[i]

    # +DI / -DI
    for i in range(period - 1, len(tr)):
        if atr_s[i] > 0:
            plus_di[i + 1] = 100 * pdm_s[i] / atr_s[i]
            minus_di[i + 1] = 100 * mdm_s[i] / atr_s[i]

    # DX and ADX
    dx = np.full(n, np.nan)
    for i in range(1, n):
        if not np.isnan(plus_di[i]) and not np.isnan(minus_di[i]):
            di_sum = plus_di[i] + minus_di[i]
            if di_sum > 0:
                dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / di_sum

    # Smooth ADX
    first_adx = period * 2
    if first_adx < n:
        valid_dx = dx[period + 1:first_adx + 1]
        valid_dx = valid_dx[~np.isnan(valid_dx)]
        if len(valid_dx) > 0:
            adx[first_adx] = np.mean(valid_dx)
            for i in range(first_adx + 1, n):
                if not np.isnan(dx[i]) and not np.isnan(adx[i - 1]):
                    adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    return adx, plus_di, minus_di


def _macd(
    data: np.ndarray, fast: int, slow: int, signal: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    fast_ema = _ema(data, fast)
    slow_ema = _ema(data, slow)
    macd_line = fast_ema - slow_ema
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ── Volume ─────────────────────────────────────────────────────────

def _vwap(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
          volumes: np.ndarray) -> np.ndarray:
    tp = (highs + lows + closes) / 3
    cum_vol = np.cumsum(volumes)
    cum_tp_vol = np.cumsum(tp * volumes)
    result = np.where(cum_vol > 0, cum_tp_vol / cum_vol, np.nan)
    return result


def _obv(closes: np.ndarray, volumes: np.ndarray) -> np.ndarray:
    n = len(closes)
    result = np.zeros(n)
    for i in range(1, n):
        if closes[i] > closes[i - 1]:
            result[i] = result[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]:
            result[i] = result[i - 1] - volumes[i]
        else:
            result[i] = result[i - 1]
    return result


# ── Ichimoku ───────────────────────────────────────────────────────

def _ichimoku(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
    tenkan: int, kijun: int, senkou_b: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(closes)
    tenkan_sen = np.full(n, np.nan)
    kijun_sen = np.full(n, np.nan)
    senkou_a = np.full(n, np.nan)
    senkou_b_line = np.full(n, np.nan)
    chikou = np.full(n, np.nan)

    for i in range(tenkan - 1, n):
        tenkan_sen[i] = (np.max(highs[i - tenkan + 1:i + 1]) + np.min(lows[i - tenkan + 1:i + 1])) / 2

    for i in range(kijun - 1, n):
        kijun_sen[i] = (np.max(highs[i - kijun + 1:i + 1]) + np.min(lows[i - kijun + 1:i + 1])) / 2

    for i in range(kijun - 1, n):
        if not np.isnan(tenkan_sen[i]) and not np.isnan(kijun_sen[i]):
            future_i = i + kijun
            if future_i < n:
                senkou_a[future_i] = (tenkan_sen[i] + kijun_sen[i]) / 2

    for i in range(senkou_b - 1, n):
        future_i = i + kijun
        if future_i < n:
            senkou_b_line[future_i] = (np.max(highs[i - senkou_b + 1:i + 1]) + np.min(lows[i - senkou_b + 1:i + 1])) / 2

    for i in range(kijun, n):
        chikou[i - kijun] = closes[i]

    return tenkan_sen, kijun_sen, senkou_a, senkou_b_line, chikou
