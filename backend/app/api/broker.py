"""
Broker / Live Trading API endpoints.

Manages broker connections, positions, orders, and market data.
All endpoints are async to properly work with the async broker adapters.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.auth import get_current_user
from app.models.user import User
from app.models.trade import Trade
from app.schemas.broker import (
    BrokerConnectRequest,
    BrokerListResponse,
    BrokerStatusResponse,
    AccountInfoResponse,
    PositionResponse,
    ClosePositionRequest,
    PlaceOrderRequest,
    ModifyOrderRequest,
    CancelOrderRequest,
    OrderResponse,
    SymbolInfoResponse,
    PriceTickResponse,
    CandleResponse,
)
from app.services.broker.base import (
    OrderRequest,
    OrderSide,
    OrderType,
    OrderModifyRequest,
)
from app.services.broker.manager import broker_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/broker", tags=["broker"])


# ── Helpers ────────────────────────────────────────────

def _get_adapter(broker: Optional[str] = None):
    """Get broker adapter or raise 400."""
    adapter = broker_manager.get_adapter(broker)
    if not adapter:
        raise HTTPException(
            status_code=400,
            detail=f"No broker connected" + (f" ({broker})" if broker else ""),
        )
    return adapter


# ── Connection ─────────────────────────────────────────

@router.post("/connect")
async def connect_broker(
    payload: BrokerConnectRequest,
    user: User = Depends(get_current_user),
):
    """Connect to a broker."""
    if payload.broker == "oanda":
        from app.services.broker.oanda import OandaAdapter
        adapter = OandaAdapter(
            api_key=payload.api_key,
            account_id=payload.account_id,
            practice=payload.practice,
        )
    elif payload.broker == "coinbase":
        from app.services.broker.coinbase import CoinbaseAdapter
        adapter = CoinbaseAdapter(
            api_key=payload.api_key,
            api_secret=payload.extra.get("api_secret", payload.account_id),
        )
    elif payload.broker == "mt5":
        # Use remote bridge adapter when MT5_BRIDGE_URL is configured (Linux/Render),
        # otherwise fall back to local MT5 terminal adapter (Windows dev).
        import os
        if os.getenv("MT5_BRIDGE_URL"):
            from app.services.broker.mt5_remote import MT5RemoteAdapter
            adapter = MT5RemoteAdapter(
                server=payload.extra.get("server", ""),
                login=int(payload.extra.get("login", payload.account_id or "0")),
                password=payload.api_key,
            )
        else:
            from app.services.broker.mt5_bridge import MT5Adapter
            adapter = MT5Adapter(
                server=payload.extra.get("server", ""),
                login=int(payload.extra.get("login", payload.account_id or "0")),
                password=payload.api_key,
            )
    elif payload.broker == "tradovate":
        from app.services.broker.tradovate import TradovateAdapter
        adapter = TradovateAdapter(
            username=payload.extra.get("username", ""),
            password=payload.api_key,
            app_id=payload.extra.get("app_id", ""),
            app_version=payload.extra.get("app_version", "1.0"),
            cid=payload.extra.get("cid", ""),
            sec=payload.extra.get("sec", payload.account_id),
            demo=payload.practice,
        )
    elif payload.broker == "ctrader":
        import os
        from app.services.broker.ctrader import CTraderAdapter
        adapter = CTraderAdapter(
            client_id=payload.extra.get("client_id", os.getenv("CTRADER_CLIENT_ID", "")),
            client_secret=payload.extra.get("client_secret", os.getenv("CTRADER_CLIENT_SECRET", "")),
            access_token=payload.access_token or payload.extra.get("access_token", ""),
            account_id=payload.account_id,
            server=payload.extra.get("server", "demo" if payload.practice else "live"),
        )
    else:
        raise HTTPException(400, f"Unsupported broker: {payload.broker}")

    success = await broker_manager.connect_broker(payload.broker, adapter)

    if not success:
        raise HTTPException(400, f"Failed to connect to {payload.broker}. Check credentials.")

    # Auto-register as market data provider for chart feed
    try:
        from app.services.market.provider import market_data, BrokerProvider
        market_data.register("broker", BrokerProvider(adapter))
        logger.info("Broker %s registered as market data provider", payload.broker)
    except Exception as e:
        logger.warning("Failed to register broker as market data provider: %s", e)

    return {"status": "connected", "broker": payload.broker}


@router.post("/disconnect/{broker_name}")
async def disconnect_broker(
    broker_name: str,
    user: User = Depends(get_current_user),
):
    """Disconnect a broker."""
    await broker_manager.disconnect_broker(broker_name)
    return {"status": "disconnected", "broker": broker_name}


@router.get("/status")
async def broker_status(user: User = Depends(get_current_user)):
    """Get status of all connected brokers."""
    status = await broker_manager.get_status()
    return BrokerListResponse(
        brokers={
            name: BrokerStatusResponse(**info)
            for name, info in status.items()
        },
        default_broker=broker_manager.default_broker,
    )


@router.get("/debug/{broker_name}")
async def broker_debug(
    broker_name: str,
    symbol: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
):
    """Debug endpoint: internal state of a broker adapter."""
    adapter = _get_adapter(broker_name)
    info: dict = {"broker": broker_name, "connected": False}
    if not adapter:
        return info
    try:
        info["connected"] = await adapter.is_connected()
    except Exception:
        pass
    # cTrader-specific debug info
    if hasattr(adapter, "_symbol_cache"):
        info["symbol_cache_size"] = len(adapter._symbol_cache)
        info["symbol_name_to_id_size"] = len(adapter._symbol_name_to_id)
        info["symbol_names_sample"] = sorted(adapter._symbol_name_to_id.keys())[:20]
        # Lookup a specific symbol
        if symbol and hasattr(adapter, "_resolve_symbol_id"):
            try:
                sid = await adapter._resolve_symbol_id(symbol)
                sym_data = adapter._symbol_cache.get(sid, {})
                info["symbol_lookup"] = {
                    "query": symbol,
                    "resolved_id": sid,
                    "digits": sym_data.get("digits", "NOT_FOUND"),
                    "pipPosition": sym_data.get("pipPosition", "NOT_FOUND"),
                    "symbolName": sym_data.get("symbolName", "NOT_FOUND"),
                    "keys": list(sym_data.keys())[:15],
                }
            except Exception as e:
                info["symbol_lookup"] = {"query": symbol, "error": str(e)}
        # Sample a few cache entries to see their structure
        cache_sample = []
        for sid, sym_data in list(adapter._symbol_cache.items())[:3]:
            cache_sample.append({"symbolId": sid, "keys": list(sym_data.keys()), "data": {k: sym_data[k] for k in list(sym_data.keys())[:8]}})
        info["cache_sample"] = cache_sample
    if hasattr(adapter, "_last_error"):
        info["last_error"] = adapter._last_error
    if hasattr(adapter, "_account_id"):
        info["account_id"] = adapter._account_id
    if hasattr(adapter, "_server"):
        info["server"] = adapter._server
    if hasattr(adapter, "_host"):
        info["host"] = adapter._host
    return info


# ── Account ────────────────────────────────────────────

@router.get("/account")
async def get_account(
    broker: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
):
    """Get account info from broker."""
    adapter = _get_adapter(broker)
    info = await adapter.get_account_info()
    return AccountInfoResponse(
        account_id=info.account_id,
        broker=info.broker,
        currency=info.currency,
        balance=info.balance,
        equity=info.equity,
        unrealized_pnl=info.unrealized_pnl,
        margin_used=info.margin_used,
        margin_available=info.margin_available,
        open_positions=info.open_positions,
        open_orders=info.open_orders,
    )


# ── Positions ──────────────────────────────────────────

@router.get("/positions")
async def get_positions(
    broker: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all open positions with agent attribution."""
    from app.models.agent import AgentTrade, TradingAgent

    adapter = _get_adapter(broker)
    try:
        positions = await adapter.get_positions()
    except Exception as e:
        logger.error("get_positions failed for broker=%s: %s", broker or "default", e, exc_info=True)
        raise HTTPException(502, f"Failed to fetch positions from broker: {e}")
    logger.info("Broker positions: got %d positions from %s", len(positions), broker or "default")

    # Build agent lookup: broker_ticket -> (agent_name, agent_id, strategy)
    agent_map: dict[str, dict] = {}
    try:
        from app.models.strategy import Strategy

        executed_trades = (
            db.query(
                AgentTrade.broker_ticket,
                AgentTrade.agent_id,
                TradingAgent.name.label("agent_name"),
                Strategy.name.label("strategy_name"),
            )
            .join(TradingAgent, AgentTrade.agent_id == TradingAgent.id)
            .outerjoin(Strategy, TradingAgent.strategy_id == Strategy.id)
            .filter(
                TradingAgent.created_by == user.id,
                AgentTrade.status.in_(["executed", "confirmed"]),
                AgentTrade.broker_ticket.isnot(None),
            )
            .all()
        )
        for ticket, agent_id, agent_name, strategy_name in executed_trades:
            if ticket:
                agent_map[ticket] = {
                    "agent_name": agent_name,
                    "agent_id": agent_id,
                    "strategy_name": strategy_name,
                }
    except Exception:
        pass  # Agent lookup is best-effort

    result = []
    for p in positions:
        agent_info = agent_map.get(p.position_id, {})
        result.append(PositionResponse(
            position_id=p.position_id,
            symbol=p.symbol,
            side=p.side.value,
            size=p.size,
            entry_price=p.entry_price,
            current_price=p.current_price,
            unrealized_pnl=p.unrealized_pnl,
            margin_used=p.margin_used,
            open_time=p.open_time.isoformat(),
            stop_loss=p.stop_loss,
            take_profit=p.take_profit,
            agent_name=agent_info.get("agent_name"),
            agent_id=agent_info.get("agent_id"),
            strategy_name=agent_info.get("strategy_name"),
        ))
    return result


