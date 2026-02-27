"""
Dedicated backtester for MSS and Gold BT strategies.

Uses the EXACT same logic as the optimization scripts and strategy engines,
producing results in the standard BacktestResult format for the UI.
"""

import math
import logging
from datetime import datetime, timezone
from typing import Optional

from app.services.backtest.engine import Bar, Trade, BacktestResult

logger = logging.getLogger(__name__)


def compute_adr10_series(bars: list[dict]) -> list[float]:
    """Compute rolling ADR10 for each bar (using daily ranges from M10 data)."""
    n = len(bars)
    adr = [0.0] * n

    # Build daily ranges
    daily_ranges = []
    day_high = bars[0]["high"]
    day_low = bars[0]["low"]
    prev_day = -1

    for i in range(n):
        ts = int(bars[i]["time"])
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        day_ord = dt.toordinal()

        if prev_day == -1:
            prev_day = day_ord

        if day_ord != prev_day:
            daily_ranges.append(day_high - day_low)
            day_high = bars[i]["high"]
            day_low = bars[i]["low"]
            prev_day = day_ord
        else:
            day_high = max(day_high, bars[i]["high"])
            day_low = min(day_low, bars[i]["low"])

        if daily_ranges:
            last_n = daily_ranges[-10:] if len(daily_ranges) >= 10 else daily_ranges
            adr[i] = sum(last_n) / len(last_n)

    return adr


