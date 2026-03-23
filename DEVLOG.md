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
