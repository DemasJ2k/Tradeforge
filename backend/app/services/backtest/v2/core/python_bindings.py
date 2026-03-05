"""
Python bindings / auto-select wrapper for the FlowrexAlgo core engine.

Tries to import the compiled Rust extension (tradeforge_core).
If that fails (not compiled, wrong platform, missing DLL), it falls
back to the pure-Python implementation in fallback.py.

Usage:
    from app.services.backtest.v2.core.python_bindings import (
        EngineConfig, SymbolConfig, Bar,
        FastRunner, FastPortfolio, BacktestResult,
        SMA, EMA, ATR, BollingerBands,
        sma_array, ema_array, atr_array,
        USING_RUST,
    )
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

USING_RUST = False

try:
    from tradeforge_core import (  # type: ignore[import-not-found]
        # Enums
        OrderSide,
        OrderType,
        OrderStatus,
        EventType,
        PositionSide,
        # Data types
        Bar,
        RustFill,
        RustOrder,
        RustClosedTrade,
        EngineConfig,
        SymbolConfig,
        # Event queue
        FastEventQueue,
        # Portfolio
        FastPortfolio,
        # Runner
        FastRunner,
        BacktestResult,
        # Indicators
        SMA,
        EMA,
        ATR,
        BollingerBands,
        IndicatorValues,
        # Vectorised
        sma_array,
        ema_array,
        atr_array,
    )
    USING_RUST = True
    logger.info("FlowrexAlgo Rust core loaded (tradeforge_core)")

except ImportError:
    from app.services.backtest.v2.core.fallback import (
        # Enums
        OrderSide,
        OrderType,
        OrderStatus,
        EventType,
        PositionSide,
        # Data types
        Bar,
        RustFill,
        RustOrder,
        RustClosedTrade,
        EngineConfig,
        SymbolConfig,
        # Event queue
        FastEventQueue,
        # Portfolio
        FastPortfolio,
        # Runner
        FastRunner,
        BacktestResult,
        # Indicators
        SMA,
        EMA,
        ATR,
        BollingerBands,
        IndicatorValues,
        # Vectorised
        sma_array,
        ema_array,
        atr_array,
    )
    USING_RUST = False
    logger.info("FlowrexAlgo Rust core not available — using Python fallback")


# ── Convenience: build bars from V2 DataHandler format ──────────

def bars_from_data_handler(data_handler, symbol_names: list[str] | None = None) -> list[Bar]:
    """Convert a V2 DataHandler's loaded data into a flat list of Bar objects
    suitable for FastRunner.

    Parameters
    ----------
    data_handler : DataHandler
        The V2 data handler with symbols loaded.
    symbol_names : list[str] or None
        If provided, maps symbol_idx → name. Otherwise uses dict keys.

    Returns
    -------
    list[Bar]
        Sorted by timestamp_ns then symbol_idx.
    """
    bars = []
    names = symbol_names or list(data_handler._symbols.keys())

    for sym_idx, sym_name in enumerate(names):
        sym_data = data_handler._symbols.get(sym_name)
        if sym_data is None:
            continue
        n_bars = len(sym_data.closes)
        for i in range(n_bars):
            bars.append(Bar(
                timestamp_ns=sym_data.timestamps[i] if hasattr(sym_data, 'timestamps') and i < len(sym_data.timestamps) else i * 1_000_000_000,
                symbol_idx=sym_idx,
                bar_index=i,
                open=sym_data.opens[i] if i < len(sym_data.opens) else 0.0,
                high=sym_data.highs[i] if i < len(sym_data.highs) else 0.0,
                low=sym_data.lows[i] if i < len(sym_data.lows) else 0.0,
                close=sym_data.closes[i],
                volume=sym_data.volumes[i] if i < len(sym_data.volumes) else 0.0,
            ))

    # Sort by timestamp, then symbol
    bars.sort(key=lambda b: (b.timestamp_ns, b.symbol_idx))
    return bars


def config_from_run_config(run_config, warm_up_bars: int = 0) -> EngineConfig:
    """Convert a V2 RunConfig to a Rust EngineConfig."""
    return EngineConfig(
        initial_cash=run_config.initial_cash,
        commission_per_lot=run_config.commission_per_lot,
        commission_pct=run_config.commission_pct,
        spread=run_config.spread,
        slippage_pct=run_config.slippage_pct,
        default_margin_rate=next(iter(run_config.margin_rates.values()), 0.01) if run_config.margin_rates else 0.01,
        max_drawdown_pct=run_config.risk.max_drawdown_pct if hasattr(run_config.risk, 'max_drawdown_pct') else 0.0,
        max_positions=run_config.risk.max_open_positions if hasattr(run_config.risk, 'max_open_positions') else 0,
        exclusive_orders=run_config.risk.exclusive_orders if hasattr(run_config.risk, 'exclusive_orders') else False,
        warm_up_bars=warm_up_bars,
        bars_per_day=run_config.bars_per_day,
    )


def symbols_from_run_config(run_config, symbol_names: list[str]) -> list[SymbolConfig]:
    """Build SymbolConfig list from RunConfig and symbol names."""
    return [
        SymbolConfig(
            symbol_idx=i,
            name=name,
            point_value=run_config.point_values.get(name, 1.0),
            margin_rate=run_config.margin_rates.get(name, 0.01),
            spread=run_config.spread,
        )
        for i, name in enumerate(symbol_names)
    ]


__all__ = [
    "USING_RUST",
    # Enums
    "OrderSide", "OrderType", "OrderStatus", "EventType", "PositionSide",
    # Data types
    "Bar", "RustFill", "RustOrder", "RustClosedTrade",
    "EngineConfig", "SymbolConfig",
    # Engine
    "FastEventQueue", "FastPortfolio", "FastRunner", "BacktestResult",
    # Indicators
    "SMA", "EMA", "ATR", "BollingerBands", "IndicatorValues",
    "sma_array", "ema_array", "atr_array",
    # Helpers
    "bars_from_data_handler", "config_from_run_config", "symbols_from_run_config",
]
