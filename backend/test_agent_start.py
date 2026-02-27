"""Start agent #18 using existing JWT token."""
import requests
import time

BASE = "http://localhost:8000"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxNzcyMTk4Mjg2fQ.blNmteh4F8hHAgQip4W15s1ynXAfhGhOuk-y356KfAE"
headers = {"Authorization": f"Bearer {TOKEN}"}

print("Starting agent #18...")
r = requests.post(f"{BASE}/api/agents/18/start", headers=headers)
print(f"Start: {r.status_code} - {r.text[:300]}")

print("\nWaiting 8 seconds for agent to initialize...")
time.sleep(8)

r = requests.get(f"{BASE}/api/agents/18/logs?limit=15", headers=headers)
print(f"\nAgent #18 recent logs ({r.status_code}):")
for log in r.json().get("items", []):
    print(f"  [{log['level']}] {log['created_at']} - {log['message']}")
