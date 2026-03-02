"""
Look-Ahead Bias Detection for the V2 backtesting engine.

Detects whether a strategy's signals change when future data is removed,
which would indicate the strategy (or its indicators) peek at future bars.

Algorithm (inspired by Freqtrade's approach):
  1. Run a full backtest on all N bars → record signal at each bar
  2. For a sample of bar indices, re-run with data truncated at that bar
  3. Compare the signal at bar K in the truncated run vs the full run
  4. If signals differ → look-ahead bias confirmed at that bar

The "signal" is captured as:
  - Orders submitted during on_bar() for a given bar_index
  - Specifically: side (BUY/SELL) and whether any order was placed

This is a statistical test — we sample S bars (default 50) to keep
run-time manageable, then report a bias score (0 = clean, 100 = severe).
"""

from __future__ import annotations

import copy
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from app.services.backtest.v2.engine.data_handler import DataHandler, SymbolData
from app.services.backtest.v2.engine.strategy_base import StrategyBase
from app.services.backtest.v2.engine.runner import Runner, RunConfig

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LookAheadConfig:
    """Parameters for look-ahead bias detection."""
    n_samples: int = 50              # Number of bars to test (random sample)
    seed: int = 42                   # RNG seed for sample selection
    skip_first_pct: float = 20.0     # Skip first N% of bars (warm-up zone)
    skip_last_pct: float = 5.0       # Skip last N% of bars (too short to matter)
    tolerance: float = 0.0           # Price tolerance for "same" order (0 = exact)


# ────────────────────────────────────────────────────────────────────
# Result
# ────────────────────────────────────────────────────────────────────

@dataclass
class SignalSnapshot:
    """Signal captured at a specific bar."""
    bar_index: int
    has_signal: bool                  # Whether any order was submitted
    side: Optional[str] = None        # "BUY" / "SELL" / None
    order_type: Optional[str] = None  # "MARKET" / "LIMIT" / "STOP" etc.
    quantity: float = 0.0
    price: Optional[float] = None     # Limit/stop price if applicable


@dataclass
class LookAheadTestPoint:
    """Result of one sample point comparison."""
    bar_index: int
    full_signal: SignalSnapshot
    truncated_signal: SignalSnapshot
    is_biased: bool                   # True if signals differ
    detail: str = ""                  # Human-readable explanation


@dataclass
class LookAheadResult:
    """Complete look-ahead bias detection result."""
    n_bars_tested: int
    n_bars_total: int
    n_biased: int
    bias_score: float                 # 0–100: percentage of tested bars with bias
    is_clean: bool                    # True if bias_score == 0
    biased_bars: list[int]            # Bar indices where bias was detected
    test_points: list[LookAheadTestPoint]
    elapsed_seconds: float
    summary: str                      # Human-readable summary


# ────────────────────────────────────────────────────────────────────
# Signal Capture Strategy Wrapper
# ────────────────────────────────────────────────────────────────────

class _SignalCapture(StrategyBase):
    """Wraps a real strategy and captures its order submissions per bar.

    After running, `captured_signals` maps bar_index → SignalSnapshot.
    """

    def __init__(self, inner: StrategyBase):
        super().__init__(name=f"_capture({inner.name})", params=inner.params)
        self._inner = inner
        self.captured_signals: dict[int, SignalSnapshot] = {}

    def on_init(self):
        # Wire inner strategy to our context
        self._inner.ctx = self.ctx
        self._inner.on_init()

    def on_bar(self, event):
        # Clear pending orders before letting inner strategy act
        # (We need to capture ONLY what this bar produces)
        self.ctx._order_queue = []
        self.ctx._init_cancel_requests()

        # Let inner strategy act
        self._inner.on_bar(event)

        # Capture what was submitted
        orders = list(self.ctx._order_queue)
        if orders:
            first = orders[0]
            self.captured_signals[event.bar_index] = SignalSnapshot(
                bar_index=event.bar_index,
                has_signal=True,
                side=first.side.value if hasattr(first.side, 'value') else str(first.side),
                order_type=first.order_type.value if hasattr(first.order_type, 'value') else str(first.order_type),
                quantity=first.quantity,
                price=first.limit_price or first.stop_price,
            )
        else:
            self.captured_signals[event.bar_index] = SignalSnapshot(
                bar_index=event.bar_index,
                has_signal=False,
            )

    def on_fill(self, event):
        self._inner.on_fill(event)

    def on_end(self):
        self._inner.on_end()


