"""
MSS Evaluator — wraps MSSEngine for use within AgentRunner.

Manages engine lifecycle (warmup, ADR10 computation) and provides
a simple interface for the algo engine to call on each new bar.
"""

import logging
from typing import Optional

from app.services.strategy.mss_engine import MSSEngine, MSSSignal, DEFAULT_MSS_CONFIG

logger = logging.getLogger(__name__)


class MSSEvaluator:
    """
    Wraps MSSEngine for use within the Algo Trading Engine.

    Usage:
        evaluator = MSSEvaluator("XAUUSD", config)
        signal = evaluator.on_bar(bars_list, daily_bars_list)
    """

    def __init__(self, symbol: str, config: Optional[dict] = None):
        self.symbol = symbol
        mss_config = config or DEFAULT_MSS_CONFIG
        self.engine = MSSEngine(symbol, mss_config)
        self._last_adr10: float = 0.0

    def on_bar(
        self,
        bars: list[dict],
        daily_bars: Optional[list[dict]] = None,
        adr10_override: float = 0.0,
    ) -> Optional[MSSSignal]:
        """
        Called on each new closed bar.

        Args:
            bars: Recent M10/M15 bars (list of dicts). Need at least 85 bars.
            daily_bars: Recent D1 bars for ADR10 computation (at least 10).
            adr10_override: If provided, use this instead of computing from daily_bars.

        Returns:
            MSSSignal if a BOS/CHoCH breakout is detected, None otherwise.
        """
        # Compute ADR10
        if adr10_override > 0:
            adr10 = adr10_override
        elif daily_bars:
            adr10 = MSSEngine.compute_adr10(daily_bars)
        elif self._last_adr10 > 0:
            adr10 = self._last_adr10
        else:
            logger.warning("[MSSEval] %s: No ADR10 available, skipping", self.symbol)
            return None

        self._last_adr10 = adr10
        return self.engine.evaluate(bars, adr10)

    def check_reversal(self, bars: list[dict]) -> bool:
        """Read-only check for reversal signal (used to close existing positions)."""
        return self.engine.has_reversal_signal(bars)

    def get_state(self) -> dict:
        """Get current engine state for display."""
        return self.engine.get_state_summary()
