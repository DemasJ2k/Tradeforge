"""
Pre-trade prop firm rule validation.

Validates a potential trade against prop firm account rules BEFORE execution,
projecting worst-case loss from SL to ensure no rule breach would occur.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.prop_firm import PropFirmAccount, PropFirmTrade

logger = logging.getLogger(__name__)


def validate_pre_trade(
    account: PropFirmAccount,
    symbol: str,
    direction: str,
    entry_price: float,
    stop_loss: float | None,
    lot_size: float,
    db: Session,
) -> str | None:
    """
    Validate a trade against prop firm rules before execution.

    Returns a breach reason string if the trade should be blocked,
    or None if the trade is allowed.

    Checks (in order):
      1. Account status must be "active"
      2. Symbol must be in allowed_symbols (if set)
      3. Open positions must not exceed max_open_positions
      4. Lot size must not exceed max_lots_per_trade
      5. Restricted hours check
      6. Projected daily loss (worst-case from SL)
      7. Projected total drawdown (worst-case from SL)
    """
    # 1. Account status
    if account.status != "active":
        return f"Account is {account.status}, cannot open trades"

    # 2. Allowed symbols
    if account.allowed_symbols and symbol not in account.allowed_symbols:
        return f"Symbol {symbol} not allowed on this account"

    # 3. Max open positions
    if account.max_open_positions:
        open_count = db.query(PropFirmTrade).filter(
            PropFirmTrade.account_id == account.id,
            PropFirmTrade.status == "open",
        ).count()
        if open_count >= account.max_open_positions:
            return f"Max open positions ({account.max_open_positions}) reached"

    # 4. Max lot size
    if account.max_lots_per_trade and lot_size > account.max_lots_per_trade:
        return f"Lot size {lot_size} exceeds max {account.max_lots_per_trade}"

    # 5. Restricted hours
    if account.restricted_hours:
        now_utc = datetime.now(timezone.utc)
        hour_str = now_utc.strftime("%H:%M")
        start = account.restricted_hours.get("start", "")
        end = account.restricted_hours.get("end", "")
        if start and end:
            if start <= end:
                if start <= hour_str <= end:
                    return f"Trading restricted between {start}-{end} UTC"
            else:  # wraps midnight, e.g. 23:00 -> 01:00
                if hour_str >= start or hour_str <= end:
                    return f"Trading restricted between {start}-{end} UTC"

    # 6 & 7. Projected loss checks
    if stop_loss and (account.max_daily_loss_pct or account.max_total_loss_pct):
        # Estimate worst-case loss if SL is hit
        max_trade_loss = abs(entry_price - stop_loss) * lot_size

        size = account.account_size
        balance = account.current_balance

        # Reset daily pnl if needed
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_pnl = account.today_pnl or 0.0
        if account.today_pnl_date != today:
            today_pnl = 0.0

        # 6. Daily loss projection
        if account.max_daily_loss_pct and account.max_daily_loss_pct > 0:
            daily_limit = size * (account.max_daily_loss_pct / 100)
            projected_daily_loss = abs(min(today_pnl - max_trade_loss, 0))
            if projected_daily_loss >= daily_limit:
                return (
                    f"Trade would breach daily loss limit: "
                    f"projected ${projected_daily_loss:,.2f} >= "
                    f"${daily_limit:,.2f} ({account.max_daily_loss_pct}%)"
                )

        # 7. Total drawdown projection
        if account.max_total_loss_pct and account.max_total_loss_pct > 0:
            total_limit = size * (account.max_total_loss_pct / 100)
            peak = account.peak_balance or size
            projected_dd = peak - (balance - max_trade_loss)
            if projected_dd >= total_limit:
                return (
                    f"Trade would breach max drawdown: "
                    f"projected ${projected_dd:,.2f} >= "
                    f"${total_limit:,.2f} ({account.max_total_loss_pct}%)"
                )

    return None
