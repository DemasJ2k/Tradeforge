# Backtesting Engine V3 — Complete Rewrite Plan

## Architecture: Hybrid (Vectorized Signals + Event-Driven Execution)

### Why Hybrid?
- **Vectorized layer**: NumPy-based indicator computation and signal generation. Fast.
- **Event-driven layer**: Bar-by-bar execution with real order book, SL/TP as actual orders.
- Best of both: VectorBT speed for signals, NautilusTrader accuracy for fills.

---

## Phase 1: Engine Core (`backend/app/services/backtest_engine/`)

### 1.1 Data Layer
- `bar.py` — Bar dataclass (time, O, H, L, C, V) + multi-TF bar alignment
- `data_feed.py` — MultiTimeframeFeed: holds bars for multiple symbols × timeframes
- `indicator_engine.py` — Vectorized indicator computation (NumPy). Computes all indicators upfront.

### 1.2 Order & Fill System
- `order.py` — Order types: Market, Limit, Stop, StopLimit + BracketOrder (parent + SL + TP as OCO pair)
- `order_book.py` — Manages pending orders, OCO links, order lifecycle
- `fill_engine.py` — Intra-bar tick synthesis (OHLC→synthetic ticks), fill simulation with slippage
- `commission.py` — Commission models: per-lot, per-trade, percentage, spread-based

### 1.3 Position & Portfolio
- `position.py` — Single position tracker (entry, avg price, PnL, margin)
- `portfolio.py` — Multi-position portfolio: balance, equity, margin, drawdown tracking
- `position_sizer.py` — Sizing methods: fixed lot, risk-percent, Kelly, ATR-based

### 1.4 Execution Engine
- `engine.py` — Main backtest loop:
  1. Advance bar
  2. Check pending orders (SL/TP/limits) against intra-bar ticks
  3. Call strategy.on_bar()
  4. Process new orders from strategy
  5. Update portfolio equity
  6. Record state

### 1.5 Strategy Interface
- `strategy_base.py` — Abstract base: `on_init()`, `on_bar()`, `on_order_filled()`, `on_position_closed()`
- `strategy_context.py` — Context API for strategies: `buy()`, `sell()`, `close()`, `set_sl()`, `set_tp()`, `get_indicator()`, `get_bar()`, `get_position()`
- `builder_strategy.py` — Evaluates JSON rule-based strategies (current condition_engine)
- `python_strategy.py` — Loads and executes .py file strategies in sandboxed environment
- `json_strategy.py` — Loads and executes .json file strategies

---

## Phase 2: Instrument Models

### 2.1 Asset Configuration
- `instrument.py` — Per-asset config: tick_size, point_value, margin_rate, commission_type, trading_hours
- Built-in presets for: Forex pairs, Gold/Silver, US indices, Crypto, Stocks
- User can override via settings

### 2.2 Fill Models
- Forex: spread-based fill, pip-level slippage
- Commodities: point-based fill, volatility-adjusted slippage
- Indices: tick-based fill
- Crypto: percentage-based slippage, maker/taker fees
- Stocks: volume-weighted fill, regulatory constraints

---

## Phase 3: Intra-Bar Tick Simulation

### 3.1 Tick Synthesis Modes
- **OHLC-4**: O→H→L→C or O→L→H→C (pessimistic for direction)
- **OHLC-5**: O→H→L→C→C (with close confirmation)
- **Brownian**: Random walk between OHLC extremes
- **ATR-weighted**: Probability-weighted tick paths based on volatility

### 3.2 SL/TP Resolution
- Within each synthetic tick sequence, check stop/limit orders
- Pessimistic ordering: when both SL and TP could trigger in same bar, assume SL first
- Gap handling: if bar opens beyond SL/TP, fill at open (gap fill)

---

## Phase 4: Analytics Pipeline

### 4.1 Core Metrics
- Total trades, win rate, profit factor, expectancy
- Gross profit/loss, net profit, avg win/loss
- Sharpe ratio, Sortino, Calmar, SQN
- Max drawdown ($, %), avg drawdown, max consecutive losses
- Recovery factor, payoff ratio

### 4.2 Advanced Analytics
- Monthly returns matrix/heatmap
- Yearly P&L breakdown
- Trade duration statistics
- Drawdown analysis (top 5 drawdowns)
- Rolling Sharpe/win rate

### 4.3 Robustness Testing (from existing V2)
- Walk-forward analysis (in-sample/out-of-sample)
- Monte Carlo simulation (trade shuffling, equity paths)
- Overfit detection score

---

## Phase 5: API Layer (`backend/app/api/backtest.py`)

### 5.1 Endpoints
- `POST /api/backtest/run` — Run single backtest
- `POST /api/backtest/walk-forward` — Run walk-forward analysis
- `GET /api/backtest/history` — List saved backtest runs
- `GET /api/backtest/history/{id}` — Get full results for a run
- `DELETE /api/backtest/history/{id}` — Delete a run
- `POST /api/backtest/compare` — Compare multiple runs

