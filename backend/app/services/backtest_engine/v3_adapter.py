"""
V3 API Adapter — Bridge between V3 engine and API layer.

Handles:
  - Converting V1/V2 Bar format → V3 Bar
  - Creating BuilderStrategy from strategy config
  - Running V3 Engine and packaging results for the API response
  - Walk-forward and Monte Carlo via V3
"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.backtest_engine.bar import Bar as V3Bar
from app.services.backtest_engine.engine import (
    Engine, EngineConfig, BacktestResult as V3Result,
)
from app.services.backtest_engine.data_feed import DataFeed
from app.services.backtest_engine.instrument import get_instrument
from app.services.backtest_engine.fill_engine import TickMode
from app.services.backtest_engine.position_sizer import SizingMethod
from app.services.backtest_engine.builder_strategy import BuilderStrategy
from app.services.backtest_engine.python_strategy import LegacyPythonStrategy
from app.services.backtest_engine.walk_forward import (
    walk_forward_backtest as v3_walk_forward,
    WFResult,
)
from app.services.backtest_engine.monte_carlo import (
    monte_carlo_trade_resample,
    MCResult,
)

logger = logging.getLogger(__name__)


def _normalize_indicator_configs(raw_configs: list[dict]) -> list[dict]:
    """Translate frontend indicator configs into compute_indicators format.

    Frontend format:
        {"id": "sma_1", "type": "SMA", "params": {"period": 5, "source": "close"}}
    Engine format (flat):
        {"type": "sma", "name": "sma_1", "period": 5, "source": "close"}
    """
    # Parameter name aliases: frontend name → engine name
    _PARAM_ALIASES = {
        "fast": "fast_period",
        "slow": "slow_period",
        "signal": "signal_period",
    }

    out: list[dict] = []
    for cfg in raw_configs:
        flat: dict = {}
        # "type" field exists in both formats — lowercase it
        ind_type = (cfg.get("type") or cfg.get("name") or "").lower()
        flat["type"] = ind_type

        # Use "id" as the storage key ("name" in engine terms)
        flat["name"] = cfg.get("id") or cfg.get("name", f"{ind_type}")

        # Flatten "params" sub-dict if present
        params = cfg.get("params", {})
        for k, v in params.items():
            # Map frontend param names to engine param names
            engine_key = _PARAM_ALIASES.get(k, k)
            flat[engine_key] = v
            # Also keep the original key for backward compat
            if engine_key != k:
                flat[k] = v

        # Also copy top-level keys that engine may use (period, source, etc.)
        for k in ("period", "source", "fast_period", "slow_period",
                   "signal_period", "std_dev", "k_period", "d_period",
                   "multiplier", "adr_period"):
            if k in cfg and k not in flat:
                flat[k] = cfg[k]

        out.append(flat)
    return out


def _parse_timestamp(raw) -> float:
    """Convert a raw timestamp value to Unix epoch float.

    Handles: float/int already, ISO datetime strings, MT5 dot-datetime
    strings (e.g. '2025.01.08 01:00:00'), and other common formats.
    Returns 0.0 if parsing fails.
    """
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str) or not raw.strip():
        return 0.0
    s = raw.strip()
    # MT5 dot-datetime: "2025.01.08 01:00:00"
    s = s.replace(".", "-", 2)  # only first two dots (date part)
    # Common datetime formats
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    # Last resort: try float parse (e.g. "1704672000.0")
    try:
        return float(raw)
    except (ValueError, TypeError):
        return 0.0


def convert_bars_to_v3(bars: list) -> list[V3Bar]:
    """Convert V1/V2 Bar objects (with .time) to V3 Bar objects (with .timestamp)."""
    v3_bars: list[V3Bar] = []
    for b in bars:
        # Support both dict and object formats
        if isinstance(b, dict):
            raw_ts = b.get("time", b.get("timestamp", 0))
            v3_bars.append(V3Bar(
                timestamp=_parse_timestamp(raw_ts),
                open=b.get("open", 0),
                high=b.get("high", 0),
                low=b.get("low", 0),
                close=b.get("close", 0),
                volume=b.get("volume", 0),
            ))
        else:
            raw_ts = getattr(b, "time", getattr(b, "timestamp", 0))
            v3_bars.append(V3Bar(
                timestamp=_parse_timestamp(raw_ts),
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=getattr(b, "volume", 0),
            ))
    return v3_bars


def _resolve_tick_mode(mode_str: str) -> TickMode:
    """Convert string tick mode to V3 enum."""
    mapping = {
        "ohlc_four": TickMode.OHLC_4,
        "ohlc_five": TickMode.OHLC_PESSIMISTIC,
        "ohlc_pessimistic": TickMode.OHLC_PESSIMISTIC,
        "brownian": TickMode.BROWNIAN,
        "close_only": TickMode.CLOSE_ONLY,
        "synthetic": TickMode.SYNTHETIC,
    }
    return mapping.get(mode_str.lower(), TickMode.OHLC_PESSIMISTIC)


def run_v3_backtest(
    bars: list,
    strategy_config: dict,
    symbol: str = "ASSET",
    initial_balance: float = 10_000.0,
    spread_points: float = 0.0,
    commission_per_lot: float = 7.0,
    point_value: float = 1.0,
    slippage_pct: float = 0.0,
    margin_rate: float = 0.01,
    tick_mode: str = "ohlc_pessimistic",
    **kwargs,
) -> V3Result:
    """Run a backtest using the V3 engine.

    Args:
        bars:              List of bar objects (V1/V2 format or dicts)
        strategy_config:   Strategy config dict with indicators, rules, risk_params
        symbol:            Trading symbol
        initial_balance:   Starting balance
        spread_points:     Spread in points
        commission_per_lot: Commission per lot round-trip
        point_value:       Value per point movement per 1 lot
        slippage_pct:      Slippage as fraction of price
        margin_rate:       Margin requirement as fraction
        tick_mode:         Tick synthesis mode string

    Returns:
        V3 BacktestResult with full analytics
    """
    # Convert bars
    v3_bars = convert_bars_to_v3(bars)

    # Build engine config
    risk_params = strategy_config.get("risk_params", {})
    sizing_method = SizingMethod.RISK_PERCENT
    sizing_params = {"risk_pct": 1.0, "fixed_lot": 0.01}

    sm = risk_params.get("sizing_method", "risk_percent")
    if sm == "fixed_lot":
        sizing_method = SizingMethod.FIXED_LOT
        sizing_params["fixed_lot"] = risk_params.get("lot_size", 0.01)
    elif sm == "risk_percent":
        sizing_method = SizingMethod.RISK_PERCENT
        sizing_params["risk_pct"] = risk_params.get("risk_percent", 1.0)
    elif sm == "risk_amount":
        sizing_method = SizingMethod.RISK_AMOUNT
        sizing_params["risk_amount"] = risk_params.get("risk_amount", 100)
    elif sm == "kelly":
        sizing_method = SizingMethod.KELLY
    elif sm == "atr_based":
        sizing_method = SizingMethod.ATR_BASED
        sizing_params["atr_multiplier"] = risk_params.get("atr_multiplier", 1.5)

    config = EngineConfig(
        initial_balance=initial_balance,
        spread_points=spread_points,
        commission=commission_per_lot,
        point_value=point_value,
        slippage_pct=slippage_pct,
        latency_ms=kwargs.get("latency_ms", 0.0),
        margin_rate=margin_rate,
        tick_mode=_resolve_tick_mode(tick_mode),
        max_positions=risk_params.get("max_positions", 1),
        allow_pyramiding=risk_params.get("allow_pyramiding", False),
        close_on_opposite=risk_params.get("close_on_opposite", True),
        close_at_end=True,
        sizing_method=sizing_method,
        sizing_params=sizing_params,
    )

    # Build instrument
    instrument = get_instrument(
        symbol,
        point_value=point_value,
        commission=commission_per_lot,
        margin_rate=margin_rate,
    )

    # Build data feed with indicators
    feed = DataFeed()
    indicator_configs = _normalize_indicator_configs(
        strategy_config.get("indicators", [])
    )
    feed.add_symbol(symbol, v3_bars, indicator_configs=indicator_configs)

    # Diagnostic: log indicator keys so we can verify lookups
    sd = feed.get_symbol_data(symbol)
    if sd:
        logger.info(
            "V3 feed for %s: %d bars, indicator keys=%s",
            symbol, sd.count, sorted(sd.indicators.keys()),
        )
    else:
        logger.warning("V3 feed: no SymbolData for %s", symbol)

    # Diagnostic: log entry rule structure
    entry_rules = strategy_config.get("entry_rules", [])
    logger.info(
        "V3 strategy config: %d indicators, entry_rules type=%s, "
        "entry_rules=%s, exit_rules=%d, risk_params keys=%s",
        len(indicator_configs),
        type(entry_rules).__name__,
        str(entry_rules)[:500],
        len(strategy_config.get("exit_rules", [])),
        list(strategy_config.get("risk_params", {}).keys()),
    )

    # Build strategy — detect Python vs Builder type
    strategy_type = strategy_config.get("strategy_type", "builder")
    file_path = strategy_config.get("file_path", "")

    if strategy_type == "python" and file_path:
        import os
        if not os.path.isfile(file_path):
            logger.warning("Python strategy file not found: %s", file_path)
            # Fall back to builder strategy
            strategy = BuilderStrategy(strategy_config=strategy_config, symbol=symbol)
        else:
            # Convert bars to dicts for legacy strategy compatibility
            bar_dicts = [b.to_dict() for b in v3_bars]
            settings = strategy_config.get("settings_values", {})
            # Safety: ensure settings is a dict (SQLite JSON columns may return strings)
            if isinstance(settings, str):
                import json as _json
                try:
                    settings = _json.loads(settings)
                except Exception:
                    settings = {}
            if not isinstance(settings, dict):
                settings = {}
            strategy = LegacyPythonStrategy(
                file_path=file_path,
                settings=settings,
                all_bars=bar_dicts,
            )
            logger.info(
                "Using LegacyPythonStrategy for %s (%s), %d settings keys",
                symbol, os.path.basename(file_path), len(settings),
            )
    else:
        strategy = BuilderStrategy(strategy_config=strategy_config, symbol=symbol)

    # Run engine
    engine = Engine(
        strategy=strategy,
        data_feed=feed,
        instrument=instrument,
        config=config,
    )
    return engine.run(symbol)


def v3_result_to_api_response(
    result: V3Result,
    initial_balance: float,
    total_bars: int,
) -> dict:
    """Convert V3 BacktestResult to API response dict.

    Returns dict matching the BacktestResponse schema structure.
    """
    # Build stats dict
    stats = {
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "losing_trades": result.losing_trades,
        "win_rate": round(result.win_rate, 2),
        "gross_profit": round(result.gross_profit, 2),
        "gross_loss": round(result.gross_loss, 2),
        "net_profit": round(result.net_profit, 2),
        "profit_factor": round(result.profit_factor, 4),
        "max_drawdown": round(result.max_drawdown, 2),
        "max_drawdown_pct": round(result.max_drawdown_pct, 2),
        "avg_win": round(result.avg_win, 2),
        "avg_loss": round(result.avg_loss, 2),
        "largest_win": round(result.largest_win, 2),
        "largest_loss": round(result.largest_loss, 2),
        "avg_trade": round(result.avg_trade, 2),
        "sharpe_ratio": round(result.sharpe_ratio, 4),
        "sqn": round(result.sqn, 4),
        "expectancy": round(result.expectancy, 2),
        "total_bars": total_bars,
        "yearly_pnl": result.yearly_pnl,
        "negative_years": sum(1 for v in result.yearly_pnl.values() if v < 0),
    }

    # V3-extended stats
    v2_stats = {
        **stats,
        "sortino_ratio": round(result.sortino_ratio, 4),
        "calmar_ratio": round(result.calmar_ratio, 4),
        "recovery_factor": round(result.recovery_factor, 4),
        "payoff_ratio": round(result.payoff_ratio, 4),
        "max_consecutive_wins": result.max_consecutive_wins,
        "max_consecutive_losses": result.max_consecutive_losses,
        "avg_bars_held": round(result.avg_bars_held, 1),
        "initial_balance": result.initial_balance,
        "final_balance": round(result.final_balance, 2),
        "monthly_returns": result.monthly_returns,
    }

    # Downsample equity curve for API
    eq = result.equity_curve
    if len(eq) > 2000:
        step = len(eq) // 2000
        eq = eq[::step] + [eq[-1]]
    eq = [round(v, 2) for v in eq]

    # Trades
    trades = result.trades  # Already dicts from TradeRecord.to_dict()

    return {
        "stats": stats,
        "v2_stats": v2_stats,
        "trades": trades,
        "equity_curve": eq,
        "tearsheet": {
            "monthly_returns": result.monthly_returns,
            "yearly_pnl": result.yearly_pnl,
        },
        "elapsed_seconds": round(result.execution_time_ms / 1000, 3),
    }


def run_v3_walk_forward(
    bars: list,
    strategy_config: dict,
    symbol: str = "ASSET",
    n_folds: int = 5,
    train_pct: float = 70.0,
    mode: str = "anchored",
    initial_balance: float = 10_000.0,
    spread_points: float = 0.0,
    commission_per_lot: float = 7.0,
    point_value: float = 1.0,
    margin_rate: float = 0.01,
    tick_mode: str = "ohlc_pessimistic",
) -> WFResult:
    """Run walk-forward validation with V3 engine.

    Mirrors run_v3_backtest config: sizing, Python strategy support, etc.
    """
    v3_bars = convert_bars_to_v3(bars)
    indicator_configs = _normalize_indicator_configs(
        strategy_config.get("indicators", [])
    )

    # Build sizing config from risk_params (matches run_v3_backtest)
    risk_params = strategy_config.get("risk_params", {})
    sizing_method = SizingMethod.RISK_PERCENT
    sizing_params = {"risk_pct": 1.0, "fixed_lot": 0.01}

    sm = risk_params.get("sizing_method", "risk_percent")
    if sm == "fixed_lot":
        sizing_method = SizingMethod.FIXED_LOT
        sizing_params["fixed_lot"] = risk_params.get("lot_size", 0.01)
    elif sm == "risk_percent":
        sizing_method = SizingMethod.RISK_PERCENT
        sizing_params["risk_pct"] = risk_params.get("risk_percent", 1.0)
    elif sm == "risk_amount":
        sizing_method = SizingMethod.RISK_AMOUNT
        sizing_params["risk_amount"] = risk_params.get("risk_amount", 100)
    elif sm == "kelly":
        sizing_method = SizingMethod.KELLY
    elif sm == "atr_based":
        sizing_method = SizingMethod.ATR_BASED
        sizing_params["atr_multiplier"] = risk_params.get("atr_multiplier", 1.5)

    config = EngineConfig(
        initial_balance=initial_balance,
        spread_points=spread_points,
        commission=commission_per_lot,
        point_value=point_value,
        margin_rate=margin_rate,
        tick_mode=_resolve_tick_mode(tick_mode),
        max_positions=risk_params.get("max_positions", 1),
        allow_pyramiding=risk_params.get("allow_pyramiding", False),
        close_on_opposite=risk_params.get("close_on_opposite", True),
        close_at_end=True,
        sizing_method=sizing_method,
        sizing_params=sizing_params,
    )

    # Detect strategy type — Python vs Builder (matches run_v3_backtest)
    strategy_type = strategy_config.get("strategy_type", "builder")
    file_path = strategy_config.get("file_path", "")

    if strategy_type == "python" and file_path:
        import os
        if os.path.isfile(file_path):
            bar_dicts = [b.to_dict() for b in v3_bars]
            settings = strategy_config.get("settings_values", {})
            if isinstance(settings, str):
                import json as _json
                try:
                    settings = _json.loads(settings)
                except Exception:
                    settings = {}
            if not isinstance(settings, dict):
                settings = {}

            def strategy_factory(segment_bars=None):
                # Walk-forward passes segment_bars (the fold's subset).
                # Convert Bar objects to dicts so the strategy sees only
                # the fold's data, fixing the bar-index mismatch bug.
                if segment_bars is not None:
                    seg_dicts = [b.to_dict() for b in segment_bars]
                else:
                    seg_dicts = bar_dicts  # full dataset for normal backtest
                return LegacyPythonStrategy(
                    file_path=file_path,
                    settings=settings,
                    all_bars=seg_dicts,
                )
        else:
            logger.warning("Python strategy file not found for WF: %s — falling back to builder", file_path)
            def strategy_factory(segment_bars=None):
                return BuilderStrategy(strategy_config=strategy_config, symbol=symbol)
    else:
        def strategy_factory(segment_bars=None):
            return BuilderStrategy(strategy_config=strategy_config, symbol=symbol)

    return v3_walk_forward(
        bars=v3_bars,
        strategy_factory=strategy_factory,
        symbol=symbol,
        indicator_configs=indicator_configs,
        engine_config=config,
        n_folds=n_folds,
        train_pct=train_pct,
        mode=mode,
    )


def run_v3_monte_carlo(
    trades: list[dict],
    initial_balance: float = 10_000.0,
    n_simulations: int = 1000,
) -> MCResult:
    """Run Monte Carlo trade resampling on backtest trades."""
    return monte_carlo_trade_resample(
        trades=trades,
        initial_balance=initial_balance,
        n_simulations=n_simulations,
    )
