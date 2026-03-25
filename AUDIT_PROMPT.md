# Tradeforge — Full Platform Audit Prompt

> **Instructions for Claude**: Copy everything below this line and paste it into Claude Desktop as a single prompt.

---

You are performing a **comprehensive, exhaustive audit** of the Tradeforge trading platform. This is a full-stack algorithmic trading platform with ML-powered agents, multi-broker integrations, and a Next.js frontend. Your job is to go through **every single file, folder, route, component, model, agent, and connection** — leaving nothing unchecked.

**Both the backend (FastAPI, port 8000) and frontend (Next.js, port 3000) are already running.** You can make live HTTP requests to test endpoints.

---

## PHASE 1: Codebase Discovery & Understanding

Before finding bugs, you must fully understand the system. Go through every folder and file systematically:

### 1.1 — Project Structure
- Read `DEVLOG.md` and `CLAUDE.md` for context on recent changes and conventions
- Map out the complete directory tree for `backend/` and `frontend/src/`
- Identify all entry points: `backend/app/main.py`, `frontend/src/app/layout.tsx`, `frontend/src/app/page.tsx`

### 1.2 — Backend Architecture (FastAPI + Python)
Read and understand every file in:
- **API routes** (`backend/app/api/`): `agent.py`, `auth.py`, `backtest.py`, `broadcast.py`, `broker.py`, `ctrader_oauth.py`, `dashboard.py`, `datasource.py`, `health.py`, `llm.py`, `market.py`, `ml.py`, `optimization.py`, `optimization_phase.py`, `portfolio.py`, `prop_firm.py`, `recycle_bin.py`, `settings.py`, `strategy.py`, `telegram_webhook.py`, `webhook.py`, `websocket.py`
- **Database models** (`backend/app/models/`): `agent.py`, `backtest.py`, `broadcast.py`, `datasource.py`, `invitation.py`, `knowledge.py`, `llm.py`, `ml.py`, `news.py`, `optimization.py`, `optimization_phase.py`, `password_reset.py`, `portfolio.py`, `prop_firm.py`, `settings.py`, `strategy.py`, `trade.py`, `user.py`, `watchlist.py`
- **Schemas** (`backend/app/schemas/`)
- **Core** (`backend/app/core/`): config, auth, database setup
- **Services**:
  - Broker adapters (`backend/app/services/broker/`): `oanda.py`, `ctrader.py`, `coinbase.py`, `tradovate.py`, `mt5_bridge.py`, `mt5_remote.py`, `manager.py`, `base.py`
  - Agent system (`backend/app/services/agent/`): `engine.py`, `scalping_agent.py`, `expert_agent.py`, `risk_manager.py`, `portfolio_manager.py`, `trade_monitor.py`, `broker_reconciler.py`, `instrument_specs.py`, `ml_filter.py`, `mss_evaluator.py`, `gold_bt_evaluator.py`, `rl_agent.py`, `rl_signal_filter.py`, `rl_performance_monitor.py`
  - ML pipeline (`backend/app/services/ml/`): `trainer.py`, `features.py`, `features_mtf.py`, `ensemble_engine.py`, `lstm_forecaster.py`, `meta_labeler.py`, `regime_detector.py`, `feature_selector.py`, `exporter.py`, `market_structure.py`, `rl_environment.py`, `rl_trainer.py`
  - Backtest engine (`backend/app/services/backtest/`)
  - Other: `llm/`, `news/`, `strategy/`, `optimize/`, `market/`, `prop_firm/`

### 1.3 — Frontend Architecture (Next.js + TypeScript + Tailwind + shadcn/ui)
Read and understand every file in:
- **Pages** (`frontend/src/app/`):
  - Dashboard: `page.tsx` (root `/`)
  - Trading: `trading/page.tsx`
  - ML Lab: `ml/page.tsx`
  - Backtest: `backtest/page.tsx` + `backtest/components/`
  - Portfolio: `portfolio/page.tsx`
  - Settings: `settings/page.tsx` + `settings/broker/ctrader/callback/`
  - Reset Password: `reset-password/page.tsx`
- **Components** (`frontend/src/components/`): `AgentPanel.tsx`, `AgentWizard.tsx`, `AuthGate.tsx`, `BacktestTradeChart.tsx`, `CandlestickChart.tsx`, `ChatSidebar.tsx`, `ChatHelpers.tsx`, `CommandPalette.tsx`, `ErrorBoundary.tsx`, `PageErrorBoundary.tsx`, `IndicatorDropdown.tsx`, `Sidebar.tsx`, `Skeletons.tsx`, `StrategySettingsModal.tsx`, `TopBar.tsx`, `UserGuide.tsx`, `Onboarding/`, `visual-editor/`, `ui/`
- **Hooks** (`frontend/src/hooks/`): all custom hooks (useAuth, useMarketData, etc.)
- **Lib** (`frontend/src/lib/`): API client, utilities
- **Types** (`frontend/src/types/`): all TypeScript type definitions

