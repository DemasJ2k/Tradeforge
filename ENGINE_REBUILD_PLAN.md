# TradeForge — Engine Rebuild & Strategy Builder Overhaul

## Master Plan

> **Scope**: Full engine rewrite (built on V2 core), comprehensive strategy builder with 40+ indicators, advanced rule logic, visual node editor, chart overlay, and all supporting backend/frontend changes.

---

## Current State Summary

### Engine (V1+V2 hybrid)

- **V2 core** is well-architected (event queue, composite fill pipeline, portfolio model) but fill pipeline is dead (atr=0, vol=0 hardcoded)
- **V1 engine** has no slippage, SL/TP priority ambiguity, spread only on entry
- **strategy_backtester.py** has massive duplication, hardcoded ×100 P&L scaling
- **Metrics** have CAGR formula bug (trading vs calendar days) and pnl_pct double-scaling
- **Optimizer** is sequential-only, no early stopping, only routes through V1

### Strategy Builder (Current)

- **13 indicators**: SMA, EMA, RSI, MACD, Bollinger, ATR, Stochastic, ADX, VWAP, ADR, Pivot Points, PivotHigh, PivotLow
- **Rule logic**: Simple AND/OR chains, no grouping or branching
- **Entry types**: Manual condition rows (left operator right) — no built-in crossover/breakout/pattern templates
- **SL/TP**: Fixed pips, ATR multiple, ADR %, Percentage, R:R ratio, Pivot level, TP2 + lot split, trailing stop
- **Filters**: Time window, trading days, ADX range, volatility range
- **UI**: Form-based StrategyEditor (1,269 lines, Tabs: Indicators/Entry/Exit/Risk/Filters)

### What's Missing

- 30+ indicators (Ichimoku, Supertrend, CCI, OBV, VWAP bands, ICT concepts, etc.)
- Advanced rule logic (IF/THEN/ELSE branching, grouped conditions)
- Entry type templates (crossover, breakout, bounce, pullback, candlestick patterns, time-based)
- Structure-based SL/TP (swing H/L), multi-target TP1/TP2/TP3
- Session/kill zone presets, trend direction filter, news filter, trade frequency limits, spread filter
- Visual node editor for complex strategies
- Chart overlay (indicators + trade signals on Trading page + backtest results)
- Parallel optimization

---

## User Decisions (Captured)

| Category | Decision |
|---|---|
| Engine approach | Rebuild on V2 core (reuse event queue, orders, portfolio, fill pipeline architecture) |
| Priority | Accuracy first |
| Position sizing | All methods: fixed lot, % risk, Kelly criterion, fixed fractional |
| Optimization | Parallel (multi-core) |
| Data support | OHLCV + real tick data |
| Scope | Core engine + UI updates |
| Order | Engine first → strategies after |
| Broker | MT5 + Render bridge (separate future workstream) |

### Indicators (ALL 6 categories selected)

| Category | Indicators to Add |
|---|---|
| **Trend** | Ichimoku Cloud, Supertrend, Donchian Channel, Keltner Channel, Parabolic SAR, Hull MA, DEMA, TEMA, ZLEMA |
| **Oscillators** | CCI, Williams %R, MFI, Stochastic RSI, ROC, Awesome Oscillator |
| **Volume** | OBV, VWAP Bands (±1σ/2σ), Accumulation/Distribution, Chaikin Money Flow, Volume Profile |
| **Volatility** | ATR Bands, Historical Volatility, Standard Deviation Channel |
| **Smart Money/ICT** | Order Blocks, Fair Value Gaps (FVG), Liquidity Sweeps, Breaker Blocks |
| **Session/Time** | Session High/Low, Kill Zone highlights, Previous Day High/Low, Weekly Open |

### Entry Types (ALL 6 selected)

- Crossover (MA cross, indicator cross level)
- Breakout (price breaks support/resistance, channel, range)
- Bounce/Reversal (price rejects level, divergence)
- Pullback (trend continuation after retracement)
- Candlestick Patterns (engulfing, pin bar, doji, hammer, morning/evening star, etc.)
- Time-based (enter at specific time, session open, kill zone start)

### SL/TP (4 of 6 selected)

