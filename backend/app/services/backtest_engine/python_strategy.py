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


# ── Legacy Python Strategy Adapter ──────────────────────────────────
#
# Bridges old-style strategies that define init(bars, settings) + on_bar(i, bar)
# with injected globals (open_trade, close_trade, open_trades, bars,
# __strategy_context__) into the V3 StrategyBase interface.


class LegacyPythonStrategy(StrategyBase):
    """Wraps old-style Python strategies for the V3 engine.

    Old-style strategies define:
      - init(bars, settings) → context dict
      - on_bar(i, bar)       → uses injected globals

    Injected globals:
      - bars:                   full bar list (list[dict])
      - __strategy_context__:   dict returned by init()
      - open_trade(dir, price, sl, tp):  open a new trade
      - close_trade(id, price, reason):  close a trade
      - open_trades:            list of open trade dicts
    """

    def __init__(self, file_path: str, settings: dict, all_bars: list[dict]):
        super().__init__(name=Path(file_path).stem, params=settings)
        self.file_path = file_path
        self.settings = settings
        self.all_bars = all_bars  # Full bar list for bars[i] lookback
        self._module_ns: dict = {}
        self._strategy_ctx: Optional[dict] = None
        self._open_trades: list[dict] = []
        self._trade_counter: int = 0
        self._loaded = False

    def _load(self) -> None:
        """Load and compile the strategy file."""
        import builtins as _builtins
        import math as _math

        path = Path(self.file_path)
        if not path.exists():
            raise FileNotFoundError(f"Strategy file not found: {self.file_path}")

        source = path.read_text(encoding="utf-8")

        # Build namespace with injected globals
        self._module_ns = {
            "__builtins__": _builtins.__dict__,
            "__name__": f"strategy_{path.stem}",
            "math": _math,
            # These will be updated before each on_bar call
            "open_trade": self._bridge_open_trade,
            "close_trade": self._bridge_close_trade,
            "open_trades": self._open_trades,
            "bars": self.all_bars,
        }

        # Allow common imports
        for mod_name in ("math", "statistics", "datetime", "collections",
                         "json", "re", "functools", "itertools"):
            try:
                self._module_ns[mod_name] = __import__(mod_name)
            except ImportError:
                pass

        # Execute strategy source in namespace
        try:
            exec(compile(source, str(path), "exec"), self._module_ns)
        except Exception as e:
            raise RuntimeError(f"Error loading strategy {path.name}: {e}") from e

        self._loaded = True
        logger.info("Loaded legacy Python strategy: %s", path.name)

    def on_init(self) -> None:
        """Load module and call strategy's init()."""
        if not self._loaded:
            self._load()

        init_fn = self._module_ns.get("init")
        if init_fn and callable(init_fn):
            try:
                self._strategy_ctx = init_fn(self.all_bars, self.settings)
                if isinstance(self._strategy_ctx, dict):
                    self._module_ns["__strategy_context__"] = self._strategy_ctx
                logger.info(
                    "Legacy strategy init() returned context with keys: %s",
                    list(self._strategy_ctx.keys()) if isinstance(self._strategy_ctx, dict) else "N/A",
                )
            except Exception as e:
                logger.error("Legacy strategy init() failed: %s", e)
                raise

    def on_bar(self, bar: Bar) -> None:
        """Call the strategy's on_bar(i, bar_dict)."""
        i = self.ctx.bar_index

        # Update injected globals
        self._module_ns["open_trades"] = self._open_trades

        on_bar_fn = self._module_ns.get("on_bar")
        if on_bar_fn and callable(on_bar_fn):
            try:
                on_bar_fn(i, self.all_bars[i])
            except Exception as e:
                # Log but don't crash — allow the backtest to continue
                if i < 5 or i % 1000 == 0:
                    logger.warning("Legacy on_bar(%d) error: %s", i, e)

    def on_position_closed(self, symbol: str, pnl: float) -> None:
        """Sync open_trades when engine closes a position (SL/TP hit)."""
        if self._open_trades:
            self._open_trades.pop(0)

    # ── Bridge Functions (injected into strategy namespace) ──────────

    def _bridge_open_trade(self, direction: str, entry_price: float,
                           sl: float, tp: float, **kwargs) -> None:
        """Bridge: open_trade("long", price, sl, tp) → ctx.buy_bracket()."""
        self._trade_counter += 1
        trade_id = f"legacy_{self.ctx.bar_index}_{self._trade_counter}"

        if direction == "long":
            self.ctx.buy_bracket(
                stop_loss=sl, take_profit=tp,
                symbol=self.ctx._instrument.symbol, tag=trade_id,
            )
        else:
            self.ctx.sell_bracket(
                stop_loss=sl, take_profit=tp,
                symbol=self.ctx._instrument.symbol, tag=trade_id,
            )

        self._open_trades.append({
            "id": trade_id,
            "direction": direction,
            "entry_price": entry_price,
            "sl": sl,
            "tp": tp,
            "entry_bar": self.ctx.bar_index,
        })

    def _bridge_close_trade(self, trade_id: str, price: float,
                            reason: str = "", **kwargs) -> None:
        """Bridge: close_trade(id, price, reason) → ctx.close_position()."""
        self.ctx.close_position(
            symbol=self.ctx._instrument.symbol,
            tag=f"close_{reason}",
        )
        self._open_trades = [t for t in self._open_trades if t["id"] != trade_id]
