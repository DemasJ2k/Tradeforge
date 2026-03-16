"""
Realistic Backtest Runner — Three High-Sharpe Scalping Strategies
=================================================================
Runs s45, s46, s47 with realistic cTrader trading costs.

Cost Research Summary (cTrader Raw Spread Accounts, IC Markets/Pepperstone):
─────────────────────────────────────────────────────────────────────────────
XAUUSD (Gold):
  Spread:     $0.10–0.15 during London/NY (raw spread account)
              $0.25–0.50 during Asian session
  Commission: $7.00 per standard lot round-trip (100 oz)
  Slippage:   ~0.01–0.02% per fill on M5 (higher on M1)
  Point value: $1 per point per lot (1 lot = 100 oz, 1 point = $0.01)

  For 0.01 lot (micro): spread cost ≈ $0.01–0.015, commission ≈ $0.07

US100 (NAS100 / NASDAQ):
  Spread:     1.0–1.5 points during NY session (raw)
              2.0–3.0 points off-hours
  Commission: $3.50 per standard lot round-trip
  Slippage:   ~0.01% per fill on M5
  Point value: $1 per point per lot (1 lot = 1 contract)

  For 0.01 lot: spread cost ≈ $0.01–0.015, commission ≈ $0.035

We use PESSIMISTIC estimates:
  - XAUUSD spread: 0.20 (includes some Asian bars in data)
  - US100 spread: 1.5 points
  - Slippage: 0.02% for both
  - Full commissions per lot
"""

import csv
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.strategy.file_runner import run_file_strategy

# ── Paths ───────────────────────────────────────────────────────────
UPLOAD_DIR = Path(__file__).parent / "data" / "uploads"
STRATEGY_DIR = Path(__file__).parent / "data" / "strategies"

# ── Realistic Cost Configurations per Instrument ─────────────────────
# Based on cTrader Raw Spread accounts (IC Markets, Pepperstone, FxPro)

# NOTE: The file_runner harness applies spread as:
#   entry_price += spread_points * point_value   (in price terms)
# Then PnL = (exit - entry) * size * point_value
# So spread cost = spread_points * point_value^2 * size
# To get correct dollar spread, we pass: spread_points = actual_spread / point_value
#
# Example: Gold actual spread $0.20, point_value=100
#   spread_points = 0.20 / 100 = 0.002
#   Cost = 0.002 * 100 * 0.01 * 100 = $0.20 ✓

INSTRUMENT_COSTS = {
    "XAUUSD": {
        "spread_points": 0.002,       # $0.20 actual spread / pv100 — pessimistic avg
        "commission_per_lot": 7.0,    # $7 RT per standard lot (100 oz)
        "point_value": 100.0,         # 1 lot = 100 oz, so $1 move = $100/lot
        "actual_spread": 0.20,        # For reporting
        "description": "Gold — $0.20 spread, $7/lot RT, 100oz/lot",
    },
    "XAUUSD_TIGHT": {
        "spread_points": 0.0012,      # $0.12 actual / pv100 — London/NY only
        "commission_per_lot": 7.0,
        "point_value": 100.0,
        "actual_spread": 0.12,
        "description": "Gold — $0.12 spread (London/NY), $7/lot RT, 100oz/lot",
    },
    "US100": {
        "spread_points": 1.5,         # 1.5 points — pessimistic avg (pv=1.0, no adjustment)
        "commission_per_lot": 3.5,    # $3.50 RT per lot
        "point_value": 1.0,           # $1 per point per lot (standard CFD)
        "actual_spread": 1.5,
        "description": "NASDAQ 100 — 1.5pt spread, $3.50/lot RT",
    },
    "US100_TIGHT": {
        "spread_points": 1.0,         # 1.0 points — NY session only
        "commission_per_lot": 3.5,
        "point_value": 1.0,
        "actual_spread": 1.0,
        "description": "NASDAQ 100 — 1.0pt spread (NY), $3.50/lot RT",
    },
}

# ── Data Files ──────────────────────────────────────────────────────
DATA_MAP = {
    ("XAUUSD", "M5"):  "1772956552_XAUUSD_M5_180000bars.csv",
    ("XAUUSD", "M15"): "1772956560_XAUUSD_M15_180000bars.csv",
    ("XAUUSD", "H1"):  "1772956576_XAUUSD_H1_121610bars.csv",
    ("US100",  "M5"):  "1772956324_US100_M5_180000bars.csv",
    ("US100",  "M15"): "1772956345_US100_M15_180000bars.csv",
    ("US100",  "H1"):  "1772956365_US100_H1_50239bars.csv",
}

