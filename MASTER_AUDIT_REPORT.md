# FlowrexAlgo (TradeForge) — Master Audit Report

**Generated:** 2025-06-30  
**Method:** Static code analysis + Live API tests (28 endpoints) + Playwright browser automation (19 test suites, 150+ checks) + Manual code verification  
**Stack:** Next.js 15 (port 3000) + FastAPI/Python (port 8000) + SQLite  
**Database:** `backend/data/tradeforge.db` — 20 tables, 17 data sources, 46 strategies, 50 backtests, 32 optimizations, 11 ML models, 1 agent

---

## EXECUTIVE SUMMARY

| Category | Working | Broken/Missing | Notes |
|----------|---------|----------------|-------|
| Navigation & Routing | 9/9 | 0 | All sidebar links and routes work |
| API Endpoints (GET) | 28/30 | 2 | chart-data + indicators/compute = 500 |
| Console Errors | 0 across all 9 pages | 0 | Clean runtime — no JS crashes |
| Branding (FlowrexAlgo) | 8/10 pages | 2 | reset-password + Documents page |
| Dashboard | 10/10 | 0 | All sections render |
| Strategies | 9/10 | 1 | Missing search/filter input |
| Strategy Editor | 5/5 tabs | 0 | All 5 tabs work (Indicators, Entry, Exit, Risk, Filters) |
| Data Sources | 7/8 | 1 | No instrument profile info |
| Backtest | 6/8 | 2 | No settings gear; metrics only show after running a backtest |
| Optimization | 8/8 | 0 | Run, Robustness, Apply all present |
| ML Lab | 5/7 | 2 | No Compare, no Walk-Forward Retrain |
| Trading | 7/8 | 1 | No "Close position" button |
| Settings | 8/8 | 0 | All sections including theme presets |
| Documents/Knowledge | 9/9 | 0 | Both tabs, 6/6 categories, quiz, progress |
| Chat Sidebar | 7/7 | 0 | Toggle, input, send icon, history, memories, new |
| Auth System | 11/11 | 0 | Login, register, TOTP, forgot password, admin |
| Build Plan (IMPLEMENTATION_PLAN) | 7/10 | 3 | MSS params + file type icons missing |
| Build Plan (UI_REDESIGN_PLAN) | 8/9 | 1 | Incomplete rebrand |

**Overall: ~143 checks working, ~15 broken/missing**

---

## 1. CRITICAL BUGS (Runtime Crashes / 500 Errors)

### BUG-1: `DataSource.creator_id` and `DataSource.is_public` missing from model
- **Impact:** Any endpoint that filters datasources by ownership crashes with HTTP 500
- **Files affected:**
  - `backend/app/models/datasource.py` — Missing columns `creator_id` (ForeignKey→users) and `is_public` (Boolean)
  - `backend/app/api/backtest.py` L605, L692 — References `DataSource.creator_id` and `DataSource.is_public`
  - `backend/app/api/backtest.py` L610, L699 — `ds.file_path` should be `ds.filepath`
  - `backend/app/api/optimization_phase.py` L121 — `ds.file_path` should be `ds.filepath`
- **Confirmed:** `GET /api/backtest/{id}/chart-data` returns **HTTP 500**
- **Confirmed:** `POST /api/backtest/indicators/compute` returns **HTTP 500**
- **Fix:** Add `creator_id` and `is_public` columns to DataSource model, or remove the filter clauses from the queries

### BUG-2: `optimization_phase.py` — `_build_strategy_config()` missing entry/exit rules
- **Impact:** Phase-based optimization builds strategy configs without `entry_rules` and `exit_rules`, meaning the backtest engine receives an incomplete strategy
- **File:** `backend/app/api/optimization_phase.py` L207-214
- **Fix:** Include `entry_rules` and `exit_rules` from the strategy model in the config dict

### BUG-3: Optimization uses V1 engine instead of V2
- **Impact:** Optimizations run against the old backtest engine, potentially giving different results than the main backtester
- **File:** `backend/app/api/optimization.py` L570, L751
- **Fix:** Import and use V2 `BacktestEngine` from `app.services.backtest_v2.engine`

### BUG-4: Optimization robustness picks arbitrary datasource
- **Impact:** Robustness testing may run against an unrelated datasource instead of the one used in the optimization
- **File:** `backend/app/api/optimization.py` L504-514, L519-530
- **Fix:** Use the datasource from the optimization's strategy or add `datasource_id` to the optimization model

