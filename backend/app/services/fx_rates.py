"""
FX Rate Service — converts currency amounts to USD using live exchange rates.

Uses the free Open Exchange Rates API (no key required for USD base).
Caches rates for 1 hour to minimize API calls.
Falls back to hardcoded rates if the API is unavailable.
"""

import asyncio
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Hardcoded fallback rates (approximate, updated 2025-Q4)
_FALLBACK_RATES: dict[str, float] = {
    "USD": 1.0,
    "EUR": 0.92,
    "GBP": 0.79,
    "AUD": 1.55,
    "CAD": 1.36,
    "CHF": 0.88,
    "JPY": 149.5,
    "NZD": 1.68,
    "SGD": 1.34,
    "HKD": 7.82,
    "SEK": 10.5,
    "NOK": 10.6,
    "DKK": 6.88,
    "PLN": 4.05,
    "CZK": 23.2,
    "HUF": 370.0,
    "ZAR": 18.3,
    "MXN": 17.2,
    "BRL": 4.95,
    "INR": 83.5,
    "CNY": 7.24,
    "KRW": 1330.0,
    "TRY": 32.0,
    "THB": 35.5,
}

_cached_rates: Optional[dict[str, float]] = None
_cache_timestamp: float = 0.0
_CACHE_TTL = 3600  # 1 hour


async def _fetch_rates() -> Optional[dict[str, float]]:
    """Fetch live rates from Open Exchange Rates API."""
    global _cached_rates, _cache_timestamp

    # Return cached if still fresh
    if _cached_rates and (time.time() - _cache_timestamp) < _CACHE_TTL:
        return _cached_rates

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://open.er-api.com/v6/latest/USD")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("result") == "success" and "rates" in data:
                    _cached_rates = data["rates"]
                    _cache_timestamp = time.time()
                    logger.info("FX rates refreshed: %d currencies", len(_cached_rates))
                    return _cached_rates
    except Exception as e:
        logger.warning("Failed to fetch FX rates: %s", e)

    return None


async def get_usd_rate(currency: str) -> float:
    """
    Get the rate to convert 1 unit of `currency` to USD.
    Returns the multiplier: amount_in_currency * rate = amount_in_usd.
    """
    currency = currency.upper().strip()
    if currency == "USD":
        return 1.0

    rates = await _fetch_rates()
    if rates and currency in rates:
        # rates are USD-based: rates[X] = how many X per 1 USD
        # To convert X → USD: divide by rate
        return 1.0 / rates[currency]

    # Fallback
    fallback_rate = _FALLBACK_RATES.get(currency)
    if fallback_rate:
        return 1.0 / fallback_rate

    logger.warning("Unknown currency '%s', assuming 1:1 with USD", currency)
    return 1.0


async def convert_to_usd(amount: float, currency: str) -> float:
    """Convert an amount in the given currency to USD."""
    rate = await get_usd_rate(currency)
    return round(amount * rate, 2)


async def get_all_rates() -> dict[str, float]:
    """Return the full rate table (USD-based)."""
    rates = await _fetch_rates()
    return rates or _FALLBACK_RATES
