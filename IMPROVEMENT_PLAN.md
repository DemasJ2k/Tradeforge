# FlowrexAlgo — 6 Improvements Plan

**Date**: 2026-03-08
**Status**: Approved by user — ready for implementation
**Backend tier**: Standard ($25/mo — 2GB RAM, 1 CPU)

---

## Current State Summary

| Feature | Status | Notes |
|---------|--------|-------|
| Pre-Trade Prop Firm Validation | 90% done | Validator exists, agent integration done. Needs API endpoint hardening + UI feedback |
| Strategy AI Import | 95% done | Pine/PDF/AI-generate all work. Needs error handling polish |
| Performance Optimization | 40% done | Frontend pagination exists. Backend needs API pagination, bar limits, caching |
| UI Polish & Production Hardening | 60% done | Core flows work. Needs error boundaries, loading states, mobile fixes |
| Onboarding Flow | 0% done | No onboarding exists — new users see empty dashboard |
| Live Dashboard Widgets | 50% done | Dashboard exists with static data. Needs live price feeds, P&L tracking, agent activity |

---

## 1. Pre-Trade Prop Firm Validation

**What exists**: `validator.py` with 7 checks (status, symbol, positions, lots, hours, daily loss, drawdown). Already integrated into `AgentRunner._evaluate_signal()` at lines 530-553. API endpoint has basic loss projection.

**What's needed**:

### 1A. Enhanced API Pre-Trade Check
- Add `POST /api/prop-firms/{id}/validate-trade` endpoint for manual/external validation
- Return structured response: `{ allowed: bool, reason: string, projected_daily_loss: float, projected_drawdown: float, remaining_daily_budget: float }`
- Useful for: frontend preview before manual trade, webhook integrations

### 1B. Weekend Holding Check
- Current `no_weekend_holding` flag exists in model but validator doesn't enforce it
- Add check: if `no_weekend_holding=True` and it's Friday after 21:00 UTC, block new trades
- Add auto-close warning for positions open near Friday close

### 1C. News Trading Filter
- Current `no_news_trading` flag exists but no enforcement
- Add basic implementation: block trades 30min before/after high-impact news
- Data source: Free ForexFactory calendar API or static schedule

### 1D. UI Feedback
- When agent logs "Trade blocked by prop firm rules: {reason}", show toast notification in frontend
- Add "Pre-Trade Check" button in prop firm account detail page
- Show remaining daily loss budget as a progress bar

**Estimated effort**: 3-4 hours
**Files**: `backend/app/services/prop_firm/validator.py`, `backend/app/api/prop_firm.py`, `frontend/src/app/prop-firm/`

---

## 2. Strategy AI Import (Polish)

**What exists**: Full pipeline — file upload (.py, .json, .pine), AI-generate from PDF/text/PineScript, LLM-powered strategy parsing via `ai_parser.py`.

**What's needed**:

### 2A. Error Handling & Validation
- Pine Script parser sometimes fails silently — add structured error messages
- Validate generated strategy JSON before saving (ensure indicators/rules are well-formed)
- Show conversion preview before saving (let user edit generated JSON)

### 2B. Strategy Templates
- Add 5 pre-built strategy templates users can start from:
  1. SMA Crossover (basic trend following)
  2. RSI Mean Reversion (counter-trend)
  3. Bollinger Band Breakout
  4. MACD + RSI Confirmation
  5. ATR Trailing Stop Momentum
- Each template: pre-filled indicators, entry/exit rules, risk params

### 2C. Natural Language Strategy Builder
- Enhance the existing AI prompt flow to accept plain English:
  "Buy when RSI drops below 30 and price is above SMA 200, sell when RSI goes above 70"
- LLM converts to strategy JSON with proper indicator configs and rule definitions
- Preview before save

**Estimated effort**: 3-4 hours
**Files**: `backend/app/services/strategy/ai_parser.py`, `backend/app/api/strategy.py`, `frontend/src/app/strategies/page.tsx`

---

