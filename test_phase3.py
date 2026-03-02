"""
Phase 3 Smoke Test — Analytics Tearsheet
Run with:  python test_phase3.py
"""
import sys, os, time, math, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from app.services.backtest.v2.engine.events import BarEvent, EventType, timestamp_ns_from_unix
from app.services.backtest.v2.engine.data_handler import DataHandler
from app.services.backtest.v2.engine.strategy_base import StrategyBase
from app.services.backtest.v2.engine.runner import Runner, RunConfig

# ────────────────────────────────────────────────────────────────
# Simple SMA crossover strategy for testing
# ────────────────────────────────────────────────────────────────
class SMACrossover(StrategyBase):
    def on_init(self):
        self._fast = 10
        self._slow = 30

    def on_bar(self, bar):
        dh = self.ctx._data_handler
        sym = bar.symbol
        idx = bar.bar_index
        if idx < self._slow:
            return

        fast_vals = [dh.get_value(sym, "price.close", idx - i) for i in range(self._fast)]
        slow_vals = [dh.get_value(sym, "price.close", idx - i) for i in range(self._slow)]
        fast_ma = sum(fast_vals) / self._fast
        slow_ma = sum(slow_vals) / self._slow

        pos = self.ctx._portfolio.position_book.positions.get(sym)
        has_long = pos and not pos.is_flat and pos.side.value == "long"
        has_short = pos and not pos.is_flat and pos.side.value == "short"

        if fast_ma > slow_ma and not has_long:
            if has_short:
                self.ctx.close_position(sym)
            self.ctx.buy_market(sym, 1.0)
        elif fast_ma < slow_ma and not has_short:
            if has_long:
                self.ctx.close_position(sym)
            self.ctx.sell_market(sym, 1.0)

# ────────────────────────────────────────────────────────────────
# Generate synthetic bar data
# ────────────────────────────────────────────────────────────────
def make_bars(n=500, start_price=2000.0, seed=42):
    rng = random.Random(seed)
    bars = []
    price = start_price
    for i in range(n):
        o = price
        c = o + rng.gauss(0, 5)
        h = max(o, c) + abs(rng.gauss(0, 2))
        l = min(o, c) - abs(rng.gauss(0, 2))
        ts = 1700000000 + i * 600  # 10-minute bars
        bars.append({
            "time": ts,
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
            "volume": rng.randint(100, 1000),
        })
        price = c
    return bars