- ✅ Fixed pips
- ✅ ATR-based (ATR multiple)
- ✅ Structure-based (swing high/low, order block edge)
- ✅ Multi-target (TP1/TP2/TP3 with partials + move SL to breakeven)
- ❌ Trailing stops (indicator-based like SAR) — not selected
- ❌ Time-based exits (close at time/N bars/session end) — not selected

### Trade Filters (ALL 6 selected)

- Time/Session filters (London, NY, Asia sessions, kill zones, custom time windows)
- Trend strength filter (ADX threshold)
- Trend direction filter (above/below MA, higher timeframe trend)
- Volatility/Spread filter (skip low vol, high spread periods)
- Trade frequency limits (max trades/day, consecutive loss pause)
- News filter (avoid high-impact news events)

### Rule Logic

- Full IF/THEN/ELSE branching with grouped conditions

### Strategy Builder UI

- Both: Enhanced form builder (improved current) + Visual node/block editor

### Chart Overlay

- Trading page + Backtest results chart (indicators + trade entry/exit signals)

---

## Phase Plan

### Phase 1 — Engine Core Rebuild

**Goal**: Accurate, unified backtesting engine built on V2 architecture

#### 1A. Fix V2 Fill Pipeline (Backend) ✅ COMPLETE

- [x] Fix `runner.py` — pass real ATR + volume data to fill model instead of hardcoded 0s
- [x] Activate `VolatilitySlippage` and `VolumeImpact` models in composite pipeline
- [x] Add configurable slippage mode: none / fixed / realistic (ATR+volume based)
- [x] Apply spread on BOTH entry and exit (already correct — SpreadModel is side-aware)
- [x] Fix SL/TP fill priority: pessimistic reordering when both trigger in same bar

#### 1B. Fix Metrics (Backend) ✅ COMPLETE

- [x] Fix CAGR formula: use actual calendar days from timestamps (fallback: trading_days × 365/252)
- [x] Fix `pnl_pct` double-scaling bug — removed extra ×100 in best/worst_trade_pct
- [x] Standardize Sharpe ratio: annualize using √(bars_per_year) consistently (was correct)
- [x] Expectancy formula verified consistent across code paths
- [x] Add trade-duration-aware metrics: avg_trade_duration_hours, auto-detect bars_per_day
- [x] Remove dead `_compute_stats()` from runner.py (replaced by tearsheet pipeline)
- [x] Add `detect_bars_per_day()` auto-detection from timestamps
- [x] Add `bars_per_day_used` diagnostic field in metrics output

#### 1C. Unified Strategy Runner (Backend) ✅ COMPLETE

- [x] Create single `UnifiedRunner` that routes ALL strategy types through V2 engine
  - `run_unified_backtest()` in v2_adapter.py — auto-detects MSS/Gold BT/builder from config
- [x] Remove V1 `engine.py` code path (or deprecate behind feature flag)
  - API endpoint `backtest.py` now routes ALL requests through V2 unified runner
  - V1 engine.py and strategy_backtester.py deprecated with docstring warnings
- [x] Remove `strategy_backtester.py` duplication — all strategies use same runner
  - `MSSStrategy(StrategyBase)` in `v2/engine/strategies.py` replaces legacy MSS path
  - `GoldBreakoutStrategy(StrategyBase)` in `v2/engine/strategies.py` replaces legacy Gold BT path
- [x] Remove hardcoded `×100` P&L scaling — compute from actual instrument specs
  - `InstrumentSpec.pnl()` uses `contract_size` (100 for gold, 5000 for silver, etc.)
- [x] Add instrument specification system (pip value, contract size, margin req per symbol)
  - `v2/engine/instrument.py` — InstrumentSpec dataclass + catalogue (14 instruments)
  - `get_instrument_spec(symbol)` with case-insensitive lookup + suffix handling + fallback
- [x] 6 tests passing (test_phase1c.py): instrument lookup, PnL math, builder/MSS/Gold BT routing, API imports

#### 1D. Position Sizing (Backend) ✅ COMPLETE

- [x] Fixed lot size (existing) — `SizingMethod.FIXED_LOT`, backward-compatible default
- [x] Percentage risk per trade (SL-distance based) — `SizingMethod.PERCENT_RISK`
  - `risk_amount = equity × risk_pct / 100; lots = risk_amount / (sl_distance × contract_size)`
