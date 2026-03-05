"""
Walk-Forward Backtest V2 — Optimized for speed.

Uses smaller datasource subsets to avoid timeout, and correct instrument params.
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

STRATEGIES = {
    43: "Adaptive Mean Reversion",
    44: "Triple EMA Momentum",
    45: "Stochastic Reversal Breakout",
}

# Use the 5K bars EURUSD and Oanda XAUUSD (4999 bars) for quick tests
# Also add M15 datasets which are 50K but faster timeframe
# Key: use correct point_value for each instrument
DATASOURCES = {
    23: {"name": "XAUUSD_H1_5K", "symbol": "XAUUSD", "bars": 4999,
         "point_value": 0.01, "spread": 30, "commission": 7.0},
    22: {"name": "EURUSD_H1_5K", "symbol": "EURUSD", "bars": 5000,
         "point_value": 0.00001, "spread": 15, "commission": 7.0},
    # M15 datasets — let's try with moderate timeout
    7:  {"name": "XAUUSD_M15_50K", "symbol": "XAUUSD", "bars": 50000,
         "point_value": 0.01, "spread": 30, "commission": 7.0},
}

print("=" * 90)
print("STANDARD V3 BACKTESTS")
print("=" * 90)

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
        
        print(f"\n  {key}...", end=" ", flush=True)
        t0 = time.time()
        try:
            r = requests.post(f"{BASE}/api/backtest/run-v3", headers=HEADERS,
                              json=payload, timeout=600)
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
                    "avg_win": stats.get("avg_win", 0),
                    "avg_loss": stats.get("avg_loss", 0),
                    "elapsed": round(elapsed, 1),
                }
                results[strat_id][ds_id] = result
                print(f"OK ({elapsed:.1f}s)")
                print(f"       Trades={result['trades']} WR={result['win_rate']:.1f}% PF={result['profit_factor']:.2f} " +
                      f"P/L=${result['net_profit']:.2f} DD={result['max_dd_pct']:.1f}% Sharpe={result['sharpe']:.2f}")
                print(f"       AvgWin=${result['avg_win']:.2f} AvgLoss=${result['avg_loss']:.2f}")
            else:
                error_text = r.text[:300]
                print(f"FAIL ({r.status_code}): {error_text}")
                results[strat_id][ds_id] = {"error": r.status_code, "msg": error_text}
        except requests.exceptions.ReadTimeout:
            elapsed = time.time() - t0
            print(f"TIMEOUT ({elapsed:.0f}s)")
            results[strat_id][ds_id] = {"error": "timeout"}
        except Exception as e:
            print(f"ERROR: {e}")
            results[strat_id][ds_id] = {"error": str(e)}

# Summary
print("\n\n" + "=" * 110)
print("RESULTS SUMMARY")
print("=" * 110)
header = f"{'Strategy':<30} {'Dataset':<16} {'Trades':>7} {'WR%':>6} {'PF':>6} {'Net P/L':>12} {'MaxDD%':>7} {'Sharpe':>7} {'AvgWin':>10} {'AvgLoss':>10}"
print(header)
print("-" * 110)

for strat_id, strat_name in STRATEGIES.items():
    for ds_id, ds_info in DATASOURCES.items():
        r = results.get(strat_id, {}).get(ds_id, {})
        if "error" in r:
            err = r.get("error", "?")
            print(f"{strat_name:<30} {ds_info['name']:<16} {'ERR: ' + str(err):>7}")
        else:
            print(f"{strat_name:<30} {ds_info['name']:<16} {r.get('trades',0):>7} {r.get('win_rate',0):>6.1f} " +
                  f"{r.get('profit_factor',0):>6.2f} {r.get('net_profit',0):>12.2f} {r.get('max_dd_pct',0):>7.1f} " +
                  f"{r.get('sharpe',0):>7.2f} {r.get('avg_win',0):>10.2f} {r.get('avg_loss',0):>10.2f}")

# Walk-forward on 5K datasets only (fast)
print("\n\n" + "=" * 110)
print("WALK-FORWARD VALIDATION (5-fold anchored)")
print("=" * 110)

WF_DS = [23, 22]  # XAUUSD_H1_5K, EURUSD_H1_5K

wf_results = {}
for strat_id, strat_name in STRATEGIES.items():
    wf_results[strat_id] = {}
    for ds_id in WF_DS:
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
            r = requests.post(f"{BASE}/api/backtest/walk-forward-v3", headers=HEADERS,
                              json=payload, timeout=600)
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
                print(f"OK ({elapsed:.1f}s)")
                print(f"       OOS: Trades={wf['oos_trades']} WR={wf['oos_win_rate']:.1f}% " +
                      f"PF={wf['oos_profit_factor']:.2f} P/L=${wf['oos_net_profit']:.2f} " +
                      f"DD={wf['oos_max_dd_pct']:.1f}%")
            else:
                print(f"FAIL ({r.status_code}): {r.text[:200]}")
                wf_results[strat_id][ds_id] = {"error": r.status_code}
        except requests.exceptions.ReadTimeout:
            elapsed = time.time() - t0
            print(f"TIMEOUT ({elapsed:.0f}s)")
            wf_results[strat_id][ds_id] = {"error": "timeout"}
        except Exception as e:
            print(f"ERROR: {e}")
            wf_results[strat_id][ds_id] = {"error": str(e)}

# WF Summary
print("\n\n" + "=" * 110)
print("WALK-FORWARD (OOS) SUMMARY")
print("=" * 110)
header = f"{'Strategy':<30} {'Dataset':<16} {'OOS Trd':>8} {'WR%':>6} {'PF':>6} {'Net P/L':>12} {'MaxDD%':>7} {'Sharpe':>7}"
print(header)
print("-" * 110)

for strat_id, strat_name in STRATEGIES.items():
    for ds_id in WF_DS:
        ds_info = DATASOURCES[ds_id]
        r = wf_results.get(strat_id, {}).get(ds_id, {})
        if "error" in r:
            print(f"{strat_name:<30} {ds_info['name']:<16} {'ERR':>8}")
        else:
            print(f"{strat_name:<30} {ds_info['name']:<16} {r.get('oos_trades',0):>8} " +
                  f"{r.get('oos_win_rate',0):>6.1f} {r.get('oos_profit_factor',0):>6.2f} " +
                  f"{r.get('oos_net_profit',0):>12.2f} {r.get('oos_max_dd_pct',0):>7.1f} " +
                  f"{r.get('oos_sharpe',0):>7.2f}")

# Save all results
output = {
    "standard": {str(sid): {str(did): results.get(sid, {}).get(did, {}) for did in DATASOURCES} for sid in STRATEGIES},
    "walk_forward": {str(sid): {str(did): wf_results.get(sid, {}).get(did, {}) for did in WF_DS} for sid in STRATEGIES},
}
with open("backtest_results_strategies.json", "w") as f:
    json.dump(output, f, indent=2)

print("\nResults saved to backtest_results_strategies.json")
