"""
Oanda broker adapter — REST API v20 + streaming prices.

Uses the httpx library for async HTTP.  No third-party Oanda SDK required.
"""

import asyncio
import json
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


# ── Timeframe mapping ─────────────────────────────────

_TF_MAP = {
    "M1": "M1", "M5": "M5", "M15": "M15", "M30": "M30",
    "H1": "H1", "H4": "H4", "D1": "D", "W1": "W", "MN": "M",
    # aliases
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1h": "H1", "4h": "H4", "1d": "D", "1w": "W",
}

# Common symbol aliases → Oanda instrument format
_SYMBOL_ALIASES: dict[str, str] = {
    "XAUUSD": "XAU_USD", "XAGUSD": "XAG_USD",
    "US30": "US30_USD", "NAS100": "NAS100_USD",
    "SPX500": "SPX500_USD", "UK100": "UK100_GBP",
    "JP225": "JP225_USD", "DE30": "DE30_EUR",
    "USOIL": "WTICO_USD", "UKOIL": "BCO_USD",
}


def _to_oanda_instrument(symbol: str) -> str:
    """Convert any common symbol format to Oanda instrument name."""
    if symbol in _SYMBOL_ALIASES:
        return _SYMBOL_ALIASES[symbol]
    if "_" in symbol:
        return symbol  # already Oanda format
    if "/" in symbol:
        return symbol.replace("/", "_")
    # 6-char forex pairs: EURUSD → EUR_USD
    if len(symbol) == 6 and symbol.isalpha():
        return f"{symbol[:3]}_{symbol[3:]}"
    return symbol