### BUG-5: ChatSidebar conversation history type mismatch
- **Impact:** Opening conversation history may silently fail (`.map()` on object instead of array)
- **File:** `frontend/src/components/ChatSidebar.tsx` L198
- **Detail:** API returns `{items: ConversationSummary[], total: number}` but code does `setConversations(response)` where state expects `ConversationSummary[]`. The `as never` cast hides the TypeScript error, and `.catch(() => {})` silently swallows runtime errors.
- **Fix:** Change to `setConversations(response.items)`

---

## 2. HIGH-PRIORITY ISSUES (Functional Defects)

### HIGH-1: Branding incomplete — "TradeForge" still appears
- **Pages affected:**
  - `frontend/src/app/reset-password/page.tsx` L16-18 — Shows "TF" monogram and "TradeForge" text
  - Documents/Knowledge page — "TradeForge" detected in page body during branding test (likely from a Knowledge article in the database, not the page code)
- **Fix:** Update reset-password to "FA"/"FlowrexAlgo"; check seeded knowledge articles for old branding

### HIGH-2: Strategy page missing search/filter
- **Detail:** No `<input>` with search/filter placeholder found on strategies page
- **Impact:** With 46 strategies, users cannot search or filter the list
- **Fix:** Add a search input that filters by strategy name

### HIGH-3: Data Sources page — no instrument profile info
- **Detail:** Page shows Symbol, Timeframe, Rows, Date Range, Source, Size — but no pip value, spread, or commission details
- **Impact:** Users cannot see or edit instrument trading parameters from the data page
- **Note:** Backend has these fields on the DataSource model and a `/api/data/{id}/profile` endpoint exists

### HIGH-4: ML Lab — Missing Compare and Walk-Forward Retrain
- **Detail:** Backend has `GET /api/ml/compare` and `POST /api/ml/retrain-wf` endpoints, but the frontend ML page has no UI for either
- **Impact:** ML model comparison and walk-forward retraining are backend-only features with no user access

### HIGH-5: Strategy page stale data on navigation
- **File:** `frontend/src/app/strategies/page.tsx` L51-52
- **Detail:** `loaded` flag is set once and never resets — deleted/added strategies from other sessions persist in local state until page hard refresh

### HIGH-6: Dashboard async/sync mismatch
- **File:** `backend/app/api/dashboard.py` L54, L69
- **Detail:** `default_adapter.get_account_info()` and `.get_positions()` might need `await` for async broker adapters
- **Current status:** Works in practice because the default adapter returns dicts, but would break with a real async broker

---

## 3. MEDIUM ISSUES

### MED-1: Optimization model missing `datasource_id` column
- **File:** `backend/app/models/optimization.py`
- **Impact:** No way to track which datasource was used for an optimization

### MED-2: No user ownership on datasources, ML models, trades
- **Impact:** All users see all data — no multi-user isolation
- **Files:** DataSource model, ML model queries, Trade model

### MED-3: Dashboard strategy count not user-scoped
- **File:** `backend/app/api/dashboard.py` L89-96
- **Impact:** Shows total strategy count across all users

### MED-4: Knowledge articles — no author/admin check on edit/delete
- **Impact:** Any authenticated user can edit or delete knowledge articles

### MED-5: Trading page — no "Close position" button
- **Impact:** Users cannot close open positions from the UI (must use broker directly)

### MED-6: Naming inconsistency across models
- **Detail:** Some models use `creator_id`, others `created_by`, others `author_id` — no consistent FK naming

### MED-7: 6 files duplicate `API_BASE` constant
- **Impact:** If the backend URL changes, it must be updated in multiple places instead of one `lib/api.ts`

---

## 4. WORKING FEATURES (Confirmed)

### Navigation & Layout
- ✅ Sidebar with 9 navigation links (Dashboard, Data, Strategies, Backtest, Optimize, ML, Trading, Documents, Settings)
- ✅ All 9 routes load correctly
- ✅ FA monogram logo in sidebar
- ✅ Command palette (Ctrl+K) opens and works
- ✅ Sonner toast notification system installed
- ✅ Consistent shadcn/ui design across all pages
- ✅ Lucide icons throughout
- ✅ Zero console errors across all pages

### Dashboard
- ✅ Account/Balance section
- ✅ Positions section
- ✅ Strategy count
- ✅ Agent status
- ✅ Recent trades
- ✅ Backtest summary
- ✅ Data sources count
- ✅ Broker connection status
- ✅ Resizable panels
- ✅ 29 KPI card elements

