"""
JSON Strategy Runner — Executes strategy definitions from .json files.

JSON format:
{
  "name": "My Strategy",
  "description": "...",
  "indicators": [ ... ],
  "entry_rules": [ ... ],
  "exit_rules": [ ... ],
  "risk_params": { ... },
  "filters": { ... }
}

This simply parses the JSON and wraps it via BuilderStrategy, since the
JSON format matches the visual-builder strategy_config.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .bar import Bar
from .builder_strategy import BuilderStrategy
from .strategy import StrategyBase, StrategyContext

logger = logging.getLogger(__name__)


class JsonStrategy(StrategyBase):
    """Wraps a .json strategy file through BuilderStrategy."""

    def __init__(self, file_path: str, symbol: str = "ASSET"):
        self.file_path = file_path
        self._inner: BuilderStrategy | None = None
        self._symbol = symbol

        config = self._load_config()
        super().__init__(
            name=config.get("name", Path(file_path).stem),
            params=config,
        )
        self._inner = BuilderStrategy(
            strategy_config=config,
            symbol=symbol,
        )

    def _load_config(self) -> dict:
        """Load and validate the JSON strategy file."""
        path = Path(self.file_path)
        if not path.exists():
            raise FileNotFoundError(f"Strategy file not found: {self.file_path}")
        if path.suffix.lower() != ".json":
            raise ValueError(f"Strategy file must be .json: {self.file_path}")

        try:
            raw = path.read_text(encoding="utf-8")
            config = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {path.name}: {e}") from e

        if not isinstance(config, dict):
            raise ValueError(f"Strategy JSON must be an object, got {type(config).__name__}")

        # Validate required sections
        required_keys = {"entry_rules"}
        missing = required_keys - set(config.keys())
        if missing:
            raise ValueError(f"Missing required keys in strategy JSON: {missing}")

        # Ensure optional keys have defaults
        config.setdefault("indicators", [])
        config.setdefault("exit_rules", [])
        config.setdefault("risk_params", {})
        config.setdefault("filters", {})

        return config

    def _set_context(self, ctx: StrategyContext) -> None:
        super()._set_context(ctx)
        if self._inner:
            self._inner._set_context(ctx)

    def on_init(self) -> None:
        if self._inner:
            self._inner.on_init()

    def on_bar(self, bar: Bar) -> None:
        if self._inner:
            self._inner.on_bar(bar)

    def on_order_filled(self, order) -> None:
        if self._inner:
            self._inner.on_order_filled(order)

    def on_position_closed(self, symbol: str, pnl: float) -> None:
        if self._inner:
            self._inner.on_position_closed(symbol, pnl)

    def on_end(self) -> None:
        if self._inner:
            self._inner.on_end()
