"""
Run file-based strategies (Python, JSON) for backtesting.

Python strategies are executed in a sandboxed subprocess.
JSON strategies define declarative rules interpreted by the engine.
"""

import json
import logging
import subprocess
import sys
import tempfile
import os
from pathlib import Path
from typing import Any

from app.services.backtest.engine import Bar, Trade, BacktestResult

logger = logging.getLogger(__name__)


def run_file_strategy(
    strategy_type: str,
    file_path: str,
    settings_values: dict[str, Any],
    bars_raw: list[dict],
    initial_balance: float = 10000.0,
    spread_points: float = 0.0,
    commission_per_lot: float = 0.0,
    point_value: float = 1.0,
) -> BacktestResult:
    """Route to the appropriate file-based strategy runner."""
    if strategy_type == "python":
        return run_python_strategy(
            file_path, settings_values, bars_raw,
            initial_balance, spread_points, commission_per_lot, point_value,
        )
    elif strategy_type == "json":
        return run_json_strategy(
            file_path, settings_values, bars_raw,
            initial_balance, spread_points, commission_per_lot, point_value,
        )
    else:
        raise ValueError(f"Unsupported strategy type for backtesting: {strategy_type}")


# ── Python Strategy Runner ─────────────────────────────────────────

# Template injected into subprocess to provide the backtest harness
PYTHON_HARNESS = '''
import json
import sys
import math

# Load data from stdin
input_data = json.loads(sys.stdin.read())
bars = input_data["bars"]
settings = input_data["settings"]
config = input_data["config"]

initial_balance = config["initial_balance"]
spread = config["spread_points"]
commission = config["commission_per_lot"]
point_value = config["point_value"]

# ── Simple bar-by-bar backtest engine ──
balance = initial_balance
open_trades = []
closed_trades = []
equity_curve = []

def open_trade(bar_idx, direction, entry_price, stop_loss=0, take_profit=0, size=0.01):
    trade = {
        "entry_bar": bar_idx,
        "entry_time": bars[bar_idx]["time"],
        "entry_price": entry_price + (spread * point_value if direction == "long" else -spread * point_value),
        "direction": direction,
        "size": size,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "exit_bar": None,
        "exit_time": None,
        "exit_price": None,
        "exit_reason": "",
        "pnl": 0.0,
    }
    open_trades.append(trade)
    return trade

def close_trade(trade, bar_idx, exit_price, reason="signal"):
    trade["exit_bar"] = bar_idx
    trade["exit_time"] = bars[bar_idx]["time"]
    trade["exit_price"] = exit_price
    trade["exit_reason"] = reason
    mult = 1 if trade["direction"] == "long" else -1
    raw_pnl = (exit_price - trade["entry_price"]) * mult * trade["size"] * point_value
    trade["pnl"] = raw_pnl - (commission * trade["size"])
    global balance
    balance += trade["pnl"]
    closed_trades.append(trade)
    if trade in open_trades:
        open_trades.remove(trade)

def check_sl_tp(bar_idx):
    """Check SL/TP for all open trades against current bar."""
    bar = bars[bar_idx]
    for trade in list(open_trades):
        if trade["direction"] == "long":
            if trade["stop_loss"] > 0 and bar["low"] <= trade["stop_loss"]:
                close_trade(trade, bar_idx, trade["stop_loss"], "stop_loss")
            elif trade["take_profit"] > 0 and bar["high"] >= trade["take_profit"]:
                close_trade(trade, bar_idx, trade["take_profit"], "take_profit")
        else:
            if trade["stop_loss"] > 0 and bar["high"] >= trade["stop_loss"]:
                close_trade(trade, bar_idx, trade["stop_loss"], "stop_loss")
            elif trade["take_profit"] > 0 and bar["low"] <= trade["take_profit"]:
                close_trade(trade, bar_idx, trade["take_profit"], "take_profit")

# Make bars accessible as list of dicts with o/h/l/c/v/time
# Execute the user strategy file
exec(open(sys.argv[1]).read())

# Strategy must define: on_bar(bar_idx, bar) or evaluate(bars, settings)
# Try class-based first, then function-based
strategy_instance = None
for name, obj in list(globals().items()):
    if isinstance(obj, type) and hasattr(obj, "on_bar"):
        strategy_instance = obj()
        if hasattr(strategy_instance, "init"):
            strategy_instance.init(bars, settings)
        break

if strategy_instance:
    for i in range(len(bars)):
        check_sl_tp(i)
        strategy_instance.on_bar(i, bars[i])
        unrealized = 0
        for t in open_trades:
            mult = 1 if t["direction"] == "long" else -1
            unrealized += (bars[i]["close"] - t["entry_price"]) * mult * t["size"] * point_value
        equity_curve.append(balance + unrealized)
elif "on_bar" in dir():
    for i in range(len(bars)):
        check_sl_tp(i)
        on_bar(i, bars[i])
        unrealized = 0
        for t in open_trades:
            mult = 1 if t["direction"] == "long" else -1
            unrealized += (bars[i]["close"] - t["entry_price"]) * mult * t["size"] * point_value
        equity_curve.append(balance + unrealized)
elif "evaluate" in dir():
    signals = evaluate(bars, settings)
    # signals should be list of {bar_idx, direction, sl, tp, size}
    for sig in (signals or []):
        idx = sig.get("bar_idx", 0)
        if idx < len(bars):
            open_trade(idx, sig.get("direction", "long"), bars[idx]["close"],
                       sig.get("sl", 0), sig.get("tp", 0), sig.get("size", 0.01))
    # Run SL/TP check
    for i in range(len(bars)):
        check_sl_tp(i)
        unrealized = 0
        for t in open_trades:
            mult = 1 if t["direction"] == "long" else -1
            unrealized += (bars[i]["close"] - t["entry_price"]) * mult * t["size"] * point_value
        equity_curve.append(balance + unrealized)

# Close remaining open trades
for trade in list(open_trades):
    close_trade(trade, len(bars) - 1, bars[-1]["close"], "end_of_data")

# Output results
output = {
    "trades": closed_trades,
    "equity_curve": equity_curve,
    "balance": balance,
}
print("__RESULT__" + json.dumps(output))
'''


