"""
Instrument specification system for the V2 backtesting engine.

Provides per-symbol contract specifications (contract size, pip value,
pip size, margin requirements) so the engine doesn't need hardcoded
×100 multipliers or other Forex-specific hacks.

Usage:
    spec = get_instrument_spec("XAUUSD")
    # or
    spec = InstrumentSpec.for_symbol("XAUUSD")
    dollar_pnl = price_diff * spec.contract_size * lots
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class InstrumentSpec:
    """Contract specification for a single instrument.

    Attributes
    ----------
    symbol : str
        Canonical symbol name (e.g. "XAUUSD").
    contract_size : float
        Units per 1.0 lot.  Forex pairs: 100_000, Gold: 100, Silver: 5000, etc.
    pip_size : float
        Minimum price increment that equals 1 pip.
        Forex 5-digit: 0.00010, JPY pairs: 0.010, Gold: 0.10, Silver: 0.010.
    pip_value_per_lot : float
        Dollar value of 1 pip move per 1.0 standard lot.
        For EURUSD: $10 per pip per lot.
        Computed as: pip_size × contract_size (for USD-denominated pairs).
    point_value : float
        Dollar value of a 1-point (minimum tick) move per 1.0 standard lot.
        For 5-digit Forex: pip_value / 10.
        For Gold (0.01 tick): contract_size × tick_size.
    margin_rate : float
        Fraction of notional required as margin (e.g. 0.01 = 100:1 leverage).
    min_lot : float
        Minimum tradeable lot size (typically 0.01).
    lot_step : float
        Lot size increment (typically 0.01).
    digits : int
        Price decimal places for display.
    description : str
        Human-readable description.
    """
    symbol: str
    contract_size: float = 100_000.0
    pip_size: float = 0.00010
    pip_value_per_lot: float = 10.0
    point_value: float = 1.0
    margin_rate: float = 0.01
    min_lot: float = 0.01
    lot_step: float = 0.01
    digits: int = 5
    description: str = ""

    @classmethod
    def for_symbol(cls, symbol: str) -> "InstrumentSpec":
        """Look up the spec for *symbol*, returning a sensible default if unknown."""
        return get_instrument_spec(symbol)

    def pip_value(self, lots: float = 1.0) -> float:
        """Dollar value of 1 pip for the given lot size."""
        return self.pip_value_per_lot * lots

    def pnl(self, price_diff: float, lots: float) -> float:
        """Compute dollar PnL from a price difference and lot size.

        ``price_diff`` is signed (positive for profit on longs).
        """
        return price_diff * self.contract_size * lots

    def margin_required(self, price: float, lots: float) -> float:
        """Notional margin required to hold *lots* at *price*."""
        return price * self.contract_size * lots * self.margin_rate


# ────────────────────────────────────────────────────────────────────
# Built-in instrument catalogue
# ────────────────────────────────────────────────────────────────────

_INSTRUMENT_CATALOGUE: dict[str, InstrumentSpec] = {}


def _register(*specs: InstrumentSpec) -> None:
    for s in specs:
        _INSTRUMENT_CATALOGUE[s.symbol.upper()] = s


# --- Forex majors ---
_register(
    InstrumentSpec("EURUSD", contract_size=100_000, pip_size=0.00010,
                   pip_value_per_lot=10.0, point_value=1.0,
                   digits=5, description="Euro / US Dollar"),
    InstrumentSpec("GBPUSD", contract_size=100_000, pip_size=0.00010,
                   pip_value_per_lot=10.0, point_value=1.0,
                   digits=5, description="Pound / US Dollar"),
    InstrumentSpec("USDJPY", contract_size=100_000, pip_size=0.010,
                   pip_value_per_lot=6.70, point_value=0.67,
                   digits=3, description="US Dollar / Japanese Yen"),
    InstrumentSpec("USDCHF", contract_size=100_000, pip_size=0.00010,
                   pip_value_per_lot=10.0, point_value=1.0,
                   digits=5, description="US Dollar / Swiss Franc"),
    InstrumentSpec("AUDUSD", contract_size=100_000, pip_size=0.00010,
                   pip_value_per_lot=10.0, point_value=1.0,
                   digits=5, description="Australian Dollar / US Dollar"),
    InstrumentSpec("USDCAD", contract_size=100_000, pip_size=0.00010,
                   pip_value_per_lot=7.30, point_value=0.73,
                   digits=5, description="US Dollar / Canadian Dollar"),
    InstrumentSpec("NZDUSD", contract_size=100_000, pip_size=0.00010,
                   pip_value_per_lot=10.0, point_value=1.0,
                   digits=5, description="NZ Dollar / US Dollar"),
)

# --- Metals ---
_register(
    InstrumentSpec("XAUUSD", contract_size=100, pip_size=0.10,
                   pip_value_per_lot=10.0, point_value=1.0,
                   margin_rate=0.01, digits=2,
                   description="Gold / US Dollar (100 oz)"),
    InstrumentSpec("XAGUSD", contract_size=5_000, pip_size=0.010,
                   pip_value_per_lot=50.0, point_value=5.0,
                   margin_rate=0.01, digits=3,
                   description="Silver / US Dollar (5000 oz)"),
)

# --- Indices ---
_register(
    InstrumentSpec("US30", contract_size=1, pip_size=1.0,
                   pip_value_per_lot=1.0, point_value=1.0,
                   margin_rate=0.005, digits=1,
                   description="Dow Jones Industrial Average"),
    InstrumentSpec("US500", contract_size=1, pip_size=0.10,
                   pip_value_per_lot=0.10, point_value=0.10,
                   margin_rate=0.005, digits=2,
                   description="S&P 500 Index"),
    InstrumentSpec("NAS100", contract_size=1, pip_size=0.10,
                   pip_value_per_lot=0.10, point_value=0.10,
                   margin_rate=0.005, digits=2,
                   description="Nasdaq 100 Index"),
)

# --- Crypto ---
_register(
    InstrumentSpec("BTCUSD", contract_size=1, pip_size=0.01,
                   pip_value_per_lot=0.01, point_value=0.01,
                   margin_rate=0.02, digits=2,
                   description="Bitcoin / US Dollar"),
    InstrumentSpec("ETHUSD", contract_size=1, pip_size=0.01,
                   pip_value_per_lot=0.01, point_value=0.01,
                   margin_rate=0.02, digits=2,
                   description="Ethereum / US Dollar"),
)


# ────────────────────────────────────────────────────────────────────
# Lookup
# ────────────────────────────────────────────────────────────────────

def get_instrument_spec(symbol: str) -> InstrumentSpec:
    """Return the InstrumentSpec for *symbol*.

    Falls back to a generic Forex-like spec if the symbol is unknown.
    """
    key = symbol.strip().upper()

    # Exact match
    if key in _INSTRUMENT_CATALOGUE:
        return _INSTRUMENT_CATALOGUE[key]

    # Try without suffix (e.g. "XAUUSD.raw" → "XAUUSD")
    base = key.split(".")[0]
    if base in _INSTRUMENT_CATALOGUE:
        return _INSTRUMENT_CATALOGUE[base]

    # Generic fallback
    return InstrumentSpec(
        symbol=symbol,
        contract_size=100_000,
        pip_size=0.00010,
        pip_value_per_lot=10.0,
        point_value=1.0,
        digits=5,
        description=f"Unknown instrument ({symbol})",
    )


def list_instruments() -> list[InstrumentSpec]:
    """Return all registered instrument specs."""
    return list(_INSTRUMENT_CATALOGUE.values())
