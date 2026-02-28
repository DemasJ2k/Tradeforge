from typing import Optional
from pydantic import BaseModel


class ParamRange(BaseModel):
    """Defines a single parameter to optimize."""
    param_path: str          # e.g. "indicators.0.params.period" or "risk_params.stop_loss_value"
    param_type: str          # "int", "float", "categorical"
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    step: Optional[float] = None
    choices: Optional[list] = None  # For categorical
    label: str = ""          # Human-readable label


class OptimizationRequest(BaseModel):
    strategy_id: int
    datasource_id: int
    param_space: list[ParamRange]
    objective: str = "sharpe_ratio"  # sharpe_ratio, net_profit, profit_factor, win_rate
    n_trials: int = 100
    method: str = "bayesian"  # bayesian, genetic, hybrid
    initial_balance: float = 10000.0
    spread_points: float = 0.0
    commission_per_lot: float = 0.0
    point_value: float = 1.0
    walk_forward: bool = False
    wf_in_sample_pct: float = 70.0  # % of data for in-sample
    # Secondary objective filter (optional)
    secondary_objective: Optional[str] = None   # sharpe_ratio, net_profit, profit_factor, win_rate
    secondary_threshold: Optional[float] = None  # threshold value the secondary metric must meet
    secondary_operator: Optional[str] = None     # ">=" or "<="


class TrialResult(BaseModel):
    trial_number: int
    params: dict
    score: float
    stats: dict  # net_profit, sharpe, etc.


class OptimizationResponse(BaseModel):
    id: int
    strategy_id: int
    status: str
    objective: str
    n_trials: int
    best_params: dict
    best_score: float
    history: list[TrialResult]
    param_importance: dict  # param_name -> importance_score


class OptimizationStatus(BaseModel):
    id: int
    status: str  # pending, running, completed, failed
    progress: float  # 0-100
    current_trial: int
    total_trials: int
    best_score: float
    best_params: dict
    elapsed_seconds: float


class OptimizationListItem(BaseModel):
    id: int
    strategy_id: int
    strategy_name: str
    objective: str
    n_trials: int
    status: str
    best_score: float
    created_at: str
