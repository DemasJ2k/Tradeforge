"""Live API endpoint testing - corrected paths."""
import requests
import json

BASE = "http://localhost:8000"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxNzcyNTEzODcyfQ.wr-pXNMsjEkEzUtR4Um_JoEqLiOyEeW-_3sUUkOo-7k"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

results = []

def test(name, method, path, expected_status=None, json_body=None, check_fn=None):
    url = f"{BASE}{path}"
    try:
        if method == "GET":
            r = requests.get(url, headers=HEADERS, timeout=15)
        elif method == "POST":
            r = requests.post(url, headers=HEADERS, json=json_body or {}, timeout=15)
        elif method == "PUT":
            r = requests.put(url, headers=HEADERS, json=json_body or {}, timeout=15)
        elif method == "DELETE":
            r = requests.delete(url, headers=HEADERS, timeout=15)
        
        status = r.status_code
        try:
            body = r.json()
        except:
            body = r.text[:300]
        
        passed = True
        notes = ""
        if expected_status and status != expected_status:
            passed = False
            notes = f"Expected {expected_status}, got {status}"
        if check_fn:
            try:
                check_fn(status, body)
            except Exception as e:
                passed = False
                notes = str(e)
        
        result = "PASS" if passed else "FAIL"
        results.append((name, result, status, notes, str(body)[:200]))
        symbol = "+" if passed else "X"
        print(f"  [{symbol}] {name} -> {status} {notes}")
    except Exception as e:
        results.append((name, "ERROR", 0, str(e), ""))
        print(f"  [!] {name} -> {str(e)[:80]}")

print("=" * 70)
print("TRADEFORGE LIVE API AUDIT - CORRECTED PATHS")
print("=" * 70)

# ── Health ──
print("\n--- Health ---")
test("Health", "GET", "/api/health", 200)

# ── Auth ──
print("\n--- Auth ---")
test("Auth/me", "GET", "/api/auth/me", 200)
test("Auth/admin/users", "GET", "/api/auth/admin/users", 200)

# ── Dashboard ──
print("\n--- Dashboard ---")
test("Dashboard/summary", "GET", "/api/dashboard/summary", 200,
     check_fn=lambda s, b: None if isinstance(b, dict) else (_ for _ in ()).throw(Exception(f"Not dict: {type(b)}")))

# ── Strategies ──
print("\n--- Strategies ---")
test("Strategies/list", "GET", "/api/strategies", 200,
     check_fn=lambda s, b: None if isinstance(b, dict) and "items" in b else (_ for _ in ()).throw(Exception(f"Missing items key")))

# ── DataSources ──
print("\n--- DataSources (correct: /api/data/sources) ---")
test("DataSources/list", "GET", "/api/data/sources", 200)

# ── Backtests ──
print("\n--- Backtests ---")
test("Backtest/list", "GET", "/api/backtest", 200)

# ── LLM ──
print("\n--- LLM ---")
test("LLM/conversations", "GET", "/api/llm/conversations", 200,
     check_fn=lambda s, b: None if isinstance(b, dict) and "items" in b else (_ for _ in ()).throw(Exception(f"Format: {type(b)} keys={list(b.keys()) if isinstance(b,dict) else 'N/A'}")))
test("LLM/memories", "GET", "/api/llm/memories", 200)
test("LLM/usage", "GET", "/api/llm/usage", 200)

# ── Knowledge ──
print("\n--- Knowledge (correct: /api/knowledge/articles) ---")
test("Knowledge/articles", "GET", "/api/knowledge/articles", 200)
test("Knowledge/categories", "GET", "/api/knowledge/categories", 200)

# ── Settings ──
print("\n--- Settings ---")
test("Settings/get", "GET", "/api/settings", 200)
test("Settings/broker-creds", "GET", "/api/settings/broker-credentials", 200)
test("Settings/storage", "GET", "/api/settings/storage", 200)

# ── Optimization ──
print("\n--- Optimization ---")
test("Optimize/list", "GET", "/api/optimize", 200)
test("Optimize/phase/chains", "GET", "/api/optimize/phase/chains", 200)

# ── ML ──
print("\n--- ML ---")
test("ML/models", "GET", "/api/ml/models", 200)
test("ML/features", "GET", "/api/ml/features", 200)

# ── Broker ──
print("\n--- Broker ---")
test("Broker/status", "GET", "/api/broker/status", 200)

