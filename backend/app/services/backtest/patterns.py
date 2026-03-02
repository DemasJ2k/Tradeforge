"""Phase 3C — Candlestick Pattern Detection Engine.

Each pattern function returns a signal series:
    +1.0 = bullish signal
    -1.0 = bearish signal
     0.0 = no signal

All functions accept OHLC lists of equal length and return ``list[float]``
of the same length.
"""

from __future__ import annotations

import math
from typing import Callable

NaN = float("nan")

__all__ = [
    "detect_pattern",
    "PATTERN_CATALOGUE",
    # Individual detection functions
    "engulfing",
    "pin_bar",
    "doji",
    "hammer",
    "inverted_hammer",
    "shooting_star",
    "morning_star",
    "evening_star",
    "inside_bar",
    "outside_bar",
    "three_white_soldiers",
    "three_black_crows",
    "harami",
    "tweezer_top",
    "tweezer_bottom",
    "spinning_top",
]


# ── Helpers ────────────────────────────────────────────────────────

def _body(o: float, c: float) -> float:
    return abs(c - o)

def _upper_wick(o: float, h: float, c: float) -> float:
    return h - max(o, c)

def _lower_wick(o: float, l: float, c: float) -> float:
    return min(o, c) - l

def _range_(h: float, l: float) -> float:
    return h - l if h > l else 1e-10

def _is_bullish(o: float, c: float) -> bool:
    return c > o

def _is_bearish(o: float, c: float) -> bool:
    return o > c


# ── Pattern Functions ──────────────────────────────────────────────

def engulfing(
    opens: list[float], highs: list[float],
    lows: list[float], closes: list[float],
) -> list[float]:
    """Bullish / Bearish Engulfing."""
    n = len(opens)
    out = [0.0] * n
    for i in range(1, n):
        body_prev = _body(opens[i-1], closes[i-1])
        body_curr = _body(opens[i], closes[i])
        if body_curr <= body_prev:
            continue
        # Bullish engulfing: prev bearish, curr bullish, curr body engulfs prev body
        if _is_bearish(opens[i-1], closes[i-1]) and _is_bullish(opens[i], closes[i]):
            if opens[i] <= closes[i-1] and closes[i] >= opens[i-1]:
                out[i] = 1.0
        # Bearish engulfing: prev bullish, curr bearish
        elif _is_bullish(opens[i-1], closes[i-1]) and _is_bearish(opens[i], closes[i]):
            if opens[i] >= closes[i-1] and closes[i] <= opens[i-1]:
                out[i] = -1.0
    return out


def pin_bar(
    opens: list[float], highs: list[float],
    lows: list[float], closes: list[float],
    body_ratio: float = 0.33, wick_ratio: float = 2.0,
) -> list[float]:
    """Pin Bar (hammer-like with long tail, small body)."""
    n = len(opens)
    out = [0.0] * n
    for i in range(n):
        body = _body(opens[i], closes[i])
        rng = _range_(highs[i], lows[i])
        uw = _upper_wick(opens[i], highs[i], closes[i])
        lw = _lower_wick(opens[i], lows[i], closes[i])
        if body / rng > body_ratio:
            continue
        # Bullish pin: long lower wick
        if lw > wick_ratio * body and lw > uw:
            out[i] = 1.0
        # Bearish pin: long upper wick
        elif uw > wick_ratio * body and uw > lw:
            out[i] = -1.0
    return out


def doji(
    opens: list[float], highs: list[float],
    lows: list[float], closes: list[float],
    threshold: float = 0.05,
) -> list[float]:
    """Doji — body < threshold × range."""
    n = len(opens)
    out = [0.0] * n
    for i in range(n):
        rng = _range_(highs[i], lows[i])
        body = _body(opens[i], closes[i])
        if body / rng <= threshold:
            out[i] = 1.0  # neutral signal — direction depends on context
    return out


def hammer(
    opens: list[float], highs: list[float],
    lows: list[float], closes: list[float],
) -> list[float]:
    """Hammer (bullish) — small body at top, long lower shadow ≥ 2× body."""
    n = len(opens)
    out = [0.0] * n
    for i in range(n):
        body = _body(opens[i], closes[i])
        lw = _lower_wick(opens[i], lows[i], closes[i])
        uw = _upper_wick(opens[i], highs[i], closes[i])
        rng = _range_(highs[i], lows[i])
        if rng == 0:
            continue
        if body / rng < 0.4 and lw >= 2 * body and uw < body:
            out[i] = 1.0
    return out