### 1.4 — ML Models on Disk
- Check `backend/data/ml_models/` — verify all referenced `.joblib`, LSTM `.h5`/`.keras`, meta-labeler, and HMM regime models exist
- Cross-reference with what `scalping_agent.py` and `expert_agent.py` try to load
- Verify models exist for all 5 symbols: XAUUSD, US30, ES, NAS100, BTCUSD
- Check both scalping models (XGBoost + LightGBM) and expert models (XGBoost + LightGBM + LSTM + Meta + HMM)

### 1.5 — Database Schema
- Read all SQLAlchemy models and verify:
  - Foreign key relationships are correct and have proper cascade behavior
  - Indexes exist on frequently queried columns
  - Nullable/non-nullable columns make sense
  - No orphaned models (models defined but never used by any API)
  - Migrations are up to date with model definitions

---

## PHASE 2: Backend Deep Audit

### 2.1 — Every API Route
For **each** route file in `backend/app/api/`, check:
- [ ] All endpoints are reachable (make test HTTP requests to `http://localhost:8000`)
- [ ] Request validation — does it reject bad input correctly?
- [ ] Response format — does it match the schema?
- [ ] Auth protection — are all non-public routes protected with `get_current_user`?
- [ ] Error handling — are exceptions caught and returned as proper HTTP errors (not 500s)?
- [ ] SQL injection / query safety — are all DB queries parameterized?
- [ ] N+1 query problems
- [ ] Pagination on list endpoints

**Test these specific endpoint groups via HTTP:**
1. **Health**: `GET /api/health`
2. **Dashboard**: `GET /api/dashboard/stats`, `GET /api/dashboard/overview`
3. **Agents**: `GET /api/agents`, `POST /api/agents`, `PUT /api/agents/{id}`, `DELETE /api/agents/{id}`, agent start/stop/pause
4. **Brokers**: `GET /api/broker/accounts`, `GET /api/broker/trades`, `GET /api/broker/positions`
5. **ML**: `GET /api/ml/models`, `POST /api/ml/train`, `GET /api/ml/retrain/status/{id}`
6. **Backtest**: `POST /api/backtest/run`, `GET /api/backtest/results`
7. **Portfolio**: `GET /api/portfolio`, `GET /api/portfolio/broker-portfolios`
8. **Settings**: `GET /api/settings`, `PUT /api/settings`
9. **Data Sources**: `GET /api/data/sources`
10. **Market**: `GET /api/market/prices`
11. **WebSocket**: `ws://localhost:8000/ws/stats`

### 2.2 — All 5 Broker Adapters
For **each** broker in `backend/app/services/broker/`:
- [ ] `oanda.py` — connection, get_positions, get_orders, place_order, close_position, get_closed_trades, lot sizing
- [ ] `ctrader.py` — same + volume conversion (centos), price encoding (double vs int), tradeSide handling
- [ ] `coinbase.py` — same + base_size vs quote_size for market orders
- [ ] `tradovate.py` — same + contractId-to-symbol resolution
- [ ] `mt5_bridge.py` / `mt5_remote.py` — same + bridge URL handling for Linux deployments
- [ ] `manager.py` — broker registry, connection lifecycle, auto-reconnect
- [ ] Verify all adapters implement the `BaseBroker` interface completely
- [ ] Check error handling and retry logic in each adapter

### 2.3 — Agent Engine
- [ ] `engine.py` — agent lifecycle (start/stop/pause/resume), signal processing, trade execution
- [ ] `scalping_agent.py` — ML model loading, feature computation, dual-model agreement, session filtering, position sizing
- [ ] `expert_agent.py` — ensemble loading (XGB+LGB+LSTM), meta-labeler, regime detection, multi-timeframe features
- [ ] `trade_monitor.py` — SL/TP monitoring, symbol subscription, dynamic symbol addition
- [ ] `risk_manager.py` — daily loss limits, drawdown checks, position limits
- [ ] `portfolio_manager.py` — allocation tracking, circuit breakers
- [ ] `broker_reconciler.py` — live vs paper position sync
- [ ] `instrument_specs.py` — verify specs for all traded instruments (XAUUSD, US30, ES, NAS100, BTCUSD)
- [ ] Check for attribute errors, direction mismatches (BUY/SELL vs long/short), and stale state bugs

