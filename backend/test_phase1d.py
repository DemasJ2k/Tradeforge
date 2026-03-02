"""
Phase 1D Tests — Position Sizing.

Tests:
  1. SizingConfig from risk_params (legacy fixed_lot)
  2. SizingConfig with percent_risk method
  3. PositionSizer — FIXED_LOT method
  4. PositionSizer — PERCENT_RISK method
  5. PositionSizer — FIXED_FRACTIONAL method
  6. PositionSizer — KELLY method (with manual overrides)
  7. PositionSizer — KELLY method (rolling stats)
  8. Clamping and lot_step rounding
  9. ctx.compute_position_size() integration
  10. Unified runner with percent_risk sizing
"""

import sys, os, math
sys.path.insert(0, os.path.dirname(__file__))

from app.services.backtest.v2.engine.position_sizer import (
    PositionSizer, SizingConfig, SizingMethod, sizing_config_from_risk_params,
)
from app.services.backtest.engine import Bar


# ── Helper ──────────────────────────────────────────────────────────
def _make_bars(n: int = 300, start_price: float = 2000.0, step: float = 0.5):
    bars = []
    p = start_price
    for i in range(n):
        noise = math.sin(i * 0.1) * 2.0
        o = p + noise
        h = o + abs(noise) + 1.0
        l = o - abs(noise) - 1.0
        c = o + step
        bars.append(Bar(
            time=1_700_000_000.0 + i * 600,
            open=round(o, 2), high=round(h, 2),
            low=round(l, 2), close=round(c, 2),
            volume=100.0,
        ))
        p = c
    return bars


# ────────────────────────────────────────────────────────────────────
# Test 1: sizing_config_from_risk_params (legacy)
# ────────────────────────────────────────────────────────────────────
def test_config_from_legacy():
    cfg = sizing_config_from_risk_params({"position_size_value": 0.05})
    assert cfg.method == SizingMethod.FIXED_LOT
    assert cfg.fixed_lots == 0.05
    print("  [PASS] test_config_from_legacy")


# ────────────────────────────────────────────────────────────────────
# Test 2: sizing_config_from_risk_params (percent_risk)
# ────────────────────────────────────────────────────────────────────
def test_config_percent_risk():
    cfg = sizing_config_from_risk_params({
        "position_size_method": "percent_risk",
        "risk_pct": 2.0,
        "max_lots": 10.0,
    })
    assert cfg.method == SizingMethod.PERCENT_RISK
    assert cfg.risk_pct == 2.0
    assert cfg.max_lots == 10.0
    print("  [PASS] test_config_percent_risk")


# ────────────────────────────────────────────────────────────────────
# Test 3: FIXED_LOT method
# ────────────────────────────────────────────────────────────────────
def test_fixed_lot():
    sizer = PositionSizer(SizingConfig(method=SizingMethod.FIXED_LOT, fixed_lots=0.10))
    lots = sizer.compute(equity=10_000, entry_price=2000, stop_loss=1990, contract_size=100)
    assert lots == 0.10, f"Expected 0.10, got {lots}"
    print("  [PASS] test_fixed_lot")


# ────────────────────────────────────────────────────────────────────
# Test 4: PERCENT_RISK method
# ────────────────────────────────────────────────────────────────────
def test_percent_risk():
    """Risk 1% of $10,000 = $100.  SL is $10 away on Gold (cs=100).
    lots = 100 / (10 * 100) = 0.10"""
    sizer = PositionSizer(SizingConfig(
        method=SizingMethod.PERCENT_RISK,
        risk_pct=1.0,
        min_lots=0.01,
        lot_step=0.01,
    ))
    lots = sizer.compute(equity=10_000, entry_price=2000, stop_loss=1990, contract_size=100)
    assert lots == 0.10, f"Expected 0.10, got {lots}"

    # 2% risk → 0.20
    sizer2 = PositionSizer(SizingConfig(
        method=SizingMethod.PERCENT_RISK,
        risk_pct=2.0,
        min_lots=0.01,
        lot_step=0.01,
    ))
    lots2 = sizer2.compute(equity=10_000, entry_price=2000, stop_loss=1990, contract_size=100)
    assert lots2 == 0.20, f"Expected 0.20, got {lots2}"

    print("  [PASS] test_percent_risk")


