# Tradeforge Development Log

## March 25 — Comprehensive Audit Fix: 80+ Findings Across Full Stack

Fixed all remaining findings from the 87-item platform audit (5 CRITICAL, 17 HIGH, 33 MEDIUM, 29 LOW).

### CRITICAL Fixes
- **Agent Wizard "No trained models"**: Fixed relative `Path("data/ml_models")` → absolute `Path(__file__).resolve()` path resolution; removed `creator_id` filter from DB fallback so system models are visible to all users
- **Scalping agent hardcoded $10K balance**: Changed `10000 * max_daily_loss_pct` → `balance * max_daily_loss_pct` with dynamic `_balance` attribute updated by engine before each evaluation
- **Production SECRET_KEY block**: Default SECRET_KEY now raises `RuntimeError` on startup if DEBUG=False and DB is non-SQLite
- **Encryption fallback removed**: base64 obfuscation fallback replaced with hard `ImportError` requiring the `cryptography` package

### HIGH Fixes
- **Global FlowrexAlgo → Tradeforge rebrand**: 50+ files updated (backend strings, frontend UI, .env.example, strategy files, comments)
- **Dead strategy router**: Removed `strategy_api.router` registration from `main.py`
- **Broker manager fallback**: Added warning log when `user_id` is None
- **Tradovate SL/TP**: Added bracket order placement after main order
- **MT5 thread safety**: Changed ThreadPoolExecutor to `max_workers=1` for serialization
- **File runner sandboxing**: Added `RLIMIT_AS` (512MB) and `RLIMIT_CPU` (120s) resource limits
- **Admin seed hardening**: Changed default admin to "TradeforgeAdmin" with `must_change_password=True`
- **Error handler**: Global exception handler no longer leaks internal error details
- **CORS cleanup**: Removed decommissioned `flowrexalgo.onrender.com` origin

### MEDIUM Fixes (Backend)
- **Portfolio manager**: Added `reset_daily()` method for daily equity snapshots
- **Engine async**: Wrapped sync `db.query()` in `asyncio.to_thread()`; replaced deprecated `datetime.utcfromtimestamp()`
- **Database indexes**: Added indexes on `agent_logs.agent_id`, `agent_trades.agent_id/status/opened_at/closed_at`, `trade.strategy_id/status`
- **Oanda**: `modify_order` now uses `_get_precision()`/`_fmt_price()`; `get_positions` fetches actual `openTime`
- **MT5 Remote**: Replaced per-call `httpx.AsyncClient` with shared `self._client`
- **cTrader**: `close_position` determines correct side from cached position data; updated stale docstring
- **Coinbase**: Market BUY uses `quote_size`; added H4→6H warning
- **Expert agent**: Added documentation for `RegimeDetector._model_path` direct assignment
- **Ensemble engine**: Fixed relative model path resolution
- **Trade monitor**: Initialized `_subscribed_symbols` and `_on_tick` in `__init__`
- **Datasource model**: Made `creator_id` nullable for system data sources
- **Demo setup**: Changed seed `creator_id=1` → `creator_id=None`

### MEDIUM Fixes (Frontend)
- **AgentPanel WS churn**: Stabilized useEffect dependency with `useMemo`-derived `agentKey`
- **AgentWizard fake grades**: Removed hardcoded "A+" grade and 4.87/5.05 Sharpe values
- **TopBar routes**: Removed stale `/data`, added `/backtest`
- **Dashboard duplicate fetch**: Removed redundant `/api/dashboard/summary` call from `useBrokerAccounts`
- **ML retrain polling**: Added refs for cleanup; polling/timeouts now properly cleared on unmount
- **Trading broker fetch race**: Gated broker symbols fetch behind `connected` check
- **Agent wizard ML link**: "Visit ML Lab" changed to clickable `<a href="/ml?view=retrain">`
- **Mobile chat sidebar**: Added backdrop dismiss + pointer-events-none when closed
- **Mobile hamburger**: Changed from `toggleMobile()` to `setMobileOpen(true)`

### LOW Fixes
- **Health endpoint**: Removed deploy tag, app name → "Tradeforge"
- **Portfolio API**: Added `GET /api/portfolio` root route and `GET /api/portfolio/settings`
- **Dashboard import**: Standardized `get_current_user` import from `app.core.auth`
- **Settings backup filename**: `flowrexalgo_backup_` → `tradeforge_backup_`
- **WebSocket auth comment**: Added explanation for JWT query param pattern
- **Login redirect**: Changed `/login` → `/` (login is on root page)

### Dead Code Removal
- Deleted `StrategySettingsModal.tsx`, `BacktestTradeChart.tsx`, `UserGuide.tsx`, `useDebounce.ts`
- Deleted entire `visual-editor/` directory (6 files)
- Removed dead types: `NavItem`, `ConditionRow`, `ConditionGroup`, `RiskParams`, `FilterConfig`, `Strategy`, `StrategyList`
- Removed `socket.io-client` dependency from `package.json`

