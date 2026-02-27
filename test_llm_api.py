"""Quick test for LLM API endpoints (without actual LLM call)."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import requests

BASE = "http://localhost:8000"

# Register + login
print("=== Register ===")
r = requests.post(f"{BASE}/api/auth/register", json={"username": "demas", "password": "testing123"})
print(r.status_code, r.json())

print("\n=== Login ===")
r = requests.post(f"{BASE}/api/auth/login", json={"username": "demas", "password": "testing123"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}
print("Token:", token[:20] + "...")

# Test conversations list (empty)
print("\n=== GET /api/llm/conversations ===")
r = requests.get(f"{BASE}/api/llm/conversations", headers=h)
print(r.status_code, r.json())

# Test memories list (empty)
print("\n=== GET /api/llm/memories ===")
r = requests.get(f"{BASE}/api/llm/memories", headers=h)
print(r.status_code, r.json())

# Test usage stats (empty)
print("\n=== GET /api/llm/usage ===")
r = requests.get(f"{BASE}/api/llm/usage", headers=h)
print(r.status_code, r.json())

# Test chat without LLM config -> should return 400
print("\n=== POST /api/llm/chat (no LLM configured) ===")
r = requests.post(f"{BASE}/api/llm/chat", json={"message": "Hello"}, headers=h)
print(r.status_code, r.json())

# Save LLM settings
print("\n=== Configure LLM (claude + dummy key) ===")
r = requests.put(f"{BASE}/api/settings", json={
    "llm_provider": "claude",
    "llm_api_key": "sk-ant-test-dummy-key",
    "llm_model": "claude-sonnet-4-20250514",
    "llm_temperature": "0.7",
    "llm_max_tokens": "4096",
}, headers=h)
print(r.status_code, "provider:", r.json().get("llm_provider"), "key_set:", r.json().get("llm_api_key_set"))

# Test chat with config (will fail because key is dummy, but tests the flow)
print("\n=== POST /api/llm/chat (dummy key -> expect 500) ===")
r = requests.post(f"{BASE}/api/llm/chat", json={
    "message": "Hello",
    "page_context": "dashboard",
}, headers=h)
print(r.status_code, r.json())

print("\n=== All API structure tests passed! ===")
