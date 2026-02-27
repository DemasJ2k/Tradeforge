import sys
sys.path.insert(0, '.')
try:
    from app.core.websocket import manager
    print("websocket.py import: OK")
except Exception as e:
    print(f"websocket.py import ERROR: {e}")

try:
    from app.services.agent.engine import AlgoEngine
    print("engine.py import: OK")
except Exception as e:
    print(f"engine.py import ERROR: {e}")
