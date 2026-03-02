"""
Synthetic tick generation from OHLCV bars via Brownian bridge.

When real tick data is unavailable, we synthesise a realistic intra-bar
price path so that limit/stop orders can be checked against a price
trajectory (not just the final OHLCV summary).

Modes
-----
1. **OHLCV synthetic** — construct O → extreme1 → extreme2 → C path
   using a Brownian bridge with endpoints pinned to OHLC.
2. **M1 synthetic** — given M1 bars, apply the same bridge within
   each M1 bar for sub-minute resolution.
3. **Real tick** (pass-through) — no synthesis needed.

The Brownian Bridge
-------------------
A Brownian bridge B(t) between time 0 and T with B(0)=a, B(T)=b is:

    B(t) = a + (b-a)*(t/T) + σ * √(t*(T-t)/T) * Z

where Z ~ N(0,1) and σ controls volatility of the path.

For OHLCV bars, we pin the path through four anchor points:
    O (open, t=0) →  H or L  →  L or H  →  C (close, t=T)

The order of H and L is randomly chosen (or inferred from O→C direction
for slightly more realism: if O<C, likely hit L first then H).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

from app.services.backtest.v2.engine.events import BarEvent


# ────────────────────────────────────────────────────────────────────
# Synthetic Tick
# ────────────────────────────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class SyntheticTick:
    """A single synthetic tick generated from OHLCV data."""
    price: float
    timestamp_ns: int
    tick_index: int           # Position within the bar's tick sequence
    bar_index: int            # Which OHLCV bar this tick belongs to
    is_anchor: bool = False   # True for O, H, L, C anchor ticks


# ────────────────────────────────────────────────────────────────────
# Brownian Bridge — core math
# ────────────────────────────────────────────────────────────────────

def _brownian_bridge_segment(
    start_price: float,
    end_price: float,
    n_ticks: int,
    volatility: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate a Brownian bridge path between two price levels.

    Parameters
    ----------
    start_price : float
        Price at the start of the segment.
    end_price : float
        Price at the end of the segment.
    n_ticks : int
        Number of intermediate ticks to generate (excludes endpoints).
    volatility : float
        Noise amplitude — scaled by sqrt(dt * (T-t) / T).
    rng : np.random.Generator
        Random number generator for reproducibility.

    Returns
    -------
    np.ndarray
        Array of length (n_ticks + 2) including start and end.
    """
    if n_ticks <= 0:
        return np.array([start_price, end_price])

    total = n_ticks + 1  # number of intervals
    t = np.arange(0, n_ticks + 2, dtype=np.float64)  # 0, 1, ..., n_ticks+1
    T = float(total)

    # Linear interpolation component
    linear = start_price + (end_price - start_price) * (t / T)

    # Bridge noise component: σ * sqrt(t*(T-t)/T) * Z
    # For endpoints (t=0 and t=T), the factor is 0 → no noise added.
    bridge_var = t * (T - t) / T
    bridge_std = np.sqrt(np.maximum(bridge_var, 0.0))
    noise = rng.standard_normal(len(t)) * bridge_std * volatility

    # Force endpoints to be exact
    noise[0] = 0.0
    noise[-1] = 0.0

    path = linear + noise
    return path


# ────────────────────────────────────────────────────────────────────
# OHLCV → Synthetic Ticks
# ────────────────────────────────────────────────────────────────────

