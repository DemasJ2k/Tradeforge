from typing import Optional
from pydantic import BaseModel


class BacktestRequest(BaseModel):
    strategy_id: int
    datasource_id: int
    initial_balance: float = 10000.0
    spread_points: float = 0.0
    commission_per_lot: float = 0.0
    point_value: float = 1.0


class TradeResult(BaseModel):
    entry_bar: int
    entry_time: float
    entry_price: float
    direction: str
    size: float
    stop_loss: float
    take_profit: float
    exit_bar: Optional[int]
    exit_time: Optional[float]
    exit_price: Optional[float]
    exit_reason: str
    pnl: float
    pnl_pct: float


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