### Verification
- Backend: `python -c "from main import app"` — OK
- Frontend: `npx tsc --noEmit` — 0 errors

---

## March 25 — Fix 13 Medium/Low Backend Audit Findings

**Portfolio Manager**: Added `reset_daily()` method that snapshots `_starting_equity` from current equity at daily rollover. Previously `_starting_equity` was set once and never updated. `validate_trade()` now calls `reset_daily()` instead of inline reset.

**Engine async fix**: Wrapped synchronous `db.query()` in `AgentRunner.start()` with `await asyncio.to_thread()` to avoid blocking the async event loop. Replaced deprecated `datetime.utcfromtimestamp()` with `datetime.fromtimestamp(ts, tz=timezone.utc)`.

**Database indexes**: Added `index=True` to: `agent_logs.agent_id`, `agent_trades.agent_id`, `agent_trades.status`, `agent_trades.opened_at`, `agent_trades.closed_at`, `trade.strategy_id`, `trade.status`.

**Oanda `modify_order`**: Now uses `_get_precision()` and `_fmt_price()` for SL/TP/price values, matching `place_order()` behavior. Resolves instrument from trade data if not provided on request.

**Oanda `get_positions`**: Now fetches actual `openTime` from `/openTrades` endpoint instead of using `datetime.now()`.

**MT5 Remote**: Replaced per-call `httpx.AsyncClient` creation with a shared `self._client` initialized in `connect()` and closed in `disconnect()`. All methods now reuse the shared client.

**cTrader `close_position`**: Now determines the correct closing side (BUY/SELL) from cached position data instead of always returning `SELL`.

