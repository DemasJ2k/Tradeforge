"""
Optimization engine: Bayesian (Optuna) + Genetic (DEAP) hybrid.

Runs backtest trials with different parameter combinations to find optimal
strategy parameters. Supports walk-forward validation.

Phase 6 upgrades:
  6A — Parallel evaluation via ThreadPoolExecutor (max_workers)
  6B — All backtests routed through V2 unified runner
  6C — Early stopping (convergence, time budget, max-DD abort)
"""
import copy
import math
import os
import time
import logging
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Any
from dataclasses import dataclass, field

from app.services.backtest.engine import Bar  # Bar dataclass still used for data transport

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
        secondary_objective: Optional[str] = None,
        secondary_threshold: Optional[float] = None,
        secondary_operator: Optional[str] = None,
        min_trades: int = 30,
        frozen_params: Optional[dict] = None,
        # Phase 6A: parallel execution
        max_workers: int = 0,
        # Phase 6B: V2 routing
        symbol: str = "UNKNOWN",
        # Phase 6C: early stopping
        early_stop_patience: int = 0,
        time_budget_seconds: float = 0,
        max_dd_abort: float = 0,
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
        self.secondary_objective = secondary_objective
        self.secondary_threshold = secondary_threshold
        self.secondary_operator = secondary_operator or ">="
        self.min_trades = max(1, int(min_trades))
        self.frozen_params = frozen_params or {}

        # Phase 6A: parallel execution
        cpu_count = os.cpu_count() or 4
        self.max_workers = max_workers if max_workers > 0 else max(1, cpu_count - 1)

        # Phase 6B: symbol for V2 routing
        self.symbol = symbol

        # Phase 6C: early stopping
        self.early_stop_patience = early_stop_patience  # 0 = disabled
        self.time_budget_seconds = time_budget_seconds   # 0 = unlimited
        self.max_dd_abort = max_dd_abort                 # 0 = disabled (% value)
        self._start_time: float = 0.0
        self._trials_since_improvement: int = 0

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

    def _should_early_stop(self) -> bool:
        """Phase 6C: Check convergence + time budget."""
        if self._cancelled:
            return True
        if self.early_stop_patience > 0 and self._trials_since_improvement >= self.early_stop_patience:
            logger.info("Early stop: %d trials without improvement", self._trials_since_improvement)
            return True
        if self.time_budget_seconds > 0 and (time.time() - self._start_time) >= self.time_budget_seconds:
            logger.info("Early stop: time budget %.0fs exceeded", self.time_budget_seconds)
            return True
        return False

    def run(self) -> OptimizationResult:
        self._start_time = time.time()

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

        elapsed = time.time() - self._start_time

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
            if self._cancelled or self._should_early_stop():
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

    # ─── Genetic Algorithm (DEAP) ───────────────────────────

    def _run_genetic(self, n_override: int | None = None, seed_from_history: bool = False):
        """Evolutionary algorithm using DEAP. Falls back to built-in GA if DEAP unavailable."""
        try:
            from deap import base, creator, tools
        except ImportError:
            logger.warning("DEAP not installed, using built-in GA. Run: pip install deap")
            self._run_genetic_builtin(n_override, seed_from_history)
            return

        n = n_override or self.n_trials
        pop_size = min(20, max(8, n // 5))
        generations = max(1, n // pop_size)
        start_trial = len(self.history)
        trial_count = [start_trial]
        param_specs = self.param_specs

        # Register DEAP types (idempotent — safe to call multiple times)
        if not hasattr(creator, "TFFitnessMax"):
            creator.create("TFFitnessMax", base.Fitness, weights=(1.0,))
        if not hasattr(creator, "TFIndividual"):
            creator.create("TFIndividual", list, fitness=creator.TFFitnessMax)

        def _ind_to_params(ind: list) -> dict:
            """Decode float genome into typed strategy params."""
            params = {}
            for i, spec in enumerate(param_specs):
                val = ind[i]
                if spec.param_type == "int":
                    lo, hi = int(spec.min_val or 1), int(spec.max_val or 100)
                    step = int(spec.step or 1)
                    v = max(lo, min(hi, int(round(val))))
                    v = lo + round((v - lo) / step) * step
                    params[spec.param_path] = max(lo, min(hi, v))
                elif spec.param_type == "float":
                    lo, hi = spec.min_val or 0.0, spec.max_val or 100.0
                    v = max(lo, min(hi, float(val)))
                    if spec.step:
                        v = round(v / spec.step) * spec.step
                    params[spec.param_path] = round(v, 6)
                elif spec.param_type == "categorical":
                    choices = spec.choices or [0]
                    idx = max(0, min(len(choices) - 1, int(round(val))))
                    params[spec.param_path] = choices[idx]
            return params

        def _params_to_genome(params: dict) -> list:
            """Encode typed params to float genome for DEAP individual."""
            genome = []
            for spec in param_specs:
                val = params.get(spec.param_path)
                if val is None:
                    lo = spec.min_val or 0.0
                    hi = spec.max_val or 100.0
                    genome.append(float((lo + hi) / 2))
                elif spec.param_type == "categorical":
                    choices = spec.choices or [0]
                    try:
                        genome.append(float(choices.index(val)))
                    except ValueError:
                        genome.append(0.0)
                else:
                    genome.append(float(val))
            return genome

        def _make_gene(spec: ParamSpec) -> float:
            if spec.param_type == "int":
                lo, hi = int(spec.min_val or 1), int(spec.max_val or 100)
                return float(random.randint(lo, hi))
            elif spec.param_type == "float":
                lo, hi = spec.min_val or 0.0, spec.max_val or 100.0
                return random.uniform(lo, hi)
            else:
                choices = spec.choices or [0]
                return float(random.randint(0, len(choices) - 1))

        def _evaluate_ind(individual: list):
            if self._cancelled or self._should_early_stop():
                return (-1e18,)
            params = _ind_to_params(individual)
            score, stats = self._evaluate(params)
            self._record_trial(trial_count[0], params, score, stats)
            trial_count[0] += 1
            return (score,)

        def _clamp(individual: list):
            """Clamp individual genes to valid ranges after mutation."""
            for i, spec in enumerate(param_specs):
                if spec.param_type in ("int", "float"):
                    lo = float(spec.min_val or 0)
                    hi = float(spec.max_val or 100)
                    individual[i] = max(lo, min(hi, individual[i]))
                elif spec.param_type == "categorical":
                    choices = spec.choices or [0]
                    individual[i] = max(0.0, min(float(len(choices) - 1), individual[i]))
            return individual

        toolbox = base.Toolbox()
        toolbox.register("individual", lambda: creator.TFIndividual(
            [_make_gene(s) for s in param_specs]
        ))
        toolbox.register("population", tools.initRepeat, list, toolbox.individual)
        toolbox.register("evaluate", _evaluate_ind)
        toolbox.register("mate", tools.cxUniform, indpb=0.5)
        toolbox.register("mutate", tools.mutGaussian, mu=0, sigma=0.25, indpb=0.4)
        toolbox.register("select", tools.selTournament, tournsize=3)

        # Initialise population — seed from best history when available
        if seed_from_history and self.history:
            sorted_h = sorted(self.history, key=lambda t: t.score, reverse=True)
            pop: list = [creator.TFIndividual(_params_to_genome(t.params)) for t in sorted_h[:pop_size]]
            while len(pop) < pop_size:
                pop.append(toolbox.individual())
        else:
            pop = toolbox.population(n=pop_size)

        # Evaluate initial generation — parallel (Phase 6A)
        self._parallel_evaluate_deap(pop, toolbox)

        # Evolution loop
        hof = tools.HallOfFame(2)
        for _gen in range(generations):
            if self._cancelled or self._should_early_stop():
                return

            offspring = toolbox.select(pop, len(pop))
            offspring = list(map(toolbox.clone, offspring))

            # Crossover
            for c1, c2 in zip(offspring[::2], offspring[1::2]):
                if random.random() < 0.7:
                    toolbox.mate(c1, c2)
                    del c1.fitness.values
                    del c2.fitness.values

            # Mutation + clamp
            for mutant in offspring:
                if random.random() < 0.3:
                    toolbox.mutate(mutant)
                    _clamp(mutant)
                    del mutant.fitness.values

            # Evaluate changed individuals — parallel (Phase 6A)
            invalid = [ind for ind in offspring if not ind.fitness.valid]
            self._parallel_evaluate_deap(invalid, toolbox)

            # Elitism: keep best 2 from old population
            hof.update(pop)
            pop[:] = offspring
            for i, elite in enumerate(hof):
                pop[i] = toolbox.clone(elite)

    # ─── Built-in GA (fallback when DEAP unavailable) ───────

    def _run_genetic_builtin(self, n_override: int | None = None, seed_from_history: bool = False):
        """Simple evolutionary algorithm — no external dependencies.
        Phase 6A: uses parallel evaluation for population batches.
        Phase 6C: checks early stopping each generation.
        """
        n = n_override or self.n_trials
        pop_size = min(20, max(8, n // 5))
        generations = max(1, n // pop_size)
        start_trial = len(self.history)

        if seed_from_history and self.history:
            sorted_h = sorted(self.history, key=lambda t: t.score, reverse=True)
            population = [t.params for t in sorted_h[:pop_size]]
            while len(population) < pop_size:
                base_p = random.choice(population[:max(1, len(population))])
                population.append(self._mutate(base_p))
        else:
            population = [self._random_params() for _ in range(pop_size)]

        # Evaluate initial population in parallel (Phase 6A)
        fitness = self._parallel_evaluate_builtin(population, start_trial)
        trial_count = pop_size

        for _gen in range(generations):
            if self._cancelled or self._should_early_stop():
                return

            new_pop = []
            new_fit = []

            sorted_idx = sorted(range(len(fitness)), key=lambda i: fitness[i], reverse=True)
            for idx in sorted_idx[:2]:
                new_pop.append(population[idx])
                new_fit.append(fitness[idx])

            # Generate offspring
            offspring = []
            while len(offspring) < pop_size - 2:
                if self._cancelled or self._should_early_stop():
                    return
                p1 = self._tournament_select(population, fitness)
                p2 = self._tournament_select(population, fitness)
                child = self._crossover(p1, p2)
                if random.random() < 0.3:
                    child = self._mutate(child)
                offspring.append(child)

            # Evaluate offspring in parallel (Phase 6A)
            offspring_fitness = self._parallel_evaluate_builtin(offspring, start_trial + trial_count)
            trial_count += len(offspring)

            new_pop.extend(offspring)
            new_fit.extend(offspring_fitness)

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
            if self._cancelled or self._should_early_stop():
                return
            params = self._random_params()
            score, stats = self._evaluate(params)
            self._record_trial(i, params, score, stats)

    # ─── Core Evaluation ────────────────────────────────────

    def _run_backtest(self, config: dict, bars):
        """Route backtest to V2 unified runner (Phase 6B).

        All strategy types (builder, MSS, Gold BT, file-based) are handled
        by run_unified_backtest which detects the type from config.
        """
        from app.services.backtest.v2_adapter import run_unified_backtest, v2_result_to_v1

        # File-based strategies still use file_runner directly
        file_info = config.get("_file_strategy")
        if file_info:
            from app.services.strategy.file_runner import run_file_strategy
            settings_vals = dict(file_info.get("settings_values", {}))
            for path_key in list(config.keys()):
                if path_key.startswith("settings_values."):
                    actual_key = path_key.split(".", 1)[1]
                    settings_vals[actual_key] = config[path_key]
            bars_raw = bars
            if bars and hasattr(bars[0], "open"):
                bars_raw = [
                    {"time": b.time, "open": b.open, "high": b.high,
                     "low": b.low, "close": b.close, "volume": b.volume}
                    for b in bars
                ]
            return run_file_strategy(
                strategy_type=file_info["strategy_type"],
                file_path=file_info["file_path"],
                settings_values=settings_vals,
                bars_raw=bars_raw,
                initial_balance=self.initial_balance,
                spread_points=self.spread,
                commission_per_lot=self.commission,
                point_value=self.point_value,
            )

        # Route everything else through V2 unified runner
        # Restructure config for run_unified_backtest which expects
        # mss_config / gold_bt_config nested under "filters"
        strategy_config = dict(config)
        # Ensure filters wrapper exists for MSS / Gold BT detection
        if "mss_config" in strategy_config or "gold_bt_config" in strategy_config:
            filters = strategy_config.setdefault("filters", {})
            if "mss_config" in strategy_config and "mss_config" not in filters:
                filters["mss_config"] = strategy_config.pop("mss_config")
            if "gold_bt_config" in strategy_config and "gold_bt_config" not in filters:
                filters["gold_bt_config"] = strategy_config.pop("gold_bt_config")

        v2_result = run_unified_backtest(
            bars=bars,
            strategy_config=strategy_config,
            symbol=self.symbol,
            initial_balance=self.initial_balance,
            spread_points=self.spread,
            commission_per_lot=self.commission,
            point_value=self.point_value,
        )

        # Convert V2 RunResult → V1 BacktestResult for metric extraction
        return v2_result_to_v1(v2_result, self.initial_balance, len(bars))

    def _evaluate(self, params: dict) -> tuple[float, dict]:
        """Run backtest with given params and return (score, stats)."""
        config = copy.deepcopy(self.base_config)

        # Apply trial params to config
        for path, value in params.items():
            try:
                _set_nested(config, path, value)
            except (KeyError, IndexError, TypeError) as e:
                logger.debug(f"Could not set param {path}={value}: {e}")

        # Apply frozen params — these always override trial params
        for path, value in self.frozen_params.items():
            try:
                _set_nested(config, path, value)
            except (KeyError, IndexError, TypeError) as e:
                logger.debug(f"Could not set frozen param {path}={value}: {e}")

        # Run backtest on in-sample data (route through V2 unified runner)
        result = self._run_backtest(config, self.in_sample_bars)

        # Extract score based on primary objective
        score = self._extract_score(result)

        stats = {
            "total_trades": result.total_trades,
            "win_rate": round(result.win_rate, 2),
            "net_profit": round(result.net_profit, 2),
            "profit_factor": round(result.profit_factor, 4),
            "sharpe_ratio": round(result.sharpe_ratio, 4),
            "max_drawdown_pct": round(result.max_drawdown_pct, 2),
            "expectancy": round(result.expectancy, 2),
            "sqn": round(getattr(result, "sqn", 0.0), 4),
            "yearly_pnl": getattr(result, "yearly_pnl", {}),
            "negative_years": getattr(result, "negative_years", 0),
        }

        # Phase 6C: max-DD abort — penalize if drawdown exceeds threshold
        if self.max_dd_abort > 0 and result.max_drawdown_pct > self.max_dd_abort:
            score = -1e6
            stats["dd_aborted"] = True

        # Apply secondary objective threshold filter
        if self.secondary_objective and self.secondary_threshold is not None:
            secondary_value = self._get_metric(result, self.secondary_objective)
            if self.secondary_operator == ">=":
                if secondary_value < self.secondary_threshold:
                    score = -999.0  # penalize — fails secondary filter
            elif self.secondary_operator == "<=":
                if secondary_value > self.secondary_threshold:
                    score = -999.0  # penalize — fails secondary filter
            stats["secondary_metric"] = round(secondary_value, 4)
            stats["secondary_passed"] = score != -999.0

        # If walk-forward, also run OOS and penalize divergence
        if self.walk_forward and self.out_sample_bars:
            oos_result = self._run_backtest(config, self.out_sample_bars)
            oos_score = self._extract_score(oos_result)

            stats["oos_net_profit"] = round(oos_result.net_profit, 2)
            stats["oos_sharpe"] = round(oos_result.sharpe_ratio, 4)
            stats["oos_win_rate"] = round(oos_result.win_rate, 2)

            # Combine: 40% in-sample + 60% out-of-sample
            score = 0.4 * score + 0.6 * oos_score

        return score, stats

    def _get_metric(self, result, metric: str) -> float:
        """Get a specific metric value from a backtest result."""
        if metric == "sharpe_ratio":
            return result.sharpe_ratio
        elif metric == "net_profit":
            return result.net_profit
        elif metric == "profit_factor":
            return result.profit_factor if result.profit_factor < 100 else 0
        elif metric == "win_rate":
            return result.win_rate
        elif metric == "sqn":
            return getattr(result, "sqn", 0.0)
        elif metric == "sharpe_sqrt_trades":
            # Composite: reward high-confidence Sharpe with trade volume
            n = result.total_trades
            s = result.sharpe_ratio
            return s * math.sqrt(n) if n > 0 and s > 0 else 0.0
        elif metric == "pf_times_sharpe":
            # Composite: good fill + statistical confidence
            pf = result.profit_factor if result.profit_factor < 100 else 0
            s = result.sharpe_ratio
            return pf * s if pf > 0 and s > 0 else 0.0
        elif metric == "expectancy_score":
            # Composite: expectancy weighted by trade count
            n = result.total_trades
            return result.expectancy * math.sqrt(n) if n > 0 else 0.0
        return 0.0

    def _extract_score(self, result) -> float:
        """Extract the optimization target from backtest result."""
        if result.total_trades < self.min_trades:
            return -1e6  # Penalize strategies with too few trades
        return self._get_metric(result, self.objective)

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
            self._trials_since_improvement = 0
        else:
            self._trials_since_improvement += 1

        if self.progress_callback:
            self.progress_callback(len(self.history), self.n_trials, self.best_score, self.best_params)

    # ─── Phase 6A: Parallel evaluation helpers ──────────────

    def _parallel_evaluate_deap(self, individuals: list, toolbox):
        """Evaluate a batch of DEAP individuals in parallel using ThreadPoolExecutor."""
        if not individuals:
            return
        if self.max_workers <= 1 or len(individuals) <= 1:
            # Sequential fallback
            for ind in individuals:
                if self._cancelled or self._should_early_stop():
                    ind.fitness.values = (-1e18,)
                else:
                    ind.fitness.values = toolbox.evaluate(ind)
            return

        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(individuals))) as executor:
            futures = {executor.submit(toolbox.evaluate, ind): ind for ind in individuals}
            for fut in as_completed(futures):
                ind = futures[fut]
                try:
                    ind.fitness.values = fut.result()
                except Exception:
                    ind.fitness.values = (-1e18,)

    def _parallel_evaluate_builtin(self, params_list: list[dict], start_trial: int) -> list[float]:
        """Evaluate a batch of param dicts in parallel. Returns list of fitness scores."""
        if not params_list:
            return []

        results: list[tuple[int, float]] = []  # (index, score)

        def _eval_one(idx: int, params: dict):
            score, stats = self._evaluate(params)
            self._record_trial(start_trial + idx, params, score, stats)
            return idx, score

        if self.max_workers <= 1 or len(params_list) <= 1:
            fitness = []
            for i, params in enumerate(params_list):
                if self._cancelled or self._should_early_stop():
                    fitness.append(-1e18)
                else:
                    score, stats = self._evaluate(params)
                    self._record_trial(start_trial + i, params, score, stats)
                    fitness.append(score)
            return fitness

        fitness = [0.0] * len(params_list)
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(params_list))) as executor:
            futures = {executor.submit(_eval_one, i, p): i for i, p in enumerate(params_list)}
            for fut in as_completed(futures):
                try:
                    idx, score = fut.result()
                    fitness[idx] = score
                except Exception:
                    idx = futures[fut]
                    fitness[idx] = -1e18
        return fitness

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
