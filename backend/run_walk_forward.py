"""
Walk-Forward Backtest — Test all 3 universal strategies across instruments.

Uses the V3 engine walk-forward validation (anchored mode, 5 folds)
to get realistic out-of-sample performance metrics.
"""
import requests
import json
import sys
import time

BASE = "http://localhost:8000"

# Login
r = requests.post(f"{BASE}/api/auth/login", json={
    "username": "FlowrexAdmin",
    "password": "Flowrex2025!"
})
TOKEN = r.json()["access_token"]
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# Strategy IDs (just created)
STRATEGIES = {
    43: "Adaptive Mean Reversion",
    44: "Triple EMA Momentum",
    45: "Stochastic Reversal Breakout",
}

# Datasources — H1 datasets with 50K bars for robust walk-forward
DATASOURCES = {
    10: {"name": "XAUUSD_H1", "symbol": "XAUUSD", "bars": 50000, "point_value": 0.01, "spread": 30, "commission": 7.0},
    14: {"name": "US30_H1",   "symbol": "US30",   "bars": 50000, "point_value": 1.0,  "spread": 30, "commission": 7.0},
    18: {"name": "US100_H1",  "symbol": "US100",  "bars": 50000, "point_value": 1.0,  "spread": 20, "commission": 7.0},
    22: {"name": "EURUSD_H1", "symbol": "EURUSD", "bars": 5000,  "point_value": 0.00001, "spread": 10, "commission": 7.0},
    24: {"name": "BTCUSD_M15","symbol": "BTCUSD", "bars": 50000, "point_value": 0.01, "spread": 50, "commission": 7.0},
}

# First run standard backtests (faster, get quick results)
print("=" * 80)
print("PHASE 1: Standard V3 Backtests (full dataset)")
print("=" * 80)

results = {}
for strat_id, strat_name in STRATEGIES.items():
    results[strat_id] = {}
    for ds_id, ds_info in DATASOURCES.items():
        key = f"{strat_name} | {ds_info['name']}"
        payload = {
            "strategy_id": strat_id,
            "datasource_id": ds_id,
            "initial_balance": 10000.0,
            "spread_points": ds_info["spread"],
            "commission_per_lot": ds_info["commission"],
            "point_value": ds_info["point_value"],
            "slippage_pct": 0.01,
            "margin_rate": 0.01,
        }
        
        print(f"\n  Running: {key}...", end=" ", flush=True)
        t0 = time.time()
        try:
            r = requests.post(f"{BASE}/api/backtest/run-v3", headers=HEADERS, json=payload, timeout=600)
            elapsed = time.time() - t0
            
            if r.status_code == 200:
                data = r.json()
                stats = data.get("stats", {})
                result = {
                    "trades": stats.get("total_trades", 0),
                    "win_rate": stats.get("win_rate", 0),
                    "net_profit": stats.get("net_profit", 0),
                    "profit_factor": stats.get("profit_factor", 0),
                    "max_dd_pct": stats.get("max_drawdown_pct", 0),
                    "sharpe": stats.get("sharpe_ratio", 0),
                    "expectancy": stats.get("expectancy", 0),
                    "elapsed": round(elapsed, 1),
                }
                results[strat_id][ds_id] = result
                print(f"OK ({elapsed:.1f}s) | Trades={result['trades']} WR={result['win_rate']:.1f}% PF={result['profit_factor']:.2f} P/L=${result['net_profit']:.0f} DD={result['max_dd_pct']:.1f}%")
            else:
                print(f"FAILED ({r.status_code}): {r.text[:200]}")
                results[strat_id][ds_id] = {"error": r.status_code}
        except Exception as e:
            print(f"ERROR: {e}")
            results[strat_id][ds_id] = {"error": str(e)}

# Summary table
print("\n\n" + "=" * 80)
print("STANDARD BACKTEST RESULTS SUMMARY")
print("=" * 80)

header = f"{'Strategy':<30} {'Dataset':<12} {'Trades':>7} {'WR%':>6} {'PF':>6} {'Net P/L':>10} {'MaxDD%':>7} {'Sharpe':>7}"
print(header)
print("-" * len(header))

for strat_id, strat_name in STRATEGIES.items():
    for ds_id, ds_info in DATASOURCES.items():
        r = results.get(strat_id, {}).get(ds_id, {})
        if "error" in r:
            print(f"{strat_name:<30} {ds_info['name']:<12} {'ERROR':>7}")
        else:
            print(f"{strat_name:<30} {ds_info['name']:<12} {r.get('trades',0):>7} {r.get('win_rate',0):>6.1f} {r.get('profit_factor',0):>6.2f} {r.get('net_profit',0):>10.0f} {r.get('max_dd_pct',0):>7.1f} {r.get('sharpe',0):>7.2f}")

# Phase 2: Walk-forward on the top performers
print("\n\n" + "=" * 80)
print("PHASE 2: Walk-Forward Validation (5-fold anchored)")
print("=" * 80)

# Run walk-forward on 3 key H1 datasets
WF_DATASOURCES = [10, 14, 18]  # XAUUSD, US30, US100 (50K bars each)

