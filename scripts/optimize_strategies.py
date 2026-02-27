"""
Strategy Optimizer — backtests Gold BT and MSS strategies on XAUUSD data.
Runs parameter grid search and reports best configurations.
"""
import csv
import sys
import time
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

# ─── Data Loading ───────────────────────────────────────

def load_csv(path: str) -> list[dict]:
    """Load OHLCV CSV into list of dicts with numeric time field."""
    rows = []
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_str = row.get("time") or row.get("Time") or row.get("date") or ""
            try:
                dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                dt = dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            rows.append({
                "time": int(dt.timestamp()),
                "open": float(row.get("open") or row.get("Open", 0)),
                "high": float(row.get("high") or row.get("High", 0)),
                "low": float(row.get("low") or row.get("Low", 0)),
                "close": float(row.get("close") or row.get("Close", 0)),
                "volume": float(row.get("tick_volume") or row.get("volume") or row.get("Volume", 0)),
            })
    return rows


# ─── Trade Result ───────────────────────────────────────

@dataclass
class Trade:
    entry_bar: int
    entry_time: float
    entry_price: float
    direction: str  # "long" or "short"
    stop_loss: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl: float = 0.0


@dataclass
class BacktestStats:
    total_trades: int = 0
    tp1_wins: int = 0
    tp2_wins: int = 0
    sl_losses: int = 0
    reversals: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_pnl: float = 0.0
    expectancy: float = 0.0
    max_consec_losses: int = 0
    max_drawdown: float = 0.0


# ══════════════════════════════════════════════════════════
#  GOLD BREAKOUT TRADER BACKTESTER
# ══════════════════════════════════════════════════════════

