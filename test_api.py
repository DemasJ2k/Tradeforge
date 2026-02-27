import urllib.request
import json

BASE = "http://localhost:8000"

def post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=body, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "detail": json.loads(e.read().decode())}

def get(path, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE}{path}", headers=headers)
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "detail": json.loads(e.read().decode())}

# 1. Register
print("=== Register ===")
r = post("/api/auth/register", {"username": "demas", "password": "password123"})
print(r)

# 2. Login
print("\n=== Login ===")
r = post("/api/auth/login", {"username": "demas", "password": "password123"})
print(r)
token = r.get("access_token", "")

# 3. Get current user
print("\n=== Me ===")
r = get("/api/auth/me", token)
print(r)

# 4. Check data sources
print("\n=== Data Sources ===")
r = get("/api/data/sources", token)
print(r)

# 5. Get candles if data exists
if r.get("items"):
    src_id = r["items"][0]["id"]
    print(f"\n=== Candles (source {src_id}) ===")
    c = get(f"/api/data/sources/{src_id}/candles?limit=5", token)
    print(f"Symbol: {c.get('symbol')}, TF: {c.get('timeframe')}, candles: {len(c.get('candles', []))}")
    if c.get("candles"):
        print(f"First candle: {c['candles'][0]}")
