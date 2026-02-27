"""Pydantic schemas for the Algo Trading Agent API."""

from typing import Optional, Literal
from pydantic import BaseModel

AGENT_MODES = Literal["paper", "confirmation", "auto"]


class AgentCreate(BaseModel):
    name: str
    strategy_id: int
    symbol: str
    timeframe: str = "M10"
    broker_name: str = "mt5"
    mode: AGENT_MODES = "paper"  # paper | confirmation | auto
    risk_config: dict = {}
    ml_model_id: Optional[int] = None  # Optional ML model for signal filtering


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    mode: Optional[str] = None
    risk_config: Optional[dict] = None
    ml_model_id: Optional[int] = None


class AgentResponse(BaseModel):
    id: int
    name: str
    strategy_id: int
    broker_name: str
    symbol: str
    timeframe: str
    mode: str
    status: str
    risk_config: dict
    performance_stats: dict
    ml_model_id: Optional[int] = None
    created_by: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class AgentLogResponse(BaseModel):
    id: int
    agent_id: int
    level: str
    message: str
    data: dict
    created_at: str

    class Config:
        from_attributes = True


class AgentTradeResponse(BaseModel):
    id: int
    agent_id: int
    symbol: str
    direction: str
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    lot_size: float
    stop_loss: Optional[float] = None
    take_profit_1: Optional[float] = None
    take_profit_2: Optional[float] = None
    pnl: float
    pnl_pct: float
    status: str
    signal_type: Optional[str] = None
    signal_reason: Optional[str] = None
    signal_confidence: float
    broker_ticket: Optional[str] = None
    opened_at: str
    closed_at: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True