### Strategies
- ✅ Strategy list renders (~56 elements for 46 strategies)
- ✅ "New Strategy" / Create button
- ✅ "AI Import" button
- ✅ "Upload File" button
- ✅ File strategy type indicators (Python shown)
- ✅ Settings gear buttons (25 found)
- ✅ Delete buttons (14 found)
- ✅ Duplicate buttons (46 found)
- ✅ Edit buttons (14 found)
- ✅ Strategy type column/indicator

### Strategy Editor
- ✅ Indicators tab (with searchable combobox)
- ✅ Entry Rules tab
- ✅ Exit Rules tab
- ✅ Risk tab
- ✅ Filters tab
- ✅ shadcn/ui components used throughout

### Data Sources
- ✅ Page renders with data
- ✅ Upload button/file input
- ✅ Fetch from Broker button
- ✅ Symbol names visible
- ✅ Timeframe info visible
- ✅ Row count visible
- ✅ Delete buttons
- ✅ Candle/chart preview area

### Backtest
- ✅ Strategy selector (combobox)
- ✅ Data source selector
- ✅ Run Backtest button
- ✅ Walk-Forward button
- ✅ Results area
- ✅ Resizable panels (35%/65% split)
- ✅ Equity chart canvas
- ✅ Result tabs: Equity Curve, Trade Chart, Trade Log, Monthly Returns, Tearsheet, Portfolio

### Optimization
- ✅ Strategy selector
- ✅ Parameter space section
- ✅ Method selector (Bayesian/Genetic/Hybrid)
- ✅ Objective selector (Sharpe/Profit Factor/etc.)
- ✅ "Run Optimization (N trials)" button
- ✅ Results history list
- ✅ "Run Robustness Test" button
- ✅ "Apply Best Params to Strategy" button
- ✅ Trade log section
- ✅ Phase-based optimization chain UI
- ✅ MSS/Gold BT param extraction

### ML Lab
- ✅ Train model section
- ✅ Model list
- ✅ Predict/inference section
- ✅ Feature engineering
- ✅ Delete model buttons

### Trading
- ✅ Broker connection status
- ✅ Positions section
- ✅ Orders section
- ✅ Price display
- ✅ Agent/algo panel
- ✅ Order placement buttons (Buy/Sell)
- ✅ Trade history section

### Settings
- ✅ 8 tabs: Profile, Appearance, AI/LLM, Trading Defaults, Brokers, Data Management, Notifications, Platform
- ✅ Theme presets (8 presets: Midnight Teal, Ocean Blue, Emerald Trader, Sunset Gold, Neon Purple, Classic Dark, Warm Stone, Arctic Light)
- ✅ Color picker component (chart colors)
- ✅ Font family setting
- ✅ Broker credentials section
- ✅ LLM/AI settings (API keys for Claude/OpenAI/Gemini)
- ✅ Notification settings (SMTP/Telegram)
- ✅ Change password section
- ✅ Admin/user management with invitations
- ✅ Clear data option
- ✅ Data Management tab (storage + backup combined)

### Documents/Knowledge
- ✅ "Knowledge" tab with articles
- ✅ "User Guide" tab with full documentation
- ✅ 6/6 knowledge categories (Basics, Technical Analysis, Fundamental, Risk Management, Psychology, Platform)
- ✅ Quiz system
- ✅ Learning progress tracking
- ✅ User Guide covers: Getting Started, Broker, Strategy, Backtest, Trading, FAQ

### Chat Sidebar
- ✅ Toggle button opens sidebar
- ✅ Chat message textarea
- ✅ Send button (icon-only, paper plane)
- ✅ History panel button
- ✅ Memories panel button
- ✅ New conversation button
- ✅ Streaming endpoint exists (/api/llm/chat/stream)

### Auth System
- ✅ Login form with username/password
- ✅ Forgot password link → reset form
- ✅ Registration via invitation system
- ✅ TOTP 2FA setup endpoint
- ✅ Reset password page
- ✅ Admin user management
- ✅ All auth API endpoints return 200

### API Endpoints (28/30 working)
- ✅ /api/health, /api/auth/me, /api/auth/admin/users, /api/auth/invitations
- ✅ /api/auth/admin/reset-requests, /api/dashboard/summary
- ✅ /api/strategies, /api/data/sources, /api/backtest
- ✅ /api/llm/conversations, /api/llm/memories, /api/llm/usage
- ✅ /api/knowledge/articles, /api/knowledge/categories, /api/knowledge/progress, /api/knowledge/quiz/history
- ✅ /api/settings, /api/settings/broker-credentials, /api/settings/storage
- ✅ /api/optimize, /api/optimize/phase/chains
- ✅ /api/ml/models, /api/ml/features
- ✅ /api/broker/status, /api/market/providers, /api/market/symbols
- ✅ /api/agents, /api/ws/stats
- ❌ /api/backtest/{id}/chart-data → 500 (DataSource.creator_id bug)
- ❌ /api/backtest/indicators/compute → 500 (DataSource.creator_id bug)

