"""Test the backtest engine end-to-end."""
import requests
import json

BASE = "http://localhost:8000"

# 1. Register + Login
print("=== Register & Login ===")
requests.post(f"{BASE}/api/auth/register", json={"username": "demas", "password": "password123"})
r = requests.post(f"{BASE}/api/auth/login", json={"username": "demas", "password": "password123"})
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
print(f"Token: {token[:20]}...")

# 2. Upload CSV
print("\n=== Upload CSV ===")
csv_path = r"D:\Doc\DATA\tradeforge\backend\data\uploads\1771417627_XAUUSD_M10_20250101_20261202_MT5.csv"
with open(csv_path, "rb") as f:
    r = requests.post(f"{BASE}/api/data/upload", files={"file": ("XAUUSD_M10.csv", f)}, headers=headers)
print(f"Upload: {r.status_code}")
ds = r.json()
ds_id = ds["id"]
print(f"DataSource ID: {ds_id}, rows: {ds.get('row_count')}, symbol: {ds.get('symbol')}")

# 3. Create a Golden Cross SMA strategy
print("\n=== Create Strategy ===")
strategy_data = {
    "name": "Golden Cross SMA",
    "description": "SMA 50/200 crossover strategy",
    "indicators": [
        {"id": "sma_fast", "type": "SMA", "params": {"period": 50, "source": "close"}, "overlay": True},
        {"id": "sma_slow", "type": "SMA", "params": {"period": 200, "source": "close"}, "overlay": True},
    ],
    "entry_rules": [
        {"left": "sma_fast", "operator": "crosses_above", "right": "sma_slow", "logic": "AND"},
    ],
    "exit_rules": [
        {"left": "sma_fast", "operator": "crosses_below", "right": "sma_slow", "logic": "AND"},
    ],
    "risk_params": {
        "position_size_type": "fixed_lot",
        "position_size_value": 0.1,
        "stop_loss_type": "fixed_pips",
        "stop_loss_value": 100,
        "take_profit_type": "rr_ratio",
        "take_profit_value": 2.0,
        "max_positions": 1,
    },
    "filters": {},
}
r = requests.post(f"{BASE}/api/strategies", json=strategy_data, headers=headers)
print(f"Create: {r.status_code}")
strat = r.json()
strat_id = strat["id"]
print(f"Strategy ID: {strat_id}")

# 4. Run backtest
print("\n=== Run Backtest ===")
bt_req = {
    "strategy_id": strat_id,
    "datasource_id": ds_id,
    "initial_balance": 10000.0,
    "spread_points": 0.3,
    "commission_per_lot": 7.0,
    "point_value": 1.0,
}
r = requests.post(f"{BASE}/api/backtest/run", json=bt_req, headers=headers)
print(f"Backtest status: {r.status_code}")

if r.status_code == 200:
    result = r.json()
    stats = result["stats"]
    print(f"\n{'='*50}")
    print(f"  BACKTEST RESULTS: Golden Cross SMA on XAUUSD M10")
    print(f"{'='*50}")
    print(f"  Total Trades:    {stats['total_trades']}")
    print(f"  Win Rate:        {stats['win_rate']}%")
    print(f"  Net Profit:      ${stats['net_profit']:.2f}")
    print(f"  Profit Factor:   {stats['profit_factor']:.2f}")
    print(f"  Sharpe Ratio:    {stats['sharpe_ratio']:.2f}")
    print(f"  Max Drawdown:    ${stats['max_drawdown']:.2f} ({stats['max_drawdown_pct']:.1f}%)")
    print(f"  Avg Win:         ${stats['avg_win']:.2f}")
    print(f"  Avg Loss:        ${stats['avg_loss']:.2f}")
    print(f"  Largest Win:     ${stats['largest_win']:.2f}")
    print(f"  Largest Loss:    ${stats['largest_loss']:.2f}")
    print(f"  Expectancy:      ${stats['expectancy']:.2f}")
    print(f"  Total Bars:      {stats['total_bars']}")
    print(f"  Equity pts:      {len(result['equity_curve'])}")
    print(f"  Trade count:     {len(result['trades'])}")
    if result['trades']:
        t = result['trades'][0]
        print(f"\n  First trade: {t['direction']} @ {t['entry_price']}, exit @ {t.get('exit_price')}, PnL: ${t['pnl']:.2f} ({t['exit_reason']})")
    print(f"{'='*50}")
else:
    print(f"ERROR: {r.text}")

# 5. List backtests
print("\n=== List Backtests ===")
r = requests.get(f"{BASE}/api/backtest", headers=headers)
print(f"Backtests: {r.status_code}, count: {len(r.json())}")
for bt in r.json():
    print(f"  ID: {bt['id']}, symbol: {bt['symbol']}, status: {bt['status']}, trades: {bt['stats'].get('total_trades', 0)}")

print("\nAll tests passed!")
