"""
cTrader Open API broker adapter — WebSocket + JSON protocol.

Connects to cTrader Open API proxy via WebSocket (WSS) using JSON payloads.
Supports OAuth2 authentication and all standard broker operations.

References:
  - https://help.ctrader.com/open-api/
  - https://help.ctrader.com/open-api/sending-receiving-json/
"""

import asyncio
import json
import logging
import ssl
import time
from datetime import datetime, timezone
from typing import Optional, AsyncGenerator

from .base import (
    BrokerAdapter,
    AccountInfo,
    ClosedTrade,
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

# ── cTrader Open API payload type IDs ──────────────────

# Proto common
PROTO_HEARTBEAT_EVENT = 51

# ProtoOA message types
PROTO_OA_APPLICATION_AUTH_REQ = 2100
PROTO_OA_APPLICATION_AUTH_RES = 2101
PROTO_OA_ACCOUNT_AUTH_REQ = 2102
PROTO_OA_ACCOUNT_AUTH_RES = 2103
PROTO_OA_ERROR_RES = 2142
PROTO_OA_TRADER_REQ = 2121
PROTO_OA_TRADER_RES = 2122
PROTO_OA_RECONCILE_REQ = 2124
PROTO_OA_RECONCILE_RES = 2125
PROTO_OA_NEW_ORDER_REQ = 2106
PROTO_OA_EXECUTION_EVENT = 2126
PROTO_OA_CLOSE_POSITION_REQ = 2111
PROTO_OA_CANCEL_ORDER_REQ = 2108
PROTO_OA_AMEND_ORDER_REQ = 2109
PROTO_OA_AMEND_POSITION_SLTP_REQ = 2110
PROTO_OA_SYMBOLS_LIST_REQ = 2114
PROTO_OA_SYMBOLS_LIST_RES = 2115
PROTO_OA_SYMBOL_BY_ID_REQ = 2116
PROTO_OA_SYMBOL_BY_ID_RES = 2117
PROTO_OA_SUBSCRIBE_SPOTS_REQ = 2127
PROTO_OA_SUBSCRIBE_SPOTS_RES = 2128
PROTO_OA_SPOT_EVENT = 2131
PROTO_OA_GET_TRENDBARS_REQ = 2137
PROTO_OA_GET_TRENDBARS_RES = 2138
PROTO_OA_DEAL_LIST_REQ = 2133
PROTO_OA_DEAL_LIST_RES = 2134
PROTO_OA_GET_ACCOUNTS_BY_ACCESS_TOKEN_REQ = 2149
PROTO_OA_GET_ACCOUNTS_BY_ACCESS_TOKEN_RES = 2150

# Order type mapping
_ORDER_TYPE_MAP = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.STOP: "STOP",
    OrderType.STOP_LIMIT: "STOP_LIMIT",
}

# Timeframe mapping to cTrader trend bar period
_TF_MAP = {
    "M1": "M1", "M5": "M5", "M15": "M15", "M30": "M30",
    "H1": "H1", "H4": "H4", "H12": "H12",
    "D1": "D1", "W1": "W1", "MN": "MN1",
    # aliases
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1h": "H1", "4h": "H4", "1d": "D1", "1w": "W1",
}