## 3. Performance Optimization

**What exists**: Frontend pagination (client-side, 20/page). Backend hard limits on queries (50 backtests, 5 datasources). Async backtest to avoid Render timeout.

**What's needed**:

### 3A. API Pagination
- Add cursor-based pagination to heavy endpoints:
  - `GET /api/backtest` — paginate backtest history (currently returns all)
  - `GET /api/prop-firms/{id}/trades` — paginate trade history
  - `GET /api/strategies` — paginate if >50 strategies
- Response format: `{ items: [...], next_cursor: string, total: number }`

### 3B. Backtest Bar Limits & Downsampling
- Cap maximum bars sent to backtest engine (e.g., 500k bars max)
- For walk-forward with very large datasets: downsample to reasonable size
- Add bar count display in frontend before running backtest

### 3C. Database Query Optimization
- Add indexes on frequently queried columns:
  - `backtests.creator_id` + `backtests.created_at` (history queries)
  - `prop_firm_trades.account_id` + `prop_firm_trades.status` (open trade counts)
  - `agents.creator_id` + `agents.is_active` (active agent listing)
- Use `select_from()` for join-heavy queries

### 3D. Frontend Lazy Loading
- Lazy load heavy components: Backtest charts, equity curves, trade tables
- Add skeleton loaders for dashboard cards
- Debounce search inputs (strategy search, trade search)

### 3E. Response Compression
- Enable gzip compression on FastAPI responses
- Compress large equity curves (currently sending 2000+ floats)

**Estimated effort**: 4-5 hours
**Files**: Multiple API endpoints, `backend/main.py` (compression), frontend components

---

## 4. UI Polish & Production Hardening

### 4A. Error Boundaries
- Add React error boundary wrapper for each page section
- Graceful fallback UI when a component crashes (instead of white screen)
- Toast notifications for API errors (currently some errors are swallowed)

### 4B. Loading States
- Add loading skeletons for:
  - Dashboard cards (currently flash on load)
  - Strategy list
  - Backtest history table
  - Prop firm account list
- Replace bare "Loading..." text with animated spinners/skeletons

### 4C. Mobile Responsiveness
- Test and fix responsive layout on:
  - Dashboard (cards should stack on mobile)
  - Backtest page (chart + controls layout)
  - Strategy builder (rule editor needs mobile-friendly inputs)
  - Sidebar navigation (hamburger menu for mobile)

### 4D. Form Validation
- Client-side validation for all forms:
  - Strategy builder: validate indicator params (period > 0, etc.)
  - Prop firm account: validate rule values (percentages 0-100)
  - Backtest config: validate date ranges, bar counts
- Show inline validation errors (not just toast)

### 4E. Session & Auth Hardening
- Token refresh flow (currently token expires silently)
- Redirect to login on 401 responses
- Remember last visited page after login
- Rate limiting on auth endpoints (prevent brute force)

### 4F. Logging & Monitoring
- Structured logging in backend (JSON format for Render log parsing)
- Add request timing middleware
- Track backtest durations and notify if consistently >60s

**Estimated effort**: 6-8 hours
**Files**: Frontend components across all pages, `backend/main.py`, middleware

---

## 5. Onboarding Flow

**What exists**: Nothing — new users see empty dashboard after signup.

### 5A. Welcome Wizard (First Login)
- Detect first login (no strategies, no data sources)
- Show 3-step wizard:
  1. **Welcome**: Brief intro to FlowrexAlgo capabilities
  2. **Data Setup**: Upload CSV or fetch from broker (with preloaded demo data option)
  3. **First Strategy**: Choose from templates OR import existing
- Skip button always available
- Store `onboarding_completed` flag in user preferences

### 5B. Empty State CTAs
- Each page should have helpful empty states (not just blank):
  - Dashboard: "No agents running — create your first strategy to get started"
  - Strategies: "No strategies yet — import one or use a template"
  - Data: "Upload market data to begin backtesting" (already done)
  - Backtest: "Select a strategy and data source to run your first backtest"
  - Prop Firm: "Track your prop firm challenge — add an account to start"