- [x] Fixed fractional (% of equity) — `SizingMethod.FIXED_FRACTIONAL`
  - `notional = equity × fractional_pct / 100; lots = notional / (entry_price × contract_size)`
- [x] Kelly criterion (based on historical win rate + avg win/loss) — `SizingMethod.KELLY`
  - `f* = (p×b − q) / b` with configurable half-Kelly scaling + rolling stats from closed trades
  - Manual overrides (`kelly_win_rate`, `kelly_avg_rr`) or auto-computed from last N trades
- [x] All sizing methods integrated into V2 portfolio model
  - `PositionSizer` created in Runner, wired to `StrategyContext._position_sizer`
  - `ctx.compute_position_size(symbol, entry, sl, direction)` available to all strategies
  - BuilderStrategy uses dynamic sizing; MSS/Gold BT also have access via ctx
  - `RunConfig.sizing` field passes `SizingConfig` through unified runner + portfolio runner
  - Rolling trade stats updated after each closed trade for Kelly criterion
  - Safety: `max_risk_pct` cap, `max_lots`/`min_lots` clamp, `lot_step` rounding
- [x] 10 tests passing (test_phase1d.py): config parsing, all 4 methods, clamping, ctx integration, unified runner

#### 1E. Data Layer (Backend) ✅ COMPLETE

- [x] OHLCV data loading with proper timestamp handling (timezone-aware)
  - `parse_timestamp()` in `data_validation.py`: handles ISO 8601 + offset, Z suffix, 11 naive formats
  - `_parse_datetime()` in `backtest.py` now delegates to robust `parse_timestamp()`
  - All timestamps normalized to UTC (offset-aware parsing + conversion)
- [x] Tick data support (TickEvent in V2 event queue)
  - `TickStore` class: loads ticks from TickData objects, dicts, or tuples
  - `DataHandler.add_ticks()` + `feed_ticks()`: generates TickEvents into EventQueue
  - TickEvent already defined in events.py (bid/ask/last/volume)
- [x] Multi-timeframe data alignment (e.g., M5 bars + H1 bars for HTF trend filter)
  - `SymbolData.resample_to_htf(tf_label)`: resamples lower-TF → higher-TF bars
  - OHLCV aggregation: O=first, H=max, L=min, C=last, V=sum
  - `htf_bar_index_for()`: O(1) base→HTF index lookup, prevents look-ahead bias
  - `DataHandler.add_htf()`: convenience method, also supports HTF indicator computation
  - `StrategyContext.get_htf_value()` / `get_htf_bar()`: strategy-facing API
  - Timeframe utilities: `parse_timeframe()`, `detect_timeframe()`, 20+ TF labels
- [x] Data validation on load (gap detection, duplicate removal, timezone normalization)
  - `validate_and_clean()`: removes NaN bars, deduplicates, sorts, repairs OHLC violations, detects gaps
  - `ValidationReport`: tracks all issues found + summary()
  - Weekend gap detection (marks Saturday/Sunday gaps as expected)
  - Wired into `_load_bars_from_csv()` — validation runs automatically on every CSV load
  - `validate_timestamps_only()`: quick monotonic check
- [x] 28 tests passing (test_phase1e.py): timestamp parsing (7), validation (8), multi-TF (3), HTF context (1), tick data (4), utilities (5)

---

### Phase 2 — Indicator Library Expansion ✅

**Goal**: 40+ indicators with consistent API, usable by both engine and chart overlay

#### 2A. Backend Indicator Engine (Backend) ✅

All indicators follow signature: `fn(ohlcv_data, **params) → dict[str, list[float]]`

**Trend Indicators:**

- [x] Ichimoku Cloud (tenkan, kijun, senkou_a, senkou_b, chikou)
- [x] Supertrend (direction + level)
- [x] Donchian Channel (upper, middle, lower)
- [x] Keltner Channel (upper, middle, lower)
- [x] Parabolic SAR
- [x] Hull Moving Average
- [x] DEMA (Double EMA)
- [x] TEMA (Triple EMA)
- [x] ZLEMA (Zero-Lag EMA)

**Oscillators:**