# ────────────────────────────────────────────────────────────────
# Test 1: Full tearsheet via runner
# ────────────────────────────────────────────────────────────────
def test_full_tearsheet():
    print("=" * 60)
    print("TEST 1: Full Tearsheet via Runner (SMA crossover, 500 bars)")
    print("=" * 60)

    bars = make_bars(500)
    data = DataHandler()
    data.add_symbol("XAUUSD", bars)

    strategy = SMACrossover(params={})
    config = RunConfig(
        initial_cash=100_000,
        commission_per_lot=7.0,
        spread=0.3,
        bars_per_day=144,  # M10 bars
    )
    runner = Runner(data_handler=data, strategy=strategy, config=config)
    result = runner.run()

    print(f"  Bars processed: {result.bars_processed}")
    print(f"  Trades: {result.stats['total_trades']}")
    print(f"  Elapsed: {result.elapsed_seconds:.4f}s")
    print()

    # Check stats has 30+ keys
    stats = result.stats
    n_metrics = len([k for k in stats.keys() if k != "monthly_returns"])
    print(f"  Metrics count: {n_metrics} (target: 30+)")
    assert n_metrics >= 30, f"Expected 30+ metrics, got {n_metrics}"
    print("  [OK] 30+ metrics present")

    # Spot-check key metrics exist
    expected_keys = [
        "total_trades", "win_rate", "profit_factor", "expectancy",
        "cagr", "annualized_volatility", "sharpe_ratio", "sortino_ratio",
        "calmar_ratio", "omega_ratio", "gain_to_pain_ratio",
        "ulcer_index", "ulcer_performance_index",
        "var_95", "var_99", "cvar_95", "cvar_99",
        "max_drawdown_pct", "max_drawdown_duration_bars",
        "avg_drawdown_pct", "risk_of_ruin",
        "kelly_criterion", "exposure_time_pct",
        "max_consecutive_wins", "max_consecutive_losses",
        "sqn", "best_trade_pct", "worst_trade_pct",
        "total_fees", "initial_capital", "final_equity", "total_return_pct",
    ]
    missing = [k for k in expected_keys if k not in stats]
    assert not missing, f"Missing metrics: {missing}"
    print("  [OK] All expected metric keys present")

    # Print key metrics
    for k in ["total_trades", "win_rate", "net_profit", "cagr",
              "sharpe_ratio", "sortino_ratio", "calmar_ratio",
              "max_drawdown_pct", "kelly_criterion", "var_95",
              "risk_of_ruin", "total_return_pct"]:
        print(f"    {k}: {stats[k]}")

    print()

    # Check tearsheet has all sections
    ts = result.tearsheet
    assert ts is not None, "Tearsheet should not be None"
    assert "metrics" in ts
    assert "equity_curve" in ts
    assert "drawdown_curve" in ts
    print("  [OK] Tearsheet has metrics, equity_curve, drawdown_curve")

    if "monte_carlo" in ts and ts["monte_carlo"] is not None:
        mc = ts["monte_carlo"]
        print(f"  [OK] Monte Carlo: {mc['n_simulations']} sims, bust_prob={mc['bust_probability']}, goal_prob={mc['goal_probability']}")
        assert mc["n_simulations"] == 1000
        assert "equity_fan" in mc
    else:
        print("  [SKIP] Monte Carlo (no trades or disabled)")

    if "benchmark" in ts and ts["benchmark"] is not None:
        bm = ts["benchmark"]
        print(f"  [OK] Benchmark: alpha={bm['alpha']}, beta={bm['beta']}, IR={bm['information_ratio']}")
        print(f"         buy_hold_return={bm['buy_and_hold_return_pct']}%")
    else:
        print("  [SKIP] Benchmark (no close prices)")

    if "rolling" in ts and ts["rolling"] is not None:
        roll = ts["rolling"]
        print(f"  [OK] Rolling: window={roll['window']}, sharpe_len={len(roll['sharpe'])}, vol_len={len(roll['volatility'])}")
        # Check that rolling arrays match equity curve length
        assert len(roll["sharpe"]) == len(ts["equity_curve"])
    else:
        print("  [SKIP] Rolling (disabled)")

    print()
    print("  >>> TEST 1 PASSED <<<")
    print()