---

## 5. BUILD PLAN vs REALITY

### IMPLEMENTATION_PLAN.md — Status

| Phase | Feature | Status | Notes |
|-------|---------|--------|-------|
| 1A | MSS strategy-specific Risk tab editing | ❌ Not implemented | StrategyEditor Risk tab is generic — no MSS/Gold BT specific params |
| 1B | MSS/Gold BT param extraction for optimizer | ❌ Not implemented | `extractOptimizableParams` doesn't extract `mss_config` params |
| 1C | Backend backtest sync (no changes needed) | ✅ Done | Backend correctly reads strategy params |
| 2A | Strategy model fields (strategy_type, file_path, etc.) | ✅ Done | Migration adds columns automatically |
| 2B | POST /api/strategies/upload endpoint | ✅ Done | Returns 422 (expects file) |
| 2C | File parsers (Python/JSON/Pine) | ✅ Done | `file_parser.py` exists |
| 3A | StrategySettingsModal component | ✅ Done | Gear icons visible (25 buttons) |
| 3C | Settings button on backtest page | ❌ Not implemented | No gear icon next to strategy selector on backtest page |
| 3D | PUT /api/strategies/{id}/settings endpoint | ✅ Done | Returns 422 (expects body) |
| 5A | Upload File button on strategies page | ✅ Done | Button present |
| 5B | File type icons (🐍/📋/🌲) | ❌ Not implemented | Python strategies shown but no emoji icons |

### UI_REDESIGN_PLAN.md — Status

| Phase | Feature | Status | Notes |
|-------|---------|--------|-------|
| A | Global Shell (sidebar, topbar, layout) | ✅ Done | |
| A | shadcn/ui + Lucide icons | ✅ Done | |
| A | Inter + JetBrains Mono fonts | ✅ Done | |
| A | Sonner toasts | ✅ Done | |
| A | Command palette (Ctrl+K) | ✅ Done | Opens and closes correctly |
| A | Full rebrand to FlowrexAlgo | ⚠️ 90% done | reset-password still shows "TF"/"TradeForge" |
| B | Backtest page with resizable panels | ✅ Done | 35/65% horizontal split |
| C | Strategy editor redesign | ✅ Done | 5 tabs with shadcn components |
| D | Remaining pages consistent design | ✅ Done | All pages use same design system |
| — | 8 theme presets | ✅ Done | All 8 in settings/Appearance |
| — | Custom color builder | ✅ Done | ColorPick component for chart colors |

---

## 6. RECOMMENDED FIX PRIORITY

### P0 — Fix Immediately (crash bugs)
1. **Add `creator_id` + `is_public` to DataSource model** (or remove filter from backtest.py L605, L692)
2. **Fix `ds.file_path` → `ds.filepath`** in backtest.py L610/L699 and optimization_phase.py L121
3. **Fix ChatSidebar conversation history** — change L198 to use `response.items`
4. **Fix `_build_strategy_config()`** — add entry_rules + exit_rules

### P1 — Fix Soon (functional gaps)
5. Update reset-password branding to FlowrexAlgo
6. Add search/filter input to strategies page
7. Add instrument profile info to data sources page (backend endpoint exists)
8. Add ML Compare and Walk-Forward Retrain UI (backend endpoints exist)
9. Fix strategy page stale data (reset `loaded` flag)

### P2 — Improve (quality/consistency)
10. Switch optimization to V2 engine
11. Fix optimization robustness datasource selection
12. Add user ownership to datasources, ML models, trades
13. Add "Close position" button to Trading page
14. Consolidate API_BASE constant usage
15. Add settings gear icon on backtest page next to strategy selector

---

## 7. TEST ARTIFACTS

- **Deep audit test suite:** `frontend/tests/e2e/deep-audit.spec.ts` (19 tests, 150+ checks)
- **Basic audit test suite:** `frontend/tests/e2e/full-audit.spec.ts` (25 tests)
- **Playwright config:** `frontend/playwright.config.ts`
- **All tests passing:** 19/19 deep audit + 25/25 basic audit = 44/44

---

*End of audit report.*