def backtest_gold_bt(bars: list[dict], cfg: dict) -> BacktestStats:
    """
    Backtest Gold Breakout Trader strategy.

    cfg keys: box_height, stop_line_buffer, stop_to_tp_gap, tp_zone_gap,
              tp1_height, tp2_height, sl_type, trigger_interval_hours
    """
    interval_h = cfg.get("trigger_interval_hours", 2)
    box_h = cfg.get("box_height", 10.0)
    buffer = cfg.get("stop_line_buffer", 2.0)
    s2tp_gap = cfg.get("stop_to_tp_gap", 2.0)
    tp_gap = cfg.get("tp_zone_gap", 1.0)
    tp1_h = cfg.get("tp1_height", 4.0)
    tp2_h = cfg.get("tp2_height", 4.0)
    sl_type = cfg.get("sl_type", "opposite_stop")
    sl_fixed = cfg.get("sl_fixed_usd", 14.0)

    # State
    ref_price = 0.0
    buy_stop = 0.0
    sell_stop = 0.0
    last_trigger_hour = -1
    last_trigger_day = -1

    # Active trade tracking
    active_entry = 0.0
    active_sl = 0.0
    active_tp1 = 0.0
    active_tp2 = 0.0
    active_dir = 0  # 1=long, -1=short

    trades_closed = []
    consec_losses = 0
    max_consec = 0
    running_pnl = 0.0
    peak_pnl = 0.0
    max_dd = 0.0

    for i in range(1, len(bars)):
        bar = bars[i]
        prev = bars[i - 1]
        ts = int(bar["time"])
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        h, m = dt.hour, dt.minute

        # ─── Check trigger ───
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
            continue  # Don't trade on trigger bar

        if buy_stop == 0:
            continue

        # ─── Calculate TP/SL for potential entries ───
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

        # ─── Check active trade exits ───
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

            if hit_tp2:
                pnl = abs(active_tp2 - active_entry)
                trades_closed.append(("TP2", pnl))
                running_pnl += pnl
                consec_losses = 0
                active_dir = 0
            elif hit_tp1 and not hit_sl:
                pnl = abs(active_tp1 - active_entry)
                trades_closed.append(("TP1", pnl))
                running_pnl += pnl
                consec_losses = 0
                active_dir = 0
            elif hit_sl:
                pnl = -abs(active_sl - active_entry)
                trades_closed.append(("SL", pnl))
                running_pnl += pnl
                consec_losses += 1
                max_consec = max(max_consec, consec_losses)
                active_dir = 0

            if running_pnl > peak_pnl:
                peak_pnl = running_pnl
            dd = peak_pnl - running_pnl
            if dd > max_dd:
                max_dd = dd

            if active_dir != 0:
                continue  # Still in trade, skip entry check

        # ─── Check for new entries ───
        prev_close = prev["close"]
        curr_close = bar["close"]

        # Reversal: close active trade if opposite signal
        new_signal = 0
        if prev_close <= buy_stop and curr_close > buy_stop:
            new_signal = 1
        elif prev_close >= sell_stop and curr_close < sell_stop:
            new_signal = -1

        if new_signal != 0:
            # Close existing if opposite direction
            if active_dir != 0 and active_dir != new_signal:
                pnl_rev = 0.0
                if active_dir == 1:
                    pnl_rev = curr_close - active_entry
                else:
                    pnl_rev = active_entry - curr_close
                trades_closed.append(("Reversal", pnl_rev))
                running_pnl += pnl_rev
                if pnl_rev <= 0:
                    consec_losses += 1
                    max_consec = max(max_consec, consec_losses)
                else:
                    consec_losses = 0
                active_dir = 0

            # Open new trade
            entry, sl, tp1, tp2 = calc_levels(new_signal)
            active_entry = entry
            active_sl = sl
            active_tp1 = tp1
            active_tp2 = tp2
            active_dir = new_signal

    # ─── Build stats ───
    stats = BacktestStats()
    stats.total_trades = len(trades_closed)
    if stats.total_trades == 0:
        return stats

    stats.tp1_wins = sum(1 for r, _ in trades_closed if r == "TP1")
    stats.tp2_wins = sum(1 for r, _ in trades_closed if r == "TP2")
    stats.sl_losses = sum(1 for r, _ in trades_closed if r == "SL")
    stats.reversals = sum(1 for r, _ in trades_closed if r == "Reversal")

    wins = stats.tp1_wins + stats.tp2_wins
    total_closed = stats.total_trades
    stats.win_rate = wins / total_closed * 100 if total_closed > 0 else 0

    gross_profit = sum(p for _, p in trades_closed if p > 0)
    gross_loss = abs(sum(p for _, p in trades_closed if p < 0))
    stats.total_pnl = sum(p for _, p in trades_closed)
    stats.profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999.0
    stats.expectancy = stats.total_pnl / total_closed if total_closed > 0 else 0
    stats.max_consec_losses = max_consec
    stats.max_drawdown = max_dd

    return stats


# ══════════════════════════════════════════════════════════
#  MSS BACKTESTER (Matching the proven backtest engine)
# ══════════════════════════════════════════════════════════

def compute_adr10_series(bars: list[dict]) -> list[float]:
    """Compute ADR10 for each bar by grouping into calendar days."""
    adr = [0.0] * len(bars)
    day_ranges = []
    day_high = -math.inf
    day_low = math.inf
    prev_day = -1

    for i, bar in enumerate(bars):
        dt = datetime.fromtimestamp(int(bar["time"]), tz=timezone.utc)
        day = dt.toordinal()
        if prev_day == -1:
            prev_day = day
            day_high = bar["high"]
            day_low = bar["low"]
        elif day != prev_day:
            dr = day_high - day_low
            if dr > 0:
                day_ranges.append(dr)
            prev_day = day
            day_high = bar["high"]
            day_low = bar["low"]
        else:
            day_high = max(day_high, bar["high"])
            day_low = min(day_low, bar["low"])

        n = min(10, len(day_ranges))
        adr[i] = sum(day_ranges[-n:]) / n if n > 0 else 0.0

    return adr