# ────────────────────────────────────────────────────────────────
# Test 2: Standalone analytics modules
# ────────────────────────────────────────────────────────────────
def test_standalone_analytics():
    print("=" * 60)
    print("TEST 2: Standalone Analytics Modules")
    print("=" * 60)

    import numpy as np
    from app.services.backtest.v2.analytics.metrics import (
        compute_all_metrics, equity_to_returns, cagr, sharpe_ratio,
        max_drawdown, value_at_risk, kelly_criterion,
    )
    from app.services.backtest.v2.analytics.monte_carlo import (
        run_monte_carlo, MonteCarloConfig,
    )
    from app.services.backtest.v2.analytics.benchmark import (
        compute_benchmark, buy_and_hold_equity, ols_alpha_beta,
    )
    from app.services.backtest.v2.analytics.rolling import (
        compute_rolling, RollingConfig, rolling_sharpe,
    )

    # Build synthetic equity curve
    rng = np.random.default_rng(42)
    n = 500
    returns = rng.normal(0.0003, 0.01, n)
    eq = 100_000 * np.cumprod(1 + returns)
    equity_curve = [{"equity": float(eq[i]), "timestamp": 1700000000 + i * 600} for i in range(n)]
    close_prices = 2000.0 + np.cumsum(rng.normal(0, 5, n))

    trades = [
        {"pnl": 150, "pnl_pct": 0.015, "duration_bars": 20, "commission": 7, "slippage": 2},
        {"pnl": -80, "pnl_pct": -0.008, "duration_bars": 10, "commission": 7, "slippage": 2},
        {"pnl": 200, "pnl_pct": 0.02, "duration_bars": 30, "commission": 7, "slippage": 2},
        {"pnl": -50, "pnl_pct": -0.005, "duration_bars": 5, "commission": 7, "slippage": 2},
        {"pnl": 300, "pnl_pct": 0.03, "duration_bars": 25, "commission": 7, "slippage": 2},
        {"pnl": -120, "pnl_pct": -0.012, "duration_bars": 15, "commission": 7, "slippage": 2},
        {"pnl": 180, "pnl_pct": 0.018, "duration_bars": 18, "commission": 7, "slippage": 2},
        {"pnl": 90, "pnl_pct": 0.009, "duration_bars": 12, "commission": 7, "slippage": 2},
    ]

    # 2a: Metrics
    metrics = compute_all_metrics(equity_curve, trades, 100_000, n, bars_per_day=144)
    print(f"  Metrics: {len([k for k in metrics if k != 'monthly_returns'])} keys")
    print(f"    CAGR: {metrics['cagr']}")
    print(f"    Sharpe: {metrics['sharpe_ratio']}")
    print(f"    Max DD: {metrics['max_drawdown_pct']}%")
    print(f"    Kelly: {metrics['kelly_criterion']}")
    print(f"    VaR 95: {metrics['var_95']}")
    print("  [OK] Metrics computed")

    # 2b: Monte Carlo
    mc = run_monte_carlo(trades, 100_000, MonteCarloConfig(n_simulations=500, seed=42))
    print(f"  MC: bust={mc.bust_probability}, goal={mc.goal_probability}, median_ret={mc.median_return}")
    assert mc.n_simulations == 500
    assert len(mc.equity_fan) > 0
    print("  [OK] Monte Carlo computed")

    # 2c: Benchmark
    bm = compute_benchmark(equity_curve, close_prices, 100_000, bars_per_day=144)
    print(f"  Benchmark: alpha={bm.alpha}, beta={bm.beta}, IR={bm.information_ratio}")
    print("  [OK] Benchmark computed")

    # 2d: Rolling
    roll = compute_rolling(equity_curve, trades, close_prices, 100_000, RollingConfig(window=60, bars_per_day=144))
    print(f"  Rolling: sharpe_len={len(roll.sharpe)}, vol_len={len(roll.volatility)}")
    assert roll.beta is not None, "Beta should be computed with benchmark"
    print("  [OK] Rolling computed")

    # 2e: Individual metric functions sanity checks
    eq_arr = np.array([e["equity"] for e in equity_curve])
    rets = equity_to_returns(eq_arr)
    assert abs(cagr(eq_arr, 144)) < 10000, "CAGR should be finite"
    assert abs(sharpe_ratio(rets, 0, 144)) < 100, "Sharpe should be finite"
    assert 0 <= max_drawdown(eq_arr) <= 1, "Max DD should be 0-1"
    assert value_at_risk(rets) >= 0, "VaR should be non-negative"
    k = kelly_criterion(0.6, 150, 80)
    assert -1 < k < 2, "Kelly should be reasonable"
    print("  [OK] Individual metric sanity checks passed")

    # 2f: OLS alpha/beta
    strat_ret = equity_to_returns(eq_arr)
    bh_eq = buy_and_hold_equity(close_prices, 100_000)
    bh_ret = equity_to_returns(bh_eq)
    alpha, beta = ols_alpha_beta(strat_ret, bh_ret)
    print(f"  OLS: alpha={alpha:.6f}, beta={beta:.4f}")
    print("  [OK] OLS alpha/beta computed")

    print()
    print("  >>> TEST 2 PASSED <<<")
    print()


# ────────────────────────────────────────────────────────────────
# Run all tests
# ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    t0 = time.perf_counter()
    test_full_tearsheet()
    test_standalone_analytics()
    elapsed = time.perf_counter() - t0
    print("=" * 60)
    print(f"ALL PHASE 3 TESTS PASSED in {elapsed:.3f}s")
    print("=" * 60)
