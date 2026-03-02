"""
Batch Backtest Runner
=====================
Runs all 25 Python strategies against available historical data
and produces a comprehensive results report.
"""

import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add backend to path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.strategy.file_runner import run_file_strategy

# ── Configuration ─────────────────────────────────────────────────

UPLOAD_DIR = Path(__file__).parent / "data" / "uploads"
STRATEGY_DIR = Path(__file__).parent / "data" / "strategies"
INITIAL_BALANCE = 10_000.0
SPREAD_POINTS = 0.0       # zero-cost for baseline; realistic spreads in phase 2
COMMISSION = 0.0
POINT_VALUE = 1.0

# ── Data Files ────────────────────────────────────────────────────

DATA_FILES = {
    # (instrument, timeframe): filename
    ("XAUUSD", "M1"):  "1772419683_XAUUSD_M1_50000bars.csv",
    ("XAUUSD", "M5"):  "1772419706_XAUUSD_M5_50000bars.csv",
    ("XAUUSD", "M15"): "1772419728_XAUUSD_M15_50000bars.csv",
    ("XAUUSD", "H1"):  "1772419808_XAUUSD_H1_50000bars.csv",
    ("US30",   "M1"):  "1772419838_US30_M1_50000bars.csv",
    ("US30",   "M5"):  "1772419846_US30_M5_50000bars.csv",
    ("US30",   "M15"): "1772419855_US30_M15_50000bars.csv",
    ("US30",   "H1"):  "1772419862_US30_H1_50000bars.csv",
    ("US100",  "M1"):  "1772419948_US100_M1_50000bars.csv",
    ("US100",  "M5"):  "1772419959_US100_M5_50000bars.csv",
    ("US100",  "M15"): "1772419976_US100_M15_50000bars.csv",
    ("US100",  "H1"):  "1772420010_US100_H1_50000bars.csv",
    ("EURUSD", "M1"):  "1772420042_EURUSD_M1_50000bars.csv",
    ("EURUSD", "M5"):  "1772420048_EURUSD_M5_50000bars.csv",
    ("EURUSD", "M15"): "1772420055_EURUSD_M15_50000bars.csv",
    ("EURUSD", "H1"):  "1772420063_EURUSD_H1_5000bars.csv",
}

# ── Strategy → Recommended Timeframes & Instruments ───────────────

STRATEGIES = {
    "s01_valentini_auction_market":   {"tf": ["H1"],        "type": "swing"},
    "s02_ict_silver_bullet":          {"tf": ["M5"],        "type": "scalp"},
    "s03_smart_money_concepts":       {"tf": ["H1"],        "type": "intraday"},
    "s04_triple_ema_vwap_scalper":    {"tf": ["M5"],        "type": "scalp"},
    "s05_opening_range_breakout":     {"tf": ["M15"],       "type": "scalp"},
    "s06_supertrend_follower":        {"tf": ["H1"],        "type": "swing"},
    "s07_turtle_trading":             {"tf": ["H1"],        "type": "swing"},
    "s08_larry_williams_breakout":    {"tf": ["H1"],        "type": "swing"},
    "s09_connors_rsi2_mean_reversion":{"tf": ["H1"],        "type": "swing"},
    "s10_ttm_squeeze":                {"tf": ["H1"],        "type": "intraday"},
    "s11_ichimoku_cloud":             {"tf": ["H1"],        "type": "swing"},
    "s12_adx_parabolic_sar":          {"tf": ["H1"],        "type": "swing"},
    "s13_woodies_cci":                {"tf": ["M15"],       "type": "intraday"},
    "s14_rsi_divergence":             {"tf": ["H1"],        "type": "swing"},
    "s15_bb_squeeze_breakout":        {"tf": ["H1"],        "type": "intraday"},
    "s16_vwap_mean_reversion":        {"tf": ["M5"],        "type": "scalp"},
    "s17_ema_ribbon":                 {"tf": ["H1"],        "type": "intraday"},
    "s18_keltner_breakout":           {"tf": ["H1"],        "type": "intraday"},
    "s19_stoch_rsi_momentum":         {"tf": ["M15"],       "type": "intraday"},
    "s20_unger_rotation":             {"tf": ["H1"],        "type": "swing"},
    "s21_hull_ma_crossover":          {"tf": ["H1"],        "type": "intraday"},
    "s22_nill_momentum_swing":        {"tf": ["H1"],        "type": "swing"},
    "s23_ao_saucer":                  {"tf": ["H1"],        "type": "intraday"},
    "s24_macd_histogram_div":         {"tf": ["H1"],        "type": "swing"},
    "s25_london_breakout":            {"tf": ["M15"],       "type": "scalp"},
    "s26_market_structure_signals":   {"tf": ["H1"],        "type": "intraday"},
}

