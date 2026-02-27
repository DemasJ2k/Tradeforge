"""
Gold BT Evaluator — wraps GoldBTEngine for use within AgentRunner.

Manages engine lifecycle (warmup, zone computation) and provides
a simple interface for the algo engine to call on each new bar.
"""

import logging
from typing import Optional

from app.services.strategy.gold_bt_engine import GoldBTEngine, GoldBTSignal, DEFAULT_GOLD_BT_CONFIG

logger = logging.getLogger(__name__)


class GoldBTEvaluator:
    """
    Wraps GoldBTEngine for use within the Algo Trading Engine.

    Usage:
        evaluator = GoldBTEvaluator("XAUUSD", config)
        signal = evaluator.on_bar(bars_list)
    """

    def __init__(self, symbol: str, config: Optional[dict] = None):
        self.symbol = symbol
        bt_config = config or DEFAULT_GOLD_BT_CONFIG
        self.engine = GoldBTEngine(symbol, bt_config)

    def on_bar(
        self,
        bars: list[dict],
        daily_bars: Optional[list[dict]] = None,
        adr10_override: float = 0.0,
    ):
        """
        Called on each new closed bar.

        Args:
            bars: Recent M1/M5 bars (list of dicts).
            daily_bars: Not used for Gold BT (zones are self-contained).
            adr10_override: Not used for Gold BT.

        Returns:
            GoldBTSignal if a breakout is detected, None otherwise.
        """
        return self.engine.evaluate(bars)

    def check_reversal(self, bars: list[dict]) -> bool:
        """Read-only check for reversal signal (used to close existing positions)."""
        return self.engine.has_reversal_signal(bars)

    def get_state(self) -> dict:
        """Get current engine state for display."""
        return self.engine.get_state_summary()
