"""
Phase 6: V2 Engine API Integration Tests.

Tests the V2 adapter pipeline:
  1. BuilderStrategy with rule-based config
  2. run_v2_backtest() produces valid RunResult
  3. v2_result_to_api_response() produces correct response shape
  4. Schema compatibility (BacktestRequest / BacktestResponse)
  5. V1 backward compat (result_to_v1)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

import math
import random

from app.services.backtest.engine import Bar
from app.services.backtest.v2_adapter import (
    run_v2_backtest,
    v2_result_to_api_response,
    v2_result_to_v1,
    BuilderStrategy,
)
from app.schemas.backtest import (
    BacktestRequest,
    BacktestResponse,
    BacktestStats,
    TradeResult,
)


# ── Helpers ──

def make_bars(n=500, start_price=2000.0, seed=42):
    """Generate synthetic OHLCV bars."""
    random.seed(seed)
    bars = []
    price = start_price
    for i in range(n):
        move = random.gauss(0, 5)
        o = price
        h = o + abs(random.gauss(0, 3))
        l = o - abs(random.gauss(0, 3))
        c = o + move
        price = c
        bars.append(Bar(
            time=1700000000 + i * 600,  # 10-min bars
            open=round(o, 2),
            high=round(max(o, h, c), 2),
            low=round(min(o, l, c), 2),
            close=round(c, 2),
            volume=random.randint(100, 1000),
        ))
    return bars


SMA_STRATEGY_CONFIG = {
    "indicators": [
        {"id": "sma_fast", "type": "SMA", "params": {"period": 10, "source": "close"}},
        {"id": "sma_slow", "type": "SMA", "params": {"period": 30, "source": "close"}},
    ],
    "entry_rules": [
        {"left": "sma_fast", "operator": "crosses_above", "right": "sma_slow", "direction": "long", "logic": "AND"},
        {"left": "sma_fast", "operator": "crosses_below", "right": "sma_slow", "direction": "short", "logic": "OR"},
    ],
    "exit_rules": [],
    "risk_params": {
        "stop_loss_type": "fixed_pips",
        "stop_loss_value": 20,
        "take_profit_type": "fixed_pips",
        "take_profit_value": 40,
        "position_size_value": 0.1,
        "max_positions": 1,
    },
    "filters": {},
}


# ── Tests ──

def test_builder_strategy_creates():
    """BuilderStrategy initializes without error."""
    strat = BuilderStrategy(SMA_STRATEGY_CONFIG, symbol="XAUUSD", point_value=1.0)
    assert strat.name == "BuilderStrategy"
    assert strat.symbol == "XAUUSD"
    print("  [PASS] test_builder_strategy_creates")


def test_run_v2_backtest_basic():
    """run_v2_backtest runs and returns a RunResult."""
    bars = make_bars(500)
    result = run_v2_backtest(
        bars=bars,
        strategy_config=SMA_STRATEGY_CONFIG,
        symbol="XAUUSD",
        initial_balance=10000.0,
        spread_points=0.3,
        commission_per_lot=7.0,
        point_value=1.0,
        bars_per_day=144,
    )
    assert result is not None
    assert result.bars_processed > 0
    assert result.elapsed_seconds >= 0
    assert len(result.equity_curve) > 0
    # Stats dict should have metrics
    assert "total_trades" in result.stats or "net_profit" in result.stats
    print(f"  [PASS] test_run_v2_backtest_basic — {result.bars_processed} bars, "
          f"{len(result.closed_trades)} trades, {result.elapsed_seconds:.3f}s")


def test_run_v2_with_fast_core():
    """run_v2_backtest with use_fast_core=True."""
    bars = make_bars(300)
    result = run_v2_backtest(
        bars=bars,
        strategy_config=SMA_STRATEGY_CONFIG,
        symbol="XAUUSD",
        initial_balance=10000.0,
        spread_points=0.3,
        commission_per_lot=7.0,
        point_value=1.0,
        use_fast_core=True,
        bars_per_day=144,
    )
    assert result is not None
    assert len(result.equity_curve) > 0
    print(f"  [PASS] test_run_v2_with_fast_core — {result.bars_processed} bars, "
          f"{len(result.closed_trades)} trades")


def test_v2_result_to_api_response():
    """v2_result_to_api_response produces the correct shape."""
    bars = make_bars(500)
    result = run_v2_backtest(
        bars=bars,
        strategy_config=SMA_STRATEGY_CONFIG,
        symbol="XAUUSD",
        initial_balance=10000.0,
        spread_points=0.3,
        commission_per_lot=7.0,
        point_value=1.0,
        bars_per_day=144,
    )
    api_data = v2_result_to_api_response(result, 10000.0, len(bars))

    # Check required keys
    assert "stats" in api_data
    assert "trades" in api_data
    assert "equity_curve" in api_data
    assert "v2_stats" in api_data
    assert "tearsheet" in api_data
    assert "elapsed_seconds" in api_data

    # Check stats has V1-compatible fields
    stats = api_data["stats"]
    for key in ["total_trades", "win_rate", "net_profit", "profit_factor",
                "max_drawdown", "sharpe_ratio", "expectancy", "total_bars"]:
        assert key in stats, f"Missing key: {key}"

    # Check equity curve is flat list of floats
    assert isinstance(api_data["equity_curve"], list)
    if api_data["equity_curve"]:
        assert isinstance(api_data["equity_curve"][0], float)

    # Check trades are dicts
    if api_data["trades"]:
        t = api_data["trades"][0]
        assert "entry_bar" in t
        assert "pnl" in t

    print(f"  [PASS] test_v2_result_to_api_response — stats: {len(stats)} fields, "
          f"trades: {len(api_data['trades'])}, eq: {len(api_data['equity_curve'])} pts")


def test_v2_result_to_v1():
    """v2_result_to_v1 produces a V1-compatible BacktestResult."""
    bars = make_bars(500)
    result = run_v2_backtest(
        bars=bars,
        strategy_config=SMA_STRATEGY_CONFIG,
        symbol="XAUUSD",
        initial_balance=10000.0,
        spread_points=0.3,
        commission_per_lot=7.0,
        point_value=1.0,
        bars_per_day=144,
    )
    v1 = v2_result_to_v1(result, 10000.0, len(bars))

    assert hasattr(v1, "trades")
    assert hasattr(v1, "equity_curve")
    assert hasattr(v1, "total_trades")
    assert hasattr(v1, "win_rate")
    assert hasattr(v1, "net_profit")
    assert hasattr(v1, "sharpe_ratio")
    print(f"  [PASS] test_v2_result_to_v1 — {v1.total_trades} trades, "
          f"profit={v1.net_profit:.2f}")


def test_schema_v2_fields():
    """BacktestRequest accepts V2 fields, BacktestResponse includes V2 extensions."""
    req = BacktestRequest(
        strategy_id=1,
        datasource_id=1,
        engine_version="v2",
        slippage_pct=0.001,
        commission_pct=0.001,
        margin_rate=0.01,
        use_fast_core=True,
        bars_per_day=144,
        tick_mode="ohlc_five",
    )
    assert req.engine_version == "v2"
    assert req.use_fast_core is True
    assert req.bars_per_day == 144

    # BacktestResponse with V2 extensions
    resp = BacktestResponse(
        id=1,
        strategy_id=1,
        datasource_id=1,
        status="completed",
        stats=BacktestStats(total_trades=10, net_profit=100),
        trades=[],
        equity_curve=[10000, 10100],
        engine_version="v2",
        v2_stats={"calmar_ratio": 1.5, "sortino_ratio": 2.0},
        tearsheet={"metrics": {}, "monte_carlo": {}},
        elapsed_seconds=0.5,
    )
    assert resp.engine_version == "v2"
    assert resp.v2_stats["calmar_ratio"] == 1.5
    assert resp.tearsheet is not None
    print("  [PASS] test_schema_v2_fields")


def test_schema_v1_backward_compat():
    """V1 requests still work (new fields have defaults)."""
    req = BacktestRequest(strategy_id=1, datasource_id=1)
    assert req.engine_version == "v1"
    assert req.slippage_pct == 0.0
    assert req.use_fast_core is False

    # V1 response (no V2 fields)
    resp = BacktestResponse(
        id=1, strategy_id=1, datasource_id=1, status="completed",
        stats=BacktestStats(), trades=[], equity_curve=[10000],
    )
    assert resp.engine_version == "v1"
    assert resp.v2_stats is None
    assert resp.tearsheet is None
    print("  [PASS] test_schema_v1_backward_compat")


def test_tearsheet_present():
    """V2 result includes tearsheet data."""
    bars = make_bars(500)
    result = run_v2_backtest(
        bars=bars,
        strategy_config=SMA_STRATEGY_CONFIG,
        symbol="XAUUSD",
        initial_balance=10000.0,
        spread_points=0.3,
        commission_per_lot=7.0,
        point_value=1.0,
        bars_per_day=144,
    )
    assert result.tearsheet is not None
    assert isinstance(result.tearsheet, dict)
    # Should have at least metrics key
    assert "metrics" in result.tearsheet
    print(f"  [PASS] test_tearsheet_present — keys: {list(result.tearsheet.keys())}")


def test_empty_strategy_no_crash():
    """A strategy with no rules shouldn't crash (0 trades is fine)."""
    bars = make_bars(200)
    empty_config = {
        "indicators": [],
        "entry_rules": [],
        "exit_rules": [],
        "risk_params": {},
        "filters": {},
    }
    result = run_v2_backtest(
        bars=bars,
        strategy_config=empty_config,
        symbol="TEST",
        initial_balance=10000.0,
    )
    assert result is not None
    assert len(result.closed_trades) == 0
    print("  [PASS] test_empty_strategy_no_crash")


