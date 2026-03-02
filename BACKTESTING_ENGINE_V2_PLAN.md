# TradeForge Backtesting Engine V2 — Implementation Plan

## Design Philosophy
- **Same code for backtest and live** — no logic divergence between simulation and production
- **Event-driven with a proper event queue** — not a flat bar loop
- **Rust/C hot path, Python orchestration** — 100x+ speed for RL training loops
- **Real tick simulation with OHLCV fallback** — honest about what the data can tell us
- **Portfolio-aware from day one** — multi-symbol shared capital, correlation tracking
- **V1 stays live in parallel** — backward compatibility adapter so existing strategies don't break

## Research Sources
Studied and borrowed ideas from:
- **backtesting.py** (8k stars) — metrics set, indicator warm-up system, OCO bracket orders
- **vectorbt** (6.8k stars) — Monte Carlo random signal baseline, parameter heatmaps
- **NautilusTrader** (20.4k stars) — event-driven architecture, Order/Position/Portfolio model, Rust core
- **QuantStats** (6.8k stars) — full tearsheet metrics (30+), Monte Carlo simulation API
- **Freqtrade** — look-ahead bias detection via shifted data re-runs
- **QSE** (C++) — tick-level fill model with liquidity consumption, per-symbol slippage

---

## Architecture Overview

```
                        ┌──────────────────────────────────────────┐
                        │           TradeForge Engine v2            │
                        │                                          │
  Data Layer            │  DataHandler  ──►  EventQueue            │
  (tick/OHLCV) ────────►│                      │                   │
                        │                PortfolioManager          │
  Strategy              │               (capital, margin,          │
  (user-defined) ──────►│                correlation)              │
                        │                      │                   │
                        │         ┌────────────┴──────────┐        │
                        │     OrderRouter           RiskManager    │
                        │         │                      │         │
                        │     ExecutionEngine     PositionBook     │
                        │     (Rust/C core)              │         │
                        │         │                      │         │
                        └─────────┼──────────────────────┼─────────┘
                                  │                      │
                            TearsheetEngine        EventLog
                            (full analytics)       (replay)
```

---

## File Structure

```
backend/app/services/backtest/
  v2/
    __init__.py
    engine/
      __init__.py
      events.py              ← All event types (Bar, Tick, Signal, Order, Fill, Cancel)
      order.py               ← Order, Fill, OrderBook — proper order lifecycle
      position.py            ← Position, PositionBook — multi-fill tracking
      portfolio.py           ← Portfolio — shared capital, margin, equity curve
      event_queue.py         ← Nanosecond-resolution heap-based priority queue
      data_handler.py        ← Feeds bar/tick events, warm-up enforcement, multi-symbol sync
      risk_manager.py        ← Pre-trade risk validation (margin, max positions, drawdown cutoff)
      strategy_base.py       ← Abstract base: on_bar(), on_tick(), on_fill()
      runner.py              ← Main event loop: dispatches events, coordinates subsystems
    execution/
      __init__.py
      fill_model.py          ← Pluggable: FixedSlippage, VolatilitySlippage, VolumeImpact
      tick_engine.py         ← Intra-bar fill logic (limit, stop, stop-limit)
      synthetic_ticks.py     ← Brownian bridge OHLCV→ticks
      gap_handler.py         ← Overnight/weekend gap fill rules
    analytics/
      __init__.py
      metrics.py             ← 30+ metrics (CAGR, Calmar, Sortino, Omega, Kelly, VaR, etc.)
      monte_carlo.py         ← Trade resample simulation (1000 paths)
      tearsheet.py           ← Assembles full report dict for API/frontend
      benchmark.py           ← Buy-and-hold comparison, Alpha, Beta, Information Ratio
      rolling.py             ← Rolling Sharpe, Sortino, Volatility, Beta
    validation/
      __init__.py
      lookahead.py           ← Look-ahead bias detector (Freqtrade approach)
      robustness.py          ← Walk-forward stability scorer (0-100)
    compat/
      __init__.py
      adapter.py             ← V1→V2 backward compatibility adapter
    core/                    ← Rust crate (Phase 5)
      Cargo.toml
      src/lib.rs
      python_bindings.py     ← PyO3 wrapper
```

---

## Phase 1 — Core Architecture Rebuild ✅ DONE
**Goal:** Replace flat Trade dataclass + bar loop with proper event-driven system.
**Estimated effort:** ~4 weeks

### New Object Model

