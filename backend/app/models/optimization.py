from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Float
from sqlalchemy.orm import relationship

from app.core.database import Base


class Optimization(Base):
    __tablename__ = "optimizations"

    id = Column(Integer, primary_key=True, index=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False)
    param_space = Column(JSON, default=dict)       # Parameter ranges
    best_params = Column(JSON, default=dict)       # Best found parameters
    best_score = Column(Float, default=0.0)
    objective = Column(String(30), default="sharpe_ratio")
    n_trials = Column(Integer, default=100)
    status = Column(String(20), default="pending")
    history = Column(JSON, default=list)           # Trial history
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    strategy = relationship("Strategy", back_populates="optimizations")