### 2.4 — ML Pipeline
- [ ] `trainer.py` — XGBoost/LightGBM training, Optuna integration, walk-forward validation
- [ ] `features.py` + `features_mtf.py` — feature computation correctness, NaN handling, feature count consistency (88 scalping vs 97 expert)
- [ ] `lstm_forecaster.py` — LSTM training, memory management (150K cap), sequence building
- [ ] `ensemble_engine.py` — model aggregation, voting logic
- [ ] `meta_labeler.py` — meta-label generation, confidence scoring
- [ ] `regime_detector.py` — HMM regime classification
- [ ] `rl_environment.py` + `rl_trainer.py` — RL pipeline (if still active)
- [ ] Verify model save/load paths are consistent between training and inference

### 2.5 — Backtest Engine
- [ ] V2 engine: `runner.py`, `data_handler.py`, `execution/` — trade execution simulation
- [ ] `agent_strategies.py` — ScalpingAgentStrategy and ExpertAgentStrategy wrappers
- [ ] `v2_adapter.py` — adapter between API and V2 engine
- [ ] `analytics/` — metric calculations (PF, Sharpe, drawdown, win rate)
- [ ] Verify backtest results are consistent with live agent logic

### 2.6 — Other Services
- [ ] `llm/` — LLM copilot integration
- [ ] `news/` — news feed providers, high-impact event detection
- [ ] `strategy/` — legacy strategy service (should be mostly dead code — verify)
- [ ] `optimize/` — optimization service
- [ ] `market/` — market data service
- [ ] `prop_firm/` — prop firm rule enforcement

---

## PHASE 3: Frontend Deep Audit

### 3.1 — Every Page
Navigate to each page and check for errors in the browser console and network tab:

1. **Dashboard** (`/`) — stats load correctly, ML intelligence widget, quick overview cards, equity chart
2. **Trading** (`/trading`) — agent list loads, AgentWizard creates agents, start/stop/pause work, pending trades appear, WebSocket updates live
3. **ML Lab** (`/ml`) — models tab (list, compare), training tab (start training, progress polling), data sources tab (uploaded + Databento sources appear)
4. **Backtest** (`/backtest`) — config dialog opens, all 2 modes work (Scalping Agent, Expert Agent), results display correctly, trade chart renders
5. **Portfolio** (`/portfolio`) — positions load, equity curve renders, agent cards show correct PnL, pause/play buttons work
6. **Settings** (`/settings`) — all 8 tabs work:
   - Profile (timezone selector)
   - Appearance (theme toggle)
   - AI Settings
   - Trading Defaults (all 5 fields save correctly: agent_type, trading_mode, max_daily_loss, max_drawdown, max_open_positions)
   - Data Management (backup/restore)
   - Notifications (email/telegram)
   - Platform
   - Prop Firms

### 3.2 — Every Component
- [ ] `AgentPanel.tsx` — agent CRUD, loading states on buttons, list refresh after edit
- [ ] `AgentWizard.tsx` — 4-step wizard flow, timeframe selector, paper mode validation (no broker required), deploy validation
- [ ] `Sidebar.tsx` — correct nav items (Dashboard, Trading, ML Lab, Backtest, Portfolio, Settings), active state, mobile responsiveness
- [ ] `TopBar.tsx` — renders correctly, mobile layout
- [ ] `ChatSidebar.tsx` — LLM copilot panel, message send/receive
- [ ] `CandlestickChart.tsx` — chart rendering with lightweight-charts
- [ ] `BacktestTradeChart.tsx` — backtest results visualization
- [ ] `CommandPalette.tsx` — keyboard shortcut (`Cmd+K`), search functionality
- [ ] `ErrorBoundary.tsx` / `PageErrorBoundary.tsx` — error catching works
- [ ] `AuthGate.tsx` — unauthenticated redirect, token refresh
- [ ] `Onboarding/` — onboarding flow for new users
- [ ] `StrategySettingsModal.tsx` — check if this is dead code (strategies were removed)

### 3.3 — Hooks & API Client
- [ ] `useAuth.ts` — login, logout (clears both token + refresh_token), token refresh, redirect
- [ ] `useMarketData.ts` — WebSocket connection, price parsing (`|| 0` not `?? 0`), reconnection
- [ ] `api.ts` — request retry on 401, `uploadFile()` retry guard, error handling
- [ ] All other custom hooks — verify they handle loading/error/empty states

### 3.4 — TypeScript & Build
- [ ] Run `npm run build` in `frontend/` — any TypeScript errors are audit findings
- [ ] Check for type mismatches between frontend types and backend schemas
- [ ] Dead imports, unused variables, unreachable code

### 3.5 — Mobile & Responsive
- [ ] Test sidebar collapse on mobile
- [ ] Safe-area padding for notched phones
- [ ] Chat panel half-height on mobile
- [ ] All pages readable on 375px width

---

## PHASE 4: Cross-Cutting Concerns

