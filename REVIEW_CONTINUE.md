# FlowrexAlgo Review — Continuation Instructions

**For the next Claude session. Read this file first.**

## Context
A comprehensive app review was performed on 2026-03-04. About 80% complete.
Full findings are in: `D:\Doc\DATA\tradeforge\REVIEW_REPORT.md`

## What Was Already Tested
All 9 pages were visually inspected and most interactive features tested:
- Dashboard, Data, Strategies, Backtest, Optimize, ML Lab, Trading, Knowledge, Settings
- AI Chat sidebar (send message, memories, chat history)
- Strategy CRUD, visual editor, AI import modal
- Trading chart (candles, MA/EMA/MACD indicators, timeframes)
- Agent create/edit, order modal, trade history
- Knowledge articles + quizzes
- All 8 settings tabs + theme switching

## What Still Needs Testing
1. **Backtest results display** — fix BUG-1 first (`DataSource.creator_id`), then verify chart + metrics render
2. **Walk-Forward analysis** — click the Walk-Forward button and test
3. **Optimize page** — run an actual optimization, verify WebSocket progress + results
4. **ML Lab training** — click Train New Model, verify the pipeline
5. **Data CSV upload** — drag/drop a CSV file
6. **Fetch from Broker** — submit MT5 fetch request
7. **Strategy Builder form mode** — create a strategy via form fields (not visual editor)
8. **AI Import execution** — upload a .pine/.txt file and run Generate Strategy
9. **Settings persistence** — change settings, refresh, verify they persist
10. **Auth flow** — logout/login, JWT handling
11. **2FA setup** — Enable 2FA button, TOTP flow
12. **Global search (Ctrl+K)** — search strategies and data sources
13. **Export CSV** — Data Management export
14. **Notifications** — verify toast notifications

## Bugs Found (Need Fixing)
See `REVIEW_REPORT.md` for full details. Priority order:
1. `backtest.py:605,692` — change `DataSource.creator_id` to correct column name
2. `ChatSidebar.tsx:428` — fix `conversations.map` (API returns object not array)
3. Backend CSV parser — symbol extraction from filenames with leading timestamps
4. Trading page polling — reduce from ~5 req/s to reasonable interval
5. New Order modal — default symbol to match chart symbol
6. Data source 0 MB size display
7. `broker-auto-connect` on every navigation

## How to Resume Testing
1. Start dev servers (both already in `.claude/launch.json`):
   - Backend: `preview_start("backend")`
   - Frontend: `preview_start("frontend")`
2. Navigate to the page being tested via `preview_click` on sidebar links
3. Use `preview_eval` for complex React interactions (React state dispatch needed for AI chat)
4. Use `preview_network` to monitor API calls
5. Use `preview_logs(serverId, {search: "error"})` to check backend errors

## User Preferences
- User implements frontend UI changes himself in VS Code
- User wants Claude to identify and report issues, not necessarily fix them all
- User asked for a comprehensive review of every function