| Object | Replaces | Key Fields |
|---|---|---|
| `Order` | implicit entry/exit | `id`, `type` (MKT/LMT/STP/STP_LMT), `side` (BUY/SELL), `size`, `limit_px`, `stop_px`, `tif`, `linked_orders` (OCO/bracket), `status` |
| `Fill` | Trade.entry/exit | `order_id`, `timestamp_ns`, `price`, `size`, `slippage`, `commission` |
| `Position` | Trade | `symbol`, `side`, `size`, `avg_entry`, `unrealized_pnl`, `realized_pnl`, `fills[]` |
| `Portfolio` | balance float | `cash`, `positions{}`, `equity_curve`, `margin_used`, `total_equity` |
| `EventQueue` | bare bar loop | heap of BarEvent, TickEvent, OrderEvent, FillEvent, SignalEvent sorted by timestamp_ns |

### Event Loop
```
while events:
    event = queue.pop()
    if BarEvent    → data_handler.update() → strategy.on_bar()
    if TickEvent   → data_handler.update() → strategy.on_tick()
    if SignalEvent → risk_manager.validate() → order_router.submit()
    if OrderEvent  → execution_engine.process() → FillEvent
    if FillEvent   → portfolio.update() → position_book.update() → strategy.on_fill()
```

### Phase 1 Deliverables
- [x] `engine/events.py` — all event types
- [x] `engine/order.py` — Order, Fill, OrderBook with full lifecycle
- [x] `engine/position.py` — Position with multi-fill tracking
- [x] `engine/portfolio.py` — Portfolio manager (multi-symbol ready)
- [x] `engine/event_queue.py` — heap priority queue
- [x] `engine/data_handler.py` — bar/tick feed with warm-up enforcement
- [x] `engine/risk_manager.py` — pre-trade risk checks
- [x] `engine/strategy_base.py` — abstract base class for strategies
- [x] `engine/runner.py` — main event loop
- [x] `compat/adapter.py` — backward compatibility with v1 config format

---

## Phase 2 — Tick-Level Fill Model ✅ DONE
**Goal:** Honest simulation of what price you actually get filled at.
**Estimated effort:** ~3 weeks (after Phase 1)

### Fill Modes (auto-selected based on data)

| Mode | Trigger | Fill Logic |
|---|---|---|
| **Real tick** | User uploads tick CSV | Direct tick stream → find exact touch, consume liquidity |
| **M1 synthetic** | M1 bars available | Brownian bridge within each M1 bar → synthetic tick path |
| **OHLCV synthetic** | Only OHLCV | Brownian bridge within bar (O→H/L→C path with random branch) |

### Realistic Fill Components
```
fill_price = signal_price
           + spread_half          # half-spread at fill side
           + slippage             # configurable: fixed_pts | pct_atr | vol_adjusted
           + market_impact        # for large size: linear(size / avg_volume)
           - rebate               # if limit order = maker rebate
```

### Intra-bar Fill Rules
- `MARKET` → fill at next tick/bar open + slippage
- `LIMIT` → fill only if L ≤ limit (long) or H ≥ limit (short); fill at limit price
- `STOP_MARKET` → trigger if H/L touched; fill at stop + slippage (gap risk: if bar opens beyond stop, fill at open)
- `STOP_LIMIT` → trigger if H/L touched; fill at limit or better, else no fill
- **Gap handling** — if overnight/weekend gap jumps over stop, fill at open price (not stop)

### Phase 2 Deliverables
- [x] `execution/fill_model.py` — FixedSlippage, VolatilitySlippage, VolumeImpact, CompositeFillModel pipeline
- [x] `execution/tick_engine.py` — core fill logic with intra-bar order matching (OHLC_FIVE + BROWNIAN modes)
- [x] `execution/synthetic_ticks.py` — Brownian bridge from OHLCV (3-segment O→H/L→L/H→C)
- [x] `execution/gap_handler.py` — overnight/weekend gap detection and fill-at-open rules
- [x] `engine/runner.py` — integrated tick engine (replaces old simple order matching)
- [ ] `data/tick_loader.py` — tick CSV parser, timestamp normalization (deferred to Phase 5)

---

## Phase 3 — Full Tearsheet Analytics  ✅ DONE
**Goal:** Every metric that matters for professional strategy evaluation.
**Completed:** 55 metrics, Monte Carlo, benchmark, rolling stats, tearsheet assembler.

### New Metrics

**Return metrics:**
- CAGR — `(final / initial) ^ (365 / days) - 1`
- Annualized Return, Annualized Volatility
- CAGR / Volatility ratio

**Risk-adjusted ratios:**
- Calmar Ratio (CAGR / |max_dd%|) — the most respected single ratio in managed futures
- Sortino Ratio — penalizes only downside volatility
- Omega Ratio — probability-weighted upside/downside
- Gain-to-Pain Ratio (Schwager) — sum(positive months) / sum(|negative months|)
- Ulcer Index — RMS of drawdown depth
- Ulcer Performance Index — return / ulcer_index

