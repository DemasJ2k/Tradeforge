"""
MT5 Bridge Server — Standalone FastAPI service for Windows VPS.

This runs alongside the MT5 terminal on a Windows machine and exposes
MetaTrader 5 operations as a REST API that the main FlowrexAlgo backend
(deployed on Render/Linux) can call remotely.

Deployment:
  1. Install on a Windows VPS with MT5 terminal running
  2. pip install fastapi uvicorn MetaTrader5
  3. Set MT5_BRIDGE_API_KEY env var for authentication
  4. python mt5_bridge_server.py

The main backend connects via HTTPS to this service.
"""

import os
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
import uvicorn

try:
    import MetaTrader5 as mt5
except ImportError:
    raise SystemExit("MetaTrader5 package required: pip install MetaTrader5")

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger("mt5-bridge")

# ── Config ────────────────────────────────────────────
API_KEY = os.getenv("MT5_BRIDGE_API_KEY", "changeme-mt5-bridge-key")
HOST = os.getenv("MT5_BRIDGE_HOST", "0.0.0.0")
PORT = int(os.getenv("MT5_BRIDGE_PORT", "8010"))

# Thread pool for sync MT5 calls
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mt5")

# ── Auth ──────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-Bridge-Key", auto_error=False)

async def verify_key(key: str = Security(api_key_header)):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid bridge API key")
    return key

# ── Timeframe mapping ─────────────────────────────────
TF_MAP = {
    "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1,
    "MN1": mt5.TIMEFRAME_MN1,
    "1m": mt5.TIMEFRAME_M1, "5m": mt5.TIMEFRAME_M5,
    "15m": mt5.TIMEFRAME_M15, "30m": mt5.TIMEFRAME_M30,
    "1h": mt5.TIMEFRAME_H1, "4h": mt5.TIMEFRAME_H4,
    "1d": mt5.TIMEFRAME_D1,
}

# ── Schemas ───────────────────────────────────────────

class ConnectRequest(BaseModel):
    server: str
    login: int
    password: str

class PlaceOrderRequest(BaseModel):
    symbol: str
    side: str               # "BUY" | "SELL"
    size: float
    order_type: str = "MARKET"  # "MARKET" | "LIMIT" | "STOP"
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    comment: str = "tradeforge"

class ModifyOrderRequest(BaseModel):
    order_id: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    price: Optional[float] = None

class CandlesRequest(BaseModel):
    symbol: str
    timeframe: str = "H1"
    count: int = 500
    from_time: Optional[int] = None  # Unix timestamp

# ── Helper ────────────────────────────────────────────

async def _run(func, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_pool, func, *args)


def _order_send_with_filling_fallback(request: dict):
    filling_modes = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
    last_result = None
    for filling in filling_modes:
        req = {**request, "type_filling": filling}
        result = mt5.order_send(req)
        if result is None:
            last_result = result
            continue
        if result.retcode == 10030:
            last_result = result
            continue
        return result
    return last_result


def _classify_symbol(s) -> str:
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

# ── App ───────────────────────────────────────────────

app = FastAPI(title="MT5 Bridge Server", version="1.0.0")

# Track connection state
_state = {"connected": False, "login": 0, "server": ""}


# ── Health ────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "connected": _state["connected"], "login": _state["login"]}


# ── Connection ────────────────────────────────────────

@app.post("/connect", dependencies=[Depends(verify_key)])
async def connect(req: ConnectRequest):
    def _do():
        if not mt5.initialize():
            return {"ok": False, "error": str(mt5.last_error())}
        authorized = mt5.login(login=req.login, password=req.password, server=req.server)
        if not authorized:
            err = str(mt5.last_error())
            mt5.shutdown()
            return {"ok": False, "error": err}
        info = mt5.account_info()
        return {
            "ok": True,
            "login": info.login,
            "server": info.server,
            "balance": info.balance,
            "currency": info.currency,
        }

    result = await _run(_do)
    if result["ok"]:
        _state["connected"] = True
        _state["login"] = result["login"]
        _state["server"] = result.get("server", "")
        logger.info("Connected: account %s on %s", result["login"], result.get("server"))
    return result


@app.post("/disconnect", dependencies=[Depends(verify_key)])
async def disconnect():
    await _run(mt5.shutdown)
    _state["connected"] = False
    _state["login"] = 0
    return {"ok": True}


@app.get("/is_connected", dependencies=[Depends(verify_key)])
async def is_connected():
    def _do():
        info = mt5.account_info()
        return info is not None
    try:
        alive = await _run(_do)
        _state["connected"] = alive
        return {"connected": alive}
    except Exception:
        _state["connected"] = False
        return {"connected": False}