wf_results = {}
for strat_id, strat_name in STRATEGIES.items():
    wf_results[strat_id] = {}
    for ds_id in WF_DATASOURCES:
        ds_info = DATASOURCES[ds_id]
        key = f"{strat_name} | {ds_info['name']}"
        payload = {
            "strategy_id": strat_id,
            "datasource_id": ds_id,
            "n_folds": 5,
            "train_pct": 70.0,
            "mode": "anchored",
            "initial_balance": 10000.0,
            "spread_points": ds_info["spread"],
            "commission_per_lot": ds_info["commission"],
            "point_value": ds_info["point_value"],
        }
        
        print(f"\n  WF: {key}...", end=" ", flush=True)
        t0 = time.time()
        try:
            r = requests.post(f"{BASE}/api/backtest/walk-forward-v3", headers=HEADERS, json=payload, timeout=900)
            elapsed = time.time() - t0
            
            if r.status_code == 200:
                data = r.json()
                wf = {
                    "oos_trades": data.get("oos_total_trades", 0),
                    "oos_win_rate": data.get("oos_win_rate", 0),
                    "oos_net_profit": data.get("oos_net_profit", 0),
                    "oos_profit_factor": data.get("oos_profit_factor", 0),
                    "oos_max_dd_pct": data.get("oos_max_drawdown_pct", 0),
                    "oos_sharpe": data.get("oos_sharpe_ratio", 0),
                    "oos_expectancy": data.get("oos_expectancy", 0),
                    "elapsed": round(elapsed, 1),
                }
                wf_results[strat_id][ds_id] = wf
                print(f"OK ({elapsed:.1f}s) | OOS: Trades={wf['oos_trades']} WR={wf['oos_win_rate']:.1f}% PF={wf['oos_profit_factor']:.2f} P/L=${wf['oos_net_profit']:.0f} DD={wf['oos_max_dd_pct']:.1f}%")
            else:
                print(f"FAILED ({r.status_code}): {r.text[:200]}")
                wf_results[strat_id][ds_id] = {"error": r.status_code}
        except Exception as e:
            print(f"ERROR: {e}")
            wf_results[strat_id][ds_id] = {"error": str(e)}

# WF Summary
print("\n\n" + "=" * 80)
print("WALK-FORWARD (OOS) RESULTS SUMMARY")
print("=" * 80)

header = f"{'Strategy':<30} {'Dataset':<12} {'OOS Trd':>8} {'WR%':>6} {'PF':>6} {'Net P/L':>10} {'MaxDD%':>7} {'Sharpe':>7}"
print(header)
print("-" * len(header))

for strat_id, strat_name in STRATEGIES.items():
    for ds_id in WF_DATASOURCES:
        ds_info = DATASOURCES[ds_id]
        r = wf_results.get(strat_id, {}).get(ds_id, {})
        if "error" in r:
            print(f"{strat_name:<30} {ds_info['name']:<12} {'ERROR':>8}")
        else:
            print(f"{strat_name:<30} {ds_info['name']:<12} {r.get('oos_trades',0):>8} {r.get('oos_win_rate',0):>6.1f} {r.get('oos_profit_factor',0):>6.2f} {r.get('oos_net_profit',0):>10.0f} {r.get('oos_max_dd_pct',0):>7.1f} {r.get('oos_sharpe',0):>7.2f}")

# Final ranking
print("\n\n" + "=" * 80)
print("OVERALL RANKING (by avg OOS Profit Factor)")
print("=" * 80)

ranking = []
for strat_id, strat_name in STRATEGIES.items():
    pfs = []
    wrs = []
    trades_total = 0
    profits_total = 0
    for ds_id in WF_DATASOURCES:
        r = wf_results.get(strat_id, {}).get(ds_id, {})
        if "error" not in r:
            pfs.append(r.get("oos_profit_factor", 0))
            wrs.append(r.get("oos_win_rate", 0))
            trades_total += r.get("oos_trades", 0)
            profits_total += r.get("oos_net_profit", 0)
    
    avg_pf = sum(pfs) / len(pfs) if pfs else 0
    avg_wr = sum(wrs) / len(wrs) if wrs else 0
    ranking.append({
        "id": strat_id,
        "name": strat_name,
        "avg_pf": avg_pf,
        "avg_wr": avg_wr,
        "total_trades": trades_total,
        "total_profit": profits_total,
    })

ranking.sort(key=lambda x: x["avg_pf"], reverse=True)

for i, r in enumerate(ranking, 1):
    print(f"  #{i}: {r['name']} (id={r['id']})")
    print(f"      Avg OOS Profit Factor: {r['avg_pf']:.2f}")
    print(f"      Avg OOS Win Rate: {r['avg_wr']:.1f}%")
    print(f"      Total OOS Trades: {r['total_trades']}")
    print(f"      Total OOS Profit: ${r['total_profit']:.0f}")
    print()

# Save results to JSON
output = {
    "standard_results": {},
    "walk_forward_results": {},
    "ranking": ranking,
}
for strat_id in STRATEGIES:
    output["standard_results"][str(strat_id)] = {
        str(ds_id): results.get(strat_id, {}).get(ds_id, {})
        for ds_id in DATASOURCES
    }
    output["walk_forward_results"][str(strat_id)] = {
        str(ds_id): wf_results.get(strat_id, {}).get(ds_id, {})
        for ds_id in WF_DATASOURCES
    }

with open("backtest_results_strategies.json", "w") as f:
    json.dump(output, f, indent=2)

print("\nResults saved to backtest_results_strategies.json")
