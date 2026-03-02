"""
Data Feed — Multi-symbol, multi-timeframe data management.

Holds bar data and pre-computed indicators for all symbols and timeframes.
"""

from __future__ import annotations

import numpy as np
from typing import Optional

from .bar import Bar
from .indicator_engine import compute_indicators


class SymbolData:
    """Holds bars and indicators for one symbol at one timeframe."""

    def __init__(self, symbol: str, timeframe: str = ""):
        self.symbol = symbol
        self.timeframe = timeframe
        self.bars: list[Bar] = []
        self.bar_dicts: list[dict] = []
        self.indicators: dict[str, np.ndarray] = {}

    def load_bars(self, bars: list[Bar], indicator_configs: list[dict] | None = None) -> None:
        """Load bars and compute indicators."""
        self.bars = bars
        self.bar_dicts = [b.to_dict() for b in bars]

        if indicator_configs:
            self.indicators = compute_indicators(self.bar_dicts, indicator_configs)
        else:
            # Always compute basic price arrays
            self.indicators = compute_indicators(self.bar_dicts, [])

    def load_from_dicts(self, bar_dicts: list[dict],
                        indicator_configs: list[dict] | None = None) -> None:
        """Load from raw dicts (API format)."""
        self.bar_dicts = bar_dicts
        self.bars = [Bar.from_dict(d) for d in bar_dicts]

        if indicator_configs:
            self.indicators = compute_indicators(bar_dicts, indicator_configs)
        else:
            self.indicators = compute_indicators(bar_dicts, [])

    @property
    def count(self) -> int:
        return len(self.bars)

    def get_bar(self, index: int) -> Optional[Bar]:
        if 0 <= index < len(self.bars):
            return self.bars[index]
        return None

    def get_indicator(self, name: str, index: int) -> float:
        """Get indicator value at bar index. Returns NaN if unavailable."""
        arr = self.indicators.get(name)
        if arr is not None and 0 <= index < len(arr):
            return float(arr[index])
        return float("nan")

    def get_indicator_array(self, name: str) -> Optional[np.ndarray]:
        return self.indicators.get(name)


class DataFeed:
    """Multi-symbol, multi-timeframe data feed."""

    def __init__(self):
        self._data: dict[str, dict[str, SymbolData]] = {}  # symbol -> timeframe -> SymbolData

    def add_symbol(
        self,
        symbol: str,
        bars: list[Bar] | list[dict],
        timeframe: str = "primary",
        indicator_configs: list[dict] | None = None,
    ) -> SymbolData:
        """Add a symbol's bar data to the feed."""
        sd = SymbolData(symbol=symbol, timeframe=timeframe)

        if bars and isinstance(bars[0], dict):
            sd.load_from_dicts(bars, indicator_configs)
        else:
            sd.load_bars(bars, indicator_configs)

        if symbol not in self._data:
            self._data[symbol] = {}
        self._data[symbol][timeframe] = sd
        return sd

    def get_symbol_data(self, symbol: str, timeframe: str = "primary") -> Optional[SymbolData]:
        return self._data.get(symbol, {}).get(timeframe)

    def get_bar(self, symbol: str, index: int, timeframe: str = "primary") -> Optional[Bar]:
        sd = self.get_symbol_data(symbol, timeframe)
        return sd.get_bar(index) if sd else None

    def get_indicator(self, symbol: str, name: str, index: int,
                      timeframe: str = "primary") -> float:
        sd = self.get_symbol_data(symbol, timeframe)
        return sd.get_indicator(name, index) if sd else float("nan")

    def bar_count(self, symbol: str, timeframe: str = "primary") -> int:
        sd = self.get_symbol_data(symbol, timeframe)
        return sd.count if sd else 0

    @property
    def symbols(self) -> list[str]:
        return list(self._data.keys())

    @property
    def primary_symbol(self) -> Optional[str]:
        symbols = self.symbols
        return symbols[0] if symbols else None
