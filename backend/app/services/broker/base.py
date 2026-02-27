"""
Abstract broker adapter interface.

All broker implementations (Oanda, Coinbase, MT5, Tradovate) must implement this.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, AsyncGenerator


# ── Enums ──────────────────────────────────────────────

class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


# ── Data Classes ───────────────────────────────────────

@dataclass
class AccountInfo:
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


@dataclass
class Position:
    position_id: str
    symbol: str
    side: PositionSide
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    margin_used: float
    open_time: datetime
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


@dataclass
class Order:
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    size: float
    price: Optional[float] = None       # for limit / stop
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_price: Optional[float] = None
    filled_time: Optional[datetime] = None
    created_time: Optional[datetime] = None


@dataclass
class OrderRequest:
    symbol: str
    side: OrderSide
    size: float
    order_type: OrderType = OrderType.MARKET
    price: Optional[float] = None       # for limit / stop
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trailing_stop_distance: Optional[float] = None
    comment: Optional[str] = None


@dataclass
class OrderModifyRequest:
    order_id: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    price: Optional[float] = None       # move limit price
    trailing_stop_distance: Optional[float] = None


@dataclass
class SymbolInfo:
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
    asset_class: str = "forex"          # forex, crypto, index, commodity


@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class PriceTick:
    symbol: str
    bid: float
    ask: float
    timestamp: datetime
    spread: float = 0.0


@dataclass
class BrokerEvent:
    """Generic event from broker stream (price update, order fill, etc.)"""
    event_type: str           # "price", "order_fill", "order_cancel", "heartbeat"
    data: dict = field(default_factory=dict)
    timestamp: Optional[datetime] = None


# ── Abstract Base ──────────────────────────────────────

class BrokerAdapter(ABC):
    """
    Abstract base class for all broker integrations.
    Each broker implements connect/disconnect, account queries,
    order management, and data streaming.
    """

    broker_name: str = "unknown"

    # ── Connection ─────────────────────────────────────

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to the broker. Returns True on success."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close the broker connection."""
        ...

    @abstractmethod
    async def is_connected(self) -> bool:
        """Check if broker connection is alive."""
        ...

    # ── Account ────────────────────────────────────────

    @abstractmethod
    async def get_account_info(self) -> AccountInfo:
        """Get account balance, equity, margin, etc."""
        ...

    # ── Positions ──────────────────────────────────────

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Get all open positions."""
        ...

    @abstractmethod
    async def close_position(self, position_id: str, size: Optional[float] = None) -> Order:
        """Close a position (fully or partially if size specified)."""
        ...

    # ── Orders ─────────────────────────────────────────

    @abstractmethod
    async def place_order(self, request: OrderRequest) -> Order:
        """Submit a new order."""
        ...

    @abstractmethod
    async def modify_order(self, request: OrderModifyRequest) -> Order:
        """Modify an existing pending order or position SL/TP."""
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order. Returns True on success."""
        ...

    @abstractmethod
    async def get_open_orders(self) -> list[Order]:
        """Get all pending orders."""
        ...

    # ── Market Data ────────────────────────────────────

    @abstractmethod
    async def get_symbols(self) -> list[SymbolInfo]:
        """Get all tradeable instruments."""
        ...

    @abstractmethod
    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        count: int = 100,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
    ) -> list[Candle]:
        """Get historical candles for a symbol."""
        ...

    @abstractmethod
    async def get_price(self, symbol: str) -> PriceTick:
        """Get current bid/ask for a symbol."""
        ...

    # ── Streaming ──────────────────────────────────────

    @abstractmethod
    async def stream_prices(self, symbols: list[str]) -> AsyncGenerator[PriceTick, None]:
        """Stream live prices. Yields PriceTick objects."""
        ...