- [x] CCI (Commodity Channel Index)
- [x] Williams %R
- [x] MFI (Money Flow Index)
- [x] Stochastic RSI
- [x] ROC (Rate of Change)
- [x] Awesome Oscillator

**Volume:**

- [x] OBV (On-Balance Volume)
- [x] VWAP Bands (VWAP ± N standard deviations)
- [x] A/D Line (Accumulation/Distribution)
- [x] CMF (Chaikin Money Flow)
- [x] Volume Profile (price-level histogram — simplified for backtest)

**Volatility:**

- [x] ATR Bands (price ± ATR×N)
- [x] Historical Volatility (rolling std dev of log returns, annualized)
- [x] Standard Deviation Channel (regression line ± N×σ)

**Smart Money / ICT Concepts:**

- [x] Order Blocks (last bullish/bearish candle before impulsive move)
- [x] Fair Value Gaps (FVG — triple-candle gap detection)
- [x] Liquidity Sweeps (sweep of swing high/low followed by reversal)
- [ ] Breaker Blocks (deferred — depends on order block invalidation logic)

**Session / Time:**

- [x] Session High/Low (London, NY, Asia — configurable open/close times)
- [x] Kill Zone markers (London open 02:00-05:00, NY open 07:00-10:00 UTC)
- [x] Previous Day High/Low/Close
- [x] Weekly Open level

#### 2B. Frontend Indicator Catalogue (Frontend) ✅

- [x] Expand `INDICATOR_TYPES` array in StrategyEditor from 13 → 43 entries
- [x] Add categories/groups to indicator selector (Trend, Oscillators, Volume, Volatility, Levels, Smart Money, Session)
- [x] Each indicator: proper `defaultParams`, `subKeys`, `overlay` flag, category tag
- [x] Searchable + grouped combobox (IndicatorCombobox upgraded with CommandGroup per category)

#### 2C. Indicator Compute API (Backend) ✅

- [x] `POST /api/backtest/indicators/compute` — given datasource + indicator configs, return computed values
- [x] Returns timestamps + indicator arrays with NaN→null JSON serialization

**Bug fix**: Normalised `SymbolData.load_bars()` to convert datetime→float Unix timestamps, fixing compatibility with all timestamp-consuming indicators.

**Tests**: 69 Phase 2 tests + 48 Phase 1 regression tests = 117 total, all passing.
- [ ] Used by chart overlay to draw indicators on live/historical data
- [ ] Cached computation (same data + same params = cached result)

---

### Phase 3 — Strategy Builder Overhaul ✅ COMPLETE

**Goal**: Advanced rule logic, entry templates, expanded SL/TP, comprehensive filters

#### 3A. Rule Engine — IF/THEN/ELSE (Backend + Frontend) ✅

- [x] New condition model: `ConditionGroup` with `node_type: "condition" | "group" | "if_then_else"`
- [x] Nested groups: `{ if_cond: ConditionGroup, then_cond: ConditionGroup, else_cond: ConditionGroup }`
- [x] Backend evaluation engine for nested condition trees (`condition_engine.py` — ~490 lines)
- [x] Dual-key normalisation: accepts both legacy (`type`/`conditions`/`logic`) and canonical (`node_type`/`children`/`group_logic`) keys
- [x] Migrate existing flat AND/OR rules to new model (backward compatible via `normalise_rules()`)
- [x] Deduplicated 4 copies of condition evaluation → single `condition_engine.py` delegation in `v2_adapter.py` (BuilderStrategy + MultiSymbolBuilderStrategy) and `v2/compat/adapter.py`

#### 3B. Entry Type Templates (Frontend) ✅

- [x] 6 pre-built entry templates with auto indicator provisioning and ID remapping
- [x] **MA Crossover**: Fast EMA(9) crosses above/below slow EMA(21)
- [x] **Bollinger Breakout**: Price breaks above upper / below lower BB(20,2)
- [x] **RSI Bounce**: RSI(14) crosses above 30 (long) / below 70 (short)
- [x] **EMA Pullback**: Price touches EMA(50) + RSI confirmation
- [x] **Engulfing + Trend**: Engulfing candlestick pattern + EMA(50) trend direction
- [x] **Session Momentum**: MACD crossover (time-based filtering via Filters tab)
- [x] Templates insert editable condition rows; auto-add missing indicators
- [x] Collapsible Quick Templates accordion in Entry Rules tab