### 5.2 Request Schema
```json
{
  "strategy_id": 1,
  "datasource_id": 2,
  "symbol": "XAUUSD",
  "timeframe": "M1",
  "initial_balance": 10000,
  "spread_points": 0.3,
  "commission": 7,
  "point_value": 1,
  "slippage_pct": 0,
  "margin_rate": 0.01,
  "tick_mode": "ohlc_pessimistic",
  "save_to_history": true
}
```

### 5.3 Response Schema
```json
{
  "id": "uuid",
  "status": "completed",
  "summary": {
    "total_trades": 143,
    "win_rate": 0.52,
    "net_profit": 3115,
    "profit_factor": 1.45,
    "max_drawdown_pct": 12.3,
    "sharpe_ratio": 1.8,
    ...
  },
  "equity_curve": [[timestamp, equity], ...],
  "trades": [...],
  "monthly_returns": {...},
  "tearsheet": {...}
}
```

---

## Phase 6: Frontend Page (`frontend/src/app/backtest/page.tsx`)

### 6.1 Layout: Config Dialog + Results Dashboard

**Config Dialog** (floating modal):
- Strategy picker (builder / python / json dropdown)
- Data source picker
- Balance, spread, commission, point value
- Advanced: slippage, margin rate, tick mode
- "Run Backtest" button → closes dialog, shows results

**Results Dashboard** (full-width):
- Top bar: strategy name, symbol, timeframe, run date, quick stats
- Tab navigation: Equity | Trade Log | Stats | Monthly Returns | Tearsheet | Trade Chart
- History sidebar (collapsible): list of past runs with quick compare

### 6.2 Components
- `BacktestConfigDialog.tsx` — Configuration modal
- `BacktestDashboard.tsx` — Main results container
- `EquityCurveChart.tsx` — Interactive equity + drawdown chart (lightweight-charts or recharts)
- `TradeLogTable.tsx` — Paginated, sortable, filterable trade table
- `StatsCards.tsx` — Performance metric cards grid
- `MonthlyHeatmap.tsx` — Monthly returns heatmap
- `TearsheetPanel.tsx` — Full quantstats-style metrics
- `TradeChartOverlay.tsx` — Candlestick chart with trade entry/exit markers
- `RunHistorySidebar.tsx` — History list with compare checkboxes
- `CompareOverlay.tsx` — Side-by-side or overlay comparison of runs

### 6.3 Run History Database
- Backend: `backtest_results` table (id, user_id, strategy_name, symbol, config_json, summary_json, trades_json, equity_json, created_at)
- Tag support for organizing runs
- Compare mode: select 2+ runs, overlay equity curves, side-by-side stats

---

## File Structure

```
backend/app/services/backtest_engine/
├── __init__.py
├── bar.py                  # Bar dataclass
├── data_feed.py            # Multi-TF data feed
├── indicator_engine.py     # Vectorized indicators (NumPy)
├── order.py                # Order types + BracketOrder
├── order_book.py           # Order management
├── fill_engine.py          # Tick synthesis + fill simulation
├── commission.py           # Commission models
├── position.py             # Position tracker
├── portfolio.py            # Portfolio/balance manager
├── position_sizer.py       # Position sizing methods
├── engine.py               # Main backtest loop
├── strategy_base.py        # Strategy abstract base
├── strategy_context.py     # Strategy API (buy/sell/indicators)
├── builder_strategy.py     # JSON rule-based strategy evaluator
├── python_strategy.py      # Python file strategy runner
├── json_strategy.py        # JSON file strategy runner
├── instrument.py           # Asset class configs
├── analytics.py            # Metrics computation
├── walk_forward.py         # Walk-forward analysis
├── monte_carlo.py          # Monte Carlo simulation
└── result.py               # Result dataclasses

frontend/src/app/backtest/
├── page.tsx                # Main page (thin orchestrator)
├── components/
│   ├── BacktestConfigDialog.tsx
│   ├── BacktestDashboard.tsx
│   ├── EquityCurveChart.tsx
│   ├── TradeLogTable.tsx
│   ├── StatsCards.tsx
│   ├── MonthlyHeatmap.tsx
│   ├── TearsheetPanel.tsx
│   ├── TradeChartOverlay.tsx
│   ├── RunHistorySidebar.tsx
│   └── CompareOverlay.tsx
```

---

## Implementation Order

1. **Engine core** — bar, order, fill_engine, position, portfolio, engine loop
2. **Order/fill system** — bracket orders, OCO, intra-bar tick synthesis, SL/TP
3. **Strategy runners** — builder, python file, json file
4. **Analytics** — metrics, monthly returns, tearsheet, walk-forward, monte carlo
5. **API layer** — endpoints, history DB, compare
6. **Frontend** — config dialog, dashboard, all 6 result views, history sidebar
7. **Integration testing** — end-to-end with Gold Breakout strategy
