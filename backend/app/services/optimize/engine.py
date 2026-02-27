"""
Optimization engine: Bayesian (Optuna) + Genetic (DEAP) hybrid.

Runs backtest trials with different parameter combinations to find optimal
strategy parameters. Supports walk-forward validation.
"""
import copy
import math
import time
import logging
import random
from typing import Optional, Any
from dataclasses import dataclass, field

from app.services.backtest.engine import BacktestEngine, Bar

logger = logging.getLogger(__name__)


@dataclass
class ParamSpec:
    """Single parameter specification for optimization."""
    param_path: str
    param_type: str   # "int", "float", "categorical"
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    step: Optional[float] = None
    choices: Optional[list] = None
    label: str = ""


@dataclass
class TrialRecord:
    """Result from a single optimization trial."""
    trial_number: int
    params: dict
    score: float
    stats: dict


@dataclass
class OptimizationResult:
    """Final optimization result."""
    best_params: dict = field(default_factory=dict)
    best_score: float = 0.0
    history: list[TrialRecord] = field(default_factory=list)
    param_importance: dict = field(default_factory=dict)
    elapsed_seconds: float = 0.0


def _set_nested(obj: dict, path: str, value: Any):
    """Set a value in a nested dict using dot notation.
    e.g. 'indicators.0.params.period' sets obj['indicators'][0]['params']['period']
    """
    keys = path.split(".")
    current = obj
    for k in keys[:-1]:
        if k.isdigit():
            current = current[int(k)]
        else:
            current = current[k]
    last = keys[-1]
    if last.isdigit():
        current[int(last)] = value
    else:
        current[last] = value


def _get_nested(obj: dict, path: str) -> Any:
    """Get a value from a nested dict using dot notation."""
    keys = path.split(".")
    current = obj
    for k in keys:
        if k.isdigit():
            current = current[int(k)]
        else:
            current = current[k]
    return current