def inverted_hammer(
    opens: list[float], highs: list[float],
    lows: list[float], closes: list[float],
) -> list[float]:
    """Inverted Hammer (potential bullish reversal) — small body at bottom, long upper shadow."""
    n = len(opens)
    out = [0.0] * n
    for i in range(n):
        body = _body(opens[i], closes[i])
        lw = _lower_wick(opens[i], lows[i], closes[i])
        uw = _upper_wick(opens[i], highs[i], closes[i])
        rng = _range_(highs[i], lows[i])
        if rng == 0:
            continue
        if body / rng < 0.4 and uw >= 2 * body and lw < body:
            out[i] = 1.0
    return out


def shooting_star(
    opens: list[float], highs: list[float],
    lows: list[float], closes: list[float],
) -> list[float]:
    """Shooting Star (bearish) — small body at bottom, long upper shadow."""
    n = len(opens)
    out = [0.0] * n
    for i in range(1, n):
        body = _body(opens[i], closes[i])
        uw = _upper_wick(opens[i], highs[i], closes[i])
        lw = _lower_wick(opens[i], lows[i], closes[i])
        rng = _range_(highs[i], lows[i])
        if rng == 0:
            continue
        # Bearish + uptrend context (close[i-1] < close[i])
        if body / rng < 0.4 and uw >= 2 * body and lw < body:
            if closes[i - 1] < highs[i]:  # preceded by upward move
                out[i] = -1.0
    return out


def morning_star(
    opens: list[float], highs: list[float],
    lows: list[float], closes: list[float],
) -> list[float]:
    """Morning Star (bullish) — 3-bar pattern: bearish → small body → bullish."""
    n = len(opens)
    out = [0.0] * n
    for i in range(2, n):
        body0 = _body(opens[i-2], closes[i-2])
        body1 = _body(opens[i-1], closes[i-1])
        body2 = _body(opens[i], closes[i])
        rng0 = _range_(highs[i-2], lows[i-2])
        if rng0 == 0:
            continue
        if (_is_bearish(opens[i-2], closes[i-2]) and
                body1 < body0 * 0.5 and
                _is_bullish(opens[i], closes[i]) and
                closes[i] > (opens[i-2] + closes[i-2]) / 2):
            out[i] = 1.0
    return out


def evening_star(
    opens: list[float], highs: list[float],
    lows: list[float], closes: list[float],
) -> list[float]:
    """Evening Star (bearish) — 3-bar pattern: bullish → small body → bearish."""
    n = len(opens)
    out = [0.0] * n
    for i in range(2, n):
        body0 = _body(opens[i-2], closes[i-2])
        body1 = _body(opens[i-1], closes[i-1])
        body2 = _body(opens[i], closes[i])
        if body0 == 0:
            continue
        if (_is_bullish(opens[i-2], closes[i-2]) and
                body1 < body0 * 0.5 and
                _is_bearish(opens[i], closes[i]) and
                closes[i] < (opens[i-2] + closes[i-2]) / 2):
            out[i] = -1.0
    return out


def inside_bar(
    opens: list[float], highs: list[float],
    lows: list[float], closes: list[float],
) -> list[float]:
    """Inside Bar — current bar's range is inside previous bar's range."""
    n = len(opens)
    out = [0.0] * n
    for i in range(1, n):
        if highs[i] <= highs[i-1] and lows[i] >= lows[i-1]:
            out[i] = 1.0  # neutral — breakout direction unknown
    return out


def outside_bar(
    opens: list[float], highs: list[float],
    lows: list[float], closes: list[float],
) -> list[float]:
    """Outside Bar — current bar engulfs previous bar's range."""
    n = len(opens)
    out = [0.0] * n
    for i in range(1, n):
        if highs[i] > highs[i-1] and lows[i] < lows[i-1]:
            if _is_bullish(opens[i], closes[i]):
                out[i] = 1.0
            else:
                out[i] = -1.0
    return out


def three_white_soldiers(
    opens: list[float], highs: list[float],
    lows: list[float], closes: list[float],
) -> list[float]:
    """Three White Soldiers (bullish) — 3 consecutive large bullish candles."""
    n = len(opens)
    out = [0.0] * n
    for i in range(2, n):
        if all(
            _is_bullish(opens[i-j], closes[i-j]) and
            closes[i-j] > closes[i-j-1] if i-j-1 >= 0 else True and
            _body(opens[i-j], closes[i-j]) > 0.5 * _range_(highs[i-j], lows[i-j])
            for j in range(3)
        ):
            out[i] = 1.0
    return out


