"""
Coinbase Advanced Trade API adapter.

Uses CDP (Cloud Developer Platform) API keys with JWT/ES256 authentication.
Supports crypto spot trading pairs.

CDP keys format:
  api_key:    "organizations/{org_id}/apiKeys/{key_id}"
  api_secret: EC private key in PEM format
"""

import json
import logging
import secrets
import time
import uuid
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

# ── Timeframe mapping ─────────────────────────────────
_TF_MAP = {
    "M1": "ONE_MINUTE", "M5": "FIVE_MINUTE", "M15": "FIFTEEN_MINUTE",
    "M30": "THIRTY_MINUTE", "H1": "ONE_HOUR", "H2": "TWO_HOUR",
    "H4": "SIX_HOUR", "D1": "ONE_DAY",
    "1m": "ONE_MINUTE", "5m": "FIVE_MINUTE", "15m": "FIFTEEN_MINUTE",
    "30m": "THIRTY_MINUTE", "1h": "ONE_HOUR", "4h": "SIX_HOUR",
    "1d": "ONE_DAY",
}


def _build_jwt(api_key: str, api_secret: str, uri: str = "") -> str:
    """Build a JWT token for Coinbase CDP API authentication."""
    import jwt as pyjwt
    from cryptography.hazmat.primitives import serialization

    # Normalize PEM key: Coinbase JSON files use literal \n escape sequences
    # and users may paste with extra whitespace or missing newlines
    secret = api_secret.replace("\\n", "\n").strip()
    if not secret.endswith("\n"):
        secret += "\n"

    private_key_bytes = secret.encode("utf-8")
    private_key = serialization.load_pem_private_key(private_key_bytes, password=None)

    now = int(time.time())
    claims = {
        "sub": api_key,
        "iss": "cdp",
        "nbf": now,
        "exp": now + 120,
    }
    if uri:
        claims["uri"] = uri

    token = pyjwt.encode(
        claims,
        private_key,
        algorithm="ES256",
        headers={"kid": api_key, "nonce": secrets.token_hex()},
    )
    return token


