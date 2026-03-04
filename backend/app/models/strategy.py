from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class Strategy(Base):
    __tablename__ = "strategies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(String(500), default="")
    indicators = Column(JSON, default=list)       # List of indicator configs
    entry_rules = Column(JSON, default=list)       # Entry condition rows
    exit_rules = Column(JSON, default=list)        # Exit condition rows
    risk_params = Column(JSON, default=dict)       # Position sizing, max DD, etc.
    filters = Column(JSON, default=dict)           # Time, volatility filters
    is_system = Column(Boolean, default=False, nullable=False)

    # File-based strategy fields
    strategy_type = Column(String(20), default="builder")  # builder | python | json | pinescript
    file_path = Column(String(500), nullable=True)          # path to uploaded strategy file
    settings_schema = Column(JSON, default=list)            # [{key, label, type, default, min, max, step, options}]
    settings_values = Column(JSON, default=dict)            # {key: current_value}
    folder = Column(String(100), nullable=True)                # user folder grouping (None = root)
    verified_performance = Column(JSON, nullable=True, default=None)  # {profit_factor, win_rate, max_dd_pct, sharpe, wf_score, trades, net_profit_pct, symbol, timeframe, robustness}

    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    deleted_at = Column(DateTime, nullable=True, default=None)

    creator = relationship("User", back_populates="strategies")
    backtests = relationship("Backtest", back_populates="strategy")
    optimizations = relationship("Optimization", back_populates="strategy")
