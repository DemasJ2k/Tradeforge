"""
Tradovate REST + WebSocket Adapter.

Supports futures trading via the Tradovate API.
Authentication uses OAuth2 with device authorization or access token.

Docs: https://api.tradovate.com
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone, timedelta
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
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D1": 1440,
    "1m": 1, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "4h": 240, "1d": 1440,
}


class TradovateAdapter(BrokerAdapter):
    """
    Tradovate futures trading adapter.

    Uses REST API for account management, orders, and positions.
    Authenticates via the Tradovate OAuth2 access token flow.

    Args:
        username:    Tradovate username
        password:    Tradovate password
        app_id:      Application ID
        app_version: Application version
        cid:         Client ID (from Tradovate API application)
        sec:         Client secret
        demo:        Use demo environment
    """

    broker_name = "tradovate"

    _DEMO_URL = "https://demo.tradovateapi.com/v1"
    _LIVE_URL = "https://live.tradovateapi.com/v1"

    def __init__(
        self,
        username: str,
        password: str,
        app_id: str = "",
        app_version: str = "1.0",
        cid: str = "",
        sec: str = "",
        demo: bool = True,
    ):
        self._username = username
        self._password = password
        self._app_id = app_id
        self._app_version = app_version
        self._cid = cid
        self._sec = sec
        self._demo = demo
        self._base_url = self._DEMO_URL if demo else self._LIVE_URL
        self._client: Optional[httpx.AsyncClient] = None
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0
        self._connected = False
        self._account_id: Optional[int] = None
        self._account_spec: Optional[str] = None

    # ── Auth ──────────────────────────────────────────

    async def _authenticate(self) -> bool:
        """Get access token from Tradovate."""
        assert self._client

        body = {
            "name": self._username,
            "password": self._password,
            "appId": self._app_id,
            "appVersion": self._app_version,
            "cid": self._cid,
            "sec": self._sec,
        }

        try:
            r = await self._client.post(
                f"{self._base_url}/auth/accesstokenrequest",
                json=body,
            )
            r.raise_for_status()
            data = r.json()

            self._access_token = data.get("accessToken")
            # Token valid for ~24h typically
            expiry = data.get("expirationTime", "")
            if expiry:
                try:
                    exp_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                    self._token_expiry = exp_dt.timestamp()
                except ValueError:
                    self._token_expiry = time.time() + 86400
            else:
                self._token_expiry = time.time() + 86400

            return bool(self._access_token)

        except httpx.HTTPStatusError as e:
            logger.error("Tradovate auth HTTP %s: %s", e.response.status_code, e.response.text)
            return False
        except Exception as e:
            logger.error("Tradovate auth failed: %s (%s)", e, type(e).__name__)
            return False

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._access_token:
            h["Authorization"] = f"Bearer {self._access_token}"
        return h

    async def _ensure_auth(self):
        """Re-authenticate if token is about to expire."""
        if time.time() > self._token_expiry - 300:
            await self._authenticate()

    async def _get(self, path: str, params: dict | None = None) -> dict | list:
        assert self._client, "Not connected"
        await self._ensure_auth()
        r = await self._client.get(
            f"{self._base_url}{path}",
            params=params,
            headers=self._headers(),
        )
        r.raise_for_status()
        return r.json()

    async def _post(self, path: str, body: dict | None = None) -> dict | list:
        assert self._client, "Not connected"
        await self._ensure_auth()
        r = await self._client.post(
            f"{self._base_url}{path}",
            json=body or {},
            headers=self._headers(),
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

    # ── Connection ────────────────────────────────────

    async def connect(self) -> bool:
        self._client = httpx.AsyncClient(timeout=30.0)
        try:
            if not await self._authenticate():
                self._connected = False
                return False

            # Get account list
            accounts = await self._get("/account/list")
            if isinstance(accounts, list) and accounts:
                acct = accounts[0]
                self._account_id = acct.get("id")
                self._account_spec = acct.get("name", "")
                logger.info(
                    "Tradovate connected: account %s (%s)",
                    self._account_id, self._account_spec,
                )
                self._connected = True
                return True
            else:
                logger.error("Tradovate: no accounts found")
                self._connected = False
                return False

        except Exception as e:
            logger.error("Tradovate connect failed: %s (%s)", e, type(e).__name__)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False
        self._access_token = None

    async def is_connected(self) -> bool:
        if not self._connected or not self._client:
            return False
        try:
            await self._get("/account/list")
            return True
        except Exception:
            self._connected = False
            return False

    # ── Account ───────────────────────────────────────

    async def get_account_info(self) -> AccountInfo:
        accounts = await self._get("/account/list")
        if not isinstance(accounts, list) or not accounts:
            raise RuntimeError("No Tradovate accounts")

        acct = accounts[0]

        # Get cash balance
        cash_balances = await self._get("/cashBalance/list")
        balance = 0.0
        for cb in (cash_balances if isinstance(cash_balances, list) else []):
            if cb.get("accountId") == self._account_id:
                balance = float(cb.get("realizedPnl", 0)) + float(cb.get("cashBalance", 0))
                break

        # Count positions
        positions = await self._get("/position/list")
        open_pos = len([
            p for p in (positions if isinstance(positions, list) else [])
            if p.get("netPos", 0) != 0
        ])

        return AccountInfo(
            account_id=str(self._account_id or acct.get("id", "")),
            broker="tradovate",
            currency="USD",
            balance=balance,
            equity=balance,
            unrealized_pnl=0,
            margin_used=0,
            margin_available=balance,
            open_positions=open_pos,
            open_orders=0,
        )

    # ── Positions ─────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        raw = await self._get("/position/list")
        positions: list[Position] = []

        for p in (raw if isinstance(raw, list) else []):
            net = p.get("netPos", 0)
            if net == 0:
                continue

            contract_id = p.get("contractId")
            symbol = await self._get_contract_name(contract_id)

            price = float(p.get("netPrice", 0))

            positions.append(Position(
                position_id=str(p.get("id", "")),
                symbol=symbol,
                side=PositionSide.LONG if net > 0 else PositionSide.SHORT,
                size=abs(net),
                entry_price=price,
                current_price=price,
                unrealized_pnl=float(p.get("openPnl", 0)),
                margin_used=0,
                open_time=self._parse_ts(p.get("timestamp", "")),
            ))

        return positions

    async def _get_contract_name(self, contract_id: int | None) -> str:
        """Resolve contract ID to symbol name."""
        if not contract_id:
            return "UNKNOWN"
        try:
            contract = await self._get(f"/contract/item?id={contract_id}")
            if isinstance(contract, dict):
                return contract.get("name", f"contract_{contract_id}")
        except Exception:
            pass
        return f"contract_{contract_id}"

    async def close_position(self, position_id: str, size: Optional[float] = None) -> Order:
        positions = await self.get_positions()
        pos = next((p for p in positions if p.position_id == position_id), None)
        if not pos:
            raise ValueError(f"Position {position_id} not found")

        close_side = OrderSide.SELL if pos.side == PositionSide.LONG else OrderSide.BUY
        close_size = size or pos.size

        req = OrderRequest(
            symbol=pos.symbol,
            side=close_side,
            size=close_size,
            order_type=OrderType.MARKET,
        )
        return await self.place_order(req)

    # ── Orders ────────────────────────────────────────

    async def place_order(self, request: OrderRequest) -> Order:
        # Resolve contract
        contract = await self._resolve_contract(request.symbol)
        if not contract:
            raise ValueError(f"Contract not found for {request.symbol}")

        body: dict = {
            "accountSpec": self._account_spec,
            "accountId": self._account_id,
            "action": "Buy" if request.side == OrderSide.BUY else "Sell",
            "symbol": request.symbol,
            "orderQty": int(request.size),
            "isAutomated": True,
        }

        if request.order_type == OrderType.MARKET:
            body["orderType"] = "Market"
        elif request.order_type == OrderType.LIMIT:
            body["orderType"] = "Limit"
            body["price"] = request.price
        elif request.order_type == OrderType.STOP:
            body["orderType"] = "Stop"
            body["stopPrice"] = request.price

        endpoint = "/order/placeorder"
        data = await self._post(endpoint, body)

        order_id = str(data.get("orderId", ""))

        return Order(
            order_id=order_id,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            size=request.size,
            price=request.price,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            status=OrderStatus.PENDING,
            created_time=datetime.now(timezone.utc),
        )

    async def _resolve_contract(self, symbol: str) -> dict | None:
        """Resolve a symbol name to a Tradovate contract."""
        try:
            data = await self._get("/contract/find", params={"name": symbol})
            if isinstance(data, dict) and data.get("id"):
                return data
        except Exception:
            pass

        # Try contract/suggest
        try:
            data = await self._get("/contract/suggest", params={"t": symbol, "l": 1})
            if isinstance(data, list) and data:
                return data[0]
        except Exception:
            pass

        return None

    async def modify_order(self, request: OrderModifyRequest) -> Order:
        body = {
            "orderId": int(request.order_id),
            "orderQty": 0,
            "orderType": "Limit",
        }
        if request.price:
            body["price"] = request.price

        try:
            data = await self._post("/order/modifyorder", body)
        except Exception as e:
            logger.error("Tradovate modify failed: %s", e)
            raise

        return Order(
            order_id=request.order_id,
            symbol="",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=0,
            price=request.price,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            status=OrderStatus.PENDING,
        )

    async def cancel_order(self, order_id: str) -> bool:
        try:
            await self._post("/order/cancelorder", {"orderId": int(order_id)})
            return True
        except Exception as e:
            logger.error("Tradovate cancel failed: %s", e)
            return False

    async def get_open_orders(self) -> list[Order]:
        raw = await self._get("/order/list")
        orders: list[Order] = []

        for o in (raw if isinstance(raw, list) else []):
            status = o.get("ordStatus", "")
            if status not in ("Working", "Accepted"):
                continue

            side = OrderSide.BUY if o.get("action") == "Buy" else OrderSide.SELL

            otype_str = o.get("orderType", "Market")
            if otype_str == "Limit":
                otype = OrderType.LIMIT
            elif otype_str == "Stop":
                otype = OrderType.STOP
            else:
                otype = OrderType.MARKET

            orders.append(Order(
                order_id=str(o.get("id", "")),
                symbol=o.get("contractId", ""),
                side=side,
                order_type=otype,
                size=float(o.get("orderQty", 0)),
                price=o.get("price"),
                status=OrderStatus.PENDING,
                created_time=self._parse_ts(o.get("timestamp", "")),
            ))

        return orders

    # ── Market Data ───────────────────────────────────

    async def get_symbols(self) -> list[SymbolInfo]:
        # Tradovate uses "product" for contract specifications
        products = await self._get("/product/list")
        symbols: list[SymbolInfo] = []

        for p in (products if isinstance(products, list) else []):
            if p.get("status") != "Verified":
                continue

            tick_size = float(p.get("tickSize", 0.01))

            symbols.append(SymbolInfo(
                symbol=p.get("name", ""),
                display_name=p.get("description", p.get("name", "")),
                base_currency=p.get("currencyId", "USD"),
                quote_currency="USD",
                pip_size=tick_size,
                min_lot=1.0,
                max_lot=10000.0,
                lot_step=1.0,
                margin_rate=0,
                tradeable=True,
                asset_class="futures",
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
        # Tradovate market data is via a separate MD endpoint
        # For now, use the REST replay/bars endpoint
        minutes = _TF_MAP.get(timeframe, 60)

        params: dict = {
            "symbol": symbol,
            "chartDescription": json.dumps({
                "underlyingType": "MinuteBar",
                "elementSize": minutes,
                "elementSizeUnit": "UnderlyingUnits",
                "withHistogram": False,
            }),
            "timeRange": json.dumps({
                "asFarAsTimestamp": (
                    from_time or (datetime.now(timezone.utc) - timedelta(days=30))
                ).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "closestTimestamp": (
                    to_time or datetime.now(timezone.utc)
                ).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            }),
        }

        try:
            data = await self._get("/md/getchart", params=params)
        except Exception:
            # Market data endpoint may require separate subscription
            return []

        candles: list[Candle] = []
        bars = data.get("bars", []) if isinstance(data, dict) else []

        for bar in bars[-count:]:
            candles.append(Candle(
                timestamp=self._parse_ts(bar.get("timestamp", "")),
                open=float(bar.get("open", 0)),
                high=float(bar.get("high", 0)),
                low=float(bar.get("low", 0)),
                close=float(bar.get("close", 0)),
                volume=float(bar.get("upVolume", 0) + bar.get("downVolume", 0)),
            ))

        return candles

    async def get_price(self, symbol: str) -> PriceTick:
        # Use quote endpoint
        try:
            contract = await self._resolve_contract(symbol)
            if not contract:
                raise ValueError(f"Contract not found: {symbol}")

            contract_id = contract.get("id")
            data = await self._get(f"/md/getquote?id={contract_id}")

            if isinstance(data, dict):
                entries = data.get("entries", {})
                bid_entry = entries.get("Bid", {})
                ask_entry = entries.get("Offer", {})
                bid = float(bid_entry.get("price", 0))
                ask = float(ask_entry.get("price", 0))
            else:
                bid = ask = 0

        except Exception:
            bid = ask = 0

        return PriceTick(
            symbol=symbol,
            bid=bid,
            ask=ask,
            timestamp=datetime.now(timezone.utc),
            spread=ask - bid if ask and bid else 0,
        )

    # ── Streaming ─────────────────────────────────────

    async def stream_prices(self, symbols: list[str]) -> AsyncGenerator[PriceTick, None]:
        """Poll Tradovate quotes every 2 seconds as fallback."""
        while True:
            for sym in symbols:
                try:
                    tick = await self.get_price(sym)
                    yield tick
                except Exception:
                    pass
            await asyncio.sleep(2)
