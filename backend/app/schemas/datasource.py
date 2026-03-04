from pydantic import BaseModel
from typing import Optional


class DataSourceResponse(BaseModel):
    id: int
    filename: str
    symbol: str
    timeframe: str
    data_type: str
    row_count: int
    date_from: str
    date_to: str
    columns: str
    file_size_mb: float
    source_type: str = "upload"
    broker_name: str = ""
    # Instrument profile
    pip_value: float = 10.0
    point_value: float = 1.0
    lot_size: float = 100000.0
    default_spread: float = 0.3
    commission_model: str = "per_lot"
    default_commission: float = 7.0

    class Config:
        from_attributes = True


class DataSourceList(BaseModel):
    items: list[DataSourceResponse]
    total: int


class BrokerFetchRequest(BaseModel):
    broker: str        # mt5, oanda, coinbase, tradovate
    symbol: str        # e.g. XAUUSD
    timeframe: str     # e.g. M5, H1, D1
    bars: int = 5000   # number of bars to fetch


class CandleData(BaseModel):
    time: float  # Unix timestamp
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = 0.0


class CandleResponse(BaseModel):
    symbol: str
    timeframe: str
    candles: list[CandleData]
    total: int
