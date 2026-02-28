"""
Market Data API endpoints.

Unified market data access via the DataProvider abstraction layer.
Routes requests through the MarketDataManager which auto-selects
the best available provider: broker → polygon → csv.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.auth import get_current_user
from app.models.user import User
from app.models.datasource import DataSource
from app.schemas.market import (
    MarketCandleData,
    MarketCandleResponse,
    ProviderStatusResponse,
    ProviderListResponse,
    RegisterPolygonRequest,
    RegisterCSVRequest,
)
from app.services.market.provider import (
    market_data,
    CSVProvider,
    BrokerProvider,
    PolygonProvider,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market", tags=["market"])


# ── Provider management ───────────────────────────────

@router.get("/providers")
async def list_providers(user: User = Depends(get_current_user)):
    """List all registered market data providers and their availability."""
    providers = []
    for name, p in market_data._providers.items():
        try:
            available = await p.is_available()
        except Exception:
            available = False

        providers.append(ProviderStatusResponse(
            name=name,
            available=available,
            provider_type=p.provider_name,
        ))

    return ProviderListResponse(providers=providers)


@router.post("/providers/polygon")
async def register_polygon(
    payload: RegisterPolygonRequest,
    user: User = Depends(get_current_user),
):
    """Register or update the Polygon.io provider with an API key."""
    provider = PolygonProvider(api_key=payload.api_key)

    # Test connectivity
    available = await provider.is_available()
    if not available:
        raise HTTPException(400, "Polygon API key is invalid or API is unreachable")

    market_data.register("polygon", provider)
    return {"status": "registered", "provider": "polygon", "available": True}


@router.post("/providers/csv")
async def register_csv(
    payload: RegisterCSVRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Register a CSV data source as a market data provider."""
    ds = db.query(DataSource).filter(DataSource.id == payload.datasource_id).first()
    if not ds:
        raise HTTPException(404, f"Data source {payload.datasource_id} not found")

    provider = CSVProvider(file_path=ds.filepath)
    name = f"csv_{ds.id}"
    market_data.register(name, provider)

    return {
        "status": "registered",
        "provider": name,
        "available": True,
        "symbol": ds.symbol,
        "timeframe": ds.timeframe,
    }


@router.delete("/providers/{provider_name}")
async def remove_provider(
    provider_name: str,
    user: User = Depends(get_current_user),
):
    """Remove a registered provider."""
    if provider_name not in market_data._providers:
        raise HTTPException(404, f"Provider '{provider_name}' not found")

    market_data.remove(provider_name)
    return {"status": "removed", "provider": provider_name}


# ── Candle data ───────────────────────────────────────

@router.get("/candles/{symbol}")
async def get_candles(
    symbol: str,
    timeframe: str = Query("H1"),
    count: int = Query(200, ge=1, le=10000),
    provider: Optional[str] = Query(None, description="Force a specific provider"),
    from_date: Optional[str] = Query(None, description="Start date (ISO 8601)"),
    to_date: Optional[str] = Query(None, description="End date (ISO 8601)"),
    user: User = Depends(get_current_user),
):
    """
    Get OHLCV candle data from the best available provider.

    Priority: explicit provider → broker → polygon → csv

    For CSV providers, use provider name like 'csv_3' (csv_{datasource_id}).
    """
    from_time = None
    to_time = None

    if from_date:
        try:
            from_time = datetime.fromisoformat(from_date.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"Invalid from_date: {from_date}")

    if to_date:
        try:
            to_time = datetime.fromisoformat(to_date.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"Invalid to_date: {to_date}")

    bars = await market_data.get_candles(
        symbol=symbol,
        timeframe=timeframe,
        count=count,
        provider_name=provider,
        from_time=from_time,
        to_time=to_time,
    )

    if not bars:
        return MarketCandleResponse(
            symbol=symbol,
            timeframe=timeframe,
            provider="none",
            candles=[],
            total=0,
        )

    # Determine which provider was used
    used_provider = provider or "auto"
    if not provider:
        for name in ["broker", "polygon", "csv"]:
            p = market_data.get_provider(name)
            if p:
                try:
                    if await p.is_available():
                        used_provider = name
                        break
                except Exception:
                    continue

    candles = [
        MarketCandleData(
            time=b.timestamp.timestamp() if hasattr(b.timestamp, "timestamp") else float(b.timestamp),
            open=b.open,
            high=b.high,
            low=b.low,
            close=b.close,
            volume=b.volume,
        )
        for b in bars
    ]

    return MarketCandleResponse(
        symbol=symbol,
        timeframe=timeframe,
        provider=used_provider,
        candles=candles,
        total=len(candles),
    )


# ── Symbols ───────────────────────────────────────────

@router.get("/symbols")
async def get_symbols(
    provider: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
):
    """Get list of available symbols across providers."""
    all_symbols: set[str] = set()

    if provider:
        p = market_data.get_provider(provider)
        if p:
            try:
                syms = await p.get_symbols()
                all_symbols.update(syms)
            except Exception as e:
                logger.warning("Provider %s failed to get symbols: %s", provider, e)
    else:
        # Gather from all providers
        for name, p in market_data._providers.items():
            try:
                if await p.is_available():
                    syms = await p.get_symbols()
                    all_symbols.update(syms)
            except Exception as e:
                logger.warning("Provider %s failed: %s", name, e)

    return {"symbols": sorted(all_symbols)}


# ── Auto-wire broker provider ─────────────────────────

@router.get("/mt5/bars/{symbol}")
async def get_mt5_bars(
    symbol: str,
    timeframe: str = Query("H1"),
    count: int = Query(500, ge=1, le=5000),
    user: User = Depends(get_current_user),
):
    """Get initial historical bars directly from MT5 for chart initialization."""
    from app.services.broker.manager import broker_manager

    adapter = broker_manager.get_adapter("mt5")
    if not adapter:
        raise HTTPException(400, "MT5 broker not connected")

    try:
        connected = await adapter.is_connected()
        if not connected:
            raise HTTPException(400, "MT5 broker not connected")
    except Exception:
        raise HTTPException(400, "MT5 broker not connected")

    bars = await adapter.get_initial_bars(symbol, timeframe, count)
    if not bars:
        raise HTTPException(404, f"No bar data for {symbol} ({timeframe})")

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "bars": bars,
        "total": len(bars),
    }


def wire_broker_provider():
    """
    Called after broker connects to register it as a market data provider.
    This allows the chart to pull live data from the connected broker.
    """
    from app.services.broker.manager import broker_manager

    async def _register():
        adapter = broker_manager.get_adapter()
        if adapter:
            provider = BrokerProvider(adapter)
            market_data.register("broker", provider)
            logger.info("Broker provider registered for market data")

    return _register