#### 3C. Candlestick Pattern Engine (Backend) ✅

- [x] `patterns.py` — 16 pattern detection functions (~340 lines)
- [x] Each returns signal series: +1 (bullish), -1 (bearish), 0 (no signal)
- [x] Patterns: engulfing, pin_bar, doji, hammer, inverted_hammer, morning_star, evening_star, inside_bar, outside_bar, three_white_soldiers, three_black_crows, harami, tweezer_top, tweezer_bottom, shooting_star, spinning_top
- [x] `detect_pattern()` dispatcher + `PATTERN_CATALOGUE` dict
- [x] Wired into `data_handler.py` as `CANDLE_PATTERN` indicator type
- [x] 16 entries added to frontend `INDICATOR_TYPES` catalogue (Candlestick category)

#### 3D. SL/TP Expansion (Backend + Frontend) ✅

- [x] Structure-based SL type + SL buffer (pips)
- [x] Multi-target TP (TP1/TP2/TP3) with 3-way lot split
- [x] Move SL to TP1 level on TP2 hit option
- [x] Frontend: TP3 row, conditional 2-way/3-way lot split, SL buffer input

#### 3E. Trade Filters Expansion (Backend + Frontend) ✅

- [x] Session presets (London, NY, Asia, LDN/NY Overlap) — auto-fill time_start/time_end
- [x] Kill zone presets (London Open, NY Open, London Close)
- [x] Trend direction filter (SMA/EMA indicator + period)
- [x] Max spread filter (pips)
- [x] Max trades per day limit
- [x] Consecutive loss pause
- [x] Frontend: expanded Filters tab with all new sections
- [x] Backend: `passes_filters()` in condition_engine handles all new filter types

#### 3F. Schema & Model Updates (Backend) ✅

- [x] `ConditionGroup` Pydantic model (recursive, with leaf/group/if_then_else fields)
- [x] Extended `RiskParams`: TP3 type/value, SL buffer, `move_sl_to_tp1_on_tp2`, 3-element `lot_split`
- [x] Extended `FilterConfig`: 7 new fields (session_preset, kill_zone_preset, trend filter, spread, max trades, consecutive loss)
- [x] Frontend `types/index.ts` mirrors all backend schema changes
- [x] Backward compatibility: `normalise_rules()` auto-wraps old flat conditions

**Tests**: 53 tests in `test_phase3.py` — all passing (170 total across all phases)

---

### Phase 4 — Visual Node Editor (Frontend) ✅ COMPLETE

**Goal**: Drag-and-drop visual strategy builder for complex strategies

#### 4A. Node Editor Framework ✅

- [x] Chose React Flow (`@xyflow/react` v12) — typed, handles zoom/pan/connections
- [x] Node types: Indicator, Price, Constant, Condition, Logic Gate (AND/OR/NOT), IF/THEN/ELSE, Pattern, Filter, Entry Signal, Exit Signal
- [x] Edge types: Data flow (indicator → condition input), Logic flow (condition → gate → signal)
- [x] Canvas with zoom (0.3–2x), pan, minimap, snap-to-grid (15px), dot background

#### 4B. Node Types ✅

- [x] **Indicator Node**: Select indicator type + configure params → outputs signal values
- [x] **Price Node**: Outputs open/high/low/close/volume via dropdown
- [x] **Constant Node**: Numeric value input → outputs value
- [x] **Condition Node**: Two inputs + operator (7 operators) → outputs boolean
- [x] **Logic Gate Node**: AND/OR/NOT — combines boolean inputs
- [x] **IF/THEN/ELSE Node**: Condition input + two logic branches
- [x] **Pattern Node**: 16 candlestick patterns → outputs boolean signal
- [x] **Filter Node**: 6 filter types → gates signal flow
- [x] **Entry Signal Node**: Final output — triggers trade when input is true
- [x] **Exit Signal Node**: Final output — triggers close when input is true

#### 4C. Serialization ✅

