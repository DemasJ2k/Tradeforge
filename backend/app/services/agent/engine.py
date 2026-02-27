"""
Algo Trading Engine — manages autonomous AgentRunner tasks.

AlgoEngine: singleton that manages multiple AgentRunner asyncio tasks.
AgentRunner: per-agent loop that subscribes to bar channels, evaluates
             strategy signals, and creates trades based on agent mode.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from app.core.database import SessionLocal
from app.core.websocket import manager as ws_manager
from app.models.agent import TradingAgent, AgentLog, AgentTrade
from app.models.ml import MLModel
from app.models.strategy import Strategy
from app.services.agent.risk_manager import RiskManager
from app.services.agent.mss_evaluator import MSSEvaluator
from app.services.agent.gold_bt_evaluator import GoldBTEvaluator
from app.services.agent.ml_filter import MLSignalFilter
from app.services.agent.trade_monitor import trade_monitor

logger = logging.getLogger(__name__)


class AgentRunner:
    """
    Per-agent asyncio loop.

    Subscribes to the bar channel for the agent's symbol+timeframe.
    On each new closed bar: evaluates strategy, checks risk, creates trade.
    """

    def __init__(self, agent_id: int):
        self.agent_id = agent_id
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._unsubscribe = None

        # Loaded from DB on start
        self._evaluator: Optional[MSSEvaluator] = None
        self._risk_manager: Optional[RiskManager] = None
        self._ml_filter: Optional[MLSignalFilter] = None
        self._mode = "paper"
        self._symbol = ""
        self._timeframe = ""
        self._broker_name = "mt5"
        self._bar_buffer: list[dict] = []
        self._strategy_type: str = "mss"
        # Position tracking (mirrors backtester behavior)
        self._active_direction: int = 0  # 0=flat, 1=long, -1=short

    async def start(self):
        """Load agent config from DB and start the evaluation loop."""
        if self._running:
            return

        db = SessionLocal()
        try:
            agent = db.query(TradingAgent).filter(TradingAgent.id == self.agent_id).first()
            if not agent:
                logger.error("[Agent %d] Not found in DB", self.agent_id)
                return

            self._mode = agent.mode
            self._symbol = agent.symbol
            self._timeframe = agent.timeframe
            self._broker_name = agent.broker_name or "mt5"

            # Initialize evaluator based on strategy type
            strategy = db.query(Strategy).filter(Strategy.id == agent.strategy_id).first()
            filters = strategy.filters or {} if strategy else {}

            if "gold_bt_config" in filters:
                gold_config = filters["gold_bt_config"]
                self._evaluator = GoldBTEvaluator(self._symbol, gold_config)
                self._strategy_type = "gold_bt"
            elif "mss_config" in filters:
                mss_config = filters["mss_config"]
                self._evaluator = MSSEvaluator(self._symbol, mss_config)
                self._strategy_type = "mss"
            else:
                # Fallback to MSS with defaults
                self._evaluator = MSSEvaluator(self._symbol)
                self._strategy_type = "mss"

            # Initialize ML filter if model is linked
            if agent.ml_model_id:
                ml_model = db.query(MLModel).filter(MLModel.id == agent.ml_model_id).first()
                if ml_model and ml_model.status == "ready" and ml_model.model_path:
                    ml_mode = (agent.risk_config or {}).get("ml_mode", "enhance")
                    self._ml_filter = MLSignalFilter(
                        model_path=ml_model.model_path,
                        features_config=ml_model.features_config,
                        target_config=ml_model.target_config,
                        mode=ml_mode,
                    )
                    if self._ml_filter.load():
                        logger.info("[Agent %d] ML filter loaded: %s (mode=%s)",
                                    self.agent_id, ml_model.name, ml_mode)
                    else:
                        self._ml_filter = None

            # Initialize risk manager
            self._risk_manager = RiskManager(agent.risk_config or {})

            # Restore position state from DB (check for open trades)
            open_trade = (
                db.query(AgentTrade)
                .filter(
                    AgentTrade.agent_id == self.agent_id,
                    AgentTrade.status.in_(["paper", "executed"]),
                    AgentTrade.closed_at.is_(None),
                )
                .order_by(AgentTrade.created_at.desc())
                .first()
            )
            if open_trade:
                self._active_direction = 1 if open_trade.direction == "BUY" else -1
                logger.info("[Agent %d] Restored active position: %s", self.agent_id, open_trade.direction)

            # Sync risk manager position count
            open_count = trade_monitor.get_open_trade_count(self.agent_id)
            self._risk_manager.set_open_positions(open_count)

            # Update DB status
            agent.status = "running"
            db.commit()
        finally:
            db.close()

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        self._log("info", f"Agent started in {self._mode} mode for {self._symbol} {self._timeframe}")

    async def stop(self):
        """Stop the agent loop."""
        self._running = False

        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        # Update DB status
        db = SessionLocal()
        try:
            agent = db.query(TradingAgent).filter(TradingAgent.id == self.agent_id).first()
            if agent:
                agent.status = "stopped"
                db.commit()
        finally:
            db.close()

        self._log("info", "Agent stopped")

    async def pause(self):
        """Pause the agent (stop evaluating but keep subscriptions)."""
        self._running = False

        db = SessionLocal()
        try:
            agent = db.query(TradingAgent).filter(TradingAgent.id == self.agent_id).first()
            if agent:
                agent.status = "paused"
                db.commit()
        finally:
            db.close()

        self._log("info", "Agent paused")

    async def _run_loop(self):
        """Main agent loop — listen for bar events and evaluate."""
        channel = f"bars:{self._symbol}:{self._timeframe}"
        bar_queue: asyncio.Queue = asyncio.Queue()

        def on_bar(msg):
            """Callback from WebSocket manager for bar messages."""
            if msg.get("type") == "bar":
                bar_queue.put_nowait(msg.get("data", {}))

        # Subscribe to bar channel (async version triggers TickAggregator)
        self._unsubscribe = await ws_manager.subscribe_internal_async(channel, on_bar)

        # Load initial bars for warmup
        await self._load_initial_bars()

        self._log("info", f"Subscribed to {channel}, waiting for bars...")

        while self._running:
            try:
                # Wait for a new closed bar (with timeout for health checks)
                try:
                    bar_data = await asyncio.wait_for(bar_queue.get(), timeout=60)
                except asyncio.TimeoutError:
                    continue

                # Add to buffer
                self._bar_buffer.append(bar_data)
                # Keep buffer at reasonable size (200 bars)
                if len(self._bar_buffer) > 200:
                    self._bar_buffer = self._bar_buffer[-200:]

                logger.info("[Agent %d] Received bar: time=%s C=%.2f (buffer=%d bars)",
                            self.agent_id, bar_data.get("time"), bar_data.get("close", 0),
                            len(self._bar_buffer))

                # Evaluate
                await self._evaluate_signal()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[Agent %d] Loop error: %s", self.agent_id, e)
                self._log("error", f"Loop error: {e}")
                await asyncio.sleep(5)

    async def _load_initial_bars(self):
        """Load initial bar history for evaluator warmup."""
        from app.services.broker.manager import broker_manager

        # Try via broker_manager first (user-connected broker)
        try:
            adapter = broker_manager.get_adapter(self._broker_name)
            if adapter and await adapter.is_connected():
                bars = await adapter.get_initial_bars(self._symbol, self._timeframe, 500)
                if bars:
                    self._bar_buffer = bars
                    self._log("info", f"Loaded {len(bars)} initial bars via broker manager")
                    return
        except Exception as e:
            logger.warning("[Agent %d] Broker manager load failed: %s", self.agent_id, e)

        # Fallback: use MT5 directly (tick streamer already initialized MT5)
        try:
            import MetaTrader5 as mt5
            from app.services.broker.mt5_bridge import _TF_MAP
            from concurrent.futures import ThreadPoolExecutor

            tf = _TF_MAP.get(self._timeframe, mt5.TIMEFRAME_H1)
            loop = asyncio.get_event_loop()
            _pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-mt5")

            def _fetch():
                mt5.symbol_select(self._symbol, True)
                return mt5.copy_rates_from_pos(self._symbol, tf, 0, 500)

            raw = await loop.run_in_executor(_pool, _fetch)
            if raw is not None and len(raw) > 0:
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
                self._bar_buffer = bars
                self._log("info", f"Loaded {len(bars)} initial bars via direct MT5")
                return
            else:
                logger.warning("[Agent %d] Direct MT5 copy_rates returned empty", self.agent_id)
        except ImportError:
            logger.warning("[Agent %d] MetaTrader5 package not available for fallback", self.agent_id)
        except Exception as e:
            logger.warning("[Agent %d] Direct MT5 fallback failed: %s", self.agent_id, e)

        self._log("warn", "No initial bars loaded — evaluator will warm up as bars arrive")

    async def _evaluate_signal(self):
        """
        Run the strategy evaluator on current bars.

        Mirrors the backtester's trade lifecycle:
          1. Evaluate strategy for new signal
          2. If signal fires and we have an open position in the OPPOSITE direction,
             close it via reversal (exactly as the backtester does)
          3. If signal direction matches current position, skip (already in trade)
          4. Apply ML filter and risk checks
          5. Open new trade
        """
        if not self._evaluator:
            return

        min_bars = 10 if self._strategy_type == "gold_bt" else 85
        if len(self._bar_buffer) < min_bars:
            return

        # Get daily bars for ADR10 (MSS needs this, Gold BT doesn't)
        daily_bars = await self._get_daily_bars() if self._strategy_type == "mss" else None

        signal = self._evaluator.on_bar(self._bar_buffer, daily_bars)
        if signal is None:
            return

        self._log("signal", f"{signal.reason}", data={
            "direction": signal.direction,
            "signal_type": signal.signal_type,
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "tp1": signal.take_profit_1,
            "tp2": signal.take_profit_2,
            "confidence": signal.confidence,
        })

        # ── Reversal logic (matches backtester exactly) ──
        # If we have an active position in the OPPOSITE direction, close it
        if self._active_direction != 0 and self._active_direction != signal.direction:
            current_price = self._bar_buffer[-1]["close"]
            closed_count = trade_monitor.close_trade_by_reversal(
                agent_id=self.agent_id,
                symbol=self._symbol,
                current_price=current_price,
            )
            if closed_count > 0:
                old_dir = "LONG" if self._active_direction == 1 else "SHORT"
                new_dir = "LONG" if signal.direction == 1 else "SHORT"
                self._log("trade", f"Reversal: closed {closed_count} {old_dir} trade(s) → opening {new_dir}")
                self._active_direction = 0
                # Update risk manager position count
                self._risk_manager.set_open_positions(
                    trade_monitor.get_open_trade_count(self.agent_id)
                )

        # If we already have a position in the SAME direction, skip
        if self._active_direction == signal.direction:
            self._log("info", f"Skipping signal — already in {signal.direction} direction")
            return

        # ── ML filter ──
        if self._ml_filter:
            ml_result = self._ml_filter.evaluate_signal(
                strategy_direction=signal.direction,
                strategy_confidence=signal.confidence,
                bars=self._bar_buffer,
            )

            self._log("ml_filter", ml_result["reason"], data={
                "ml_direction": ml_result["ml_direction"],
                "ml_confidence": ml_result["ml_confidence"],
                "combined_confidence": ml_result["combined_confidence"],
                "approved": ml_result["approved"],
            })

            if not ml_result["approved"]:
                self._log("info", f"Trade filtered by ML model: {ml_result['reason']}")
                return

            signal.confidence = ml_result["combined_confidence"]

        # ── Risk check ──
        balance = await self._get_balance()
        direction = "BUY" if signal.direction == 1 else "SELL"

        # Sync open position count before risk check
        open_count = trade_monitor.get_open_trade_count(self.agent_id)
        self._risk_manager.set_open_positions(open_count)

        risk_decision = self._risk_manager.evaluate(
            symbol=self._symbol,
            direction=direction,
            balance=balance,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
        )

        if not risk_decision.approved:
            self._log("warn", f"Trade rejected by risk manager: {risk_decision.reason}")
            return

        lot_size = risk_decision.adjusted_lot_size or 0.01

        # ── Create trade and track position ──
        await self._create_trade(signal, direction, lot_size)
        self._active_direction = signal.direction

    async def _create_trade(self, signal, direction: str, lot_size: float):
        """
        Create an AgentTrade record and execute based on agent mode.

        Modes:
          paper:        Record trade, monitor via TradeMonitor for SL/TP exits
          confirmation: Record trade as pending, wait for user confirmation
          auto:         Record trade AND send to broker with SL/TP levels
        """
        db = SessionLocal()
        try:
            if self._mode == "paper":
                status = "paper"
            elif self._mode == "confirmation":
                status = "pending_confirmation"
            elif self._mode == "auto":
                status = "executed"  # Will send to broker below
            else:
                status = "pending_confirmation"  # default safe

            trade = AgentTrade(
                agent_id=self.agent_id,
                symbol=self._symbol,
                direction=direction,
                entry_price=signal.entry_price,
                lot_size=lot_size,
                stop_loss=signal.stop_loss,
                take_profit_1=signal.take_profit_1,
                take_profit_2=signal.take_profit_2,
                status=status,
                signal_type=signal.signal_type,
                signal_reason=signal.reason,
                signal_confidence=signal.confidence,
            )
            db.add(trade)
            db.commit()
            db.refresh(trade)

            trade_id = trade.id

            # ── Auto-execution: send order to broker with SL/TP ──
            broker_ticket = None
            if self._mode == "auto":
                broker_ticket = await self._execute_on_broker(
                    direction=direction,
                    lot_size=lot_size,
                    entry_price=signal.entry_price,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit_2 or signal.take_profit_1,
                )
                if broker_ticket:
                    trade.broker_ticket = broker_ticket
                    self._log("trade", f"LIVE {direction} {self._symbol} @ {signal.entry_price:.5f} | ticket={broker_ticket}", data={
                        "trade_id": trade_id,
                        "lot_size": lot_size,
                        "status": "executed",
                        "broker_ticket": broker_ticket,
                    })
                else:
                    trade.status = "rejected"
                    self._active_direction = 0  # Reset since execution failed
                    self._log("error", f"Broker execution failed for {direction} {self._symbol}")

                db.commit()
            else:
                self._log("trade", f"{direction} {self._symbol} @ {signal.entry_price:.5f} — {status}", data={
                    "trade_id": trade_id,
                    "lot_size": lot_size,
                    "status": status,
                })

            # Notify via WebSocket
            await ws_manager.broadcast_to_channel(
                f"agent:{self.agent_id}",
                {
                    "type": "agent_trade",
                    "channel": f"agent:{self.agent_id}",
                    "data": {
                        "trade_id": trade_id,
                        "agent_id": self.agent_id,
                        "symbol": self._symbol,
                        "direction": direction,
                        "entry_price": signal.entry_price,
                        "stop_loss": signal.stop_loss,
                        "tp1": signal.take_profit_1,
                        "tp2": signal.take_profit_2,
                        "lot_size": lot_size,
                        "status": trade.status,
                        "signal_type": signal.signal_type,
                        "reason": signal.reason,
                        "broker_ticket": broker_ticket,
                    },
                },
            )

        finally:
            db.close()

    async def _execute_on_broker(self, direction: str, lot_size: float,
                                    entry_price: float, stop_loss: float,
                                    take_profit: float) -> Optional[str]:
        """Send a market order to the broker with SL/TP. Returns broker ticket or None."""
        # Try via broker_manager first
        try:
            from app.services.broker.manager import broker_manager
            adapter = broker_manager.get_adapter(self._broker_name)
            if adapter and await adapter.is_connected():
                from app.schemas.broker import OrderRequest
                request = OrderRequest(
                    symbol=self._symbol,
                    side=direction,
                    size=lot_size,
                    order_type="MARKET",
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                )
                result = await adapter.place_order(request)
                if result and result.get("ticket"):
                    return str(result["ticket"])
                return None
        except Exception as e:
            logger.warning("[Agent %d] Broker manager execution failed: %s", self.agent_id, e)

        # Fallback: use MT5 directly (tick streamer already initialized MT5)
        try:
            import MetaTrader5 as mt5
            from concurrent.futures import ThreadPoolExecutor
            loop = asyncio.get_event_loop()
            _pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-order")

            order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL

            def _place_order():
                mt5.symbol_select(self._symbol, True)
                symbol_info = mt5.symbol_info(self._symbol)
                if symbol_info is None:
                    return None

                price = symbol_info.ask if direction == "BUY" else symbol_info.bid
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": self._symbol,
                    "volume": lot_size,
                    "type": order_type,
                    "price": price,
                    "sl": stop_loss,
                    "tp": take_profit,
                    "deviation": 20,
                    "magic": 234000,
                    "comment": f"TradeForge Agent#{self.agent_id}",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                result = mt5.order_send(request)
                return result

            result = await loop.run_in_executor(_pool, _place_order)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                self._log("info", f"Direct MT5 order placed: ticket={result.order}")
                return str(result.order)
            else:
                retcode = result.retcode if result else "None"
                comment = result.comment if result else "no result"
                self._log("error", f"Direct MT5 order failed: retcode={retcode}, {comment}")
                return None
        except ImportError:
            self._log("error", "MetaTrader5 package not available for direct execution")
            return None
        except Exception as e:
            logger.error("[Agent %d] Direct MT5 execution error: %s", self.agent_id, e)
            return None

    async def _get_daily_bars(self) -> list[dict]:
        """Fetch daily bars for ADR10 computation."""
        # Try broker_manager first
        try:
            from app.services.broker.manager import broker_manager
            adapter = broker_manager.get_adapter(self._broker_name)
            if adapter and await adapter.is_connected():
                bars = await adapter.get_initial_bars(self._symbol, "D1", 15)
                if bars:
                    return bars
        except Exception:
            pass

        # Fallback: direct MT5
        try:
            import MetaTrader5 as mt5
            from concurrent.futures import ThreadPoolExecutor
            loop = asyncio.get_event_loop()
            _pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-daily")

            def _fetch():
                mt5.symbol_select(self._symbol, True)
                return mt5.copy_rates_from_pos(self._symbol, mt5.TIMEFRAME_D1, 0, 15)

            raw = await loop.run_in_executor(_pool, _fetch)
            if raw is not None and len(raw) > 0:
                return [
                    {
                        "time": int(r['time']),
                        "open": float(r['open']),
                        "high": float(r['high']),
                        "low": float(r['low']),
                        "close": float(r['close']),
                        "volume": float(r['tick_volume']),
                    }
                    for r in raw
                ]
        except Exception:
            pass
        return []

    async def _get_balance(self) -> float:
        """Get current account balance from broker."""
        # Try broker_manager first
        try:
            from app.services.broker.manager import broker_manager
            adapter = broker_manager.get_adapter(self._broker_name)
            if adapter and await adapter.is_connected():
                info = await adapter.get_account_info()
                if info:
                    return info.get("balance", 10000.0)
        except Exception:
            pass

        # Fallback: direct MT5
        try:
            import MetaTrader5 as mt5
            from concurrent.futures import ThreadPoolExecutor
            loop = asyncio.get_event_loop()
            _pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-bal")

            def _fetch():
                info = mt5.account_info()
                return info.balance if info else None

            balance = await loop.run_in_executor(_pool, _fetch)
            if balance is not None:
                return balance
        except Exception:
            pass
        return 10000.0  # Default for paper trading

    def _log(self, level: str, message: str, data: Optional[dict] = None):
        """Write a log entry to DB and broadcast via WebSocket."""
        db = SessionLocal()
        try:
            log = AgentLog(
                agent_id=self.agent_id,
                level=level,
                message=message,
                data=data or {},
            )
            db.add(log)
            db.commit()
        except Exception as e:
            logger.error("[Agent %d] Failed to write log: %s", self.agent_id, e)
        finally:
            db.close()

        # Non-blocking WS broadcast
        asyncio.ensure_future(self._broadcast_log(level, message, data))

    async def _broadcast_log(self, level: str, message: str, data: Optional[dict] = None):
        try:
            await ws_manager.broadcast_to_channel(
                f"agent:{self.agent_id}",
                {
                    "type": "agent_log",
                    "channel": f"agent:{self.agent_id}",
                    "data": {
                        "agent_id": self.agent_id,
                        "level": level,
                        "message": message,
                        "data": data or {},
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                },
            )
        except Exception:
            pass


class AlgoEngine:
    """
    Singleton that manages all AgentRunner instances.
    """

    def __init__(self):
        self._runners: dict[int, AgentRunner] = {}

    async def start(self):
        """Initialize the engine on app startup.

        Resets any agents stuck in 'running' status from a previous crash/restart.
        They need to be manually re-started by the user.
        """
        db = SessionLocal()
        try:
            zombies = db.query(TradingAgent).filter(
                TradingAgent.status == "running"
            ).all()
            for agent in zombies:
                agent.status = "stopped"
                logger.warning(
                    "Reset zombie agent #%d (%s) from running → stopped",
                    agent.id, agent.name,
                )
            if zombies:
                db.commit()
                logger.info("Reset %d zombie agent(s) to stopped", len(zombies))
        except Exception as e:
            logger.error("Failed to reset zombie agents: %s", e)
            db.rollback()
        finally:
            db.close()
        logger.info("AlgoEngine started")

    async def stop(self):
        """Stop all running agents on app shutdown."""
        for runner in list(self._runners.values()):
            await runner.stop()
        self._runners.clear()
        logger.info("AlgoEngine stopped — all agents stopped")

    async def start_agent(self, agent_id: int):
        """Start an agent by ID."""
        if agent_id in self._runners and self._runners[agent_id]._running:
            return  # Already running

        runner = AgentRunner(agent_id)
        self._runners[agent_id] = runner
        await runner.start()

    async def stop_agent(self, agent_id: int):
        """Stop a running agent."""
        runner = self._runners.pop(agent_id, None)
        if runner:
            await runner.stop()

    async def pause_agent(self, agent_id: int):
        """Pause a running agent."""
        runner = self._runners.get(agent_id)
        if runner:
            await runner.pause()

    def is_running(self, agent_id: int) -> bool:
        runner = self._runners.get(agent_id)
        return runner is not None and runner._running

    def list_active(self) -> list[int]:
        return [aid for aid, r in self._runners.items() if r._running]


# Singleton
algo_engine = AlgoEngine()
