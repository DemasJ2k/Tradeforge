"""
Instrument — Asset class configuration for fill models, margin, and sizing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AssetClass(str, Enum):
    FOREX = "forex"
    COMMODITY = "commodity"
    INDEX = "index"
    CRYPTO = "crypto"
    STOCK = "stock"


class CommissionType(str, Enum):
    PER_LOT = "per_lot"           # Fixed $ per standard lot
    PER_TRADE = "per_trade"       # Fixed $ per trade
    PERCENTAGE = "percentage"     # % of notional
    SPREAD_MARKUP = "spread"      # Built into spread


@dataclass
class Instrument:
    """Configuration for a tradable instrument."""
    symbol: str
    asset_class: AssetClass = AssetClass.FOREX
    tick_size: float = 0.00001    # Minimum price increment
    point_value: float = 1.0      # $ per point per lot
    lot_size: float = 100_000     # Units per standard lot
    margin_rate: float = 0.01     # 1% = 100:1 leverage
    commission_type: CommissionType = CommissionType.PER_LOT
    commission_value: float = 7.0 # $ per round-trip per lot
    min_lot: float = 0.01
    max_lot: float = 100.0
    lot_step: float = 0.01
    swap_long: float = 0.0       # Daily swap rate
    swap_short: float = 0.0
    trading_hours: Optional[str] = None  # e.g. "00:00-23:59" for 24h

    @property
    def pip_value(self) -> float:
        """Value of one pip (point_value * tick_size * lot_size)."""
        return self.point_value

    def round_price(self, price: float) -> float:
        """Round price to instrument's tick size."""
        if self.tick_size <= 0:
            return price
        return round(round(price / self.tick_size) * self.tick_size, 10)

    def round_lot(self, size: float) -> float:
        """Round lot size to instrument's lot step."""
        if self.lot_step <= 0:
            return size
        rounded = round(round(size / self.lot_step) * self.lot_step, 8)
        return max(self.min_lot, min(self.max_lot, rounded))

    def compute_commission(self, size: float, entry_price: float = 0.0) -> float:
        """Calculate commission for a trade (one side)."""
        if self.commission_type == CommissionType.PER_LOT:
            return self.commission_value * size
        elif self.commission_type == CommissionType.PER_TRADE:
            return self.commission_value
        elif self.commission_type == CommissionType.PERCENTAGE:
            notional = size * self.lot_size * entry_price
            return notional * self.commission_value / 100.0
        return 0.0  # SPREAD_MARKUP is built into the fill price


# ── Built-in Instrument Presets ────────────────────────────────────

FOREX_DEFAULTS = dict(
    asset_class=AssetClass.FOREX,
    tick_size=0.00001,
    lot_size=100_000,
    margin_rate=0.01,
    commission_type=CommissionType.PER_LOT,
    commission_value=7.0,
    min_lot=0.01, max_lot=100.0, lot_step=0.01,
)

GOLD_DEFAULTS = dict(
    asset_class=AssetClass.COMMODITY,
    tick_size=0.01,
    point_value=1.0,
    lot_size=100,   # 100 oz per lot
    margin_rate=0.02,
    commission_type=CommissionType.PER_LOT,
    commission_value=7.0,
    min_lot=0.01, max_lot=50.0, lot_step=0.01,
)

INDEX_DEFAULTS = dict(
    asset_class=AssetClass.INDEX,
    tick_size=0.01,
    point_value=1.0,
    lot_size=1,
    margin_rate=0.005,
    commission_type=CommissionType.PER_LOT,
    commission_value=3.0,
    min_lot=0.1, max_lot=100.0, lot_step=0.1,
)

CRYPTO_DEFAULTS = dict(
    asset_class=AssetClass.CRYPTO,
    tick_size=0.01,
    point_value=1.0,
    lot_size=1,
    margin_rate=0.05,
    commission_type=CommissionType.PERCENTAGE,
    commission_value=0.1,  # 0.1% = typical exchange fee
    min_lot=0.001, max_lot=1000.0, lot_step=0.001,
)

STOCK_DEFAULTS = dict(
    asset_class=AssetClass.STOCK,
    tick_size=0.01,
    point_value=1.0,
    lot_size=1,
    margin_rate=0.5,  # stocks typically 2:1
    commission_type=CommissionType.PER_TRADE,
    commission_value=0.0,  # commission-free era
    min_lot=1.0, max_lot=100_000.0, lot_step=1.0,
)


def get_instrument(symbol: str, point_value: float = 1.0,
                   commission: float = 7.0, margin_rate: float = 0.01) -> Instrument:
    """Auto-detect instrument config from symbol name."""
    s = symbol.upper()

    # Gold/Silver
    if s in ("XAUUSD", "GOLD", "XAGUSD", "SILVER"):
        return Instrument(symbol=s, point_value=point_value,
                          commission_value=commission, margin_rate=margin_rate,
                          **{k: v for k, v in GOLD_DEFAULTS.items()
                             if k not in ("point_value", "commission_value", "margin_rate")})

    # Oil
    if s in ("XTIUSD", "XBRUSD", "USOIL", "UKOIL", "CL", "WTI"):
        return Instrument(symbol=s, point_value=point_value,
                          commission_value=commission, margin_rate=margin_rate,
                          asset_class=AssetClass.COMMODITY, tick_size=0.01,
                          lot_size=1000, min_lot=0.01, max_lot=50.0, lot_step=0.01)

    # Indices
    if any(idx in s for idx in ("US30", "US100", "US500", "SPX", "NAS", "NDX",
                                  "DAX", "FTSE", "NIKKEI", "DJ30", "SP500")):
        return Instrument(symbol=s, point_value=point_value,
                          commission_value=commission, margin_rate=margin_rate,
                          **{k: v for k, v in INDEX_DEFAULTS.items()
                             if k not in ("point_value", "commission_value", "margin_rate")})

    # Crypto
    if any(c in s for c in ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA")):
        return Instrument(symbol=s, point_value=point_value,
                          commission_value=commission, margin_rate=margin_rate,
                          **{k: v for k, v in CRYPTO_DEFAULTS.items()
                             if k not in ("point_value", "commission_value", "margin_rate")})

    # Default: Forex pair
    tick_size = 0.001 if "JPY" in s else 0.00001
    return Instrument(symbol=s, tick_size=tick_size, point_value=point_value,
                      commission_value=commission, margin_rate=margin_rate,
                      **{k: v for k, v in FOREX_DEFAULTS.items()
                         if k not in ("tick_size", "point_value", "commission_value", "margin_rate")})