def backtest_mss(
    bars_raw: list[Bar],
    mss_config: dict,
    initial_balance: float = 10000.0,
    spread_points: float = 0.0,
    commission_per_lot: float = 0.0,
    point_value: float = 1.0,
) -> BacktestResult:
    """
    Run MSS backtest using the EXACT same logic as optimize_strategies.py.
    """
    # Convert Bar objects to dicts
    bars = [
        {"time": b.time, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume}
        for b in bars_raw
    ]

    lb = mss_config.get("swing_lb", 42)
    tp1_pct = mss_config.get("tp1_pct", 15.0)
    tp2_pct = mss_config.get("tp2_pct", 25.0)
    sl_pct = mss_config.get("sl_pct", 25.0)
    use_pb = mss_config.get("use_pullback", True)
    pb_pct = mss_config.get("pb_pct", 0.382)
    use_close = mss_config.get("confirm", "close") == "close"

    N = len(bars)
    min_needed = lb * 2 + 1
    if N < min_needed:
        return BacktestResult(total_bars=N)

    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    closes = [b["close"] for b in bars]

    # Precompute ADR10
    adr10 = compute_adr10_series(bars)

    # Detect all pivots
    pivot_highs = [None] * N
    pivot_lows = [None] * N
    for i in range(lb, N - lb):
        window_h = highs[i - lb: i + lb + 1]
        val_h = highs[i]
        if val_h == max(window_h) and window_h.count(val_h) == 1:
            pivot_highs[i] = val_h
        window_l = lows[i - lb: i + lb + 1]
        val_l = lows[i]
        if val_l == min(window_l) and window_l.count(val_l) == 1:
            pivot_lows[i] = val_l

    # State
    last_high = float("nan")
    last_low = float("nan")
    high_active = False
    low_active = False
    last_break_dir = 0

    active_entry = 0.0
    active_sl = 0.0
    active_tp1 = 0.0
    active_tp2 = 0.0
    active_dir = 0

    trades_list: list[Trade] = []
    equity_curve = [initial_balance]
    balance = initial_balance
    lot_size = 0.01

    consec_losses = 0
    max_consec = 0
    peak_balance = initial_balance
    max_dd = 0.0
    max_dd_pct = 0.0
    active_entry_bar = 0
    active_entry_time = 0.0

    for i in range(lb * 2, N):
        # Update pivots
        pivot_bar = i - lb
        if pivot_bar >= 0:
            if pivot_highs[pivot_bar] is not None:
                last_high = pivot_highs[pivot_bar]
                high_active = True
            if pivot_lows[pivot_bar] is not None:
                last_low = pivot_lows[pivot_bar]
                low_active = True

        # Breakout detection
        src_h = closes[i] if use_close else highs[i]
        src_l = closes[i] if use_close else lows[i]

        bullish = False
        bearish = False

        if high_active and not math.isnan(last_high) and src_h > last_high:
            bullish = True
            high_active = False
        if low_active and not math.isnan(last_low) and src_l < last_low:
            bearish = True
            low_active = False

        if bullish:
            last_break_dir = 1
        if bearish:
            last_break_dir = -1

        # Check active trade exits
        if active_dir != 0:
            hit_tp2 = False
            hit_tp1 = False
            hit_sl = False

            if active_dir == 1:
                hit_tp2 = highs[i] >= active_tp2
                hit_tp1 = highs[i] >= active_tp1
                hit_sl = lows[i] <= active_sl
            else:
                hit_tp2 = lows[i] <= active_tp2
                hit_tp1 = lows[i] <= active_tp1
                hit_sl = highs[i] >= active_sl

            exit_price = None
            exit_reason = ""

            if hit_tp2:
                exit_price = active_tp2
                exit_reason = "TP2"
            elif hit_tp1 and not hit_sl:
                exit_price = active_tp1
                exit_reason = "TP1"
            elif hit_sl:
                exit_price = active_sl
                exit_reason = "SL"

            if exit_price is not None:
                pnl = abs(exit_price - active_entry) if exit_reason != "SL" else -abs(active_sl - active_entry)
                if active_dir == -1 and exit_reason != "SL":
                    pnl = abs(active_entry - exit_price)
                elif active_dir == -1 and exit_reason == "SL":
                    pnl = -(abs(active_sl - active_entry))

                # Apply commission and spread
                cost = commission_per_lot * lot_size + spread_points * point_value * lot_size
                pnl_dollar = pnl * point_value * lot_size * 100 - cost
                balance += pnl_dollar

                trades_list.append(Trade(
                    entry_bar=active_entry_bar,
                    entry_time=active_entry_time,
                    entry_price=active_entry,
                    direction="long" if active_dir == 1 else "short",
                    size=lot_size,
                    stop_loss=active_sl,
                    take_profit=active_tp2,
                    exit_bar=i,
                    exit_time=bars[i]["time"],
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    pnl=round(pnl_dollar, 2),
                    pnl_pct=round(pnl_dollar / initial_balance * 100, 2),
                ))

                active_dir = 0

                if balance > peak_balance:
                    peak_balance = balance
                dd = peak_balance - balance
                dd_pct = dd / peak_balance * 100 if peak_balance > 0 else 0
                if dd > max_dd:
                    max_dd = dd
                if dd_pct > max_dd_pct:
                    max_dd_pct = dd_pct

        equity_curve.append(balance)

        # Signal handling
        signal_dir = 0
        if bullish and not math.isnan(last_high):
            signal_dir = 1
        elif bearish and not math.isnan(last_low):
            signal_dir = -1

        if signal_dir == 0:
            continue

        # Close existing trade on reversal
        if active_dir != 0:
            if active_dir == 1:
                rev_pnl = closes[i] - active_entry
            else:
                rev_pnl = active_entry - closes[i]

            cost = commission_per_lot * lot_size + spread_points * point_value * lot_size
            rev_pnl_dollar = rev_pnl * point_value * lot_size * 100 - cost
            balance += rev_pnl_dollar

            trades_list.append(Trade(
                entry_bar=active_entry_bar,
                entry_time=active_entry_time,
                entry_price=active_entry,
                direction="long" if active_dir == 1 else "short",
                size=lot_size,
                stop_loss=active_sl,
                take_profit=active_tp2,
                exit_bar=i,
                exit_time=bars[i]["time"],
                exit_price=closes[i],
                exit_reason="Reversal",
                pnl=round(rev_pnl_dollar, 2),
                pnl_pct=round(rev_pnl_dollar / initial_balance * 100, 2),
            ))

            active_dir = 0

        # Open new trade
        a = adr10[i]
        if a <= 0:
            continue

        tp1_dist = a * (tp1_pct / 100.0)
        tp2_dist = a * (tp2_pct / 100.0)
        sl_dist = a * (sl_pct / 100.0)
        pivot = last_high if signal_dir == 1 else last_low

        if signal_dir == 1:
            entry = pivot - pb_pct * sl_dist if use_pb else pivot
            sl = entry - sl_dist
            tp1 = entry + tp1_dist
            tp2 = entry + tp2_dist
        else:
            entry = pivot + pb_pct * sl_dist if use_pb else pivot
            sl = entry + sl_dist
            tp1 = entry - tp1_dist
            tp2 = entry - tp2_dist

        active_entry = entry
        active_sl = sl
        active_tp1 = tp1
        active_tp2 = tp2
        active_dir = signal_dir
        active_entry_bar = i
        active_entry_time = bars[i]["time"]

    # Build stats
    return _build_result(trades_list, equity_curve, initial_balance, N, max_dd, max_dd_pct)


