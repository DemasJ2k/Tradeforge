"""
Prop Firm Account API endpoints.

Full CRUD for prop firm accounts, trade recording, rule checking,
and dashboard aggregation.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.prop_firm import PropFirmAccount, PropFirmTrade
from app.models.user import User
from app.schemas.prop_firm import (
    PropFirmAccountCreate,
    PropFirmAccountUpdate,
    PropFirmAccountResponse,
    PropFirmAccountSummary,
    PropFirmDashboard,
    PropFirmTradeCreate,
    PropFirmTradeClose,
    PropFirmTradeResponse,
    FirmPreset,
)

router = APIRouter(prefix="/api/prop-firms", tags=["Prop Firm Accounts"])
_log = logging.getLogger(__name__)


# ── Firm Presets ──

FIRM_PRESETS = {
    "ftmo_challenge": FirmPreset(
        firm_name="FTMO", phase="challenge",
        max_daily_loss_pct=5.0, max_total_loss_pct=10.0,
        profit_target_pct=10.0, min_trading_days=4,
        max_trading_days=30, no_news_trading=True, no_weekend_holding=True,
    ),
    "ftmo_verification": FirmPreset(
        firm_name="FTMO", phase="verification",
        max_daily_loss_pct=5.0, max_total_loss_pct=10.0,
        profit_target_pct=5.0, min_trading_days=4,
        max_trading_days=60, no_news_trading=True, no_weekend_holding=True,
    ),
    "ftmo_funded": FirmPreset(
        firm_name="FTMO", phase="funded",
        max_daily_loss_pct=5.0, max_total_loss_pct=10.0,
        profit_target_pct=0.0, min_trading_days=0,
        no_news_trading=True, no_weekend_holding=True,
    ),
    "funded_next_challenge": FirmPreset(
        firm_name="Funded Next", phase="challenge",
        max_daily_loss_pct=5.0, max_total_loss_pct=10.0,
        profit_target_pct=8.0, min_trading_days=5,
        max_trading_days=None, no_news_trading=True, no_weekend_holding=True,
    ),
    "funded_next_funded": FirmPreset(
        firm_name="Funded Next", phase="funded",
        max_daily_loss_pct=5.0, max_total_loss_pct=10.0,
        profit_target_pct=0.0, min_trading_days=0,
        no_news_trading=True, no_weekend_holding=True,
    ),
}


def _compute_account_fields(account: PropFirmAccount) -> dict:
    """Compute derived fields for response."""
    size = account.account_size or 1
    balance = account.current_balance or size
    peak = account.peak_balance or size

    # Profit target progress
    if account.profit_target_pct and account.profit_target_pct > 0:
        target_amount = size * (account.profit_target_pct / 100)
        progress = ((balance - size) / target_amount * 100) if target_amount > 0 else 0
        profit_target_progress_pct = min(max(progress, 0), 100)
    else:
        profit_target_progress_pct = 0.0

    # Daily loss remaining
    daily_limit = size * (account.max_daily_loss_pct / 100) if account.max_daily_loss_pct else 0
    daily_used = abs(min(account.today_pnl or 0, 0))
    daily_loss_remaining_pct = ((daily_limit - daily_used) / size * 100) if size > 0 else 0

    # Total loss remaining
    total_limit = size * (account.max_total_loss_pct / 100) if account.max_total_loss_pct else 0
    total_dd_amount = peak - balance
    total_loss_remaining_pct = ((total_limit - total_dd_amount) / size * 100) if size > 0 else 0

    # Win rate
    total = account.total_trades or 0
    wins = account.winning_trades or 0
    win_rate = (wins / total * 100) if total > 0 else 0.0

    # Days remaining
    days_remaining = None
    if account.max_trading_days and account.max_trading_days > 0:
        days_remaining = max(account.max_trading_days - (account.trading_days or 0), 0)

    return {
        "profit_target_progress_pct": round(profit_target_progress_pct, 1),
        "daily_loss_remaining_pct": round(daily_loss_remaining_pct, 2),
        "total_loss_remaining_pct": round(total_loss_remaining_pct, 2),
        "win_rate": round(win_rate, 1),
        "days_remaining": days_remaining,
    }


def _to_response(account: PropFirmAccount) -> PropFirmAccountResponse:
    """Convert model to response with computed fields."""
    computed = _compute_account_fields(account)
    data = {c.name: getattr(account, c.name) for c in account.__table__.columns}
    data.update(computed)
    # Remove fields not in response
    data.pop("user_id", None)
    data.pop("deleted_at", None)
    data.pop("equity_history", None)
    data.pop("today_pnl_date", None)
    data.pop("trading_days_list", None)
    return PropFirmAccountResponse(**data)


def _to_summary(account: PropFirmAccount) -> PropFirmAccountSummary:
    """Convert model to lightweight summary."""
    computed = _compute_account_fields(account)
    return PropFirmAccountSummary(
        id=account.id,
        account_name=account.account_name,
        firm_name=account.firm_name,
        phase=account.phase,
        status=account.status,
        account_size=account.account_size,
        current_balance=account.current_balance,
        total_pnl=account.total_pnl or 0,
        today_pnl=account.today_pnl or 0,
        max_drawdown_pct=account.max_drawdown_pct or 0,
        profit_target_progress_pct=computed["profit_target_progress_pct"],
        total_trades=account.total_trades or 0,
        trading_days=account.trading_days or 0,
        win_rate=computed["win_rate"],
    )


def _check_rules(account: PropFirmAccount, trade_pnl: float = 0.0) -> str | None:
    """
    Check if a trade or current state breaches any prop firm rules.
    Returns breach reason string or None if OK.
    """
    size = account.account_size
    balance = account.current_balance

    # Daily loss check
    if account.max_daily_loss_pct and account.max_daily_loss_pct > 0:
        daily_limit = size * (account.max_daily_loss_pct / 100)
        today_loss = abs(min((account.today_pnl or 0) + trade_pnl, 0))
        if today_loss >= daily_limit:
            return f"Daily loss limit breached: ${today_loss:,.2f} >= ${daily_limit:,.2f} ({account.max_daily_loss_pct}%)"

    # Total drawdown check
    if account.max_total_loss_pct and account.max_total_loss_pct > 0:
        total_limit = size * (account.max_total_loss_pct / 100)
        total_dd = (account.peak_balance or size) - (balance + trade_pnl)
        if total_dd >= total_limit:
            return f"Max drawdown breached: ${total_dd:,.2f} >= ${total_limit:,.2f} ({account.max_total_loss_pct}%)"

    return None


def _reset_daily_pnl_if_needed(account: PropFirmAccount):
    """Reset today_pnl if it's a new day."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if account.today_pnl_date != today:
        account.today_pnl = 0.0
        account.today_pnl_date = today