# Primary test instrument per strategy type
PRIMARY_INSTRUMENT = {
    "scalp":    "XAUUSD",
    "intraday": "XAUUSD",
    "swing":    "XAUUSD",
}

# Additional instruments to test top performers
ALL_INSTRUMENTS = ["XAUUSD", "US30", "US100", "EURUSD"]

# ── CSV Parser ────────────────────────────────────────────────────

DATETIME_FORMATS = [
    "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
    "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
]


def parse_time(val: str) -> float:
    """Parse datetime string to unix timestamp."""
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
    """Load CSV file into list of bar dicts."""
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
        time_aliases = {"time", "date", "datetime", "timestamp", "<time>"}
        open_aliases = {"open", "o", "<open>"}
        high_aliases = {"high", "h", "<high>"}
        low_aliases = {"low", "l", "<low>"}
        close_aliases = {"close", "c", "<close>"}
        vol_aliases = {"volume", "vol", "v", "tick_volume", "<vol>", "<tickvol>"}

        col_time = next((headers[k] for k in headers if k in time_aliases), None)
        col_open = next((headers[k] for k in headers if k in open_aliases), None)
        col_high = next((headers[k] for k in headers if k in high_aliases), None)
        col_low = next((headers[k] for k in headers if k in low_aliases), None)
        col_close = next((headers[k] for k in headers if k in close_aliases), None)
        col_vol = next((headers[k] for k in headers if k in vol_aliases), None)

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


# ── Data Cache ────────────────────────────────────────────────────

_data_cache: dict[str, list[dict]] = {}


def get_data(instrument: str, tf: str) -> list[dict]:
    """Load data with caching."""
    key = f"{instrument}_{tf}"
    if key not in _data_cache:
        fname = DATA_FILES.get((instrument, tf))
        if not fname:
            return []
        fp = UPLOAD_DIR / fname
        if not fp.exists():
            print(f"  [WARN] Data file not found: {fp}")
            return []
        _data_cache[key] = load_csv(fp)
    return _data_cache[key]


# ── Run Single Backtest ──────────────────────────────────────────

def run_single(strategy_name: str, instrument: str, tf: str) -> dict:
    """Run a single strategy on one dataset. Returns summary dict."""
    file_path = str(STRATEGY_DIR / f"{strategy_name}.py")
    if not os.path.exists(file_path):
        return {"error": f"Strategy file not found: {file_path}"}

    bars = get_data(instrument, tf)
    if not bars:
        return {"error": f"No data for {instrument} {tf}"}

    try:
        t0 = time.time()
        result = run_file_strategy(
            strategy_type="python",
            file_path=file_path,
            settings_values={},   # Use strategy DEFAULTS
            bars_raw=bars,
            initial_balance=INITIAL_BALANCE,
            spread_points=SPREAD_POINTS,
            commission_per_lot=COMMISSION,
            point_value=POINT_VALUE,
        )
        elapsed = time.time() - t0

        return {
            "strategy":        strategy_name,
            "instrument":      instrument,
            "timeframe":       tf,
            "bars":            result.total_bars,
            "trades":          result.total_trades,
            "win_rate":        round(result.win_rate, 2),
            "net_profit":      round(result.net_profit, 2),
            "profit_factor":   round(result.profit_factor, 2),
            "max_dd_pct":      round(result.max_drawdown_pct, 2),
            "sharpe":          round(result.sharpe_ratio, 2),
            "expectancy":      round(result.expectancy, 2),
            "avg_trade":       round(result.avg_trade, 2),
            "largest_win":     round(result.largest_win, 2),
            "largest_loss":    round(result.largest_loss, 2),
            "elapsed":         round(elapsed, 1),
            "error":           None,
        }
    except Exception as e:
        return {
            "strategy":   strategy_name,
            "instrument": instrument,
            "timeframe":  tf,
            "error":      str(e)[:200],
        }


