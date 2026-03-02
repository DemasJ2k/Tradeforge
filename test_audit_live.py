"""Live API endpoint testing for TradeForge audit."""
import requests
import json
import time

BASE = "http://localhost:8000"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxNzcyNTEzODcyfQ.wr-pXNMsjEkEzUtR4Um_JoEqLiOyEeW-_3sUUkOo-7k"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

results = []

def test(name, method, path, expected_status=None, json_body=None, check_fn=None):
    url = f"{BASE}{path}"
    try:
        if method == "GET":
            r = requests.get(url, headers=HEADERS, timeout=10)
        elif method == "POST":
            r = requests.post(url, headers=HEADERS, json=json_body or {}, timeout=10)
        elif method == "PUT":
            r = requests.put(url, headers=HEADERS, json=json_body or {}, timeout=10)
        elif method == "DELETE":
            r = requests.delete(url, headers=HEADERS, timeout=10)
        
        status = r.status_code
        try:
            body = r.json()
        except:
            body = r.text[:200]
        
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
        results.append((name, result, status, notes, str(body)[:150]))
        print(f"  [{result}] {name} -> {status} {notes}")
    except Exception as e:
        results.append((name, "ERROR", 0, str(e), ""))
        print(f"  [ERROR] {name} -> {str(e)[:80]}")

print("=" * 70)
print("TRADEFORGE LIVE API AUDIT")
print("=" * 70)

# ── Health ──
print("\n--- Health ---")
test("Health check", "GET", "/api/health", 200)

# ── Auth ──
print("\n--- Auth ---")
test("Auth: me", "GET", "/api/auth/me", 200)
test("Auth: login bad creds", "POST", "/api/auth/login", 401, {"username": "bad", "password": "bad"})

# ── Dashboard ──
print("\n--- Dashboard ---")
test("Dashboard: summary", "GET", "/api/dashboard/summary", 200)

# ── Strategies ──
print("\n--- Strategies ---")
test("Strategies: list", "GET", "/api/strategies", 200)
test("Strategies: list check", "GET", "/api/strategies", check_fn=lambda s, b: None if isinstance(b, list) else (_ for _ in ()).throw(Exception(f"Expected list, got {type(b).__name__}")))

# ── DataSources ──
print("\n--- DataSources ---")
test("DataSources: list", "GET", "/api/datasources", 200)

# ── Backtests ──
print("\n--- Backtests ---")
test("Backtests: list", "GET", "/api/backtest", 200)

# ── LLM / Chat ──
print("\n--- LLM ---")
test("LLM: conversations", "GET", "/api/llm/conversations", 200)
test("LLM: conversations format", "GET", "/api/llm/conversations", 
     check_fn=lambda s, b: None if isinstance(b, dict) and "items" in b else (_ for _ in ()).throw(Exception(f"Expected dict with 'items', got: {type(b).__name__} keys={list(b.keys()) if isinstance(b,dict) else 'N/A'}")))
test("LLM: memories", "GET", "/api/llm/memories", 200)
test("LLM: usage", "GET", "/api/llm/usage", 200)

# ── Knowledge / Documents ──
print("\n--- Knowledge ---")
test("Knowledge: list", "GET", "/api/knowledge", 200)

# ── Settings ──
print("\n--- Settings ---")
test("Settings: get", "GET", "/api/settings", 200)
test("Settings: broker config", "GET", "/api/settings/broker", 200)
test("Settings: llm config", "GET", "/api/settings/llm", 200)

# ── Optimization ──
print("\n--- Optimization ---")
test("Optimization: list", "GET", "/api/optimize", 200)

# ── ML ──  
print("\n--- ML ---")
test("ML: models list", "GET", "/api/ml/models", 200)
test("ML: predictions list", "GET", "/api/ml/predictions", 200)

# ── Broker ──
print("\n--- Broker ---")
test("Broker: status", "GET", "/api/broker/status", 200)

# ── Market ──
print("\n--- Market ---")
test("Market: status", "GET", "/api/market/status")

# ── Agent ──
print("\n--- Agent ---")
test("Agent: list", "GET", "/api/agent")

# ── WebSocket ──
print("\n--- WebSocket ---")
test("WebSocket: endpoint exists check", "GET", "/api/ws")

# ── Summary ──
print("\n" + "=" * 70)
print("AUDIT SUMMARY")
print("=" * 70)
pass_count = sum(1 for r in results if r[1] == "PASS")
fail_count = sum(1 for r in results if r[1] == "FAIL")
error_count = sum(1 for r in results if r[1] == "ERROR")
print(f"PASS: {pass_count}  |  FAIL: {fail_count}  |  ERROR: {error_count}  |  TOTAL: {len(results)}")

if fail_count or error_count:
    print("\n--- Failed/Error Details ---")
    for name, result, status, notes, body in results:
        if result != "PASS":
            print(f"\n  [{result}] {name}")
            print(f"    Status: {status}")
            print(f"    Notes: {notes}")
            print(f"    Body: {body}")
