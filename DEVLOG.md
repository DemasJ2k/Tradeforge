# Tradeforge Development Log

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

### March 23 — Architecture Restructuring, Mobile, & Cleanup

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

---

## Summary of Major Changes

| Area | What Changed |
|------|-------------|
| **Architecture** | Strategy-first → Agent-centric. Strategies page removed entirely. |
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
