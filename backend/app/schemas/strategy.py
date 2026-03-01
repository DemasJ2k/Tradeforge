from typing import Optional
from pydantic import BaseModel


# --- Indicator config ---
class IndicatorConfig(BaseModel):
    id: str                    # unique id for referencing in rules
    type: str                  # SMA, EMA, RSI, MACD, Bollinger, ATR, VWAP, Pivot, Stochastic, ADX, ADR, PivotHigh, PivotLow
    params: dict = {}          # e.g. {"period": 20, "source": "close"}
    overlay: bool = True       # display on price chart vs separate panel


# --- Condition row ---
class ConditionRow(BaseModel):
    left: str                  # indicator id or "price.close", "price.open", etc.
    operator: str              # crosses_above, crosses_below, >, <, ==, etc.
    right: str                 # indicator id, or a literal number string
    logic: str = "AND"         # AND / OR (how to chain with next condition)
    direction: str = "both"    # long | short | both — which direction this rule applies to


# --- Risk params ---
class RiskParams(BaseModel):
    position_size_type: str = "fixed_lot"   # fixed_lot | percent_risk | percent_equity
    position_size_value: float = 0.01
    stop_loss_type: str = "fixed_pips"      # fixed_pips | atr_multiple | adr_pct | percent | swing
    stop_loss_value: float = 50.0
    take_profit_type: str = "fixed_pips"    # fixed_pips | atr_multiple | adr_pct | percent | rr_ratio | pivot_level
    take_profit_value: float = 100.0
    take_profit_2_type: str = ""            # same options as TP — empty = disabled
    take_profit_2_value: float = 0.0
    lot_split: list[float] = []             # e.g. [0.6, 0.4] — TP1/TP2 lot split; empty = no split
    breakeven_on_tp1: bool = False          # move SL to breakeven when TP1 is hit
    trailing_stop: bool = False
    trailing_stop_type: str = "fixed_pips"  # fixed_pips | atr_multiple
    trailing_stop_value: float = 0.0
    max_positions: int = 1
    max_drawdown_pct: float = 0.0           # 0 = disabled


# --- Filters ---
class FilterConfig(BaseModel):
    time_start: str = ""       # e.g. "08:00"
    time_end: str = ""         # e.g. "16:00"
    days_of_week: list[int] = []  # 0=Mon..6=Sun, empty=all
    min_volatility: float = 0.0
    max_volatility: float = 0.0
    min_adx: float = 0.0      # e.g. 20 — only trade when ADX > this
    max_adx: float = 0.0      # e.g. 25 — only trade when ADX < this (ranging)


# --- Strategy CRUD ---
class StrategyCreate(BaseModel):
    name: str
    description: str = ""
    indicators: list[dict] = []
    entry_rules: list[dict] = []
    exit_rules: list[dict] = []
    risk_params: dict = {}
    filters: dict = {}
    strategy_type: str = "builder"
    settings_schema: list[dict] = []
    settings_values: dict = {}


class StrategyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    indicators: Optional[list[dict]] = None
    entry_rules: Optional[list[dict]] = None
    exit_rules: Optional[list[dict]] = None
    risk_params: Optional[dict] = None
    filters: Optional[dict] = None
    settings_schema: Optional[list[dict]] = None
    settings_values: Optional[dict] = None


class StrategySettingsUpdate(BaseModel):
    """Update only the settings_values for a file-based strategy."""
    settings_values: dict


class StrategyResponse(BaseModel):
    id: int
    name: str
    description: str
    indicators: list[dict]
    entry_rules: list[dict]
    exit_rules: list[dict]
    risk_params: dict
    filters: dict
    creator_id: int
    is_system: bool = False
    strategy_type: str = "builder"
    file_path: Optional[str] = None
    settings_schema: list[dict] = []
    settings_values: dict = {}
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class StrategyListResponse(BaseModel):
    items: list[StrategyResponse]
    total: int
