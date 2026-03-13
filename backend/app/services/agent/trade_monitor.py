"""
Paper Trade Monitor — Simulates trade lifecycle for paper & agent trades.

Matches the exact exit logic from the backtester:
  1. Check TP2 first (highest priority exit)
  2. Check TP1 (if TP2 not hit and SL not hit on same bar)
  3. Check SL
  4. Track PnL and update DB

Subscribes to tick channels to monitor price against open trades' SL/TP levels.
Also handles reversal signals from the agent engine.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from app.core.database import SessionLocal
from app.models.agent import AgentTrade, TradingAgent, AgentLog

logger = logging.getLogger(__name__)


class PaperTradeMonitor:
    """
    Background service that monitors all open paper/executed agent trades
    and simulates exits when SL/TP levels are hit.

    Runs as a periodic task (checks every 2 seconds) using latest tick prices.
    """

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # Cache latest prices per symbol: { "XAUUSD": { "bid": ..., "ask": ..., "last": ... } }
        self._prices: dict[str, dict] = {}
        self._unsubscribers: list = []

    async def start(self):
        """Start the trade monitor background loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("[TradeMonitor] Started — monitoring paper trades for SL/TP exits")

    async def stop(self):
        """Stop the monitor."""
        self._running = False
        for unsub in self._unsubscribers:
            unsub()
        self._unsubscribers.clear()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[TradeMonitor] Stopped")

    def update_price(self, symbol: str, bid: float, ask: float, last: float = 0.0):
        """Update latest price for a symbol (called from tick subscription)."""
        self._prices[symbol] = {
            "bid": bid,
            "ask": ask,
            "last": last or (bid + ask) / 2,
            "high": max(bid, ask),
            "low": min(bid, ask),
        }

    def subscribe_to_ticks(self, ws_manager):
        """Subscribe to all tick channels to get live price updates."""
        from app.core.websocket import manager

        def on_tick(msg):
            if msg.get("type") == "tick":
                data = msg.get("data", {})
                symbol = data.get("symbol", "")
                if symbol:
                    bid = float(data.get("bid", 0))
                    ask = float(data.get("ask", 0))
                    last = float(data.get("last", 0))
                    self.update_price(symbol, bid, ask, last)

        # Subscribe to common symbols
        for symbol in ["XAUUSD", "XAGUSD", "US30", "NAS100", "EURUSD", "GBPUSD"]:
            unsub = manager.subscribe_internal(f"ticks:{symbol}", on_tick)
            self._unsubscribers.append(unsub)

        logger.info("[TradeMonitor] Subscribed to tick channels for price updates")

    async def _monitor_loop(self):
        """Main monitoring loop — checks open trades every 2 seconds."""
        while self._running:
            try:
                await self._check_open_trades()
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[TradeMonitor] Loop error: %s", e, exc_info=True)
                await asyncio.sleep(5)

    async def _check_open_trades(self):
        """Check all open paper/executed trades against current prices."""
        if not self._prices:
            return

        db = SessionLocal()
        try:
            # Get only PAPER trades — broker-executed trades are managed
            # by the broker's own SL/TP and synced by BrokerReconciler.
            open_trades = (
                db.query(AgentTrade)
                .filter(
                    AgentTrade.status == "paper",
                    AgentTrade.closed_at.is_(None),
                )
                .all()
            )

            if not open_trades:
                return

            for trade in open_trades:
                price_data = self._prices.get(trade.symbol)
                if not price_data:
                    continue

                exit_result = self._check_exit(trade, price_data)
                if exit_result:
                    self._close_trade(db, trade, exit_result)

            db.commit()

        except Exception as e:
            logger.error("[TradeMonitor] Error checking trades: %s", e)
            db.rollback()
        finally:
            db.close()

    def _check_exit(self, trade: AgentTrade, price: dict) -> Optional[dict]:
        """
        Check if a trade should be exited based on current price.

        Uses the SAME priority as the backtester:
          1. TP2 (highest priority)
          2. TP1 (only if SL not also hit)
          3. SL

        Returns exit dict or None.
        """
        current_price = price["last"]
        high = price.get("high", current_price)
        low = price.get("low", current_price)

        if trade.direction == "BUY":
            # Long trade
            hit_tp2 = trade.take_profit_2 and high >= trade.take_profit_2
            hit_tp1 = trade.take_profit_1 and high >= trade.take_profit_1
            hit_sl = trade.stop_loss and low <= trade.stop_loss
        else:
            # Short trade
            hit_tp2 = trade.take_profit_2 and low <= trade.take_profit_2
            hit_tp1 = trade.take_profit_1 and low <= trade.take_profit_1
            hit_sl = trade.stop_loss and high >= trade.stop_loss

        # Priority: TP2 > TP1 (only if no SL) > SL
        if hit_tp2:
            exit_price = trade.take_profit_2
            return {
                "exit_price": exit_price,
                "exit_reason": "TP2",
                "pnl": self._calc_pnl(trade, exit_price),
            }
        elif hit_tp1 and not hit_sl:
            exit_price = trade.take_profit_1
            return {
                "exit_price": exit_price,
                "exit_reason": "TP1",
                "pnl": self._calc_pnl(trade, exit_price),
            }
        elif hit_sl:
            exit_price = trade.stop_loss
            return {
                "exit_price": exit_price,
                "exit_reason": "SL",
                "pnl": self._calc_pnl(trade, exit_price),
            }

        return None

    def _calc_pnl(self, trade: AgentTrade, exit_price: float) -> float:
        """Calculate dollar PnL for a trade using instrument specs."""
        from app.services.agent.instrument_specs import calc_pnl_dollars
        entry = getattr(trade, "filled_price", None) or trade.entry_price
        if not entry or not exit_price:
            return 0.0
        broker = getattr(trade, "broker_name", None) or "oanda"
        return calc_pnl_dollars(
            trade.symbol, trade.direction, entry, exit_price,
            trade.lot_size, broker,
        )

    def _close_trade(self, db, trade: AgentTrade, exit_result: dict):
        """Close a trade with the exit result."""
        trade.exit_price = exit_result["exit_price"]
        trade.pnl = exit_result["pnl"]
        if trade.entry_price and trade.entry_price != 0 and trade.lot_size:
            # pnl_pct relative to risk amount (entry × lot)
            trade.pnl_pct = (exit_result["pnl"] / (trade.entry_price * trade.lot_size)) * 100
        trade.status = "closed"
        trade.closed_at = datetime.now(timezone.utc)
        trade.exit_reason = exit_result.get("exit_reason", "")

        # Log the exit
        log = AgentLog(
            agent_id=trade.agent_id,
            level="trade",
            message=f"{exit_result['exit_reason']} hit — {trade.direction} {trade.symbol} "
                    f"closed @ {exit_result['exit_price']:.5f} | PnL={exit_result['pnl']:.2f}",
            data={
                "trade_id": trade.id,
                "exit_reason": exit_result["exit_reason"],
                "exit_price": exit_result["exit_price"],
                "pnl": exit_result["pnl"],
                "entry_price": trade.entry_price,
            },
        )
        db.add(log)

        logger.info(
            "[TradeMonitor] Trade #%d closed: %s %s @ %.5f → %.5f | %s | PnL=%.2f",
            trade.id, trade.direction, trade.symbol,
            trade.entry_price, exit_result["exit_price"],
            exit_result["exit_reason"], exit_result["pnl"],
        )

        # Record RL performance metrics (if agent uses RL filter)
        self._record_rl_performance(db, trade, exit_result)

        # Broadcast via WebSocket
        self._broadcast_close(trade, exit_result)

    def _record_rl_performance(self, db, trade: AgentTrade, exit_result: dict):
        """Record trade result in RL performance monitor if agent uses RL filter."""
        try:
            agent = db.query(TradingAgent).filter(TradingAgent.id == trade.agent_id).first()
            if not agent:
                return
            risk_config = agent.risk_config or {}
            if not risk_config.get("rl_enhanced") or not risk_config.get("rl_model_id"):
                return

            from app.services.agent.rl_performance_monitor import rl_performance_monitor
            model_id = int(risk_config["rl_model_id"])
            pnl = exit_result.get("pnl", 0.0)

            alert = rl_performance_monitor.record_trade(model_id, pnl)
            if alert:
                # Log the alert
                log = AgentLog(
                    agent_id=trade.agent_id,
                    level="warn" if alert["level"] == "warning" else "error",
                    message=alert["message"],
                    data=alert.get("metrics", {}),
                )
                db.add(log)

                # Broadcast alert via WebSocket
                try:
                    from app.core.websocket import manager as ws_manager
                    asyncio.ensure_future(ws_manager.broadcast_to_channel(
                        f"agent:{trade.agent_id}",
                        {"type": "rl_performance_alert", "data": alert},
                    ))
                except Exception:
                    pass
        except Exception as e:
            logger.warning("[TradeMonitor] RL performance tracking error: %s", e)

    def _broadcast_close(self, trade: AgentTrade, exit_result: dict):
        """Broadcast trade close event via WebSocket."""
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
                        "entry_price": trade.entry_price,
                        "exit_price": exit_result["exit_price"],
                        "exit_reason": exit_result["exit_reason"],
                        "pnl": exit_result["pnl"],
                    },
                },
            ))
        except Exception:
            pass

    def close_trade_by_reversal(self, agent_id: int, symbol: str, current_price: float):
        """
        Close open trades for an agent due to a reversal signal.
        Called by AgentRunner when an opposite-direction signal fires.

        Paper trades: close immediately in DB.
        Executed trades: close on broker first, then mark closed.
        """
        db = SessionLocal()
        try:
            open_trades = (
                db.query(AgentTrade)
                .filter(
                    AgentTrade.agent_id == agent_id,
                    AgentTrade.symbol == symbol,
                    AgentTrade.status.in_(["paper", "executed"]),
                    AgentTrade.closed_at.is_(None),
                )
                .all()
            )

            closed_count = 0
            for trade in open_trades:
                # For executed (broker) trades, try to close on broker first
                if trade.status == "executed" and trade.broker_name:
                    try:
                        import asyncio
                        from app.services.broker.manager import broker_manager
                        adapter = broker_manager.get_adapter(trade.broker_name)
                        if adapter:
                            loop = asyncio.get_event_loop()
                            loop.create_task(adapter.close_position(trade.symbol))
                    except Exception as e:
                        logger.warning("[TradeMonitor] Could not close broker position for reversal: %s", e)

                pnl = self._calc_pnl(trade, current_price)
                exit_result = {
                    "exit_price": current_price,
                    "exit_reason": "Reversal",
                    "pnl": pnl,
                }
                self._close_trade(db, trade, exit_result)
                closed_count += 1

            db.commit()
            return closed_count

        except Exception as e:
            logger.error("[TradeMonitor] Error closing reversal trades: %s", e)
            db.rollback()
            return 0
        finally:
            db.close()

    def get_open_trade_count(self, agent_id: int) -> int:
        """Get number of open trades for an agent."""
        db = SessionLocal()
        try:
            return (
                db.query(AgentTrade)
                .filter(
                    AgentTrade.agent_id == agent_id,
                    AgentTrade.status.in_(["paper", "executed"]),
                    AgentTrade.closed_at.is_(None),
                )
                .count()
            )
        finally:
            db.close()

    def get_open_trades(self, agent_id: int) -> list[dict]:
        """Get open trades for an agent."""
        db = SessionLocal()
        try:
            trades = (
                db.query(AgentTrade)
                .filter(
                    AgentTrade.agent_id == agent_id,
                    AgentTrade.status.in_(["paper", "executed"]),
                    AgentTrade.closed_at.is_(None),
                )
                .all()
            )
            return [
                {
                    "id": t.id,
                    "direction": t.direction,
                    "entry_price": t.entry_price,
                    "stop_loss": t.stop_loss,
                    "take_profit_1": t.take_profit_1,
                    "take_profit_2": t.take_profit_2,
                }
                for t in trades
            ]
        finally:
            db.close()


# Singleton
trade_monitor = PaperTradeMonitor()