# ── Main ─────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print("  TRADEFORGE BATCH BACKTEST RUNNER")
    print(f"  Balance: ${INITIAL_BALANCE:,.0f}  |  Spread: {SPREAD_POINTS}  |  Commission: {COMMISSION}")
    print("=" * 80)

    # Phase 1: Test each strategy on primary instrument + recommended TF
    results = []
    total = len(STRATEGIES)

    for idx, (name, cfg) in enumerate(STRATEGIES.items(), 1):
        instrument = PRIMARY_INSTRUMENT[cfg["type"]]
        tf = cfg["tf"][0]
        print(f"\n[{idx:2d}/{total}] {name}  →  {instrument} {tf} ...", end="", flush=True)
        res = run_single(name, instrument, tf)
        results.append(res)

        if res.get("error"):
            print(f"  ERROR: {res['error'][:80]}")
        else:
            trades = res["trades"]
            wr = res["win_rate"]
            pf = res["profit_factor"]
            net = res["net_profit"]
            dd = res["max_dd_pct"]
            sharpe = res["sharpe"]
            print(f"  {trades} trades | WR: {wr}% | PF: {pf} | Net: ${net:,.0f} | DD: {dd}% | Sharpe: {sharpe} | {res['elapsed']}s")

    # Phase 2: Test top performers across all instruments
    print("\n" + "=" * 80)
    print("  PHASE 2: TOP PERFORMERS ACROSS ALL INSTRUMENTS")
    print("=" * 80)

    # Filter strategies that had profitable results
    top = [r for r in results if not r.get("error") and r.get("net_profit", 0) > 0 and r.get("trades", 0) >= 5]
    top.sort(key=lambda x: x.get("sharpe", 0), reverse=True)
    top = top[:10]  # Top 10 performers

    cross_results = []
    for r in top:
        name = r["strategy"]
        cfg = STRATEGIES[name]
        tf = cfg["tf"][0]
        for inst in ALL_INSTRUMENTS:
            if inst == r["instrument"]:
                cross_results.append(r)  # Already tested
                continue
            key = (inst, tf)
            if key not in DATA_FILES:
                continue
            print(f"  {name}  →  {inst} {tf} ...", end="", flush=True)
            cr = run_single(name, inst, tf)
            cross_results.append(cr)
            if cr.get("error"):
                print(f"  ERROR: {cr['error'][:60]}")
            else:
                print(f"  {cr['trades']}t WR:{cr['win_rate']}% PF:{cr['profit_factor']} Net:${cr['net_profit']:,.0f}")

    # ── Print Summary Report ──────────────────────────────────────

    print("\n\n" + "=" * 120)
    print("  BACKTEST RESULTS SUMMARY")
    print("=" * 120)
    print(f"{'Strategy':<38} {'Inst':<7} {'TF':<4} {'Trades':>7} {'WinRate':>8} {'PF':>6} {'NetProfit':>11} {'MaxDD%':>7} {'Sharpe':>7} {'Expect':>8} {'AvgTr':>8}")
    print("-" * 120)

    # Sort by net profit
    valid = [r for r in results if not r.get("error")]
    valid.sort(key=lambda x: x.get("net_profit", 0), reverse=True)

    for r in valid:
        print(f"{r['strategy']:<38} {r['instrument']:<7} {r['timeframe']:<4} "
              f"{r['trades']:>7} {r['win_rate']:>7.1f}% {r['profit_factor']:>6.2f} "
              f"${r['net_profit']:>10,.2f} {r['max_dd_pct']:>6.1f}% {r['sharpe']:>7.2f} "
              f"${r['expectancy']:>7.2f} ${r['avg_trade']:>7.2f}")

    # Print errors
    errors = [r for r in results if r.get("error")]
    if errors:
        print(f"\n{'ERRORS':=^120}")
        for r in errors:
            print(f"  {r['strategy']}: {r['error']}")

    # Print cross-instrument results for top performers
    if cross_results:
        print(f"\n\n{'=' * 120}")
        print("  CROSS-INSTRUMENT RESULTS (Top Performers)")
        print("=" * 120)
        print(f"{'Strategy':<38} {'Inst':<7} {'TF':<4} {'Trades':>7} {'WinRate':>8} {'PF':>6} {'NetProfit':>11} {'MaxDD%':>7} {'Sharpe':>7}")
        print("-" * 120)

        cross_valid = [r for r in cross_results if not r.get("error")]
        cross_valid.sort(key=lambda x: (x["strategy"], x["instrument"]))
        for r in cross_valid:
            print(f"{r['strategy']:<38} {r['instrument']:<7} {r['timeframe']:<4} "
                  f"{r['trades']:>7} {r['win_rate']:>7.1f}% {r['profit_factor']:>6.2f} "
                  f"${r['net_profit']:>10,.2f} {r['max_dd_pct']:>6.1f}% {r['sharpe']:>7.2f}")

    # Save full results to JSON
    output_path = Path(__file__).parent.parent / "backtest_results_phase1.json"
    all_results = {
        "timestamp": datetime.now().isoformat(),
        "config": {
            "initial_balance": INITIAL_BALANCE,
            "spread_points": SPREAD_POINTS,
            "commission": COMMISSION,
            "point_value": POINT_VALUE,
        },
        "primary_results": results,
        "cross_instrument_results": cross_results,
    }
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n\nResults saved to: {output_path}")

    # ── Grade strategies ──────────────────────────────────────────
    print("\n\n" + "=" * 80)
    print("  STRATEGY GRADES")
    print("=" * 80)

    for r in valid:
        grade = _grade_strategy(r)
        name = r["strategy"]
        print(f"  {grade}  {name}  (PF:{r['profit_factor']:.2f} WR:{r['win_rate']:.0f}% DD:{r['max_dd_pct']:.1f}% Sharpe:{r['sharpe']:.2f})")

    if errors:
        for r in errors:
            print(f"  [FAIL] {r['strategy']}  ({r['error'][:50]})")