class CoinbaseAdapter(BrokerAdapter):
    """
    Coinbase Advanced Trade API adapter using CDP JWT authentication.

    Args:
        api_key:    CDP API key (format: "organizations/{org_id}/apiKeys/{key_id}")
        api_secret: CDP API secret (EC private key in PEM format)
    """

    broker_name = "coinbase"

    _BASE_URL = "https://api.coinbase.com"

    def __init__(self, api_key: str, api_secret: str):
        self._api_key = api_key
        self._api_secret = api_secret
        self._client: Optional[httpx.AsyncClient] = None
        self._connected = False
        self._last_error: str = ""

    # ── Auth helpers ───────────────────────────────────

    def _auth_headers(self, method: str, path: str) -> dict:
        """Build JWT auth headers for a Coinbase API request."""
        # Coinbase CDP JWT spec requires URI without protocol: "GET api.coinbase.com/path"
        host = self._BASE_URL.replace("https://", "").replace("http://", "")
        uri = f"{method.upper()} {host}{path}"
        token = _build_jwt(self._api_key, self._api_secret, uri)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _get(self, path: str, params: dict | None = None) -> dict:
        assert self._client, "Not connected"
        headers = self._auth_headers("GET", path)
        r = await self._client.get(
            f"{self._BASE_URL}{path}",
            params=params,
            headers=headers,
        )
        r.raise_for_status()
        return r.json()

    async def _post(self, path: str, body: dict) -> dict:
        assert self._client, "Not connected"
        body_str = json.dumps(body)
        headers = self._auth_headers("POST", path)
        r = await self._client.post(
            f"{self._BASE_URL}{path}",
            content=body_str,
            headers=headers,
        )
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _parse_ts(ts_str: str) -> datetime:
        if ts_str:
            try:
                return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                pass
        return datetime.now(timezone.utc)

    # ── Connection ─────────────────────────────────────

    async def connect(self) -> bool:
        self._last_error = ""
        self._client = httpx.AsyncClient(timeout=30.0)
        logger.info("Coinbase connecting with API key %s...", self._api_key[:8] if len(self._api_key) > 8 else "***")
        try:
            data = await self._get("/api/v3/brokerage/accounts")
            self._connected = True
            logger.info("Coinbase connected: %d accounts", len(data.get("accounts", [])))
            return True
        except httpx.HTTPStatusError as e:
            body = e.response.text[:500]
            self._last_error = f"HTTP {e.response.status_code}: {body}"
            logger.error("Coinbase connect HTTP %s: %s", e.response.status_code, body)
            self._connected = False
            return False
        except Exception as e:
            self._last_error = f"{type(e).__name__}: {str(e)}"
            logger.error("Coinbase connect failed: %s (%s)", e, type(e).__name__)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False

    async def is_connected(self) -> bool:
        if not self._connected or not self._client:
            return False
        try:
            await self._get("/api/v3/brokerage/accounts")
            return True
        except Exception:
            self._connected = False
            return False

    # ── Account ────────────────────────────────────────

    async def get_account_info(self) -> AccountInfo:
        data = await self._get("/api/v3/brokerage/accounts")
        accounts = data.get("accounts", [])

        # Sum up balances across all crypto accounts
        total_balance = 0.0
        for acct in accounts:
            bal = acct.get("available_balance", {})
            total_balance += float(bal.get("value", 0))

        return AccountInfo(
            account_id="coinbase_all",
            broker="coinbase",
            currency="USD",
            balance=total_balance,
            equity=total_balance,
            unrealized_pnl=0,
            margin_used=0,
            margin_available=total_balance,
            open_positions=len([a for a in accounts if float(a.get("available_balance", {}).get("value", 0)) > 0.01]),
            open_orders=0,
        )

    # ── Positions ──────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        data = await self._get("/api/v3/brokerage/accounts")
        positions: list[Position] = []

        for acct in data.get("accounts", []):
            bal = acct.get("available_balance", {})
            amount = float(bal.get("value", 0))
            currency = bal.get("currency", "")

            if amount < 0.01 or currency == "USD":
                continue

            # Try to get current price
            product_id = f"{currency}-USD"
            try:
                ticker = await self._get(f"/api/v3/brokerage/products/{product_id}")
                price = float(ticker.get("price", 0))
            except Exception:
                price = 0

            positions.append(Position(
                position_id=acct.get("uuid", currency),
                symbol=product_id,
                side=PositionSide.LONG,
                size=amount,
                entry_price=0,
                current_price=price,
                unrealized_pnl=0,
                margin_used=0,
                open_time=datetime.now(timezone.utc),
            ))

        return positions

    async def close_position(self, position_id: str, size: Optional[float] = None) -> Order:
        # For crypto, "closing" means selling the holding
        # We need to figure out what to sell
        positions = await self.get_positions()
        pos = next((p for p in positions if p.position_id == position_id), None)
        if not pos:
            raise ValueError(f"Position {position_id} not found")

        sell_size = size or pos.size
        req = OrderRequest(
            symbol=pos.symbol,
            side=OrderSide.SELL,
            size=sell_size,
            order_type=OrderType.MARKET,
        )
        return await self.place_order(req)

    # ── Orders ─────────────────────────────────────────

    async def place_order(self, request: OrderRequest) -> Order:
        product_id = request.symbol.replace("/", "-")
        client_order_id = str(uuid.uuid4())

        order_config: dict = {}
        if request.order_type == OrderType.MARKET:
            if request.side == OrderSide.BUY:
                order_config["market_market_ioc"] = {
                    "quote_size": str(request.size),
                }
            else:
                order_config["market_market_ioc"] = {
                    "base_size": str(request.size),
                }
        elif request.order_type == OrderType.LIMIT:
            order_config["limit_limit_gtc"] = {
                "base_size": str(request.size),
                "limit_price": str(request.price),
            }
        elif request.order_type == OrderType.STOP:
            order_config["stop_limit_stop_limit_gtc"] = {
                "base_size": str(request.size),
                "limit_price": str(request.price),
                "stop_price": str(request.price),
            }

        body = {
            "client_order_id": client_order_id,
            "product_id": product_id,
            "side": request.side.value,
            "order_configuration": order_config,
        }

        data = await self._post("/api/v3/brokerage/orders", body)

        success_resp = data.get("success_response", {})
        order_id = success_resp.get("order_id", client_order_id)

        return Order(
            order_id=order_id,
            symbol=product_id,
            side=request.side,
            order_type=request.order_type,
            size=request.size,
            price=request.price,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            status=OrderStatus.FILLED if data.get("success") else OrderStatus.PENDING,
            created_time=datetime.now(timezone.utc),
        )

    async def modify_order(self, request: OrderModifyRequest) -> Order:
        # Coinbase doesn't support order modification — cancel and replace
        await self.cancel_order(request.order_id)
        return Order(
            order_id=request.order_id,
            symbol="",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=0,
            status=OrderStatus.CANCELLED,
        )

    async def cancel_order(self, order_id: str) -> bool:
        try:
            data = await self._post(
                "/api/v3/brokerage/orders/batch_cancel",
                {"order_ids": [order_id]},
            )
            results = data.get("results", [])
            return len(results) > 0 and results[0].get("success", False)
        except Exception as e:
            logger.error("Coinbase cancel order failed: %s", e)
            return False

    async def get_open_orders(self) -> list[Order]:
        data = await self._get(
            "/api/v3/brokerage/orders/historical/batch",
            params={"order_status": "OPEN"},
        )
        orders: list[Order] = []

        for o in data.get("orders", []):
            side = OrderSide.BUY if o.get("side") == "BUY" else OrderSide.SELL

            config = o.get("order_configuration", {})
            otype = OrderType.MARKET
            price = None
            size = 0.0

            if "limit_limit_gtc" in config:
                otype = OrderType.LIMIT
                cfg = config["limit_limit_gtc"]
                price = float(cfg.get("limit_price", 0))
                size = float(cfg.get("base_size", 0))
            elif "market_market_ioc" in config:
                cfg = config["market_market_ioc"]
                size = float(cfg.get("base_size", 0) or cfg.get("quote_size", 0))

            orders.append(Order(
                order_id=o.get("order_id", ""),
                symbol=o.get("product_id", ""),
                side=side,
                order_type=otype,
                size=size,
                price=price,
                status=OrderStatus.PENDING,
                created_time=self._parse_ts(o.get("created_time", "")),
            ))

        return orders

    # ── Market Data ────────────────────────────────────

    async def get_symbols(self) -> list[SymbolInfo]:
        data = await self._get("/api/v3/brokerage/products")
        symbols: list[SymbolInfo] = []

        for p in data.get("products", []):
            if p.get("status") != "online":
                continue

            symbols.append(SymbolInfo(
                symbol=p.get("product_id", ""),
                display_name=p.get("product_id", "").replace("-", "/"),
                base_currency=p.get("base_currency_id", ""),
                quote_currency=p.get("quote_currency_id", ""),
                pip_size=float(p.get("quote_increment", "0.01")),
                min_lot=float(p.get("base_min_size", "0.001")),
                max_lot=float(p.get("base_max_size", "1000000")),
                lot_step=float(p.get("base_increment", "0.001")),
                margin_rate=0,
                tradeable=not p.get("trading_disabled", False),
                asset_class="crypto",
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
        product_id = symbol.replace("/", "-")
        granularity = _TF_MAP.get(timeframe, "ONE_HOUR")

        params: dict = {"granularity": granularity}
        if from_time:
            params["start"] = str(int(from_time.timestamp()))
        if to_time:
            params["end"] = str(int(to_time.timestamp()))

        if not from_time and not to_time:
            now = int(time.time())
            # Estimate bar width in seconds
            bar_seconds = {
                "ONE_MINUTE": 60, "FIVE_MINUTE": 300, "FIFTEEN_MINUTE": 900,
                "THIRTY_MINUTE": 1800, "ONE_HOUR": 3600, "TWO_HOUR": 7200,
                "SIX_HOUR": 21600, "ONE_DAY": 86400,
            }.get(granularity, 3600)
            params["start"] = str(now - (count * bar_seconds))
            params["end"] = str(now)

        data = await self._get(
            f"/api/v3/brokerage/products/{product_id}/candles",
            params=params,
        )

        candles: list[Candle] = []
        for c in data.get("candles", []):
            candles.append(Candle(
                timestamp=datetime.fromtimestamp(int(c.get("start", 0)), tz=timezone.utc),
                open=float(c.get("open", 0)),
                high=float(c.get("high", 0)),
                low=float(c.get("low", 0)),
                close=float(c.get("close", 0)),
                volume=float(c.get("volume", 0)),
            ))

        # Coinbase returns newest first — reverse for chronological order
        candles.reverse()
        return candles

    async def get_price(self, symbol: str) -> PriceTick:
        product_id = symbol.replace("/", "-")
        data = await self._get(f"/api/v3/brokerage/products/{product_id}")

        price = float(data.get("price", 0))
        bid = float(data.get("bid", price))
        ask = float(data.get("ask", price))

        return PriceTick(
            symbol=product_id,
            bid=bid,
            ask=ask,
            timestamp=datetime.now(timezone.utc),
            spread=ask - bid,
        )

    # ── Streaming ──────────────────────────────────────

    async def stream_prices(self, symbols: list[str]) -> AsyncGenerator[PriceTick, None]:
        """
        Coinbase WebSocket streaming is complex (requires JWT auth for advanced).
        For now, we poll every 2 seconds as a fallback.
        """
        import asyncio

        product_ids = [s.replace("/", "-") for s in symbols]

        while True:
            for pid in product_ids:
                try:
                    tick = await self.get_price(pid)
                    yield tick
                except Exception:
                    pass
            await asyncio.sleep(2)
