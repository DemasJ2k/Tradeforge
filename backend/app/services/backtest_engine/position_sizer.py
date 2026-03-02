"""
Position Sizer — Compute trade size based on risk management rules.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from .instrument import Instrument


class SizingMethod(str, Enum):
    FIXED_LOT = "fixed_lot"
    RISK_PERCENT = "risk_percent"
    RISK_AMOUNT = "risk_amount"
    KELLY = "kelly"
    ATR_BASED = "atr_based"


def compute_size(
    method: SizingMethod,
    balance: float,
    entry_price: float,
    stop_loss_price: float,
    instrument: Instrument,
    # Method-specific params
    fixed_lot: float = 0.01,
    risk_pct: float = 1.0,
    risk_amount: float = 100.0,
    win_rate: float = 0.5,
    avg_win_loss_ratio: float = 1.5,
    atr_value: float = 0.0,
    atr_risk_multiple: float = 1.0,
) -> float:
    """Calculate position size based on the chosen method."""

    if method == SizingMethod.FIXED_LOT:
        return instrument.round_lot(fixed_lot)

    elif method == SizingMethod.RISK_PERCENT:
        return _risk_based_size(
            risk_dollars=balance * risk_pct / 100.0,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            instrument=instrument,
        )

    elif method == SizingMethod.RISK_AMOUNT:
        return _risk_based_size(
            risk_dollars=risk_amount,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            instrument=instrument,
        )

    elif method == SizingMethod.KELLY:
        # Kelly fraction: f* = (p * b - q) / b
        # where p = win_rate, q = 1 - p, b = avg_win / avg_loss
        q = 1.0 - win_rate
        b = avg_win_loss_ratio
        kelly_f = (win_rate * b - q) / b if b > 0 else 0
        kelly_f = max(0, min(kelly_f, 0.25))  # Cap at 25%

        return _risk_based_size(
            risk_dollars=balance * kelly_f,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            instrument=instrument,
        )

    elif method == SizingMethod.ATR_BASED:
        if atr_value <= 0:
            return instrument.round_lot(fixed_lot)
        risk_dollars = balance * risk_pct / 100.0
        risk_per_lot = atr_value * atr_risk_multiple * instrument.point_value
        if risk_per_lot <= 0:
            return instrument.round_lot(fixed_lot)
        size = risk_dollars / risk_per_lot
        return instrument.round_lot(size)

    return instrument.round_lot(fixed_lot)


def _risk_based_size(
    risk_dollars: float,
    entry_price: float,
    stop_loss_price: float,
    instrument: Instrument,
) -> float:
    """Compute lot size from risk dollars and SL distance."""
    sl_distance = abs(entry_price - stop_loss_price)
    if sl_distance <= 0:
        # No SL = use 1% of balance as risk distance proxy
        sl_distance = entry_price * 0.01

    risk_per_lot = sl_distance * instrument.point_value
    if risk_per_lot <= 0:
        return instrument.min_lot

    size = risk_dollars / risk_per_lot
    return instrument.round_lot(size)