def backtest_mss(bars: list[dict], cfg: dict) -> BacktestStats:
    """
    Backtest MSS strategy matching the proven engine.

    cfg keys: swing_lb, tp1_pct, tp2_pct, sl_pct, use_pullback, pb_pct, confirm
    """
    lb = cfg.get("swing_lb", 42)
    tp1_pct = cfg.get("tp1_pct", 15.0)
    tp2_pct = cfg.get("tp2_pct", 25.0)
    sl_pct = cfg.get("sl_pct", 25.0)
    use_pb = cfg.get("use_pullback", True)
    pb_pct = cfg.get("pb_pct", 0.382)
    use_close = cfg.get("confirm", "close") == "close"

    N = len(bars)
    min_needed = lb * 2 + 1
    if N < min_needed:
        return BacktestStats()

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

    # Trade tracking
    active_entry = 0.0
    active_sl = 0.0
    active_tp1 = 0.0
    active_tp2 = 0.0
    active_dir = 0

    trades_closed = []
    consec_losses = 0
    max_consec = 0
    running_pnl = 0.0
    peak_pnl = 0.0
    max_dd = 0.0

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

        is_bull_choch = bullish and last_break_dir == -1
        is_bear_choch = bearish and last_break_dir == 1

        if bullish:
            last_break_dir = 1
        if bearish:
            last_break_dir = -1

        # Check active trade exits first
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

            if hit_tp2:
                pnl = abs(active_tp2 - active_entry)
                trades_closed.append(("TP2", pnl))
                running_pnl += pnl
                consec_losses = 0
                active_dir = 0
            elif hit_tp1 and not hit_sl:
                pnl = abs(active_tp1 - active_entry)
                trades_closed.append(("TP1", pnl))
                running_pnl += pnl
                consec_losses = 0
                active_dir = 0
            elif hit_sl:
                pnl = -abs(active_sl - active_entry)
                trades_closed.append(("SL", pnl))
                running_pnl += pnl
                consec_losses += 1
                max_consec = max(max_consec, consec_losses)
                active_dir = 0

            if running_pnl > peak_pnl:
                peak_pnl = running_pnl
            dd = peak_pnl - running_pnl
            if dd > max_dd:
                max_dd = dd

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
            trades_closed.append(("Reversal", rev_pnl))
            running_pnl += rev_pnl
            if rev_pnl <= 0:
                consec_losses += 1
                max_consec = max(max_consec, consec_losses)
            else:
                consec_losses = 0
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

    # Build stats
    stats = BacktestStats()
    stats.total_trades = len(trades_closed)
    if stats.total_trades == 0:
        return stats

    stats.tp1_wins = sum(1 for r, _ in trades_closed if r == "TP1")
    stats.tp2_wins = sum(1 for r, _ in trades_closed if r == "TP2")
    stats.sl_losses = sum(1 for r, _ in trades_closed if r == "SL")
    stats.reversals = sum(1 for r, _ in trades_closed if r == "Reversal")

    wins = stats.tp1_wins + stats.tp2_wins
    stats.win_rate = wins / stats.total_trades * 100 if stats.total_trades > 0 else 0

    gross_profit = sum(p for _, p in trades_closed if p > 0)
    gross_loss = abs(sum(p for _, p in trades_closed if p < 0))
    stats.total_pnl = sum(p for _, p in trades_closed)
    stats.profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999.0
    stats.expectancy = stats.total_pnl / stats.total_trades if stats.total_trades > 0 else 0
    stats.max_consec_losses = max_consec
    stats.max_drawdown = max_dd

    return stats


# ══════════════════════════════════════════════════════════
#  OPTIMIZATION GRID SEARCH
# ══════════════════════════════════════════════════════════

