# Backtesting Engine Comparison & TradeForge Architecture Audit

## Table of Contents
1. [Professional Engine Profiles](#1-professional-engine-profiles)
2. [TradeForge Architecture Audit](#2-tradeforge-architecture-audit)
3. [Side-by-Side Comparison Matrix](#3-side-by-side-comparison-matrix)
4. [Weakness Analysis](#4-weakness-analysis)
5. [Recommendations](#5-recommendations)

---

## 1. Professional Engine Profiles

### 1.1 NautilusTrader

| Dimension | Details |
|-----------|---------|
| **Core Architecture** | Event-driven with single-threaded deterministic event ordering. Rust core (21+ crates) with Python/Cython bindings via PyO3/cbindgen. Domain-driven design with Ports & Adapters pattern. Central `NautilusKernel` orchestrates `MessageBus` (pub/sub + req/rep), `Cache`, `DataEngine`, `ExecutionEngine`, `RiskEngine`. Same code runs backtest, sandbox, and live trading. `BacktestEngine` (low-level) and `BacktestNode` (high-level) APIs. Crash-only design philosophy. |
| **Order Execution** | Full order lifecycle: MARKET, LIMIT, STOP_MARKET, STOP_LIMIT, MARKET_IF_TOUCHED, LIMIT_IF_TOUCHED, TRAILING_STOP_MARKET, TRAILING_STOP_LIMIT, MARKET_TO_LIMIT. Three-phase main loop per data point: (1) Exchange processes data + iterates matching engine, (2) Strategy receives data via callbacks, (3) Settle venues (drain commands, iterate matching until no pending commands). Cascading orders settle within the same timestamp. `LatencyModel` support for simulated network latency with inflight queuing. |
| **SL/TP Management** | Bracket orders (entry + SL + TP as linked group). OCO (One-Cancels-Other) for SL/TP pairs. Trailing stops with activation price. Bar-based execution: gap scenario fills at open; move-through scenario fills at trigger price. Adaptive H/L ordering (`bar_adaptive_high_low_ordering`) achieves ~75-85% accuracy in predicting intra-bar H/L sequence, critical for determining which of SL or TP fires first. |
| **Slippage/Commission** | **Fill Models** (12+ pluggable): `FillModel` (probabilistic `prob_slippage`, `prob_fill_on_limit`), `OneTickSlippageFillModel`, `TwoTierFillModel`, `ThreeTierFillModel`, `ProbabilisticFillModel`, `SizeAwareFillModel`, `LimitOrderPartialFillModel`, `MarketHoursFillModel`, `VolumeSensitiveFillModel`, `CompetitionAwareFillModel`, `BestPriceFillModel`. Custom models via `get_orderbook_for_fill_simulation()` generating synthetic order books. L2/L3: real book-walking fills with partial fills across price levels. L1: probabilistic slippage, 1-tick adversarial. Price protection (max slippage boundary). Liquidity consumption tracking to prevent duplicate fills. Commission via `MakerTakerFeeModel` or custom. **Margin models**: `StandardMarginModel`, `LeveragedMarginModel`, custom. |
| **Bar vs Tick Simulation** | Supports **L3** (market-by-order), **L2** (market-by-price), **L1** (top-of-book quotes), **Trade ticks**, and **Bars** in descending order of granularity. Bar execution converts OHLC into 4 price points (O→H→L→C or adaptive ordering) with volume split 25% each. Internal order book maintained even for bar data. Tick data provides true event-by-event simulation. Trade-based execution with aggressor-side modeling. Queue position tracking for limit orders. Nanosecond timestamp resolution. |
| **Position Management** | Full netting and hedging OMS modes. Multi-venue, multi-instrument, multi-strategy simultaneously. Cash, Margin, and Betting account types. Position sizing handled by strategy logic. Reduce-only orders supported. Portfolio-level tracking across all venues. |
| **Robustness Testing** | Not built-in (no native walk-forward, Monte Carlo, or robustness scoring). Relies on `BacktestNode` repeated runs with config variations. Parameter optimization via external orchestration. Deterministic results with fixed `random_seed` in FillModel. Strategy development typically done in Jupyter notebooks with custom analysis. |
| **Performance Metrics** | Via `analysis` subpackage and external visualization (`Visualization` concept). Generates tearsheets. Standard metrics (returns, Sharpe, Sortino, max drawdown, etc.) via portfolio analyzer. Reports module for detailed performance data. |
| **Data Handling** | Parquet-native via `ParquetDataCatalog`. Streaming API for datasets exceeding RAM (automatic chunking via generators, manual chunking via `streaming=True`). Deferred sorting optimization for multi-instrument loading. Strict precision invariants (price_precision, size_precision) enforced at matching engine level. Supports custom data types. Bar timestamp convention enforcement (ts_init must represent close time). |

**Key Strengths**: Production-grade execution realism (L1-L3 order book simulation, queue position tracking, liquidity consumption, price protection), Rust performance with Python flexibility, backtest-live parity, institutional-quality fill modeling.

---

### 1.2 Backtrader

| Dimension | Details |
|-----------|---------|
| **Core Architecture** | Event-driven, Python-only. `Cerebro` class as central orchestrator. Strategy inherits from `bt.Strategy` with `__init__()` for indicator setup and `next()` for bar-by-bar logic. Lines-based data model where every indicator/data feed is a "line" of values accessed by index `[0]` (current), `[-1]` (previous). `Broker` simulates exchange. Modular via analyzers, observers, writers, sizers. |
| **Order Execution** | Order types: Market, Limit, Stop, StopLimit, Close, StopTrail, StopTrailLimit. **Next-bar execution**: orders submitted on bar N execute at bar N+1's open. `BackBroker` manages order matching with configurable `cheat_on_open` (fill at current bar's open) and `cheat_on_close` (fill at close). Bracket orders (`buy_bracket`/`sell_bracket`) create entry + SL + TP as OCO group. Order validity: GTC, GTD, DAY. Partial fills not supported by default. |
| **SL/TP Management** | Bracket orders: `buy_bracket(price, stopprice, limitprice)` creates 3 linked orders (entry + stop loss + take profit). When entry fills, SL and TP become active. When one hits, other is cancelled (OCO). Manual SL/TP via separate order submission. Trailing stops via `StopTrail` order type with `trailamount` or `trailpercent`. No built-in breakeven-on-TP1 or TP2 lot-split. |
| **Slippage/Commission** | `set_slippage_perc(perc)` or `set_slippage_fixed(fixed)` on broker. Granular controls: `slip_open` (slip on open price), `slip_limit` (no slip on limit by default), `slip_match` (match to current bar H/L), `slip_out` (allow slip outside H/L). Capping fills at bar's H/L. Commission schemes: percentage, per-share, per-trade. Customizable via `CommInfoBase`. No volume-impact or volatility-based slippage. |
| **Bar vs Tick Simulation** | Primarily bar-based. Tick data supported via custom data feeds but not native. No synthetic tick generation from bars. OHLC processed as a single bar event per `next()` call. No intra-bar order matching (all orders fill at next bar). Multi-timeframe via data resampling/replaying. |
| **Position Management** | Single default position per data feed (can be configured for multiple). Position tracking with `self.position` object. Sizers (`bt.Sizer`) for position sizing (FixedSize, FixedReverser, PercentSizer, AllInSizer). No native netting vs hedging distinction. |
| **Robustness Testing** | `cerebro.optstrategy()` for parameter optimization with multiprocessing. No built-in walk-forward, Monte Carlo, or robustness scoring. External libraries (e.g., `backtrader_addons`) add some capability. Analyzer framework for custom metrics. |
| **Performance Metrics** | Via Analyzers: `SharpeRatio`, `DrawDown`, `TradeAnalyzer`, `SQN`, `Returns`, `TimeReturn`, `AnnualReturn`, `VWR` (Variability-Weighted Return). PyFolio integration for tearsheets. Extensible analyzer framework. ~15 built-in analyzers. |
| **Data Handling** | Pandas DataFrame, CSV, or custom data feeds. `GenericCSVData` for arbitrary CSV formats. Data resampling (`resampledata`) and replaying (`replaydata`) for multi-timeframe. No built-in Parquet or database support. Memory-resident data. Lines-based access model. |

**Key Strengths**: Simplicity and rapid prototyping, excellent documentation, mature community, bracket orders, multi-timeframe via replay/resample, extensible analyzer framework.

---

### 1.3 VectorBT

| Dimension | Details |
|-----------|---------|
| **Core Architecture** | **Vectorized** (not event-driven). NumPy/Numba-based array operations. Entire backtest expressed as array computations without per-bar loops. Broadcasting engine auto-aligns arrays of different shapes for massive parameter sweeps. `Portfolio` class as primary simulation interface. Column-major data layout. Designed for speed and parameter exploration, not execution realism. |
| **Order Execution** | Simplified: entries/exits as boolean signal arrays. `Portfolio.from_signals()`, `Portfolio.from_orders()`, `Portfolio.from_order_func()`. The `from_order_func()` callback allows per-bar logic (slower). Market orders only in signal mode. Limit/stop orders simulated via price crossing in array operations. No proper order lifecycle (pending → filled → cancelled). Fill at next bar's open or same bar's close depending on config. |
| **SL/TP Management** | Array-based SL/TP via `sl_stop` and `tp_stop` parameters. Percentage or absolute price. Trailing stops via `trailing_sl` parameter. No bracket orders, no OCO. SL/TP applied as post-hoc price checks on OHLC arrays. Cannot model intra-bar SL/TP priority. |
| **Slippage/Commission** | Fixed slippage (absolute or percentage) applied uniformly to all fills. Commission: fixed, percentage, or per-share. No volume-impact modeling. No volatility-based slippage. Simple and consistent but unrealistic for large orders or illiquid markets. Applied as array-wide adjustment. |
| **Bar vs Tick Simulation** | Bar-only for vectorized mode. Operates on OHLCV arrays. No tick simulation. `from_order_func()` iterates bar-by-bar (loses vectorization speed advantage). No synthetic tick generation. Ultra-fast for bar-level testing (~100-1000x faster than event-driven engines for parameter sweeps). |
| **Position Management** | Long/short/both directions. Position sizing: fixed, percentage, target value. `size_type` parameter controls interpretation. Auto-sizing to fit. No multi-position per instrument (single position track). Accumulation and reduction supported. No margin/leverage modeling beyond simple multiplier. |
| **Robustness Testing** | **Excellent for parameter sweeps** due to broadcasting - test thousands of parameter combinations in one pass. No built-in walk-forward or Monte Carlo (but trivial to implement with array slicing). Combinatorial parameter exploration is the primary use case. |
| **Performance Metrics** | Comprehensive: total return, Sharpe, Sortino, Calmar, Omega, max drawdown, win rate, profit factor, expectancy, etc. via `Portfolio.stats()`. Plotting via Plotly. Accessible as properties (e.g., `pf.sharpe_ratio()`). Comparison across parameter combinations natively. 50+ metrics. |
| **Data Handling** | Pandas DataFrame as primary input. Multi-column support for multi-symbol via column hierarchy. Automatic broadcasting for parameter grids. Memory-resident. No built-in data sourcing (bring your own data). Efficient memory usage via NumPy views. |

**Key Strengths**: Unmatched speed for parameter optimization and exploration, elegant broadcasting for combinatorial testing, rich built-in metrics, excellent visualization via Plotly.

---

### 1.4 Zipline (Quantopian)

| Dimension | Details |
|-----------|---------|
| **Core Architecture** | Event-driven, Python. `initialize(context)` + `handle_data(context, data)` pattern. `TradingAlgorithm` as core engine. Pipeline API for cross-sectional factor computation. Clock-driven simulation with daily/minute resolutions. Bundle system for data management. Originally built for US equities (Quantopian). Calendar-aware (exchange trading calendars). |
| **Order Execution** | `order()`, `order_target()`, `order_target_percent()`, `order_value()`, `order_percent()`. Market orders only in basic API. Limit and stop orders via `style` parameter (`LimitOrder`, `StopOrder`, `StopLimitOrder`). Orders fill at **next bar** (no look-ahead). Fills are volume-aware: orders exceeding volume share limits get partially filled and carry over. Cancel-and-replace supported. |
| **SL/TP Management** | No native SL/TP or bracket orders. Must be implemented manually in `handle_data()` by tracking entry prices and submitting orders when conditions met. No trailing stops. No OCO. Users build their own SL/TP logic. |
| **Slippage/Commission** | **Pluggable models**: `FixedSlippage(spread)`, `VolumeShareSlippage(volume_limit, price_impact)` (default: fills up to 2.5% of bar volume with square-root impact), `FixedBasisPointsSlippage`. Commission: `PerShare(cost, min_trade_cost)`, `PerTrade(cost)`, `PerDollar(cost)`. Volume-aware fills are a distinguishing feature. Custom models via subclassing. |
| **Bar vs Tick Simulation** | Bar-based (daily or minute). No tick data support. Pipeline API processes entire cross-sections per bar (factor model style). No intra-bar simulation. No synthetic tick generation. Time resolution limited to minute bars minimum. |
| **Position Management** | `context.portfolio.positions` dictionary. Position tracking per asset. Long/short. Portfolio-level: `context.portfolio.portfolio_value`, `positions_value`, `cash`. `order_target_percent()` for portfolio rebalancing. Designed for portfolio strategies (cross-section of equities), not single-instrument trading. |
| **Robustness Testing** | No built-in walk-forward, Monte Carlo, or robustness scoring. Meant for research iteration on Quantopian platform (historically). `run_algorithm()` returns a DataFrame of daily performance for external analysis. Parameter optimization via external loops. |
| **Performance Metrics** | Via `pyfolio` integration: Sharpe, Sortino, max drawdown, alpha, beta, rolling metrics, tear sheets. Daily returns, benchmark comparison, factor exposure. Per-bar metrics in returned DataFrame: `portfolio_value`, `positions`, `orders`, `transactions`, `returns`, `benchmark_return`. |
| **Data Handling** | Bundle system: `zipline ingest -b <bundle>`. Pre-defined bundles (Quandl, CSV). OHLCV + adjustments (splits, dividends for equities). Calendar-aligned data. Pipeline API for cross-sectional computations (factors, filters, classifiers). Data accessed via `data.current()`, `data.history()`. Limited to equities/futures without customization. |

**Key Strengths**: Volume-aware fill modeling, Pipeline API for cross-sectional factor research, calendar-aware execution, portfolio-level order management (order_target_percent), pyfolio integration.

---

### 1.5 QuantConnect LEAN

| Dimension | Details |
|-----------|---------|
| **Core Architecture** | Event-driven, C# core with Python bindings. **Algorithm Framework**: 5 modular components (Universe Selection → Alpha → Portfolio Construction → Execution → Risk Management), each replaceable. `QCAlgorithm` base class. Supports both classic (`OnData`) and framework approach. Cloud and local execution. Open-source engine + commercial cloud platform. |
| **Order Execution** | Full order types: Market, Limit, StopMarket, StopLimit, MarketOnOpen, MarketOnClose, TrailingStop, LimitIfTouched, ComboMarket, ComboLimit, OptionExercise. **Pluggable models**: `ImmediateFillModel` (fills at quote), `EquityFillModel` (stale-price checks, fill at official price), `FutureFillModel`, `ForexFillModel`, `CryptoFillModel` - each asset class has specialized fill logic. Next-bar execution for market orders. Partial fills via configurable fill quantity. |
| **SL/TP Management** | No native bracket/OCO orders in the engine. Implemented via Alpha model generating Insight objects with `Insight.Price(symbol, timedelta, direction)` that have magnitude and confidence. Risk Management model enforces max drawdown or trailing stops. Manual SL/TP via `StopMarketOrder` + `LimitOrder` with custom tracking in `OnOrderEvent()`. Community examples for bracket patterns. |
| **Slippage/Commission** | **Pluggable slippage models**: `ConstantSlippageModel`, `VolumeShareSlippageModel` (uses % of volume with price impact), `MarketImpactSlippageModel`, custom via `ISlippageModel`. **Fee models** per asset class: `ConstantFeeModel`, `InteractiveBrokersFeeModel`, `BinanceFeeModel`, `GDAXFeeModel`, `AlphaStreamsFeeModel`, etc. Margin models per security type. Buying power model (leverage). Configurable per security. |
| **Bar vs Tick Simulation** | Supports **Tick**, **Second**, **Minute**, **Hour**, **Daily** resolutions. Tick data is first-class. Multi-resolution subscriptions per algorithm. `Consolidator` framework for building custom bar types (Renko, Volume, Range). Universe selection can process hundreds of symbols. No synthetic tick generation from bars needed (real tick data available in cloud). |
| **Position Management** | `Portfolio` object with per-security holdings. `Securities` dictionary with margin requirements, leverage, buying power. Long/short, multi-asset. **9 asset classes**: Equities, Options, Futures, Forex, Crypto, CFDs, Index Options, Future Options, Crypto Futures. Portfolio construction models: `EqualWeightingPortfolioConstructionModel`, `MeanVarianceOptimizationPortfolioConstructionModel`, `BlackLittermanOptimizationPortfolioConstructionModel`, `InsightWeightingPortfolioConstructionModel`. |
| **Robustness Testing** | **Optimization** via LEAN CLI (`lean optimize`) with parameter grids. No built-in walk-forward or Monte Carlo. LEAN cloud provides some analytics. Backtesting at scale via parameter sweeps. Framework approach enables swapping Alpha models for A/B comparison. `RollingWindowAlphaModel` for adaptive strategies. |
| **Performance Metrics** | Extensive: total return, CAGR, Sharpe, Sortino, Treynor, information ratio, max drawdown, beta, alpha, tracking error, win rate, loss rate, compounding annual return, drawdown, total orders, average win/loss, profit-loss ratio, Kelly criterion, etc. Benchmark comparison. Rolling statistics. Delivered in structured `BacktestResult` JSON. |
| **Data Handling** | Cloud data library: 40+ exchanges, tick to daily resolution, equities/options/futures/forex/crypto. 9 asset classes. Local data via Lean Data Format (LDF) - hierarchical folder structure. `AddEquity()/AddForex()/AddCrypto()` with resolution parameter. Universe Selection for dynamic instrument subscription. Data normalization (splits, dividends). Alternative data (fundamentals, SEC filings, sentiment). |

**Key Strengths**: Multi-asset (9 classes), Algorithm Framework modularity, largest data library (40+ exchanges), asset-class-specific fill models, production-scale (375K+ live algorithms, $45B/month traded), universe selection, portfolio construction models (Mean-Variance, Black-Litterman).

---

## 2. TradeForge Architecture Audit

### 2.1 Engine Files

#### V1 Engine (`backend/app/services/backtest/engine.py` — 691 lines, DEPRECATED Phase 1C)
- **Pattern**: Bar-by-bar loop, no event system
- **Data model**: `Bar` dataclass (time, O, H, L, C, V), `Trade` dataclass (entry/exit/SL/TP/pnl), `BacktestResult` (20+ stats)
- **Indicator computation**: `_compute_indicators()` with 15+ indicator types via manual numpy
- **Entry/exit logic**: `_check_entries()` → `_eval_condition()` / `_eval_rules()` → `_open_trade()`
- **SL/TP calculation**: `_calc_sl_tp()` supports fixed_pips, atr_multiple, adr_pct, percent, rr_ratio
- **Advanced features**: TP2 with lot-split, trailing stops, breakeven_on_tp1, filters (time, day, ADX, volatility)
- **Weaknesses**: Fills at bar close for entries, SL/TP checked against H/L without intra-bar priority, simplistic Sharpe formula, no partial fills, no commission modeling in trade execution, no proper order types
- **Status**: Still imported for `Bar` dataclass and referenced by walk-forward/optimizer scripts

#### V2 Engine (`backend/app/services/backtest/v2/` — ~15 modules)

**Runner** (`runner.py` — 1036 lines):
- `RunConfig`: initial_cash, commission per-lot + pct, spread, slippage_pct, per-symbol point_values/margin_rates, `SlippageMode` enum (NONE/FIXED/REALISTIC), tick_mode, fill_model, tearsheet config, sizing config, `use_fast_core` flag, bars_per_day
- `Runner` class: orchestrates EventQueue, OrderBook, Portfolio, PositionBook, RiskManager, PositionSizer, StrategyContext, TickEngine
- **Event dispatch**: BAR → TICK → FILL → ORDER → CANCEL → TIMER via heap-based priority queue
- **Bar processing loop**: (1) process pending orders via tick engine, (2) `strategy.on_bar()`, (3) process strategy orders, (4) process cancels, (5) snapshot equity, (6) check drawdown halt
- **SL/TP pessimistic reordering**: when both SL and TP trigger on same bar, SL is processed first (pessimistic)
- **Pre-computed**: system ATR(14) and rolling average volume per symbol
- **Fast-core path**: delegates to Rust `FastRunner` or Python `fallback.FastRunner`

**Order Model** (`order.py` — 534 lines):
- `OrderSide`: BUY/SELL
- `OrderType`: MARKET, LIMIT, STOP, STOP_LIMIT
- `TimeInForce`: GTC, GTD, IOC, FOK, DAY
- `OrderStatus`: PENDING → SUBMITTED → PARTIALLY_FILLED / FILLED / CANCELLED / REJECTED / EXPIRED
- `LinkedOrderType`: NONE, OCO, OTO, BRACKET
- Full `Fill` dataclass with slippage and commission tracking
- `OrderBook` manages pending orders

**Events System** (`events.py` — 182 lines):
- `EventType` IntEnum with priority: FILL(0) > CANCEL(1) > ORDER(2) > SIGNAL(3) > TICK(4) > BAR(5) > TIMER(6)
- `Event` base with nanosecond timestamps
- Specialized: BarEvent, TickEvent, SignalEvent, OrderEvent, FillEvent, CancelEvent
- All use `__slots__` for memory efficiency

**Position/PositionBook** (`position.py` — 419 lines):
- `PositionSide`: FLAT/LONG/SHORT
- `ClosedTrade`: enriched (entry/exit time, side, quantity, entry/exit price, PnL, commission, MAE/MFE, duration, linked_order_ids)
- `Position`: multi-fill tracking, partial close, position flip, weighted average entry, realized/unrealized PnL with point_value

**Portfolio** (`portfolio.py` — 325 lines):
- `MarginModel`: CFD/Forex with per-symbol margin_rates
- `EquitySnapshot`: cash + unrealized + margin
- Cash/margin/equity separation, multi-symbol, equity curve tracking
- `apply_fill()` with PnL and commission accounting

**Tick Engine** (`tick_engine.py` — 478 lines):
- `TickMode`: OHLC_FIVE, BROWNIAN, REAL_TICK
- OHLC_FIVE: generates 5 synthetic ticks (O, H, L, C, mid) with Open first, then pessimistic H/L ordering
- BROWNIAN: random walk between OHLC prices via Brownian bridge
- Walks ticks checking pending orders, applies fill model, detects gaps
- Fill rules: MARKET → first tick + fill model, LIMIT BUY → tick ≤ limit, STOP BUY → tick ≥ stop, gap → fill at open

**Fill Model** (`fill_model.py` — 330 lines):
- `FillModel` ABC with `adjust_fill_price()` method
- `SpreadModel`: half-spread with maker rebate
- `FixedSlippage`: constant points
- `VolatilitySlippage`: ATR-scaled with min_pct/max_pct bounds
- `VolumeImpact`: linear impact proportional to order_size/avg_volume
- `CompositeFillModel`: pipeline of models applied sequentially
- Factory: `make_default_fill_model()`, `make_realistic_fill_model()`

**Strategy Base** (`strategy_base.py` — 457 lines):
- `StrategyContext`: dependency injection (data_handler, portfolio, position_sizer)
- Data access: `get_value()`, `get_bar()`, `get_htf_value()`/`get_htf_bar()` (Phase 1E multi-TF)
- Order helpers: `buy_market()`, `sell_market()`, `buy_bracket()`, `sell_bracket()`, `close_position()`
- Position info: `get_position()`, `get_equity()`, `get_cash()`, `compute_position_size()`

**Data Handler** (`data_handler.py` — 1062 lines):
- `BarData`: OHLCV + indicators, `SymbolData`: array storage with indicator pre-computation
- Multi-timeframe via resampling (Phase 1E)
- Warm-up enforcement, bar synchronization across symbols
- 15+ indicator types computed

**Risk Manager** (`risk_manager.py` — 244 lines):
- `RiskConfig`: max_positions, max_positions_per_symbol, max_order_size, min_order_size, max_drawdown_pct, max_exposure_pct, min_cash_reserve, allow_pyramiding, exclusive_orders
- 7 validation checks: halted, order_size, max_positions, pyramiding, margin, max_drawdown, max_exposure

**Position Sizer** (`position_sizer.py` — 384 lines):
- `SizingMethod`: FIXED_LOT, PERCENT_RISK, FIXED_FRACTIONAL, KELLY
- Dynamic Kelly: rolling trade stats with ewma
- Max/min lots, lot_step rounding

**Strategies** (`strategies.py` — 388 lines):
- `MSSStrategy` (Market Structure Shift): pivot detection, ADR10-based SL/TP
- `GoldBTStrategy`: similar pattern
- Both are V2-native (inherit StrategyBase)

### 2.2 API Route (`backend/app/api/backtest.py` — 829 lines)

- `POST /api/backtest/run`: main endpoint
- CSV loading with multi-format support (6+ date formats, ; and , delimiters)
- Phase 1E data validation (bar count, date range, OHLC sanity)
- Routes to V2 unified `Runner` via `v2_adapter.py` based on `strategy_type`
- Walk-forward endpoint: `POST /api/backtest/walk-forward`
- Error handling with HTTP status codes and structured error responses
- CORS-enabled, authentication-gated

### 2.3 Data Model (`backend/app/models/backtest.py`)

- SQLAlchemy model: `Backtest` table
- Fields: id, strategy_id, creator_id, symbol, timeframe, date_from, date_to, initial_balance, status, results (JSON), created_at
- Results stored as monolithic JSON blob (entire RunResult serialized)
- No separate tables for trades, equity curves, or metrics

### 2.4 Frontend Page (`frontend/src/app/backtest/page.tsx` — 1233 lines)

- Next.js React page with:
  - `StatCard` component for summary metrics display
  - `EquityCurve` custom canvas component with theme-aware rendering
  - `BacktestTradeChart` for trade visualization
  - `StrategySettingsModal` for configuration
  - `ResizablePanel` layout (likely sidebar + main area)
  - ChatHelpers integration (LLM-assisted strategy building)
- Single monolithic page component (~1233 lines)

### 2.5 Strategy Execution

**V2 Adapter** (`v2_adapter.py` — 913 lines):
- `BuilderStrategy(StrategyBase)`: bridges V1 rule-based strategies to V2 engine
- Replicates V1 condition evaluation via `condition_engine.py`
- Builds bracket orders with SL/TP from strategy config
- Handles: TP2/lot-split, trailing stops, exit rules, filters
- Converts `BacktestRequest` → `RunConfig` → `RunResult` → API response

**Condition Engine** (`condition_engine.py` — 487 lines):
- Unified condition evaluation (Phase 3A)
- Nested IF/THEN/ELSE condition groups
- Operators: >, <, >=, <=, ==, !=, crosses_above, crosses_below
- `normalise_rules()` for legacy compatibility
- `evaluate_condition_tree()`, `evaluate_direction()`, `passes_filters()`

**Rust Core** (`v2/core/src/lib.rs`):
- PyO3 module `tradeforge_core` exposing: FastEventQueue, FastPortfolio, FastRunner, BacktestResult
- Indicator functions: sma_array, ema_array, atr_array
- Data types: Bar, RustFill, RustOrder, RustClosedTrade, EngineConfig, SymbolConfig

**Python Fallback** (`v2/core/fallback.py` — 1112 lines):
- Mirrors Rust counterparts 1:1
- IntEnum types, dataclasses, FastPortfolio, FastRunner
- Estimated ~50-100x slower than Rust path

### 2.6 Analytics Pipeline

| Module | Lines | Purpose |
|--------|-------|---------|
| `metrics.py` | 730 | 30+ metrics: CAGR, annualized return/vol, Sharpe, Sortino, Calmar, Omega, Gain-to-Pain, Ulcer Index, VaR, CVaR, Kelly, exposure, max_drawdown, avg_drawdown, streaks, win rate |
| `monte_carlo.py` | 200 | Trade resampling & block bootstrap (n=1000, bust/goal probability, terminal equity stats, max_dd stats, equity fan percentile bands) |
| `benchmark.py` | 241 | Buy-and-hold comparison, OLS alpha/beta, information ratio, correlation |
| `rolling.py` | 333 | Rolling Sharpe, Sortino, volatility, beta, drawdown, win rate (vectorized via stride tricks) |
| `tearsheet.py` | 239 | Assembles all analytics: metrics + Monte Carlo + benchmark + rolling |
| `robustness.py` | 550 | Composite robustness score (0-100): Window Profitability (30%), Sharpe Consistency (25%), CAGR Stability (20%), Drawdown Resilience (15%), Trade Count Stability (10%). Overfit probability estimate. |
| `walk_forward.py` | 334 | Walk-forward validation: anchored/rolling modes, per-fold train/test, combined OOS equity curve, consistency_score |

---

## 3. Side-by-Side Comparison Matrix

### 3.1 Core Architecture

| Feature | NautilusTrader | Backtrader | VectorBT | Zipline | LEAN | TradeForge V2 |
|---------|---------------|------------|----------|---------|------|---------------|
| Pattern | Event-driven | Event-driven | Vectorized | Event-driven | Event-driven | Event-driven |
| Language | Rust + Python | Python | Python + Numba | Python | C# + Python | Python + Rust |
| Event Queue | MessageBus (pub/sub) | Cerebro loop | N/A (array ops) | Clock-driven | Event-driven handlers | Heap-priority EventQueue |
| Backtest-Live Parity | ✅ Same code | ❌ Separate | ❌ Backtest only | ❌ Separate | ✅ Same code | ❌ Separate |
| Multi-Symbol | ✅ Native | ✅ Multi-data | ✅ Broadcasting | ✅ Pipeline API | ✅ Universe Selection | ✅ Multi-symbol |
| Multi-Strategy | ✅ Multiple | ✅ Multiple | ❌ Single | ❌ Single | ✅ Algorithm Framework | ❌ Single |

### 3.2 Order Execution

| Feature | NautilusTrader | Backtrader | VectorBT | Zipline | LEAN | TradeForge V2 |
|---------|---------------|------------|----------|---------|------|---------------|
| Market | ✅ | ✅ | ✅ Signals | ✅ | ✅ | ✅ |
| Limit | ✅ | ✅ | ⚠️ Array-based | ✅ | ✅ | ✅ |
| Stop | ✅ | ✅ | ⚠️ Array-based | ✅ | ✅ | ✅ |
| Stop-Limit | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| Trailing Stop | ✅ | ✅ | ⚠️ Basic | ❌ | ✅ | ⚠️ Via adapter |
| Market-If-Touched | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Bracket Orders | ✅ | ✅ | ❌ | ❌ | ❌ Native | ✅ |
| OCO | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| OTO | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Partial Fills | ✅ L2/L3 | ❌ | ❌ | ✅ Volume-based | ✅ | ⚠️ Model exists, unused |
| Next-Bar Execution | ✅ Configurable | ✅ Default | ✅ | ✅ | ✅ | ❌ Same-bar via tick |
| Latency Simulation | ✅ LatencyModel | ❌ | ❌ | ❌ | ❌ | ❌ |

### 3.3 SL/TP Management

| Feature | NautilusTrader | Backtrader | VectorBT | Zipline | LEAN | TradeForge V2 |
|---------|---------------|------------|----------|---------|------|---------------|
| SL/TP Methods | fixed, adaptive H/L | fixed price | % or absolute | Manual only | Manual StopMarket/Limit | fixed_pips, ATR, ADR%, percent, RR |
| Bracket SL/TP | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Intra-bar Priority | ✅ Adaptive (~85%) | ❌ | ❌ | ❌ | ✅ OHLC sequence | ✅ Pessimistic SL-first |
| Trailing Stop | ✅ Activation price | ✅ Trail amount/% | ⚠️ Basic | ❌ | ✅ | ✅ Via adapter |
| Breakeven on TP1 | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| TP2 Lot Split | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Gap Handling | ✅ Fill at open | ❌ Fills at H/L | ❌ | ❌ | ✅ | ✅ Fill at open |

### 3.4 Slippage & Commission

| Feature | NautilusTrader | Backtrader | VectorBT | Zipline | LEAN | TradeForge V2 |
|---------|---------------|------------|----------|---------|------|---------------|
| Slippage Models | 12+ pluggable | Fixed/% + controls | Fixed/% | Volume-share + fixed | Volume-share + constant | Spread + Fixed + ATR + Volume |
| Volume Impact | ✅ Via FillModel | ❌ | ❌ | ✅ Default model | ✅ VolumeShare | ✅ VolumeImpact model |
| Volatility-Based | ⚠️ Custom model | ❌ | ❌ | ❌ | ❌ | ✅ VolatilitySlippage |
| Composite Pipeline | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ CompositeFillModel |
| Commission Types | Maker/taker + custom | %, per-share, per-trade | Fixed/% | Per-share, per-trade, per-$ | Per-broker models (IB, Binance) | Per-lot + percentage |
| Spread Modeling | ✅ Via book | ✅ Basic | ❌ | ❌ | ✅ | ✅ SpreadModel |
| Queue Position | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Liquidity Consumption | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |

### 3.5 Bar vs Tick Simulation

| Feature | NautilusTrader | Backtrader | VectorBT | Zipline | LEAN | TradeForge V2 |
|---------|---------------|------------|----------|---------|------|---------------|
| Tick Data | ✅ Native | ⚠️ Custom feed | ❌ | ❌ | ✅ Native | ⚠️ REAL_TICK mode |
| Order Book Depth | ✅ L1/L2/L3 | ❌ | ❌ | ❌ | ❌ | ❌ |
| Synthetic Ticks | ✅ O→H→L→C (adaptive) | ❌ | ❌ | ❌ | ✅ OHLC sequence | ✅ OHLC_FIVE + Brownian |
| Intra-bar Matching | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Bar Timestamp | ✅ Strict close-time | Bar-close | N/A | Bar-close | ✅ Configurable | Bar-close |

### 3.6 Position Management

| Feature | NautilusTrader | Backtrader | VectorBT | Zipline | LEAN | TradeForge V2 |
|---------|---------------|------------|----------|---------|------|---------------|
| Netting/Hedging | Both | Netting only | Netting | Netting | Both | Netting (implicit) |
| Multi-Position | ✅ | Limited | ❌ | Via assets | ✅ | ⚠️ Via allow_pyramiding |
| Position Sizing | Strategy-defined | Sizer classes | Built-in | order_target_percent | Portfolio construction | 4 methods (fixed/risk/%/Kelly) |
| Margin Model | Standard + Leveraged + Custom | Basic | ❌ | ❌ | Per-security type | CFD/Forex margin rates |
| Account Types | Cash/Margin/Betting | Single | Single | Cash | Cash/Margin | Margin (CFD-style) |
| Asset Classes | Multi (configurable) | Any | Any | Equities/Futures | 9 native classes | Forex/CFD (configured) |

### 3.7 Robustness Testing

| Feature | NautilusTrader | Backtrader | VectorBT | Zipline | LEAN | TradeForge V2 |
|---------|---------------|------------|----------|---------|------|---------------|
| Walk-Forward | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ Anchored + Rolling |
| Monte Carlo | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ Trade + Block bootstrap |
| Robustness Score | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ Composite 0-100 |
| Overfit Detection | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ IS vs OOS gap |
| Parameter Optimization | Via external | optstrategy (MP) | ✅ Broadcasting | Via external | lean optimize | ❌ Not integrated |

### 3.8 Performance Metrics

| Feature | NautilusTrader | Backtrader | VectorBT | Zipline | LEAN | TradeForge V2 |
|---------|---------------|------------|----------|---------|------|---------------|
| Metric Count | ~20 | ~15 | ~50 | ~20 (via pyfolio) | ~30 | ~30+ |
| Risk-Adjusted | Sharpe, Sortino | Sharpe, SQN | Sharpe, Sortino, Calmar, Omega | Sharpe, Sortino, alpha, beta | Sharpe, Sortino, Treynor, info ratio | Sharpe, Sortino, Calmar, Omega, Ulcer, Gain-to-Pain |
| VaR/CVaR | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ |
| Rolling Stats | ❌ Built-in | ❌ | ✅ | ✅ | ✅ | ✅ |
| Benchmark | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ Alpha/beta/info ratio |
| Tearsheet | ✅ | Via pyfolio | ✅ Plotly | ✅ pyfolio | ✅ | ✅ Custom |
| Equity Fan | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ Monte Carlo percentiles |

### 3.9 Data Handling

| Feature | NautilusTrader | Backtrader | VectorBT | Zipline | LEAN | TradeForge V2 |
|---------|---------------|------------|----------|---------|------|---------------|
| Primary Format | Parquet | CSV/Pandas | Pandas | Bundles (HDF5) | LDF (proprietary) | CSV (uploaded) |
| Streaming/Large Data | ✅ Generator API | ❌ Memory-only | ❌ Memory-only | ❌ Memory-only | ✅ Lazy loading | ❌ Memory-only |
| Multi-Timeframe | ✅ Via subscription | ✅ Resample/Replay | ✅ Broadcasting | ❌ | ✅ Consolidator | ✅ Resampling (Phase 1E) |
| Indicator Computation | 100+ (ta-lib style) | 100+ built-in | 100+ (via pandas-ta) | Pipeline factors | 200+ | 15+ custom |
| Data Validation | ✅ Strict precision | ❌ | ❌ | ❌ | ✅ | ✅ Phase 1E (OHLC sanity) |
| Universe Selection | Via adapters | ❌ | ❌ | Pipeline API | ✅ Native | ❌ |

---

## 4. Weakness Analysis

### 4.1 Critical Weaknesses

#### W1: No Order Book Simulation
**Impact: HIGH** — TradeForge has no concept of order book depth (L1/L2/L3). NautilusTrader maintains an internal order book even for bar data. TradeForge's TickEngine generates synthetic price paths but doesn't maintain a book with bids, asks, and depth levels.
- **Result**: Cannot simulate partial fills due to insufficient liquidity, market impact for large orders, or queue position for limit orders
- **Gap vs**: NautilusTrader (L1/L2/L3 book), LEAN (per-asset-class fill models)

#### W2: No Backtest-Live Parity
**Impact: HIGH** — The V2 engine is backtest-only. There is no shared execution path between backtesting and live trading (via MT5 bridge). Strategy logic, order handling, and position management are separate codebases.
- **Result**: Strategies that backtest profitably may behave differently in live trading
- **Gap vs**: NautilusTrader (same code backtest/live), LEAN (same Algorithm class)

#### W3: No Real Tick Data Support in Practice
**Impact: MEDIUM-HIGH** — Although `TickMode.REAL_TICK` exists in the enum, the data pipeline loads CSV bars. There is no infrastructure for ingesting, storing, or replaying actual tick data (quote ticks, trade ticks).
- **Result**: All execution simulation depends on synthetic tick approximation from OHLC bars
- **Gap vs**: NautilusTrader (native tick/quote/trade data), LEAN (tick resolution from cloud)

#### W4: Single-Strategy Architecture
**Impact: MEDIUM** — The Runner executes one strategy per backtest run. No mechanism for running multiple strategies simultaneously with shared portfolio, cross-strategy risk management, or portfolio-level rebalancing.
- **Result**: Cannot model portfolio of strategies or strategy interaction effects
- **Gap vs**: NautilusTrader (multiple strategies), LEAN (Algorithm Framework with multiple Alpha models)

#### W5: No Universe Selection / Dynamic Instrument Subscription
**Impact: MEDIUM** — Instruments (symbols) are fixed at backtest start. No ability to dynamically add/remove instruments based on screening criteria during the backtest.
- **Result**: Cannot backtest rotation strategies, momentum screening, or any universe-dependent strategy
- **Gap vs**: LEAN (Universe Selection module), Zipline (Pipeline API)

### 4.2 Significant Weaknesses

#### W6: Pessimistic-Only SL/TP Ordering
**Impact: MEDIUM** — When both SL and TP trigger on the same bar, TradeForge always processes SL first (pessimistic). NautilusTrader's adaptive H/L ordering (~75-85% accuracy) is more realistic. The current approach systematically understates strategy performance when both levels are within the same bar.
- **Mitigation**: Brownian tick mode provides better resolution, but OHLC_FIVE mode is deterministically pessimistic

#### W7: No Latency / Network Simulation
**Impact: MEDIUM** — No modeling of order submission latency, fill confirmation delay, or network round-trip time. All orders are processed instantaneously within the event loop.
- **Gap vs**: NautilusTrader (LatencyModel with inflight queue)

#### W8: Partial Fill Support Incomplete
**Impact: MEDIUM** — Order model includes `PARTIALLY_FILLED` status, but the TickEngine and FillModel don't implement volume-aware partial fills. All fills are complete (full quantity).
- **Gap vs**: NautilusTrader (L2/L3 partial fills), Zipline (volume-share partial fills), LEAN (configurable fill quantity)

#### W9: Limited Indicator Library
**Impact: MEDIUM** — 15+ indicators computed manually via NumPy. Professional engines offer 100-200+ indicators. Users cannot easily add custom indicators without modifying `data_handler.py`.
- **Gap vs**: All engines (100+ indicators), especially Backtrader and LEAN

#### W10: No Parameter Optimization Framework
**Impact: MEDIUM** — Despite having walk-forward and robustness scoring, there is no mechanism for automated parameter grid search or optimization. Walk-forward runs a single parameter set; it doesn't search for optimal parameters per window.
- **Gap vs**: Backtrader (optstrategy with multiprocessing), VectorBT (broadcasting), LEAN (lean optimize)

### 4.3 Moderate Weaknesses

#### W11: Monolithic Data Storage
- Backtest results stored as single JSON blob in `results` column. No separate tables for trades, equity curves, metrics, or Monte Carlo results. Limits querying and cross-backtest analysis.

#### W12: No Asset-Class-Specific Fill Models
- Single fill model pipeline for all instruments. LEAN provides separate models for equities, forex, futures, crypto, each with asset-class-specific behavior (e.g., equity staleness checks, forex instant fill).

#### W13: No Portfolio Construction Models
- No built-in portfolio-level allocation (equal weight, mean-variance, Black-Litterman, risk parity). Only position-level sizing.
- **Gap vs**: LEAN (4 portfolio construction models)

#### W14: Frontend Page Monolith
- 1233-line single React component. Should be decomposed into smaller components (chart, settings, results table, equity curve, trade list, Monte Carlo visualization, etc.) for maintainability and testing.

#### W15: V1 Engine Legacy Debt
- Deprecated V1 engine still imported for `Bar` dataclass. `walk_forward.py` and optimizer scripts reference V1 types. Should be fully migrated or types extracted to shared module.

#### W16: Fallback Performance Gap
- When Rust core is unavailable, Python fallback is ~50-100x slower. No intermediate option (e.g., Cython compilation). Build system (`build_rust_core.py`) may fail silently, leaving users on slow path.

#### W17: Commission Model Simplicity
- Only per-lot fixed and percentage commission. No broker-specific models (Interactive Brokers tiered, Binance maker/taker, etc.), no minimum commission, no exchange fees.
- **Gap vs**: LEAN (per-broker fee models), Zipline (per-share with minimums)

#### W18: No Data Streaming for Large Datasets
- Entire dataset loaded into memory. No streaming/chunking for multi-year tick data or large multi-symbol universes.
- **Gap vs**: NautilusTrader (generator streaming), LEAN (lazy loading)

---

## 5. Recommendations

### 5.1 Priority 1 — Execution Realism (Addresses W1, W3, W6, W8)

1. **Implement Adaptive H/L Ordering**: Replace pessimistic-only SL/TP with NautilusTrader-style adaptive ordering (Open closer to High → O→H→L→C, else O→L→H→C). Research shows ~75-85% accuracy. Low implementation cost, high impact.

2. **Add Volume-Aware Partial Fills**: Extend `TickEngine` to track available volume per synthetic tick. When order size exceeds available volume, partially fill and carry remainder. Use bar volume / N_ticks as available per tick.

3. **Build L1 Order Book Simulation**: Maintain a simple top-of-book (best bid/ask) state within `TickEngine`. Apply spread model to create bid/ask from mid-price synthetic ticks. Fill buy orders against ask, sell against bid.

### 5.2 Priority 2 — Architecture (Addresses W2, W4, W5)

4. **Extract Strategy Protocol / Interface**: Create a shared `IStrategy` interface that both backtest and live trading (MT5 bridge) implement. This is the foundation for backtest-live parity.

5. **Multi-Strategy Runner**: Allow `Runner` to accept multiple strategy instances sharing a single `Portfolio`. Add cross-strategy risk checks.

6. **Parameter Optimization**: Add `OptimizerRunner` that accepts parameter grid + objective function, delegates to parallel `Runner` instances, returns results matrix. Leverage VectorBT's broadcasting concept for array-friendly strategies.

### 5.3 Priority 3 — Data & Infrastructure (Addresses W9, W11, W17, W18)

7. **Normalize Data Storage**: Create separate database tables for `BacktestTrade`, `EquityCurvePoint`, `BacktestMetric`. Enable cross-backtest queries and strategy comparison dashboards.

8. **Expand Indicator Library**: Integrate `pandas-ta` or `ta-lib` as indicator backend. Allow user-defined indicators via config.

9. **Broker-Specific Commission Models**: Add preset commission profiles (Interactive Brokers, Binance, etc.) with maker/taker distinction and minimum fees.

### 5.4 Priority 4 — Quality of Life (Addresses W14, W15, W16)

10. **Decompose Frontend**: Split `page.tsx` into: `BacktestConfigPanel`, `EquityCurveChart`, `TradeTable`, `MetricsGrid`, `MonteCarloViz`, `RobustnessPanel`.

11. **Extract Shared Types**: Move `Bar` dataclass and common types out of V1 engine into `backend/app/services/backtest/types.py`. Remove V1 imports from V2 code.

12. **Rust Build Resilience**: Add CI check for Rust compilation. Log clear warning when falling back to Python. Consider Cython as middle-ground performance option.

---

## Summary

**TradeForge's Standout Strengths** (features no competitor has):
- ✅ Built-in robustness scoring (composite 0-100 score with 5 weighted components)
- ✅ Monte Carlo simulation with block bootstrap and equity fan visualization
- ✅ Walk-forward validation integrated into the engine
- ✅ Overfit probability estimation (IS vs OOS performance gap)
- ✅ Breakeven-on-TP1 and TP2 lot-split (unique retail trader features)
- ✅ Composite fill model pipeline (spread + volatility + volume impact as sequential chain)
- ✅ Brownian bridge synthetic tick generation (more realistic than fixed OHLC sequence)
- ✅ 5 SL/TP methods (fixed_pips, ATR, ADR%, percent, RR ratio) — richer than any competitor

**TradeForge's Competitive Position**:
- **Analytics**: Near-parity with or exceeds all competitors (30+ metrics, Monte Carlo, walk-forward, robustness scoring, rolling stats, benchmark comparison)
- **Execution Realism**: Behind NautilusTrader (no order book, no queue position, no latency model) but ahead of Backtrader, VectorBT, and Zipline (synthetic tick simulation, composite fill model, gap detection)
- **Architecture**: Modern event-driven design competitive with all except NautilusTrader's parity model. Rust fast-path is forward-looking.
- **Biggest Gaps**: No backtest-live parity, no universe selection, no multi-strategy, no parameter optimization, limited asset class support
