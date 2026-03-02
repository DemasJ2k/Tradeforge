"""
OptimizationPhase model — represents a single stage in a multi-phase
(chain) optimization workflow.

Phase chains allow users to:
1. Optimize entry params in Phase 1
2. Freeze those results, then optimize exit/risk params in Phase 2
3. Continue adding phases as needed
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, JSON
from app.core.database import Base


class OptimizationPhase(Base):
    __tablename__ = "optimization_phases"

    id = Column(Integer, primary_key=True, index=True)

    # Chain grouping — all phases sharing the same chain_id form one chain
    chain_id = Column(String(36), nullable=False, index=True)
    phase_number = Column(Integer, nullable=False, default=1)

    # Reference to original optimization run (strategy + datasource source)
    strategy_id = Column(Integer, nullable=True)
    datasource_id = Column(Integer, nullable=True)

    # Phase-specific optimization config
    objective = Column(String(64), nullable=False, default="sharpe_ratio")
    n_trials = Column(Integer, nullable=False, default=50)
    method = Column(String(20), nullable=False, default="bayesian")
    min_trades = Column(Integer, nullable=False, default=30)

    # Param specs for this phase (JSON list of ParamRange dicts)
    param_space = Column(JSON, nullable=True)

    # Params frozen from previous phases
    frozen_params = Column(JSON, nullable=True)

    # Backtest simulation settings
    initial_balance = Column(Float, nullable=False, default=10000.0)
    spread_points = Column(Float, nullable=False, default=0.0)
    commission_per_lot = Column(Float, nullable=False, default=0.0)
    point_value = Column(Float, nullable=False, default=1.0)

    # Results
    status = Column(String(20), nullable=False, default="pending")
    best_params = Column(JSON, nullable=True)
    best_score = Column(Float, nullable=True)
    param_importance = Column(JSON, nullable=True)
    history = Column(JSON, nullable=True)  # list of trial records

    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
