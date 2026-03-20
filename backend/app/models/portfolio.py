"""
Portfolio Manager models.

PortfolioManager — coordinates multiple agents for a single user with
                   portfolio-level risk management, correlation awareness,
                   and drawdown circuit breakers.
PortfolioSnapshot — periodic equity snapshots for portfolio equity curves.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, JSON,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class PortfolioManager(Base):
    __tablename__ = "portfolio_managers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False, default="My Portfolio")

    # Risk mode: conservative | balanced | aggressive
    mode = Column(String(20), nullable=False, default="balanced")

    # Portfolio-level risk limits
    max_daily_loss_pct = Column(Float, default=5.0)       # Prop firm: 5%
    max_total_drawdown_pct = Column(Float, default=10.0)   # Prop firm: 10%
    max_portfolio_risk_pct = Column(Float, default=2.0)    # Max % of capital at risk at once
    correlation_threshold = Column(Float, default=0.85)    # Block if correlation exceeds
    max_concurrent_positions = Column(Integer, default=6)  # Total across all agents

    # Capital allocation per agent: { agent_id: fraction (0-1) }
    capital_allocation = Column(JSON, default=dict)

    # Status: active | paused | breached
    status = Column(String(20), nullable=False, default="active")

    # Tracked performance (updated by background task)
    peak_equity = Column(Float, default=0.0)
    current_equity = Column(Float, default=0.0)
    daily_pnl = Column(Float, default=0.0)
    total_pnl = Column(Float, default=0.0)
    current_drawdown_pct = Column(Float, default=0.0)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User")
    snapshots = relationship("PortfolioSnapshot", back_populates="portfolio",
                             cascade="all, delete-orphan", order_by="PortfolioSnapshot.timestamp")


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolio_managers.id"), nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    total_equity = Column(Float, default=0.0)
    total_pnl = Column(Float, default=0.0)
    daily_pnl = Column(Float, default=0.0)
    drawdown_pct = Column(Float, default=0.0)

    # Per-agent breakdown
    positions_summary = Column(JSON, default=dict)
    # { agent_id: { symbol, direction, pnl, lots } }

    # Correlation matrix at snapshot time
    correlation_matrix = Column(JSON, default=dict)
    # { "US30_NAS100": 0.87, "BTCUSD_ETHUSD": 0.92, ... }

    portfolio = relationship("PortfolioManager", back_populates="snapshots")
