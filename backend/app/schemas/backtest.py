from typing import Any, Optional
from pydantic import BaseModel, Field


class BacktestRequest(BaseModel):
    strategy_id: int = 0  # Optional for agent-based backtests (scalping_agent, expert_agent)
    datasource_id: int
    initial_balance: float = Field(10000.0, gt=0, le=100_000_000)
    spread_points: float = Field(0.3, ge=0, le=1000)
    commission_per_lot: float = Field(7.0, ge=0, le=10000)
    point_value: float = Field(1.0, gt=0)
    # V2 engine selection
    engine_version: str = "v1"            # "v1" or "v2"
    # V2-specific options (ignored when engine_version="v1")
    slippage_pct: float = Field(0.02, ge=0, le=1.0)
    commission_pct: float = Field(0.0, ge=0, le=1.0)
    margin_rate: float = Field(0.01, gt=0, le=1.0)
    use_fast_core: bool = False           # Use Rust/fallback fast runner
    bars_per_day: float = Field(1.0, gt=0)
    tick_mode: str = "ohlc_five"          # Tick synthesis mode
    latency_ms: float = Field(0.0, ge=0, le=10000)
    # Phase 4 — Multi-symbol portfolio mode
    datasource_ids: Optional[list[int]] = None  # Multiple datasources (overrides datasource_id)
    # Phase 5 — ML-enhanced backtesting
    ml_model_id: Optional[int] = None            # ML model to filter strategy signals
    regime_model_id: Optional[int] = None         # HMM regime model for regime-conditional testing
    rl_model_id: Optional[int] = None             # RL agent model (replaces strategy)
    strategy_type: str = "strategy"               # "strategy", "rl", "scalping_agent", "expert_agent"
    ml_threshold: float = Field(0.5, ge=0, le=1.0)


class TradeResult(BaseModel):
    entry_bar: int
    entry_time: float
    entry_price: float
    direction: str
    size: float
    stop_loss: float = 0.0
    take_profit: float = 0.0
    exit_bar: Optional[int] = None
    exit_time: Optional[float] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0
    # V2 extra fields
    commission: Optional[float] = None
    slippage: Optional[float] = None
    duration_bars: Optional[int] = None


class BacktestStats(BaseModel):
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_profit: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    avg_trade: float = 0.0
    sharpe_ratio: float = 0.0
    expectancy: float = 0.0
    total_bars: int = 0


class BacktestResponse(BaseModel):
    id: int
    strategy_id: int
    datasource_id: int
    status: str
    stats: BacktestStats
    trades: list[TradeResult]
    equity_curve: list[float]
    # V2 extended response (None when engine_version="v1")
    engine_version: str = "v1"
    v2_stats: Optional[dict[str, Any]] = None        # Full 55+ metrics dict
    tearsheet: Optional[dict[str, Any]] = None        # Tearsheet with MC, rolling, benchmark
    elapsed_seconds: Optional[float] = None
    # Phase 4 — Multi-symbol portfolio fields
    portfolio_analytics: Optional[dict[str, Any]] = None  # Per-symbol, correlation, diversification
    symbols: Optional[list[str]] = None                   # Symbols in portfolio mode
    # Phase 5 — ML-enhanced backtest results
    ml_filter_stats: Optional[dict[str, Any]] = None      # ML filter rate, regime breakdown
    rl_action_stats: Optional[dict[str, int]] = None      # RL action distribution
    agent_stats: Optional[dict[str, Any]] = None          # Agent backtest stats (scalping/expert)


# ── Walk-Forward Validation ──

class WalkForwardRequest(BaseModel):
    strategy_id: int
    datasource_id: int
    n_folds: int = Field(5, ge=2, le=50)
    train_pct: float = Field(70.0, gt=10, lt=100)
    mode: str = "anchored"  # "anchored" or "rolling"
    initial_balance: float = Field(10000.0, gt=0, le=100_000_000)
    spread_points: float = Field(0.3, ge=0, le=1000)
    commission_per_lot: float = Field(7.0, ge=0, le=10000)
    point_value: float = Field(1.0, gt=0)


class WFWindowStats(BaseModel):
    fold: int
    train_bars: int = 0
    test_bars: int = 0
    train_stats: dict = {}
    test_stats: dict = {}


class WalkForwardResponse(BaseModel):
    strategy_id: int
    datasource_id: int
    n_folds: int
    mode: str
    # Aggregated OOS performance
    oos_total_trades: int = 0
    oos_win_rate: float = 0.0
    oos_net_profit: float = 0.0
    oos_profit_factor: float = 0.0
    oos_max_drawdown: float = 0.0
    oos_max_drawdown_pct: float = 0.0
    oos_sharpe_ratio: float = 0.0
    oos_expectancy: float = 0.0
    oos_avg_win: float = 0.0
    oos_avg_loss: float = 0.0
    # Per-fold breakdown
    windows: list[WFWindowStats] = []
    # Consistency
    fold_win_rates: list[float] = []
    fold_profit_factors: list[float] = []
    fold_net_profits: list[float] = []
    consistency_score: float = 0.0
    # Charts
    oos_equity_curve: list[float] = []
    trades: list[TradeResult] = []