def backtest_gold_bt(
    bars_raw: list[Bar],
    gold_config: dict,
    initial_balance: float = 10000.0,
    spread_points: float = 0.0,
    commission_per_lot: float = 0.0,
    point_value: float = 1.0,
) -> BacktestResult:
    """
    Run Gold BT backtest using the EXACT same logic as optimize_strategies.py.
    """
    bars = [
        {"time": b.time, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume}
        for b in bars_raw
    ]

    interval_h = gold_config.get("trigger_interval_hours", 2)
    box_h = gold_config.get("box_height", 10.0)
    buffer = gold_config.get("stop_line_buffer", 2.0)
    s2tp_gap = gold_config.get("stop_to_tp_gap", 2.0)
    tp_gap = gold_config.get("tp_zone_gap", 1.0)
    tp1_h = gold_config.get("tp1_height", 4.0)
    tp2_h = gold_config.get("tp2_height", 4.0)
    sl_type = gold_config.get("sl_type", "opposite_stop")
    sl_fixed = gold_config.get("sl_fixed_usd", 14.0)

    ref_price = 0.0
    buy_stop = 0.0
    sell_stop = 0.0
    last_trigger_hour = -1
    last_trigger_day = -1

    active_entry = 0.0
    active_sl = 0.0
    active_tp1 = 0.0
    active_tp2 = 0.0
    active_dir = 0
    active_entry_bar = 0
    active_entry_time = 0.0

    trades_list: list[Trade] = []
    balance = initial_balance
    equity_curve = [initial_balance]
    lot_size = 0.01

    peak_balance = initial_balance
    max_dd = 0.0
    max_dd_pct = 0.0

    N = len(bars)
    for i in range(1, N):
        bar = bars[i]
        prev = bars[i - 1]
        ts = int(bar["time"])
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        h, m = dt.hour, dt.minute

        # Check trigger
        is_trigger = False
        if m == 0 and h % interval_h == 0:
            day_ord = dt.toordinal()
            if day_ord != last_trigger_day or h != last_trigger_hour:
                is_trigger = True
                last_trigger_day = day_ord
                last_trigger_hour = h

        if is_trigger:
            ref_price = bar["close"]
            half = box_h / 2.0
            buy_stop = ref_price + half + buffer
            sell_stop = ref_price - half - buffer
            equity_curve.append(balance)
            continue

        if buy_stop == 0:
            equity_curve.append(balance)
            continue

        def calc_levels(direction):
            if direction == 1:
                entry = buy_stop
                t1_bot = entry + s2tp_gap
                t1_top = t1_bot + tp1_h
                tp1_mid = (t1_top + t1_bot) / 2.0
                t2_bot = t1_top + tp_gap
                t2_top = t2_bot + tp2_h
                tp2_mid = (t2_top + t2_bot) / 2.0
                if sl_type == "opposite_stop":
                    sl = sell_stop
                elif sl_type == "gray_box":
                    sl = ref_price - box_h / 2.0
                else:
                    sl = entry - sl_fixed
                return entry, sl, tp1_mid, tp2_mid
            else:
                entry = sell_stop
                t1_top = entry - s2tp_gap
                t1_bot = t1_top - tp1_h
                tp1_mid = (t1_top + t1_bot) / 2.0
                t2_top = t1_bot - tp_gap
                t2_bot = t2_top - tp2_h
                tp2_mid = (t2_top + t2_bot) / 2.0
                if sl_type == "opposite_stop":
                    sl = buy_stop
                elif sl_type == "gray_box":
                    sl = ref_price + box_h / 2.0
                else:
                    sl = entry + sl_fixed
                return entry, sl, tp1_mid, tp2_mid

        # Check active trade exits
        if active_dir != 0:
            hit_tp2 = False
            hit_tp1 = False
            hit_sl = False

            if active_dir == 1:
                hit_tp2 = bar["high"] >= active_tp2
                hit_tp1 = bar["high"] >= active_tp1
                hit_sl = bar["low"] <= active_sl
            else:
                hit_tp2 = bar["low"] <= active_tp2
                hit_tp1 = bar["low"] <= active_tp1
                hit_sl = bar["high"] >= active_sl

            exit_price = None
            exit_reason = ""

            if hit_tp2:
                exit_price = active_tp2
                exit_reason = "TP2"
                pnl = abs(active_tp2 - active_entry)
            elif hit_tp1 and not hit_sl:
                exit_price = active_tp1
                exit_reason = "TP1"
                pnl = abs(active_tp1 - active_entry)
            elif hit_sl:
                exit_price = active_sl
                exit_reason = "SL"
                pnl = -abs(active_sl - active_entry)

            if exit_price is not None:
                cost = commission_per_lot * lot_size + spread_points * point_value * lot_size
                pnl_dollar = pnl * point_value * lot_size * 100 - cost
                balance += pnl_dollar

                trades_list.append(Trade(
                    entry_bar=active_entry_bar,
                    entry_time=active_entry_time,
                    entry_price=active_entry,
                    direction="long" if active_dir == 1 else "short",
                    size=lot_size,
                    stop_loss=active_sl,
                    take_profit=active_tp2,
                    exit_bar=i,
                    exit_time=bar["time"],
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    pnl=round(pnl_dollar, 2),
                    pnl_pct=round(pnl_dollar / initial_balance * 100, 2),
                ))

                active_dir = 0

                if balance > peak_balance:
                    peak_balance = balance
                dd = peak_balance - balance
                dd_pct = dd / peak_balance * 100 if peak_balance > 0 else 0
                if dd > max_dd:
                    max_dd = dd
                if dd_pct > max_dd_pct:
                    max_dd_pct = dd_pct

            if active_dir != 0:
                equity_curve.append(balance)
                continue

        # Check for new entries
        prev_close = prev["close"]
        curr_close = bar["close"]

        new_signal = 0
        if prev_close <= buy_stop and curr_close > buy_stop:
            new_signal = 1
        elif prev_close >= sell_stop and curr_close < sell_stop:
            new_signal = -1

        if new_signal != 0:
            # Close existing on reversal
            if active_dir != 0 and active_dir != new_signal:
                if active_dir == 1:
                    pnl_rev = curr_close - active_entry
                else:
                    pnl_rev = active_entry - curr_close

                cost = commission_per_lot * lot_size + spread_points * point_value * lot_size
                pnl_dollar = pnl_rev * point_value * lot_size * 100 - cost
                balance += pnl_dollar

                trades_list.append(Trade(
                    entry_bar=active_entry_bar,
                    entry_time=active_entry_time,
                    entry_price=active_entry,
                    direction="long" if active_dir == 1 else "short",
                    size=lot_size,
                    stop_loss=active_sl,
                    take_profit=active_tp2,
                    exit_bar=i,
                    exit_time=bar["time"],
                    exit_price=curr_close,
                    exit_reason="Reversal",
                    pnl=round(pnl_dollar, 2),
                    pnl_pct=round(pnl_dollar / initial_balance * 100, 2),
                ))
                active_dir = 0

            # Open new trade
            entry, sl, tp1, tp2 = calc_levels(new_signal)
            active_entry = entry
            active_sl = sl
            active_tp1 = tp1
            active_tp2 = tp2
            active_dir = new_signal
            active_entry_bar = i
            active_entry_time = bar["time"]

        equity_curve.append(balance)

    return _build_result(trades_list, equity_curve, initial_balance, N, max_dd, max_dd_pct)


