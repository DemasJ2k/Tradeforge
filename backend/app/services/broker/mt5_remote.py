"""
MetaTrader 5 Remote Bridge Adapter.

Replaces direct MetaTrader5 Python package calls with HTTP requests
to an external MT5 Bridge Server running on a Windows VPS.

This adapter is used when the main backend is deployed on Linux (Render)
where the MetaTrader5 package cannot run.

The bridge server URL and API key are configured via environment variables:
  MT5_BRIDGE_URL  — e.g. https://your-vps-ip:8010
  MT5_BRIDGE_KEY  — shared secret key

Falls back to the local MetaTrader5 package if MT5_BRIDGE_URL is not set
and the package is available (for local Windows development).
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional, AsyncGenerator

import httpx

from .base import (
    BrokerAdapter,
    AccountInfo,
    Position,
    PositionSide,
    Order,
    OrderRequest,
    OrderModifyRequest,
    OrderSide,
    OrderType,
    OrderStatus,
    SymbolInfo,
    Candle,
    PriceTick,
)

logger = logging.getLogger(__name__)

BRIDGE_URL = os.getenv("MT5_BRIDGE_URL", "").rstrip("/")
BRIDGE_KEY = os.getenv("MT5_BRIDGE_KEY", "changeme-mt5-bridge-key")

# Timeout: 15s connect, 30s read (MT5 operations can be slow)
_TIMEOUT = httpx.Timeout(connect=15.0, read=30.0, write=15.0, pool=15.0)


class MT5RemoteAdapter(BrokerAdapter):
    """
    MT5 adapter that communicates with a remote MT5 Bridge Server via REST.

    The bridge server runs on a Windows VPS alongside the MT5 terminal
    and exposes all MT5 operations as HTTP endpoints.
    """

    broker_name = "mt5"

    def __init__(self, server: str, login: int, password: str):
        self._server = server
        self._login = login
        self._password = password
        self._connected = False
        self._bridge_url = BRIDGE_URL
        self._headers = {"X-Bridge-Key": BRIDGE_KEY}

    def _url(self, path: str) -> str:
        return f"{self._bridge_url}{path}"

    # ── Connection ────────────────────────────────────

    async def connect(self) -> bool:
        if not self._bridge_url:
            logger.error("MT5_BRIDGE_URL not configured")
            return False

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
                resp = await client.post(
                    self._url("/connect"),
                    headers=self._headers,
                    json={
                        "server": self._server,
                        "login": self._login,
                        "password": self._password,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("ok"):
                    self._connected = True
                    logger.info(
                        "MT5 bridge connected: account %s on %s (balance: %.2f %s)",
                        data.get("login"), data.get("server"),
                        data.get("balance", 0), data.get("currency", ""),
                    )
                    return True
                else:
                    logger.error("MT5 bridge connect failed: %s", data.get("error"))
                    return False
        except Exception as e:
            logger.error("MT5 bridge connect exception: %s", e)
            return False

    async def disconnect(self) -> None:
        if self._connected:
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
                    await client.post(self._url("/disconnect"), headers=self._headers)
            except Exception:
                pass
        self._connected = False

    async def is_connected(self) -> bool:
        if not self._connected or not self._bridge_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
                resp = await client.get(self._url("/is_connected"), headers=self._headers)
                data = resp.json()
                self._connected = data.get("connected", False)
                return self._connected
        except Exception:
            self._connected = False
            return False

    # ── Account ───────────────────────────────────────

    async def get_account_info(self) -> AccountInfo:
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
            resp = await client.get(self._url("/account"), headers=self._headers)
            resp.raise_for_status()
            d = resp.json()

        return AccountInfo(
            account_id=d["account_id"],
            broker="mt5",
            currency=d["currency"],
            balance=d["balance"],
            equity=d["equity"],
            unrealized_pnl=d["unrealized_pnl"],
            margin_used=d["margin_used"],
            margin_available=d["margin_available"],
            open_positions=0,
            open_orders=0,
        )

    # ── Positions ─────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
            resp = await client.get(self._url("/positions"), headers=self._headers)
            resp.raise_for_status()
            raw = resp.json()

        positions = []
        for p in raw:
            positions.append(Position(
                position_id=p["position_id"],
                symbol=p["symbol"],
                side=PositionSide.LONG if p["side"] == "LONG" else PositionSide.SHORT,
                size=p["size"],
                entry_price=p["entry_price"],
                current_price=p["current_price"],
                unrealized_pnl=p["unrealized_pnl"],
                margin_used=p.get("margin_used", 0),
                open_time=datetime.fromisoformat(p["open_time"]),
                stop_loss=p.get("stop_loss"),
                take_profit=p.get("take_profit"),
            ))
        return positions

    async def close_position(self, position_id: str, size: Optional[float] = None) -> Order:
        params = {"position_id": position_id}
        if size is not None:
            params["size"] = str(size)

        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
            resp = await client.post(
                self._url("/positions/close"),
                headers=self._headers,
                params=params,
            )
            resp.raise_for_status()
            d = resp.json()

        if not d.get("ok"):
            raise RuntimeError(f"MT5 close failed: {d.get('error')}")

        return Order(
            order_id=d["order_id"],
            symbol=d.get("symbol", ""),
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            size=d.get("volume", 0),
            filled_price=d.get("filled_price"),
            filled_time=datetime.now(timezone.utc),
            status=OrderStatus.FILLED,
            created_time=datetime.now(timezone.utc),
        )

    # ── Orders ────────────────────────────────────────

    async def place_order(self, request: OrderRequest) -> Order:
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
            resp = await client.post(
                self._url("/orders"),
                headers=self._headers,
                json={
                    "symbol": request.symbol,
                    "side": request.side.value,
                    "size": request.size,
                    "order_type": request.order_type.value,
                    "price": request.price,
                    "stop_loss": request.stop_loss,
                    "take_profit": request.take_profit,
                    "comment": request.comment or "flowrexalgo",
                },
            )
            resp.raise_for_status()
            d = resp.json()

        if not d.get("ok"):
            raise RuntimeError(f"MT5 order failed: {d.get('error')}")

        return Order(
            order_id=d["order_id"],
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            size=request.size,
            price=request.price,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            filled_price=d.get("filled_price"),
            filled_time=datetime.now(timezone.utc),
            status=OrderStatus.FILLED if request.order_type == OrderType.MARKET else OrderStatus.PENDING,
            created_time=datetime.now(timezone.utc),
        )

    async def modify_order(self, request: OrderModifyRequest) -> Order:
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
            resp = await client.put(
                self._url("/orders"),
                headers=self._headers,
                json={
                    "order_id": request.order_id,
                    "stop_loss": request.stop_loss,
                    "take_profit": request.take_profit,
                    "price": request.price,
                },
            )
            resp.raise_for_status()
            d = resp.json()

        if not d.get("ok"):
            raise RuntimeError(f"MT5 modify failed: {d.get('error')}")

        return Order(
            order_id=request.order_id,
            symbol=d.get("symbol", ""),
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=0,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            status=OrderStatus.PENDING,
        )

    async def cancel_order(self, order_id: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
                resp = await client.delete(
                    self._url(f"/orders/{order_id}"),
                    headers=self._headers,
                )
                resp.raise_for_status()
                d = resp.json()
            return d.get("ok", False)
        except Exception as e:
            logger.error("MT5 cancel order failed: %s", e)
            return False

    async def get_open_orders(self) -> list[Order]:
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
            resp = await client.get(self._url("/orders"), headers=self._headers)
            resp.raise_for_status()
            raw = resp.json()

        orders = []
        for o in raw:
            otype = {"MARKET": OrderType.MARKET, "LIMIT": OrderType.LIMIT, "STOP": OrderType.STOP}.get(
                o.get("order_type", "MARKET"), OrderType.MARKET
            )
            side = OrderSide.BUY if o.get("side") == "BUY" else OrderSide.SELL

            orders.append(Order(
                order_id=o["order_id"],
                symbol=o["symbol"],
                side=side,
                order_type=otype,
                size=o["size"],
                price=o.get("price"),
                stop_loss=o.get("stop_loss"),
                take_profit=o.get("take_profit"),
                status=OrderStatus.PENDING,
                created_time=datetime.fromisoformat(o["created_time"]) if o.get("created_time") else None,
            ))
        return orders

    # ── Market Data ───────────────────────────────────

    async def get_symbols(self) -> list[SymbolInfo]:
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
            resp = await client.get(self._url("/symbols"), headers=self._headers)
            resp.raise_for_status()
            raw = resp.json()

        symbols = []
        for s in raw:
            symbols.append(SymbolInfo(
                symbol=s["symbol"],
                display_name=s.get("display_name", s["symbol"]),
                base_currency=s.get("base_currency", ""),
                quote_currency=s.get("quote_currency", ""),
                pip_size=s.get("pip_size", 0.0001),
                min_lot=s.get("min_lot", 0.01),
                max_lot=s.get("max_lot", 100),
                lot_step=s.get("lot_step", 0.01),
                margin_rate=s.get("margin_rate", 0),
                tradeable=s.get("tradeable", True),
                asset_class=s.get("asset_class", "forex"),
            ))
        return symbols

    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        count: int = 100,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
    ) -> list[Candle]:
        body = {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": count,
        }
        if from_time:
            body["from_time"] = int(from_time.timestamp())

        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
            resp = await client.post(self._url("/candles"), headers=self._headers, json=body)
            resp.raise_for_status()
            raw = resp.json()

        candles = []
        for r in raw:
            candles.append(Candle(
                timestamp=datetime.fromtimestamp(r["time"], tz=timezone.utc),
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r["volume"],
            ))
        return candles

    async def get_price(self, symbol: str) -> PriceTick:
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
            resp = await client.get(self._url(f"/price/{symbol}"), headers=self._headers)
            resp.raise_for_status()
            d = resp.json()

        return PriceTick(
            symbol=d["symbol"],
            bid=d["bid"],
            ask=d["ask"],
            timestamp=datetime.fromisoformat(d["timestamp"]),
            spread=d.get("spread", 0),
        )

    # ── Initial bars for chart ─────────────────────────

    async def get_initial_bars(self, symbol: str, timeframe: str, count: int = 500) -> list[dict]:
        body = {"symbol": symbol, "timeframe": timeframe, "count": count}

        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
            resp = await client.post(self._url("/candles"), headers=self._headers, json=body)
            resp.raise_for_status()
            return resp.json()  # Already in {time, open, high, low, close, volume} format

    # ── Streaming ─────────────────────────────────────

    async def stream_prices(self, symbols: list[str]) -> AsyncGenerator[PriceTick, None]:
        """Poll bridge for ticks every second."""
        import asyncio
        while True:
            for sym in symbols:
                try:
                    tick = await self.get_price(sym)
                    yield tick
                except Exception:
                    pass
            await asyncio.sleep(1)