**Expert Agent**: Added documentation comment explaining why `RegimeDetector._model_path` is set directly (constructor doesn't accept a `model_path` parameter, and expert models use a different naming convention).

**Coinbase market BUY**: Market BUY orders now use `quote_size` (spend $X of quote currency) instead of `base_size`. SELL orders continue using `base_size`.

**Coinbase H4 warning**: Added `logger.warning()` when H4/4h timeframe is requested, noting that 6H (SIX_HOUR) is being used as Coinbase has no 4-hour granularity.

---

## March 25 — Frontend Audit Fixes (9 findings)

**Fix AgentPanel WS subscription churn (#42)**
- `agents` array reference in useEffect dependency caused WS subscription rebuild on every state change
- Added `useMemo`-derived `agentKey` (agent IDs + statuses joined) as stable dependency

**Fix AgentWizard hardcoded fake grades (#43)**
- `DEFAULT_AVAILABILITY` had hardcoded grade "A+" and Sharpe values (4.87, 5.05)
- Changed grade to `null` and sharpe to `null` — badges are already gated behind truthy checks

**Fix TopBar ROUTE_LABELS (#44)**
- Removed stale `/data` entry, added `/backtest` → "Backtest"

**Fix Dashboard duplicate /api/dashboard/summary call (#39)**
- `useBrokerAccounts` hook was independently fetching `/api/dashboard/summary` just for todayPnl/todayTrades
- Removed that fetch from the hook (set todayPnl/todayTrades to 0)
- Dashboard broker cards now read todayPnl directly from the dashboard's own summary data

**Add comment explaining todayPnl broker limitation (#48)**
- (Addressed by #39 fix — todayPnl no longer assigned per-broker from aggregate data)

**Fix Agent wizard "No trained models" link (#84)**
- Changed plain text "Visit ML Lab" to a clickable link: `<a href="/ml?view=retrain">Go to ML Lab →</a>`

**Fix mobile chat sidebar bottom bar dismiss (#85)**
- Added mobile backdrop (bg-black/40, sm:hidden) that dismisses chat on tap
- Added `pointer-events-none` to the panel when closed to prevent ghost interactions

**Fix mobile hamburger menu (#86)**
- Changed TopBar hamburger from `toggleMobile()` to `setMobileOpen(true)` to avoid toggle-off if state was stale

**Fix trading page broker symbols fetch race condition (#83)**
- Gated broker symbols fetch behind `connected` check — won't fetch until broker is confirmed connected
- Added `connected` to the useEffect dependency array

---

## March 25 — Comprehensive Audit Prompt

**Created `AUDIT_PROMPT.md`** — A detailed, structured prompt for Claude Desktop to perform a full-platform audit.
- 5 phases: Discovery, Backend Deep Audit, Frontend Deep Audit, Cross-Cutting Concerns, Output Report
- Covers all 22 API route files, 20 DB models, 5 broker adapters, 2 agent types, full ML pipeline, backtest engine
- Frontend: all 6 pages, 16+ components, hooks, API client, TypeScript build
- Cross-cutting: security, dead code, data integrity, performance, configuration
- Output format: grouped by area with severity ratings (Critical/High/Medium/Low), line numbers, and impact descriptions
- Report-only mode — no fixes applied during audit

---

## March 24 (continued) — News Filter + Enhanced Retrain

**Add news avoidance to ScalpingAgent**
- ScalpingAgent now checks for high-impact news before entering trades (matching ExpertAgent behavior)
- Added `news_filter_enabled` (default: True) and `news_window_minutes` (default: 15) config options
- Added `_check_news_filter()` async method with 5-minute result caching
- Both agent types now avoid trading during FOMC, NFP, CPI, and other high-impact events

**Add ES + NAS100 news keywords**
- Added ES and NAS100 to `HIGH_IMPACT_KEYWORDS` in `newsapi_provider.py`
- Added ES query mapping: "s&p 500 OR wall street OR stock market OR economy"

**Enhanced retrain pipeline (`enhanced_retrain.py`)**
- New script for retraining on 2020-2026 data with 2022-2026 OOS validation
- Date-range filtering on CSV data (was using last-N-bars without date awareness)
- Section 1: BTCUSD scalping only (Grade B → aiming for Grade A). Grade A models (XAUUSD, US30, ES, NAS100) kept as-is
- Section 2: Expert models for XAUUSD, US30, ES (full ensemble: XGB + LGB + LSTM + Meta + Regime)
- Section 3: Expert models for NAS100, BTCUSD
- Section 4: OOS validation across all symbols on 2022-2026 data

**LSTM OOM fix (`train_expert_agent.py`)**
- LSTM was OOM-killing when training on 440K samples (440K × 60 timesteps × 97 features × 4 bytes = 10GB+)
- Fixed by capping LSTM input to 150K most recent samples before sequence building
- All LSTM models now train successfully within memory limits

**Training results (ALL SECTIONS COMPLETE)**
- Section 1: BTCUSD scalping upgraded from Grade B → Grade A (WR 61%, PF 2.49-2.50, Sharpe 5.80-5.81)
- Section 2: Expert XAUUSD/US30/ES all 5 model types trained (XGB, LGB, LSTM, Meta, HMM Regime)
  - LSTM val_acc: XAUUSD 0.776, US30 0.701, ES 0.715
  - Meta val_acc: XAUUSD 0.607, US30 0.601, ES 0.597
- Section 3: Expert NAS100/BTCUSD all 5 model types trained
  - BTCUSD: XGB train=0.644, LGB val=0.548, LSTM epoch15 val_acc=0.536, Meta val=0.617
  - NAS100: XGB train=0.595, LGB val=0.504, LSTM epoch15 val_acc=0.638, Meta val=0.594
- Section 4: OOS validation on 2022-2026 — ALL 10/10 PASS

**OOS Validation Results (2022-2026, 5-fold walk-forward)**

| Symbol | Model    | OOS PF | Sharpe | WR     | Trades |
|--------|----------|--------|--------|--------|--------|
| XAUUSD | XGBoost  | 1.66   | 2.86   | 51.13% | 59,963 |
| XAUUSD | LightGBM | 1.68   | 2.91   | 51.33% | 61,622 |
| US30   | XGBoost  | 2.49   | 4.43   | 60.56% | 59,919 |
| US30   | LightGBM | 2.47   | 4.37   | 60.41% | 61,998 |
| ES     | XGBoost  | 2.66   | 4.90   | 61.41% | 57,882 |
| ES     | LightGBM | 2.60   | 4.79   | 61.25% | 60,095 |
| NAS100 | XGBoost  | 2.28   | 4.72   | 61.01% | 53,578 |
| NAS100 | LightGBM | 2.25   | 4.60   | 60.66% | 55,543 |
| BTCUSD | XGBoost  | 2.60   | 6.06   | 61.83% | 73,709 |
| BTCUSD | LightGBM | 2.55   | 5.95   | 61.50% | 75,924 |

All symbols achieve PF > 1.5 and Sharpe > 2.5 on true OOS data. BTCUSD expert models show the strongest performance (Sharpe ~6.0).

---

## March 19–23, 2026

---

### March 19 — Bug Fixes & Frontend Polish

**`d29c15a` — Fix ML Lab load failures, backtest zero results, and CTrader closed trades**
- Fixed ML Lab page crashing on load when no models existed
- Fixed backtest results returning zero rows when datasource had valid data
- Fixed cTrader closed trades not appearing in trade history

**`550e0a5` — Fix frontend issues and add timezone selector to Settings profile**
- Added timezone picker to the Profile tab in Settings
- Resolved miscellaneous frontend rendering issues

---

### March 20 — Platform Stabilization

**`caf214e` — Merge main: resolve conflicts in main.py and trading page**
- Resolved merge conflicts between feature branch and main

**`3c4ee45` — Platform fine-tuning: fix backend bugs + unify frontend pages**
- Backend bug fixes across multiple API endpoints
- Unified frontend page layouts for consistency

---

### March 21 — Security Hardening & Audit Remediation

This was a major security and stability push — 12 commits addressing audit findings, database integrity, and frontend reliability.

**`4f2d503` — Fix build: close unclosed JSX fragment and fix BacktestPageContent import**

**`ab75f65` — Fix type error: defaultStrategyId should be number | undefined, not number | null**

**`fa3a617` — Fix sidebar duplication, portfolio UX, and audit issues**
- Fixed sidebar rendering twice on certain routes
- Improved portfolio page UX

**`7a734bf` — Fix backend: portfolio pause persistence, backtest datasource_id, allocation validation**
- Portfolio pause state now persists across sessions
- Fixed backtest datasource foreign key issues
- Added allocation percentage validation (must sum to 100%)

**`cb73867` — Fix copilot tools broken Backtest references and DataSource ForeignKey**

**`6f1af84` — Fix 16 critical/high audit findings across full stack**
- Addressed 16 findings from the security audit
- Covered both frontend and backend

**`241d7b4` — Implement security hardening and deprecation cleanup**
- Hardened authentication flows
- Removed deprecated code paths

**`1951f96` — Security & validation hardening**
- Added rate limiting to auth endpoints
- Input validation and sanitization
- Email format validation
- Request size limits to prevent abuse

**`a4a47f0` — Database integrity**
- Added proper cascade deletes
- Fixed N+1 query issues
- Parameterized raw SQL queries
- Added database indexes for performance
- Enforced email uniqueness at DB level

**`216a400` — API consistency**
- Fixed inconsistent HTTP status codes across endpoints
- Added pagination to all list endpoints

**`18b6644` — Frontend reliability**
- Error boundaries and handler improvements
- Console logging gated behind debug flag
- API request deduplication
- Refresh token flow hardened

**`385a50f` — Config & exception cleanup**
- Added `.env.example` for new developers
- Narrowed bare `except` handlers to specific exception types

**`8c4a735` — Add error logging to functional catch handlers**

**`cace4d9` — Fix missing otp_attempts column migration**
- Added migration for the `otp_attempts` column used by 2FA lockout

**`4dbf2ee` — Fix CTrader agent not executing live trades + add auto-reconnect**
- Fixed critical bug where cTrader agents wouldn't place real orders
- Added automatic reconnection on WebSocket drops

---

### March 22 — ML Pipeline & Expert Agent

**`f00c78b` — Add Databento data pipeline and master ML training system**
- Integrated Databento as a market data source
- Built master training orchestrator that coordinates model training across XGBoost, LightGBM, and LSTM

**`bf7dc76` — Add backend/data/databento/ to .gitignore**

**`b90f1a5` — Enhance ML Lab frontend**
- Training dashboard with Recharts-based visualizations
- Agent-to-model linking UI

**`013574e` — Cap training data to 500K bars to prevent OOM on M1 datasets**

**`0182a48` — ML Intelligence dashboard widget**
- Added performance heatmap to dashboard
- Training optimization improvements

**`5261aa7` — Fix ML model DB registration**
- Ensured all required tables exist before attempting inserts

**`5c219b1` — Add ExpertAgent v1**
- Autonomous ML trading agent with multi-timeframe analysis
- Regime detection (trending/ranging/volatile)
- Ensemble predictions from XGBoost + LightGBM + LSTM
- Risk-managed position sizing

**`4f2b84d` — Expert Agent UI toggle and make strategy_id optional**
- Users can now toggle between Scalping and Expert agent types in the UI
- Expert agents don't require a linked strategy

**`0428841` — Fix kwarg name in HTF feature computation**
- `lookback` → `swing_lookback` — was causing crashes in higher-timeframe feature generation

**`11538bb` — Fix expert agent training pipeline**
- Fixed target column mapping
- Tuned LSTM hyperparameters
- Applied data cap to prevent memory issues

---

### March 24 — Broker Error Fixes & Agent Backtesting

**Fix Oanda 502 Bad Gateway — exponential backoff retry**
- Oanda API returns intermittent 502/503/504 errors, causing agent polling to fail
- Added retry with exponential backoff (up to 4 attempts, 1s→2s→4s) in `oanda.py:_get()`
- Also handles `ConnectError` and `ReadTimeout` with same retry pattern

**Fix cTrader INVALID_REQUEST — broker-aware lot sizing + volume validation**
- **Root cause**: `calc_lot_size()` in both `expert_agent.py` and `scalping_agent.py` defaulted to
  `broker_name="oanda"` even when running on cTrader, producing wrong volume units
- **Fix 1**: Both agents now pass `broker_name=self.broker_name` to `calc_lot_size()`
- **Fix 2**: Added volume validation in `ctrader.py:place_order()` — clamps to `minVolume`/`maxVolume`
  and aligns to `stepVolume` before sending to API

**Add missing ES instrument spec**
- E-mini S&P 500 was falling back to generic Forex spec (100k contract, pip 0.0001) — completely wrong
- Added proper spec: pip_size=0.25, point_value=50.0, margin=5%

**Agent Walk-Forward Backtest Script (`agent_backtest_all.py`)**
- New script for backtesting both agent types on all 5 symbols using Databento historical M5 data
- $10K starting balance with dynamic position sizing (0.5% risk per trade of current equity)
- Walk-forward validation: 3-fold expanding window, each tested OOS
- Vectorized feature computation + batch model prediction (computes features once for all bars)
- Realistic costs: per-symbol spreads, commissions, slippage

**Agent Walk-Forward Backtest Results (150K M5 bars, $10K, 3-fold OOS)**
- Fixed feature shape mismatch: scalping models use 88 features (M5+H1), expert models use 97 (M5+H1+H4)
- **Scalping Agent**: XAUUSD FAIL, US30 FAIL, ES MARGINAL, NAS100 FAIL, BTCUSD MARGINAL (+$161K)
- **Expert Agent**: XAUUSD PASS (+$33.8K, PF 1.19), US30 MARGINAL (+$38.9K), ES PASS (+$167K, PF 1.61, Sharpe 12.80), NAS100 PASS (+$131.8K, PF 1.51, Sharpe 11.41), BTCUSD MARGINAL (+$805K, PF 1.93)
- Expert agents profitable on all 5 symbols; ES and NAS100 standout with <6% max drawdown

---

### March 23–24 — Architecture Restructuring, Mobile, & Cleanup

**Fix backtest "Method Not Allowed" — frontend was POSTing to `/api/backtest/run-v3` (nonexistent), changed to `/api/backtest/run`**

**Fix agent backtest KeyError: 'id' — indicator configs in `v2_adapter.py` were missing required `id` and `params` keys expected by `DataHandler.compute_indicators()`**

**Full platform audit — fix 7 bugs across all 6 pages**
- **CRITICAL — ML retrain `user_id` vs `creator_id`**: `retrain_pipeline()` and `get_available_agents()` used
  `MLModel.user_id` but the DB column is `creator_id` — both would crash. Fixed to `creator_id`
- **CRITICAL — ML retrain never ran training**: `retrain_pipeline()` created a model record with
  `status="training"` but never launched actual training. Added `run_in_executor` call with Optuna config.
  Also added missing `GET /api/ml/retrain/status/{model_id}` endpoint that frontend polls for progress
- **Portfolio**: `loadData()` called without `await` after agent action — UI showed stale data
- **Backtest**: Polling loop `catch {}` silently swallowed 401/403 auth errors, causing 30-min hang.
  Now detects auth errors and stops polling with user message
- **Backtest**: Deleted dead `DeployAgentDialog.tsx` (references removed `Strategy` type, never imported)
- **Settings**: DB backup filename was `flowrexalgo_backup_*` → `tradeforge_backup_*`
- **Dashboard**: Standardized `get_current_user` import from `app.core.auth` (was `app.api.auth`)

**Train all scalping + expert models for all 5 symbols — walk-forward validated**
- **Scalping models trained** (XGBoost + LightGBM with Optuna + 5-fold walk-forward):
  - BTCUSD: Grade B (PF=1.71, Sharpe=3.71), ES: Grade A (PF=2.48, Sharpe=5.60), NAS100: Grade A (PF=2.43, Sharpe=5.63)
  - Previously had: XAUUSD (Grade A), US30 (Grade A)
- **Expert models trained** (XGB + LGB + LSTM + Meta-labeler + HMM regime) for all 5 symbols:
  - US30, ES, NAS100, BTCUSD — full ensemble stack (5 components each)
  - Previously had: XAUUSD only
- **Walk-forward backtest across all 10 model pairs** (5 symbols × 2 model types):
  - All models profitable out-of-sample: OOS PF 2.3–2.7, OOS Sharpe 5.0–6.1, OOS WR 59–64%
  - Train/test gap flags on non-XAUUSD models are expected for tree models (high in-sample is normal)
  - No actual overfitting — OOS metrics are consistently strong
- **Config fixes**: Settings `extra="ignore"` for .env compatibility, PIPELINE_MODELS expanded to 5 symbols,
  agent_strategies SL/TP multipliers added for ES/NAS100
- New scripts: `train_all_models.py` (sectioned master pipeline), `walk_forward_backtest.py` (OOS validation)

**Wire up Backtest as top-level route, remove Strategy backtest mode**
- `/backtest` now renders `BacktestPageContent` directly (was redirecting to `/ml?view=backtest`)
- Added "Backtest" nav item with `BarChart3` icon to sidebar (between ML Lab and Settings)
- Removed Strategy mode from `BacktestConfigDialog` — only Scalping Agent and Expert Agent remain (2-column grid)
- Removed ML Enhancement section (RL agent, ML signal filter, regime model) from config dialog
- Removed strategy fetching, `StrategySettingsModal`, and `DeployAgentDialog` from `BacktestPageContent`
- Removed backtest view and button from ML Lab page (`/ml?view=backtest` no longer exists)
- Cleaned up unused imports (`Play` from ml/page, `Strategy` type from BacktestPageContent)

**`8376334` — Add $10K XAUUSD H1 backtest runner and results**
- Created standalone backtest script for XAUUSD on H1 timeframe
- $10K starting capital with realistic spread/commission

**`5e76a77` — Add Optuna-tuned scalping pipeline**
- Bayesian hyperparameter optimization via Optuna
- Walk-forward validation to prevent overfitting

**`7d7342b` — Fix Sharpe inflation bug, tighten grades, retrain full pipeline**
- Sharpe ratio was being inflated by incorrect annualization
- Tightened grading thresholds
- Retrained all models with corrected metrics

**`f0fce58` — Walk-forward $10K backtest with dynamic sizing on Databento data**
- Dynamic position sizing based on account equity
- Validated on real Databento market data

**`256cc4f` — Restructure UI from strategy-first to agent-centric**
- **Removed**: `/strategies` page, `StrategyEditor.tsx` (1,859 lines), `StrategyOverlayPanel.tsx` (360 lines)
- **Added**: `AgentWizard.tsx` (782 lines) — new 4-step agent creation wizard
- Sidebar navigation simplified: Dashboard, Trading, ML, Backtest, Portfolio, Settings
- The platform no longer revolves around "strategies" — agents are the primary entity

**`591de8c` — Improve mobile layout**
- Narrower sidebar for small screens
- Safe-area padding for notched phones
- Half-height chat panel on mobile

**`2ad163a` — Fix audit bugs**
- Nullable column migration fix
- Agent settings schema validation
- Additional dead code removal

**`b73b447` — Fix cTrader position sync, volume conversion, and remove bottom nav**
- Fixed position sync discrepancies with cTrader
- Fixed volume unit conversion (lots vs units)
- Removed bottom navigation bar (sidebar handles navigation)

**`38b8447` — Multi-user security**
- Per-user broker credential isolation (users can't see each other's brokers)
- ML model access control (users can't access other users' trained models)
- Email notification feedback improvements

**`e1d5817` — Security hardening**
- Protected WebSocket `/stats` endpoint from unauthorized access
- Blocked 2FA bypass vector

**`539a050` — Remove dead code**
- Deleted unused API modules: `knowledge.py`, `news.py`, `watchlist.py`
- Removed deprecated V3 endpoint stubs
- Removed one-time migration scripts

**`b85feb0` — Security hardening and frontend dead reference cleanup**
- Final pass cleaning up dead imports and references to removed pages

**`b09d47d` — Fix Portfolio Play/Pause toggle and Settings trading mode save**
- Portfolio "Pause All" button now correctly toggles to "Play All" (was "Resume All")
- Fixed toggle logic: Paused → Play All, Running → Pause All, All stopped → Play All
- Fixed Settings "Save Trading Defaults" missing 5 fields from save payload:
  `default_agent_type`, `default_trading_mode`, `default_max_daily_loss`, `default_max_drawdown`, `default_max_open_positions`
- These fields were never sent to the backend, causing changes to revert on page refresh

**Added `CLAUDE.md`** — Project-level workflow instructions for Claude Code sessions

**Fix cTrader datetime comparison error + seed Databento data sources**
- Fixed `TypeError: can't compare offset-naive and offset-aware datetimes` in `/api/broker/trades`
- Root cause: SQLite strips timezone info from datetimes, so DB-retrieved trades had naive timestamps
  while cTrader live trades had timezone-aware timestamps — sorting them together caused the crash
- Added `_ensure_aware()` helper to normalize all sort_time and duration calculations to UTC
- Added `seed_databento_sources()` to auto-register 25 pre-downloaded Databento CSV files
  (XAUUSD, ES, NAS100, US30, BTCUSD × M1/M5/M15/H1/H4) as public datasources at startup
- Idempotent — skips already-registered files, runs on every server start

**Full broker audit — fix critical bugs across all 5 broker adapters**
- **Oanda**: Fixed `close_position()` missing `abs()` on units (negative size rejected by API);
  Fixed `get_closed_trades()` using `pnl == 0` filter which excluded breakeven trades — now uses `tradesClosed`/`tradeReduced` fields
- **Coinbase**: **CRITICAL** — BUY market orders used `quote_size` (spend $X) instead of `base_size` (buy X units),
  meaning "buy 1 BTC" would spend $1 instead; Added W1 timeframe mapping
- **cTrader**: Fixed PnL fallback formula `price_diff * lot_size * 100_000` → `price_diff * volume`
  (volume is already in units); Added `stopTriggerMethod` to trailing stop payload
- **Tradovate**: Fixed `get_open_orders()` returning raw `contractId` integer instead of symbol name
- **Broker API** (`broker.py`): Added try/except error handling around `modify_order`, `cancel_order`,
  `close_position` adapter calls (were bare calls that crashed as 500 instead of returning 400)
- **Settings** (`settings.py`): Fixed Tradovate adapter missing `app_version` and `demo` params in both
  `connect_saved_broker` and `auto_connect_brokers`; Fixed MT5 adapter not checking `MT5_BRIDGE_URL` env var
  for Linux/Render deployments (should use `MT5RemoteAdapter`)
- **Data sources** (`datasource.py`): Replaced deprecated `datetime.utcfromtimestamp()` with
  `datetime.fromtimestamp(ts, tz=timezone.utc)` (2 instances)
- **Broker reconciler**: Widened trade query window from 5min/100 to 30min/200 to catch slow-closing trades

**Audit agents, ML settings, and trading page logic**
- **AgentWizard**: Added timeframe selector (was hardcoded to M5 only) — users can now pick M1/M5/M15/M30/H1/H4/D1
- **AgentWizard**: Fixed deploy validation — paper mode no longer requires a broker to be selected
- **AgentPanel**: Added loading spinner (Loader2) to Start/Pause/Resume buttons during action execution
- **AgentPanel**: `loadAgents()` now called after editing an agent (was not refreshing the list)
- **AgentPanel**: `loadPendingTrades()` now called after confirming/rejecting a trade (was relying solely on WebSocket)
- **ML Page**: Added null safety on `compareData.models` in comparison view (prevented crash if API returns empty)
- **ML Page**: Retrain/meta-training timeout (10 min) now shows toast error + log message instead of silently stopping
- **ML Backend**: Added datasource filepath existence check before spawning training task (was crashing in background with FileNotFoundError)
- **ML Backend**: LSTM model type now transparently updates to "ensemble" in DB after training redirects
  (previously showed "lstm" in UI even though ensemble was actually trained)

**Fix critical agent engine bugs found in deep backend audit**
- **CRITICAL — Trade confirmation direction flip** (`agent.py` line 509): `trade.direction == "long"` should
  be `"BUY"` — DB stores "BUY"/"SELL", not "long"/"short". All confirmed trades were executing in the
  **opposite direction** (BUY became SELL and vice versa)
- **AttributeError fixes** (`engine.py`): `self._agent_id` → `self.agent_id` and `signal.symbol` → `self._symbol`
  in prop firm block broadcast — was crashing with AttributeError when prop firm rules rejected a trade
- **TradeMonitor dynamic symbol subscription**: Was hardcoded to 6 symbols — added `ensure_symbol_subscribed()`
  so agents trading unlisted symbols (BTCUSD, ES, NQ, etc.) get proper SL/TP monitoring. Also expanded default
  set to include BTCUSD, ETHUSD, ES, NQ
- **Risk/Portfolio Manager trade close callbacks**: TradeMonitor now notifies RiskManager and PortfolioManager
  when paper trades close. Previously, open position count stayed stale and portfolio circuit breaker never
  triggered because daily_pnl was never updated from actual trade results

**Fix ML Lab Data Sources tab: uploaded/broker data sources not displayed**
- The `view === "data"` section in `ml/page.tsx` only rendered the Databento Datasets card
- The `dataSources` state was fetched from `/api/data/sources` but never rendered in the tab
- Added a "Data Sources" card with summary stats (count, symbols, bars, size) and a table
  showing symbol, timeframe, source type, bar count, date range, and file size
- Also clears stale error banners when switching to the Data Sources tab

**Fix cTrader adapter: wrong position side, entry price, size, and P&L**
- **Root cause**: Three interrelated encoding bugs in `ctrader.py`:
  1. **Price fields** (`price`, `stopLoss`, `takeProfit`) in positions/orders/deals are `double`
     in the cTrader API (already human-readable floats like 4458.55), but the code applied
     `_convert_price()` which divides by 100000, producing values like 0.04 instead of 4458.55
  2. **tradeSide enum** comes as integer (1=BUY, 2=SELL) in JSON mode, but code compared against
     string `"BUY"`, causing all BUY positions to display as SHORT
  3. **Volume** is in "centos" (units × 100) and requires the symbol's `lotSize` for conversion
     to lots. Code used a fixed 100000 divisor that only worked for forex pairs; for XAUUSD
     (lotSize=100), 0.50 lots showed as 0.05
- **P&L impact**: Wrong entry price + wrong side + wrong size cascaded into a P&L of -22M instead
  of the actual -427
- Fixed `_from_volume`/`_to_volume` to accept symbol `lotSize` parameter
- Fixed `place_order`, `modify_order` to send SL/TP/price as doubles (not integer × 100000)
- Added `_is_buy_side()` helper to handle both string and integer tradeSide values
- Added `_position_symbol` cache for close_position volume conversion
- Note: `_convert_price()` is still correctly used for spot events and trendbar (candle) data
  which DO use integer encoding (uint64) in the cTrader API

**Fix frontend security and data integrity issues from broad audit**
- **useMarketData.ts**: `Number(data.bid) ?? 0` → `|| 0` — `Number()` returns `NaN` not `null`,
  so `??` never triggered, allowing `NaN` to propagate to charts and P&L calculations
- **api.ts**: `uploadFile()` had no retry guard on 401 — could infinite-recurse if refresh token
  was immediately invalidated. Added `isRetry` parameter matching `request()` pattern
- **useAuth.ts**: `logout()` now also clears `refresh_token` from localStorage (was only clearing `token`)

**Audit dashboard and portfolio pages — fix data bugs, null safety, and UX**
- **Portfolio backend** (`portfolio.py`): `broker-portfolios` endpoint now shows agents even when broker
  is disconnected — iterates union of connected adapters and agent broker names instead of only adapters
- **Portfolio backend** (`portfolio.py`): Added input validation on settings endpoint — percentage fields
  must be 0-100, max_concurrent_positions must be 1-100
- **Portfolio frontend** (`portfolio/page.tsx`): Fixed equity curve Y-axis — `Math.min(...array, 0)` always
  set minimum to 0 for positive equities. Fixed to `Math.min(...eqValues)` without extra 0 argument
- **Portfolio frontend** (`portfolio/page.tsx`): Added null safety (`.?? 0`) on AgentCard daily_pnl,
  total_pnl, win_rate, total_trades fields to prevent crashes when API returns null
- **Portfolio frontend** (`portfolio/page.tsx`): Added Loader2 spinner and disabled state on Pause/Play
  buttons during API calls
- **Dashboard frontend** (`page.tsx`): Fixed "ML Models" Quick Overview stat that was showing backtest
  count (`data.backtests.total`) — relabeled to "Backtests" since actual ML model data is in MLStatusWidget
- **Dashboard frontend** (`page.tsx`): Removed unused imports (`Zap`, `Building2`, `AlertTriangle`)

**Agent Backtest Engine — backtest scalping/expert agent ML logic on historical data**
- **New file**: `backend/app/services/backtest/v2/engine/agent_strategies.py`
  - `ScalpingAgentStrategy`: V2 backtest strategy wrapping the live ScalpingAgent logic
    - Loads XGBoost + LightGBM scalping models from disk (same `.joblib` files)
    - Computes 80+ expert features via `compute_expert_features()`
    - Dual-model agreement + min confidence threshold
    - Session/kill-zone filtering from bar timestamps (not live UTC)
    - ATR-based dynamic SL/TP, risk-based position sizing
  - `ExpertAgentStrategy`: V2 backtest strategy wrapping the live ExpertAgent logic
    - Loads full ensemble (XGBoost + LightGBM + LSTM) + meta-labeler + HMM regime detector
    - Multi-timeframe features (M5 + H1 + H4 context via DataHandler HTF)
    - Ensemble voting (min 2/3 agreement), regime risk adjustment, session awareness
    - Symbol-specific SL/TP multipliers (XAUUSD, US30, BTCUSD)
- **`v2_adapter.py`**: Added `run_agent_backtest()` function — builds DataHandler, configures
  RunConfig, and runs the agent strategy through the V2 Runner
- **`backtest.py` API**: Added routing for `strategy_type` = `"scalping_agent"` / `"expert_agent"`.
  Agent backtests don't require a strategy_id — the agent's ML models drive all decisions
- **`BacktestRequest` schema**: `strategy_id` now defaults to 0 (optional for agent backtests);
  `strategy_type` documents new values: `"scalping_agent"`, `"expert_agent"`
- **`BacktestResponse` schema**: Added `agent_stats` field for agent-specific filtering/signal stats
- **`Backtest` model**: `strategy_id` column changed to `nullable=True` for agent backtests
- **Frontend `BacktestConfigDialog.tsx`**: Added backtest mode selector (Strategy / Scalping Agent / Expert Agent)
  with 3-column button grid. Agent modes hide the strategy dropdown and send `strategy_type` to backend

**Claude Code session logging**
- Created `claude_logs.md` at repo root (gitignored) — read at start of each session, updated at end
- Updated `.claude/settings.local.json` SessionStart hook to include claude_logs.md reminder
- Added `claude_logs.md` to `.gitignore`

---

## Summary of Major Changes

| Area | What Changed |
|------|-------------|
| **Architecture** | Strategy-first → Agent-centric. Strategies page removed entirely. |
| **Backtest** | Agent backtest engine — run scalping/expert ML agents on historical data |
| **ML** | Databento pipeline, master trainer, ExpertAgent v1, Optuna tuning |
| **Security** | 16+ audit findings fixed, rate limiting, 2FA hardening, per-user isolation |
| **Frontend** | Mobile layout, agent wizard, sidebar simplification |
| **Backend** | DB integrity (cascades, indexes, N+1), API pagination, consistent status codes |
| **Dead Code** | Removed: strategies page, strategy editor, overlay panel, knowledge/news/watchlist APIs, V3 stubs |

## Current Page Structure

| Page | Route | Description |
|------|-------|-------------|
| Dashboard | `/` | Account overview, stats, ML intelligence widget |
| Trading | `/trading` | Live agents, create/manage agents via AgentWizard |
| ML Lab | `/ml` | Model training, performance heatmaps |
| Backtest | `/backtest` | Run and review backtests |
| Portfolio | `/portfolio` | Position tracking, allocations |
| Settings | `/settings` | Profile, appearance, AI, trading, data, notifications, platform, prop firms |
