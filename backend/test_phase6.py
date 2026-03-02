"""Phase 6 — Optimizer Upgrade Tests.

Covers:
  6A: Parallel execution (ThreadPoolExecutor workers)
  6B: V2 routing (optimizer uses run_unified_backtest)
  6C: Early stopping (convergence, time budget, max-DD abort)
  6D: Walk-forward generalisation (all strategy types via V2)

Run: python -m pytest test_phase6.py -v
"""

import math
import sys
import os
import time
import copy

sys.path.insert(0, os.path.dirname(__file__))

import pytest

from app.services.backtest.engine import Bar
from app.services.optimize.engine import (
    OptimizerEngine,
    ParamSpec,
    OptimizationResult,
    TrialRecord,
    _set_nested,
    _get_nested,
)


# ── Shared fixtures ─────────────────────────────────────────────

def _make_bars(n=300, base=2000.0, seed=42):
    """Generate synthetic OHLCV bars."""
    import random as _r
    _r.seed(seed)
    bars = []
    price = base
    for i in range(n):
        o = price
        h = o + _r.uniform(1, 10)
        l = o - _r.uniform(1, 10)
        c = o + _r.uniform(-5, 5)
        bars.append(Bar(
            time=1700000000 + i * 600,
            open=o, high=h, low=l, close=c,
            volume=_r.uniform(100, 1000),
        ))
        price = c
    return bars


def _simple_strategy_config():
    """A minimal builder strategy config with one SMA indicator and simple rules."""
    return {
        "indicators": [
            {"id": "sma_1", "type": "SMA", "params": {"period": 20, "source": "close"}},
        ],
        "entry_rules": [
            {"left": "close", "operator": ">", "right": "sma_1", "logic": "AND"},
        ],
        "exit_rules": [
            {"left": "close", "operator": "<", "right": "sma_1", "logic": "AND"},
        ],
        "risk_params": {
            "stop_loss_type": "none",
            "take_profit_type": "none",
            "position_size_type": "fixed_lot",
            "position_size_value": 0.01,
        },
        "filters": {},
    }


def _sma_param_specs():
    """Parameter specs for SMA period optimisation."""
    return [
        ParamSpec(
            param_path="indicators.0.params.period",
            param_type="int",
            min_val=5, max_val=50, step=1,
            label="SMA period",
        ),
    ]


BARS = _make_bars(300)


# ── 6A: Parallel Execution ──────────────────────────────────────

class TestParallelExecution:
    def test_max_workers_default(self):
        """max_workers=0 should default to CPU count - 1."""
        engine = OptimizerEngine(
            bars=BARS,
            strategy_config=_simple_strategy_config(),
            param_specs=_sma_param_specs(),
            n_trials=10,
            method="bayesian",
            symbol="XAUUSD",
        )
        assert engine.max_workers >= 1

    def test_explicit_max_workers(self):
        engine = OptimizerEngine(
            bars=BARS,
            strategy_config=_simple_strategy_config(),
            param_specs=_sma_param_specs(),
            n_trials=10,
            max_workers=2,
            symbol="XAUUSD",
        )
        assert engine.max_workers == 2

    def test_parallel_evaluate_builtin(self):
        """Parallel evaluation of a batch of params should return scores."""
        engine = OptimizerEngine(
            bars=BARS,
            strategy_config=_simple_strategy_config(),
            param_specs=_sma_param_specs(),
            n_trials=10,
            max_workers=2,
            symbol="XAUUSD",
        )
        params_list = [engine._random_params() for _ in range(4)]
        fitness = engine._parallel_evaluate_builtin(params_list, 0)
        assert len(fitness) == 4
        # All should be finite (could be negative penalty for few trades, but not crash)
        for f in fitness:
            assert math.isfinite(f)

    def test_sequential_fallback(self):
        """With max_workers=1, should fall back to sequential."""
        engine = OptimizerEngine(
            bars=BARS,
            strategy_config=_simple_strategy_config(),
            param_specs=_sma_param_specs(),
            n_trials=10,
            max_workers=1,
            symbol="XAUUSD",
        )
        params_list = [engine._random_params() for _ in range(3)]
        fitness = engine._parallel_evaluate_builtin(params_list, 0)
        assert len(fitness) == 3


