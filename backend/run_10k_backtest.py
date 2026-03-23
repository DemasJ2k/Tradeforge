"""
$10K Account Backtest — XAUUSD H1
==================================
Tests top strategies with realistic cTrader costs on $10k account.
Lot size: 0.1 (moderate — ~$10/point on Gold)

Cost assumptions (cTrader Raw Spread, IC Markets):
  XAUUSD spread: $0.20 (pessimistic avg)
  Commission: $7/standard lot RT → $0.70 for 0.1 lot
  Point value: $100/lot → $10 for 0.1 lot per $1 move
"""

import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.strategy.file_runner import run_file_strategy

# ── Configuration ─────────────────────────────────────────────────
UPLOAD_DIR = Path(__file__).parent / "data" / "uploads"
STRATEGY_DIR = Path(__file__).parent / "data" / "strategies"

INITIAL_BALANCE = 10_000.0
LOT_SIZE = 0.1          # 0.1 lot = $10 per $1 gold move
SPREAD_POINTS = 0.002   # $0.20 actual spread / pv100
COMMISSION = 7.0        # $7 per standard lot RT
POINT_VALUE = 100.0     # 1 lot = 100oz, $1 move = $100

INSTRUMENT = "XAUUSD"
TIMEFRAME = "H1"
DATA_FILE = "1772956576_XAUUSD_H1_121610bars.csv"

# Top strategies for XAUUSD H1 (mix of swing, intraday, trend-following)
STRATEGIES = [
    "s03_smart_money_concepts",
    "s06_supertrend_follower",
    "s07_turtle_trading",
    "s08_larry_williams_breakout",
    "s09_connors_rsi2_mean_reversion",
    "s10_ttm_squeeze",
    "s11_ichimoku_cloud",
    "s12_adx_parabolic_sar",
    "s14_rsi_divergence",
    "s15_bb_squeeze_breakout",
    "s17_ema_ribbon",
    "s18_keltner_breakout",
    "s21_hull_ma_crossover",
    "s22_nill_momentum_swing",
    "s24_macd_histogram_div",
    "s26_market_structure_signals",
    "s33_xauusd_london_breakout",
    "s34_xauusd_ny_momentum",
]

# ── CSV Parser ────────────────────────────────────────────────────

DATETIME_FORMATS = [
    "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
    "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
]