# ── Account ───────────────────────────────────────────

@app.get("/account", dependencies=[Depends(verify_key)])
async def get_account():
    def _do():
        info = mt5.account_info()
        if not info:
            return None
        return {
            "account_id": str(info.login),
            "broker": "mt5",
            "currency": info.currency,
            "balance": info.balance,
            "equity": info.equity,
            "unrealized_pnl": info.profit,
            "margin_used": info.margin,
            "margin_available": info.margin_free,
        }

    data = await _run(_do)
    if data is None:
        raise HTTPException(500, "MT5 account_info failed")
    return data


# ── Positions ─────────────────────────────────────────

@app.get("/positions", dependencies=[Depends(verify_key)])
async def get_positions():
    def _do():
        raw = mt5.positions_get()
        if raw is None:
            return []
        positions = []
        for p in raw:
            positions.append({
                "position_id": str(p.ticket),
                "symbol": p.symbol,
                "side": "LONG" if p.type == 0 else "SHORT",
                "size": p.volume,
                "entry_price": p.price_open,
                "current_price": p.price_current,
                "unrealized_pnl": p.profit,
                "margin_used": 0,
                "open_time": datetime.fromtimestamp(p.time, tz=timezone.utc).isoformat(),
                "stop_loss": p.sl if p.sl > 0 else None,
                "take_profit": p.tp if p.tp > 0 else None,
            })
        return positions

    return await _run(_do)


@app.post("/positions/close", dependencies=[Depends(verify_key)])
async def close_position(position_id: str, size: Optional[float] = None):
    ticket = int(position_id)

    def _do():
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return {"ok": False, "error": f"Position {ticket} not found"}
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
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = result.comment if result else "unknown"
            return {"ok": False, "error": f"Close failed: {err}"}
        return {
            "ok": True,
            "order_id": str(result.order),
            "symbol": p.symbol,
            "filled_price": result.price,
            "volume": result.volume,
        }

    return await _run(_do)


# ── Orders ────────────────────────────────────────────

@app.post("/orders", dependencies=[Depends(verify_key)])
async def place_order(req: PlaceOrderRequest):
    def _do():
        symbol_info = mt5.symbol_info(req.symbol)
        if symbol_info is None:
            return {"ok": False, "error": f"Symbol {req.symbol} not found"}
        if not symbol_info.visible:
            mt5.symbol_select(req.symbol, True)

        tick = mt5.symbol_info_tick(req.symbol)
        if tick is None:
            return {"ok": False, "error": f"No tick for {req.symbol}"}

        is_buy = req.side.upper() == "BUY"
        price = tick.ask if is_buy else tick.bid

        mt5_req: dict = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": req.symbol,
            "volume": req.size,
            "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
            "price": price,
            "deviation": 20,
            "magic": 100,
            "comment": req.comment,
            "type_time": mt5.ORDER_TIME_GTC,
        }

        if req.order_type == "LIMIT":
            mt5_req["action"] = mt5.TRADE_ACTION_PENDING
            mt5_req["type"] = mt5.ORDER_TYPE_BUY_LIMIT if is_buy else mt5.ORDER_TYPE_SELL_LIMIT
            mt5_req["price"] = req.price
        elif req.order_type == "STOP":
            mt5_req["action"] = mt5.TRADE_ACTION_PENDING
            mt5_req["type"] = mt5.ORDER_TYPE_BUY_STOP if is_buy else mt5.ORDER_TYPE_SELL_STOP
            mt5_req["price"] = req.price

        if req.stop_loss:
            mt5_req["sl"] = req.stop_loss
        if req.take_profit:
            mt5_req["tp"] = req.take_profit

        result = _order_send_with_filling_fallback(mt5_req)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = result.comment if result else "unknown"
            code = result.retcode if result else -1
            return {"ok": False, "error": f"Order failed ({code}): {err}"}

        return {
            "ok": True,
            "order_id": str(result.order),
            "filled_price": result.price,
            "volume": result.volume,
        }

    return await _run(_do)