def optimize_gold_bt(bars: list[dict]) -> list[tuple]:
    """Run grid search on Gold BT parameters."""
    param_grid = {
        "box_height":       [6.0, 8.0, 10.0, 14.0],
        "stop_line_buffer": [1.0, 2.0, 4.0],
        "stop_to_tp_gap":   [1.0, 2.0],
        "tp_zone_gap":      [1.0],
        "tp1_height":       [4.0, 8.0, 12.0, 18.0],
        "tp2_height":       [8.0, 14.0, 20.0, 30.0],
        "sl_type":          ["opposite_stop", "gray_box"],
        "trigger_interval_hours": [1, 2, 4],
    }

    keys = list(param_grid.keys())
    combos = list(product(*[param_grid[k] for k in keys]))
    total = len(combos)
    print(f"\n  Gold BT: Testing {total} configurations...")

    results = []
    t0 = time.time()

    for idx, combo in enumerate(combos):
        cfg = dict(zip(keys, combo))
        stats = backtest_gold_bt(bars, cfg)

        if stats.total_trades >= 10:
            results.append((cfg, stats))

        if (idx + 1) % 500 == 0:
            elapsed = time.time() - t0
            print(f"    [{idx+1}/{total}] {elapsed:.0f}s")

    elapsed = time.time() - t0
    print(f"  Done: {len(results)} configs with 10+ trades in {elapsed:.1f}s")

    # Sort by profit factor
    results.sort(key=lambda x: x[1].profit_factor, reverse=True)
    return results


def optimize_mss(bars: list[dict]) -> list[tuple]:
    """Run grid search on MSS parameters."""
    param_grid = {
        "swing_lb": [25, 30, 35, 42, 50],
        "tp1_pct":  [10.0, 15.0, 20.0],
        "tp2_pct":  [20.0, 25.0, 30.0, 40.0],
        "sl_pct":   [15.0, 20.0, 25.0, 30.0],
        "pb_pct":   [0.382, 0.5],
    }

    keys = list(param_grid.keys())
    combos = list(product(*[param_grid[k] for k in keys]))
    total = len(combos)
    print(f"\n  MSS: Testing {total} configurations...")

    results = []
    t0 = time.time()

    for idx, combo in enumerate(combos):
        cfg = dict(zip(keys, combo))
        cfg["use_pullback"] = True
        cfg["confirm"] = "close"
        stats = backtest_mss(bars, cfg)

        if stats.total_trades >= 10:
            results.append((cfg, stats))

        if (idx + 1) % 100 == 0:
            elapsed = time.time() - t0
            print(f"    [{idx+1}/{total}] {elapsed:.0f}s")

    elapsed = time.time() - t0
    print(f"  Done: {len(results)} configs with 10+ trades in {elapsed:.1f}s")

    results.sort(key=lambda x: x[1].profit_factor, reverse=True)
    return results


# ══════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════

def print_results(title: str, results: list[tuple], top_n: int = 25):
    """Print top N results in a table."""
    print(f"\n{'='*100}")
    print(f"  {title} — TOP {top_n}")
    print(f"{'='*100}")
    print(f"  {'#':<4} {'Config':<60} {'Trd':>5} {'WR%':>7} {'PF':>7} {'PnL':>10} {'Exp':>8} {'TP1':>4} {'TP2':>4} {'SL':>4} {'Rev':>4} {'MaxCL':>5}")
    print(f"  {'-'*4} {'-'*60} {'-'*5} {'-'*7} {'-'*7} {'-'*10} {'-'*8} {'-'*4} {'-'*4} {'-'*4} {'-'*4} {'-'*5}")

    for i, (cfg, s) in enumerate(results[:top_n]):
        # Build config string
        if "box_height" in cfg:
            # Gold BT config
            cfg_str = f"Box{cfg['box_height']}_Buf{cfg['stop_line_buffer']}_TP{cfg['tp1_height']}/{cfg['tp2_height']}_SL:{cfg['sl_type'][:3]}_{cfg['trigger_interval_hours']}h"
        else:
            # MSS config
            cfg_str = f"LB{cfg['swing_lb']}_TP{cfg['tp1_pct']}/{cfg['tp2_pct']}_SL{cfg['sl_pct']}_PB{cfg.get('pb_pct', 0.382)}"

        star = " **" if s.profit_factor >= 3.0 else ""
        print(f"  {i+1:<4} {cfg_str:<60} {s.total_trades:>5} {s.win_rate:>6.1f}% {s.profit_factor:>6.2f} {s.total_pnl:>10.1f} {s.expectancy:>7.2f} {s.tp1_wins:>4} {s.tp2_wins:>4} {s.sl_losses:>4} {s.reversals:>4} {s.max_consec_losses:>5}{star}")

    if results:
        best_cfg, best_s = results[0]
        print(f"\n  BEST: {best_cfg}")
        print(f"    Trades: {best_s.total_trades} | Win Rate: {best_s.win_rate:.1f}% | PF: {best_s.profit_factor:.3f}")
        print(f"    Total PnL: {best_s.total_pnl:.1f} | Expectancy: {best_s.expectancy:.2f}")
        print(f"    TP1: {best_s.tp1_wins} | TP2: {best_s.tp2_wins} | SL: {best_s.sl_losses} | Rev: {best_s.reversals}")
        print(f"    Max Consec Loss: {best_s.max_consec_losses} | Max DD: {best_s.max_drawdown:.1f}")