### 5C. Demo Data Bundle
- Pre-load a demo dataset (XAUUSD H1, 1 year) on account creation
- Include 2-3 system strategies that work with the demo data
- Let user run a backtest immediately after signup

### 5D. Guided Tour (Optional)
- Add tooltip-based tour highlighting key UI elements
- Use a lightweight library (e.g., react-joyride or custom)
- Triggered by "Take a Tour" button in navbar
- 8-10 steps covering: sidebar nav, strategy builder, backtest, data, agents

**Estimated effort**: 5-6 hours
**Files**: New `frontend/src/components/Onboarding/`, `frontend/src/app/page.tsx`, backend user preferences

---

## 6. Live Dashboard Widgets

**What exists**: Dashboard shows static data fetched on page load — account balance, positions, agents, recent trades. No real-time updates.

### 6A. Live P&L Ticker
- Real-time unrealized P&L display on dashboard
- Updates every 5s via polling (or WebSocket if broker connected)
- Shows: current equity, daily P&L, daily P&L %, unrealized P&L per position
- Color-coded: green for profit, red for loss

### 6B. Agent Activity Feed
- Live feed showing agent actions in real-time:
  - "Agent #3 opened BUY XAUUSD @ 2345.50"
  - "Agent #1 SL hit on US30 — closed @ -$45.20"
  - "Agent #2 signal blocked by prop firm rules"
- Scrollable feed with timestamps
- Filter by agent or all agents

### 6C. Mini Equity Chart
- Small inline chart on dashboard showing account equity over last 30 days
- Uses lightweight-charts or a simple SVG line chart
- Click to expand to full backtest/equity page

### 6D. Market Overview Widget
- Show current prices for watched symbols (from broker connection or free API)
- Display: symbol, last price, daily change %, mini sparkline
- Configurable watchlist (user picks symbols)

### 6E. Prop Firm Status Cards
- For users with prop firm accounts: show daily loss remaining, drawdown status, days left
- Progress bars: profit target progress, daily loss consumed
- Alert badge when approaching limits (>80% of daily loss used)

### 6F. Auto-Refresh
- Dashboard auto-refreshes every 30s (configurable)
- Visual indicator when data is stale
- Manual refresh button with "Last updated: X seconds ago"

**Estimated effort**: 6-8 hours
**Files**: `frontend/src/app/page.tsx`, new widget components, `backend/app/api/dashboard.py`

---

## Implementation Priority & Order

```
Phase 1 — Quick wins (Day 1):
  ├── 3A. API Pagination (high-impact, prevents crashes on large datasets)
  ├── 4A-4B. Error boundaries + loading skeletons (user experience)
  └── 1A. Pre-trade validation endpoint

Phase 2 — User Experience (Day 2):
  ├── 5A-5C. Onboarding wizard + empty states + demo data
  ├── 2B. Strategy templates (helps new users)
  └── 4C. Mobile responsiveness

Phase 3 — Live Features (Day 3):
  ├── 6A-6B. Live P&L ticker + agent activity feed
  ├── 6E-6F. Prop firm status cards + auto-refresh
  └── 1B-1D. Weekend/news filters + UI feedback

Phase 4 — Polish (Day 4):
  ├── 3B-3E. Performance (bar limits, indexes, compression)
  ├── 4D-4F. Form validation, auth hardening, logging
  ├── 2A,2C. AI import polish + natural language builder
  └── 6C-6D. Mini equity chart + market overview
```

**Total estimated effort**: 25-30 hours across all 6 features

---

## Notes for Implementation

- All changes should be tested locally before pushing to GitHub
- Backend changes deploy automatically via Render (push to main)
- Frontend changes also auto-deploy (push to main)
- User prefers Skye to handle everything end-to-end
- User wants to be consulted on design decisions ("always ask me extra questions")
- CMD shell: use `git commit -F commit_msg.txt` for multi-line messages