def _build_result(
    trades: list[Trade],
    equity_curve: list[float],
    initial_balance: float,
    total_bars: int,
    max_dd: float,
    max_dd_pct: float,
) -> BacktestResult:
    """Build BacktestResult from trade list."""
    result = BacktestResult(
        trades=trades,
        equity_curve=equity_curve,
        total_bars=total_bars,
    )

    if not trades:
        return result

    result.total_trades = len(trades)
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]

    result.winning_trades = len(wins)
    result.losing_trades = len(losses)
    result.win_rate = len(wins) / len(trades) * 100 if trades else 0

    result.gross_profit = sum(t.pnl for t in wins) if wins else 0
    result.gross_loss = abs(sum(t.pnl for t in losses)) if losses else 0
    result.net_profit = result.gross_profit - result.gross_loss

    result.profit_factor = result.gross_profit / result.gross_loss if result.gross_loss > 0 else 999.0

    result.avg_win = result.gross_profit / len(wins) if wins else 0
    result.avg_loss = -result.gross_loss / len(losses) if losses else 0
    result.largest_win = max(t.pnl for t in wins) if wins else 0
    result.largest_loss = min(t.pnl for t in losses) if losses else 0

    result.avg_trade = result.net_profit / len(trades) if trades else 0
    result.expectancy = result.avg_trade

    result.max_drawdown = max_dd
    result.max_drawdown_pct = max_dd_pct

    # Sharpe ratio (simplified)
    if len(trades) > 1:
        pnls = [t.pnl for t in trades]
        mean_pnl = sum(pnls) / len(pnls)
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
        std = math.sqrt(variance) if variance > 0 else 1
        result.sharpe_ratio = (mean_pnl / std) * math.sqrt(252) if std > 0 else 0

    return result