class OptimizerEngine:
    """
    Runs optimization over strategy parameters using multiple methods:
    - bayesian: Optuna TPE sampler
    - genetic: Simple evolutionary algorithm (no DEAP dependency)
    - hybrid: Bayesian first half, genetic refinement second half
    """

    def __init__(
        self,
        bars: list[Bar],
        strategy_config: dict,
        param_specs: list[ParamSpec],
        objective: str = "sharpe_ratio",
        n_trials: int = 100,
        method: str = "bayesian",
        initial_balance: float = 10000.0,
        spread_points: float = 0.0,
        commission_per_lot: float = 0.0,
        point_value: float = 1.0,
        walk_forward: bool = False,
        wf_in_sample_pct: float = 70.0,
        progress_callback=None,
    ):
        self.bars = bars
        self.base_config = strategy_config
        self.param_specs = param_specs
        self.objective = objective
        self.n_trials = max(n_trials, 10)
        self.method = method
        self.initial_balance = initial_balance
        self.spread = spread_points
        self.commission = commission_per_lot
        self.point_value = point_value
        self.walk_forward = walk_forward
        self.wf_in_sample_pct = wf_in_sample_pct
        self.progress_callback = progress_callback

        # Split data for walk-forward
        if walk_forward:
            split = int(len(bars) * wf_in_sample_pct / 100)
            self.in_sample_bars = bars[:split]
            self.out_sample_bars = bars[split:]
        else:
            self.in_sample_bars = bars
            self.out_sample_bars = []

        self.history: list[TrialRecord] = []
        self.best_score = -1e18
        self.best_params: dict = {}
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self) -> OptimizationResult:
        t0 = time.time()

        if self.method == "bayesian":
            self._run_bayesian()
        elif self.method == "genetic":
            self._run_genetic()
        elif self.method == "hybrid":
            # Bayesian for first 60%, genetic for last 40%
            bayesian_n = int(self.n_trials * 0.6)
            genetic_n = self.n_trials - bayesian_n
            self._run_bayesian(n_override=bayesian_n)
            if not self._cancelled:
                self._run_genetic(n_override=genetic_n, seed_from_history=True)
        else:
            self._run_bayesian()

        elapsed = time.time() - t0

        # Calculate param importance
        importance = self._calc_param_importance()

        return OptimizationResult(
            best_params=self.best_params,
            best_score=round(self.best_score, 6),
            history=self.history,
            param_importance=importance,
            elapsed_seconds=round(elapsed, 3),
        )

    # ─── Bayesian (Optuna) ───────────────────────────────────

    def _run_bayesian(self, n_override: int | None = None):
        """Run Bayesian optimization using Optuna TPE."""
        try:
            import optuna
            optuna.logging.set_verbosity(optuna.logging.WARNING)
        except ImportError:
            logger.warning("Optuna not installed, falling back to random search")
            self._run_random(n_override or self.n_trials)
            return

        n = n_override or self.n_trials
        start_trial = len(self.history)

        def objective_fn(trial: optuna.Trial) -> float:
            if self._cancelled:
                raise optuna.exceptions.OptunaError("Cancelled")

            params = {}
            for spec in self.param_specs:
                name = spec.label or spec.param_path
                if spec.param_type == "int":
                    val = trial.suggest_int(
                        name,
                        int(spec.min_val or 1),
                        int(spec.max_val or 100),
                        step=int(spec.step or 1),
                    )
                elif spec.param_type == "float":
                    val = trial.suggest_float(
                        name,
                        spec.min_val or 0.0,
                        spec.max_val or 100.0,
                        step=spec.step if spec.step else None,
                    )
                elif spec.param_type == "categorical":
                    val = trial.suggest_categorical(name, spec.choices or [])
                else:
                    continue
                params[spec.param_path] = val

            score, stats = self._evaluate(params)
            self._record_trial(start_trial + trial.number, params, score, stats)
            return score

        study = optuna.create_study(direction="maximize")
        try:
            study.optimize(objective_fn, n_trials=n, show_progress_bar=False)
        except optuna.exceptions.OptunaError:
            pass  # Cancelled

        # Extract importance from Optuna if enough trials
        if len(study.trials) >= 10:
            try:
                imp = optuna.importance.get_param_importances(study)
                for spec in self.param_specs:
                    name = spec.label or spec.param_path
                    if name in imp:
                        spec._importance = imp[name]
            except Exception:
                pass

    # ─── Genetic Algorithm ──────────────────────────────────

    def _run_genetic(self, n_override: int | None = None, seed_from_history: bool = False):
        """Simple evolutionary algorithm — no external dependencies."""
        n = n_override or self.n_trials
        pop_size = min(20, max(8, n // 5))
        generations = max(1, n // pop_size)
        start_trial = len(self.history)

        # Initialize population
        if seed_from_history and self.history:
            # Seed from top performers in history
            sorted_h = sorted(self.history, key=lambda t: t.score, reverse=True)
            population = [t.params for t in sorted_h[:pop_size]]
            # Fill remaining with mutations
            while len(population) < pop_size:
                base = random.choice(population[:max(1, len(population))])
                population.append(self._mutate(base))
        else:
            population = [self._random_params() for _ in range(pop_size)]

        # Evaluate initial population
        fitness = []
        for i, params in enumerate(population):
            if self._cancelled:
                return
            score, stats = self._evaluate(params)
            fitness.append(score)
            self._record_trial(start_trial + i, params, score, stats)

        trial_count = pop_size

        # Evolution loop
        for gen in range(generations):
            if self._cancelled:
                return

            new_pop = []
            new_fit = []

            # Elitism: keep top 2
            sorted_idx = sorted(range(len(fitness)), key=lambda i: fitness[i], reverse=True)
            for idx in sorted_idx[:2]:
                new_pop.append(population[idx])
                new_fit.append(fitness[idx])

            # Fill rest with crossover + mutation
            while len(new_pop) < pop_size:
                if self._cancelled:
                    return

                # Tournament selection
                p1 = self._tournament_select(population, fitness)
                p2 = self._tournament_select(population, fitness)

                # Crossover
                child = self._crossover(p1, p2)

                # Mutation (30% chance)
                if random.random() < 0.3:
                    child = self._mutate(child)

                score, stats = self._evaluate(child)
                self._record_trial(start_trial + trial_count, child, score, stats)
                trial_count += 1

                new_pop.append(child)
                new_fit.append(score)

            population = new_pop
            fitness = new_fit

    def _random_params(self) -> dict:
        params = {}
        for spec in self.param_specs:
            if spec.param_type == "int":
                lo, hi = int(spec.min_val or 1), int(spec.max_val or 100)
                step = int(spec.step or 1)
                val = random.randrange(lo, hi + 1, step)
                params[spec.param_path] = val
            elif spec.param_type == "float":
                lo, hi = spec.min_val or 0.0, spec.max_val or 100.0
                val = random.uniform(lo, hi)
                if spec.step:
                    val = round(val / spec.step) * spec.step
                params[spec.param_path] = round(val, 6)
            elif spec.param_type == "categorical":
                params[spec.param_path] = random.choice(spec.choices or [0])
        return params

    def _mutate(self, params: dict) -> dict:
        child = dict(params)
        # Mutate 1-2 params
        specs_to_mutate = random.sample(
            self.param_specs,
            min(random.randint(1, 2), len(self.param_specs)),
        )
        for spec in specs_to_mutate:
            if spec.param_type == "int":
                lo, hi = int(spec.min_val or 1), int(spec.max_val or 100)
                step = int(spec.step or 1)
                current = child.get(spec.param_path, lo)
                delta = random.choice([-step, step, -2*step, 2*step])
                val = max(lo, min(hi, int(current) + delta))
                child[spec.param_path] = val
            elif spec.param_type == "float":
                lo, hi = spec.min_val or 0.0, spec.max_val or 100.0
                current = child.get(spec.param_path, lo)
                range_size = hi - lo
                delta = random.gauss(0, range_size * 0.15)
                val = max(lo, min(hi, float(current) + delta))
                if spec.step:
                    val = round(val / spec.step) * spec.step
                child[spec.param_path] = round(val, 6)
            elif spec.param_type == "categorical":
                child[spec.param_path] = random.choice(spec.choices or [0])
        return child

    def _crossover(self, p1: dict, p2: dict) -> dict:
        child = {}
        for spec in self.param_specs:
            key = spec.param_path
            if random.random() < 0.5:
                child[key] = p1.get(key, p2.get(key))
            else:
                child[key] = p2.get(key, p1.get(key))
        return child

    def _tournament_select(self, pop: list[dict], fitness: list[float], k: int = 3) -> dict:
        indices = random.sample(range(len(pop)), min(k, len(pop)))
        best = max(indices, key=lambda i: fitness[i])
        return pop[best]

    # ─── Random Search (fallback) ───────────────────────────

    def _run_random(self, n: int):
        for i in range(n):
            if self._cancelled:
                return
            params = self._random_params()
            score, stats = self._evaluate(params)
            self._record_trial(i, params, score, stats)

    # ─── Core Evaluation ────────────────────────────────────

    def _evaluate(self, params: dict) -> tuple[float, dict]:
        """Run backtest with given params and return (score, stats)."""
        config = copy.deepcopy(self.base_config)

        # Apply params to config
        for path, value in params.items():
            try:
                _set_nested(config, path, value)
            except (KeyError, IndexError, TypeError) as e:
                logger.debug(f"Could not set param {path}={value}: {e}")

        # Run backtest on in-sample data
        engine = BacktestEngine(
            bars=self.in_sample_bars,
            strategy_config=config,
            initial_balance=self.initial_balance,
            spread_points=self.spread,
            commission_per_lot=self.commission,
            point_value=self.point_value,
        )
        result = engine.run()

        # Extract score based on objective
        score = self._extract_score(result)

        stats = {
            "total_trades": result.total_trades,
            "win_rate": round(result.win_rate, 2),
            "net_profit": round(result.net_profit, 2),
            "profit_factor": round(result.profit_factor, 4),
            "sharpe_ratio": round(result.sharpe_ratio, 4),
            "max_drawdown_pct": round(result.max_drawdown_pct, 2),
            "expectancy": round(result.expectancy, 2),
        }

        # If walk-forward, also run OOS and penalize divergence
        if self.walk_forward and self.out_sample_bars:
            oos_engine = BacktestEngine(
                bars=self.out_sample_bars,
                strategy_config=config,
                initial_balance=self.initial_balance,
                spread_points=self.spread,
                commission_per_lot=self.commission,
                point_value=self.point_value,
            )
            oos_result = oos_engine.run()
            oos_score = self._extract_score(oos_result)

            stats["oos_net_profit"] = round(oos_result.net_profit, 2)
            stats["oos_sharpe"] = round(oos_result.sharpe_ratio, 4)
            stats["oos_win_rate"] = round(oos_result.win_rate, 2)

            # Combine: 40% in-sample + 60% out-of-sample
            score = 0.4 * score + 0.6 * oos_score

        return score, stats

    def _extract_score(self, result) -> float:
        """Extract the optimization target from backtest result."""
        if result.total_trades < 5:
            return -1e6  # Penalize strategies with too few trades

        if self.objective == "sharpe_ratio":
            return result.sharpe_ratio
        elif self.objective == "net_profit":
            return result.net_profit
        elif self.objective == "profit_factor":
            return result.profit_factor if result.profit_factor < 100 else 0
        elif self.objective == "win_rate":
            return result.win_rate
        else:
            return result.sharpe_ratio

    # ─── Helpers ────────────────────────────────────────────

    def _record_trial(self, num: int, params: dict, score: float, stats: dict):
        rec = TrialRecord(
            trial_number=num,
            params=params,
            score=round(score, 6),
            stats=stats,
        )
        self.history.append(rec)

        if score > self.best_score:
            self.best_score = score
            self.best_params = dict(params)

        if self.progress_callback:
            self.progress_callback(len(self.history), self.n_trials, self.best_score, self.best_params)

    def _calc_param_importance(self) -> dict:
        """Estimate parameter importance via correlation with score."""
        if len(self.history) < 10:
            return {}

        importance = {}
        scores = [t.score for t in self.history]
        mean_score = sum(scores) / len(scores)
        var_score = sum((s - mean_score) ** 2 for s in scores)
        if var_score < 1e-10:
            return {}

        for spec in self.param_specs:
            path = spec.param_path
            if spec.param_type == "categorical":
                importance[path] = 0.0
                continue

            values = []
            valid_scores = []
            for t in self.history:
                v = t.params.get(path)
                if v is not None:
                    try:
                        values.append(float(v))
                        valid_scores.append(t.score)
                    except (ValueError, TypeError):
                        continue

            if len(values) < 5:
                importance[path] = 0.0
                continue

            mean_v = sum(values) / len(values)
            var_v = sum((v - mean_v) ** 2 for v in values)
            if var_v < 1e-10:
                importance[path] = 0.0
                continue

            mean_s = sum(valid_scores) / len(valid_scores)
            cov = sum(
                (values[i] - mean_v) * (valid_scores[i] - mean_s)
                for i in range(len(values))
            )
            corr = cov / math.sqrt(var_v * sum((s - mean_s) ** 2 for s in valid_scores))
            importance[path] = round(abs(corr), 4)

        # Normalize to sum = 1
        total = sum(importance.values())
        if total > 0:
            importance = {k: round(v / total, 4) for k, v in importance.items()}

        return importance