class OandaAdapter(BrokerAdapter):
    """
    Oanda v20 REST adapter.

    Args:
        api_key:    Oanda personal access token
        account_id: Oanda account ID  (e.g. "101-011-12345678-001")
        practice:   True → practice endpoint, False → live
    """

    broker_name = "oanda"

    # Oanda REST endpoints
    _PRACTICE_URL = "https://api-fxpractice.oanda.com"
    _LIVE_URL     = "https://api-fxtrade.oanda.com"
    _PRACTICE_STREAM = "https://stream-fxpractice.oanda.com"
    _LIVE_STREAM     = "https://stream-fxtrade.oanda.com"

    def __init__(
        self,
        api_key: str,
        account_id: str,
        practice: bool = True,
    ):
        self._api_key = api_key
        self._account_id = account_id
        self._practice = practice
        self._base_url = self._PRACTICE_URL if practice else self._LIVE_URL
        self._stream_url = self._PRACTICE_STREAM if practice else self._LIVE_STREAM
        self._client: Optional[httpx.AsyncClient] = None
        self._connected = False
        self._last_error: str = ""

    # ── helpers ────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept-Datetime-Format": "RFC3339",
        }

    async def _get(self, path: str, params: dict | None = None) -> dict:
        assert self._client, "Not connected"
        r = await self._client.get(
            f"{self._base_url}/v3{path}",
            params=params,
            headers=self._headers(),
        )
        r.raise_for_status()
        return r.json()

    async def _post(self, path: str, body: dict) -> dict:
        assert self._client, "Not connected"
        r = await self._client.post(
            f"{self._base_url}/v3{path}",
            json=body,
            headers=self._headers(),
        )
        r.raise_for_status()
        return r.json()

    async def _put(self, path: str, body: dict) -> dict:
        assert self._client, "Not connected"
        r = await self._client.put(
            f"{self._base_url}/v3{path}",
            json=body,
            headers=self._headers(),
        )
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _parse_ts(ts_str: str) -> datetime:
        """Parse Oanda RFC3339 timestamp."""
        if ts_str:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return datetime.now(timezone.utc)

    # ── Connection ─────────────────────────────────────

    async def connect(self) -> bool:
        self._last_error = ""
        self._client = httpx.AsyncClient(timeout=30.0)
        env = "practice" if self._practice else "live"
        logger.info("Oanda connecting to %s (%s), account %s", self._base_url, env, self._account_id)
        try:
            data = await self._get(f"/accounts/{self._account_id}/summary")
            self._connected = True
            logger.info("Oanda connected: account %s (%s)", self._account_id, env)
            return True
        except httpx.HTTPStatusError as e:
            body = e.response.text[:500]
            self._last_error = f"HTTP {e.response.status_code} from {env} API: {body}"
            logger.error("Oanda connect HTTP %s (%s): %s", e.response.status_code, env, body)
            self._connected = False
            return False
        except Exception as e:
            self._last_error = f"{type(e).__name__}: {str(e)}"
            logger.error("Oanda connect failed: %s (%s)", e, type(e).__name__)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False
        logger.info("Oanda disconnected")

    async def is_connected(self) -> bool:
        if not self._connected or not self._client:
            return False
        try:
            await self._get(f"/accounts/{self._account_id}/summary")
            return True
        except Exception:
            self._connected = False
            return False

    # ── Account ────────────────────────────────────────

    async def get_account_info(self) -> AccountInfo:
        data = await self._get(f"/accounts/{self._account_id}/summary")
        acct = data["account"]
        return AccountInfo(
            account_id=self._account_id,
            broker="oanda",
            currency=acct.get("currency", "USD"),
            balance=float(acct.get("balance", 0)),
            equity=float(acct.get("NAV", 0)),
            unrealized_pnl=float(acct.get("unrealizedPL", 0)),
            margin_used=float(acct.get("marginUsed", 0)),
            margin_available=float(acct.get("marginAvailable", 0)),
            open_positions=int(acct.get("openPositionCount", 0)),
            open_orders=int(acct.get("pendingOrderCount", 0)),
        )

    # ── Positions ──────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        data = await self._get(f"/accounts/{self._account_id}/openPositions")
        positions: list[Position] = []

        for pos in data.get("positions", []):
            long_units = float(pos.get("long", {}).get("units", 0))
            short_units = float(pos.get("short", {}).get("units", 0))

            if long_units > 0:
                side_data = pos["long"]
                side = PositionSide.LONG
                size = long_units
            elif short_units < 0:
                side_data = pos["short"]
                side = PositionSide.SHORT
                size = abs(short_units)
            else:
                continue

            avg_price = float(side_data.get("averagePrice", 0))
            unrealized = float(side_data.get("unrealizedPL", 0))

            # get current price from pricing endpoint
            try:
                price_data = await self._get(
                    f"/accounts/{self._account_id}/pricing",
                    params={"instruments": pos["instrument"]},
                )
                prices = price_data.get("prices", [{}])
                current_bid = float(prices[0].get("bids", [{"price": 0}])[0]["price"])
                current_ask = float(prices[0].get("asks", [{"price": 0}])[0]["price"])
                current_price = (current_bid + current_ask) / 2
            except Exception:
                current_price = avg_price

            # extract SL/TP if set
            sl = None
            tp = None
            if "stopLossOrder" in side_data:
                sl = float(side_data["stopLossOrder"].get("price", 0))
            if "takeProfitOrder" in side_data:
                tp = float(side_data["takeProfitOrder"].get("price", 0))

            positions.append(Position(
                position_id=f"{pos['instrument']}_{side.value}",
                symbol=pos["instrument"],
                side=side,
                size=size,
                entry_price=avg_price,
                current_price=current_price,
                unrealized_pnl=unrealized,
                margin_used=0,
                open_time=datetime.now(timezone.utc),
                stop_loss=sl,
                take_profit=tp,
            ))

        return positions

    async def close_position(self, position_id: str, size: Optional[float] = None) -> Order:
        # position_id is "{instrument}_{LONG|SHORT}"
        parts = position_id.rsplit("_", 1)
        instrument = parts[0]
        side = parts[1] if len(parts) > 1 else "LONG"

        body: dict = {}
        if side == "LONG":
            body["longUnits"] = str(int(size)) if size else "ALL"
        else:
            body["shortUnits"] = str(int(size)) if size else "ALL"

        data = await self._put(
            f"/accounts/{self._account_id}/positions/{instrument}/close",
            body,
        )

        # parse response
        related = data.get("longOrderFillTransaction") or data.get("shortOrderFillTransaction", {})
        return Order(
            order_id=str(related.get("id", "0")),
            symbol=instrument,
            side=OrderSide.SELL if side == "LONG" else OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=float(related.get("units", 0)),
            status=OrderStatus.FILLED,
            filled_price=float(related.get("price", 0)),
            filled_time=self._parse_ts(related.get("time", "")),
        )

    # ── Orders ─────────────────────────────────────────

    async def place_order(self, request: OrderRequest) -> Order:
        oanda_instrument = _to_oanda_instrument(request.symbol)

        # Units: positive = buy, negative = sell
        units = request.size if request.side == OrderSide.BUY else -request.size

        order_body: dict = {
            "type": request.order_type.value,
            "instrument": oanda_instrument,
            "units": str(int(units)) if units == int(units) else str(units),
            "timeInForce": "FOK" if request.order_type == OrderType.MARKET else "GTC",
        }

        # Price for limit / stop
        if request.price and request.order_type != OrderType.MARKET:
            order_body["price"] = str(request.price)

        # SL / TP
        if request.stop_loss:
            order_body["stopLossOnFill"] = {"price": str(request.stop_loss)}
        if request.take_profit:
            order_body["takeProfitOnFill"] = {"price": str(request.take_profit)}
        if request.trailing_stop_distance:
            order_body["trailingStopLossOnFill"] = {"distance": str(request.trailing_stop_distance)}

        data = await self._post(
            f"/accounts/{self._account_id}/orders",
            {"order": order_body},
        )

        # Market orders fill immediately
        fill_tx = data.get("orderFillTransaction", {})
        create_tx = data.get("orderCreateTransaction", {})
        tx = fill_tx or create_tx

        status = OrderStatus.FILLED if fill_tx else OrderStatus.PENDING

        return Order(
            order_id=str(tx.get("id", data.get("orderCreateTransaction", {}).get("id", "0"))),
            symbol=oanda_instrument,
            side=request.side,
            order_type=request.order_type,
            size=abs(float(tx.get("units", request.size))),
            price=request.price,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            status=status,
            filled_price=float(fill_tx.get("price", 0)) if fill_tx else None,
            filled_time=self._parse_ts(fill_tx.get("time", "")) if fill_tx else None,
            created_time=self._parse_ts(tx.get("time", "")),
        )

    async def modify_order(self, request: OrderModifyRequest) -> Order:
        # Try modifying as a trade (position) SL/TP first
        body: dict = {}
        if request.stop_loss is not None:
            body["stopLoss"] = {"price": str(request.stop_loss)}
        if request.take_profit is not None:
            body["takeProfit"] = {"price": str(request.take_profit)}
        if request.trailing_stop_distance is not None:
            body["trailingStopLoss"] = {"distance": str(request.trailing_stop_distance)}

        try:
            # Try as trade modification
            data = await self._put(
                f"/accounts/{self._account_id}/trades/{request.order_id}/orders",
                body,
            )
            return Order(
                order_id=request.order_id,
                symbol="",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                size=0,
                stop_loss=request.stop_loss,
                take_profit=request.take_profit,
                status=OrderStatus.PENDING,
            )
        except httpx.HTTPStatusError:
            # Try as pending order modification
            order_body: dict = {}
            if request.price is not None:
                order_body["price"] = str(request.price)
            if request.stop_loss is not None:
                order_body["stopLossOnFill"] = {"price": str(request.stop_loss)}
            if request.take_profit is not None:
                order_body["takeProfitOnFill"] = {"price": str(request.take_profit)}

            data = await self._put(
                f"/accounts/{self._account_id}/orders/{request.order_id}",
                {"order": order_body},
            )

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
            await self._put(
                f"/accounts/{self._account_id}/orders/{order_id}/cancel",
                {},
            )
            return True
        except Exception as e:
            logger.error("Cancel order %s failed: %s", order_id, e)
            return False

    async def get_open_orders(self) -> list[Order]:
        data = await self._get(f"/accounts/{self._account_id}/pendingOrders")
        orders: list[Order] = []

        for o in data.get("orders", []):
            side = OrderSide.BUY if float(o.get("units", 0)) > 0 else OrderSide.SELL

            otype_str = o.get("type", "MARKET").upper()
            otype_map = {
                "MARKET": OrderType.MARKET,
                "LIMIT": OrderType.LIMIT,
                "STOP": OrderType.STOP,
                "MARKET_IF_TOUCHED": OrderType.LIMIT,
            }
            otype = otype_map.get(otype_str, OrderType.MARKET)

            sl = None
            tp = None
            if "stopLossOnFill" in o:
                sl = float(o["stopLossOnFill"].get("price", 0))
            if "takeProfitOnFill" in o:
                tp = float(o["takeProfitOnFill"].get("price", 0))

            orders.append(Order(
                order_id=o.get("id", ""),
                symbol=o.get("instrument", ""),
                side=side,
                order_type=otype,
                size=abs(float(o.get("units", 0))),
                price=float(o.get("price", 0)) if "price" in o else None,
                stop_loss=sl,
                take_profit=tp,
                status=OrderStatus.PENDING,
                created_time=self._parse_ts(o.get("createTime", "")),
            ))

        return orders

    # ── Market Data ────────────────────────────────────

    async def get_symbols(self) -> list[SymbolInfo]:
        data = await self._get(f"/accounts/{self._account_id}/instruments")
        symbols: list[SymbolInfo] = []

        for inst in data.get("instruments", []):
            pip_loc = int(inst.get("pipLocation", -4))
            pip_size = 10 ** pip_loc

            # Determine asset class from instrument type
            inst_type = inst.get("type", "CURRENCY")
            asset_class_map = {
                "CURRENCY": "forex",
                "CFD": "cfd",
                "METAL": "commodity",
            }

            # Parse currency pair
            name = inst.get("name", "")
            parts = name.split("_")
            base = parts[0] if len(parts) > 1 else name
            quote = parts[1] if len(parts) > 1 else "USD"

            symbols.append(SymbolInfo(
                symbol=name,
                display_name=inst.get("displayName", name),
                base_currency=base,
                quote_currency=quote,
                pip_size=pip_size,
                min_lot=float(inst.get("minimumTradeSize", 1)),
                max_lot=float(inst.get("maximumOrderUnits", 100000000)),
                lot_step=1.0,
                margin_rate=float(inst.get("marginRate", 0.05)),
                tradeable=inst.get("type", "") != "DISABLED",
                asset_class=asset_class_map.get(inst.get("type", ""), "other"),
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
        instrument = _to_oanda_instrument(symbol)
        gran = _TF_MAP.get(timeframe, timeframe)

        params: dict = {
            "granularity": gran,
            "count": min(count, 5000),
            "price": "M",
        }
        if from_time:
            params["from"] = from_time.isoformat()
            params.pop("count", None)
        if to_time:
            params["to"] = to_time.isoformat()

        data = await self._get(
            f"/instruments/{instrument}/candles",
            params=params,
        )

        candles: list[Candle] = []
        for c in data.get("candles", []):
            if not c.get("complete", True) and len(data.get("candles", [])) > 1:
                continue  # skip incomplete candle unless it's the only one
            mid = c.get("mid", {})
            candles.append(Candle(
                timestamp=self._parse_ts(c.get("time", "")),
                open=float(mid.get("o", 0)),
                high=float(mid.get("h", 0)),
                low=float(mid.get("l", 0)),
                close=float(mid.get("c", 0)),
                volume=float(c.get("volume", 0)),
            ))

        return candles

    async def get_initial_bars(self, symbol: str, timeframe: str, count: int = 500) -> list[dict]:
        """Return the last `count` bars as plain dicts (for agent warmup).

        Convenience wrapper around get_candles() so the agent engine
        can call the same method name on all adapters.
        """
        try:
            candles = await self.get_candles(symbol, timeframe, count)
            return [
                {
                    "time": int(c.timestamp.timestamp()),
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                }
                for c in candles
            ]
        except Exception as e:
            logger.warning("get_initial_bars(%s, %s, %d) failed: %s", symbol, timeframe, count, e)
            return []

    async def get_price(self, symbol: str) -> PriceTick:
        instrument = _to_oanda_instrument(symbol)
        data = await self._get(
            f"/accounts/{self._account_id}/pricing",
            params={"instruments": instrument},
        )
        prices = data.get("prices", [])
        if not prices:
            raise ValueError(f"No price data for {symbol}")

        p = prices[0]
        bid = float(p.get("bids", [{"price": 0}])[0]["price"])
        ask = float(p.get("asks", [{"price": 0}])[0]["price"])

        return PriceTick(
            symbol=instrument,
            bid=bid,
            ask=ask,
            timestamp=self._parse_ts(p.get("time", "")),
            spread=ask - bid,
        )

    # ── Streaming ──────────────────────────────────────

    async def stream_prices(self, symbols: list[str]) -> AsyncGenerator[PriceTick, None]:
        instruments = ",".join(_to_oanda_instrument(s) for s in symbols)
        url = f"{self._stream_url}/v3/accounts/{self._account_id}/pricing/stream"

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "GET",
                url,
                params={"instruments": instruments},
                headers=self._headers(),
            ) as response:
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("type") == "PRICE":
                            bids = data.get("bids", [])
                            asks = data.get("asks", [])
                            bid = float(bids[0]["price"]) if bids else 0
                            ask = float(asks[0]["price"]) if asks else 0
                            yield PriceTick(
                                symbol=data.get("instrument", ""),
                                bid=bid,
                                ask=ask,
                                timestamp=self._parse_ts(data.get("time", "")),
                                spread=ask - bid,
                            )
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