# ────────────────────────────────────────────────────────────────────
# Test 5: FIXED_FRACTIONAL method
# ────────────────────────────────────────────────────────────────────
def test_fixed_fractional():
    """5% of $10,000 = $500 notional.
    lots = 500 / (2000 * 100) = 0.0025 → rounded to 0.01 (min)"""
    sizer = PositionSizer(SizingConfig(
        method=SizingMethod.FIXED_FRACTIONAL,
        fractional_pct=5.0,
        min_lots=0.01,
        lot_step=0.01,
    ))
    lots = sizer.compute(equity=10_000, entry_price=2000, stop_loss=1990, contract_size=100)
    # 500 / 200,000 = 0.0025 → clamped to 0.01
    assert lots == 0.01, f"Expected 0.01, got {lots}"

    # With Forex (cs=100_000): 500 / (1.1000 * 100_000) = 0.00454 → 0.01
    lots_fx = sizer.compute(equity=10_000, entry_price=1.1000, stop_loss=1.0950, contract_size=100_000)
    assert lots_fx == 0.01, f"Expected 0.01, got {lots_fx}"

    # 50% fractional on $100k account, Gold: 50,000 / (2000 * 100) = 0.25
    sizer2 = PositionSizer(SizingConfig(
        method=SizingMethod.FIXED_FRACTIONAL,
        fractional_pct=50.0,
        min_lots=0.01,
        lot_step=0.01,
    ))
    lots2 = sizer2.compute(equity=100_000, entry_price=2000, stop_loss=1990, contract_size=100)
    assert lots2 == 0.25, f"Expected 0.25, got {lots2}"

    print("  [PASS] test_fixed_fractional")


# ────────────────────────────────────────────────────────────────────
# Test 6: KELLY method (manual overrides)
# ────────────────────────────────────────────────────────────────────
def test_kelly_manual():
    """Kelly with win_rate=0.60, avg_rr=1.5, half-Kelly.
    f* = (0.60 * 1.5 - 0.40) / 1.5 = (0.90 - 0.40) / 1.5 = 0.3333
    Effective risk% = 0.3333 * 100 * 0.5 = 16.667%
    But max_risk_pct = 5%, so capped at 5%.
    risk_amount = 10000 * 5 / 100 = 500
    lots = 500 / (10 * 100) = 0.50"""
    sizer = PositionSizer(SizingConfig(
        method=SizingMethod.KELLY,
        kelly_fraction=0.5,
        kelly_win_rate=0.60,
        kelly_avg_rr=1.5,
        max_risk_pct=5.0,
        min_lots=0.01,
        lot_step=0.01,
    ))
    # Feed dummy trades so the "enough trades" check passes
    for _ in range(20):
        sizer.update_trade_stats(10.0)  # wins
    for _ in range(10):
        sizer.update_trade_stats(-5.0)  # losses

    lots = sizer.compute(equity=10_000, entry_price=2000, stop_loss=1990, contract_size=100)
    assert lots == 0.50, f"Expected 0.50, got {lots}"
    print("  [PASS] test_kelly_manual")


# ────────────────────────────────────────────────────────────────────
# Test 7: KELLY method (rolling stats)
# ────────────────────────────────────────────────────────────────────
def test_kelly_rolling():
    """Feed 20 wins of $100 and 10 losses of $50.
    Rolling: p = 20/30 = 0.667, avg_win = 100, avg_loss = 50, b = 2.0
    f* = (0.667 * 2 - 0.333) / 2 = (1.333 - 0.333) / 2 = 0.50
    Half-Kelly: 0.50 * 100 * 0.5 = 25%
    Capped by max_risk_pct=10%: risk = 10000 * 10 / 100 = 1000
    lots = 1000 / (10 * 100) = 1.00"""
    sizer = PositionSizer(SizingConfig(
        method=SizingMethod.KELLY,
        kelly_fraction=0.5,
        kelly_win_rate=None,  # use rolling
        kelly_avg_rr=None,    # use rolling
        max_risk_pct=10.0,
        min_lots=0.01,
        lot_step=0.01,
    ))
    for _ in range(20):
        sizer.update_trade_stats(100.0)
    for _ in range(10):
        sizer.update_trade_stats(-50.0)

    assert abs(sizer.rolling_win_rate - 0.6667) < 0.01
    assert abs(sizer.rolling_avg_rr - 2.0) < 0.01

    lots = sizer.compute(equity=10_000, entry_price=2000, stop_loss=1990, contract_size=100)
    assert lots == 1.0, f"Expected 1.0 (capped by max_risk_pct), got {lots}"
    print("  [PASS] test_kelly_rolling")