### 4.1 — Security
- [ ] All API routes require auth (except health, login, register, password reset)
- [ ] Per-user data isolation (User A cannot see User B's agents, models, brokers, trades)
- [ ] WebSocket `/ws/stats` requires authentication
- [ ] Rate limiting on auth endpoints
- [ ] No SQL injection vectors (parameterized queries only)
- [ ] No XSS vectors in frontend
- [ ] Secrets not hardcoded (check for API keys, passwords in source code)
- [ ] `.env.example` exists and doesn't contain real secrets
- [ ] CORS configuration is correct

### 4.2 — Dead Code & Stale References
- [ ] `backend/app/models/knowledge.py`, `news.py`, `watchlist.py` — are these still used? APIs were removed but models may still exist
- [ ] `backend/app/api/strategy.py` — strategies were removed from the UI; is this API still needed?
- [ ] `backend/app/api/optimization.py`, `optimization_phase.py` — still functional?
- [ ] `frontend/src/components/StrategySettingsModal.tsx` — dead code?
- [ ] Any imports referencing deleted files or removed features
- [ ] Unused dependencies in `package.json` / `requirements.txt`

### 4.3 — Data Integrity
- [ ] Broker trade sync — do paper trades and live trades coexist correctly?
- [ ] Agent state persistence — does pause/resume survive server restart?
- [ ] ML model versioning — can two models for the same symbol coexist?
- [ ] Backtest results — are they tied to the correct user and not leaking across accounts?

### 4.4 — Performance
- [ ] N+1 queries in list endpoints
- [ ] Large data loads without pagination
- [ ] Frontend re-renders — unnecessary API calls on mount
- [ ] WebSocket message frequency — is it throttled?
- [ ] ML inference latency — are models cached after first load?

### 4.5 — Configuration & Naming
- [ ] `config.py` still references `FlowrexAlgo` (old name) — should be `Tradeforge`
- [ ] `SECRET_KEY` has a dev default — verify it's overridden in production
- [ ] Database URL defaults to SQLite — verify production uses Postgres
- [ ] Check `render.yaml` for deployment configuration correctness

---

## PHASE 5: Output Format

Produce a single audit report in this exact format:

```markdown
# Tradeforge Full Platform Audit Report
**Date**: [date]
**Auditor**: Claude

## Executive Summary
[2-3 sentences: overall health, number of findings by severity, critical areas]

## Findings by Area

### 1. Backend — API Routes
| # | Severity | File | Line | Finding | Impact |
|---|----------|------|------|---------|--------|
| 1 | CRITICAL | ... | ... | ... | ... |

### 2. Backend — Broker Adapters
| # | Severity | File | Line | Finding | Impact |
|---|----------|------|------|---------|--------|

### 3. Backend — Agent Engine
| # | Severity | File | Line | Finding | Impact |

### 4. Backend — ML Pipeline
| # | Severity | File | Line | Finding | Impact |

### 5. Backend — Backtest Engine
| # | Severity | File | Line | Finding | Impact |

### 6. Backend — Other Services
| # | Severity | File | Line | Finding | Impact |

### 7. Backend — Database & Models
| # | Severity | File | Line | Finding | Impact |

### 8. Frontend — Pages
| # | Severity | File | Line | Finding | Impact |

### 9. Frontend — Components
| # | Severity | File | Line | Finding | Impact |

### 10. Frontend — Hooks & API Client
| # | Severity | File | Line | Finding | Impact |

### 11. Frontend — TypeScript & Build
| # | Severity | File | Line | Finding | Impact |

### 12. Security
| # | Severity | File | Line | Finding | Impact |

### 13. Dead Code & Stale References
| # | Severity | File | Line | Finding | Impact |

### 14. Performance
| # | Severity | File | Line | Finding | Impact |

### 15. Configuration & Naming
| # | Severity | File | Line | Finding | Impact |

## Severity Definitions
- **CRITICAL**: Will cause crashes, data loss, wrong trades, or security breaches in production
- **HIGH**: Broken functionality that users will encounter
- **MEDIUM**: Incorrect behavior in edge cases, or degraded UX
- **LOW**: Code quality, naming, minor inconsistencies

## Statistics
- Total findings: X
- Critical: X | High: X | Medium: X | Low: X
- Files audited: X
- Endpoints tested: X
```

---

## Rules
1. **Do NOT fix anything.** Report only. Fixes come in a separate pass.
2. **Do NOT skip files.** Every `.py`, `.tsx`, `.ts` file must be opened and read.
3. **Do NOT assume code is correct because it was recently changed.** Recent changes can introduce new bugs.
4. **Include line numbers** for every finding.
5. **Test endpoints live** against `http://localhost:8000` wherever possible.
6. **Be specific** — "might have an issue" is not acceptable. State exactly what is wrong and what the impact is.
7. **Check the DEVLOG.md** — many bugs listed there were previously fixed. Verify the fixes are actually in place and working.
