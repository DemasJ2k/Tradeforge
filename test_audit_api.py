import requests, json

BASE = 'http://localhost:8000'

# 1. Health check
r = requests.get(f'{BASE}/api/health')
print(f'1. Health: {r.status_code} - {r.json()}')

# 2. Login to get token
r = requests.post(f'{BASE}/api/auth/login', json={'username': 'TradeforgeAdmin', 'password': 'admin123'})
if r.status_code == 200:
    token = r.json().get('access_token')
    print(f'2. Login: OK (token={token[:20]}...)')
else:
    print(f'2. Login: FAILED {r.status_code} - {r.text}')
    token = None

if not token:
    exit(1)

h = {'Authorization': f'Bearer {token}'}

# 3. Dashboard summary
r = requests.get(f'{BASE}/api/dashboard/summary', headers=h)
print(f'3. Dashboard summary: {r.status_code}')
if r.status_code == 200:
    d = r.json()
    bal = d.get("balance")
    pos = d.get("positions")
    print(f'   balance={bal}, positions={pos}')
else:
    err = r.text[:200]
    print(f'   ERROR: {err}')

# 4. List strategies
r = requests.get(f'{BASE}/api/strategies', headers=h)
cnt = len(r.json()) if r.status_code == 200 else "ERR"
print(f'4. Strategies: {r.status_code} - count={cnt}')

# 5. List datasources
r = requests.get(f'{BASE}/api/data/sources', headers=h)
cnt = len(r.json()) if r.status_code == 200 else "ERR"
print(f'5. Data sources: {r.status_code} - count={cnt}')

# 6. List backtests
r = requests.get(f'{BASE}/api/backtest', headers=h)
cnt = len(r.json()) if r.status_code == 200 else "ERR"
print(f'6. Backtests: {r.status_code} - count={cnt}')

# 7. LLM conversations
r = requests.get(f'{BASE}/api/llm/conversations', headers=h)
print(f'7. LLM conversations: {r.status_code}')
if r.status_code == 200:
    data = r.json()
    dtype = type(data).__name__
    if isinstance(data, dict):
        print(f'   type=dict, keys={list(data.keys())}')
    else:
        print(f'   type={dtype}, len={len(data)}')
else:
    print(f'   ERROR: {r.text[:200]}')

# 8. Agents
r = requests.get(f'{BASE}/api/agents', headers=h)
cnt = len(r.json()) if r.status_code == 200 else "ERR"
print(f'8. Agents: {r.status_code} - count={cnt}')

# 9. ML models
r = requests.get(f'{BASE}/api/ml/models', headers=h)
cnt = len(r.json()) if r.status_code == 200 else "ERR"
print(f'9. ML models: {r.status_code} - count={cnt}')

# 10. Optimizations
r = requests.get(f'{BASE}/api/optimize', headers=h)
cnt = len(r.json()) if r.status_code == 200 else "ERR"
print(f'10. Optimizations: {r.status_code} - count={cnt}')

# 11. Test compute indicators (known broken endpoint)
r = requests.post(f'{BASE}/api/backtest/indicators/compute', headers=h, json={
    'datasource_id': 1, 
    'indicators': [{'name': 'SMA', 'params': {'period': 20}}]
})
print(f'11. Compute indicators: {r.status_code}')
if r.status_code != 200:
    print(f'    ERROR: {r.text[:300]}')

# 12. Test chart-data (known broken endpoint)
backtests = requests.get(f'{BASE}/api/backtest', headers=h).json()
if backtests:
    bt_id = backtests[0]['id']
    r = requests.get(f'{BASE}/api/backtest/{bt_id}/chart-data', headers=h)
    print(f'12. Chart data (bt={bt_id}): {r.status_code}')
    if r.status_code != 200:
        print(f'    ERROR: {r.text[:300]}')
else:
    print('12. Chart data: SKIP (no backtests)')

# 13. Knowledge
r = requests.get(f'{BASE}/api/knowledge/articles', headers=h)
cnt = len(r.json()) if r.status_code == 200 else "ERR"
print(f'13. Knowledge articles: {r.status_code} - count={cnt}')

# 14. Settings
r = requests.get(f'{BASE}/api/settings', headers=h)
print(f'14. Settings: {r.status_code}')

# 15. Knowledge progress
r = requests.get(f'{BASE}/api/knowledge/progress', headers=h)
print(f'15. Knowledge progress: {r.status_code}')

# 16. Broker status
r = requests.get(f'{BASE}/api/broker/status', headers=h)
print(f'16. Broker status: {r.status_code}')

# 17. Market providers
r = requests.get(f'{BASE}/api/market/providers', headers=h)
print(f'17. Market providers: {r.status_code}')

print("\n=== DONE ===")
