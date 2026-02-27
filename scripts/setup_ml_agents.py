"""
Setup script: Train ML models and create agents for MSS and Gold BT strategies.
"""
import requests
import time
import json

BASE = "http://localhost:8000/api"

def login():
    r = requests.post(f"{BASE}/auth/login", json={
        "username": "TradeforgeAdmin",
        "password": "Tradeforge2025!",
    })
    r.raise_for_status()
    return r.json()["access_token"]


def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def main():
    print("=" * 80)
    print("  TRADEFORGE — ML MODEL TRAINING & AGENT SETUP")
    print("=" * 80)

    token = login()
    h = headers(token)
    print("  Logged in successfully\n")

    # ─── Verify strategies ───
    r = requests.get(f"{BASE}/strategies", headers=h)
    strategies = r.json()["items"]
    print("  Strategies:")
    for s in strategies:
        if s["id"] in [2, 3]:
            print(f"    ID={s['id']}: {s['name']} (system={s['is_system']})")

    # ─── Verify datasources ───
    r = requests.get(f"{BASE}/data/sources", headers=h)
    datasources = r.json()
    items = datasources.get("items", []) if isinstance(datasources, dict) else datasources
    print("\n  Data Sources:")
    for ds in items:
        if isinstance(ds, dict) and ("XAUUSD" in ds.get("filename", "") or "XAUUSD" in ds.get("symbol", "")):
            print(f"    ID={ds['id']}: {ds.get('filename', '')} ({ds.get('symbol', '')} {ds.get('timeframe', '')})")

    # ─── Train ML Model for MSS Strategy ───
    print("\n" + "=" * 80)
    print("  TRAINING ML MODEL — MSS Strategy (XAUUSD M10)")
    print("=" * 80)

    mss_train = {
        "name": "MSS-XAUUSD-Signal-XGB",
        "level": 2,
        "model_type": "xgboost",
        "datasource_id": 6,  # XAUUSD M10
        "strategy_id": 2,    # MSS strategy
        "symbol": "XAUUSD",
        "timeframe": "M10",
        "features": [
            "returns", "volatility", "candle_patterns",
            "sma", "ema", "rsi", "atr", "macd",
            "bollinger", "adx", "stochastic", "volume"
        ],
        "target_type": "direction",
        "target_horizon": 5,
        "n_estimators": 200,
        "max_depth": 8,
        "learning_rate": 0.05,
        "train_ratio": 0.8,
    }

    print(f"  Submitting MSS training request...")
    r = requests.post(f"{BASE}/ml/train", headers=h, json=mss_train)
    if r.status_code in (200, 201):
        mss_model = r.json()
        print(f"  MSS Model created: ID={mss_model['id']}, Status={mss_model['status']}")
        print(f"  Training metrics: {json.dumps(mss_model.get('train_metrics', {}), indent=4)[:500]}")
        print(f"  Validation metrics: {json.dumps(mss_model.get('val_metrics', {}), indent=4)[:500]}")
        mss_model_id = mss_model["id"]
    else:
        print(f"  ERROR: {r.status_code} — {r.text[:300]}")
        mss_model_id = None

    # ─── Train ML Model for Gold BT Strategy ───
    print("\n" + "=" * 80)
    print("  TRAINING ML MODEL — Gold BT Strategy (XAUUSD M1)")
    print("=" * 80)

    gold_train = {
        "name": "GoldBT-XAUUSD-Signal-XGB",
        "level": 2,
        "model_type": "xgboost",
        "datasource_id": 5,  # XAUUSD M1
        "strategy_id": 3,    # Gold BT strategy
        "symbol": "XAUUSD",
        "timeframe": "M1",
        "features": [
            "returns", "volatility", "candle_patterns",
            "sma", "ema", "rsi", "atr", "macd",
            "bollinger", "stochastic", "volume"
        ],
        "target_type": "direction",
        "target_horizon": 10,
        "n_estimators": 200,
        "max_depth": 8,
        "learning_rate": 0.05,
        "train_ratio": 0.8,
    }

    print(f"  Submitting Gold BT training request...")
    r = requests.post(f"{BASE}/ml/train", headers=h, json=gold_train)
    if r.status_code in (200, 201):
        gold_model = r.json()
        print(f"  Gold BT Model created: ID={gold_model['id']}, Status={gold_model['status']}")
        print(f"  Training metrics: {json.dumps(gold_model.get('train_metrics', {}), indent=4)[:500]}")
        print(f"  Validation metrics: {json.dumps(gold_model.get('val_metrics', {}), indent=4)[:500]}")
        gold_model_id = gold_model["id"]
    else:
        print(f"  ERROR: {r.status_code} — {r.text[:300]}")
        gold_model_id = None

    # ─── List trained models ───
    print("\n" + "=" * 80)
    print("  TRAINED ML MODELS")
    print("=" * 80)
    r = requests.get(f"{BASE}/ml/models", headers=h)
    if r.status_code == 200:
        models = r.json()
        for m in models:
            acc = m.get("val_accuracy")
            acc_str = f"{acc:.1%}" if acc else "N/A"
            print(f"  ID={m['id']}: {m['name']} | {m['model_type']} | {m['status']} | Val Acc: {acc_str}")

    # ─── Create Agent for MSS Strategy ───
    print("\n" + "=" * 80)
    print("  CREATING TRADING AGENTS")
    print("=" * 80)

    mss_agent = {
        "name": "MSS-XAUUSD-Agent",
        "strategy_id": 2,
        "symbol": "XAUUSD",
        "timeframe": "M10",
        "broker_name": "mt5",
        "mode": "paper",
        "risk_config": {
            "max_daily_loss_pct": 3.0,
            "max_open_positions": 1,
            "max_drawdown_pct": 10.0,
            "position_size_type": "fixed_lot",
            "position_size_value": 0.01,
        },
    }

    print(f"  Creating MSS Agent...")
    r = requests.post(f"{BASE}/agents", headers=h, json=mss_agent)
    if r.status_code in (200, 201):
        agent = r.json()
        print(f"  MSS Agent created: ID={agent['id']}, Mode={agent['mode']}, Status={agent['status']}")
    else:
        print(f"  ERROR: {r.status_code} — {r.text[:300]}")

    # ─── Create Agent for Gold BT Strategy ───
    gold_agent = {
        "name": "GoldBT-XAUUSD-Agent",
        "strategy_id": 3,
        "symbol": "XAUUSD",
        "timeframe": "M1",
        "broker_name": "mt5",
        "mode": "paper",
        "risk_config": {
            "max_daily_loss_pct": 3.0,
            "max_open_positions": 1,
            "max_drawdown_pct": 10.0,
            "position_size_type": "fixed_lot",
            "position_size_value": 0.01,
        },
    }

    print(f"  Creating Gold BT Agent...")
    r = requests.post(f"{BASE}/agents", headers=h, json=gold_agent)
    if r.status_code in (200, 201):
        agent = r.json()
        print(f"  Gold BT Agent created: ID={agent['id']}, Mode={agent['mode']}, Status={agent['status']}")
    else:
        print(f"  ERROR: {r.status_code} — {r.text[:300]}")

    # ─── List all agents ───
    print("\n  All Agents:")
    r = requests.get(f"{BASE}/agents", headers=h)
    if r.status_code == 200:
        agents = r.json()
        for a in agents.get("items", agents):
            print(f"    ID={a['id']}: {a['name']} | {a['symbol']} {a['timeframe']} | Mode: {a['mode']} | Status: {a['status']}")

    print("\n" + "=" * 80)
    print("  SETUP COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