def main():
    base = Path(r"D:\Doc\DATA\Backtest Data")

    # Load data
    print("=" * 100)
    print("  STRATEGY OPTIMIZER — XAUUSD")
    print("=" * 100)

    # For Gold BT: use M1 data for most precise backtesting
    m1_path = base / "XAUUSD_M1_20250801_20260201_MT5.csv"
    # For MSS: use M10 data (matching the proven backtest)
    m10_path = base / "XAUUSD_M10_20250101_20261202_MT5.csv"

    print(f"\n  Loading M1 data from: {m1_path}")
    m1_bars = load_csv(str(m1_path))
    print(f"  Loaded {len(m1_bars)} M1 candles")

    print(f"\n  Loading M10 data from: {m10_path}")
    m10_bars = load_csv(str(m10_path))
    print(f"  Loaded {len(m10_bars)} M10 candles")

    # ─── Gold BT Optimization ───
    gold_results = optimize_gold_bt(m1_bars)
    print_results("GOLD BREAKOUT TRADER — XAUUSD M1", gold_results)

    # ─── MSS Optimization ───
    mss_results = optimize_mss(m10_bars)
    print_results("MARKET STRUCTURE SIGNALS — XAUUSD M10", mss_results)

    # ─── Verify known-best MSS config ───
    print(f"\n{'='*100}")
    print("  VERIFYING KNOWN-BEST MSS CONFIG (from mss_results.txt)")
    print(f"{'='*100}")
    best_known = {
        "swing_lb": 30, "tp1_pct": 15.0, "tp2_pct": 25.0,
        "sl_pct": 25.0, "use_pullback": True, "pb_pct": 0.382, "confirm": "close"
    }
    best_stats = backtest_mss(m10_bars, best_known)
    print(f"  LB30_TP15/25_SL25_PB0.382:")
    print(f"    Trades: {best_stats.total_trades} | WR: {best_stats.win_rate:.1f}% | PF: {best_stats.profit_factor:.2f}")
    print(f"    PnL: {best_stats.total_pnl:.1f} | Exp: {best_stats.expectancy:.2f}")
    print(f"    TP1: {best_stats.tp1_wins} | TP2: {best_stats.tp2_wins} | SL: {best_stats.sl_losses} | Rev: {best_stats.reversals}")

    universal = {
        "swing_lb": 42, "tp1_pct": 15.0, "tp2_pct": 25.0,
        "sl_pct": 25.0, "use_pullback": True, "pb_pct": 0.382, "confirm": "close"
    }
    uni_stats = backtest_mss(m10_bars, universal)
    print(f"\n  LB42_TP15/25_SL25_PB0.382 (universal best):")
    print(f"    Trades: {uni_stats.total_trades} | WR: {uni_stats.win_rate:.1f}% | PF: {uni_stats.profit_factor:.2f}")
    print(f"    PnL: {uni_stats.total_pnl:.1f} | Exp: {uni_stats.expectancy:.2f}")
    print(f"    TP1: {uni_stats.tp1_wins} | TP2: {uni_stats.tp2_wins} | SL: {uni_stats.sl_losses} | Rev: {uni_stats.reversals}")

    print(f"\n{'='*100}")
    print("  OPTIMIZATION COMPLETE")
    print(f"{'='*100}")


if __name__ == "__main__":
    main()
