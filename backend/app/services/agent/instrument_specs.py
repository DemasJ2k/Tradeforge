"""
Instrument specifications for position sizing and P&L calculation.

Provides broker-aware dollar P&L and lot-size calculations.
On Oanda, "units" translate directly: pnl = price_diff × units.
On MT5, standard lots apply: pnl = price_diff × lots × contract_size.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Instrument spec table ──────────────────────────────────────────
# contract_size: how many base units per 1.0 lot (MT5 convention)
# For Oanda: ignored — Oanda uses raw units so pnl = diff × units.

INSTRUMENT_SPECS: dict[str, dict] = {
    # Forex majors (1 standard lot = 100,000 base currency)
    "EURUSD":  {"type": "forex", "contract_size": 100_000, "pip_size": 0.0001},
    "GBPUSD":  {"type": "forex", "contract_size": 100_000, "pip_size": 0.0001},
    "USDJPY":  {"type": "forex", "contract_size": 100_000, "pip_size": 0.01},
    "AUDUSD":  {"type": "forex", "contract_size": 100_000, "pip_size": 0.0001},
    "USDCAD":  {"type": "forex", "contract_size": 100_000, "pip_size": 0.0001},
    "NZDUSD":  {"type": "forex", "contract_size": 100_000, "pip_size": 0.0001},
    "USDCHF":  {"type": "forex", "contract_size": 100_000, "pip_size": 0.0001},
    "EURGBP":  {"type": "forex", "contract_size": 100_000, "pip_size": 0.0001},
    "EURJPY":  {"type": "forex", "contract_size": 100_000, "pip_size": 0.01},
    "GBPJPY":  {"type": "forex", "contract_size": 100_000, "pip_size": 0.01},

    # Metals
    "XAUUSD":  {"type": "metal", "contract_size": 100, "pip_size": 0.01},
    "XAGUSD":  {"type": "metal", "contract_size": 5000, "pip_size": 0.001},

    # Indices (Oanda CFD: 1 unit = 1 index point = $1/point)
    "US30":    {"type": "index", "contract_size": 1, "pip_size": 1.0},
    "NAS100":  {"type": "index", "contract_size": 1, "pip_size": 1.0},
    "SPX500":  {"type": "index", "contract_size": 1, "pip_size": 0.1},
    "US100":   {"type": "index", "contract_size": 1, "pip_size": 1.0},
    "AUS200":  {"type": "index", "contract_size": 1, "pip_size": 1.0},
    "UK100":   {"type": "index", "contract_size": 1, "pip_size": 1.0},

    # Crypto
    "BTCUSD":  {"type": "crypto", "contract_size": 1, "pip_size": 1.0},
    "ETHUSD":  {"type": "crypto", "contract_size": 1, "pip_size": 0.01},

    # Energies
    "WTIUSD":  {"type": "energy", "contract_size": 1000, "pip_size": 0.01},
    "BCOUSD":  {"type": "energy", "contract_size": 1000, "pip_size": 0.01},
}

# Default for unknown instruments
_DEFAULT_SPEC = {"type": "unknown", "contract_size": 1, "pip_size": 1.0}


def _normalize_symbol(symbol: str) -> str:
    """Strip Oanda suffixes like _USD, /USD to find the base symbol."""
    s = symbol.upper().replace("/", "").replace("_", "")
    # e.g. "US30USD" → try "US30" if full name not found
    if s not in INSTRUMENT_SPECS:
        for suffix in ("USD", "EUR", "GBP", "AUD", "JPY", "CAD", "CHF"):
            if s.endswith(suffix) and s[:-len(suffix)] in INSTRUMENT_SPECS:
                return s[:-len(suffix)]
    return s


def get_spec(symbol: str) -> dict:
    """Get instrument specification. Falls back to safe defaults for unknown symbols."""
    norm = _normalize_symbol(symbol)
    spec = INSTRUMENT_SPECS.get(norm)
    if spec is None:
        logger.warning("Unknown instrument '%s' (normalized: '%s') — using defaults", symbol, norm)
        return {**_DEFAULT_SPEC, "symbol": norm}
    return {**spec, "symbol": norm}


def calc_pnl_dollars(
    symbol: str,
    direction: str,
    entry_price: float,
    exit_price: float,
    lot_size: float,
    broker_name: str = "oanda",
) -> float:
    """
    Calculate dollar P&L for a closed trade.

    Oanda: pnl = price_diff × units (lot_size IS units on Oanda)
    MT5:   pnl = price_diff × lots × contract_size
    """
    if not entry_price or not exit_price:
        return 0.0

    if direction.upper() == "BUY":
        price_diff = exit_price - entry_price
    else:
        price_diff = entry_price - exit_price

    if broker_name and broker_name.lower() == "oanda":
        # Oanda: lot_size = raw units. 1 unit of US30 = $1 per point.
        return price_diff * lot_size
    else:
        # MT5 / other: standard lot convention
        spec = get_spec(symbol)
        return price_diff * lot_size * spec["contract_size"]


def calc_lot_size(
    symbol: str,
    risk_amount_usd: float,
    sl_distance: float,
    broker_name: str = "oanda",
    min_size: float = 0.01,
    max_size: float = 10000.0,
) -> float:
    """
    Calculate position size from risk amount and stop-loss distance.

    Oanda: units = risk_amount / sl_distance (since 1 unit = $1/pt for indices)
    MT5:   lots = risk_amount / (sl_distance × contract_size)

    Returns lot_size clamped to [min_size, max_size] and rounded to 2dp.
    """
    if sl_distance <= 0 or risk_amount_usd <= 0:
        return min_size

    if broker_name and broker_name.lower() == "oanda":
        lot_size = risk_amount_usd / sl_distance
    else:
        spec = get_spec(symbol)
        divisor = sl_distance * spec["contract_size"]
        lot_size = risk_amount_usd / divisor if divisor > 0 else min_size

    lot_size = max(min_size, min(max_size, lot_size))
    return round(lot_size, 2)
