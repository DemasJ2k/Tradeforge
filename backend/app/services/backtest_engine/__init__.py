"""
Backtesting Engine V3 — Hybrid Architecture

Vectorized signal generation + Event-driven execution.
Supports all asset classes, bracket orders (OCO SL/TP),
intra-bar tick simulation, multi-timeframe, trailing stops,
and Python/JSON file strategies.
"""

from .bar import Bar
from .instrument import Instrument, AssetClass, get_instrument
from .order import Order, BracketOrder, OrderBook, OrderSide, OrderType, OrderRole
from .fill_engine import FillEngine, FillResult, TickMode
from .position import Position, Portfolio
from .position_sizer import SizingMethod, compute_size
from .indicator_engine import compute_indicators
from .data_feed import DataFeed, SymbolData
from .strategy import StrategyBase, StrategyContext, TradeRecord
from .engine import Engine, EngineConfig, BacktestResult, run_backtest
from .analytics import compute_analytics
from .builder_strategy import BuilderStrategy
from .python_strategy import PythonStrategy
from .json_strategy import JsonStrategy
from .walk_forward import walk_forward_backtest, WFResult, WFWindow
from .monte_carlo import (
    monte_carlo_trade_resample,
    monte_carlo_data_perturbation,
    MCResult,
)

__all__ = [
    "Bar",
    "Instrument", "AssetClass", "get_instrument",
    "Order", "BracketOrder", "OrderBook", "OrderSide", "OrderType", "OrderRole",
    "FillEngine", "FillResult", "TickMode",
    "Position", "Portfolio",
    "SizingMethod", "compute_size",
    "compute_indicators",
    "DataFeed", "SymbolData",
    "StrategyBase", "StrategyContext", "TradeRecord",
    "Engine", "EngineConfig", "BacktestResult", "run_backtest",
    "compute_analytics",
    "BuilderStrategy",
    "PythonStrategy",
    "JsonStrategy",
    "walk_forward_backtest", "WFResult", "WFWindow",
    "monte_carlo_trade_resample", "monte_carlo_data_perturbation", "MCResult",
]
