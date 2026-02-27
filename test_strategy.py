import urllib.request
import json

BASE = "http://localhost:8000"

def req(method, path, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else None
    r = urllib.request.Request(f"{BASE}{path}", data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(r)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "detail": json.loads(e.read().decode())}

# Login
r = req("POST", "/api/auth/login", {"username": "demas", "password": "password123"})
token = r["access_token"]
print(f"Logged in, token: {token[:20]}...")

# Create strategy
print("\n=== Create Strategy ===")
strat = req("POST", "/api/strategies", {
    "name": "Golden Cross SMA",
    "description": "Classic SMA crossover strategy",
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
        "stop_loss_type": "atr_multiple",
        "stop_loss_value": 2.0,
        "take_profit_type": "rr_ratio",
        "take_profit_value": 2.0,
        "max_positions": 1,
    },
    "filters": {
        "time_start": "08:00",
        "time_end": "20:00",
    },
}, token)
print(json.dumps(strat, indent=2))

# List strategies
print("\n=== List Strategies ===")
r = req("GET", "/api/strategies", token=token)
print(f"Total: {r['total']}, first: {r['items'][0]['name']}")

# Update
print("\n=== Update Strategy ===")
sid = strat["id"]
r = req("PUT", f"/api/strategies/{sid}", {"name": "Golden Cross SMA v2"}, token)
print(f"Updated name: {r['name']}")

# Duplicate
print("\n=== Duplicate Strategy ===")
r = req("POST", f"/api/strategies/{sid}/duplicate", token=token)
print(f"Duplicated: {r['name']} (id={r['id']})")

# Delete duplicate
print("\n=== Delete Duplicate ===")
r = req("DELETE", f"/api/strategies/{r['id']}", token=token)
print(r)

# Final list
print("\n=== Final List ===")
r = req("GET", "/api/strategies", token=token)
print(f"Total: {r['total']}")
for s in r["items"]:
    print(f"  - [{s['id']}] {s['name']}: {len(s['indicators'])} indicators, {len(s['entry_rules'])} entry rules")
