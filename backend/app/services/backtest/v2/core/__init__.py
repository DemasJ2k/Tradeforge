"""
FlowrexAlgo Core — Rust-accelerated hot-path engine.

Provides FastRunner, FastPortfolio, indicators, and tick matching
backed by a compiled Rust extension (tradeforge_core, via PyO3).

Falls back to a pure-Python implementation automatically if the
Rust extension is not compiled.

Build the Rust extension:
    cd backend/app/services/backtest/v2/core
    maturin develop --release

Check availability:
    >>> from app.services.backtest.v2.core import USING_RUST
    >>> print("Rust" if USING_RUST else "Python fallback")
"""

from app.services.backtest.v2.core.python_bindings import *  # noqa: F401,F403
from app.services.backtest.v2.core.python_bindings import USING_RUST  # noqa: F401
