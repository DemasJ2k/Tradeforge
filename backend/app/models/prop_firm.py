"""
Prop Firm Account models.

PropFirmAccount  — A prop firm trading account with rules and tracking
PropFirmTrade    — Individual trades executed within a prop firm account
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, Integer, String, Float, DateTime, ForeignKey, JSON, Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class PropFirmAccount(Base):
    __tablename__ = "prop_firm_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # ── Account Identity ──
    account_name = Column(String(100), nullable=False)     # "FTMO Challenge #1"
    firm_name = Column(String(50), nullable=False)          # "FTMO", "Funded Next", etc.
    account_size = Column(Float, nullable=False)            # Starting balance (e.g. 100000)
    currency = Column(String(10), default="USD")

    # ── Account Phase ──
    # challenge | verification | funded | free_trial
    phase = Column(String(20), nullable=False, default="challenge")

    # ── Status ──
    # active | paused | breached | passed | completed
    status = Column(String(20), nullable=False, default="active")
    breach_reason = Column(String(200), nullable=True)      # Why account was breached

    # ── Firm Rules (configurable per account) ──
    max_daily_loss_pct = Column(Float, default=5.0)         # 5% daily loss limit
    max_total_loss_pct = Column(Float, default=10.0)        # 10% max drawdown
    profit_target_pct = Column(Float, default=8.0)          # 8% profit target
    min_trading_days = Column(Integer, default=5)            # Minimum trading days
    max_trading_days = Column(Integer, nullable=True)        # Max days (None = unlimited)
    no_news_trading = Column(Boolean, default=True)          # No trading during news
    no_weekend_holding = Column(Boolean, default=True)       # No holding over weekend
    max_lots_per_trade = Column(Float, nullable=True)        # Max position size
    max_open_positions = Column(Integer, nullable=True)      # Max simultaneous positions
    allowed_symbols = Column(JSON, default=list)             # [] = all allowed
    restricted_hours = Column(JSON, default=dict)            # {"start": "23:00", "end": "01:00"}

    # ── Strategy Assignment ──
    # Which strategies are assigned to this account
    assigned_strategies = Column(JSON, default=list)         # [{"strategy_id": 53, "symbol": "US30", "timeframe": "H1"}]

    # ── Live Tracking ──
    current_balance = Column(Float, nullable=False)          # Updated after each trade
    current_equity = Column(Float, nullable=False)           # Balance + unrealized PnL
    total_pnl = Column(Float, default=0.0)
    today_pnl = Column(Float, default=0.0)                   # Reset daily
    today_pnl_date = Column(String(10), nullable=True)       # "2026-03-07" — tracks which day
    max_drawdown_pct = Column(Float, default=0.0)            # Highest DD hit
    peak_balance = Column(Float, nullable=False)             # High-water mark
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    trading_days = Column(Integer, default=0)                # Distinct days with trades
    trading_days_list = Column(JSON, default=list)           # ["2026-03-01", "2026-03-02", ...]

    # ── Progress ──
    profit_target_reached = Column(Boolean, default=False)
    daily_loss_breached = Column(Boolean, default=False)
    total_loss_breached = Column(Boolean, default=False)

    # ── Equity Curve (for chart) ──
    equity_history = Column(JSON, default=list)
    # [{"date": "2026-03-01", "balance": 100500, "equity": 100700, "pnl": 500}, ...]

    # ── Metadata ──
    notes = Column(Text, nullable=True)
    broker_account_id = Column(String(100), nullable=True)   # Link to actual broker account
    broker_name = Column(String(50), nullable=True)          # "oanda", "mt5", etc.

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    deleted_at = Column(DateTime, nullable=True, default=None)

    # ── Relationships ──
    user = relationship("User")
    trades = relationship("PropFirmTrade", back_populates="account",
                         cascade="all, delete-orphan",
                         order_by="PropFirmTrade.opened_at.desc()")


class PropFirmTrade(Base):
    __tablename__ = "prop_firm_trades"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("prop_firm_accounts.id"), nullable=False)

    # ── Trade Details ──
    symbol = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False)           # BUY or SELL
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    lot_size = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)

    # ── P&L ──
    pnl = Column(Float, default=0.0)                         # Dollar P&L
    pnl_pct = Column(Float, default=0.0)                     # % of account
    commission = Column(Float, default=0.0)

    # ── Status ──
    # open | closed | cancelled
    status = Column(String(20), nullable=False, default="open")
    close_reason = Column(String(50), nullable=True)         # tp_hit, sl_hit, manual, rule_breach

    # ── Strategy Link ──
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=True)
    agent_id = Column(Integer, ForeignKey("trading_agents.id"), nullable=True)
    broker_ticket = Column(String(50), nullable=True)        # Broker order ID

    # ── Balance Snapshot ──
    balance_before = Column(Float, nullable=True)            # Account balance before trade
    balance_after = Column(Float, nullable=True)             # Account balance after trade

    # ── Timestamps ──
    opened_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    closed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # ── Relationships ──
    account = relationship("PropFirmAccount", back_populates="trades")
    strategy = relationship("Strategy")
