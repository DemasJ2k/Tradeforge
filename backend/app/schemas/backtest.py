from typing import Any, Optional
from pydantic import BaseModel


class BacktestRequest(BaseModel):
    strategy_id: int
    datasource_id: int
    initial_balance: float = 10000.0
    spread_points: float = 0.0
    commission_per_lot: float = 0.0
    point_value: float = 1.0
    # V2 engine selection
    engine_version: str = "v1"            # "v1" or "v2"
    # V2-specific options (ignored when engine_version="v1")
    slippage_pct: float = 0.0             # Random slippage as fraction of price
    commission_pct: float = 0.0           # Percentage commission (e.g. 0.001 = 0.1%)
    margin_rate: float = 0.01             # Margin rate for position sizing
    use_fast_core: bool = False           # Use Rust/fallback fast runner
    bars_per_day: float = 1.0             # For annualisation (e.g. 144 for M10)
    tick_mode: str = "ohlc_five"          # Tick synthesis mode
    # Phase 4 — Multi-symbol portfolio mode
    datasource_ids: Optional[list[int]] = None  # Multiple datasources (overrides datasource_id)


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


# ── Walk-Forward Validation ──

class WalkForwardRequest(BaseModel):
    strategy_id: int
    datasource_id: int
    n_folds: int = 5
    train_pct: float = 70.0
    mode: str = "anchored"  # "anchored" or "rolling"
    initial_balance: float = 10000.0
    spread_points: float = 0.0
    commission_per_lot: float = 0.0
    point_value: float = 1.0


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
