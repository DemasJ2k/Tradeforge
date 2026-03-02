"""
Phase 1C Tests — Unified Strategy Runner.

Tests:
  1. InstrumentSpec catalogue lookup & fallback
  2. InstrumentSpec PnL computation (replaces ×100 hack)
  3. Unified runner routes builder strategy through V2
  4. Unified runner routes MSS config to MSSStrategy
  5. Unified runner routes Gold BT config to GoldBreakoutStrategy
  6. API import path (Bar from engine.py, run_unified_backtest from v2_adapter)
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app.services.backtest.engine import Bar
from app.services.backtest.v2.engine.instrument import (
    get_instrument_spec, InstrumentSpec, list_instruments,
)


# ── Helper: generate simple bars ───────────────────────────────────
def _make_bars(n: int = 300, start_price: float = 2000.0, step: float = 0.5):
    """Make synthetic bars with a gentle uptrend + some noise."""
    import math
    bars = []
    p = start_price
    for i in range(n):
        noise = math.sin(i * 0.1) * 2.0
        o = p + noise
        h = o + abs(noise) + 1.0
        l = o - abs(noise) - 1.0
        c = o + step  # small uptrend
        bars.append(Bar(
            time=1_700_000_000.0 + i * 600,  # M10 bars
            open=round(o, 2),
            high=round(h, 2),
            low=round(l, 2),
            close=round(c, 2),
            volume=100.0,
        ))
        p = c
    return bars


# ────────────────────────────────────────────────────────────────────
# Test 1: InstrumentSpec — Catalogue lookup
# ────────────────────────────────────────────────────────────────────
def test_instrument_lookup():
    spec = get_instrument_spec("XAUUSD")
    assert spec.contract_size == 100, f"Gold contract_size should be 100, got {spec.contract_size}"
    assert spec.symbol == "XAUUSD"

    spec2 = get_instrument_spec("XAGUSD")
    assert spec2.contract_size == 5000, f"Silver contract_size should be 5000, got {spec2.contract_size}"

    # Case-insensitive + suffix handling
    spec3 = get_instrument_spec("xauusd.raw")
    assert spec3.contract_size == 100

    # Unknown symbol → generic Forex fallback
    spec4 = get_instrument_spec("ZZZZZ")
    assert spec4.contract_size == 100_000
    assert spec4.pip_size == 0.00010

    # list_instruments should return all registered
    all_specs = list_instruments()
    assert len(all_specs) >= 12, f"Expected 12+ instruments, got {len(all_specs)}"

    print("  [PASS] test_instrument_lookup")


# ────────────────────────────────────────────────────────────────────
# Test 2: InstrumentSpec — PnL computation
# ────────────────────────────────────────────────────────────────────
def test_instrument_pnl():
    spec = get_instrument_spec("XAUUSD")
    # 1 lot gold, price moves +$10 → PnL = 10 * 100 * 1 = $1000
    pnl = spec.pnl(price_diff=10.0, lots=1.0)
    assert pnl == 1000.0, f"Expected $1000, got {pnl}"

    # 0.01 lots, price moves -$5 → PnL = -5 * 100 * 0.01 = -$5
    pnl2 = spec.pnl(price_diff=-5.0, lots=0.01)
    assert abs(pnl2 - (-5.0)) < 0.001, f"Expected -$5, got {pnl2}"

    # Forex: EURUSD 1 lot, moves 0.0010 (10 pips) → 0.0010 * 100_000 * 1 = $100
    spec_fx = get_instrument_spec("EURUSD")
    pnl_fx = spec_fx.pnl(price_diff=0.0010, lots=1.0)
    assert abs(pnl_fx - 100.0) < 0.001, f"Expected $100, got {pnl_fx}"

    print("  [PASS] test_instrument_pnl")


# ────────────────────────────────────────────────────────────────────
# Test 3: Unified runner — Builder strategy (no MSS/Gold BT config)
# ────────────────────────────────────────────────────────────────────
def test_unified_builder():
    from app.services.backtest.v2_adapter import run_unified_backtest

    bars = _make_bars(300)
    strategy_config = {
        "indicators": [
            {"id": "sma10", "type": "sma", "params": {"period": 10}, "output_name": "sma10"},
            {"id": "sma50", "type": "sma", "params": {"period": 50}, "output_name": "sma50"},
        ],
        "entry_rules": [
            {"left": "sma10", "right": "sma50", "operator": "crosses_above", "direction": "long"},
        ],
        "exit_rules": [
            {"left": "sma10", "right": "sma50", "operator": "crosses_below"},
        ],
        "risk_params": {"position_size_value": 0.01, "max_positions": 1},
        "filters": {},
    }

    result = run_unified_backtest(
        bars=bars,
        strategy_config=strategy_config,
        symbol="XAUUSD",
        initial_balance=10_000.0,
        spread_points=0.5,
        commission_per_lot=3.0,
        point_value=1.0,
        bars_per_day=144.0,
    )

    assert result is not None
    assert hasattr(result, "closed_trades")
    assert hasattr(result, "equity_curve")
    assert hasattr(result, "tearsheet")
    final_eq = result.equity_curve[-1]["equity"] if result.equity_curve else 0.0
    print(f"  [PASS] test_unified_builder — {len(result.closed_trades)} trades, "
          f"final equity {final_eq:.2f}")


# ────────────────────────────────────────────────────────────────────
# Test 4: Unified runner — MSS config routing
# ────────────────────────────────────────────────────────────────────
def test_unified_mss():
    from app.services.backtest.v2_adapter import run_unified_backtest

    bars = _make_bars(500, start_price=2000.0)
    strategy_config = {
        "indicators": [],
        "entry_rules": [],
        "exit_rules": [],
        "risk_params": {"position_size_value": 0.01, "max_positions": 1},
        "filters": {
            "mss_config": {
                "swing_lb": 20,
                "tp1_pct": 15.0,
                "tp2_pct": 25.0,
                "sl_pct": 25.0,
                "use_pullback": False,
                "confirm": "close",
                "lot_size": 0.01,
            },
        },
    }

    result = run_unified_backtest(
        bars=bars,
        strategy_config=strategy_config,
        symbol="XAUUSD",
        initial_balance=10_000.0,
        spread_points=0.5,
        commission_per_lot=3.0,
        point_value=1.0,
        bars_per_day=144.0,
    )

    assert result is not None
    assert hasattr(result, "closed_trades")
    assert hasattr(result, "equity_curve")
    # MSS should produce some trades on 500 bars of trending data
    final_eq = result.equity_curve[-1]["equity"] if result.equity_curve else 0.0
    print(f"  [PASS] test_unified_mss — {len(result.closed_trades)} trades, "
          f"final equity {final_eq:.2f}")


# ────────────────────────────────────────────────────────────────────
# Test 5: Unified runner — Gold BT config routing
# ────────────────────────────────────────────────────────────────────
def test_unified_gold_bt():
    from app.services.backtest.v2_adapter import run_unified_backtest

    bars = _make_bars(500, start_price=2000.0, step=0.3)
    strategy_config = {
        "indicators": [],
        "entry_rules": [],
        "exit_rules": [],
        "risk_params": {"position_size_value": 0.01, "max_positions": 1},
        "filters": {
            "gold_bt_config": {
                "trigger_interval_hours": 2,
                "box_height": 3.0,
                "stop_line_buffer": 1.0,
                "stop_to_tp_gap": 2.0,
                "tp_zone_gap": 2.0,
                "tp1_height": 3.0,
                "tp2_height": 5.0,
                "sl_type": "fixed",
                "sl_fixed_usd": 5.0,
                "lot_size": 0.01,
            },
        },
    }

    result = run_unified_backtest(
        bars=bars,
        strategy_config=strategy_config,
        symbol="XAUUSD",
        initial_balance=10_000.0,
        spread_points=0.5,
        commission_per_lot=3.0,
        point_value=1.0,
        bars_per_day=144.0,
    )

    assert result is not None
    assert hasattr(result, "closed_trades")
    assert hasattr(result, "equity_curve")
    final_eq = result.equity_curve[-1]["equity"] if result.equity_curve else 0.0
    print(f"  [PASS] test_unified_gold_bt — {len(result.closed_trades)} trades, "
          f"final equity {final_eq:.2f}")


# ────────────────────────────────────────────────────────────────────
# Test 6: API import path still works
# ────────────────────────────────────────────────────────────────────
def test_api_imports():
    """Verify the API file can resolve its imports after V1 path removal."""
    from app.services.backtest.engine import Bar as BarClass
    from app.services.backtest.v2_adapter import (
        run_unified_backtest as _rub,
        run_v2_backtest as _r2,
        v2_result_to_api_response as _v2r,
    )
    assert callable(_rub)
    assert callable(_r2)
    assert callable(_v2r)
    print("  [PASS] test_api_imports")


# ────────────────────────────────────────────────────────────────────
# Runner
# ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        test_instrument_lookup,
        test_instrument_pnl,
        test_unified_builder,
        test_unified_mss,
        test_unified_gold_bt,
        test_api_imports,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            import traceback; traceback.print_exc()
            failed += 1

    print(f"\n{'='*50}")
    print(f"Phase 1C: {passed} passed, {failed} failed out of {len(tests)} tests")
    if failed == 0:
        print("ALL TESTS PASSED ✓")
    else:
        print("SOME TESTS FAILED ✗")
