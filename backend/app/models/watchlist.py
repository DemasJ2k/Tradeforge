"""Watchlist & Webhook Alert models."""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, JSON, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base


class Watchlist(Base):
    """User's symbol watchlist for monitoring prices."""
    __tablename__ = "watchlists"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False, default="Default")
    symbols = Column(JSON, default=list)  # ["XAUUSD", "EURUSD", "BTCUSD"]
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class WatchlistAlert(Base):
    """Price alert on a watched symbol."""
    __tablename__ = "watchlist_alerts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    symbol = Column(String(50), nullable=False)
    condition = Column(String(20), nullable=False)  # price_above, price_below, pct_change
    threshold = Column(Float, nullable=False)
    message = Column(String(500), default="")
    triggered = Column(Boolean, default=False)
    triggered_at = Column(DateTime, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class WebhookEndpoint(Base):
    """Configured webhook URL for automated notifications."""
    __tablename__ = "webhook_endpoints"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    url = Column(String(1000), nullable=False)           # https://hooks.slack.com/...
    secret = Column(String(200), default="")              # Optional signing secret
    events = Column(JSON, default=list)                   # ["trade_opened", "trade_closed", "signal", "agent_status"]
    headers = Column(JSON, default=dict)                  # Custom headers
    enabled = Column(Boolean, default=True)
    last_triggered_at = Column(DateTime, nullable=True)
    last_status_code = Column(Integer, nullable=True)
    failure_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class WebhookLog(Base):
    """Log of webhook delivery attempts."""
    __tablename__ = "webhook_logs"

    id = Column(Integer, primary_key=True, index=True)
    endpoint_id = Column(Integer, ForeignKey("webhook_endpoints.id"), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)       # trade_opened, signal, etc.
    payload = Column(JSON, default=dict)                   # The JSON sent
    status_code = Column(Integer, nullable=True)
    response_body = Column(Text, default="")
    success = Column(Boolean, default=False)
    delivered_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
