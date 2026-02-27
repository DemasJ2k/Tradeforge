@echo off
echo ========================================
echo   TradeForge - Starting Services
echo ========================================
echo.

:: Start backend
echo [1/2] Starting Python backend on :8000...
start "TradeForge Backend" cmd /k "cd /d D:\Doc\DATA\tradeforge\backend && python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000"

:: Wait a moment for backend to initialize
timeout /t 3 /nobreak >nul

:: Start frontend
echo [2/2] Starting Next.js frontend on :3000...
start "TradeForge Frontend" cmd /k "cd /d D:\Doc\DATA\tradeforge\frontend && npm run dev"

echo.
echo ========================================
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:3000
echo   API Docs: http://localhost:8000/docs
echo ========================================
echo.
echo Both services started. Close this window anytime.
pause