def synthesize_ticks_from_bar(
    bar: BarEvent,
    ticks_per_segment: int = 10,
    volatility_factor: float = 0.3,
    seed: int | None = None,
) -> list[SyntheticTick]:
    """Generate synthetic ticks from a single OHLCV bar.

    Creates a 3-segment Brownian bridge path:
        Segment 1:  O → first_extreme  (e.g. O → L or O → H)
        Segment 2:  first_extreme → second_extreme  (L → H or H → L)
        Segment 3:  second_extreme → C

    The order of H/L visit is chosen heuristically:
        - If O is closer to H than to L: path goes O → H → L → C  (bearish bar)
        - Otherwise: O → L → H → C  (bullish bar)
    This produces more realistic paths for trending bars.

    Parameters
    ----------
    bar : BarEvent
        The OHLCV bar to synthesize ticks from.
    ticks_per_segment : int
        Number of intermediate ticks per segment (total ticks ≈ 3 × this + 4).
    volatility_factor : float
        Controls noise amplitude relative to bar range.
        0 = straight lines between anchors,  1 = very noisy.
    seed : int or None
        Random seed for reproducibility.  If None, use bar_index as seed.

    Returns
    -------
    list[SyntheticTick]
        Ordered list of ticks covering the bar duration.
    """
    rng = np.random.default_rng(seed if seed is not None else bar.bar_index)

    O, H, L, C = bar.open, bar.high, bar.low, bar.close
    bar_range = H - L if H > L else 1e-8

    # Volatility for bridge noise — proportional to bar range
    vol = volatility_factor * bar_range / math.sqrt(max(ticks_per_segment, 1))

    # Decide visit order: which extreme is touched first?
    # Heuristic: if open is in top half of range, likely hit high first then low
    mid = (H + L) / 2.0
    if O >= mid:
        # Open near high → visit H first, then drop to L
        anchors = [O, H, L, C]
    else:
        # Open near low → visit L first, then rise to H
        anchors = [O, L, H, C]

    # Generate 3 bridge segments
    segments: list[np.ndarray] = []
    for i in range(3):
        seg = _brownian_bridge_segment(
            start_price=anchors[i],
            end_price=anchors[i + 1],
            n_ticks=ticks_per_segment,
            volatility=vol,
            rng=rng,
        )
        if i > 0:
            # Skip first tick of segment (it's the last tick of previous)
            seg = seg[1:]
        segments.append(seg)

    # Concatenate into full path
    full_path = np.concatenate(segments)

    # Clamp to [L, H] — bridge noise can occasionally escape
    full_path = np.clip(full_path, L, H)

    # Build timestamp distribution across the bar
    # Assume bar starts at bar.timestamp_ns and has uniform tick spacing
    n_total = len(full_path)
    # We don't know bar duration from BarEvent alone, so use 1 ns per tick
    # (the tick_engine will remap timestamps if needed)
    ts_start = bar.timestamp_ns
    ts_step = max(1, 1)  # Placeholder — real duration set by tick_engine

    ticks = []
    anchor_indices = {0, ticks_per_segment, ticks_per_segment * 2 + 1, n_total - 1}

    for idx in range(n_total):
        ticks.append(SyntheticTick(
            price=float(full_path[idx]),
            timestamp_ns=ts_start + idx * ts_step,
            tick_index=idx,
            bar_index=bar.bar_index,
            is_anchor=(idx in anchor_indices),
        ))

    return ticks


# ────────────────────────────────────────────────────────────────────
# Batch generation for a full bar series
# ────────────────────────────────────────────────────────────────────

def synthesize_ticks_from_bars(
    bars: Sequence[BarEvent],
    ticks_per_segment: int = 10,
    volatility_factor: float = 0.3,
    base_seed: int = 42,
) -> list[list[SyntheticTick]]:
    """Generate synthetic ticks for a sequence of bars.

    Parameters
    ----------
    bars : Sequence[BarEvent]
        Ordered list of OHLCV bars.
    ticks_per_segment : int
        Ticks per bridge segment per bar.
    volatility_factor : float
        Noise amplitude scaling.
    base_seed : int
        Base seed — each bar gets seed = base_seed + bar_index.

    Returns
    -------
    list[list[SyntheticTick]]
        Outer list is per-bar, inner list is ordered ticks within that bar.
    """
    result = []
    for bar in bars:
        seed = base_seed + bar.bar_index
        ticks = synthesize_ticks_from_bar(
            bar=bar,
            ticks_per_segment=ticks_per_segment,
            volatility_factor=volatility_factor,
            seed=seed,
        )
        result.append(ticks)
    return result


# ────────────────────────────────────────────────────────────────────
# Quick-path: 5-tick summary (O, H1, L1, H2/L2, C)
# ────────────────────────────────────────────────────────────────────

def five_tick_ohlc(bar: BarEvent) -> list[SyntheticTick]:
    """Generate a minimal 5-tick path: O → extreme → extreme → C.

    No Brownian noise — just straight anchors.  This is the fastest
    mode for order matching when full path generation is too expensive.
    """
    O, H, L, C = bar.open, bar.high, bar.low, bar.close
    mid = (H + L) / 2.0
    ts = bar.timestamp_ns

    if O >= mid:
        # O near high → H first, then L
        prices = [O, H, L, C]
    else:
        # O near low → L first, then H
        prices = [O, L, H, C]

    # Add midpoint between extremes for better stop-limit evaluation
    mid_price = (prices[1] + prices[2]) / 2.0
    prices_5 = [prices[0], prices[1], mid_price, prices[2], prices[3]]

    return [
        SyntheticTick(
            price=p,
            timestamp_ns=ts + i,
            tick_index=i,
            bar_index=bar.bar_index,
            is_anchor=(i != 2),
        )
        for i, p in enumerate(prices_5)
    ]
