"""
Pydantic schemas for Market Data API.
"""

from typing import Optional
from pydantic import BaseModel


class MarketCandleData(BaseModel):
    time: float
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class MarketCandleResponse(BaseModel):
    symbol: str
    timeframe: str
    provider: str
    candles: list[MarketCandleData]
    total: int


class ProviderStatusResponse(BaseModel):
    name: str
    available: bool
    provider_type: str  # csv, broker, polygon, databento


class ProviderListResponse(BaseModel):
    providers: list[ProviderStatusResponse]


class RegisterPolygonRequest(BaseModel):
    api_key: str


class RegisterCSVRequest(BaseModel):
    datasource_id: int
