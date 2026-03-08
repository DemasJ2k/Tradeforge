"""
Background service that periodically checks watchlist price alerts
and triggers notifications when conditions are met.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.watchlist import WatchlistAlert

logger = logging.getLogger(__name__)


class AlertChecker:
    """Polls active price alerts every 15 seconds and triggers notifications."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._interval = 15  # seconds

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("AlertChecker started (interval=%ds)", self._interval)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("AlertChecker stopped")

    async def _loop(self):
        while self._running:
            try:
                await self._check_alerts()
            except Exception as e:
                logger.error("AlertChecker error: %s", e)
            await asyncio.sleep(self._interval)

    async def _check_alerts(self):
        db: Session = SessionLocal()
        try:
            # Get all active, untriggered alerts
            alerts = (
                db.query(WatchlistAlert)
                .filter(
                    WatchlistAlert.active == True,
                    WatchlistAlert.triggered == False,
                )
                .all()
            )

            if not alerts:
                return

            # Group alerts by symbol to minimize price lookups
            symbol_alerts: dict[str, list[WatchlistAlert]] = {}
            for alert in alerts:
                symbol_alerts.setdefault(alert.symbol, []).append(alert)

            # Get current prices
            from app.services.broker.manager import broker_manager

            for symbol, alert_list in symbol_alerts.items():
                price = await self._get_price(symbol, broker_manager)
                if price is None:
                    continue

                for alert in alert_list:
                    triggered = self._evaluate(alert, price)
                    if triggered:
                        alert.triggered = True
                        alert.triggered_at = datetime.now(timezone.utc)
                        db.commit()

                        # Send notification
                        await self._notify(alert, price, db)
                        logger.info(
                            "Alert %d triggered: %s %s %.5f (price=%.5f)",
                            alert.id, alert.symbol, alert.condition,
                            alert.threshold, price,
                        )
        finally:
            db.close()

    async def _get_price(self, symbol: str, broker_manager) -> Optional[float]:
        """Get the current price for a symbol from any connected broker."""
        try:
            adapter = broker_manager.get_adapter()
            if adapter and await adapter.is_connected():
                tick = await adapter.get_price(symbol)
                if tick:
                    return (tick.bid + tick.ask) / 2
        except Exception:
            pass

        # Try each broker
        for name in broker_manager.active_brokers:
            try:
                adapter = broker_manager.get_adapter(name)
                if adapter and await adapter.is_connected():
                    tick = await adapter.get_price(symbol)
                    if tick:
                        return (tick.bid + tick.ask) / 2
            except Exception:
                continue
        return None

    def _evaluate(self, alert: WatchlistAlert, price: float) -> bool:
        """Check if the alert condition is met."""
        if alert.condition == "price_above":
            return price >= alert.threshold
        elif alert.condition == "price_below":
            return price <= alert.threshold
        elif alert.condition == "pct_change":
            # pct_change would need a reference price — skip for now
            return False
        return False

    async def _notify(self, alert: WatchlistAlert, price: float, db: Session):
        """Send notification for a triggered alert."""
        try:
            from app.services.notification import notify

            condition_text = {
                "price_above": "rose above",
                "price_below": "fell below",
                "pct_change": "changed by",
            }.get(alert.condition, alert.condition)

            message = (
                alert.message
                or f"{alert.symbol} {condition_text} {alert.threshold:.5f} (current: {price:.5f})"
            )

            await notify(
                db=db,
                user_id=alert.user_id,
                subject=f"Price Alert: {alert.symbol}",
                body=message,
                event_type="price_alert",
            )
        except Exception as e:
            logger.error("Failed to send alert notification %d: %s", alert.id, e)


alert_checker = AlertChecker()
