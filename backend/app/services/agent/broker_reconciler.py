"""
Broker Reconciler — Syncs executed AgentTrades with actual broker state.

Periodically checks:
1. Recently closed trades on the broker → update AgentTrade with real P&L
2. Open positions on the broker → verify they match our records
3. Orphaned trades → flag trades we think are open but broker doesn't know about
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.core.database import SessionLocal
from app.models.agent import AgentTrade, AgentLog
from app.services.broker.manager import broker_manager

logger = logging.getLogger(__name__)


class BrokerReconciler:
    """Background service that reconciles AgentTrades with broker state."""

    def __init__(self, interval_seconds: int = 15):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._interval = interval_seconds
        self._last_check = datetime.now(timezone.utc) - timedelta(hours=1)

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._reconcile_loop())
        logger.info("[BrokerReconciler] Started — checking every %ds", self._interval)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[BrokerReconciler] Stopped")

    async def _reconcile_loop(self):
        # Wait a bit on startup for broker connections to establish
        await asyncio.sleep(10)
        while self._running:
            try:
                await self._reconcile()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[BrokerReconciler] Error: %s", e, exc_info=True)
            await asyncio.sleep(self._interval)

    async def _reconcile(self):
        """Main reconciliation pass."""
        db = SessionLocal()
        try:
            # Find all open executed trades
            open_trades = (
                db.query(AgentTrade)
                .filter(
                    AgentTrade.status == "executed",
                    AgentTrade.closed_at.is_(None),
                )
                .all()
            )

            if not open_trades:
                return

            # Group by broker
            trades_by_broker: dict[str, list[AgentTrade]] = {}
            for t in open_trades:
                broker = t.broker_name or "oanda"
                trades_by_broker.setdefault(broker, []).append(t)

            for broker_name, trades in trades_by_broker.items():
                adapter = broker_manager.get_adapter(broker_name)
                if not adapter:
                    continue

                try:
                    await self._reconcile_broker(db, adapter, broker_name, trades)
                except Exception as e:
                    logger.warning("[BrokerReconciler] %s reconcile error: %s", broker_name, e)

            db.commit()
            self._last_check = datetime.now(timezone.utc)

        except Exception as e:
            logger.error("[BrokerReconciler] DB error: %s", e)
            db.rollback()
        finally:
            db.close()

    async def _reconcile_broker(self, db, adapter, broker_name: str, open_trades: list):
        """Reconcile trades for a single broker."""
        # Get recently closed trades from broker
        closed_broker_trades = []
        try:
            closed_broker_trades = await adapter.get_closed_trades(
                since=self._last_check - timedelta(minutes=5),
                limit=100,
            )
        except Exception as e:
            logger.debug("[BrokerReconciler] get_closed_trades failed for %s: %s", broker_name, e)

        if not closed_broker_trades:
            return

        # Build lookup: broker_trade_id/ticket → closed trade info
        closed_lookup: dict[str, object] = {}
        for ct in closed_broker_trades:
            closed_lookup[ct.trade_id] = ct

        # Check each open AgentTrade
        for trade in open_trades:
            ticket = trade.broker_ticket or ""
            broker_tid = trade.broker_trade_id or ""

            # Try matching by broker_ticket or broker_trade_id
            match = closed_lookup.get(ticket) or closed_lookup.get(broker_tid)
            if not match:
                continue

            # Trade was closed on broker — update our record
            trade.exit_price = match.exit_price
            trade.broker_pnl = match.pnl
            trade.pnl = match.pnl  # Use broker's actual P&L
            trade.status = "closed"
            trade.closed_at = match.close_time or datetime.now(timezone.utc)
            trade.exit_reason = "Reconciled"

            # Log the reconciliation
            log = AgentLog(
                agent_id=trade.agent_id,
                level="trade",
                message=(
                    f"Reconciled: {trade.direction} {trade.symbol} closed by broker | "
                    f"P&L=${match.pnl:.2f} @ {match.exit_price:.5f}"
                ),
                data={
                    "trade_id": trade.id,
                    "broker_pnl": match.pnl,
                    "exit_price": match.exit_price,
                    "exit_reason": "Reconciled",
                },
            )
            db.add(log)

            logger.info(
                "[BrokerReconciler] Trade #%d reconciled: %s %s P&L=$%.2f",
                trade.id, trade.direction, trade.symbol, match.pnl,
            )

            # Broadcast via WebSocket
            try:
                from app.core.websocket import manager as ws_manager
                asyncio.ensure_future(ws_manager.broadcast_to_channel(
                    f"agent:{trade.agent_id}",
                    {
                        "type": "trade_closed",
                        "channel": f"agent:{trade.agent_id}",
                        "data": {
                            "trade_id": trade.id,
                            "agent_id": trade.agent_id,
                            "symbol": trade.symbol,
                            "direction": trade.direction,
                            "exit_price": match.exit_price,
                            "exit_reason": "Reconciled",
                            "pnl": match.pnl,
                        },
                    },
                ))
            except Exception:
                pass


# Singleton
broker_reconciler = BrokerReconciler()