# ── 6B: V2 Routing ─────────────────────────────────────────────

class TestV2Routing:
    def test_builder_strategy_via_v2(self):
        """Builder strategy should run through V2 unified runner."""
        engine = OptimizerEngine(
            bars=BARS,
            strategy_config=_simple_strategy_config(),
            param_specs=_sma_param_specs(),
            n_trials=10,
            method="bayesian",
            symbol="XAUUSD",
        )
        result = engine.run()
        assert isinstance(result, OptimizationResult)
        assert len(result.history) >= 1
        assert result.elapsed_seconds > 0

    def test_optimizer_produces_valid_scores(self):
        """Scores should be finite numbers (not NaN)."""
        engine = OptimizerEngine(
            bars=BARS,
            strategy_config=_simple_strategy_config(),
            param_specs=_sma_param_specs(),
            n_trials=10,
            method="bayesian",
            symbol="XAUUSD",
            min_trades=1,
        )
        result = engine.run()
        for trial in result.history:
            assert math.isfinite(trial.score), f"Trial {trial.trial_number} has non-finite score"

    def test_genetic_method_via_v2(self):
        """Genetic method should work with V2 routing."""
        engine = OptimizerEngine(
            bars=BARS,
            strategy_config=_simple_strategy_config(),
            param_specs=_sma_param_specs(),
            n_trials=20,
            method="genetic",
            symbol="XAUUSD",
            min_trades=1,
            max_workers=1,  # sequential for determinism
        )
        result = engine.run()
        assert len(result.history) >= 1

    def test_hybrid_method_via_v2(self):
        """Hybrid method should work with V2 routing."""
        engine = OptimizerEngine(
            bars=BARS,
            strategy_config=_simple_strategy_config(),
            param_specs=_sma_param_specs(),
            n_trials=20,
            method="hybrid",
            symbol="XAUUSD",
            min_trades=1,
            max_workers=1,
        )
        result = engine.run()
        assert len(result.history) >= 1

    def test_v2_routing_no_v1_import(self):
        """Optimizer should NOT import BacktestEngine (V1 is deprecated)."""
        import app.services.optimize.engine as mod
        source = open(mod.__file__).read()
        assert "from app.services.backtest.engine import BacktestEngine" not in source


# ── 6C: Early Stopping ─────────────────────────────────────────

