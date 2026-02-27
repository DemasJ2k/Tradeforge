"""Pydantic schemas for broker / trading API endpoints."""

from typing import Optional
from pydantic import BaseModel


# ── Connection ─────────────────────────────────────────

class BrokerConnectRequest(BaseModel):
    broker: str                        # "oanda", "coinbase", etc.
    api_key: str
    account_id: str = ""
    practice: bool = True              # Oanda: practice vs live
    extra: dict = {}                   # broker-specific extra config


class BrokerStatusResponse(BaseModel):
    connected: bool
    broker_name: str
    is_default: bool


class BrokerListResponse(BaseModel):
    brokers: dict[str, BrokerStatusResponse]
    default_broker: Optional[str] = None


# ── Account ────────────────────────────────────────────

class AccountInfoResponse(BaseModel):
    account_id: str
    broker: str
    currency: str
    balance: float
    equity: float
    unrealized_pnl: float
    margin_used: float
    margin_available: float
    open_positions: int
    open_orders: int


# ── Positions ──────────────────────────────────────────

class PositionResponse(BaseModel):
    position_id: str
    symbol: str
    side: str
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    margin_used: float
    open_time: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


class ClosePositionRequest(BaseModel):
    position_id: str
    size: Optional[float] = None       # None = close all


# ── Orders ─────────────────────────────────────────────

class PlaceOrderRequest(BaseModel):
    symbol: str
    side: str                          # BUY or SELL
    size: float
    order_type: str = "MARKET"         # MARKET, LIMIT, STOP
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trailing_stop_distance: Optional[float] = None
    comment: Optional[str] = None
    broker: Optional[str] = None       # use specific broker (default if None)


class ModifyOrderRequest(BaseModel):
    order_id: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    price: Optional[float] = None
    trailing_stop_distance: Optional[float] = None
    broker: Optional[str] = None


class CancelOrderRequest(BaseModel):
    order_id: str
    broker: Optional[str] = None


class OrderResponse(BaseModel):
    order_id: str
    symbol: str
    side: str
    order_type: str
    size: float
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    status: str
    filled_price: Optional[float] = None
    filled_time: Optional[str] = None
    created_time: Optional[str] = None


# ── Market Data ────────────────────────────────────────

class SymbolInfoResponse(BaseModel):
    symbol: str
    display_name: str
    base_currency: str
    quote_currency: str
    pip_size: float
    min_lot: float
    max_lot: float
    lot_step: float
    margin_rate: float
    tradeable: bool
    asset_class: str


class PriceTickResponse(BaseModel):
    symbol: str
    bid: float
    ask: float
    spread: float
    timestamp: str


class CandleResponse(BaseModel):
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