# ── GET /presets ──

@router.get("/presets")
def get_firm_presets():
    """Return available firm rule presets."""
    return {k: v.model_dump() for k, v in FIRM_PRESETS.items()}


# ── CRUD ──

@router.post("/", response_model=PropFirmAccountResponse)
def create_account(
    payload: PropFirmAccountCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new prop firm account."""
    account = PropFirmAccount(
        user_id=user.id,
        account_name=payload.account_name,
        firm_name=payload.firm_name,
        account_size=payload.account_size,
        currency=payload.currency,
        phase=payload.phase,
        current_balance=payload.account_size,
        current_equity=payload.account_size,
        peak_balance=payload.account_size,
        max_daily_loss_pct=payload.max_daily_loss_pct,
        max_total_loss_pct=payload.max_total_loss_pct,
        profit_target_pct=payload.profit_target_pct,
        min_trading_days=payload.min_trading_days,
        max_trading_days=payload.max_trading_days,
        no_news_trading=payload.no_news_trading,
        no_weekend_holding=payload.no_weekend_holding,
        max_lots_per_trade=payload.max_lots_per_trade,
        max_open_positions=payload.max_open_positions,
        allowed_symbols=payload.allowed_symbols,
        restricted_hours=payload.restricted_hours,
        assigned_strategies=payload.assigned_strategies,
        notes=payload.notes,
        broker_account_id=payload.broker_account_id,
        broker_name=payload.broker_name,
        today_pnl_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    _log.info("Created prop firm account %d: %s (%s %s)",
              account.id, account.account_name, account.firm_name, account.phase)
    return _to_response(account)


@router.get("/", response_model=list[PropFirmAccountSummary])
def list_accounts(
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all prop firm accounts for the current user."""
    q = db.query(PropFirmAccount).filter(
        PropFirmAccount.user_id == user.id,
        PropFirmAccount.deleted_at.is_(None),
    )
    if status:
        q = q.filter(PropFirmAccount.status == status)
    accounts = q.order_by(PropFirmAccount.created_at.desc()).all()
    return [_to_summary(a) for a in accounts]


@router.get("/dashboard", response_model=PropFirmDashboard)
def get_dashboard(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Aggregated dashboard across all prop firm accounts."""
    accounts = db.query(PropFirmAccount).filter(
        PropFirmAccount.user_id == user.id,
        PropFirmAccount.deleted_at.is_(None),
    ).all()

    summaries = [_to_summary(a) for a in accounts]
    return PropFirmDashboard(
        total_accounts=len(accounts),
        active_accounts=sum(1 for a in accounts if a.status == "active"),
        passed_accounts=sum(1 for a in accounts if a.status == "passed"),
        breached_accounts=sum(1 for a in accounts if a.status == "breached"),
        total_pnl=sum(a.total_pnl or 0 for a in accounts),
        total_trades=sum(a.total_trades or 0 for a in accounts),
        accounts=summaries,
    )


@router.get("/{account_id}", response_model=PropFirmAccountResponse)
def get_account(
    account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get detailed account info."""
    account = db.query(PropFirmAccount).filter(
        PropFirmAccount.id == account_id,
        PropFirmAccount.user_id == user.id,
        PropFirmAccount.deleted_at.is_(None),
    ).first()
    if not account:
        raise HTTPException(404, "Account not found")
    _reset_daily_pnl_if_needed(account)
    db.commit()
    return _to_response(account)


@router.put("/{account_id}", response_model=PropFirmAccountResponse)
def update_account(
    account_id: int,
    payload: PropFirmAccountUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update account settings/rules."""
    account = db.query(PropFirmAccount).filter(
        PropFirmAccount.id == account_id,
        PropFirmAccount.user_id == user.id,
        PropFirmAccount.deleted_at.is_(None),
    ).first()
    if not account:
        raise HTTPException(404, "Account not found")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(account, key, value)

    db.commit()
    db.refresh(account)
    return _to_response(account)


@router.delete("/{account_id}")
def delete_account(
    account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-delete a prop firm account."""
    account = db.query(PropFirmAccount).filter(
        PropFirmAccount.id == account_id,
        PropFirmAccount.user_id == user.id,
        PropFirmAccount.deleted_at.is_(None),
    ).first()
    if not account:
        raise HTTPException(404, "Account not found")

    account.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"message": f"Account '{account.account_name}' deleted"}


# ── Trade Recording ──

@router.post("/{account_id}/trades", response_model=PropFirmTradeResponse)
def record_trade_open(
    account_id: int,
    payload: PropFirmTradeCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record a new trade opened in this prop firm account."""
    account = db.query(PropFirmAccount).filter(
        PropFirmAccount.id == account_id,
        PropFirmAccount.user_id == user.id,
        PropFirmAccount.deleted_at.is_(None),
    ).first()
    if not account:
        raise HTTPException(404, "Account not found")
    if account.status != "active":
        raise HTTPException(400, f"Account is {account.status}, cannot open trades")

    # Check allowed symbols
    if account.allowed_symbols and payload.symbol not in account.allowed_symbols:
        raise HTTPException(400, f"Symbol {payload.symbol} not allowed on this account")

    # Check max open positions
    if account.max_open_positions:
        open_count = db.query(PropFirmTrade).filter(
            PropFirmTrade.account_id == account_id,
            PropFirmTrade.status == "open",
        ).count()
        if open_count >= account.max_open_positions:
            raise HTTPException(400, f"Max open positions ({account.max_open_positions}) reached")

    # Check max lot size
    if account.max_lots_per_trade and payload.lot_size > account.max_lots_per_trade:
        raise HTTPException(400, f"Lot size {payload.lot_size} exceeds max {account.max_lots_per_trade}")

    # Pre-trade loss projection: block if worst-case SL hit would breach rules
    _reset_daily_pnl_if_needed(account)
    if payload.stop_loss and (account.max_daily_loss_pct or account.max_total_loss_pct):
        max_trade_loss = abs(payload.entry_price - payload.stop_loss) * payload.lot_size
        breach = _check_rules(account, trade_pnl=-max_trade_loss)
        if breach:
            raise HTTPException(400, f"Trade would breach rules: {breach}")

    trade = PropFirmTrade(
        account_id=account_id,
        symbol=payload.symbol,
        direction=payload.direction,
        entry_price=payload.entry_price,
        lot_size=payload.lot_size,
        stop_loss=payload.stop_loss,
        take_profit=payload.take_profit,
        strategy_id=payload.strategy_id,
        agent_id=payload.agent_id,
        broker_ticket=payload.broker_ticket,
        balance_before=account.current_balance,
        status="open",
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return PropFirmTradeResponse.model_validate(trade)


@router.put("/{account_id}/trades/{trade_id}/close", response_model=PropFirmTradeResponse)
def close_trade(
    account_id: int,
    trade_id: int,
    payload: PropFirmTradeClose,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Close an open trade and update account P&L."""
    account = db.query(PropFirmAccount).filter(
        PropFirmAccount.id == account_id,
        PropFirmAccount.user_id == user.id,
        PropFirmAccount.deleted_at.is_(None),
    ).first()
    if not account:
        raise HTTPException(404, "Account not found")

    trade = db.query(PropFirmTrade).filter(
        PropFirmTrade.id == trade_id,
        PropFirmTrade.account_id == account_id,
        PropFirmTrade.status == "open",
    ).first()
    if not trade:
        raise HTTPException(404, "Open trade not found")

    _reset_daily_pnl_if_needed(account)

    # Calculate PnL
    if trade.direction == "BUY":
        pnl = (payload.exit_price - trade.entry_price) * trade.lot_size
    else:
        pnl = (trade.entry_price - payload.exit_price) * trade.lot_size
    pnl -= payload.commission

    pnl_pct = (pnl / account.account_size * 100) if account.account_size > 0 else 0

    # Update trade
    trade.exit_price = payload.exit_price
    trade.pnl = round(pnl, 2)
    trade.pnl_pct = round(pnl_pct, 4)
    trade.commission = payload.commission
    trade.status = "closed"
    trade.close_reason = payload.close_reason
    trade.closed_at = datetime.now(timezone.utc)
    trade.balance_after = account.current_balance + pnl

    # Update account
    account.current_balance += pnl
    account.current_equity = account.current_balance
    account.total_pnl = (account.total_pnl or 0) + pnl
    account.today_pnl = (account.today_pnl or 0) + pnl
    account.total_trades = (account.total_trades or 0) + 1

    if pnl > 0:
        account.winning_trades = (account.winning_trades or 0) + 1
    elif pnl < 0:
        account.losing_trades = (account.losing_trades or 0) + 1

    # Update peak balance (high-water mark)
    if account.current_balance > (account.peak_balance or account.account_size):
        account.peak_balance = account.current_balance

    # Update max drawdown
    dd_pct = ((account.peak_balance - account.current_balance) / account.account_size * 100) if account.account_size > 0 else 0
    if dd_pct > (account.max_drawdown_pct or 0):
        account.max_drawdown_pct = round(dd_pct, 2)

    # Update trading days
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    days_list = account.trading_days_list or []
    if today not in days_list:
        days_list.append(today)
        account.trading_days_list = days_list
        account.trading_days = len(days_list)

    # Add to equity history
    history = account.equity_history or []
    history.append({
        "date": today,
        "balance": round(account.current_balance, 2),
        "equity": round(account.current_equity, 2),
        "pnl": round(pnl, 2),
        "trade_id": trade.id,
    })
    account.equity_history = history

    # Check profit target
    if account.profit_target_pct and account.profit_target_pct > 0:
        target = account.account_size * (1 + account.profit_target_pct / 100)
        if account.current_balance >= target:
            account.profit_target_reached = True

    # Check rule breaches
    breach = _check_rules(account)
    if breach:
        account.status = "breached"
        account.breach_reason = breach
        if "Daily loss" in breach:
            account.daily_loss_breached = True
        elif "drawdown" in breach:
            account.total_loss_breached = True
        _log.warning("Prop firm account %d breached: %s", account.id, breach)

    db.commit()
    db.refresh(trade)
    return PropFirmTradeResponse.model_validate(trade)


@router.get("/{account_id}/trades", response_model=list[PropFirmTradeResponse])
def list_trades(
    account_id: int,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List trades for a prop firm account."""
    account = db.query(PropFirmAccount).filter(
        PropFirmAccount.id == account_id,
        PropFirmAccount.user_id == user.id,
        PropFirmAccount.deleted_at.is_(None),
    ).first()
    if not account:
        raise HTTPException(404, "Account not found")

    q = db.query(PropFirmTrade).filter(PropFirmTrade.account_id == account_id)
    if status:
        q = q.filter(PropFirmTrade.status == status)
    trades = q.order_by(PropFirmTrade.opened_at.desc()).offset(offset).limit(limit).all()
    return [PropFirmTradeResponse.model_validate(t) for t in trades]


@router.get("/{account_id}/equity-curve")
def get_equity_curve(
    account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get equity curve data for charting."""
    account = db.query(PropFirmAccount).filter(
        PropFirmAccount.id == account_id,
        PropFirmAccount.user_id == user.id,
        PropFirmAccount.deleted_at.is_(None),
    ).first()
    if not account:
        raise HTTPException(404, "Account not found")

    return {
        "account_id": account.id,
        "account_name": account.account_name,
        "account_size": account.account_size,
        "profit_target": account.account_size * (1 + (account.profit_target_pct or 0) / 100),
        "loss_limit": account.account_size * (1 - (account.max_total_loss_pct or 0) / 100),
        "history": account.equity_history or [],
    }


# ── Account Actions ──

@router.post("/{account_id}/pause")
def pause_account(
    account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pause trading on this account."""
    account = db.query(PropFirmAccount).filter(
        PropFirmAccount.id == account_id,
        PropFirmAccount.user_id == user.id,
    ).first()
    if not account:
        raise HTTPException(404, "Account not found")
    account.status = "paused"
    db.commit()
    return {"message": f"Account '{account.account_name}' paused"}


@router.post("/{account_id}/resume")
def resume_account(
    account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Resume trading on a paused account."""
    account = db.query(PropFirmAccount).filter(
        PropFirmAccount.id == account_id,
        PropFirmAccount.user_id == user.id,
    ).first()
    if not account:
        raise HTTPException(404, "Account not found")
    if account.status == "breached":
        raise HTTPException(400, "Cannot resume a breached account")
    account.status = "active"
    db.commit()
    return {"message": f"Account '{account.account_name}' resumed"}


@router.post("/{account_id}/reset")
def reset_account(
    account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reset account to starting state (e.g., for a new challenge attempt)."""
    account = db.query(PropFirmAccount).filter(
        PropFirmAccount.id == account_id,
        PropFirmAccount.user_id == user.id,
    ).first()
    if not account:
        raise HTTPException(404, "Account not found")

    # Reset all tracking fields
    account.current_balance = account.account_size
    account.current_equity = account.account_size
    account.peak_balance = account.account_size
    account.total_pnl = 0.0
    account.today_pnl = 0.0
    account.max_drawdown_pct = 0.0
    account.total_trades = 0
    account.winning_trades = 0
    account.losing_trades = 0
    account.trading_days = 0
    account.trading_days_list = []
    account.equity_history = []
    account.profit_target_reached = False
    account.daily_loss_breached = False
    account.total_loss_breached = False
    account.breach_reason = None
    account.status = "active"

    # Delete all trades
    db.query(PropFirmTrade).filter(PropFirmTrade.account_id == account_id).delete()

    db.commit()
    return {"message": f"Account '{account.account_name}' reset to ${account.account_size:,.2f}"}