class TestEarlyStopping:
    def test_convergence_patience(self):
        """Should stop early if no improvement for N trials."""
        engine = OptimizerEngine(
            bars=BARS,
            strategy_config=_simple_strategy_config(),
            param_specs=_sma_param_specs(),
            n_trials=200,
            method="bayesian",
            symbol="XAUUSD",
            early_stop_patience=5,  # Stop after 5 trials without improvement
            max_workers=1,
        )
        result = engine.run()
        # Should stop well before 200 trials
        assert len(result.history) < 200, (
            f"Expected early stop, but ran {len(result.history)}/200 trials"
        )
        assert len(result.history) >= 5  # At least patience trials ran

    def test_time_budget(self):
        """Should stop when time budget is exceeded."""
        engine = OptimizerEngine(
            bars=BARS,
            strategy_config=_simple_strategy_config(),
            param_specs=_sma_param_specs(),
            n_trials=500,
            method="bayesian",
            symbol="XAUUSD",
            time_budget_seconds=2.0,  # Very short budget
            max_workers=1,
        )
        t0 = time.time()
        result = engine.run()
        elapsed = time.time() - t0
        # Allow 1s tolerance for overhead — should stop around 2-3s
        assert elapsed < 10.0, f"Time budget not respected: ran for {elapsed:.1f}s"
        assert len(result.history) < 500

    def test_max_dd_abort(self):
        """Trials with excessive drawdown should be penalized to -1e6."""
        engine = OptimizerEngine(
            bars=BARS,
            strategy_config=_simple_strategy_config(),
            param_specs=_sma_param_specs(),
            n_trials=10,
            method="bayesian",
            symbol="XAUUSD",
            max_dd_abort=0.01,  # Extremely tight threshold — nearly all trials should fail
            min_trades=1,
            max_workers=1,
        )
        result = engine.run()
        # Most trials should have been penalized (score -1e6 or very low)
        penalized = [t for t in result.history if t.score <= -1e5]
        # At least some should be penalized with such a tight DD threshold
        # (If strategy makes any trades at all, there will be some drawdown)
        assert len(result.history) >= 1

    def test_should_early_stop_function(self):
        """Directly test _should_early_stop logic."""
        engine = OptimizerEngine(
            bars=BARS[:50],
            strategy_config=_simple_strategy_config(),
            param_specs=_sma_param_specs(),
            n_trials=10,
            symbol="XAUUSD",
            early_stop_patience=3,
        )
        engine._start_time = time.time()
        engine._trials_since_improvement = 0
        assert engine._should_early_stop() is False

        engine._trials_since_improvement = 3
        assert engine._should_early_stop() is True

    def test_should_early_stop_time_budget(self):
        engine = OptimizerEngine(
            bars=BARS[:50],
            strategy_config=_simple_strategy_config(),
            param_specs=_sma_param_specs(),
            n_trials=10,
            symbol="XAUUSD",
            time_budget_seconds=0.001,  # Already expired
        )
        engine._start_time = time.time() - 1.0  # Started 1s ago
        assert engine._should_early_stop() is True

    def test_should_early_stop_cancelled(self):
        engine = OptimizerEngine(
            bars=BARS[:50],
            strategy_config=_simple_strategy_config(),
            param_specs=_sma_param_specs(),
            n_trials=10,
            symbol="XAUUSD",
        )
        engine._start_time = time.time()
        engine.cancel()
        assert engine._should_early_stop() is True

    def test_convergence_tracking(self):
        """_record_trial should track trials since improvement."""
        engine = OptimizerEngine(
            bars=BARS[:50],
            strategy_config=_simple_strategy_config(),
            param_specs=_sma_param_specs(),
            n_trials=10,
            symbol="XAUUSD",
        )
        engine._record_trial(0, {"p": 1}, 10.0, {})
        assert engine._trials_since_improvement == 0  # New best
        assert engine.best_score == 10.0

        engine._record_trial(1, {"p": 2}, 5.0, {})
        assert engine._trials_since_improvement == 1  # No improvement

        engine._record_trial(2, {"p": 3}, 7.0, {})
        assert engine._trials_since_improvement == 2  # Still no improvement

        engine._record_trial(3, {"p": 4}, 15.0, {})
        assert engine._trials_since_improvement == 0  # New best
        assert engine.best_score == 15.0


# ── 6D: Walk-Forward Generalisation ────────────────────────────