def parse_time(val: str) -> float:
    val = val.strip()
    try:
        return float(val)
    except ValueError:
        pass
    for fmt in DATETIME_FORMATS:
        try:
            dt = datetime.strptime(val, fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    return 0.0


def load_csv(filepath: Path) -> list[dict]:
    bars = []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        delim = ","
        if sample.count("\t") > sample.count(","):
            delim = "\t"
        elif sample.count(";") > sample.count(","):
            delim = ";"

        reader = csv.DictReader(f, delimiter=delim)
        if not reader.fieldnames:
            return bars

        headers = {h.strip().lower(): h.strip() for h in reader.fieldnames}
        col_time = next((headers[k] for k in headers if k in {"time", "date", "datetime", "timestamp", "<time>"}), None)
        col_open = next((headers[k] for k in headers if k in {"open", "o", "<open>"}), None)
        col_high = next((headers[k] for k in headers if k in {"high", "h", "<high>"}), None)
        col_low = next((headers[k] for k in headers if k in {"low", "l", "<low>"}), None)
        col_close = next((headers[k] for k in headers if k in {"close", "c", "<close>"}), None)
        col_vol = next((headers[k] for k in headers if k in {"volume", "vol", "v", "tick_volume", "<vol>", "<tickvol>"}), None)

        if not all([col_time, col_open, col_high, col_low, col_close]):
            raise ValueError(f"CSV missing required columns: {filepath}")

        for row in reader:
            try:
                bars.append({
                    "time": parse_time(row[col_time]),
                    "open": float(row[col_open]),
                    "high": float(row[col_high]),
                    "low": float(row[col_low]),
                    "close": float(row[col_close]),
                    "volume": float(row[col_vol]) if col_vol and row.get(col_vol) else 0.0,
                })
            except (ValueError, KeyError):
                continue
    return bars


# ── Run Backtest ──────────────────────────────────────────────────

def run_single(strategy_name: str, bars: list[dict]) -> dict:
    file_path = str(STRATEGY_DIR / f"{strategy_name}.py")
    if not os.path.exists(file_path):
        return {"strategy": strategy_name, "error": f"File not found: {file_path}"}

    try:
        t0 = time.time()
        result = run_file_strategy(
            strategy_type="python",
            file_path=file_path,
            settings_values={"lot_size": LOT_SIZE, "size": LOT_SIZE, "position_size": LOT_SIZE},
            bars_raw=bars,
            initial_balance=INITIAL_BALANCE,
            spread_points=SPREAD_POINTS,
            commission_per_lot=COMMISSION,
            point_value=POINT_VALUE,
        )
        elapsed = time.time() - t0

        # Return on account
        roi_pct = (result.net_profit / INITIAL_BALANCE) * 100

        # Calmar ratio
        calmar = 0.0
        if result.max_drawdown_pct > 0:
            calmar = roi_pct / result.max_drawdown_pct

        return {
            "strategy": strategy_name,
            "instrument": INSTRUMENT,
            "timeframe": TIMEFRAME,
            "bars": result.total_bars,
            "trades": result.total_trades,
            "winners": result.winning_trades,
            "losers": result.losing_trades,
            "win_rate": round(result.win_rate, 2),
            "net_profit": round(result.net_profit, 2),
            "roi_pct": round(roi_pct, 2),
            "gross_profit": round(result.gross_profit, 2),
            "gross_loss": round(result.gross_loss, 2),
            "profit_factor": round(result.profit_factor, 2),
            "max_dd_pct": round(result.max_drawdown_pct, 2),
            "max_dd_usd": round(result.max_drawdown, 2),
            "sharpe": round(result.sharpe_ratio, 2),
            "calmar": round(calmar, 2),
            "expectancy": round(result.expectancy, 2),
            "avg_trade": round(result.avg_trade, 2),
            "avg_win": round(result.avg_win, 2),
            "avg_loss": round(result.avg_loss, 2),
            "largest_win": round(result.largest_win, 2),
            "largest_loss": round(result.largest_loss, 2),
            "elapsed": round(elapsed, 1),
            "error": None,
        }
    except Exception as e:
        return {"strategy": strategy_name, "error": str(e)[:300]}


def grade(r: dict) -> str:
    score = 0
    pf = r.get("profit_factor", 0)
    wr = r.get("win_rate", 0)
    dd = r.get("max_dd_pct", 100)
    sharpe = r.get("sharpe", 0)
    trades = r.get("trades", 0)
    net = r.get("net_profit", 0)

    if pf >= 2.0: score += 3
    elif pf >= 1.5: score += 2
    elif pf >= 1.1: score += 1

    if wr >= 55: score += 2
    elif wr >= 45: score += 1

    if dd <= 10: score += 3
    elif dd <= 20: score += 2
    elif dd <= 30: score += 1

    if sharpe >= 2.0: score += 3
    elif sharpe >= 1.0: score += 2
    elif sharpe >= 0.5: score += 1

    if trades >= 100: score += 2
    elif trades >= 30: score += 1

    if net > 0: score += 1

    if score >= 12: return "A+"
    if score >= 10: return " A"
    if score >= 8:  return " B"
    if score >= 6:  return " C"
    if score >= 4:  return " D"
    return " F"


def main():
    print()
    print("=" * 110)
    print("  TRADEFORGE — $10K XAUUSD H1 BACKTEST")
    print("  Realistic cTrader Costs | 0.1 Lot ($10/point)")
    print("=" * 110)
    print(f"  Account: ${INITIAL_BALANCE:,.0f}")
    print(f"  Lot size: {LOT_SIZE} (0.1 std lot = 10 oz Gold)")
    print(f"  Spread: $0.20 | Commission: $0.70/RT (0.1 lot)")
    print(f"  Risk per $1 move: ~${LOT_SIZE * POINT_VALUE:.0f}")
    print(f"  Data: {DATA_FILE}")
    print("=" * 110)

    # Load data
    fp = UPLOAD_DIR / DATA_FILE
    if not fp.exists():
        print(f"ERROR: Data file not found: {fp}")
        return
    print(f"\nLoading data...", end="", flush=True)
    bars = load_csv(fp)
    print(f" {len(bars):,} bars loaded")

    # Date range
    if bars:
        first_ts = bars[0]["time"]
        last_ts = bars[-1]["time"]
        try:
            first_dt = datetime.fromtimestamp(first_ts, tz=timezone.utc).strftime("%Y-%m-%d")
            last_dt = datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%d")
            print(f"Date range: {first_dt} → {last_dt}")
        except Exception:
            pass

    # Run all strategies
    results = []
    total = len(STRATEGIES)

    for idx, name in enumerate(STRATEGIES, 1):
        print(f"\n[{idx:2d}/{total}] {name} ...", end="", flush=True)
        res = run_single(name, bars)
        results.append(res)

        if res.get("error"):
            print(f" ERROR: {res['error'][:80]}")
        else:
            g = grade(res)
            profit_str = f"${res['net_profit']:>+10,.2f}"
            print(f" [{g}] {res['trades']:>4} trades | WR:{res['win_rate']:>5.1f}% | "
                  f"PF:{res['profit_factor']:>5.2f} | P&L:{profit_str} ({res['roi_pct']:>+.1f}%) | "
                  f"DD:{res['max_dd_pct']:>5.1f}% | Sharpe:{res['sharpe']:>5.2f} | {res['elapsed']:.0f}s")

    # ── Summary Table ──────────────────────────────────────────────
    valid = [r for r in results if not r.get("error")]
    errors = [r for r in results if r.get("error")]
    valid.sort(key=lambda x: x.get("net_profit", 0), reverse=True)

    print("\n\n" + "=" * 140)
    print("  RESULTS RANKED BY NET PROFIT")
    print("=" * 140)
    print(f"{'#':>3} {'Gr':>3} {'Strategy':<38} {'Trades':>7} {'WinRate':>8} {'PF':>6} "
          f"{'Net P&L':>12} {'ROI%':>7} {'MaxDD%':>7} {'Sharpe':>7} {'AvgWin':>9} {'AvgLoss':>9} {'Expect':>9}")
    print("-" * 140)

    profitable = 0
    for i, r in enumerate(valid, 1):
        g = grade(r)
        if r["net_profit"] > 0:
            profitable += 1
        print(f"{i:>3} [{g}] {r['strategy']:<38} {r['trades']:>7} {r['win_rate']:>7.1f}% "
              f"{r['profit_factor']:>6.2f} ${r['net_profit']:>+10,.2f} {r['roi_pct']:>+6.1f}% "
              f"{r['max_dd_pct']:>6.1f}% {r['sharpe']:>7.2f} "
              f"${r['avg_win']:>8.2f} ${r['avg_loss']:>8.2f} ${r['expectancy']:>8.2f}")

    if errors:
        print(f"\n  ERRORS ({len(errors)}):")
        for r in errors:
            print(f"    {r['strategy']}: {r['error'][:100]}")

    # ── Summary Stats ──────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("  SUMMARY")
    print("=" * 80)
    print(f"  Strategies tested: {len(STRATEGIES)}")
    print(f"  Successful runs:   {len(valid)}")
    print(f"  Profitable:        {profitable}/{len(valid)} ({profitable/max(len(valid),1)*100:.0f}%)")
    if valid:
        best = valid[0]
        worst = valid[-1]
        print(f"\n  Best:   {best['strategy']}")
        print(f"          ${best['net_profit']:+,.2f} ({best['roi_pct']:+.1f}%) | "
              f"{best['trades']} trades | WR: {best['win_rate']:.1f}% | PF: {best['profit_factor']:.2f} | "
              f"Sharpe: {best['sharpe']:.2f}")
        print(f"\n  Worst:  {worst['strategy']}")
        print(f"          ${worst['net_profit']:+,.2f} ({worst['roi_pct']:+.1f}%) | "
              f"{worst['trades']} trades | WR: {worst['win_rate']:.1f}% | PF: {worst['profit_factor']:.2f}")

    # Top 3 by Sharpe
    by_sharpe = sorted(valid, key=lambda x: x.get("sharpe", 0), reverse=True)[:3]
    if by_sharpe:
        print(f"\n  Top 3 by Sharpe Ratio:")
        for r in by_sharpe:
            print(f"    {r['strategy']}: Sharpe {r['sharpe']:.2f} | PF {r['profit_factor']:.2f} | "
                  f"${r['net_profit']:+,.2f}")

    # ── Verdict ────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    a_grade = [r for r in valid if grade(r).strip() in ("A+", "A")]
    b_grade = [r for r in valid if grade(r).strip() == "B"]

    if a_grade:
        print("  VERDICT: Found A-grade strategies worth pursuing!")
        for r in a_grade:
            print(f"    ★ {r['strategy']}: ${r['net_profit']:+,.2f} | Sharpe: {r['sharpe']:.2f}")
    elif b_grade:
        print("  VERDICT: Some B-grade strategies with potential. ML training could improve them.")
    else:
        print("  VERDICT: No strong edge found with default parameters.")
        print("  RECOMMENDATION: Train ML models to find optimal indicator combinations per symbol.")
    print("=" * 80)

    # ── Save Results ──────────────────────────────────────────────
    output_path = Path(__file__).parent.parent / "backtest_results_10k.json"
    output = {
        "timestamp": datetime.now().isoformat(),
        "config": {
            "initial_balance": INITIAL_BALANCE,
            "lot_size": LOT_SIZE,
            "spread_points": SPREAD_POINTS,
            "commission_per_lot": COMMISSION,
            "point_value": POINT_VALUE,
            "instrument": INSTRUMENT,
            "timeframe": TIMEFRAME,
            "data_file": DATA_FILE,
        },
        "results": valid,
        "errors": errors,
    }
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