# ────────────────────────────────────────────────────────────────────
# Core Detection Logic
# ────────────────────────────────────────────────────────────────────

def detect_look_ahead(
    bars_dict: dict[str, list],
    strategy_factory,
    run_config: Optional[RunConfig] = None,
    config: Optional[LookAheadConfig] = None,
    indicator_configs: Optional[dict] = None,
) -> LookAheadResult:
    """Detect look-ahead bias in a strategy.

    Parameters
    ----------
    bars_dict : dict[str, list]
        Mapping of symbol → list of bar dicts (same format as DataHandler).
        Usually just one symbol: {"XAUUSD": [bar_dicts...]}.
    strategy_factory : callable
        A zero-argument callable that returns a fresh StrategyBase instance.
        Must create a NEW strategy each time (strategies have state).
        Example: ``lambda: SMACrossover(params={"fast": 10, "slow": 30})``
    run_config : RunConfig, optional
        Backtest configuration. Default if None.
    config : LookAheadConfig, optional
        Detection parameters. Default if None.
    indicator_configs : dict, optional
        Indicator configs to pass to DataHandler.add_symbol.

    Returns
    -------
    LookAheadResult
    """
    if config is None:
        config = LookAheadConfig()
    if run_config is None:
        run_config = RunConfig()
    # Disable tearsheet for speed during detection
    from app.services.backtest.v2.analytics.tearsheet import TearsheetConfig
    run_config.tearsheet = TearsheetConfig(
        enable_monte_carlo=False,
        enable_benchmark=False,
        enable_rolling=False,
    )

    t0 = time.perf_counter()

    # ── Step 1: Full run — capture signals at every bar ─────────────
    primary_sym = next(iter(bars_dict))
    all_bars = bars_dict[primary_sym]
    n_total = len(all_bars)

    full_signals = _run_and_capture(bars_dict, strategy_factory, run_config, indicator_configs)

    # ── Step 2: Select sample bars to test ──────────────────────────
    import numpy as np
    rng = np.random.default_rng(config.seed)

    start_idx = int(n_total * config.skip_first_pct / 100)
    end_idx = int(n_total * (1 - config.skip_last_pct / 100))

    # Only test bars where the full run produced a signal (more efficient)
    signal_bars = [idx for idx in range(start_idx, end_idx)
                   if idx in full_signals and full_signals[idx].has_signal]

    if not signal_bars:
        # No signals at all — test a random sample of all bars instead
        candidate_bars = list(range(start_idx, end_idx))
        n_sample = min(config.n_samples, len(candidate_bars))
        sample_bars = sorted(rng.choice(candidate_bars, size=n_sample, replace=False).tolist())
    else:
        n_sample = min(config.n_samples, len(signal_bars))
        sample_bars = sorted(rng.choice(signal_bars, size=n_sample, replace=False).tolist())

    # ── Step 3: For each sample bar, run truncated backtest ─────────
    test_points: list[LookAheadTestPoint] = []
    n_biased = 0

    for bar_idx in sample_bars:
        # Truncate bars at bar_idx + 1 (so bar_idx is the last bar)
        truncated_bars = {sym: bs[:bar_idx + 1] for sym, bs in bars_dict.items()}

        trunc_signals = _run_and_capture(
            truncated_bars, strategy_factory, run_config, indicator_configs
        )

        # Compare signal at bar_idx
        full_sig = full_signals.get(bar_idx, SignalSnapshot(bar_index=bar_idx, has_signal=False))
        trunc_sig = trunc_signals.get(bar_idx, SignalSnapshot(bar_index=bar_idx, has_signal=False))

        is_biased = _signals_differ(full_sig, trunc_sig, config.tolerance)

        detail = ""
        if is_biased:
            n_biased += 1
            detail = _describe_difference(full_sig, trunc_sig)

        test_points.append(LookAheadTestPoint(
            bar_index=bar_idx,
            full_signal=full_sig,
            truncated_signal=trunc_sig,
            is_biased=is_biased,
            detail=detail,
        ))

    # ── Step 4: Build result ────────────────────────────────────────
    elapsed = time.perf_counter() - t0
    bias_score = round(n_biased / len(sample_bars) * 100, 1) if sample_bars else 0.0
    biased_bars = [tp.bar_index for tp in test_points if tp.is_biased]

    summary = _build_summary(n_biased, len(sample_bars), n_total, bias_score, biased_bars)

    return LookAheadResult(
        n_bars_tested=len(sample_bars),
        n_bars_total=n_total,
        n_biased=n_biased,
        bias_score=bias_score,
        is_clean=n_biased == 0,
        biased_bars=biased_bars,
        test_points=test_points,
        elapsed_seconds=round(elapsed, 3),
        summary=summary,
    )


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

