"""Test settings API."""
import requests
BASE = "http://localhost:8000"

# Register + Login
requests.post(f"{BASE}/api/auth/register", json={"username": "demas", "password": "password123"})
r = requests.post(f"{BASE}/api/auth/login", json={"username": "demas", "password": "password123"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# GET default settings
print("=== GET settings (defaults) ===")
r = requests.get(f"{BASE}/api/settings", headers=h)
print(f"Status: {r.status_code}")
s = r.json()
print(f"  theme={s['theme']}, accent={s['accent_color']}, llm_key_set={s['llm_api_key_set']}")
print(f"  balance={s['default_balance']}, spread={s['default_spread']}")

# PUT update some settings
print("\n=== PUT update settings ===")
r = requests.put(f"{BASE}/api/settings", json={
    "display_name": "Demas",
    "theme": "dark",
    "accent_color": "orange",
    "llm_provider": "claude",
    "llm_api_key": "sk-ant-test-key-12345",
    "llm_model": "claude-sonnet-4-20250514",
    "default_balance": "50000",
    "default_risk_pct": "1.5",
    "preferred_instruments": "XAUUSD,EURUSD,BTCUSD",
    "preferred_timeframes": "M10,H1,H4",
    "csv_retention_days": 90,
    "notifications": {"backtest": True, "optimize": True, "trade": True},
}, headers=h)
print(f"Status: {r.status_code}")
s = r.json()
print(f"  display_name={s['display_name']}, accent={s['accent_color']}")
print(f"  llm_provider={s['llm_provider']}, llm_key_set={s['llm_api_key_set']}, model={s['llm_model']}")
print(f"  balance={s['default_balance']}, risk={s['default_risk_pct']}")
print(f"  instruments={s['preferred_instruments']}")
print(f"  csv_retention={s['csv_retention_days']} days")

# GET again to verify persistence
print("\n=== GET settings (after update) ===")
r = requests.get(f"{BASE}/api/settings", headers=h)
s = r.json()
print(f"  display_name={s['display_name']}, llm_key_set={s['llm_api_key_set']}")
assert s["display_name"] == "Demas"
assert s["llm_api_key_set"] == True
assert s["default_balance"] == "50000"

# Storage info
print("\n=== Storage Info ===")
r = requests.get(f"{BASE}/api/settings/storage", headers=h)
print(f"Status: {r.status_code}")
print(f"  {r.json()}")

# Change password
print("\n=== Change Password ===")
r = requests.post(f"{BASE}/api/settings/change-password", json={
    "current_password": "password123",
    "new_password": "newpass456",
}, headers=h)
print(f"Status: {r.status_code}, {r.json()}")

# Verify new password works
r = requests.post(f"{BASE}/api/auth/login", json={"username": "demas", "password": "newpass456"})
print(f"Login with new password: {r.status_code}")
assert r.status_code == 200

# Revert password
token2 = r.json()["access_token"]
h2 = {"Authorization": f"Bearer {token2}"}
r = requests.post(f"{BASE}/api/settings/change-password", json={
    "current_password": "newpass456",
    "new_password": "password123",
}, headers=h2)

print("\nAll settings tests passed!")