# ── Strategy Configurations ─────────────────────────────────────────
STRATEGIES = [
    {
        "name": "s45_xauusd_session_momentum_m5",
        "label": "XAUUSD Session Momentum (M5)",
        "instrument": "XAUUSD",
        "timeframe": "M5",
        "cost_profile": "XAUUSD",       # Use pessimistic spread
        "settings": {},                  # Use strategy DEFAULTS
    },
    {
        "name": "s45_xauusd_session_momentum_m5",
        "label": "XAUUSD Session Momentum (M5) [Tight Spread]",
        "instrument": "XAUUSD",
        "timeframe": "M5",
        "cost_profile": "XAUUSD_TIGHT",  # London/NY only — more realistic since strategy filters sessions
        "settings": {},
    },
    {
        "name": "s46_nas100_orb_vwap_m5",
        "label": "NAS100 ORB + VWAP (M5)",
        "instrument": "US100",
        "timeframe": "M5",
        "cost_profile": "US100",
        "settings": {},
    },
    {
        "name": "s46_nas100_orb_vwap_m5",
        "label": "NAS100 ORB + VWAP (M5) [Tight Spread]",
        "instrument": "US100",
        "timeframe": "M5",
        "cost_profile": "US100_TIGHT",
        "settings": {},
    },
    {
        "name": "s47_xauusd_rsi2_mean_reversion_m1",
        "label": "XAUUSD RSI-2 MeanRev (M5 proxy — no M1 data)",
        "instrument": "XAUUSD",
        "timeframe": "M5",
        "cost_profile": "XAUUSD",
        "settings": {
            # Adjust for M5 (wider bars = need wider thresholds)
            "rsi_oversold": 15,       # Slightly relaxed for M5
            "rsi_overbought": 85,
            "max_bars_held": 8,       # 8 M5 bars = 40 min
            "min_bars_between": 2,
            "atr_sl_mult": 1.5,       # Wider SL for M5
        },
    },
    {
        "name": "s47_xauusd_rsi2_mean_reversion_m1",
        "label": "XAUUSD RSI-2 MeanRev (M5 proxy) [Tight Spread]",
        "instrument": "XAUUSD",
        "timeframe": "M5",
        "cost_profile": "XAUUSD_TIGHT",
        "settings": {
            "rsi_oversold": 15,
            "rsi_overbought": 85,
            "max_bars_held": 8,
            "min_bars_between": 2,
            "atr_sl_mult": 1.5,
        },
    },
]

# ── CSV Parser ──────────────────────────────────────────────────────

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


# ── Data Cache ──────────────────────────────────────────────────────
_cache: dict[str, list[dict]] = {}


def get_data(instrument: str, tf: str) -> list[dict]:
    key = f"{instrument}_{tf}"
    if key not in _cache:
        fname = DATA_MAP.get((instrument, tf))
        if not fname:
            return []
        fp = UPLOAD_DIR / fname
        if not fp.exists():
            print(f"  [WARN] Data file not found: {fp}")
            return []
        _cache[key] = load_csv(fp)
    return _cache[key]


# ── Backtest Runner ─────────────────────────────────────────────────

INITIAL_BALANCE = 3000.0   # $3k account — realistic for the user


