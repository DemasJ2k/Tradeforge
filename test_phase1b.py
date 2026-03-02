"""Phase 1B — Metrics Fixes Smoke Tests.

Tests:
  1. CAGR uses actual timestamps (calendar days) when available
  2. CAGR fallback converts trading→calendar days correctly
  3. pnl_pct is NOT double-scaled in best/worst trade %
  4. bars_per_day auto-detection from timestamps
  5. detect_bars_per_day utility
  6. avg_trade_duration_hours is present
  7. Full compute_all_metrics round-trip with real-ish data
"""

import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

import numpy as np
from app.services.backtest.v2.analytics.metrics import (
    cagr,
    detect_bars_per_day,
    compute_all_metrics,
    TRADING_DAYS_PER_YEAR,
)


def test_cagr_with_timestamps():
    """CAGR should use actual calendar days when timestamps are provided."""
    # Equity: 10000 → 11000 over exactly 365 calendar days = 1 year
    eq = np.array([10_000.0, 11_000.0])
    ts_start = 1_700_000_000.0  # some Unix epoch
    ts_end = ts_start + 365 * 86_400  # +365 days

    timestamps = np.array([ts_start, ts_end])
    c = cagr(eq, bars_per_day=1.0, timestamps=timestamps)

    # Expected: (11000/10000)^(1/1) - 1 = 0.10
    assert abs(c - 0.10) < 0.001, f"CAGR with timestamps = {c}, expected ~0.10"
    print(f"  PASS: CAGR with timestamps = {c:.6f} (expected 0.10)")


def test_cagr_with_timestamps_half_year():
    """CAGR over 6 months should annualise correctly."""
    eq = np.array([10_000.0, 11_000.0])
    ts_start = 1_700_000_000.0
    ts_end = ts_start + 182.5 * 86_400  # ~6 months

    timestamps = np.array([ts_start, ts_end])
    c = cagr(eq, bars_per_day=1.0, timestamps=timestamps)

    # Expected: (1.10)^(365/182.5) - 1 = 1.10^2 - 1 = 0.21
    expected = 1.10 ** (365 / 182.5) - 1
    assert abs(c - expected) < 0.001, f"CAGR 6mo = {c}, expected ~{expected:.4f}"
    print(f"  PASS: CAGR half-year = {c:.6f} (expected {expected:.6f})")


def test_cagr_fallback_trading_days():
    """Without timestamps, CAGR should convert trading→calendar days."""
    # 252 daily bars = 1 trading year ≈ 1 calendar year
    n = 253  # 252 intervals
    eq = np.linspace(10_000, 11_000, n)

    c_fixed = cagr(eq, bars_per_day=1.0, timestamps=None)

    # With correction: trading_days=252, calendar_days = 252 * 365/252 = 365
    # years = 365/365 = 1.0
    # CAGR = (11000/10000)^1 - 1 = 0.10
    assert abs(c_fixed - 0.10) < 0.005, f"CAGR fallback = {c_fixed}, expected ~0.10"
    print(f"  PASS: CAGR fallback (252 bars) = {c_fixed:.6f} (expected ~0.10)")


def test_pnl_pct_not_double_scaled():
    """best_trade_pct / worst_trade_pct should NOT multiply by 100 again.

    position.py already stores pnl_pct as percentage (e.g. 5.0 for 5%).
    """
    equity_curve = [
        {"equity": 10000.0, "timestamp": 1700000000},
        {"equity": 10500.0, "timestamp": 1700086400},
        {"equity": 10300.0, "timestamp": 1700172800},
    ]
    closed_trades = [
        {"pnl": 500, "pnl_pct": 5.0, "duration_bars": 1, "commission": 0, "slippage": 0},
        {"pnl": -200, "pnl_pct": -2.0, "duration_bars": 1, "commission": 0, "slippage": 0},
    ]

    result = compute_all_metrics(
        equity_curve=equity_curve,
        closed_trades=closed_trades,
        initial_capital=10000.0,
        total_bars=3,
        bars_per_day=1.0,
    )

    best = result["best_trade_pct"]
    worst = result["worst_trade_pct"]

    # Should be 5.0 and -2.0, NOT 500 and -200
    assert best == 5.0, f"best_trade_pct = {best}, expected 5.0 (was double-scaled!)"
    assert worst == -2.0, f"worst_trade_pct = {worst}, expected -2.0 (was double-scaled!)"
    print(f"  PASS: best_trade_pct = {best}, worst_trade_pct = {worst}")


