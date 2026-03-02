"""
Phase 4 (Validation) Smoke Test — Look-ahead detection + Robustness scoring
Run with:  python test_phase4.py
"""
import sys, os, time, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from app.services.backtest.v2.engine.events import BarEvent, EventType
from app.services.backtest.v2.engine.data_handler import DataHandler
from app.services.backtest.v2.engine.strategy_base import StrategyBase
from app.services.backtest.v2.engine.runner import Runner, RunConfig

# ────────────────────────────────────────────────────────────────
# Clean SMA crossover (no look-ahead bias)
# ────────────────────────────────────────────────────────────────
class CleanSMA(StrategyBase):
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

        if fast_ma > slow_ma and not has_long:
            self.ctx.buy_market(sym, 1.0)
        elif fast_ma < slow_ma and has_long:
            self.ctx.close_position(sym)


# ────────────────────────────────────────────────────────────────
# Cheating strategy (uses future data = look-ahead bias)
# ────────────────────────────────────────────────────────────────
class CheaterStrategy(StrategyBase):
    """Peeks at a future bar to decide signal — should be caught."""
    def on_init(self):
        pass

    def on_bar(self, bar):
        dh = self.ctx._data_handler
        sym = bar.symbol
        idx = bar.bar_index
        # Try to read 5 bars ahead
        future = dh.get_value(sym, "price.close", idx + 5)
        if future is None:
            return
        current = bar.close
        pos = self.ctx._portfolio.position_book.positions.get(sym)
        has_pos = pos and not pos.is_flat

        if future > current * 1.001 and not has_pos:
            self.ctx.buy_market(sym, 1.0)
        elif future < current * 0.999 and has_pos:
            self.ctx.close_position(sym)


# ────────────────────────────────────────────────────────────────
# Synthetic bar data
# ────────────────────────────────────────────────────────────────
def make_bars(n=1000, start_price=2000.0, seed=42):
    rng = random.Random(seed)
    bars = []
    price = start_price
    for i in range(n):
        o = price
        c = o + rng.gauss(0, 5)
        h = max(o, c) + abs(rng.gauss(0, 2))
        l = min(o, c) - abs(rng.gauss(0, 2))
        ts = 1700000000 + i * 600
        bars.append({
            "time": ts, "open": round(o, 2), "high": round(h, 2),
            "low": round(l, 2), "close": round(c, 2),
            "volume": rng.randint(100, 1000),
        })
        price = c
    return bars


# ════════════════════════════════════════════════════════════════
# TEST 1: Look-Ahead Detection — Clean Strategy
# ════════════════════════════════════════════════════════════════
def test_lookahead_clean():
    print("=" * 60)
    print("TEST 1: Look-Ahead Detection — Clean SMA")
    print("=" * 60)

    from app.services.backtest.v2.validation.lookahead import (
        detect_look_ahead, LookAheadConfig,
    )

    bars = make_bars(500)
    config = LookAheadConfig(n_samples=20, seed=42)
    run_config = RunConfig(initial_cash=100_000, spread=0.3, bars_per_day=144)

    result = detect_look_ahead(
        bars_dict={"XAUUSD": bars},
        strategy_factory=lambda: CleanSMA(params={}),
        run_config=run_config,
        config=config,
    )

    print(f"  Bars tested: {result.n_bars_tested}/{result.n_bars_total}")
    print(f"  Biased: {result.n_biased}")
    print(f"  Bias score: {result.bias_score}%")
    print(f"  Clean: {result.is_clean}")
    print(f"  Time: {result.elapsed_seconds:.3f}s")
    print(f"  Summary: {result.summary}")

    assert result.is_clean, f"Clean SMA should have no look-ahead bias! Got {result.n_biased} biased bars"
    assert result.bias_score == 0.0
    print()
    print("  >>> TEST 1 PASSED <<<")
    print()


# ════════════════════════════════════════════════════════════════
# TEST 2: Look-Ahead Detection — Cheating Strategy
# ════════════════════════════════════════════════════════════════
def test_lookahead_cheater():
    print("=" * 60)
    print("TEST 2: Look-Ahead Detection — Cheater Strategy")
    print("=" * 60)

    from app.services.backtest.v2.validation.lookahead import (
        detect_look_ahead, LookAheadConfig,
    )

    bars = make_bars(500)
    config = LookAheadConfig(n_samples=20, seed=42)
    run_config = RunConfig(initial_cash=100_000, spread=0.3, bars_per_day=144)

    result = detect_look_ahead(
        bars_dict={"XAUUSD": bars},
        strategy_factory=lambda: CheaterStrategy(params={}),
        run_config=run_config,
        config=config,
    )

    print(f"  Bars tested: {result.n_bars_tested}/{result.n_bars_total}")
    print(f"  Biased: {result.n_biased}")
    print(f"  Bias score: {result.bias_score}%")
    print(f"  Clean: {result.is_clean}")
    print(f"  Time: {result.elapsed_seconds:.3f}s")
    print(f"  Summary: {result.summary}")

    assert not result.is_clean, "Cheater strategy should have look-ahead bias!"
    assert result.n_biased > 0, "Should detect at least some biased bars"
    print()
    print("  >>> TEST 2 PASSED <<<")
    print()