@app.put("/orders", dependencies=[Depends(verify_key)])
async def modify_order(req: ModifyOrderRequest):
    def _do():
        # Try modifying position SL/TP
        positions = mt5.positions_get()
        for p in (positions or []):
            if str(p.ticket) == req.order_id:
                mod_req = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "symbol": p.symbol,
                    "position": p.ticket,
                    "sl": req.stop_loss or p.sl,
                    "tp": req.take_profit or p.tp,
                }
                result = mt5.order_send(mod_req)
                if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                    err = result.comment if result else "unknown"
                    return {"ok": False, "error": f"Modify failed: {err}"}
                return {"ok": True, "order_id": req.order_id, "symbol": p.symbol}

        # Try modifying pending order
        orders = mt5.orders_get()
        for o in (orders or []):
            if str(o.ticket) == req.order_id:
                mod_req = {
                    "action": mt5.TRADE_ACTION_MODIFY,
                    "order": o.ticket,
                    "price": req.price or o.price_open,
                    "sl": req.stop_loss or o.sl,
                    "tp": req.take_profit or o.tp,
                }
                result = mt5.order_send(mod_req)
                if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                    err = result.comment if result else "unknown"
                    return {"ok": False, "error": f"Modify failed: {err}"}
                return {"ok": True, "order_id": req.order_id, "symbol": o.symbol}

        return {"ok": False, "error": f"Order/position {req.order_id} not found"}

    return await _run(_do)


@app.delete("/orders/{order_id}", dependencies=[Depends(verify_key)])
async def cancel_order(order_id: str):
    ticket = int(order_id)

    def _do():
        orders = mt5.orders_get()
        for o in (orders or []):
            if o.ticket == ticket:
                request = {"action": mt5.TRADE_ACTION_REMOVE, "order": ticket}
                result = mt5.order_send(request)
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    return {"ok": True}
                err = result.comment if result else "unknown"
                return {"ok": False, "error": err}
        return {"ok": False, "error": "Order not found"}

    return await _run(_do)


@app.get("/orders", dependencies=[Depends(verify_key)])
async def get_open_orders():
    def _do():
        raw = mt5.orders_get()
        if raw is None:
            return []
        orders = []
        for o in raw:
            if o.type in (2, 3):
                otype = "LIMIT"
            elif o.type in (4, 5):
                otype = "STOP"
            else:
                otype = "MARKET"
            side = "BUY" if o.type in (0, 2, 4) else "SELL"
            orders.append({
                "order_id": str(o.ticket),
                "symbol": o.symbol,
                "side": side,
                "order_type": otype,
                "size": o.volume_current,
                "price": o.price_open,
                "stop_loss": o.sl if o.sl > 0 else None,
                "take_profit": o.tp if o.tp > 0 else None,
                "status": "PENDING",
                "created_time": datetime.fromtimestamp(o.time_setup, tz=timezone.utc).isoformat(),
            })
        return orders

    return await _run(_do)


# ── Market Data ───────────────────────────────────────

@app.get("/symbols", dependencies=[Depends(verify_key)])
async def get_symbols():
    def _do():
        all_symbols = mt5.symbols_get()
        if not all_symbols:
            return []
        symbols = []
        for s in all_symbols:
            if not s.visible:
                continue
            symbols.append({
                "symbol": s.name,
                "display_name": s.description or s.name,
                "base_currency": s.currency_base,
                "quote_currency": s.currency_profit,
                "pip_size": s.point,
                "min_lot": s.volume_min,
                "max_lot": s.volume_max,
                "lot_step": s.volume_step,
                "margin_rate": 0,
                "tradeable": s.trade_mode > 0,
                "asset_class": _classify_symbol(s),
            })
        return symbols

    return await _run(_do)


@app.post("/candles", dependencies=[Depends(verify_key)])
async def get_candles(req: CandlesRequest):
    tf = TF_MAP.get(req.timeframe, mt5.TIMEFRAME_H1)

    def _do():
        mt5.symbol_select(req.symbol, True)
        if req.from_time:
            dt = datetime.fromtimestamp(req.from_time, tz=timezone.utc)
            rates = mt5.copy_rates_from(req.symbol, tf, dt, req.count)
        else:
            rates = mt5.copy_rates_from_pos(req.symbol, tf, 0, req.count)
        if rates is None:
            return []
        candles = []
        for r in rates:
            candles.append({
                "time": int(r["time"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r["tick_volume"]),
            })
        return candles

    return await _run(_do)


@app.get("/price/{symbol}", dependencies=[Depends(verify_key)])
async def get_price(symbol: str):
    def _do():
        mt5.symbol_select(symbol, True)
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        return {
            "symbol": symbol,
            "bid": tick.bid,
            "ask": tick.ask,
            "timestamp": datetime.fromtimestamp(tick.time, tz=timezone.utc).isoformat(),
            "spread": tick.ask - tick.bid,
        }

    data = await _run(_do)
    if data is None:
        raise HTTPException(404, f"No tick data for {symbol}")
    return data


# ── Main ──────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting MT5 Bridge Server on %s:%d", HOST, PORT)
    logger.info("API Key: %s...", API_KEY[:8])
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
