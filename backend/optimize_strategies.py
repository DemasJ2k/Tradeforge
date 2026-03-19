"""
Strategy Parameter Optimizer
=============================
Grid search over key parameters for each strategy to find the best
Sharpe / PF / Net combination with realistic costs.
"""

import csv
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from itertools import product

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.services.strategy.file_runner import run_file_strategy

UPLOAD_DIR = Path(__file__).parent / "data" / "uploads"
STRATEGY_DIR = Path(__file__).parent / "data" / "strategies"
INITIAL_BALANCE = 3000.0

# ── CSV parser (reuse) ─────────────────────────────────────────────
DATETIME_FORMATS = [
    "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
]

def parse_time(val):
    val = val.strip()
    try: return float(val)
    except ValueError: pass
    for fmt in DATETIME_FORMATS:
        try: return datetime.strptime(val, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError: continue
    return 0.0

def load_csv(filepath):
    bars = []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        sample = f.read(4096); f.seek(0)
        delim = "\t" if sample.count("\t") > sample.count(",") else (";" if sample.count(";") > sample.count(",") else ",")
        reader = csv.DictReader(f, delimiter=delim)
        if not reader.fieldnames: return bars
        headers = {h.strip().lower(): h.strip() for h in reader.fieldnames}
        ct = next((headers[k] for k in headers if k in {"time","date","datetime","timestamp","<time>"}), None)
        co = next((headers[k] for k in headers if k in {"open","o","<open>"}), None)
        ch = next((headers[k] for k in headers if k in {"high","h","<high>"}), None)
        cl = next((headers[k] for k in headers if k in {"low","l","<low>"}), None)
        cc = next((headers[k] for k in headers if k in {"close","c","<close>"}), None)
        cv = next((headers[k] for k in headers if k in {"volume","vol","v","tick_volume","<vol>","<tickvol>"}), None)
        for row in reader:
            try:
                bars.append({"time": parse_time(row[ct]), "open": float(row[co]),
                    "high": float(row[ch]), "low": float(row[cl]),
                    "close": float(row[cc]),
                    "volume": float(row[cv]) if cv and row.get(cv) else 0.0})
            except: continue
    return bars

_cache = {}
def get_data(inst, tf):
    key = f"{inst}_{tf}"
    if key not in _cache:
        fmap = {
            ("XAUUSD","M5"): "1772956552_XAUUSD_M5_180000bars.csv",
            ("US100","M5"):  "1772956324_US100_M5_180000bars.csv",
        }
        fname = fmap.get((inst, tf))
        if not fname: return []
        fp = UPLOAD_DIR / fname
        if not fp.exists(): return []
        _cache[key] = load_csv(fp)
    return _cache[key]

# ── Runner ──────────────────────────────────────────────────────────
def run_test(strategy_file, settings, bars, spread_pts, commission, pv):
    fp = str(STRATEGY_DIR / strategy_file)
    try:
        r = run_file_strategy("python", fp, settings, bars, INITIAL_BALANCE, spread_pts, commission, pv)
        if r.total_trades < 10:
            return None
        return {
            "trades": r.total_trades, "win_rate": round(r.win_rate, 1),
            "pf": round(r.profit_factor, 2), "net": round(r.net_profit, 2),
            "dd": round(r.max_drawdown_pct, 1), "sharpe": round(r.sharpe_ratio, 2),
            "avg_win": round(r.avg_win, 2), "avg_loss": round(r.avg_loss, 2),
        }
    except Exception as e:
        return None

def score(r):
    """Combined score: Sharpe + PF + penalty for high DD."""
    if r is None: return -999
    s = r["sharpe"] * 2 + r["pf"] * 3
    if r["dd"] > 30: s -= 5
    elif r["dd"] > 20: s -= 2
    if r["net"] < 0: s -= 3
    if r["trades"] < 30: s -= 2
    return s


# ════════════════════════════════════════════════════════════════════
#  OPTIMIZE S45: XAUUSD Session Momentum
# ════════════════════════════════════════════════════════════════════
def optimize_s45():
    print("\n" + "=" * 90)
    print("  OPTIMIZING: S45 XAUUSD Session Momentum (M5)")
    print("=" * 90)

    bars = get_data("XAUUSD", "M5")
    if not bars:
        print("  No data!"); return

    # Grid search
    params = {
        "adx_threshold":  [18, 22, 25, 30],
        "atr_sl_mult":    [1.2, 1.5, 2.0],
        "atr_tp_mult":    [2.0, 3.0, 4.0, 5.0],
        "rsi_cap":        [65, 70, 75, 80],
        "session_start_hour": [7, 8],
        "session_end_hour":   [15, 16],
    }

    keys = list(params.keys())
    combos = list(product(*params.values()))
    print(f"  Testing {len(combos)} parameter combinations...")

    best = None
    best_score = -999
    best_settings = {}
    count = 0

    for vals in combos:
        settings = dict(zip(keys, vals))
        settings["lot_size"] = 0.01

        # Skip illogical: TP must be > SL for positive expectancy
        if settings["atr_tp_mult"] <= settings["atr_sl_mult"]:
            continue

        r = run_test("s45_xauusd_session_momentum_m5.py", settings, bars,
                      0.0012, 7.0, 100.0)  # Tight spread
        count += 1
        if count % 50 == 0:
            print(f"  ... {count}/{len(combos)} tested", flush=True)

        s = score(r)
        if s > best_score:
            best_score = s
            best = r
            best_settings = settings.copy()

    print(f"\n  BEST S45 Parameters:")
    for k, v in best_settings.items():
        print(f"    {k}: {v}")
    if best:
        print(f"\n  Results: {best['trades']} trades | WR: {best['win_rate']}% | "
              f"PF: {best['pf']} | Net: ${best['net']:.2f} | DD: {best['dd']}% | "
              f"Sharpe: {best['sharpe']}")
    return best_settings, best


# ════════════════════════════════════════════════════════════════════
#  OPTIMIZE S46: NAS100 ORB + VWAP
# ════════════════════════════════════════════════════════════════════
def optimize_s46():
    print("\n" + "=" * 90)
    print("  OPTIMIZING: S46 NAS100 ORB + VWAP (M5)")
    print("=" * 90)

    bars = get_data("US100", "M5")
    if not bars:
        print("  No data!"); return

    params = {
        "or_bars":        [4, 6, 9, 12],        # 20/30/45/60 min opening range
        "atr_sl_mult":    [1.5, 2.0, 2.5],
        "atr_tp_mult":    [2.5, 3.5, 5.0],
        "use_vwap_filter": [True, False],
        "use_trailing":   [True, False],
        "entry_cutoff_hour": [17, 18, 19],
        "max_daily_trades":  [2, 3],
    }

    keys = list(params.keys())
    combos = list(product(*params.values()))
    print(f"  Testing {len(combos)} parameter combinations...")

    best = None
    best_score = -999
    best_settings = {}
    count = 0

    for vals in combos:
        settings = dict(zip(keys, vals))
        settings["lot_size"] = 0.1

        if settings["atr_tp_mult"] <= settings["atr_sl_mult"]:
            continue

        r = run_test("s46_nas100_orb_vwap_m5.py", settings, bars,
                      1.0, 3.5, 1.0)  # Tight spread
        count += 1
        if count % 50 == 0:
            print(f"  ... {count}/{len(combos)} tested", flush=True)

        s = score(r)
        if s > best_score:
            best_score = s
            best = r
            best_settings = settings.copy()

    print(f"\n  BEST S46 Parameters:")
    for k, v in best_settings.items():
        print(f"    {k}: {v}")
    if best:
        print(f"\n  Results: {best['trades']} trades | WR: {best['win_rate']}% | "
              f"PF: {best['pf']} | Net: ${best['net']:.2f} | DD: {best['dd']}% | "
              f"Sharpe: {best['sharpe']}")
    return best_settings, best


# ════════════════════════════════════════════════════════════════════
#  OPTIMIZE S47: XAUUSD RSI-2 Mean Reversion
# ════════════════════════════════════════════════════════════════════
def optimize_s47():
    print("\n" + "=" * 90)
    print("  OPTIMIZING: S47 XAUUSD RSI-2 Mean Reversion (M5 proxy)")
    print("=" * 90)

    bars = get_data("XAUUSD", "M5")
    if not bars:
        print("  No data!"); return

    params = {
        "rsi_oversold":    [5, 10, 15, 20],
        "rsi_overbought":  [80, 85, 90, 95],
        "atr_sl_mult":     [1.0, 1.5, 2.0, 2.5],
        "bb_mult":         [1.5, 2.0, 2.5],
        "max_bars_held":   [5, 10, 15],
        "min_bars_between": [2, 3, 5],
    }

    keys = list(params.keys())
    combos = list(product(*params.values()))
    print(f"  Testing {len(combos)} parameter combinations...")

    best = None
    best_score = -999
    best_settings = {}
    count = 0

    for vals in combos:
        settings = dict(zip(keys, vals))
        settings["lot_size"] = 0.01
        settings["tp_target"] = "bb_mid"

        # RSI thresholds must be symmetric-ish
        if settings["rsi_overbought"] <= (100 - settings["rsi_oversold"] - 10):
            continue

        r = run_test("s47_xauusd_rsi2_mean_reversion_m1.py", settings, bars,
                      0.0012, 7.0, 100.0)  # Tight spread
        count += 1
        if count % 50 == 0:
            print(f"  ... {count}/{len(combos)} tested", flush=True)

        s = score(r)
        if s > best_score:
            best_score = s
            best = r
            best_settings = settings.copy()

    print(f"\n  BEST S47 Parameters:")
    for k, v in best_settings.items():
        print(f"    {k}: {v}")
    if best:
        print(f"\n  Results: {best['trades']} trades | WR: {best['win_rate']}% | "
              f"PF: {best['pf']} | Net: ${best['net']:.2f} | DD: {best['dd']}% | "
              f"Sharpe: {best['sharpe']}")
    return best_settings, best


# ════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    t0 = time.time()

    r1 = optimize_s45()
    r2 = optimize_s46()
    r3 = optimize_s47()

    elapsed = time.time() - t0
    print(f"\n\nTotal optimization time: {elapsed:.0f}s ({elapsed/60:.1f}m)")

    # Save results
    output = {
        "timestamp": datetime.now().isoformat(),
        "s45_best_params": r1[0] if r1 else {},
        "s45_best_result": r1[1] if r1 else {},
        "s46_best_params": r2[0] if r2 else {},
        "s46_best_result": r2[1] if r2 else {},
        "s47_best_params": r3[0] if r3 else {},
        "s47_best_result": r3[1] if r3 else {},
    }
    with open(Path(__file__).parent / "optimization_results.json", "w") as f:
        json.dump(output, f, indent=2)
    print("Results saved to optimization_results.json")