def _grade_strategy(r: dict) -> str:
    """Grade a strategy A/B/C/D/F based on key metrics."""
    score = 0
    pf = r.get("profit_factor", 0)
    wr = r.get("win_rate", 0)
    dd = r.get("max_dd_pct", 100)
    sharpe = r.get("sharpe", 0)
    trades = r.get("trades", 0)
    net = r.get("net_profit", 0)

    # Profit factor
    if pf >= 2.0: score += 3
    elif pf >= 1.5: score += 2
    elif pf >= 1.1: score += 1

    # Win rate
    if wr >= 55: score += 2
    elif wr >= 45: score += 1

    # Drawdown
    if dd <= 10: score += 3
    elif dd <= 20: score += 2
    elif dd <= 30: score += 1

    # Sharpe
    if sharpe >= 2.0: score += 3
    elif sharpe >= 1.0: score += 2
    elif sharpe >= 0.5: score += 1

    # Trade count (enough for significance)
    if trades >= 100: score += 2
    elif trades >= 30: score += 1

    # Net profit
    if net > 0: score += 1

    if score >= 12: return "[A+]"
    if score >= 10: return "[ A]"
    if score >= 8:  return "[ B]"
    if score >= 6:  return "[ C]"
    if score >= 4:  return "[ D]"
    return "[ F]"


if __name__ == "__main__":
    main()