**Risk metrics:**
- VaR (95%, 99%) — daily return at 5th percentile
- CVaR / Expected Shortfall — mean of returns below VaR
- Max Drawdown Duration (bars/days from peak to recovery)
- Avg Drawdown depth and Avg Recovery Time
- Risk of Ruin — probability of hitting specified loss threshold

**Trade-level:**
- Best/Worst Trade [%] (not just $)
- Avg Win Duration / Avg Loss Duration
- Consecutive Wins / Losses (max streaks)
- Kelly Criterion
- Exposure Time [%]
- Total Fees Paid (cumulative)

**Benchmark comparison:**
- Alpha, Beta (OLS regression vs buy-and-hold)
- Information Ratio — alpha / tracking error
- Buy-and-Hold return for same period and capital

### Phase 3 Deliverables
- [x] `analytics/metrics.py` — 55 metrics computed from equity curve + trades
- [x] `analytics/monte_carlo.py` — resample trades 1000x, bust/goal probability, equity fan
- [x] `analytics/tearsheet.py` — assembles full report for API (metrics + MC + benchmark + rolling)
- [x] `analytics/benchmark.py` — buy-and-hold, alpha, beta, information ratio, correlation, R²
- [x] `analytics/rolling.py` — rolling Sharpe, Sortino, Volatility, Beta, Drawdown, Win Rate
- [ ] Frontend: monthly returns heatmap, rolling charts, drawdown plot, Monte Carlo fan, trade duration histogram, return distribution histogram

---

## Phase 4 — Multi-Symbol Portfolio
**Goal:** Share capital across symbols, correlation tracking, portfolio-level risk.
**Estimated effort:** ~3 weeks (after Phase 1+2)

### Features
- Shared capital pool — cash decremented by each position across all symbols
- Margin model — CFD/Forex: margin = size × price × margin_rate; stocks: full notional
- Rolling correlation matrix (Pearson + Spearman) between open positions
- Portfolio-level max drawdown — on total equity, not per-symbol
- Capital allocation — fixed-fraction per symbol, or Kelly-weighted per symbol
- Cross-symbol signals — strategy reads one symbol's data as filter while trading another
- Data synchronization — align bars across symbols by timestamp

### Phase 4 Deliverables
- [ ] `engine/portfolio.py` extended for multi-symbol capital management
- [ ] `engine/data_handler.py` — synchronized multi-symbol bar delivery
- [ ] `analytics/correlation.py` — rolling Pearson/Spearman matrix
- [ ] API: `POST /backtest/run` accepts `symbols: list[str]`

---

## Phase 5 — Rust/C Inner Loop  ✅ DONE
**Goal:** 100x+ speed to enable RL training loops and large parameter sweeps.
**Completed:** Full Rust crate (PyO3) + Python fallback + auto-select wrapper + runner integration.

### What goes in Rust
- Event queue dispatch (hot path, millions of calls)
- Tick stream processing (per-tick fill logic)
- Indicator calculation (rolling window math: SMA, EMA, ATR, BB)
- Portfolio mark-to-market (called every tick)
- Fill execution logic (price comparison, gap logic, partial fills)

### What stays in Python
- Strategy logic (on_bar, on_tick) — user-written, must be readable
- Analytics/tearsheet — one-time aggregation at end
- ML model inference — PyTorch/sklearn
- API layer — FastAPI

### Interface
```python
from tradeforge_engine import BacktestCore
core = BacktestCore(config)
core.run(bars, strategy_fn)  # strategy_fn is a Python callback
result = core.get_result()   # serialized back to Python
```

### Phase 5 Deliverables
- [x] `core/` — Rust crate (Cargo.toml, src/lib.rs, types.rs, event_queue.rs, portfolio.rs, tick_matcher.rs, indicators.rs, runner.rs)
- [x] PyO3 bindings: FastRunner, FastPortfolio, IndicatorSet (SMA/EMA/ATR/BB)
- [x] Python fallback engine (identical logic, pure Python) — used if Rust build fails
- [x] Auto-select wrapper (`python_bindings.py`) — tries Rust, falls back to Python
- [x] Runner integration (`use_fast_core=True` flag in RunConfig)
- [x] Build script (`build_rust_core.py`) for maturin-based compilation
- [x] 10/10 smoke tests passing (indicators, queue, portfolio, runner, integration, benchmark)

---