- [x] Convert node graph → JSON strategy definition (`graphToStrategy()`)
- [x] Convert JSON strategy definition → node graph (`strategyToGraph()`)
- [x] User can switch between form view and visual view of same strategy
- [x] 11 vitest roundtrip tests passing

#### 4D. UI Integration ✅

- [x] Form / Visual toggle in StrategyEditor with lazy-loaded React Flow
- [x] Visual editor shares same save/load logic as form builder via onSync callback
- [x] Dirty state indicator + Sync→Form / Reload buttons

---

### Phase 5 — Chart Overlay ✅

**Goal**: Draw indicators + trade signals on Trading page chart and backtest results chart

#### 5A. Trading Page Chart Overlay (Frontend) ✅

- [x] Collapsible sidebar panel on Trading page chart (`StrategyOverlayPanel.tsx`)
- [x] Strategy selector: dropdown of user's strategies
- [x] On select: call `/api/backtest/indicators/compute` with strategy's indicator configs + datasource
- [x] Draw overlay indicators using Lightweight Charts v5 API:
  - Price overlays (MAs, Bollinger, Ichimoku cloud, etc.) as LineSeries
  - Oscillators in sub-panes (RSI, MACD, Stochastic, etc.) with separate priceScaleId
- [x] Toggle individual indicator visibility (Eye/EyeOff icons)
- [x] Works with static data sources (datasource auto-loaded on mount)
- [x] Helper library: `chartIndicators.ts` (addIndicatorLine, removeOverlayLines, buildTradeMarkers, colour palette)

#### 5B. Backtest Results Chart Overlay (Frontend) ✅

- [x] After backtest completes, draw full candlestick chart (`BacktestTradeChart.tsx`):
  - Entry markers (green ▲ for long, red ▼ for short) via `createSeriesMarkers` (LW Charts v5 plugin)
  - Exit markers with P&L label (✕ +/-amount)
  - Volume histogram pane
  - Equity curve overlay on separate "equity" price scale
  - Indicator overlays from strategy config
- [x] "Trade Chart" tab added between Equity Curve and Trade Log
- [x] `scrollToTime()` imperative handle for trade-list click-to-scroll

#### 5C. Backend Support ✅

- [x] Include indicator values computed via `SymbolData.compute_indicators()` in chart-data response
- [x] Include chart marks (entry/exit coordinates with direction, price, P&L) in backtest results
- [x] Endpoint: `GET /api/backtest/{id}/chart-data` — returns OHLCV bars + indicators + trade marks + equity curve
- [x] Backtest save updated to persist `trades` and `equity_curve` in DB results blob
- [x] Tests: 23 backend (test_phase5.py) + 10 frontend vitest (chartIndicators.test.ts) — all passing

---

### Phase 6 — Optimizer Upgrade  ✅ COMPLETE

**Goal**: Parallel optimization, V2-routed, with early stopping and walk-forward

#### 6A. Parallel Execution ✅

- [x] Use `concurrent.futures.ThreadPoolExecutor` for parallel backtest runs
- [x] Configurable `max_workers` (default: CPU count - 1, 0 = auto)
- [x] Each worker runs independent V2 engine instance via `_parallel_evaluate_deap()` / `_parallel_evaluate_builtin()`
- [x] Sequential fallback when `max_workers=1`

#### 6B. Route Through V2 ✅

- [x] All optimizer runs use `run_unified_backtest()` + `v2_result_to_v1()` (V2 adapter)
- [x] Removed V1 `BacktestEngine` import from optimizer engine
- [x] Parameter grid/search works with any strategy type (builder, file-based, MSS, Gold BT)
- [x] File-based strategies still use `file_runner` directly

#### 6C. Early Stopping ✅

- [x] Convergence detection: `early_stop_patience` — stop if best metric hasn't improved in N trials
- [x] Max drawdown abort: `max_dd_abort` — penalise trial to -1e6 if DD exceeds threshold
- [x] Time budget: `time_budget_seconds` — optional max runtime limit
- [x] All search methods (Bayesian, Genetic, Built-in GA, Random) check `_should_early_stop()`

#### 6D. Walk-Forward Integration ✅