class CTraderAdapter(BrokerAdapter):
    """
    cTrader Open API adapter using WebSocket + JSON.

    Args:
        client_id:     cTrader Open API application client ID
        client_secret: cTrader Open API application client secret
        access_token:  OAuth2 access token
        account_id:    cTrader trading account ID (ctidTraderAccountId)
        server:        "demo" or "live"
    """

    broker_name = "ctrader"

    _DEMO_HOST = "demo.ctraderapi.com"
    _LIVE_HOST = "live.ctraderapi.com"
    _PORT = 5036  # JSON mode (5035 = protobuf only)

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        access_token: str,
        account_id: str,
        server: str = "demo",
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token = access_token
        if not account_id:
            raise ValueError("cTrader account_id is required")
        self._account_id = int(account_id)
        self._server = server.lower()
        self._host = self._DEMO_HOST if self._server == "demo" else self._LIVE_HOST

        # WebSocket state
        self._ws = None
        self._connected = False
        self._msg_id_counter = 0
        self._pending_requests: dict[str, asyncio.Future] = {}
        self._recv_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

        # Caches
        self._symbol_cache: dict[int, dict] = {}      # symbolId -> symbol info
        self._symbol_name_to_id: dict[str, int] = {}   # "XAUUSD" -> symbolId
        self._price_cache: dict[str, PriceTick] = {}    # symbol -> last tick
        self._position_symbol: dict[str, int] = {}     # positionId -> symbolId
        self._spot_callbacks: list = []

        # Rate limiting
        self._request_semaphore = asyncio.Semaphore(40)
        self._last_request_time = 0.0

        # Last error message (for UI feedback)
        self._last_error = ""

    # ── Helpers ────────────────────────────────────────

    def _next_msg_id(self) -> str:
        self._msg_id_counter += 1
        return f"msg_{self._msg_id_counter}"

    async def _send(self, payload_type: int, payload: dict, msg_id: str | None = None) -> dict:
        """Send a JSON message and wait for the response."""
        if not self._ws or (hasattr(self._ws, 'closed') and self._ws.closed):
            self._connected = False
            raise ConnectionError("Not connected to cTrader")

        msg_id = msg_id or self._next_msg_id()
        message = {
            "clientMsgId": msg_id,
            "payloadType": payload_type,
            "payload": payload,
        }

        future = asyncio.get_running_loop().create_future()
        self._pending_requests[msg_id] = future

        async with self._request_semaphore:
            # Rate limit: min 25ms between requests
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < 0.025:
                await asyncio.sleep(0.025 - elapsed)
            self._last_request_time = time.monotonic()

            await self._ws.send(json.dumps(message))

        try:
            response = await asyncio.wait_for(future, timeout=15.0)
        except asyncio.TimeoutError:
            self._pending_requests.pop(msg_id, None)
            raise TimeoutError(f"cTrader request timed out (type={payload_type})")

        # Check for error response
        if response.get("payloadType") == PROTO_OA_ERROR_RES:
            error_payload = response.get("payload", {})
            error_code = error_payload.get("errorCode", "UNKNOWN")
            description = error_payload.get("description", "Unknown error")
            raise RuntimeError(f"cTrader error {error_code}: {description}")

        return response

    async def _recv_loop(self):
        """Background task to receive messages from WebSocket."""
        try:
            async for raw_msg in self._ws:
                try:
                    msg = json.loads(raw_msg)
                except (json.JSONDecodeError, TypeError):
                    continue

                msg_id = msg.get("clientMsgId", "")
                payload_type = msg.get("payloadType", 0)

                # Handle heartbeat
                if payload_type == PROTO_HEARTBEAT_EVENT:
                    continue

                # Handle spot price events (streaming)
                if payload_type == PROTO_OA_SPOT_EVENT:
                    self._handle_spot_event(msg.get("payload", {}))
                    continue

                # Handle execution events (order fills, etc.)
                if payload_type == PROTO_OA_EXECUTION_EVENT:
                    exec_payload = msg.get("payload", {})
                    exec_type = exec_payload.get("executionType", "?")
                    order_info = exec_payload.get("order", {})
                    position_info = exec_payload.get("position", {})
                    logger.info(
                        "cTrader execution event: type=%s, orderId=%s, positionId=%s, errorCode=%s",
                        exec_type,
                        order_info.get("orderId"),
                        position_info.get("positionId") if position_info else None,
                        exec_payload.get("errorCode", ""),
                    )
                    if exec_type in ("ORDER_REJECTED", "ORDER_CANCELLED", "ORDER_EXPIRED"):
                        logger.warning(
                            "cTrader %s: orderId=%s, reason=%s",
                            exec_type, order_info.get("orderId"),
                            exec_payload.get("reasonCode", exec_payload.get("errorCode", "unknown")),
                        )

                # Resolve pending request
                if msg_id and msg_id in self._pending_requests:
                    fut = self._pending_requests.pop(msg_id)
                    if not fut.done():
                        fut.set_result(msg)
        except Exception as e:
            if self._connected:
                logger.error("cTrader recv loop error: %s", e)
                self._connected = False

    async def _heartbeat_loop(self):
        """Send heartbeat every 10 seconds."""
        while self._connected and self._ws:
            try:
                await asyncio.sleep(10)
                if self._ws:
                    msg = json.dumps({
                        "clientMsgId": self._next_msg_id(),
                        "payloadType": PROTO_HEARTBEAT_EVENT,
                        "payload": {},
                    })
                    await self._ws.send(msg)
            except Exception:
                break

    def _handle_spot_event(self, payload: dict):
        """Handle incoming spot price event."""
        symbol_id = payload.get("symbolId", 0)
        sym_info = self._symbol_cache.get(symbol_id)
        if not sym_info:
            return

        symbol_name = sym_info.get("symbolName", str(symbol_id))
        digits = sym_info.get("digits", 5)

        bid = round(payload.get("bid", 0) / 100000.0, digits) if "bid" in payload else None
        ask = round(payload.get("ask", 0) / 100000.0, digits) if "ask" in payload else None

        # Update from last known values if partial update
        last = self._price_cache.get(symbol_name)
        if bid is None and last:
            bid = last.bid
        if ask is None and last:
            ask = last.ask

        if bid is not None and ask is not None:
            tick = PriceTick(
                symbol=symbol_name,
                bid=bid,
                ask=ask,
                timestamp=datetime.now(timezone.utc),
                spread=ask - bid,
            )
            self._price_cache[symbol_name] = tick

    @staticmethod
    def _convert_price(price_int: int, digits: int) -> float:
        """Convert cTrader integer price to float.

        All cTrader Open API prices (spot, trendbar, position, order)
        are encoded with a fixed factor of 100000. Divide by 100000
        then round to the symbol's digit precision.
        See: https://help.ctrader.com/open-api/symbol-data/
        """
        return round(price_int / 100000.0, digits)

    @staticmethod
    def _to_price_int(price: float, digits: int) -> int:
        """Convert float price to cTrader integer format (× 100000).

        Only used for fields that use integer encoding (spot/trendbar).
        """
        return int(round(price * 100000))

    @staticmethod
    def _is_buy_side(trade_side) -> bool:
        """Check if tradeSide indicates a BUY.

        cTrader JSON API may send tradeSide as string ("BUY"/"SELL")
        or as integer enum (1=BUY, 2=SELL).
        """
        return trade_side in ("BUY", 1)

    def _to_volume(self, lots: float, lot_size: int = 100_000) -> int:
        """Convert lot size to cTrader volume (centos of units).

        cTrader Open API volume = units × 100 (centos).
        lot_size comes from the symbol's lotSize field (e.g. 100000 for forex, 100 for gold).
        """
        return int(round(lots * lot_size * 100))

    def _from_volume(self, volume: int, lot_size: int = 100_000) -> float:
        """Convert cTrader volume (centos of units) to lot size.

        lot_size comes from the symbol's lotSize field.
        """
        if lot_size <= 0:
            lot_size = 100_000
        return volume / (lot_size * 100)

    # Common symbol aliases for broker-specific naming conventions
    _SYMBOL_ALIASES: dict[str, list[str]] = {
        "US30": ["DJ30", "WS30", "DJI", "USTEC30", "US Wall Street 30"],
        "NAS100": ["USTEC", "NQ100", "NDX100", "US Tech 100"],
        "XAUUSD": ["XAU/USD", "GOLD", "Gold"],
        "XAGUSD": ["XAG/USD", "SILVER", "Silver"],
        "BTCUSD": ["BTC/USD", "BITCOIN", "Bitcoin"],
        "ETHUSD": ["ETH/USD", "ETHEREUM", "Ethereum"],
        "EURUSD": ["EUR/USD"],
        "GBPUSD": ["GBP/USD"],
        "USDJPY": ["USD/JPY"],
        "AUDUSD": ["AUD/USD"],
        "USDCAD": ["USD/CAD"],
        "USDCHF": ["USD/CHF"],
        "NZDUSD": ["NZD/USD"],
        "EURJPY": ["EUR/JPY"],
        "GBPJPY": ["GBP/JPY"],
    }

    @staticmethod
    def _normalize_symbol(name: str) -> str:
        """Normalize a symbol name for fuzzy matching.

        Strips common suffixes (.m, .e, .pro, etc.), removes separators
        (/, -, _) and lowercases so that user input like "BTCUSD" can
        match broker names like "BTC/USD", "BTCUSD.m", "btcusd.pro".
        """
        s = name.strip().lower()
        # Remove common cTrader broker suffixes
        for suffix in (".m", ".e", ".pro", ".raw", ".ecn", ".std", ".z", ".b"):
            if s.endswith(suffix):
                s = s[: -len(suffix)]
                break
        # Strip separators
        s = s.replace("/", "").replace("-", "").replace("_", "").replace(".", "")
        return s

    async def _resolve_symbol_id(self, symbol: str) -> int:
        """Resolve symbol name to cTrader symbolId with fuzzy matching.

        Tries in order: exact match, case-insensitive, normalized (strip
        suffixes/separators), slash variants, aliases, and substring match.
        """
        # Ensure symbols are loaded
        if not self._symbol_cache:
            await self._load_symbols()

        # 1. Exact match
        if symbol in self._symbol_name_to_id:
            return self._symbol_name_to_id[symbol]

        # Build uppercase lookup for case-insensitive matching
        upper_map = {k.upper(): k for k in self._symbol_name_to_id}
        sym_upper = symbol.upper()

        # 2. Case-insensitive match
        if sym_upper in upper_map:
            self._symbol_name_to_id[symbol] = self._symbol_name_to_id[upper_map[sym_upper]]
            return self._symbol_name_to_id[symbol]

        # 3. Normalized match (strips broker suffixes like .m, .pro, .ecn)
        normalized_input = self._normalize_symbol(symbol)
        for name, sid in self._symbol_name_to_id.items():
            if self._normalize_symbol(name) == normalized_input:
                logger.info("cTrader symbol mapped: %s -> %s", symbol, name)
                self._symbol_name_to_id[symbol] = sid
                return sid

        # 4. Strip slashes: "XAU/USD" -> "XAUUSD"
        stripped = sym_upper.replace("/", "").replace(" ", "")
        if stripped in upper_map:
            return self._symbol_name_to_id[upper_map[stripped]]

        # 5. Insert slash for common forex/metals/crypto patterns
        for split_pos in (3, 4):
            if len(sym_upper) >= split_pos + 3:
                slashed = f"{sym_upper[:split_pos]}/{sym_upper[split_pos:]}"
                if slashed in upper_map:
                    return self._symbol_name_to_id[upper_map[slashed]]

        # 6. Check known aliases
        for canonical, aliases in self._SYMBOL_ALIASES.items():
            if sym_upper == canonical.upper() or sym_upper in [a.upper() for a in aliases]:
                for candidate in [canonical] + aliases:
                    cand_upper = candidate.upper()
                    if cand_upper in upper_map:
                        return self._symbol_name_to_id[upper_map[cand_upper]]

        # 7. Substring match (find symbols containing the query)
        matches = [k for k in self._symbol_name_to_id
                   if sym_upper in k.upper() or k.upper() in sym_upper]
        if len(matches) == 1:
            logger.info("cTrader fuzzy match: '%s' -> '%s'", symbol, matches[0])
            return self._symbol_name_to_id[matches[0]]

        # Log available symbols for debugging
        available = sorted(self._symbol_name_to_id.keys())[:50]
        logger.warning(
            "Symbol '%s' not found in cTrader. Available symbols (first 50): %s",
            symbol, ", ".join(available)
        )
        raise ValueError(
            f"Symbol {symbol} not found in cTrader. "
            f"Try one of: {', '.join(available[:20])}"
        )

    async def _load_symbols(self):
        """Load symbol list from cTrader and populate caches."""
        logger.info("cTrader _load_symbols: requesting symbol list for account %d", self._account_id)
        resp = await self._send(PROTO_OA_SYMBOLS_LIST_REQ, {
            "ctidTraderAccountId": self._account_id,
        })
        logger.info("cTrader _load_symbols: response payloadType=%s, payload keys=%s",
                     resp.get("payloadType"), list(resp.get("payload", {}).keys()))
        symbols = resp.get("payload", {}).get("symbol", [])
        logger.info("cTrader _load_symbols: got %d light symbols", len(symbols))

        # Get detailed info for all symbols
        symbol_ids = [s.get("symbolId") for s in symbols if s.get("symbolId")]

        if symbol_ids:
            logger.info("cTrader _load_symbols: fetching details for %d symbols in batches of 50", len(symbol_ids))
            # Request details in batches of 50
            for i in range(0, len(symbol_ids), 50):
                batch = symbol_ids[i:i + 50]
                detail_resp = await self._send(PROTO_OA_SYMBOL_BY_ID_REQ, {
                    "ctidTraderAccountId": self._account_id,
                    "symbolId": batch,
                })
                detail_symbols = detail_resp.get("payload", {}).get("symbol", [])
                logger.info("cTrader _load_symbols: batch %d got %d detailed symbols", i // 50, len(detail_symbols))
                for sym in detail_symbols:
                    sid = sym.get("symbolId", 0)
                    name = sym.get("symbolName", "")
                    self._symbol_cache[sid] = sym
                    if name:
                        self._symbol_name_to_id[name] = sid
        else:
            logger.warning("cTrader _load_symbols: no symbol IDs found in response")

        # Merge light symbol data into cache (detail response lacks symbolName/description)
        for s in symbols:
            sid = s.get("symbolId", 0)
            if not sid:
                continue
            name = s.get("symbolName", "")
            if sid not in self._symbol_cache:
                # Detail fetch failed/timed out — use light symbol as fallback
                self._symbol_cache[sid] = s
            else:
                # Detail exists but lacks symbolName — merge from light symbol
                if name and "symbolName" not in self._symbol_cache[sid]:
                    self._symbol_cache[sid]["symbolName"] = name
                # Also merge description if available
                desc = s.get("description", "")
                if desc and "description" not in self._symbol_cache[sid]:
                    self._symbol_cache[sid]["description"] = desc
            # Map name → id
            if name and name not in self._symbol_name_to_id:
                self._symbol_name_to_id[name] = sid

        symbol_names = sorted(self._symbol_name_to_id.keys())
        logger.info("cTrader loaded %d symbols: %s", len(self._symbol_cache),
                     ", ".join(symbol_names[:30]) + ("..." if len(symbol_names) > 30 else ""))

    # ── Connection ─────────────────────────────────────

    async def connect(self) -> bool:
        self._last_error = ""
        try:
            import websockets
        except ImportError:
            self._last_error = "websockets package not installed"
            logger.error(self._last_error)
            return False

        if not self._client_id or not self._client_secret:
            self._last_error = "CTRADER_CLIENT_ID or CTRADER_CLIENT_SECRET not configured"
            logger.error(self._last_error)
            return False

        if not self._access_token:
            self._last_error = "No cTrader access token — complete OAuth flow first"
            logger.error(self._last_error)
            return False

        if not self._account_id:
            self._last_error = "No cTrader account selected — pick an account first"
            logger.error(self._last_error)
            return False

        url = f"wss://{self._host}:{self._PORT}"
        logger.info("cTrader connecting to %s (%s)", url, self._server)

        try:
            ssl_ctx = ssl.create_default_context()
            self._ws = await websockets.connect(url, ssl=ssl_ctx, ping_interval=None)

            # Start receive loop
            self._recv_task = asyncio.create_task(self._recv_loop())

            # 1. Application auth
            resp = await self._send(PROTO_OA_APPLICATION_AUTH_REQ, {
                "clientId": self._client_id,
                "clientSecret": self._client_secret,
            })
            if resp.get("payloadType") != PROTO_OA_APPLICATION_AUTH_RES:
                err = resp.get("payload", {}).get("description", "Unknown error")
                self._last_error = f"App auth failed: {err}"
                logger.error("cTrader app auth failed: %s", resp)
                return False
            logger.info("cTrader application authenticated")

            # 2. Account auth
            resp = await self._send(PROTO_OA_ACCOUNT_AUTH_REQ, {
                "ctidTraderAccountId": self._account_id,
                "accessToken": self._access_token,
            })
            if resp.get("payloadType") != PROTO_OA_ACCOUNT_AUTH_RES:
                err = resp.get("payload", {}).get("description", "Unknown error")
                self._last_error = f"Account auth failed: {err} (token may be expired)"
                logger.error("cTrader account auth failed: %s", resp)
                return False
            logger.info("cTrader account %d authenticated", self._account_id)

            # Start heartbeat
            self._connected = True
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            # Pre-load symbols
            try:
                await self._load_symbols()
            except Exception as e:
                logger.warning("cTrader symbol pre-load failed: %s", e)

            return True

        except Exception as e:
            self._last_error = f"Connection failed: {str(e)}"
            logger.error("cTrader connect failed: %s", e)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        self._connected = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._recv_task:
            self._recv_task.cancel()
            self._recv_task = None
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        # Fail all pending requests
        for msg_id, fut in self._pending_requests.items():
            if not fut.done():
                fut.set_exception(ConnectionError("Disconnected"))
        self._pending_requests.clear()

        logger.info("cTrader disconnected")

    async def is_connected(self) -> bool:
        if not self._connected or not self._ws:
            return False
        # Check if WebSocket is actually open
        try:
            if hasattr(self._ws, 'closed') and self._ws.closed:
                self._connected = False
                return False
        except Exception:
            pass
        return True

    # ── Account ────────────────────────────────────────

    async def get_account_info(self) -> AccountInfo:
        resp = await self._send(PROTO_OA_TRADER_REQ, {
            "ctidTraderAccountId": self._account_id,
        })
        trader = resp.get("payload", {}).get("trader", {})

        money_digits = trader.get("moneyDigits", 2)
        balance = trader.get("balance", 0) / (10 ** money_digits)

        # Get positions and orders to calculate equity (single reconcile call)
        total_unrealized = 0.0
        open_position_count = 0
        open_order_count = 0
        try:
            positions = await self.get_positions()
            total_unrealized = sum(p.unrealized_pnl for p in positions)
            open_position_count = len(positions)
            # Orders come from the same reconcile, fetch separately
            reconcile = await self._send(PROTO_OA_RECONCILE_REQ, {
                "ctidTraderAccountId": self._account_id,
            })
            open_order_count = len(reconcile.get("payload", {}).get("order", []))
        except Exception as e:
            logger.debug("cTrader account info: failed to get positions/orders: %s", e)

        equity = balance + total_unrealized

        return AccountInfo(
            account_id=str(self._account_id),
            broker="ctrader",
            currency=trader.get("depositAsset", {}).get("name", "USD"),
            balance=balance,
            equity=equity,
            unrealized_pnl=total_unrealized,
            margin_used=0.0,
            margin_available=equity,
            open_positions=open_position_count,
            open_orders=open_order_count,
        )

    # ── Positions ──────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        resp = await self._send(PROTO_OA_RECONCILE_REQ, {
            "ctidTraderAccountId": self._account_id,
        })
        payload = resp.get("payload", {})
        raw_positions = payload.get("position", [])
        logger.info("cTrader reconcile: payloadType=%s, %d positions, %d orders, keys=%s",
                     resp.get("payloadType"), len(raw_positions),
                     len(payload.get("order", [])), list(payload.keys()))
        if raw_positions:
            logger.debug("cTrader first position raw: %s", raw_positions[0])
        positions: list[Position] = []

        for pos in raw_positions:
            symbol_id = pos.get("tradeData", {}).get("symbolId", 0)
            sym_info = self._symbol_cache.get(symbol_id, {})
            symbol_name = sym_info.get("symbolName", str(symbol_id))
            digits = sym_info.get("digits", 5)
            lot_size = sym_info.get("lotSize", 100_000)

            is_buy = self._is_buy_side(pos.get("tradeData", {}).get("tradeSide", 1))
            volume = pos.get("tradeData", {}).get("volume", 0)
            # Position price/SL/TP are doubles in the cTrader API (not integer-encoded)
            entry_price = round(float(pos.get("price", 0)), digits)

            # SL/TP — also doubles
            sl = round(float(pos.get("stopLoss", 0)), digits) if pos.get("stopLoss") else None
            tp = round(float(pos.get("takeProfit", 0)), digits) if pos.get("takeProfit") else None

            # Get current price from cache
            last_tick = self._price_cache.get(symbol_name)
            current_price = (last_tick.bid if not is_buy else last_tick.ask) if last_tick else entry_price

            # Unrealized PnL — calculate from price difference
            swap = pos.get("swap", 0) / 100
            commission = pos.get("commission", 0) / 100
            lots = self._from_volume(volume, lot_size)
            # moneyDigits tells us the precision of monetary values (e.g. 2 for cents)
            money_digits = pos.get("moneyDigits", 2)

            if entry_price > 0 and current_price > 0:
                price_diff = (current_price - entry_price) if is_buy else (entry_price - current_price)
                # Use utpList if available (cTrader's own PnL in cents), else calculate
                utp_list = pos.get("utpList", [])
                if utp_list:
                    # Sum monetary unrealized from cTrader's own calculation
                    unrealized = sum(u.get("money", 0) for u in utp_list) / (10 ** money_digits)
                else:
                    # Fallback: price_diff × units (volume in centos, so divide by 100)
                    units = volume / 100
                    unrealized = price_diff * units
            else:
                unrealized = 0.0
            unrealized += swap + commission

            open_ts = pos.get("tradeData", {}).get("openTimestamp", 0)
            open_time = datetime.fromtimestamp(open_ts / 1000, tz=timezone.utc) if open_ts else datetime.now(timezone.utc)

            pos_id = str(pos.get("positionId", ""))
            self._position_symbol[pos_id] = symbol_id

            positions.append(Position(
                position_id=pos_id,
                symbol=symbol_name,
                side=PositionSide.LONG if is_buy else PositionSide.SHORT,
                size=lots,
                entry_price=entry_price,
                current_price=current_price,
                unrealized_pnl=unrealized,
                margin_used=0.0,
                open_time=open_time,
                stop_loss=sl if sl and sl > 0 else None,
                take_profit=tp if tp and tp > 0 else None,
            ))

        return positions

    async def close_position(self, position_id: str, size: Optional[float] = None) -> Order:
        payload: dict = {
            "ctidTraderAccountId": self._account_id,
            "positionId": int(position_id),
        }
        if size is not None:
            # Look up lot_size from cached position → symbol mapping
            symbol_id = self._position_symbol.get(position_id, 0)
            lot_size = self._symbol_cache.get(symbol_id, {}).get("lotSize", 100_000)
            payload["volume"] = self._to_volume(size, lot_size)

        resp = await self._send(PROTO_OA_CLOSE_POSITION_REQ, payload)
        exec_payload = resp.get("payload", {})

        return Order(
            order_id=str(exec_payload.get("orderId", position_id)),
            symbol="",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            size=size or 0,
            status=OrderStatus.FILLED,
            filled_price=0,
            filled_time=datetime.now(timezone.utc),
        )

    # ── Orders ─────────────────────────────────────────

    async def place_order(self, request: OrderRequest) -> Order:
        symbol_id = await self._resolve_symbol_id(request.symbol)
        sym_info = self._symbol_cache.get(symbol_id, {})
        digits = sym_info.get("digits", 5)
        lot_size = sym_info.get("lotSize", 100_000)

        volume = self._to_volume(request.size, lot_size)

        # Validate volume against symbol constraints
        min_vol = sym_info.get("minVolume", 100)
        step_vol = sym_info.get("stepVolume", 100)
        max_vol = sym_info.get("maxVolume", 10_000_000)

        if volume < min_vol:
            logger.warning("cTrader volume %d < minVolume %d for %s — clamping up", volume, min_vol, request.symbol)
            volume = min_vol
        if volume > max_vol:
            logger.warning("cTrader volume %d > maxVolume %d for %s — clamping down", volume, max_vol, request.symbol)
            volume = max_vol
        if step_vol > 0 and volume % step_vol != 0:
            volume = max(min_vol, (volume // step_vol) * step_vol)

        payload: dict = {
            "ctidTraderAccountId": self._account_id,
            "symbolId": symbol_id,
            "orderType": _ORDER_TYPE_MAP.get(request.order_type, "MARKET"),
            "tradeSide": "BUY" if request.side == OrderSide.BUY else "SELL",
            "volume": volume,
        }

        # Price for limit/stop orders (API expects doubles, not integer-encoded)
        if request.price and request.order_type != OrderType.MARKET:
            payload["limitPrice" if request.order_type == OrderType.LIMIT else "stopPrice"] = (
                round(request.price, digits)
            )

        # SL/TP — doubles
        if request.stop_loss:
            payload["stopLoss"] = round(request.stop_loss, digits)
        if request.take_profit:
            payload["takeProfit"] = round(request.take_profit, digits)
        if request.trailing_stop_distance:
            payload["trailingStopLoss"] = True
            payload["stopTriggerMethod"] = "TRADE"

        if request.comment:
            payload["comment"] = request.comment[:25]  # cTrader limits comment length

        logger.info("cTrader order: %s %s %.2f lots, SL=%s, TP=%s",
                    request.side.value, request.symbol, request.size,
                    request.stop_loss, request.take_profit)

        logger.info("cTrader order payload: %s", {k: v for k, v in payload.items() if k != "ctidTraderAccountId"})
        resp = await self._send(PROTO_OA_NEW_ORDER_REQ, payload)
        exec_payload = resp.get("payload", {})
        order_data = exec_payload.get("order", {})
        position = exec_payload.get("position", {})
        logger.info("cTrader order response: executionType=%s, orderId=%s, positionId=%s, keys=%s",
                     exec_payload.get("executionType"), order_data.get("orderId"),
                     position.get("positionId") if position else None,
                     list(exec_payload.keys()))

        filled_price = 0.0
        if position and position.get("price"):
            filled_price = round(float(position["price"]), digits)
        elif order_data and order_data.get("executionPrice"):
            filled_price = round(float(order_data["executionPrice"]), digits)

        exec_type = exec_payload.get("executionType", "")
        error_code = exec_payload.get("errorCode", "")

        if exec_type == "ORDER_FILLED":
            status = OrderStatus.FILLED
        elif exec_type in ("ORDER_ACCEPTED", "ORDER_REPLACED"):
            status = OrderStatus.PENDING
        elif exec_type in ("ORDER_REJECTED", "ORDER_CANCEL_REJECTED"):
            reason = exec_payload.get("reasonCode", error_code or "unknown")
            logger.error("cTrader order REJECTED: exec_type=%s, reason=%s", exec_type, reason)
            raise RuntimeError(f"Order rejected by cTrader: {reason}")
        elif exec_type in ("ORDER_CANCELLED", "ORDER_EXPIRED"):
            reason = exec_payload.get("reasonCode", error_code or "unknown")
            logger.warning("cTrader order cancelled/expired: exec_type=%s, reason=%s", exec_type, reason)
            raise RuntimeError(f"Order {exec_type.lower().replace('order_', '')}: {reason}")
        elif exec_type == "ORDER_PARTIAL_FILL":
            status = OrderStatus.PARTIALLY_FILLED
        elif error_code:
            logger.error("cTrader order error: errorCode=%s, exec_type=%s", error_code, exec_type)
            raise RuntimeError(f"cTrader order error: {error_code}")
        else:
            # Unknown execution type — treat as pending but log
            logger.warning("cTrader unknown executionType=%s, treating as PENDING", exec_type)
            status = OrderStatus.PENDING

        return Order(
            order_id=str(order_data.get("orderId", exec_payload.get("orderId", "0"))),
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            size=request.size,
            price=request.price,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            status=status,
            filled_price=filled_price if filled_price > 0 else None,
            filled_time=datetime.now(timezone.utc) if status == OrderStatus.FILLED else None,
            created_time=datetime.now(timezone.utc),
        )

    async def modify_order(self, request: OrderModifyRequest) -> Order:
        # Try as position SL/TP modification
        payload: dict = {
            "ctidTraderAccountId": self._account_id,
            "positionId": int(request.order_id),
        }

        # Need symbol digits for price conversion
        digits = 5  # default
        try:
            positions = await self.get_positions()
            for pos in positions:
                if pos.position_id == request.order_id:
                    sym_id = self._symbol_name_to_id.get(pos.symbol, 0)
                    digits = self._symbol_cache.get(sym_id, {}).get("digits", 5)
                    break
        except Exception:
            pass

        if request.stop_loss is not None:
            payload["stopLoss"] = round(request.stop_loss, digits)
        if request.take_profit is not None:
            payload["takeProfit"] = round(request.take_profit, digits)

        try:
            await self._send(PROTO_OA_AMEND_POSITION_SLTP_REQ, payload)
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
        except RuntimeError:
            # Try as pending order modification
            order_payload: dict = {
                "ctidTraderAccountId": self._account_id,
                "orderId": int(request.order_id),
            }
            if request.price is not None:
                order_payload["limitPrice"] = round(request.price, digits)
            if request.stop_loss is not None:
                order_payload["stopLoss"] = round(request.stop_loss, digits)
            if request.take_profit is not None:
                order_payload["takeProfit"] = round(request.take_profit, digits)

            await self._send(PROTO_OA_AMEND_ORDER_REQ, order_payload)
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
            await self._send(PROTO_OA_CANCEL_ORDER_REQ, {
                "ctidTraderAccountId": self._account_id,
                "orderId": int(order_id),
            })
            return True
        except Exception as e:
            logger.error("cTrader cancel order %s failed: %s", order_id, e)
            return False

    async def get_open_orders(self) -> list[Order]:
        resp = await self._send(PROTO_OA_RECONCILE_REQ, {
            "ctidTraderAccountId": self._account_id,
        })
        orders: list[Order] = []

        for o in resp.get("payload", {}).get("order", []):
            symbol_id = o.get("tradeData", {}).get("symbolId", 0)
            sym_info = self._symbol_cache.get(symbol_id, {})
            symbol_name = sym_info.get("symbolName", str(symbol_id))
            digits = sym_info.get("digits", 5)
            lot_size = sym_info.get("lotSize", 100_000)

            is_buy = self._is_buy_side(o.get("tradeData", {}).get("tradeSide", 1))
            volume = o.get("tradeData", {}).get("volume", 0)
            # Order prices are doubles in the cTrader API
            price = round(float(o.get("limitPrice", o.get("stopPrice", 0))), digits)

            order_type_str = o.get("orderType", "MARKET")
            otype_map = {
                "MARKET": OrderType.MARKET,
                "LIMIT": OrderType.LIMIT,
                "STOP": OrderType.STOP,
                "STOP_LIMIT": OrderType.STOP_LIMIT,
            }

            sl = round(float(o.get("stopLoss", 0)), digits) if o.get("stopLoss") else None
            tp = round(float(o.get("takeProfit", 0)), digits) if o.get("takeProfit") else None

            orders.append(Order(
                order_id=str(o.get("orderId", "")),
                symbol=symbol_name,
                side=OrderSide.BUY if is_buy else OrderSide.SELL,
                order_type=otype_map.get(order_type_str, OrderType.MARKET),
                size=self._from_volume(volume, lot_size),
                price=price if price > 0 else None,
                stop_loss=sl if sl and sl > 0 else None,
                take_profit=tp if tp and tp > 0 else None,
                status=OrderStatus.PENDING,
            ))

        return orders

    # ── Closed Trades ─────────────────────────────────

    async def get_closed_trades(
        self,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> list[ClosedTrade]:
        """Fetch closed trades (deals) from cTrader deal history."""
        # cTrader requires a time range; default to last 7 days
        to_ts = int(time.time() * 1000)
        if since:
            from_ts = int(since.timestamp() * 1000)
        else:
            from_ts = to_ts - 7 * 24 * 60 * 60 * 1000  # 7 days ago

        try:
            resp = await self._send(PROTO_OA_DEAL_LIST_REQ, {
                "ctidTraderAccountId": self._account_id,
                "fromTimestamp": from_ts,
                "toTimestamp": to_ts,
                "maxRows": min(limit, 1000),
            })
        except Exception as e:
            logger.warning("cTrader: failed to get deal history: %s", e)
            return []

        closed_trades: list[ClosedTrade] = []
        for deal in resp.get("payload", {}).get("deal", []):
            # Only closing deals have realized P&L
            close_pnl = deal.get("closePositionDetail", {})
            if not close_pnl:
                continue

            money_digits = close_pnl.get("moneyDigits", deal.get("moneyDigits", 2))
            divisor = 10 ** money_digits
            pnl = (close_pnl.get("grossProfit", 0) + close_pnl.get("swap", 0)
                   + close_pnl.get("commission", 0)) / divisor

            symbol_id = deal.get("symbolId", 0)
            sym_info = self._symbol_cache.get(symbol_id, {})
            symbol_name = sym_info.get("symbolName", str(symbol_id))
            digits = sym_info.get("digits", 5)

            is_buy = self._is_buy_side(deal.get("tradeSide", 1))
            volume = deal.get("volume", 0)
            lot_size = sym_info.get("lotSize", 100_000)
            # Deal prices are doubles in the cTrader API
            exec_price = round(float(deal.get("executionPrice", 0)), digits)
            entry_price = round(float(close_pnl.get("entryPrice", 0)), digits)

            exec_ts = deal.get("executionTimestamp", 0)
            close_time = (datetime.fromtimestamp(exec_ts / 1000, tz=timezone.utc)
                          if exec_ts else datetime.now(timezone.utc))

            closed_trades.append(ClosedTrade(
                trade_id=str(deal.get("dealId", "")),
                symbol=symbol_name,
                side="BUY" if is_buy else "SELL",
                size=self._from_volume(volume, lot_size),
                entry_price=entry_price,
                exit_price=exec_price,
                pnl=pnl,
                close_time=close_time,
            ))

        return closed_trades

    # ── Market Data ────────────────────────────────────

    async def get_symbols(self) -> list[SymbolInfo]:
        logger.info("cTrader get_symbols called, cache size=%d", len(self._symbol_cache))
        if not self._symbol_cache:
            await self._load_symbols()

        symbols: list[SymbolInfo] = []
        for sid, sym in self._symbol_cache.items():
            name = sym.get("symbolName", "")
            if not name:
                continue

            # Parse base/quote from symbol name
            base = name[:3] if len(name) >= 6 else name
            quote = name[3:6] if len(name) >= 6 else "USD"

            # Determine asset class
            asset_class = "forex"
            symbol_group = sym.get("symbolGroupId", 0)
            description = sym.get("description", "").lower()
            if any(w in description for w in ("gold", "silver", "oil", "metal", "commodity")):
                asset_class = "commodity"
            elif any(w in description for w in ("index", "us30", "nas", "spx", "dax")):
                asset_class = "index"
            elif any(w in description for w in ("bitcoin", "ethereum", "crypto", "btc", "eth")):
                asset_class = "crypto"

            digits = sym.get("digits", 5)
            pip_size = 10 ** (-digits)
            step_volume = sym.get("stepVolume", 100)
            min_volume = sym.get("minVolume", 100)
            max_volume = sym.get("maxVolume", 10000000)

            symbols.append(SymbolInfo(
                symbol=name,
                display_name=sym.get("description", name),
                base_currency=base,
                quote_currency=quote,
                pip_size=pip_size,
                min_lot=min_volume / 100,
                max_lot=max_volume / 100,
                lot_step=step_volume / 100,
                margin_rate=0.05,
                tradeable=sym.get("enabled", True),
                asset_class=asset_class,
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
        symbol_id = await self._resolve_symbol_id(symbol)
        sym_info = self._symbol_cache.get(symbol_id, {})
        digits = sym_info.get("digits", 5)
        period = _TF_MAP.get(timeframe, timeframe)

        payload: dict = {
            "ctidTraderAccountId": self._account_id,
            "symbolId": symbol_id,
            "period": period,
            "count": min(count, 4000),
        }

        if from_time:
            payload["fromTimestamp"] = int(from_time.timestamp() * 1000)
        if to_time:
            payload["toTimestamp"] = int(to_time.timestamp() * 1000)

        resp = await self._send(PROTO_OA_GET_TRENDBARS_REQ, payload)
        bars = resp.get("payload", {}).get("trendbar", [])

        candles: list[Candle] = []
        for bar in bars:
            ts_ms = bar.get("utcTimestampInMinutes", 0) * 60 * 1000
            if "timestamp" in bar:
                ts_ms = bar["timestamp"]

            low = bar.get("low", 0)
            delta_open = bar.get("deltaOpen", 0)
            delta_high = bar.get("deltaHigh", 0)
            delta_close = bar.get("deltaClose", 0)

            candles.append(Candle(
                timestamp=datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
                open=self._convert_price(low + delta_open, digits),
                high=self._convert_price(low + delta_high, digits),
                low=self._convert_price(low, digits),
                close=self._convert_price(low + delta_close, digits),
                volume=float(bar.get("volume", 0)),
            ))

        return candles

    async def get_initial_bars(self, symbol: str, timeframe: str, count: int = 500) -> list[dict]:
        """Return the last `count` bars as plain dicts (for agent warmup)."""
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
            logger.warning("cTrader get_initial_bars(%s, %s, %d) failed: %s", symbol, timeframe, count, e)
            return []

    def _broker_symbol_name(self, symbol: str) -> Optional[str]:
        """Get the broker's actual symbol name for a user-provided symbol.

        The price cache is keyed by the broker's symbol name (e.g. "BTC/USD"),
        but the user may pass "BTCUSD".  This resolves that mismatch.
        """
        # Exact match — user name IS the broker name
        if symbol in self._price_cache or symbol in self._symbol_name_to_id:
            return symbol
        # The symbol was mapped by _resolve_symbol_id — look it up
        sid = self._symbol_name_to_id.get(symbol)
        if sid:
            info = self._symbol_cache.get(sid, {})
            return info.get("symbolName", symbol)
        return None

    async def get_price(self, symbol: str) -> PriceTick:
        # Resolve user symbol to broker's actual name for cache lookup
        broker_name = self._broker_symbol_name(symbol)

        # Return from cache if available
        if broker_name and broker_name in self._price_cache:
            return self._price_cache[broker_name]

        # Subscribe to spots for this symbol to get prices
        try:
            symbol_id = await self._resolve_symbol_id(symbol)
            await self._send(PROTO_OA_SUBSCRIBE_SPOTS_REQ, {
                "ctidTraderAccountId": self._account_id,
                "symbolId": [symbol_id],
            })
            # Re-resolve broker name after symbol loading
            broker_name = self._broker_symbol_name(symbol) or symbol
            # Wait briefly for first tick
            await asyncio.sleep(1.0)
            if broker_name in self._price_cache:
                return self._price_cache[broker_name]
        except Exception as e:
            logger.warning("cTrader get_price(%s) subscribe failed: %s", symbol, e)

        raise ValueError(f"No price data for {symbol}")

    # ── Streaming ──────────────────────────────────────

    async def stream_prices(self, symbols: list[str]) -> AsyncGenerator[PriceTick, None]:
        # Subscribe to spots
        symbol_ids = []
        for sym in symbols:
            try:
                sid = await self._resolve_symbol_id(sym)
                symbol_ids.append(sid)
            except ValueError:
                logger.warning("cTrader: cannot stream %s (not found)", sym)

        if symbol_ids:
            await self._send(PROTO_OA_SUBSCRIBE_SPOTS_REQ, {
                "ctidTraderAccountId": self._account_id,
                "symbolId": symbol_ids,
            })

        # Yield from price cache as updates arrive
        # Resolve user symbols to broker names for cache lookup
        sym_to_broker = {sym: (self._broker_symbol_name(sym) or sym) for sym in symbols}
        last_prices: dict[str, float] = {}
        while self._connected:
            for sym in symbols:
                bname = sym_to_broker[sym]
                tick = self._price_cache.get(bname)
                if tick and last_prices.get(sym) != tick.bid:
                    last_prices[sym] = tick.bid
                    yield tick
            await asyncio.sleep(0.5)