# ════════════════════════════════════════════════════════════════
# TEST 3: Robustness Scoring
# ════════════════════════════════════════════════════════════════
def test_robustness():
    print("=" * 60)
    print("TEST 3: Walk-Forward Robustness Scoring")
    print("=" * 60)

    from app.services.backtest.v2.validation.robustness import (
        score_robustness, RobustnessConfig,
    )

    bars = make_bars(1000)
    config = RobustnessConfig(n_folds=4, train_pct=70.0, mode="anchored")
    run_config = RunConfig(initial_cash=100_000, spread=0.3, bars_per_day=144)

    result = score_robustness(
        bars_dict={"XAUUSD": bars},
        strategy_factory=lambda: CleanSMA(params={}),
        run_config=run_config,
        config=config,
    )

    print(f"  Score: {result.score}/100 (Grade {result.grade})")
    print(f"  Folds: {result.n_folds}")
    print(f"  Component scores:")
    print(f"    Profitability:     {result.profitability_score}")
    print(f"    Sharpe consistency: {result.sharpe_consistency_score}")
    print(f"    CAGR stability:    {result.cagr_stability_score}")
    print(f"    DD resilience:     {result.drawdown_resilience_score}")
    print(f"    Trade count:       {result.trade_count_score}")
    print(f"  OOS stats:")
    print(f"    Total trades: {result.oos_total_trades}")
    print(f"    Net profit: {result.oos_net_profit}")
    print(f"    Sharpe: {result.oos_sharpe}")
    print(f"    Max DD: {result.oos_max_dd_pct}%")
    print(f"  Overfit detection:")
    print(f"    IS vs OOS gap: {result.is_vs_oos_gap}")
    print(f"    Overfit probability: {result.overfit_probability}")
    print(f"    Likely overfit: {result.is_likely_overfit}")
    print(f"  Time: {result.elapsed_seconds:.3f}s")
    print(f"  Summary: {result.summary}")

    # Basic assertions
    assert 0 <= result.score <= 100
    assert result.grade in ("A", "B", "C", "D", "F")
    assert result.n_folds == 4
    assert len(result.windows) == 4
    assert result.oos_total_trades >= 0
    assert len(result.oos_equity_curve) > 0

    # Per-window detail
    for w in result.windows:
        print(f"    Fold {w.fold}: IS profit={w.is_net_profit:.2f} OOS profit={w.oos_net_profit:.2f} trades={w.oos_total_trades}")
        assert w.train_bars > 0
        assert w.test_bars > 0

    print()
    print("  >>> TEST 3 PASSED <<<")
    print()


# ════════════════════════════════════════════════════════════════
# TEST 4: Robustness with rolling mode
# ════════════════════════════════════════════════════════════════
def test_robustness_rolling():
    print("=" * 60)
    print("TEST 4: Robustness — Rolling Mode")
    print("=" * 60)

    from app.services.backtest.v2.validation.robustness import (
        score_robustness, RobustnessConfig,
    )

    bars = make_bars(1000)
    config = RobustnessConfig(n_folds=3, train_pct=70.0, mode="rolling")
    run_config = RunConfig(initial_cash=100_000, spread=0.3, bars_per_day=144)

    result = score_robustness(
        bars_dict={"XAUUSD": bars},
        strategy_factory=lambda: CleanSMA(params={}),
        run_config=run_config,
        config=config,
    )

    print(f"  Score: {result.score}/100 (Grade {result.grade})")
    print(f"  Folds: {result.n_folds}")
    assert 0 <= result.score <= 100
    assert result.n_folds > 0
    print(f"  Time: {result.elapsed_seconds:.3f}s")
    print()
    print("  >>> TEST 4 PASSED <<<")
    print()


# ────────────────────────────────────────────────────────────────
# Run all tests
# ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    t0 = time.perf_counter()
    test_lookahead_clean()
    test_lookahead_cheater()
    test_robustness()
    test_robustness_rolling()
    elapsed = time.perf_counter() - t0
    print("=" * 60)
    print(f"ALL PHASE 4 (VALIDATION) TESTS PASSED in {elapsed:.3f}s")
    print("=" * 60)