def test_detect_bars_per_day():
    """detect_bars_per_day should infer bar frequency from timestamps."""
    # M10 data: 1 bar every 600 seconds → 144 bars per 24h day
    n = 200
    ts = np.arange(n, dtype=np.float64) * 600.0 + 1_700_000_000.0

    detected = detect_bars_per_day(ts)
    assert detected is not None
    assert abs(detected - 144.0) < 1.0, f"Detected {detected}, expected ~144"
    print(f"  PASS: detect_bars_per_day (M10) = {detected}")


def test_auto_detect_in_compute():
    """compute_all_metrics should auto-detect bars_per_day from timestamps
    when caller leaves default (1.0) and timestamps indicate intraday data."""
    # Build 500 M10 bars with timestamps
    n = 500
    ts_base = 1_700_000_000.0
    equity_data = np.linspace(10000.0, 10500.0, n)
    equity_curve = [
        {"equity": float(equity_data[i]), "timestamp": ts_base + i * 600.0}
        for i in range(n)
    ]

    result = compute_all_metrics(
        equity_curve=equity_curve,
        closed_trades=[],
        initial_capital=10000.0,
        total_bars=n,
        bars_per_day=1.0,  # Default — should be overridden
    )

    # Should have detected ~144 (M10)
    bpd = result.get("bars_per_day_used", 1.0)
    assert bpd > 100, f"bars_per_day_used = {bpd}, expected auto-detected ~144"
    print(f"  PASS: auto-detected bars_per_day = {bpd}")


def test_duration_hours_present():
    """avg_trade_duration_hours should be present in output."""
    equity_curve = [
        {"equity": 10000.0, "timestamp": 1700000000},
        {"equity": 10100.0, "timestamp": 1700086400},
    ]
    closed_trades = [
        {"pnl": 100, "pnl_pct": 1.0, "duration_bars": 10, "commission": 0, "slippage": 0},
    ]

    result = compute_all_metrics(
        equity_curve=equity_curve,
        closed_trades=closed_trades,
        initial_capital=10000.0,
        total_bars=2,
        bars_per_day=144.0,
    )

    hours = result.get("avg_trade_duration_hours")
    assert hours is not None, "avg_trade_duration_hours missing from output"
    # 10 bars × (24h / 144 bars/day) = ~1.67 hours
    expected = 10 * 24.0 / 144.0
    assert abs(hours - expected) < 0.1, f"duration_hours = {hours}, expected ~{expected:.2f}"
    print(f"  PASS: avg_trade_duration_hours = {hours} (expected ~{expected:.2f})")


def test_full_round_trip():
    """Full compute_all_metrics with realistic data."""
    n = 1000
    ts_base = 1_700_000_000.0
    equity = 10000.0
    eq_list = []
    for i in range(n):
        eq_list.append({
            "equity": equity,
            "timestamp": ts_base + i * 600.0,  # M10
        })
        equity += np.random.normal(0.5, 5.0)  # Slight upward drift

    trades = []
    for j in range(20):
        pnl = np.random.normal(25, 100)
        trades.append({
            "pnl": float(pnl),
            "pnl_pct": float(pnl / 10000 * 100),  # percentage
            "duration_bars": int(np.random.randint(5, 50)),
            "commission": 1.0,
            "slippage": 0.5,
        })

    result = compute_all_metrics(
        equity_curve=eq_list,
        closed_trades=trades,
        initial_capital=10000.0,
        total_bars=n,
        bars_per_day=1.0,  # Will be auto-detected to ~144
    )

    # Sanity checks
    assert "cagr" in result
    assert "sharpe_ratio" in result
    assert "avg_trade_duration_hours" in result
    assert result["bars_per_day_used"] > 100  # Auto-detected M10
    assert result["total_trades"] == 20
    assert abs(result["best_trade_pct"]) < 50  # Not 5000 (no double-scale)
    print(f"  PASS: Full round-trip OK — CAGR={result['cagr']:.4f}, "
          f"Sharpe={result['sharpe_ratio']:.4f}, "
          f"bars_per_day={result['bars_per_day_used']}")


# ── Run all ──
if __name__ == "__main__":
    np.random.seed(42)
    tests = [
        test_cagr_with_timestamps,
        test_cagr_with_timestamps_half_year,
        test_cagr_fallback_trading_days,
        test_pnl_pct_not_double_scaled,
        test_detect_bars_per_day,
        test_auto_detect_in_compute,
        test_duration_hours_present,
        test_full_round_trip,
    ]

    passed = 0
    failed = 0
    for t in tests:
        print(f"\n[TEST] {t.__name__}")
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
    if failed == 0:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)