def run_single(strat_cfg: dict) -> dict:
    """Run a single strategy backtest with realistic costs."""
    name = strat_cfg["name"]
    instrument = strat_cfg["instrument"]
    tf = strat_cfg["timeframe"]
    cost_profile = strat_cfg["cost_profile"]
    settings = strat_cfg["settings"]
    label = strat_cfg["label"]

    costs = INSTRUMENT_COSTS[cost_profile]
    file_path = str(STRATEGY_DIR / f"{name}.py")

    if not os.path.exists(file_path):
        return {"label": label, "error": f"Strategy file not found: {file_path}"}

    bars = get_data(instrument, tf)
    if not bars:
        return {"label": label, "error": f"No data for {instrument} {tf}"}

    try:
        t0 = time.time()
        result = run_file_strategy(
            strategy_type="python",
            file_path=file_path,
            settings_values=settings,
            bars_raw=bars,
            initial_balance=INITIAL_BALANCE,
            spread_points=costs["spread_points"],
            commission_per_lot=costs["commission_per_lot"],
            point_value=costs["point_value"],
        )
        elapsed = time.time() - t0

        # Additional metrics
        calmar = 0
        if result.max_drawdown_pct > 0:
            # Annualized return / max DD
            total_return_pct = (result.net_profit / INITIAL_BALANCE) * 100
            calmar = total_return_pct / result.max_drawdown_pct

        return {
            "label": label,
            "instrument": instrument,
            "timeframe": tf,
            "cost_profile": cost_profile,
            "spread": costs["spread_points"],
            "commission": costs["commission_per_lot"],
            "bars": result.total_bars,
            "trades": result.total_trades,
            "winners": result.winning_trades,
            "losers": result.losing_trades,
            "win_rate": round(result.win_rate, 2),
            "net_profit": round(result.net_profit, 2),
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
        return {"label": label, "error": str(e)[:300]}


# ── Grade Strategy ──────────────────────────────────────────────────

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


# ── Main ────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 100)
    print("  TRADEFORGE — REALISTIC STRATEGY BACKTEST RUNNER")
    print("  3 High-Sharpe M1/M5 Scalping Strategies with cTrader Costs")
    print("=" * 100)
    print(f"  Account: ${INITIAL_BALANCE:,.0f}  |  Broker: cTrader (Raw Spread)")
    print(f"  XAUUSD spread: $0.12–0.20  |  US100 spread: 1.0–1.5 pts")
    print(f"  Commission: XAUUSD $7/lot, US100 $3.50/lot  |  Slippage: via spread")
    print("=" * 100)

    results = []
    total = len(STRATEGIES)

    for idx, strat_cfg in enumerate(STRATEGIES, 1):
        label = strat_cfg["label"]
        print(f"\n[{idx}/{total}] {label} ...", end="", flush=True)

        res = run_single(strat_cfg)
        results.append(res)

        if res.get("error"):
            print(f"\n  ERROR: {res['error'][:120]}")
        else:
            g = grade(res)
            print(f"\n  [{g}] {res['trades']} trades | WR: {res['win_rate']:.1f}% | "
                  f"PF: {res['profit_factor']:.2f} | Net: ${res['net_profit']:,.2f} | "
                  f"DD: {res['max_dd_pct']:.1f}% | Sharpe: {res['sharpe']:.2f} | "
                  f"Calmar: {res['calmar']:.2f} | {res['elapsed']:.0f}s")

    # ── Summary Table ──────────────────────────────────────────────
    print("\n\n" + "=" * 140)
    print("  RESULTS SUMMARY — REALISTIC COSTS")
    print("=" * 140)
    header = (f"{'Strategy':<52} {'Spread':>7} {'Trades':>7} {'WinRate':>8} {'PF':>6} "
              f"{'NetProfit':>11} {'MaxDD%':>7} {'Sharpe':>7} {'Calmar':>7} "
              f"{'AvgWin':>8} {'AvgLoss':>8} {'Expect':>8}")
    print(header)
    print("-" * 140)

    valid = [r for r in results if not r.get("error")]
    valid.sort(key=lambda x: x.get("sharpe", 0), reverse=True)

    for r in valid:
        g = grade(r)
        print(f"[{g}] {r['label']:<48} {r['spread']:>7.2f} {r['trades']:>7} "
              f"{r['win_rate']:>7.1f}% {r['profit_factor']:>6.2f} "
              f"${r['net_profit']:>10,.2f} {r['max_dd_pct']:>6.1f}% "
              f"{r['sharpe']:>7.2f} {r['calmar']:>7.2f} "
              f"${r['avg_win']:>7.2f} ${r['avg_loss']:>7.2f} ${r['expectancy']:>7.2f}")

    # Print errors
    errors = [r for r in results if r.get("error")]
    if errors:
        print(f"\n  ERRORS:")
        for r in errors:
            print(f"    {r['label']}: {r['error'][:100]}")

    # ── Cost Impact Analysis ──────────────────────────────────────
    print("\n\n" + "=" * 100)
    print("  COST IMPACT ANALYSIS")
    print("=" * 100)

    for r in valid:
        if r["trades"] == 0:
            continue
        total_spread_cost = r["spread"] * r["trades"] * r.get("point_value", 1.0) * 0.01  # micro lot
        total_commission = r["commission"] * r["trades"] * 0.01  # micro lot
        total_cost = total_spread_cost + total_commission
        cost_per_trade = total_cost / r["trades"] if r["trades"] > 0 else 0
        net_before_costs = r["net_profit"] + total_cost  # approximate
        cost_drag_pct = (total_cost / net_before_costs * 100) if net_before_costs > 0 else 0

        print(f"\n  {r['label']}:")
        print(f"    Trades: {r['trades']} | Spread cost: ~${total_spread_cost:.2f} | "
              f"Commission: ~${total_commission:.2f}")
        print(f"    Total friction: ~${total_cost:.2f} ({cost_drag_pct:.1f}% of gross) | "
              f"Per trade: ~${cost_per_trade:.4f}")

    # ── Save Results ──────────────────────────────────────────────
    output_path = Path(__file__).parent / "backtest_results_scalping.json"
    output = {
        "timestamp": datetime.now().isoformat(),
        "config": {
            "initial_balance": INITIAL_BALANCE,
            "broker": "cTrader Raw Spread",
            "cost_profiles": INSTRUMENT_COSTS,
        },
        "results": [r for r in results if not r.get("error")],
        "errors": [r for r in results if r.get("error")],
    }
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
