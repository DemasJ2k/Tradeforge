"""
MetaTrader 5 Bridge Adapter.

Wraps the MetaTrader5 Python package for live trading.
MT5 operations are synchronous, so we run them in a thread pool
to avoid blocking the async event loop.

Requirements:
  pip install MetaTrader5
  MT5 terminal must be installed and running on the same machine.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from typing import Optional, AsyncGenerator

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

# Thread pool for running synchronous MT5 calls
_mt5_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mt5")

# ── Timeframe mapping ─────────────────────────────────
_TF_MAP: dict[str, int] = {}  # populated on import if mt5 available

try:
    import MetaTrader5 as mt5

    _TF_MAP = {
        "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1,
        "MN1": mt5.TIMEFRAME_MN1,
        # Lowercase aliases
        "1m": mt5.TIMEFRAME_M1, "5m": mt5.TIMEFRAME_M5,
        "15m": mt5.TIMEFRAME_M15, "30m": mt5.TIMEFRAME_M30,
        "1h": mt5.TIMEFRAME_H1, "4h": mt5.TIMEFRAME_H4,
        "1d": mt5.TIMEFRAME_D1,
    }
    _MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    _MT5_AVAILABLE = False
    logger.warning("MetaTrader5 package not installed — MT5 adapter unavailable")


def _order_send_with_filling_fallback(request: dict):
    """
    Try different MT5 order filling modes.
    Retcode 10030 = unsupported filling mode — try the next mode.
    """
    import MetaTrader5 as mt5
    filling_modes = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
    last_result = None
    for filling in filling_modes:
        req = {**request, "type_filling": filling}
        result = mt5.order_send(req)
        if result is None:
            last_result = result
            continue
        if result.retcode == 10030:  # Unsupported filling mode
            last_result = result
            continue
        return result
    return last_result


class MT5Adapter(BrokerAdapter):
    """
    MetaTrader 5 bridge adapter.

    Uses the MetaTrader5 Python package which communicates with a local
    MT5 terminal instance. All MT5 calls are synchronous and run in a
    thread pool to keep the async event loop responsive.

    Args:
        server:   MT5 broker server name (e.g. "MetaQuotes-Demo")
        login:    MT5 account number
        password: MT5 account password
    """

    broker_name = "mt5"

    def __init__(self, server: str, login: int, password: str):
        self._server = server
        self._login = login
        self._password = password
        self._connected = False

    # ── Thread-pool helper ────────────────────────────

    async def _run(self, func, *args):
        """Run a synchronous MT5 function in the thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_mt5_pool, func, *args)

    # ── Connection ────────────────────────────────────

    async def connect(self) -> bool:
        if not _MT5_AVAILABLE:
            logger.error("MetaTrader5 package not installed")
            return False

        def _do_connect():
            if not mt5.initialize():
                logger.error("MT5 initialize failed: %s", mt5.last_error())
                return False

            authorized = mt5.login(
                login=self._login,
                password=self._password,
                server=self._server,
            )
            if not authorized:
                logger.error("MT5 login failed: %s", mt5.last_error())
                mt5.shutdown()
                return False

            info = mt5.account_info()
            logger.info(
                "MT5 connected: account %d on %s (balance: %.2f %s)",
                info.login, info.server, info.balance, info.currency,
            )
            return True

        try:
            result = await self._run(_do_connect)
            self._connected = result
            return result
        except Exception as e:
            logger.error("MT5 connect exception: %s (%s)", e, type(e).__name__)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        if _MT5_AVAILABLE and self._connected:
            await self._run(mt5.shutdown)
        self._connected = False

    async def is_connected(self) -> bool:
        if not self._connected or not _MT5_AVAILABLE:
            return False
        try:
            info = await self._run(mt5.account_info)
            return info is not None
        except Exception:
            self._connected = False
            return False

    # ── Account ───────────────────────────────────────

    async def get_account_info(self) -> AccountInfo:
        info = await self._run(mt5.account_info)
        if not info:
            raise RuntimeError("MT5 account_info failed")

        return AccountInfo(
            account_id=str(info.login),
            broker="mt5",
            currency=info.currency,
            balance=info.balance,
            equity=info.equity,
            unrealized_pnl=info.profit,
            margin_used=info.margin,
            margin_available=info.margin_free,
            open_positions=0,  # filled below
            open_orders=0,
        )

    # ── Positions ─────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        raw = await self._run(mt5.positions_get)
        if raw is None:
            return []

        positions: list[Position] = []
        for p in raw:
            positions.append(Position(
                position_id=str(p.ticket),
                symbol=p.symbol,
                side=PositionSide.LONG if p.type == 0 else PositionSide.SHORT,
                size=p.volume,
                entry_price=p.price_open,
                current_price=p.price_current,
                unrealized_pnl=p.profit,
                margin_used=0,
                open_time=datetime.fromtimestamp(p.time, tz=timezone.utc),
                stop_loss=p.sl if p.sl > 0 else None,
                take_profit=p.tp if p.tp > 0 else None,
            ))

        return positions

    async def close_position(self, position_id: str, size: Optional[float] = None) -> Order:
        ticket = int(position_id)

        def _do_close():
            pos = mt5.positions_get(ticket=ticket)
            if not pos:
                raise ValueError(f"Position {ticket} not found")
            p = pos[0]

            close_type = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
            close_volume = size or p.volume

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": p.symbol,
                "volume": close_volume,
                "type": close_type,
                "position": ticket,
                "deviation": 20,
                "magic": 100,
                "comment": "tradeforge_close",
                "type_time": mt5.ORDER_TIME_GTC,
            }

            result = _order_send_with_filling_fallback(request)
            return result

        result = await self._run(_do_close)

        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = result.comment if result else "unknown"
            raise RuntimeError(f"MT5 close failed: {err}")

        return Order(
            order_id=str(result.order),
            symbol=result.request.symbol if hasattr(result, 'request') else "",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            size=result.volume,
            price=None,
            filled_price=result.price,
            filled_time=datetime.now(timezone.utc),
            status=OrderStatus.FILLED,
            created_time=datetime.now(timezone.utc),
        )

    # ── Orders ────────────────────────────────────────

    async def place_order(self, request: OrderRequest) -> Order:
        def _do_order():
            symbol_info = mt5.symbol_info(request.symbol)
            if symbol_info is None:
                raise ValueError(f"Symbol {request.symbol} not found")
            if not symbol_info.visible:
                mt5.symbol_select(request.symbol, True)

            # Get current price for market orders
            tick = mt5.symbol_info_tick(request.symbol)
            if tick is None:
                raise RuntimeError(f"Cannot get tick for {request.symbol}")

            if request.side == OrderSide.BUY:
                order_type = mt5.ORDER_TYPE_BUY
                price = tick.ask
            else:
                order_type = mt5.ORDER_TYPE_SELL
                price = tick.bid

            # Build request
            mt5_request: dict = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": request.symbol,
                "volume": request.size,
                "type": order_type,
                "price": price,
                "deviation": 20,
                "magic": 100,
                "comment": request.comment or "tradeforge",
                "type_time": mt5.ORDER_TIME_GTC,
            }

            if request.order_type == OrderType.LIMIT:
                mt5_request["action"] = mt5.TRADE_ACTION_PENDING
                mt5_request["type"] = (
                    mt5.ORDER_TYPE_BUY_LIMIT if request.side == OrderSide.BUY
                    else mt5.ORDER_TYPE_SELL_LIMIT
                )
                mt5_request["price"] = request.price

            elif request.order_type == OrderType.STOP:
                mt5_request["action"] = mt5.TRADE_ACTION_PENDING
                mt5_request["type"] = (
                    mt5.ORDER_TYPE_BUY_STOP if request.side == OrderSide.BUY
                    else mt5.ORDER_TYPE_SELL_STOP
                )
                mt5_request["price"] = request.price

            if request.stop_loss:
                mt5_request["sl"] = request.stop_loss
            if request.take_profit:
                mt5_request["tp"] = request.take_profit

            result = _order_send_with_filling_fallback(mt5_request)
            return result

        result = await self._run(_do_order)

        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = result.comment if result else "unknown"
            code = result.retcode if result else -1
            raise RuntimeError(f"MT5 order failed ({code}): {err}")

        return Order(
            order_id=str(result.order),
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            size=request.size,
            price=request.price,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            filled_price=result.price,
            filled_time=datetime.now(timezone.utc),
            status=OrderStatus.FILLED if request.order_type == OrderType.MARKET else OrderStatus.PENDING,
            created_time=datetime.now(timezone.utc),
        )

    async def modify_order(self, request: OrderModifyRequest) -> Order:
        def _do_modify():
            # Try modifying position SL/TP first
            positions = mt5.positions_get()
            for p in (positions or []):
                if str(p.ticket) == request.order_id:
                    mod_request = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "symbol": p.symbol,
                        "position": p.ticket,
                        "sl": request.stop_loss or p.sl,
                        "tp": request.take_profit or p.tp,
                    }
                    return mt5.order_send(mod_request), p.symbol

            # Try modifying pending order
            orders = mt5.orders_get()
            for o in (orders or []):
                if str(o.ticket) == request.order_id:
                    mod_request = {
                        "action": mt5.TRADE_ACTION_MODIFY,
                        "order": o.ticket,
                        "price": request.price or o.price_open,
                        "sl": request.stop_loss or o.sl,
                        "tp": request.take_profit or o.tp,
                    }
                    return mt5.order_send(mod_request), o.symbol

            raise ValueError(f"Order/position {request.order_id} not found")

        result, symbol = await self._run(_do_modify)

        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = result.comment if result else "unknown"
            raise RuntimeError(f"MT5 modify failed: {err}")

        return Order(
            order_id=request.order_id,
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=0,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            status=OrderStatus.PENDING,
        )

    async def cancel_order(self, order_id: str) -> bool:
        def _do_cancel():
            ticket = int(order_id)
            orders = mt5.orders_get()
            target = None
            for o in (orders or []):
                if o.ticket == ticket:
                    target = o
                    break

            if not target:
                return False

            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": ticket,
            }
            result = mt5.order_send(request)
            return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE

        try:
            return await self._run(_do_cancel)
        except Exception as e:
            logger.error("MT5 cancel order failed: %s", e)
            return False

    async def get_open_orders(self) -> list[Order]:
        raw = await self._run(mt5.orders_get)
        if raw is None:
            return []

        orders: list[Order] = []
        for o in raw:
            # Map MT5 order types
            if o.type in (2, 3):   # BUY_LIMIT, SELL_LIMIT
                otype = OrderType.LIMIT
            elif o.type in (4, 5): # BUY_STOP, SELL_STOP
                otype = OrderType.STOP
            else:
                otype = OrderType.MARKET

            side = OrderSide.BUY if o.type in (0, 2, 4) else OrderSide.SELL

            orders.append(Order(
                order_id=str(o.ticket),
                symbol=o.symbol,
                side=side,
                order_type=otype,
                size=o.volume_current,
                price=o.price_open,
                stop_loss=o.sl if o.sl > 0 else None,
                take_profit=o.tp if o.tp > 0 else None,
                status=OrderStatus.PENDING,
                created_time=datetime.fromtimestamp(o.time_setup, tz=timezone.utc),
            ))

        return orders

    # ── Market Data ───────────────────────────────────

    async def get_symbols(self) -> list[SymbolInfo]:
        def _do_get():
            all_symbols = mt5.symbols_get()
            if not all_symbols:
                return []
            return all_symbols

        raw = await self._run(_do_get)
        symbols: list[SymbolInfo] = []

        for s in raw:
            if not s.visible:
                continue

            symbols.append(SymbolInfo(
                symbol=s.name,
                display_name=s.description or s.name,
                base_currency=s.currency_base,
                quote_currency=s.currency_profit,
                pip_size=s.point,
                min_lot=s.volume_min,
                max_lot=s.volume_max,
                lot_step=s.volume_step,
                margin_rate=0,
                tradeable=s.trade_mode > 0,
                asset_class=_classify_mt5_symbol(s),
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
        tf = _TF_MAP.get(timeframe, mt5.TIMEFRAME_H1 if _MT5_AVAILABLE else 0)

        def _do_get():
            if from_time:
                rates = mt5.copy_rates_from(symbol, tf, from_time, count)
            else:
                rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
            return rates

        raw = await self._run(_do_get)
        if raw is None:
            return []

        candles: list[Candle] = []
        for r in raw:
            candles.append(Candle(
                timestamp=datetime.fromtimestamp(r['time'], tz=timezone.utc),
                open=float(r['open']),
                high=float(r['high']),
                low=float(r['low']),
                close=float(r['close']),
                volume=float(r['tick_volume']),
            ))

        return candles

    async def get_price(self, symbol: str) -> PriceTick:
        def _do_get():
            # Make sure symbol is visible
            mt5.symbol_select(symbol, True)
            tick = mt5.symbol_info_tick(symbol)
            return tick

        tick = await self._run(_do_get)
        if tick is None:
            raise RuntimeError(f"No tick data for {symbol}")

        return PriceTick(
            symbol=symbol,
            bid=tick.bid,
            ask=tick.ask,
            timestamp=datetime.fromtimestamp(tick.time, tz=timezone.utc),
            spread=tick.ask - tick.bid,
        )

    # ── Initial bars for chart ─────────────────────────

    async def get_initial_bars(self, symbol: str, timeframe: str, count: int = 500) -> list[dict]:
        """
        Get historical bars for chart initialization.
        Returns list of { time, open, high, low, close, volume } dicts.
        """
        tf = _TF_MAP.get(timeframe, mt5.TIMEFRAME_H1 if _MT5_AVAILABLE else 0)

        def _do_get():
            mt5.symbol_select(symbol, True)
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
            return rates

        raw = await self._run(_do_get)
        if raw is None:
            return []

        bars = []
        for r in raw:
            bars.append({
                "time": int(r['time']),
                "open": float(r['open']),
                "high": float(r['high']),
                "low": float(r['low']),
                "close": float(r['close']),
                "volume": float(r['tick_volume']),
            })
        return bars

    # ── Streaming ─────────────────────────────────────

    async def stream_prices(self, symbols: list[str]) -> AsyncGenerator[PriceTick, None]:
        """Poll MT5 ticks every second."""
        while True:
            for sym in symbols:
                try:
                    tick = await self.get_price(sym)
                    yield tick
                except Exception:
                    pass
            await asyncio.sleep(1)


def _classify_mt5_symbol(s) -> str:
    """Attempt to classify an MT5 symbol into an asset class."""
    path = (s.path or "").lower()
    if "forex" in path or "fx" in path:
        return "forex"
    elif "crypto" in path:
        return "crypto"
    elif "indices" in path or "index" in path:
        return "index"
    elif "commodit" in path or "metal" in path:
        return "commodity"
    elif "stock" in path or "equit" in path:
        return "stock"
    elif "future" in path:
        return "futures"
    return "other"
