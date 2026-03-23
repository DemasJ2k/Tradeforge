# Tradeforge — Work Log (March 22–23, 2026)

## Summary

21 commits across two days covering: ML pipeline buildout, Expert Agent v1, architecture restructuring (strategy-first → agent-centric), security hardening, mobile UI improvements, and dead code cleanup.

---

## Chronological Commit Log

### March 22

| Commit | Description |
|--------|-------------|
| `f00c78b` | **Add Databento data pipeline and master ML training system** — Integrated Databento as a data source; built master training orchestrator |
| `bf7dc76` | **Add backend/data/databento/ to .gitignore** — Keep large market data files out of repo |
| `b90f1a5` | **Enhance ML Lab frontend** — Training dashboard with Recharts charts, agent-model linking UI |
| `013574e` | **Cap training data to 500K bars** — Prevent OOM crashes on M1 datasets |
| `0182a48` | **ML Intelligence dashboard widget** — Performance heatmap, training optimizations |
| `5261aa7` | **Fix ML model DB registration** — Ensure all tables exist before insert |
| `5c219b1` | **Add ExpertAgent v1** — Autonomous ML trading agent with multi-timeframe analysis |
| `4f2b84d` | **Expert Agent UI toggle** — Make strategy_id optional for expert agents |
| `0428841` | **Fix kwarg name** — `lookback → swing_lookback` in HTF feature computation |
| `11538bb` | **Fix expert agent training pipeline** — Target mapping, LSTM tuning, data cap |

### March 23

| Commit | Description |
|--------|-------------|
| `8376334` | **Add $10K XAUUSD H1 backtest runner and results** |
| `5e76a77` | **Add Optuna-tuned scalping pipeline** — Walk-forward validation included |
| `7d7342b` | **Fix Sharpe inflation bug** — Tighten grades, retrain full pipeline |
| `f0fce58` | **Walk-forward $10K backtest** — Dynamic sizing on Databento data |
| `256cc4f` | **Restructure UI: strategy-first → agent-centric** — Removed Strategies page, StrategyEditor, StrategyOverlayPanel; added AgentWizard; simplified sidebar navigation |
| `591de8c` | **Improve mobile layout** — Narrower sidebar, safe-area bottom nav, half-height chat |
| `2ad163a` | **Fix audit bugs** — Nullable migration, agent settings schema, remove dead code |
| `b73b447` | **Fix cTrader** — Position sync, volume conversion, remove bottom nav |
| `38b8447` | **Multi-user security** — Per-user broker isolation, ML access control, email feedback |
| `e1d5817` | **Security hardening** — Protect ws/stats endpoint, block 2FA bypass |
| `539a050` | **Remove dead code** — Unused API modules (knowledge.py, news.py, watchlist.py), deprecated V3 endpoints, one-time scripts |
| `b85feb0` | **Security hardening and frontend dead reference cleanup** |

---

## What Was Removed

### Frontend
- **`/strategies` page** — Entire page deleted (strategy-first model replaced by agent-centric)
- **`StrategyEditor.tsx`** — 1,859-line component removed
- **`StrategyOverlayPanel.tsx`** — 360-line component removed
- **`backtest/page.tsx.old`** — 1,232-line dead file removed
- **Bottom nav bar** — Removed (mobile uses sidebar instead)
- Dead references to knowledge, news, watchlist pages cleaned up

### Backend
- **`api/knowledge.py`** — Removed (unused)
- **`api/news.py`** — Removed (unused)
- **`api/watchlist.py`** — Removed (unused)
- **Deprecated V3 endpoints** — Removed
- **One-time migration scripts** — Removed

---

## What Was Added

### ML / Training
- **Databento data pipeline** — New market data source integration
- **Master ML training system** — Orchestrates training across models
- **Optuna-tuned scalping pipeline** — Bayesian hyperparameter optimization with walk-forward validation
- **ExpertAgent v1** — Autonomous ML agent: multi-timeframe analysis, regime detection, ensemble predictions
- **ML Intelligence dashboard** — Performance heatmap, training metrics visualization
- **$10K walk-forward backtests** — Validated on XAUUSD H1 with dynamic position sizing

### Frontend
- **AgentWizard.tsx** — New 782-line wizard for creating trading agents (replaces strategy editor flow)
- **Agent-centric navigation** — Dashboard, Trading, ML, Backtest, Portfolio, Settings
- **Mobile layout improvements** — Narrower sidebar, safe-area support, responsive chat

### Security
- Per-user broker credential isolation
- ML model access control (can't access other users' models)
- WebSocket stats endpoint protection
- 2FA bypass prevention
- Request size limiting
- Email feedback validation

---

## Current Application State

### Frontend Pages (live)
| Page | Status |
|------|--------|
| `/` (Dashboard) | ✅ Active |
| `/trading` | ✅ Active |
| `/ml` | ✅ Active |
| `/backtest` | ✅ Active |
| `/portfolio` | ✅ Active |
| `/settings` | ✅ Active |
| `/reset-password` | ✅ Active |

### Frontend Pages (removed)
| Page | Status |
|------|--------|
| `/strategies` | ❌ Removed in `256cc4f` |
| `/knowledge` | ❌ Removed previously |
| `/optimization` | ❌ No longer exists |

### Backend API Modules (still present)
| Module | Status | Notes |
|--------|--------|-------|
| `strategy.py` | ⚠️ Still exists | May need cleanup — no frontend consumer |
| `optimization.py` | ⚠️ Still exists | No frontend consumer |
| `optimization_phase.py` | ⚠️ Still exists | No frontend consumer |
| `backtest/` (V1 engine) | ⚠️ Still exists | Was supposedly cleaned up |
| `backtest_engine/` (V2 engine) | ⚠️ Still exists | Was supposedly cleaned up |
| `prop_firm.py` | ⚠️ Still exists | No frontend page |
| `recycle_bin.py` | ⚠️ Still exists | May be unused |

---

## Known Remaining Cleanup

1. **Dead strategies in database** — 46 strategies exist in DB but no strategies page to manage them; need to be purged
2. **Backend `strategy.py` API** — No frontend consumer; candidate for removal
3. **Backend `optimization.py` + `optimization_phase.py`** — No frontend consumer; candidate for removal
4. **Backend backtest engines (V1 + V2)** — User indicated these were already removed/cleaned, but directories still exist on disk
5. **Backend `prop_firm.py`** — No frontend page
6. **Stale audit reports** — `MASTER_AUDIT_REPORT.md` references pages/features that no longer exist
