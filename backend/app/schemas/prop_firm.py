"""Pydantic schemas for Prop Firm Account feature."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ── Firm Preset ──

class FirmPreset(BaseModel):
    """Pre-configured rules for known prop firms."""
    firm_name: str
    phase: str
    max_daily_loss_pct: float
    max_total_loss_pct: float
    profit_target_pct: float
    min_trading_days: int
    max_trading_days: Optional[int] = None
    no_news_trading: bool = True
    no_weekend_holding: bool = True


# ── Create / Update ──

class PropFirmAccountCreate(BaseModel):
    account_name: str = Field(..., min_length=1, max_length=100)
    firm_name: str = Field(..., min_length=1, max_length=50)
    account_size: float = Field(..., gt=0)
    currency: str = "USD"
    phase: str = "challenge"

    # Rules (optional — defaults from firm preset)
    max_daily_loss_pct: float = 5.0
    max_total_loss_pct: float = 10.0
    profit_target_pct: float = 8.0
    min_trading_days: int = 5
    max_trading_days: Optional[int] = None
    no_news_trading: bool = True
    no_weekend_holding: bool = True
    max_lots_per_trade: Optional[float] = None
    max_open_positions: Optional[int] = None
    allowed_symbols: list[str] = []
    restricted_hours: dict = {}

    # Optional
    notes: Optional[str] = None
    broker_account_id: Optional[str] = None
    broker_name: Optional[str] = None
    assigned_strategies: list[dict] = []


class PropFirmAccountUpdate(BaseModel):
    account_name: Optional[str] = None
    phase: Optional[str] = None
    status: Optional[str] = None

    # Rules
    max_daily_loss_pct: Optional[float] = None
    max_total_loss_pct: Optional[float] = None
    profit_target_pct: Optional[float] = None
    min_trading_days: Optional[int] = None
    max_trading_days: Optional[int] = None
    no_news_trading: Optional[bool] = None
    no_weekend_holding: Optional[bool] = None
    max_lots_per_trade: Optional[float] = None
    max_open_positions: Optional[int] = None
    allowed_symbols: Optional[list[str]] = None
    restricted_hours: Optional[dict] = None

    # Strategy assignment
    assigned_strategies: Optional[list[dict]] = None

    # Metadata
    notes: Optional[str] = None
    broker_account_id: Optional[str] = None
    broker_name: Optional[str] = None


# ── Response Schemas ──

class PropFirmTradeResponse(BaseModel):
    id: int
    account_id: int
    symbol: str
    direction: str
    entry_price: float
    exit_price: Optional[float] = None
    lot_size: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    commission: float = 0.0
    status: str
    close_reason: Optional[str] = None
    strategy_id: Optional[int] = None
    balance_before: Optional[float] = None
    balance_after: Optional[float] = None
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PropFirmAccountResponse(BaseModel):
    id: int
    account_name: str
    firm_name: str
    account_size: float
    currency: str
    phase: str
    status: str
    breach_reason: Optional[str] = None

    # Rules
    max_daily_loss_pct: float
    max_total_loss_pct: float
    profit_target_pct: float
    min_trading_days: int
    max_trading_days: Optional[int] = None
    no_news_trading: bool
    no_weekend_holding: bool
    max_lots_per_trade: Optional[float] = None
    max_open_positions: Optional[int] = None
    allowed_symbols: list = []
    restricted_hours: dict = {}

    # Strategy assignment
    assigned_strategies: list = []

    # Tracking
    current_balance: float
    current_equity: float
    total_pnl: float
    today_pnl: float
    max_drawdown_pct: float
    peak_balance: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    trading_days: int

    # Progress
    profit_target_reached: bool
    daily_loss_breached: bool
    total_loss_breached: bool

    # Computed fields
    profit_target_progress_pct: float = 0.0   # How close to profit target
    daily_loss_remaining_pct: float = 0.0     # How much daily loss left
    total_loss_remaining_pct: float = 0.0     # How much total loss left
    win_rate: float = 0.0
    days_remaining: Optional[int] = None

    # Metadata
    notes: Optional[str] = None
    broker_account_id: Optional[str] = None
    broker_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PropFirmAccountSummary(BaseModel):
    """Lightweight summary for list views and dashboard."""
    id: int
    account_name: str
    firm_name: str
    phase: str
    status: str
    account_size: float
    current_balance: float
    total_pnl: float
    today_pnl: float
    max_drawdown_pct: float
    profit_target_progress_pct: float
    total_trades: int
    trading_days: int
    win_rate: float

    class Config:
        from_attributes = True


class PropFirmDashboard(BaseModel):
    """Dashboard widget data — aggregated across all accounts."""
    total_accounts: int
    active_accounts: int
    passed_accounts: int
    breached_accounts: int
    total_pnl: float
    total_trades: int
    accounts: list[PropFirmAccountSummary]


# ── Trade Recording ──

class PropFirmTradeCreate(BaseModel):
    """Record a new trade against a prop firm account."""
    symbol: str
    direction: str  # BUY or SELL
    entry_price: float
    lot_size: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    strategy_id: Optional[int] = None
    agent_id: Optional[int] = None
    broker_ticket: Optional[str] = None


class PropFirmTradeClose(BaseModel):
    """Close an open trade."""
    exit_price: float
    close_reason: str = "manual"  # tp_hit, sl_hit, manual, rule_breach
    commission: float = 0.0