def run_python_strategy(
    file_path: str,
    settings_values: dict[str, Any],
    bars_raw: list[dict],
    initial_balance: float,
    spread_points: float,
    commission_per_lot: float,
    point_value: float,
) -> BacktestResult:
    """Execute a Python strategy file in a subprocess."""
    if not os.path.exists(file_path):
        raise ValueError(f"Strategy file not found: {file_path}")

    # Write harness to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(PYTHON_HARNESS)
        harness_path = f.name

    try:
        input_data = json.dumps({
            "bars": bars_raw,
            "settings": settings_values,
            "config": {
                "initial_balance": initial_balance,
                "spread_points": spread_points,
                "commission_per_lot": commission_per_lot,
                "point_value": point_value,
            },
        })

        result = subprocess.run(
            [sys.executable, harness_path, file_path],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=120,  # 2 minute timeout
            cwd=os.path.dirname(file_path),
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip()[-500:] if result.stderr else "Unknown error"
            raise ValueError(f"Strategy execution failed: {error_msg}")

        # Extract result from stdout
        output = result.stdout
        marker = "__RESULT__"
        idx = output.rfind(marker)
        if idx == -1:
            raise ValueError("Strategy did not produce results. Ensure it defines on_bar() or evaluate().")

        result_json = json.loads(output[idx + len(marker):])
        return _build_result_from_raw(result_json, initial_balance, len(bars_raw))

    finally:
        try:
            os.unlink(harness_path)
        except OSError:
            pass


# ── JSON Strategy Runner ───────────────────────────────────────────


def run_json_strategy(
    file_path: str,
    settings_values: dict[str, Any],
    bars_raw: list[dict],
    initial_balance: float,
    spread_points: float,
    commission_per_lot: float,
    point_value: float,
) -> BacktestResult:
    """Execute a JSON strategy by converting it to the generic engine format."""
    from app.services.backtest.engine import BacktestEngine, Bar as BarClass

    if not os.path.exists(file_path):
        raise ValueError(f"Strategy file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Merge settings_values into the strategy config
    logic = data.get("logic", data)

    # Build strategy config compatible with generic BacktestEngine
    strategy_config = {
        "indicators": logic.get("indicators", []),
        "entry_rules": logic.get("entry_rules", []),
        "exit_rules": logic.get("exit_rules", []),
        "risk_params": logic.get("risk_params", {}),
        "filters": logic.get("filters", {}),
    }

    # Override risk_params with settings_values where applicable
    risk_keys = {"stop_loss_value", "take_profit_value", "position_size_value", "max_positions"}
    for key, val in settings_values.items():
        if key in risk_keys:
            strategy_config["risk_params"][key] = val
        elif key in strategy_config.get("filters", {}):
            strategy_config["filters"][key] = val
        else:
            # Try to find and override in indicator params
            for ind in strategy_config["indicators"]:
                if key in (ind.get("params") or {}):
                    ind["params"][key] = val

    bars = [
        BarClass(
            time=b.get("time", 0),
            open=b["open"],
            high=b["high"],
            low=b["low"],
            close=b["close"],
            volume=b.get("volume", 0),
        )
        for b in bars_raw
    ]

    engine = BacktestEngine(
        bars=bars,
        strategy_config=strategy_config,
        initial_balance=initial_balance,
        spread_points=spread_points,
        commission_per_lot=commission_per_lot,
        point_value=point_value,
    )
    return engine.run()


# ── Helpers ─────────────────────────────────────────────────────────

import math


def _build_result_from_raw(raw: dict, initial_balance: float, total_bars: int) -> BacktestResult:
    """Convert subprocess output to BacktestResult."""
    trades_raw = raw.get("trades", [])
    equity_curve = raw.get("equity_curve", [])

    trades = []
    for t in trades_raw:
        trades.append(Trade(
            entry_bar=t.get("entry_bar", 0),
            entry_time=t.get("entry_time", 0),
            entry_price=t.get("entry_price", 0),
            direction=t.get("direction", "long"),
            size=t.get("size", 0.01),
            stop_loss=t.get("stop_loss", 0),
            take_profit=t.get("take_profit", 0),
            exit_bar=t.get("exit_bar"),
            exit_time=t.get("exit_time"),
            exit_price=t.get("exit_price"),
            exit_reason=t.get("exit_reason", ""),
            pnl=t.get("pnl", 0),
        ))

    result = BacktestResult()
    result.trades = trades
    result.equity_curve = equity_curve
    result.total_trades = len(trades)
    result.total_bars = total_bars

    winners = [t for t in trades if t.pnl > 0]
    losers = [t for t in trades if t.pnl <= 0]
    result.winning_trades = len(winners)
    result.losing_trades = len(losers)
    result.win_rate = (len(winners) / len(trades) * 100) if trades else 0

    result.gross_profit = sum(t.pnl for t in winners)
    result.gross_loss = abs(sum(t.pnl for t in losers))
    result.net_profit = result.gross_profit - result.gross_loss
    result.profit_factor = (result.gross_profit / result.gross_loss) if result.gross_loss > 0 else 0

    result.avg_win = (result.gross_profit / len(winners)) if winners else 0
    result.avg_loss = (result.gross_loss / len(losers)) if losers else 0
    result.largest_win = max((t.pnl for t in winners), default=0)
    result.largest_loss = min((t.pnl for t in losers), default=0)
    result.avg_trade = (result.net_profit / len(trades)) if trades else 0

    # Drawdown
    peak = initial_balance
    max_dd = 0
    max_dd_pct = 0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = peak - eq
        dd_pct = (dd / peak * 100) if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
    result.max_drawdown = max_dd
    result.max_drawdown_pct = max_dd_pct

    # Sharpe ratio
    if len(trades) > 1:
        returns = [t.pnl for t in trades]
        avg_r = sum(returns) / len(returns)
        var = sum((r - avg_r) ** 2 for r in returns) / (len(returns) - 1)
        std = math.sqrt(var) if var > 0 else 0
        result.sharpe_ratio = (avg_r / std * math.sqrt(252)) if std > 0 else 0
    else:
        result.sharpe_ratio = 0

    # Expectancy
    if trades:
        wr = result.win_rate / 100
        result.expectancy = (wr * result.avg_win) - ((1 - wr) * result.avg_loss)

    return result