- [x] Walk-forward validation generalised to ALL strategy types (not just MSS/Gold BT)
- [x] Anchored + rolling window options preserved
- [x] `walk_forward.py` uses `run_unified_backtest()` + `v2_result_to_v1()`
- [x] Legacy callers auto-wrapped into full strategy_config
- [x] `symbol` parameter threaded through optimizer → walk-forward → V2 runner

**Tests**: 27 tests in `test_phase6.py` (parallel eval, V2 routing, early stopping, walk-forward, schema)

---

## Implementation Priority

```
Phase 1 (Engine Core)     ──── MUST DO FIRST ────  ~3-5 days
Phase 2 (Indicators)      ──── Foundation ────────  ~3-4 days
Phase 3 (Strategy Builder) ─── Core feature ──────  ~4-6 days
Phase 5 (Chart Overlay)   ──── COMPLETE ───────────  done
Phase 6 (Optimizer)       ──── COMPLETE ───────────  done
Phase 4 (Visual Editor)   ──── COMPLETE ───────────  done
```

**Recommended start**: Phase 1A → 1B → 1C → 1D → 2A (batch 1: trend + oscillators) → 3A → 3B → 2A (batch 2: volume + volatility + ICT) → 3C → 3D → 3E → 5A → 5B → 6A → 6B → 4A-D

---

## Files to Create/Modify

### New Files

| File | Purpose |
|---|---|
| `backend/app/services/backtest/v2/engine/unified_runner.py` | Single entry point for all backtests |
| `backend/app/services/backtest/v2/instruments.py` | Instrument specs (pip value, contract size, margin) |
| `backend/app/services/backtest/indicators_v2.py` | New indicator library (40+ indicators) |
| `backend/app/services/backtest/patterns.py` | Candlestick pattern detection engine |
| `backend/app/services/backtest/condition_engine.py` | Nested IF/THEN/ELSE condition evaluator |
| `backend/app/api/indicators.py` | `/api/indicators/compute` endpoint |
| `frontend/src/components/StrategyNodeEditor.tsx` | Visual node-based strategy editor |
| `frontend/src/components/ChartOverlay.tsx` | Chart overlay panel (indicator + signal rendering) |
| `frontend/src/components/ConditionTreeBuilder.tsx` | Nested condition group builder UI |
| `frontend/src/components/EntryTemplates.tsx` | Pre-built entry type template selector |
| `frontend/src/lib/chartIndicators.ts` | Lightweight Charts indicator rendering helpers |

### Modified Files

| File | Changes |
|---|---|
| `backend/app/services/backtest/v2/engine/runner.py` | Fix ATR/volume passthrough to fill model |
| `backend/app/services/backtest/v2/analytics/metrics.py` | Fix CAGR, pnl_pct, standardize Sharpe |
| `backend/app/services/backtest/v2/execution/fill_model.py` | Activate slippage models, add exit spread |
| `backend/app/services/optimize/engine.py` | Parallel execution, V2 routing, early stopping |
| `backend/app/services/backtest/walk_forward.py` | Generalize to all strategy types, re-optimize per fold |
| `backend/app/schemas/strategy.py` | ConditionGroup model, expanded FilterConfig, TP3, patterns |
| `backend/app/models/strategy.py` | (JSON columns — minimal changes needed) |
| `frontend/src/components/StrategyEditor.tsx` | Expanded INDICATOR_TYPES, new filter sections, TP3, template insertion, form/visual toggle |
| `frontend/src/components/CandlestickChart.tsx` | Indicator overlay rendering, trade signal markers |
| `frontend/src/app/trading/page.tsx` | Strategy overlay panel, indicator display toggle |
| `frontend/src/app/backtest/page.tsx` | Trade signal markers on results chart |
| `frontend/src/types/index.ts` | New types for ConditionGroup, chart overlay, indicator compute |

---

## Notes

- **Backward compatibility**: Existing strategies (MSS, Gold BT, existing builder strategies) must continue to work. New schema wraps old flat conditions in a single AND group.
- **JSON columns**: Strategy model uses JSON columns for indicators, rules, risk_params, filters — schema changes are additive, no DB migration needed for most changes.
- **Performance**: Indicator library should use NumPy where available for large datasets (>100k bars). Pure Python fallback for small datasets.
- **Testing**: Each phase should include unit tests for critical paths (fill model accuracy, indicator correctness, condition evaluation logic).
