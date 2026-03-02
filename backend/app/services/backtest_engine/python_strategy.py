"""
Python Strategy Runner — Executes user-written .py strategy files.

Loads a .py file that either:
  A) Defines a class inheriting from StrategyBase, OR
  B) Defines an on_bar(ctx, bar) function at module level.

The file is executed in a restricted namespace with access to the
StrategyBase, StrategyContext, Bar, and Order types.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import types
from pathlib import Path
from typing import Optional

from .bar import Bar
from .strategy import StrategyBase, StrategyContext
from .order import OrderSide, OrderType, OrderRole

logger = logging.getLogger(__name__)

# Modules allowed in the strategy sandbox
ALLOWED_IMPORTS = frozenset({
    "math", "statistics", "collections", "itertools", "functools",
    "datetime", "time", "json", "re", "decimal", "fractions",
    "dataclasses", "enum", "typing", "abc",
    "numpy", "pandas",
})


class PythonStrategy(StrategyBase):
    """Wraps a user-supplied .py file as a V3 strategy."""

    def __init__(self, file_path: str, params: dict | None = None):
        super().__init__(name=Path(file_path).stem, params=params or {})
        self.file_path = file_path
        self._user_cls: Optional[type] = None
        self._user_instance: Optional[StrategyBase] = None
        self._user_on_bar = None  # Function-style strategy
        self._loaded = False

    def _load(self) -> None:
        """Load and parse the Python strategy file."""
        path = Path(self.file_path)
        if not path.exists():
            raise FileNotFoundError(f"Strategy file not found: {self.file_path}")
        if not path.suffix == ".py":
            raise ValueError(f"Strategy file must be .py: {self.file_path}")

        source = path.read_text(encoding="utf-8")

        # Create restricted namespace
        namespace = self._build_namespace()

        # Execute in namespace
        try:
            exec(compile(source, str(path), "exec"), namespace)
        except Exception as e:
            raise RuntimeError(f"Error loading strategy {path.name}: {e}") from e

        # Look for a StrategyBase subclass
        for name, obj in namespace.items():
            if (
                isinstance(obj, type)
                and issubclass(obj, StrategyBase)
                and obj is not StrategyBase
                and not name.startswith("_")
            ):
                self._user_cls = obj
                break

        # Or look for an on_bar function
        if self._user_cls is None and "on_bar" in namespace:
            fn = namespace["on_bar"]
            if callable(fn):
                self._user_on_bar = fn

        if self._user_cls is None and self._user_on_bar is None:
            raise ValueError(
                f"Strategy file {path.name} must define either a "
                f"StrategyBase subclass or an on_bar(ctx, bar) function."
            )

        self._loaded = True

    def _build_namespace(self) -> dict:
        """Build the execution namespace for user strategy."""
        from . import bar as bar_mod
        from . import strategy as strat_mod
        from . import order as order_mod

        ns = {
            "__builtins__": _safe_builtins(),
            # Engine types
            "StrategyBase": StrategyBase,
            "StrategyContext": StrategyContext,
            "Bar": Bar,
            "OrderSide": OrderSide,
            "OrderType": OrderType,
            "OrderRole": OrderRole,
            # Convenience
            "math": __import__("math"),
        }

        # Allow safe imports
        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def safe_import(name, *args, **kwargs):
            if name.split(".")[0] in ALLOWED_IMPORTS:
                return original_import(name, *args, **kwargs)
            raise ImportError(f"Import of '{name}' is not allowed in strategies.")

        ns["__import__"] = safe_import

        return ns

    def _set_context(self, ctx: StrategyContext) -> None:
        """Override to pass context to user instance."""
        super()._set_context(ctx)
        if not self._loaded:
            self._load()
        if self._user_cls:
            self._user_instance = self._user_cls(
                name=self.name, params=self.params
            )
            self._user_instance._set_context(ctx)

    def on_init(self) -> None:
        if self._user_instance:
            self._user_instance.on_init()

    def on_bar(self, bar: Bar) -> None:
        if self._user_instance:
            self._user_instance.on_bar(bar)
        elif self._user_on_bar:
            self._user_on_bar(self.ctx, bar)

    def on_order_filled(self, order) -> None:
        if self._user_instance:
            self._user_instance.on_order_filled(order)

    def on_position_closed(self, symbol: str, pnl: float) -> None:
        if self._user_instance:
            self._user_instance.on_position_closed(symbol, pnl)

    def on_end(self) -> None:
        if self._user_instance:
            self._user_instance.on_end()


def _safe_builtins() -> dict:
    """Return a restricted builtins dict for strategy execution."""
    import builtins

    safe = {}
    allowed = {
        # Types & constructors
        "int", "float", "str", "bool", "list", "dict", "tuple", "set",
        "frozenset", "bytes", "bytearray", "complex", "type",
        "range", "enumerate", "zip", "map", "filter", "reversed", "sorted",
        "min", "max", "abs", "sum", "round", "pow", "divmod",
        "len", "any", "all", "hash", "id", "repr", "str", "format",
        "isinstance", "issubclass", "callable", "hasattr", "getattr", "setattr",
        "print", "super", "property", "staticmethod", "classmethod",
        "True", "False", "None",
        "ValueError", "TypeError", "KeyError", "IndexError",
        "RuntimeError", "StopIteration", "AttributeError",
        "Exception", "BaseException",
        "NotImplementedError", "ZeroDivisionError",
    }
    for name in allowed:
        if hasattr(builtins, name):
            safe[name] = getattr(builtins, name)

    return safe