def test_rsi_strategy():
    """Test a strategy with RSI indicator."""
    bars = make_bars(500)
    config = {
        "indicators": [
            {"id": "rsi_14", "type": "RSI", "params": {"period": 14, "source": "close"}},
        ],
        "entry_rules": [
            {"left": "rsi_14", "operator": "<", "right": "30", "direction": "long", "logic": "AND"},
        ],
        "exit_rules": [
            {"left": "rsi_14", "operator": ">", "right": "70", "logic": "AND"},
        ],
        "risk_params": {
            "stop_loss_type": "fixed_pips",
            "stop_loss_value": 30,
            "take_profit_type": "fixed_pips",
            "take_profit_value": 60,
            "position_size_value": 0.1,
            "max_positions": 1,
        },
        "filters": {},
    }
    result = run_v2_backtest(
        bars=bars,
        strategy_config=config,
        symbol="XAUUSD",
        initial_balance=10000.0,
        spread_points=0.3,
        commission_per_lot=7.0,
        point_value=1.0,
        bars_per_day=144,
    )
    assert result is not None
    print(f"  [PASS] test_rsi_strategy — {len(result.closed_trades)} trades")


# ── Runner ──

if __name__ == "__main__":
    tests = [
        test_builder_strategy_creates,
        test_run_v2_backtest_basic,
        test_run_v2_with_fast_core,
        test_v2_result_to_api_response,
        test_v2_result_to_v1,
        test_schema_v2_fields,
        test_schema_v1_backward_compat,
        test_tearsheet_present,
        test_empty_strategy_no_crash,
        test_rsi_strategy,
    ]

    passed = 0
    failed = 0
    print(f"\n{'='*60}")
    print(f"  Phase 6: API Integration Tests ({len(tests)} tests)")
    print(f"{'='*60}\n")

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {test.__name__}: {e}")

    print(f"\n{'='*60}")
    print(f"  Results: {passed}/{len(tests)} passed, {failed} failed")
    print(f"{'='*60}\n")

    sys.exit(0 if failed == 0 else 1)