def three_black_crows(
    opens: list[float], highs: list[float],
    lows: list[float], closes: list[float],
) -> list[float]:
    """Three Black Crows (bearish) — 3 consecutive large bearish candles."""
    n = len(opens)
    out = [0.0] * n
    for i in range(2, n):
        if all(
            _is_bearish(opens[i-j], closes[i-j]) and
            closes[i-j] < closes[i-j-1] if i-j-1 >= 0 else True and
            _body(opens[i-j], closes[i-j]) > 0.5 * _range_(highs[i-j], lows[i-j])
            for j in range(3)
        ):
            out[i] = -1.0
    return out


def harami(
    opens: list[float], highs: list[float],
    lows: list[float], closes: list[float],
) -> list[float]:
    """Harami — second bar's body is within first bar's body."""
    n = len(opens)
    out = [0.0] * n
    for i in range(1, n):
        o0, c0 = opens[i-1], closes[i-1]
        o1, c1 = opens[i], closes[i]
        body_top_prev = max(o0, c0)
        body_bot_prev = min(o0, c0)
        body_top_curr = max(o1, c1)
        body_bot_curr = min(o1, c1)
        if body_top_curr <= body_top_prev and body_bot_curr >= body_bot_prev:
            if _body(o0, c0) > _body(o1, c1) * 1.5:
                if _is_bearish(o0, c0):
                    out[i] = 1.0   # bullish harami
                else:
                    out[i] = -1.0  # bearish harami
    return out


def tweezer_top(
    opens: list[float], highs: list[float],
    lows: list[float], closes: list[float],
    tolerance: float = 0.001,
) -> list[float]:
    """Tweezer Top (bearish) — two candles with nearly identical highs."""
    n = len(opens)
    out = [0.0] * n
    for i in range(1, n):
        if abs(highs[i] - highs[i-1]) <= tolerance * highs[i-1]:
            if _is_bullish(opens[i-1], closes[i-1]) and _is_bearish(opens[i], closes[i]):
                out[i] = -1.0
    return out


def tweezer_bottom(
    opens: list[float], highs: list[float],
    lows: list[float], closes: list[float],
    tolerance: float = 0.001,
) -> list[float]:
    """Tweezer Bottom (bullish) — two candles with nearly identical lows."""
    n = len(opens)
    out = [0.0] * n
    for i in range(1, n):
        if lows[i-1] > 0 and abs(lows[i] - lows[i-1]) <= tolerance * lows[i-1]:
            if _is_bearish(opens[i-1], closes[i-1]) and _is_bullish(opens[i], closes[i]):
                out[i] = 1.0
    return out


def spinning_top(
    opens: list[float], highs: list[float],
    lows: list[float], closes: list[float],
    body_threshold: float = 0.3,
) -> list[float]:
    """Spinning Top — small body, roughly equal upper and lower wicks."""
    n = len(opens)
    out = [0.0] * n
    for i in range(n):
        body = _body(opens[i], closes[i])
        rng = _range_(highs[i], lows[i])
        uw = _upper_wick(opens[i], highs[i], closes[i])
        lw = _lower_wick(opens[i], lows[i], closes[i])
        if rng == 0:
            continue
        if (body / rng < body_threshold and
                uw > body * 0.5 and lw > body * 0.5):
            out[i] = 1.0  # indecision signal
    return out


# ── Pattern catalogue & dispatcher ─────────────────────────────────

PATTERN_CATALOGUE: dict[str, Callable] = {
    "engulfing": engulfing,
    "pin_bar": pin_bar,
    "doji": doji,
    "hammer": hammer,
    "inverted_hammer": inverted_hammer,
    "shooting_star": shooting_star,
    "morning_star": morning_star,
    "evening_star": evening_star,
    "inside_bar": inside_bar,
    "outside_bar": outside_bar,
    "three_white_soldiers": three_white_soldiers,
    "three_black_crows": three_black_crows,
    "harami": harami,
    "tweezer_top": tweezer_top,
    "tweezer_bottom": tweezer_bottom,
    "spinning_top": spinning_top,
}


def detect_pattern(
    pattern_name: str,
    opens: list[float], highs: list[float],
    lows: list[float], closes: list[float],
    **kwargs,
) -> list[float]:
    """Dispatch to the appropriate pattern detection function.

    Returns a signal series of the same length: +1 (bullish), -1 (bearish), 0 (none).
    Raises ``KeyError`` for unknown pattern names.
    """
    fn = PATTERN_CATALOGUE.get(pattern_name.lower())
    if fn is None:
        raise KeyError(
            f"Unknown pattern '{pattern_name}'. "
            f"Available: {sorted(PATTERN_CATALOGUE.keys())}"
        )
    return fn(opens, highs, lows, closes, **kwargs)
