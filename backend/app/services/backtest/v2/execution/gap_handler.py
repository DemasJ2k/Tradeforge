"""
Gap detection and fill rules for the V2 backtesting engine.

Gaps occur when:
    - Overnight session break (e.g., stocks close at 16:00, open at 09:30)
    - Weekend gap (Friday close → Monday open)
    - News/halt gap (trading halted then resumed at different price)

Gap Fill Rules:
    - STOP orders: if bar opens beyond the stop price, fill at open (not stop).
      This is "gap slippage" — the worst-case realistic scenario.
    - LIMIT orders: if bar opens through the limit price, fill at limit
      (price improvement — the order was "better than expected").
    - STOP_LIMIT: if bar gaps past both stop and limit, no fill.
      If gaps past stop but not limit, fill at limit.

Detection:
    A gap is detected when the distance between prev_bar.close and
    current_bar.open exceeds a configurable threshold (absolute or
    percentage of recent ATR).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.services.backtest.v2.engine.events import BarEvent


# ────────────────────────────────────────────────────────────────────
# Gap Types
# ────────────────────────────────────────────────────────────────────

class GapType(str, Enum):
    """Classification of price gaps."""
    NONE = "none"               # No gap detected
    GAP_UP = "gap_up"           # Open > prev close
    GAP_DOWN = "gap_down"       # Open < prev close


# ────────────────────────────────────────────────────────────────────
# Gap Information
# ────────────────────────────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class GapInfo:
    """Details about a price gap between consecutive bars."""
    gap_type: GapType
    gap_size: float              # Absolute distance: |open - prev_close|
    gap_pct: float               # Relative gap: gap_size / prev_close
    prev_close: float            # Previous bar's close
    current_open: float          # Current bar's open
    bar_index: int               # Current bar's index
    is_session_gap: bool = False  # True if detected as session boundary gap

    @property
    def is_gap(self) -> bool:
        """Whether a meaningful gap was detected."""
        return self.gap_type != GapType.NONE

    @property
    def is_gap_up(self) -> bool:
        return self.gap_type == GapType.GAP_UP

    @property
    def is_gap_down(self) -> bool:
        return self.gap_type == GapType.GAP_DOWN


# ────────────────────────────────────────────────────────────────────
# Gap Detector
# ────────────────────────────────────────────────────────────────────

class GapDetector:
    """Detect and classify price gaps between consecutive bars.

    Two detection modes:
        1. **Percentage threshold** — gap_pct > min_gap_pct
        2. **ATR threshold** — gap_size > atr_multiplier × ATR

    Either condition triggers a gap if exceeded.

    Parameters
    ----------
    min_gap_pct : float
        Minimum gap as a percentage of prev close to be considered a gap.
        Default 0.001 (0.1%) — catches most meaningful gaps.
    atr_multiplier : float
        Gap must exceed this multiple of ATR to qualify.
        Default 0.5 — half ATR is a significant move.
    session_gap_hours : float
        If the time gap between bars exceeds this many hours, mark as
        session gap (overnight/weekend). Default 4 hours.
    """

    def __init__(
        self,
        min_gap_pct: float = 0.001,
        atr_multiplier: float = 0.5,
        session_gap_hours: float = 4.0,
    ):
        self.min_gap_pct = abs(min_gap_pct)
        self.atr_multiplier = abs(atr_multiplier)
        self.session_gap_ns = int(session_gap_hours * 3600 * 1e9)

    def detect(
        self,
        prev_bar: BarEvent,
        current_bar: BarEvent,
        atr: float = 0.0,
    ) -> GapInfo:
        """Detect a gap between two consecutive bars.

        Parameters
        ----------
        prev_bar : BarEvent
            The previous bar.
        current_bar : BarEvent
            The current bar being processed.
        atr : float
            Current ATR value (0 = disable ATR-based threshold).

        Returns
        -------
        GapInfo
            Gap classification and details.
        """
        prev_close = prev_bar.close
        current_open = current_bar.open

        if prev_close <= 0:
            return GapInfo(
                gap_type=GapType.NONE,
                gap_size=0.0,
                gap_pct=0.0,
                prev_close=prev_close,
                current_open=current_open,
                bar_index=current_bar.bar_index,
            )

        gap_size = abs(current_open - prev_close)
        gap_pct = gap_size / prev_close

        # Session gap detection (based on timestamp distance)
        time_gap_ns = current_bar.timestamp_ns - prev_bar.timestamp_ns
        is_session = time_gap_ns > self.session_gap_ns if self.session_gap_ns > 0 else False

        # Determine if this qualifies as a gap
        is_gap = False

        # Percentage threshold
        if gap_pct >= self.min_gap_pct:
            is_gap = True

        # ATR threshold
        if atr > 0 and gap_size >= self.atr_multiplier * atr:
            is_gap = True

        if not is_gap:
            return GapInfo(
                gap_type=GapType.NONE,
                gap_size=gap_size,
                gap_pct=gap_pct,
                prev_close=prev_close,
                current_open=current_open,
                bar_index=current_bar.bar_index,
                is_session_gap=is_session,
            )

        # Classify direction
        if current_open > prev_close:
            gap_type = GapType.GAP_UP
        else:
            gap_type = GapType.GAP_DOWN

        return GapInfo(
            gap_type=gap_type,
            gap_size=gap_size,
            gap_pct=gap_pct,
            prev_close=prev_close,
            current_open=current_open,
            bar_index=current_bar.bar_index,
            is_session_gap=is_session,
        )


# ────────────────────────────────────────────────────────────────────
# Gap-aware fill price helpers
# ────────────────────────────────────────────────────────────────────

def gap_adjusted_stop_price(
    order_side: str,
    stop_price: float,
    bar_open: float,
    gap: GapInfo | None,
) -> tuple[float, bool]:
    """Compute the raw fill price for a stop order considering gaps.

    If the bar opens beyond the stop price (gap-through), the fill
    price should be the bar open — not the stop price.

    Parameters
    ----------
    order_side : str
        "BUY" or "SELL".
    stop_price : float
        The order's stop trigger price.
    bar_open : float
        The current bar's open price.
    gap : GapInfo or None
        Gap information (can be None if no gap).

    Returns
    -------
    tuple[float, bool]
        (adjusted_price, is_gap_fill)
    """
    if gap is None or not gap.is_gap:
        return stop_price, False

    if order_side == "BUY" or order_side == "buy":
        if bar_open > stop_price:
            # Gap up through buy stop → fill at open
            return bar_open, True
    else:
        if bar_open < stop_price:
            # Gap down through sell stop → fill at open
            return bar_open, True

    return stop_price, False


def gap_adjusted_limit_price(
    order_side: str,
    limit_price: float,
    bar_open: float,
    gap: GapInfo | None,
) -> tuple[float, bool]:
    """Compute the raw fill price for a limit order considering gaps.

    If the bar opens through the limit price, the order gets price
    improvement — fill at the limit price (not open).

    Parameters
    ----------
    order_side : str
        "BUY" or "SELL".
    limit_price : float
        The order's limit price.
    bar_open : float
        The current bar's open price.
    gap : GapInfo or None
        Gap information.

    Returns
    -------
    tuple[float, bool]
        (adjusted_price, is_gap_fill)
        For limits, gap-through gives *better* fill at limit price.
    """
    if gap is None or not gap.is_gap:
        return limit_price, False

    if order_side == "BUY" or order_side == "buy":
        if bar_open <= limit_price:
            # Gap gives better price → fill at open (price improvement)
            return min(bar_open, limit_price), True
    else:
        if bar_open >= limit_price:
            # Gap gives better price → fill at open (price improvement)
            return max(bar_open, limit_price), True

    return limit_price, False