def _run_and_capture(
    bars_dict: dict[str, list],
    strategy_factory,
    run_config: RunConfig,
    indicator_configs: Optional[dict],
) -> dict[int, SignalSnapshot]:
    """Run a full backtest with signal capture and return the signal map."""
    data = DataHandler()
    for sym, bars in bars_dict.items():
        pv = run_config.point_values.get(sym, 1.0)
        data.add_symbol(sym, bars, indicator_configs=indicator_configs, point_value=pv)

    inner_strategy = strategy_factory()
    capture = _SignalCapture(inner_strategy)

    runner = Runner(data_handler=data, strategy=capture, config=run_config)
    runner.run()

    return capture.captured_signals


def _signals_differ(
    full: SignalSnapshot,
    trunc: SignalSnapshot,
    tolerance: float,
) -> bool:
    """Check if two signals differ meaningfully."""
    # Case 1: Signal presence differs
    if full.has_signal != trunc.has_signal:
        return True
    # Case 2: Both have no signal — no difference
    if not full.has_signal and not trunc.has_signal:
        return False
    # Case 3: Both have signals — compare side
    if full.side != trunc.side:
        return True
    # Case 4: Compare order type
    if full.order_type != trunc.order_type:
        return True
    # Case 5: Compare quantity
    if abs(full.quantity - trunc.quantity) > 1e-9:
        return True
    # Case 6: Compare price (for limit/stop orders)
    if full.price is not None and trunc.price is not None:
        if tolerance > 0:
            if abs(full.price - trunc.price) > tolerance:
                return True
        else:
            if full.price != trunc.price:
                return True
    elif (full.price is None) != (trunc.price is None):
        return True
    return False


def _describe_difference(full: SignalSnapshot, trunc: SignalSnapshot) -> str:
    """Human-readable description of how signals differ."""
    parts = []
    if full.has_signal != trunc.has_signal:
        if full.has_signal:
            parts.append(f"Full run: {full.side} signal; truncated: no signal")
        else:
            parts.append(f"Full run: no signal; truncated: {trunc.side} signal")
    else:
        if full.side != trunc.side:
            parts.append(f"Side changed: {full.side} → {trunc.side}")
        if full.order_type != trunc.order_type:
            parts.append(f"Order type changed: {full.order_type} → {trunc.order_type}")
        if full.quantity != trunc.quantity:
            parts.append(f"Quantity changed: {full.quantity} → {trunc.quantity}")
        if full.price != trunc.price:
            parts.append(f"Price changed: {full.price} → {trunc.price}")
    return "; ".join(parts) if parts else "Unknown difference"


def _build_summary(
    n_biased: int,
    n_tested: int,
    n_total: int,
    bias_score: float,
    biased_bars: list[int],
) -> str:
    """Build a human-readable summary."""
    if n_biased == 0:
        return (
            f"CLEAN — No look-ahead bias detected. "
            f"Tested {n_tested} of {n_total} bars, all signals stable."
        )
    severity = "MILD" if bias_score < 10 else ("MODERATE" if bias_score < 30 else "SEVERE")
    return (
        f"{severity} LOOK-AHEAD BIAS — {n_biased}/{n_tested} tested bars "
        f"({bias_score}%) showed signal changes when future data removed. "
        f"Biased bars: {biased_bars[:10]}{'...' if len(biased_bars) > 10 else ''}. "
        f"Root cause likely: indicator using full array or future data access."
    )