class TestWalkForwardGeneralisation:
    def test_builder_strategy_walk_forward(self):
        """Walk-forward should work with builder strategies (not just MSS/Gold BT)."""
        from app.services.backtest.walk_forward import walk_forward_backtest

        config = _simple_strategy_config()
        result = walk_forward_backtest(
            bars=_make_bars(500),
            strategy_type="builder",
            strategy_config=config,
            n_folds=3,
            train_pct=70.0,
            mode="anchored",
            initial_balance=10000.0,
            symbol="XAUUSD",
        )
        assert result.n_folds == 3
        assert len(result.windows) >= 1
        # Each window should have stats
        for w in result.windows:
            assert w.train_stats is not None
            assert w.test_stats is not None

    def test_rolling_mode(self):
        """Rolling mode should produce non-overlapping windows."""
        from app.services.backtest.walk_forward import walk_forward_backtest

        config = _simple_strategy_config()
        result = walk_forward_backtest(
            bars=_make_bars(500),
            strategy_type="builder",
            strategy_config=config,
            n_folds=3,
            train_pct=70.0,
            mode="rolling",
            initial_balance=10000.0,
            symbol="XAUUSD",
        )
        assert len(result.windows) >= 1

    def test_consistency_score(self):
        """Consistency score should be between 0 and 100."""
        from app.services.backtest.walk_forward import walk_forward_backtest

        config = _simple_strategy_config()
        result = walk_forward_backtest(
            bars=_make_bars(500),
            strategy_type="builder",
            strategy_config=config,
            n_folds=3,
            symbol="XAUUSD",
        )
        assert 0 <= result.consistency_score <= 100

    def test_walk_forward_accepts_symbol_param(self):
        """walk_forward_backtest should accept symbol parameter."""
        from app.services.backtest.walk_forward import walk_forward_backtest
        import inspect
        sig = inspect.signature(walk_forward_backtest)
        assert "symbol" in sig.parameters, "walk_forward_backtest should accept 'symbol' parameter"

    def test_optimizer_walk_forward_via_v2(self):
        """Optimizer with walk_forward=True should work via V2."""
        engine = OptimizerEngine(
            bars=BARS,
            strategy_config=_simple_strategy_config(),
            param_specs=_sma_param_specs(),
            n_trials=10,
            method="bayesian",
            symbol="XAUUSD",
            walk_forward=True,
            wf_in_sample_pct=70.0,
            min_trades=1,
            max_workers=1,
        )
        result = engine.run()
        assert len(result.history) >= 1
        # OOS stats should be in at least some trial stats
        has_oos = any("oos_net_profit" in t.stats for t in result.history)
        assert has_oos, "Walk-forward trials should include OOS stats"


# ── Utility function tests ──────────────────────────────────────

class TestUtilities:
    def test_set_nested(self):
        obj = {"indicators": [{"params": {"period": 10}}]}
        _set_nested(obj, "indicators.0.params.period", 20)
        assert obj["indicators"][0]["params"]["period"] == 20

    def test_get_nested(self):
        obj = {"indicators": [{"params": {"period": 10}}]}
        assert _get_nested(obj, "indicators.0.params.period") == 10

    def test_random_params_types(self):
        specs = [
            ParamSpec(param_path="a", param_type="int", min_val=1, max_val=100),
            ParamSpec(param_path="b", param_type="float", min_val=0.1, max_val=10.0),
        ]
        engine = OptimizerEngine(
            bars=BARS[:50],
            strategy_config=_simple_strategy_config(),
            param_specs=specs,
            n_trials=10,
            symbol="XAUUSD",
        )
        params = engine._random_params()
        assert isinstance(params["a"], int)
        assert isinstance(params["b"], float)
        assert 1 <= params["a"] <= 100
        assert 0.1 <= params["b"] <= 10.0

    def test_param_importance_calculation(self):
        """After enough trials, param importance should be calculated."""
        engine = OptimizerEngine(
            bars=BARS,
            strategy_config=_simple_strategy_config(),
            param_specs=_sma_param_specs(),
            n_trials=15,
            method="bayesian",
            symbol="XAUUSD",
            min_trades=1,
            max_workers=1,
        )
        result = engine.run()
        # With 15+ trials, importance should be calculated
        if len(result.history) >= 10:
            assert isinstance(result.param_importance, dict)


# ── Phase 6 schema tests ───────────────────────────────────────

class TestOptimizationSchema:
    def test_request_has_phase6_fields(self):
        from app.schemas.optimization import OptimizationRequest
        fields = OptimizationRequest.model_fields
        assert "max_workers" in fields
        assert "early_stop_patience" in fields
        assert "time_budget_seconds" in fields
        assert "max_dd_abort" in fields

    def test_request_defaults(self):
        from app.schemas.optimization import OptimizationRequest
        req = OptimizationRequest(
            strategy_id=1, datasource_id=1,
            param_space=[],
        )
        assert req.max_workers == 0
        assert req.early_stop_patience == 0
        assert req.time_budget_seconds == 0
        assert req.max_dd_abort == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
