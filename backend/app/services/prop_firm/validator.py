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
      3. Max open positions
      4. Max lot size per trade
      5. Restricted hours
      6. Weekend holding restriction
      7. Projected daily loss (worst-case from SL)
      8. Projected total drawdown (worst-case from SL)
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

    now_utc = datetime.now(timezone.utc)

    # 5. Restricted hours
    if account.restricted_hours:
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

    # 6. Weekend holding restriction — block new trades after Friday 21:00 UTC
    if getattr(account, "no_weekend_holding", False):
        weekday = now_utc.weekday()  # 0=Mon ... 4=Fri, 5=Sat, 6=Sun
        if weekday == 4 and now_utc.hour >= 21:
            return "No weekend holding: new trades blocked after Friday 21:00 UTC"
        if weekday in (5, 6):
            return "No weekend holding: trading blocked on weekends"

    # 6b. News trading restriction — block 30min before/after high-impact events
    if getattr(account, "no_news_trading", False):
        reason = _check_news_window(now_utc)
        if reason:
            return reason

    # 7 & 8. Projected loss checks
    if stop_loss and (account.max_daily_loss_pct or account.max_total_loss_pct):
        # Estimate worst-case loss if SL is hit
        max_trade_loss = abs(entry_price - stop_loss) * lot_size

        size = account.account_size
        balance = account.current_balance

        # Reset daily pnl if needed
        today = now_utc.strftime("%Y-%m-%d")
        today_pnl = account.today_pnl or 0.0
        if account.today_pnl_date != today:
            today_pnl = 0.0

        # 7. Daily loss projection
        if account.max_daily_loss_pct and account.max_daily_loss_pct > 0:
            daily_limit = size * (account.max_daily_loss_pct / 100)
            projected_daily_loss = abs(min(today_pnl - max_trade_loss, 0))
            if projected_daily_loss >= daily_limit:
                return (
                    f"Trade would breach daily loss limit: "
                    f"projected ${projected_daily_loss:,.2f} >= "
                    f"${daily_limit:,.2f} ({account.max_daily_loss_pct}%)"
                )

        # 8. Total drawdown projection
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


def validate_pre_trade_detailed(
    account: PropFirmAccount,
    symbol: str,
    direction: str,
    entry_price: float,
    stop_loss: float | None,
    lot_size: float,
    db: Session,
) -> dict:
    """
    Detailed pre-trade validation with budget information.

    Returns a dict with:
      - allowed (bool): Whether the trade is permitted
      - reason (str | None): Block reason if not allowed
      - projected_daily_loss (float): Worst-case daily loss after this trade
      - projected_drawdown (float): Worst-case total drawdown after this trade
      - remaining_daily_budget (float): $ remaining before daily limit hit
      - remaining_drawdown_budget (float): $ remaining before max DD hit
      - daily_limit (float): Total daily loss limit in $
      - drawdown_limit (float): Total drawdown limit in $
      - open_positions (int): Current open position count
      - max_positions (int | None): Max positions allowed
    """
    now_utc = datetime.now(timezone.utc)
    size = account.account_size or 0
    balance = account.current_balance or size
    peak = account.peak_balance or size

    # Reset daily pnl if needed
    today = now_utc.strftime("%Y-%m-%d")
    today_pnl = account.today_pnl or 0.0
    if account.today_pnl_date != today:
        today_pnl = 0.0

    # Compute budget numbers
    daily_limit = size * (account.max_daily_loss_pct / 100) if account.max_daily_loss_pct else 0
    drawdown_limit = size * (account.max_total_loss_pct / 100) if account.max_total_loss_pct else 0

    daily_used = abs(min(today_pnl, 0))
    remaining_daily = max(daily_limit - daily_used, 0)

    current_dd = max(peak - balance, 0)
    remaining_dd = max(drawdown_limit - current_dd, 0)

    # Worst-case projections from SL
    max_trade_loss = 0.0
    if stop_loss and entry_price:
        max_trade_loss = abs(entry_price - stop_loss) * lot_size

    projected_daily_loss = abs(min(today_pnl - max_trade_loss, 0))
    projected_dd = peak - (balance - max_trade_loss)

    # Open positions count
    open_count = db.query(PropFirmTrade).filter(
        PropFirmTrade.account_id == account.id,
        PropFirmTrade.status == "open",
    ).count()

    # Run the standard validation
    breach = validate_pre_trade(
        account=account,
        symbol=symbol,
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        lot_size=lot_size,
        db=db,
    )

    return {
        "allowed": breach is None,
        "reason": breach,
        "projected_daily_loss": round(projected_daily_loss, 2),
        "projected_drawdown": round(max(projected_dd, 0), 2),
        "remaining_daily_budget": round(remaining_daily, 2),
        "remaining_drawdown_budget": round(remaining_dd, 2),
        "daily_limit": round(daily_limit, 2),
        "drawdown_limit": round(drawdown_limit, 2),
        "open_positions": open_count,
        "max_positions": account.max_open_positions,
        "max_trade_loss": round(max_trade_loss, 2),
    }


# ── High-impact news schedule (static, covers major recurring events) ──────

# Each entry: (day_of_week, hour_utc, minute_utc, label)
# day_of_week: 0=Mon..4=Fri, or None for monthly events
_HIGH_IMPACT_WEEKLY = [
    # US session opens / ISM / employment data — typically Tue-Fri 13:30-15:00 UTC
    (1, 15, 0, "US data release window"),   # Tuesday ISM
    (2, 13, 30, "US data release window"),  # Wednesday ADP/GDP
    (3, 13, 30, "US data release window"),  # Thursday claims
]

# NFP: First Friday of month at 13:30 UTC
# FOMC: ~every 6 weeks on Wednesday at 19:00 UTC (8 meetings/year)
_NEWS_BUFFER_MINUTES = 30


def _check_news_window(now_utc: datetime) -> str | None:
    """
    Check if current time falls within ±30min of a known high-impact news window.

    Returns a reason string if blocked, None if OK.
    Uses a static schedule of recurring US/EU events.
    """
    weekday = now_utc.weekday()
    current_minutes = now_utc.hour * 60 + now_utc.minute

    # Check weekly recurring events
    for wd, hour, minute, label in _HIGH_IMPACT_WEEKLY:
        if weekday == wd:
            event_minutes = hour * 60 + minute
            if abs(current_minutes - event_minutes) <= _NEWS_BUFFER_MINUTES:
                return f"News trading restricted: {label} (±{_NEWS_BUFFER_MINUTES}min buffer)"

    # NFP: First Friday of month at 13:30 UTC
    if weekday == 4 and now_utc.day <= 7:
        nfp_minutes = 13 * 60 + 30
        if abs(current_minutes - nfp_minutes) <= _NEWS_BUFFER_MINUTES:
            return f"News trading restricted: NFP release (±{_NEWS_BUFFER_MINUTES}min buffer)"

    # FOMC: Wednesdays at 19:00 UTC (check every Wednesday — overly cautious
    # but better than missing an actual FOMC day)
    if weekday == 2:
        fomc_minutes = 19 * 60
        if abs(current_minutes - fomc_minutes) <= _NEWS_BUFFER_MINUTES:
            return f"News trading restricted: potential FOMC window (±{_NEWS_BUFFER_MINUTES}min buffer)"

    return None