# ── Market ──
print("\n--- Market ---")
test("Market/providers", "GET", "/api/market/providers", 200)
test("Market/symbols", "GET", "/api/market/symbols", 200)

# ── Agent ──
print("\n--- Agent ---")
test("Agent/list", "GET", "/api/agents", 200)

# ── WebSocket stats ──
print("\n--- WebSocket ---")
test("WS/stats", "GET", "/api/ws/stats", 200)

# ── Test data counts ──
print("\n--- Data Counts ---")
# Get datasource IDs for deeper testing
r = requests.get(f"{BASE}/api/data/sources", headers=HEADERS, timeout=10)
if r.status_code == 200:
    ds_data = r.json()
    if isinstance(ds_data, list):
        ds_count = len(ds_data)
    elif isinstance(ds_data, dict) and "items" in ds_data:
        ds_count = len(ds_data["items"])
    else:
        ds_count = 0
    print(f"  DataSources: {ds_count}")
else:
    print(f"  DataSources: ERROR {r.status_code}")

r = requests.get(f"{BASE}/api/strategies", headers=HEADERS, timeout=10)
if r.status_code == 200:
    s_data = r.json()
    s_count = len(s_data.get("items", [])) if isinstance(s_data, dict) else len(s_data)
    print(f"  Strategies: {s_count}")

r = requests.get(f"{BASE}/api/backtest", headers=HEADERS, timeout=10)
if r.status_code == 200:
    b_data = r.json()
    b_count = len(b_data) if isinstance(b_data, list) else len(b_data.get("items", []))
    print(f"  Backtests: {b_count}")

r = requests.get(f"{BASE}/api/optimize", headers=HEADERS, timeout=10)
if r.status_code == 200:
    o_data = r.json()
    o_count = len(o_data) if isinstance(o_data, list) else len(o_data.get("items", []))
    print(f"  Optimizations: {o_count}")

r = requests.get(f"{BASE}/api/ml/models", headers=HEADERS, timeout=10)
if r.status_code == 200:
    ml_data = r.json()
    ml_count = len(ml_data) if isinstance(ml_data, list) else len(ml_data.get("items", []))
    print(f"  ML Models: {ml_count}")

r = requests.get(f"{BASE}/api/agents", headers=HEADERS, timeout=10)
if r.status_code == 200:
    a_data = r.json()
    a_count = len(a_data) if isinstance(a_data, list) else len(a_data.get("items", []))
    print(f"  Agents: {a_count}")

# ── Deep tests on specific bugs ──
print("\n--- Deep Bug Verification ---")

# Bug: Dashboard .get() on dataclass / async issues
test("Dashboard/summary structure", "GET", "/api/dashboard/summary",
     check_fn=lambda s, b: None if s == 200 and isinstance(b, dict) and "strategy_count" in b else (_ for _ in ()).throw(Exception(f"Unexpected dashboard format: {list(b.keys()) if isinstance(b,dict) else b}")))

# Bug: backtest chart-data with existing backtest
r = requests.get(f"{BASE}/api/backtest", headers=HEADERS, timeout=10)
if r.status_code == 200:
    btests = r.json()
    if isinstance(btests, list) and len(btests) > 0:
        bt_id = btests[0]["id"]
        test(f"Backtest chart-data (id={bt_id})", "GET", f"/api/backtest/{bt_id}/chart-data")
    elif isinstance(btests, dict) and btests.get("items"):
        bt_id = btests["items"][0]["id"]
        test(f"Backtest chart-data (id={bt_id})", "GET", f"/api/backtest/{bt_id}/chart-data")
    else:
        print("  [SKIP] No backtests to test chart-data")

# ── Summary ──
print("\n" + "=" * 70)
print("FINAL AUDIT SUMMARY")
print("=" * 70)
pass_count = sum(1 for r in results if r[1] == "PASS")
fail_count = sum(1 for r in results if r[1] == "FAIL")
error_count = sum(1 for r in results if r[1] == "ERROR")
print(f"PASS: {pass_count}  |  FAIL: {fail_count}  |  ERROR: {error_count}  |  TOTAL: {len(results)}")

if fail_count or error_count:
    print("\n--- FAILURES ---")
    for name, result, status, notes, body in results:
        if result != "PASS":
            print(f"\n  [{result}] {name}")
            print(f"    HTTP {status} | {notes}")
            print(f"    Body: {body[:200]}")
