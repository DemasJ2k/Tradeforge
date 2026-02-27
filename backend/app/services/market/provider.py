"""
Market data provider abstraction.

Defines the DataProvider interface and implementations for:
  - CSVProvider: Load from uploaded CSV files
  - BrokerProvider: Fetch from connected broker adapters
  - PolygonProvider: Polygon.io REST API
  - DatabentProvider: Databento API (placeholder)

Each provider returns standardized OHLCV data that can be consumed
by the chart, backtest engine, and ML pipeline.
"""

import csv
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class OHLCVBar:
    """Standardized OHLCV bar."""
    timestamp: float      # Unix seconds
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class DataProvider(ABC):
    """Abstract market data provider."""

    provider_name: str = "base"

    @abstractmethod
    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        count: int = 100,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
    ) -> list[OHLCVBar]:
        """Fetch OHLCV candle data."""
        ...

    @abstractmethod
    async def get_symbols(self) -> list[str]:
        """Get list of available symbols."""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the provider is available/configured."""
        ...


# ── CSV Provider ──────────────────────────────────────

class CSVProvider(DataProvider):
    """Load candle data from an uploaded CSV file."""

    provider_name = "csv"

    def __init__(self, file_path: str):
        self._path = file_path

    async def get_candles(
        self,
        symbol: str = "",
        timeframe: str = "",
        count: int = 100,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
    ) -> list[OHLCVBar]:
        if not os.path.exists(self._path):
            return []

        bars: list[OHLCVBar] = []
        with open(self._path, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    # Parse timestamp
                    ts_raw = row.get("datetime") or row.get("date") or row.get("time") or row.get("timestamp") or ""
                    ts = _parse_timestamp(ts_raw)

                    bar = OHLCVBar(
                        timestamp=ts,
                        open=float(row.get("open") or row.get("Open") or row.get("o") or 0),
                        high=float(row.get("high") or row.get("High") or row.get("h") or 0),
                        low=float(row.get("low") or row.get("Low") or row.get("l") or 0),
                        close=float(row.get("close") or row.get("Close") or row.get("c") or 0),
                        volume=float(row.get("volume") or row.get("Volume") or row.get("v") or 0),
                    )
                    if bar.close > 0:
                        bars.append(bar)
                except (ValueError, TypeError):
                    continue

        # Apply time filters
        if from_time:
            from_ts = from_time.timestamp()
            bars = [b for b in bars if b.timestamp >= from_ts]
        if to_time:
            to_ts = to_time.timestamp()
            bars = [b for b in bars if b.timestamp <= to_ts]

        # Limit count
        if count and len(bars) > count:
            bars = bars[-count:]

        return bars

    async def get_symbols(self) -> list[str]:
        return []

    async def is_available(self) -> bool:
        return os.path.exists(self._path)


# ── Broker Provider ───────────────────────────────────

class BrokerProvider(DataProvider):
    """Fetch data from a connected broker adapter."""

    provider_name = "broker"

    def __init__(self, adapter):
        self._adapter = adapter

    async def get_candles(
        self,
        symbol: str = "",
        timeframe: str = "H1",
        count: int = 100,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
    ) -> list[OHLCVBar]:
        candles = await self._adapter.get_candles(symbol, timeframe, count, from_time, to_time)
        return [
            OHLCVBar(
                timestamp=c.timestamp.timestamp(),
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
            )
            for c in candles
        ]

    async def get_symbols(self) -> list[str]:
        symbols = await self._adapter.get_symbols()
        return [s.symbol for s in symbols]

    async def is_available(self) -> bool:
        return await self._adapter.is_connected()


# ── Polygon.io Provider ──────────────────────────────

class PolygonProvider(DataProvider):
    """
    Polygon.io REST API provider for stocks, forex, and crypto.
    Requires API key (free tier supports delayed data).

    Docs: https://polygon.io/docs
    """

    provider_name = "polygon"

    _BASE_URL = "https://api.polygon.io"

    # Timeframe mapping to Polygon format
    _TF_MAP = {
        "M1": ("1", "minute"), "M5": ("5", "minute"), "M15": ("15", "minute"),
        "M30": ("30", "minute"), "H1": ("1", "hour"), "H4": ("4", "hour"),
        "D1": ("1", "day"), "W1": ("1", "week"), "MN1": ("1", "month"),
        "1m": ("1", "minute"), "5m": ("5", "minute"), "15m": ("15", "minute"),
        "30m": ("30", "minute"), "1h": ("1", "hour"), "4h": ("4", "hour"),
        "1d": ("1", "day"),
    }

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def get_candles(
        self,
        symbol: str = "",
        timeframe: str = "H1",
        count: int = 100,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
    ) -> list[OHLCVBar]:
        import httpx

        multiplier, span = self._TF_MAP.get(timeframe, ("1", "hour"))

        # Default: last 30 days
        end = to_time or datetime.now(timezone.utc)
        if from_time:
            start = from_time
        else:
            # Estimate how far back to go
            bar_seconds = {
                "minute": 60, "hour": 3600, "day": 86400, "week": 604800, "month": 2592000,
            }.get(span, 3600)
            start = end - timedelta(seconds=count * bar_seconds * int(multiplier))

        from_str = start.strftime("%Y-%m-%d")
        to_str = end.strftime("%Y-%m-%d")

        # Polygon symbol format: stocks use as-is, forex uses C:EURUSD, crypto uses X:BTCUSD
        polygon_symbol = symbol
        if "/" in symbol:
            # e.g. EUR/USD → C:EURUSD
            parts = symbol.split("/")
            polygon_symbol = f"C:{parts[0]}{parts[1]}"
        elif "-" in symbol:
            # e.g. BTC-USD → X:BTCUSD
            parts = symbol.split("-")
            polygon_symbol = f"X:{parts[0]}{parts[1]}"

        url = (
            f"{self._BASE_URL}/v2/aggs/ticker/{polygon_symbol}"
            f"/range/{multiplier}/{span}/{from_str}/{to_str}"
        )

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(url, params={
                    "adjusted": "true",
                    "sort": "asc",
                    "limit": min(count, 50000),
                    "apiKey": self._api_key,
                })
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            logger.error("Polygon API error: %s", e)
            return []

        bars: list[OHLCVBar] = []
        for result in data.get("results", []):
            bars.append(OHLCVBar(
                timestamp=result["t"] / 1000,  # Polygon returns ms
                open=float(result["o"]),
                high=float(result["h"]),
                low=float(result["l"]),
                close=float(result["c"]),
                volume=float(result.get("v", 0)),
            ))

        return bars[-count:] if len(bars) > count else bars

    async def get_symbols(self) -> list[str]:
        """Polygon has thousands of symbols — return empty for now."""
        return []

    async def is_available(self) -> bool:
        if not self._api_key:
            return False
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    f"{self._BASE_URL}/v3/reference/tickers",
                    params={"limit": 1, "apiKey": self._api_key},
                )
                return r.status_code == 200
        except Exception:
            return False


# ── Databento Provider (placeholder) ──────────────────

class DabentoProvider(DataProvider):
    """
    Databento API provider for institutional-grade market data.
    Placeholder — requires Databento subscription.
    """

    provider_name = "databento"

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def get_candles(self, **kwargs) -> list[OHLCVBar]:
        # TODO: Implement when Databento MCP or SDK is available
        logger.warning("Databento provider not yet implemented")
        return []

    async def get_symbols(self) -> list[str]:
        return []

    async def is_available(self) -> bool:
        return bool(self._api_key)


# ── Provider manager ──────────────────────────────────

class MarketDataManager:
    """
    Manages available market data providers and routes requests
    to the most appropriate one.

    Priority: Broker (live) → Polygon → CSV (fallback)
    """

    def __init__(self):
        self._providers: dict[str, DataProvider] = {}

    def register(self, name: str, provider: DataProvider):
        self._providers[name] = provider

    def remove(self, name: str):
        self._providers.pop(name, None)

    def get_provider(self, name: str) -> Optional[DataProvider]:
        return self._providers.get(name)

    async def get_candles(
        self,
        symbol: str,
        timeframe: str = "H1",
        count: int = 100,
        provider_name: Optional[str] = None,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
    ) -> list[OHLCVBar]:
        """
        Get candles from the best available provider.
        If provider_name is specified, use that one directly.
        """
        if provider_name and provider_name in self._providers:
            p = self._providers[provider_name]
            if await p.is_available():
                return await p.get_candles(symbol, timeframe, count, from_time, to_time)

        # Auto-select: broker first, then polygon, then csv
        for name in ["broker", "polygon", "csv"]:
            p = self._providers.get(name)
            if p and await p.is_available():
                try:
                    bars = await p.get_candles(symbol, timeframe, count, from_time, to_time)
                    if bars:
                        return bars
                except Exception as e:
                    logger.warning("Provider %s failed: %s", name, e)
                    continue

        return []


# Global instance
market_data = MarketDataManager()


# ── Helpers ───────────────────────────────────────────

def _parse_timestamp(ts_str: str) -> float:
    """Parse various timestamp formats to Unix seconds."""
    if not ts_str:
        return 0.0

    # Try numeric (unix timestamp)
    try:
        val = float(ts_str)
        if val > 1e12:  # milliseconds
            return val / 1000
        return val
    except ValueError:
        pass

    # Try ISO 8601
    for fmt in [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
    ]:
        try:
            dt = datetime.strptime(ts_str.strip(), fmt)
            return dt.replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue

    # Try with Z suffix
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except ValueError:
        pass

    return 0.0