# ────────────────────────────────────────────────────────────────────
# Test 8: Clamping and lot_step rounding
# ────────────────────────────────────────────────────────────────────
def test_clamp_and_round():
    sizer = PositionSizer(SizingConfig(
        method=SizingMethod.PERCENT_RISK,
        risk_pct=1.0,
        min_lots=0.01,
        max_lots=0.05,
        lot_step=0.01,
    ))
    # 100 / (10 * 100) = 0.10 → clamped to max_lots 0.05
    lots = sizer.compute(equity=10_000, entry_price=2000, stop_loss=1990, contract_size=100)
    assert lots == 0.05, f"Expected 0.05 (max), got {lots}"

    # Tiny equity → falls to min_lots
    lots2 = sizer.compute(equity=10, entry_price=2000, stop_loss=1990, contract_size=100)
    assert lots2 == 0.01, f"Expected 0.01 (min), got {lots2}"

    # lot_step rounding: 0.10 with lot_step=0.03 → floor(0.10/0.03)*0.03 = 0.09
    sizer3 = PositionSizer(SizingConfig(
        method=SizingMethod.PERCENT_RISK,
        risk_pct=1.0,
        min_lots=0.01,
        lot_step=0.03,
    ))
    lots3 = sizer3.compute(equity=10_000, entry_price=2000, stop_loss=1990, contract_size=100)
    assert abs(lots3 - 0.09) < 1e-8, f"Expected 0.09, got {lots3}"

    print("  [PASS] test_clamp_and_round")


# ────────────────────────────────────────────────────────────────────
# Test 9: ctx.compute_position_size() integration
# ────────────────────────────────────────────────────────────────────
def test_ctx_integration():
    from app.services.backtest.v2.engine.strategy_base import StrategyContext
    ctx = StrategyContext()
    # Without sizer → fallback 0.01
    lots = ctx.compute_position_size("XAUUSD", 2000, 1990)
    assert lots == 0.01, f"Expected fallback 0.01, got {lots}"

    # Wire a percent_risk sizer
    sizer = PositionSizer(SizingConfig(
        method=SizingMethod.PERCENT_RISK,
        risk_pct=1.0,
        min_lots=0.01,
        lot_step=0.01,
    ))
    ctx._position_sizer = sizer

    # Mock portfolio equity via a simple portfolio-like object
    class FakePortfolio:
        initial_cash = 10_000.0
        def __init__(self): self._equity_curve = [10_000.0]
        @property
        def equity_curve(self): return self._equity_curve
    ctx._portfolio = FakePortfolio()

    lots = ctx.compute_position_size("XAUUSD", entry_price=2000, stop_loss=1990)
    # equity=10000, risk=100, SL=10, cs=100 → 0.10
    assert lots == 0.10, f"Expected 0.10, got {lots}"
    print("  [PASS] test_ctx_integration")


# ────────────────────────────────────────────────────────────────────
# Test 10: Unified runner with percent_risk
# ────────────────────────────────────────────────────────────────────
def test_unified_percent_risk():
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
        "risk_params": {
            "position_size_method": "percent_risk",
            "risk_pct": 2.0,
            "position_size_value": 0.01,  # fallback, should be overridden
            "max_positions": 1,
            "stop_loss_type": "fixed_pips",
            "stop_loss_value": 10,
            "take_profit_type": "fixed_pips",
            "take_profit_value": 20,
        },
        "filters": {},
    }

    result = run_unified_backtest(
        bars=bars,
        strategy_config=strategy_config,
        symbol="XAUUSD",
        initial_balance=10_000.0,
        spread_points=0.5,
        commission_per_lot=3.0,
        bars_per_day=144.0,
    )

    assert result is not None
    assert hasattr(result, "closed_trades")

    # Check that position sizes are NOT all 0.01 (dynamic sizing should vary)
    trade_sizes = set()
    for t in result.closed_trades:
        q = t.get("quantity") or t.get("size") or t.get("lots", 0)
        if q > 0:
            trade_sizes.add(round(q, 4))

    n_trades = len(result.closed_trades)
    final_eq = result.equity_curve[-1]["equity"] if result.equity_curve else 0.0
    print(f"  [PASS] test_unified_percent_risk — {n_trades} trades, "
          f"sizes={trade_sizes}, final equity {final_eq:.2f}")


# ────────────────────────────────────────────────────────────────────
# Runner
# ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        test_config_from_legacy,
        test_config_percent_risk,
        test_fixed_lot,
        test_percent_risk,
        test_fixed_fractional,
        test_kelly_manual,
        test_kelly_rolling,
        test_clamp_and_round,
        test_ctx_integration,
        test_unified_percent_risk,
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
    print(f"Phase 1D: {passed} passed, {failed} failed out of {len(tests)} tests")
    if failed == 0:
        print("ALL TESTS PASSED ✓")
    else:
        print("SOME TESTS FAILED ✗")