@router.post("/positions/close")
async def close_position(
    payload: ClosePositionRequest,
    broker: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Close a position (fully or partially)."""
    adapter = _get_adapter(broker)
    order = await adapter.close_position(payload.position_id, payload.size)

    # Log trade to DB
    trade = Trade(
        user_id=user.id,
        broker=adapter.broker_name,
        symbol=order.symbol,
        direction=order.side.value,
        entry_price=0,
        exit_price=order.filled_price or 0,
        entry_time=order.created_time or order.filled_time,
        exit_time=order.filled_time,
        lot_size=order.size,
        pnl=0,
        status="closed",
    )
    db.add(trade)
    db.commit()

    # Fire webhooks
    try:
        from app.services.webhook import fire_webhooks
        await fire_webhooks(db, user.id, "trade_closed", {
            "symbol": order.symbol,
            "direction": order.side.value,
            "size": order.size,
            "exit_price": order.filled_price,
            "broker": adapter.broker_name,
        })
    except Exception:
        pass  # Webhook failure should not break trading

    return OrderResponse(
        order_id=order.order_id,
        symbol=order.symbol,
        side=order.side.value,
        order_type=order.order_type.value,
        size=order.size,
        status=order.status.value,
        filled_price=order.filled_price,
        filled_time=order.filled_time.isoformat() if order.filled_time else None,
    )


# ── Orders ─────────────────────────────────────────────

@router.post("/orders")
async def place_order(
    payload: PlaceOrderRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Place a new order."""
    adapter = _get_adapter(payload.broker)

    request = OrderRequest(
        symbol=payload.symbol,
        side=OrderSide(payload.side),
        size=payload.size,
        order_type=OrderType(payload.order_type),
        price=payload.price,
        stop_loss=payload.stop_loss,
        take_profit=payload.take_profit,
        trailing_stop_distance=payload.trailing_stop_distance,
        comment=payload.comment,
    )

    order = await adapter.place_order(request)

    # Log trade to DB if filled
    if order.status.value == "FILLED":
        trade = Trade(
            user_id=user.id,
            broker=adapter.broker_name,
            symbol=order.symbol,
            direction=order.side.value,
            entry_price=order.filled_price or 0,
            entry_time=order.filled_time or order.created_time,
            lot_size=order.size,
            stop_loss=payload.stop_loss,
            take_profit=payload.take_profit,
            status="open",
            metadata_={"order_id": order.order_id},
        )
        db.add(trade)
        db.commit()

        # Fire webhooks
        try:
            from app.services.webhook import fire_webhooks
            await fire_webhooks(db, user.id, "trade_opened", {
                "symbol": order.symbol,
                "direction": order.side.value,
                "size": order.size,
                "entry_price": order.filled_price,
                "stop_loss": payload.stop_loss,
                "take_profit": payload.take_profit,
                "broker": adapter.broker_name,
            })
        except Exception:
            pass  # Webhook failure should not break trading

    return OrderResponse(
        order_id=order.order_id,
        symbol=order.symbol,
        side=order.side.value,
        order_type=order.order_type.value,
        size=order.size,
        price=order.price,
        stop_loss=order.stop_loss,
        take_profit=order.take_profit,
        status=order.status.value,
        filled_price=order.filled_price,
        filled_time=order.filled_time.isoformat() if order.filled_time else None,
        created_time=order.created_time.isoformat() if order.created_time else None,
    )


@router.put("/orders")
async def modify_order(
    payload: ModifyOrderRequest,
    user: User = Depends(get_current_user),
):
    """Modify a pending order or position SL/TP."""
    adapter = _get_adapter(payload.broker)

    request = OrderModifyRequest(
        order_id=payload.order_id,
        stop_loss=payload.stop_loss,
        take_profit=payload.take_profit,
        price=payload.price,
        trailing_stop_distance=payload.trailing_stop_distance,
    )

    order = await adapter.modify_order(request)

    return OrderResponse(
        order_id=order.order_id,
        symbol=order.symbol,
        side=order.side.value,
        order_type=order.order_type.value,
        size=order.size,
        price=order.price,
        stop_loss=order.stop_loss,
        take_profit=order.take_profit,
        status=order.status.value,
    )


@router.delete("/orders/{order_id}")
async def cancel_order(
    order_id: str,
    broker: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
):
    """Cancel a pending order."""
    adapter = _get_adapter(broker)
    success = await adapter.cancel_order(order_id)

    if not success:
        raise HTTPException(400, f"Failed to cancel order {order_id}")

    return {"status": "cancelled", "order_id": order_id}


@router.get("/orders")
async def get_open_orders(
    broker: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
):
    """Get all pending orders."""
    adapter = _get_adapter(broker)
    orders = await adapter.get_open_orders()

    return [
        OrderResponse(
            order_id=o.order_id,
            symbol=o.symbol,
            side=o.side.value,
            order_type=o.order_type.value,
            size=o.size,
            price=o.price,
            stop_loss=o.stop_loss,
            take_profit=o.take_profit,
            status=o.status.value,
            created_time=o.created_time.isoformat() if o.created_time else None,
        )
        for o in orders
    ]


# ── Market Data ────────────────────────────────────────

@router.get("/symbols")
async def get_symbols(
    broker: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
):
    """Get tradeable instruments from broker."""
    adapter = _get_adapter(broker)
    try:
        symbols = await adapter.get_symbols()
    except (ConnectionError, TimeoutError):
        # Connection dropped — try reconnecting
        try:
            ok = await adapter.connect()
            symbols = await adapter.get_symbols() if ok else []
        except Exception:
            symbols = []
    except Exception as e:
        logger.warning("get_symbols failed for broker=%s: %s", broker, e)
        symbols = []

    if search:
        search_lower = search.lower()
        symbols = [
            s for s in symbols
            if search_lower in s.symbol.lower()
            or search_lower in s.display_name.lower()
        ]

    return [
        SymbolInfoResponse(
            symbol=s.symbol,
            display_name=s.display_name,
            base_currency=s.base_currency,
            quote_currency=s.quote_currency,
            pip_size=s.pip_size,
            min_lot=s.min_lot,
            max_lot=s.max_lot,
            lot_step=s.lot_step,
            margin_rate=s.margin_rate,
            tradeable=s.tradeable,
            asset_class=s.asset_class,
        )
        for s in symbols
    ]


@router.get("/price/{symbol}")
async def get_price(
    symbol: str,
    broker: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
):
    """Get current price for a symbol."""
    adapter = _get_adapter(broker)
    tick = await adapter.get_price(symbol)

    return PriceTickResponse(
        symbol=tick.symbol,
        bid=tick.bid,
        ask=tick.ask,
        spread=tick.spread,
        timestamp=tick.timestamp.isoformat(),
    )


@router.get("/candles/{symbol}")
async def get_candles(
    symbol: str,
    timeframe: str = Query("H1"),
    count: int = Query(100, ge=1, le=5000),
    broker: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
):
    """Get historical candles for a symbol."""
    adapter = _get_adapter(broker)
    try:
        candles = await adapter.get_candles(symbol, timeframe, count)
    except (ConnectionError, TimeoutError) as e:
        # Connection dropped — try reconnecting once
        logger.info("get_candles connection lost for %s, attempting reconnect...", broker)
        try:
            ok = await adapter.connect()
            if ok:
                candles = await adapter.get_candles(symbol, timeframe, count)
            else:
                logger.warning("get_candles reconnect failed for %s", broker)
                return []
        except Exception as e2:
            logger.warning("get_candles retry failed for %s/%s: %s", symbol, timeframe, e2)
            return []
    except Exception as e:
        logger.warning("get_candles failed for %s/%s (broker=%s): %s", symbol, timeframe, broker, e, exc_info=True)
        return []

    # Return time as Unix float to match CandleInput format expected by the chart
    return [
        {
            "time": c.timestamp.timestamp() if hasattr(c.timestamp, "timestamp") else float(c.timestamp),
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        }
        for c in candles
    ]


# ── Trade History ──────────────────────────────────────

@router.get("/trades")
async def get_trade_history(
    limit: int = Query(100, ge=1, le=500),
    status: Optional[str] = Query(None),
    include_agents: bool = Query(True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get unified trade history — broker trades + agent trades merged."""
    from sqlalchemy import or_
    from app.models.agent import AgentTrade, TradingAgent

    results: list[dict] = []

    # 1. Broker trades from Trade table
    q = db.query(Trade).filter(
        or_(Trade.user_id == user.id, Trade.user_id == None)  # noqa: E711
    )
    if status:
        q = q.filter(Trade.status == status)
    broker_trades = q.order_by(Trade.created_at.desc()).limit(limit).all()

    for t in broker_trades:
        meta = t.metadata_ or {}
        results.append({
            "id": t.id,
            "source": "broker",
            "broker": t.broker,
            "symbol": t.symbol,
            "direction": t.direction,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "entry_time": t.entry_time.isoformat() if t.entry_time else None,
            "exit_time": t.exit_time.isoformat() if t.exit_time else None,
            "lot_size": t.lot_size,
            "pnl": t.pnl,
            "commission": t.commission,
            "status": t.status,
            "stop_loss": t.stop_loss,
            "take_profit": t.take_profit,
            "exit_reason": meta.get("exit_reason"),
            "agent_name": meta.get("agent_name"),
            "agent_id": meta.get("agent_id"),
            "strategy_id": t.strategy_id,
            "duration_seconds": (
                (t.exit_time - t.entry_time).total_seconds()
                if t.exit_time and t.entry_time else None
            ),
            "sort_time": t.exit_time or t.entry_time or t.created_at,
        })

    # 2. Agent trades (if requested)
    if include_agents:
        agent_statuses = ["closed", "executed", "paper"]
        if status:
            agent_statuses = [s.strip() for s in status.split(",")]

        agent_rows = (
            db.query(AgentTrade, TradingAgent.name.label("agent_name"))
            .join(TradingAgent, AgentTrade.agent_id == TradingAgent.id)
            .filter(
                TradingAgent.created_by == user.id,
                TradingAgent.deleted_at.is_(None),
                AgentTrade.status.in_(agent_statuses),
            )
            .order_by(AgentTrade.created_at.desc())
            .limit(limit)
            .all()
        )

        for at, agent_name in agent_rows:
            entry_t = at.opened_at or at.created_at
            exit_t = at.closed_at
            results.append({
                "id": at.id,
                "source": "agent",
                "broker": at.broker_name or "paper",
                "symbol": at.symbol,
                "direction": at.direction,
                "entry_price": at.filled_price or at.entry_price,
                "exit_price": at.exit_price,
                "entry_time": entry_t.isoformat() if entry_t else None,
                "exit_time": exit_t.isoformat() if exit_t else None,
                "lot_size": at.lot_size or 0.01,
                "pnl": at.broker_pnl if at.broker_pnl is not None else at.pnl,
                "commission": 0.0,
                "status": at.status,
                "stop_loss": at.stop_loss,
                "take_profit": at.take_profit_1,
                "exit_reason": at.exit_reason,
                "agent_name": agent_name,
                "agent_id": at.agent_id,
                "strategy_id": None,
                "signal_type": at.signal_type,
                "signal_confidence": at.signal_confidence,
                "duration_seconds": (
                    (exit_t - entry_t).total_seconds()
                    if exit_t and entry_t else None
                ),
                "sort_time": exit_t or entry_t or at.created_at,
            })

    # Sort all results by time descending, then trim to limit
    results.sort(key=lambda x: x.get("sort_time") or "", reverse=True)
    for r in results:
        r.pop("sort_time", None)

    return results[:limit]