## Phase 6 — Testing & Validation Layer  ✅ DONE
**Goal:** Statistical tools to validate strategy robustness before deployment.
**Completed:** Look-ahead bias detector + walk-forward robustness scorer (0–100).

### Monte Carlo Simulation
1. Collect closed trade PnL list [t1, t2, ..., tN]
2. For i in 1..1000: shuffle randomly (resample with replacement), replay as equity curve
3. Report: median final equity, 5th/95th percentile, bust probability, goal probability
4. Insight: if real curve is near top of 1000 random shuffles → lucky ordering, not edge

### Strategy Robustness Score (0-100)
- Run walk-forward across N windows
- Score = (% windows profitable) × (Sharpe sign consistency) × (1 - variance of CAGR)
- Flag: "This strategy only worked in 2 of 6 windows — likely overfit"

### Look-Ahead Bias Detection (Freqtrade approach)
1. Run full backtest: record all signal timestamps and directions
2. Re-run with data truncated at bar N (for sample of N values)
3. If signal at bar N-10 changes when bar N is appended → look-ahead confirmed
4. Root cause: indicator using future data or rolling on full array

### Phase 6 Deliverables
- [x] `validation/lookahead.py` — bias detector (signal capture + truncated re-run comparison)
- [x] `validation/robustness.py` — walk-forward stability scorer (5-component weighted score 0–100)

---

## Build Sequence

```
Phase 1: Architecture Rebuild         ████████████████████  ✅ DONE
  └─ Events, Orders, Positions, Portfolio, Runner
  └─ Backward compat adapter

Phase 2: Tick Fill Model              ████████████████████  ✅ DONE
  └─ OHLCV synthetic ticks
  └─ 5-tick OHLC path, gap detection

Phase 3: Analytics Tearsheet          ████████████████████  ✅ DONE
  └─ 55 metrics, Monte Carlo, rolling, benchmark

Phase 4: Multi-symbol Portfolio       ░░░░░░░░░░░░░░░░░░░░  TODO

Phase 5: Rust Core                    ████████████████████  ✅ DONE
  └─ Pure Python fallback ships first
  └─ Rust replaces hot paths in drop-in
  └─ 165k bars/sec (fallback), 100x+ target with Rust

Phase 6: Testing/Validation Suite     ████████████████████  ✅ DONE
  └─ Look-ahead bias detection, Robustness scoring
```

---

## V1 vs V2 Metrics Comparison

| Metric | V1 Now | V2 Target |
|---|---|---|
| Win Rate | ✅ | ✅ |
| Profit Factor | ✅ | ✅ |
| Max Drawdown $ / % | ✅ | ✅ |
| Sharpe Ratio | ✅ (trade-based) | ✅ (equity-curve + trade-based) |
| SQN | ✅ | ✅ |
| Expectancy | ✅ | ✅ |
| Yearly PnL | ✅ | ✅ |
| CAGR | ❌ | ✅ Phase 3 |
| Calmar Ratio | ❌ | ✅ Phase 3 |
| Sortino Ratio | ❌ | ✅ Phase 3 |
| Omega Ratio | ❌ | ✅ Phase 3 |
| Kelly Criterion | ❌ | ✅ Phase 3 |
| Max DD Duration | ❌ | ✅ Phase 3 |
| Avg DD / Duration | ❌ | ✅ Phase 3 |
| Exposure Time % | ❌ | ✅ Phase 3 |
| VaR / CVaR | ❌ | ✅ Phase 3 |
| Ulcer Index | ❌ | ✅ Phase 3 |
| Consecutive Win/Loss | ❌ | ✅ Phase 3 |
| Alpha / Beta | ❌ | ✅ Phase 3 |
| Monte Carlo | ❌ | ✅ Phase 3 DONE |
| Robustness Score | ❌ | ✅ Phase 6 DONE |
| Look-ahead Detection | ❌ | ✅ Phase 6 DONE |
| Multi-symbol | ❌ | ✅ Phase 4 |
| Tick fills | ❌ | ✅ Phase 2 |
| Realistic slippage | ❌ (spread only) | ✅ Phase 2 |
| Gap handling | ❌ | ✅ Phase 2 |
| Rust performance | ❌ | ✅ Phase 5 |

---

## Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Inner loop language | Rust via PyO3 | 100x speed, RL training support |
| Tick data | Synthetic + real | Honest fallback, no forced new data format |
| Portfolio scope | Multi-symbol from day one | Shared capital is the realistic constraint |
| Fill model | Intra-bar with gap handling | Gap fills are where 80% of backtest lies are |
| Architecture | Full rebuild in v2/ directory | Clean design; v1 stays live in parallel |
| Python fallback | Always available | Rust build can fail; Python fallback ships first |
