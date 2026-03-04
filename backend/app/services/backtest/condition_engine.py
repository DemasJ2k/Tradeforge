"""Phase 3A — Unified Condition Engine.

Replaces the 4 duplicated implementations of condition evaluation
with a single reusable module that supports nested IF/THEN/ELSE
condition groups.

Schema overview
===============

A *flat* condition (legacy ``ConditionRow``):

    {"type": "condition",
     "left": "ema_1", "operator": "crosses_above", "right": "ema_2",
     "logic": "AND", "direction": "both"}

A *group* of conditions:

    {"type": "group", "logic": "AND",
     "conditions": [ <condition | group | if_then_else>, ... ]}

An *if/then/else* node:

    {"type": "if_then_else",
     "if":   <group>,
     "then": <group>,
     "else": <group | null>}

Backward compatibility: a plain ``list[dict]`` with no ``type`` key
is auto-wrapped in a single AND group (the legacy flat model).
"""

from __future__ import annotations

import math
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "evaluate_condition_tree",
    "evaluate_direction",
    "normalise_rules",
    "passes_filters",
]


# ---------------------------------------------------------------------------
# Value resolver protocol
# ---------------------------------------------------------------------------
# A *value_fn* takes (source: str, bar_idx: int) → float.
# It is supplied by whichever engine calls the condition engine so that
# indicator look-ups and price look-ups are engine-agnostic.
ValueFn = Callable[[str, int], float]


# ---------------------------------------------------------------------------
# Normalise legacy rules → new tree format
# ---------------------------------------------------------------------------

def normalise_rules(rules: list[dict] | dict | None) -> dict:
    """Convert *rules* into a canonical condition-tree dict.

    Accepts:
    - ``None`` / empty list  →  empty AND group
    - ``list[dict]`` without ``type``/``node_type`` key  →  wrap as flat AND/OR chain
    - A single dict that already has ``type``/``node_type`` → passthrough
    """
    if rules is None or (isinstance(rules, list) and len(rules) == 0):
        return {"node_type": "group", "group_logic": "AND", "children": []}

    if isinstance(rules, dict):
        if "type" in rules or "node_type" in rules:
            return _normalise_keys(rules)
        # Single leaf dict without type/node_type → wrap as group with one child
        child = _normalise_keys(rules)
        if child.get("node_type") is None:
            child["node_type"] = "condition"
        return {"node_type": "group", "group_logic": "AND", "children": [child]}

    if isinstance(rules, list):
        # Legacy flat list → wrap.  Respect per-row logic.
        children = []
        for r in rules:
            child = _normalise_keys(r)
            if child.get("node_type") is None:
                child["node_type"] = "condition"
            children.append(child)
        return {"node_type": "group", "group_logic": "AND", "children": children}

    return {"node_type": "group", "group_logic": "AND", "children": []}


def _normalise_keys(node: dict) -> dict:
    """Normalise node keys to the canonical schema:
    ``node_type``, ``group_logic``, ``children``, ``if_cond``, ``then_cond``, ``else_cond``.
    
    Also accepts legacy keys: ``type``, ``logic``, ``conditions``, ``if``, ``then``, ``else``.
    """
    out = dict(node)
    # type → node_type
    if "type" in out and "node_type" not in out:
        out["node_type"] = out.pop("type")
    # conditions → children
    if "conditions" in out and "children" not in out:
        out["children"] = out.pop("conditions")
    # logic → group_logic (only for group nodes)
    nt = out.get("node_type", "condition")
    if nt == "group" and "logic" in out and "group_logic" not in out:
        out["group_logic"] = out.pop("logic")
    # if/then/else → if_cond/then_cond/else_cond
    if "if" in out and "if_cond" not in out:
        out["if_cond"] = out.pop("if")
    if "then" in out and "then_cond" not in out:
        out["then_cond"] = out.pop("then")
    if "else" in out and "else_cond" not in out:
        out["else_cond"] = out.pop("else")
    # Recursively normalise children
    if "children" in out and isinstance(out["children"], list):
        out["children"] = [_normalise_keys(c) for c in out["children"]]
    for key in ("if_cond", "then_cond", "else_cond"):
        if key in out and isinstance(out[key], dict):
            out[key] = _normalise_keys(out[key])
    return out


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def _eval_single(rule: dict, bar_idx: int, value_fn: ValueFn) -> bool:
    """Evaluate a single flat condition (``node_type: "condition"``)."""
    left_now = value_fn(rule["left"], bar_idx)
    right_now = value_fn(rule["right"], bar_idx)

    if any(math.isnan(v) for v in (left_now, right_now)):
        return False

    op = rule.get("operator", ">")

    # Cross operators need previous bar
    if op in ("crosses_above", "crosses_below"):
        if bar_idx < 1:
            return False
        left_prev = value_fn(rule["left"], bar_idx - 1)
        right_prev = value_fn(rule["right"], bar_idx - 1)
        if any(math.isnan(v) for v in (left_prev, right_prev)):
            return False
        if op == "crosses_above":
            return left_prev <= right_prev and left_now > right_now
        return left_prev >= right_prev and left_now < right_now

    if op == ">":
        return left_now > right_now
    if op == "<":
        return left_now < right_now
    if op == ">=":
        return left_now >= right_now
    if op == "<=":
        return left_now <= right_now
    if op == "==":
        return abs(left_now - right_now) < 1e-10
    if op == "!=":
        return abs(left_now - right_now) >= 1e-10
    return False


def _eval_node(node: dict, bar_idx: int, value_fn: ValueFn) -> bool:
    """Recursively evaluate any node in the condition tree."""
    ntype = node.get("node_type", node.get("type", "condition"))

    # ── Leaf: single condition ──────────────────────────────────
    if ntype == "condition":
        return _eval_single(node, bar_idx, value_fn)

    # ── Group: AND / OR over children ───────────────────────────
    if ntype == "group":
        children = node.get("children", node.get("conditions", []))
        if not children:
            return False
        logic = node.get("group_logic", node.get("logic", "AND")).upper()
        if logic == "OR":
            return any(_eval_node(c, bar_idx, value_fn) for c in children)
        # Default AND — but respect per-child "logic" field for legacy compat
        return _eval_chain(children, bar_idx, value_fn)

    # ── IF / THEN / ELSE ───────────────────────────────────────
    if ntype == "if_then_else":
        cond_if = node.get("if_cond", node.get("if", {}))
        cond_then = node.get("then_cond", node.get("then", {}))
        cond_else = node.get("else_cond", node.get("else"))
        if _eval_node(cond_if, bar_idx, value_fn):
            return _eval_node(cond_then, bar_idx, value_fn)
        if cond_else:
            return _eval_node(cond_else, bar_idx, value_fn)
        return False

    return False


def _eval_chain(children: list[dict], bar_idx: int, value_fn: ValueFn) -> bool:
    """Evaluate a list of nodes respecting per-node ``logic`` field.

    This preserves backward compatibility with the legacy flat model where
    each row has its own ``logic: "AND" | "OR"`` that chains with the *next*
    condition left-to-right.
    """
    if not children:
        return False
    result = _eval_node(children[0], bar_idx, value_fn)
    for i in range(1, len(children)):
        child = children[i]
        child_result = _eval_node(child, bar_idx, value_fn)
        logic = child.get("logic", "AND").upper()
        if logic == "OR":
            result = result or child_result
        else:
            result = result and child_result
    return result


def evaluate_condition_tree(
    rules: list[dict] | dict | None,
    bar_idx: int,
    value_fn: ValueFn,
) -> bool:
    """Top-level entry point — evaluate rules at *bar_idx*.

    *rules* may be legacy ``list[dict]`` or new tree ``dict``.
    """
    tree = normalise_rules(rules)
    return _eval_node(tree, bar_idx, value_fn)


# ---------------------------------------------------------------------------
# Direction helpers
# ---------------------------------------------------------------------------

def _infer_direction(rule: dict) -> str:
    op = rule.get("operator", ">")
    if op in ("crosses_above", ">", ">="):
        return "long"
    if op in ("crosses_below", "<", "<="):
        return "short"
    return "long"


def _direction_from_rule(rule: dict) -> str:
    explicit = rule.get("direction", "both")
    if explicit in ("long", "short"):
        return explicit
    return _infer_direction(rule)


def _direction_from_flat_rules(rules: list[dict]) -> str:
    for r in rules:
        d = r.get("direction", "both")
        if d in ("long", "short"):
            return d
    return _infer_direction(rules[0]) if rules else "long"


def _collect_leaves(node: dict) -> list[dict]:
    """Collect all leaf conditions from a tree."""
    ntype = node.get("node_type", node.get("type", "condition"))
    if ntype == "condition":
        return [node]
    if ntype == "group":
        out: list[dict] = []
        for c in node.get("children", node.get("conditions", [])):
            out.extend(_collect_leaves(c))
        return out
    if ntype == "if_then_else":
        out = []
        for key in ("if_cond", "then_cond", "else_cond", "if", "then", "else"):
            sub = node.get(key)
            if sub:
                out.extend(_collect_leaves(sub))
        return out
    return []


def evaluate_direction(
    rules: list[dict] | dict | None,
    bar_idx: int,
    value_fn: ValueFn,
) -> str:
    """Evaluate rules and return trade direction: "long", "short", or "" (no signal).

    Handles both flat (legacy) and tree (new) formats.

    For flat legacy rules with direction fields, rules are partitioned by
    direction.  All conditions in a direction group must pass (AND) for that
    direction to fire.  "both" rules are shared across all direction groups.
    """
    if rules is None or (isinstance(rules, list) and len(rules) == 0):
        return ""

    # ── Flat legacy list (no type/node_type keys) ─────────────────────
    if isinstance(rules, list) and all(
        "type" not in r and "node_type" not in r for r in rules
    ):
        return _evaluate_direction_flat(rules, bar_idx, value_fn)

    # ── Tree evaluation ──────────────────────────────────────────────
    tree = normalise_rules(rules)
    if not _eval_node(tree, bar_idx, value_fn):
        return ""

    # Determine direction from leaf conditions
    leaves = _collect_leaves(tree)
    for leaf in leaves:
        d = leaf.get("direction", "both")
        if d in ("long", "short"):
            return d
    # Infer from first leaf operator
    if leaves:
        return _infer_direction(leaves[0])
    return "long"


def _evaluate_direction_flat(
    rules: list[dict],
    bar_idx: int,
    value_fn: ValueFn,
) -> str:
    """Evaluate a flat legacy rule list partitioned by direction.

    Rules are grouped by their ``direction`` field ("long", "short", "both").
    Within each direction group, ALL conditions must pass (AND logic).
    "both" rules are appended to every direction group.

    Returns the first direction whose complete group passes:
      - "long" rules (+ "both" rules) all true  → "long"
      - "short" rules (+ "both" rules) all true → "short"
      - neither passes → ""

    If NO rule has an explicit direction, fall back to the old behaviour:
    evaluate all rules together and infer direction from operators.
    """
    long_rules: list[dict] = []
    short_rules: list[dict] = []
    both_rules: list[dict] = []

    for r in rules:
        d = r.get("direction", "both").lower()
        if d == "long":
            long_rules.append(r)
        elif d == "short":
            short_rules.append(r)
        else:
            both_rules.append(r)

    # If no rule has an explicit direction, use legacy behaviour
    if not long_rules and not short_rules:
        if all(_eval_single(r, bar_idx, value_fn) for r in rules):
            return _direction_from_flat_rules(rules)
        return ""

    # Evaluate shared "both" rules once
    both_pass = all(_eval_single(r, bar_idx, value_fn) for r in both_rules) if both_rules else True
    if not both_pass:
        return ""

    # Check long group
    if long_rules and all(_eval_single(r, bar_idx, value_fn) for r in long_rules):
        return "long"

    # Check short group
    if short_rules and all(_eval_single(r, bar_idx, value_fn) for r in short_rules):
        return "short"

    return ""


# ---------------------------------------------------------------------------
# Filter evaluation (unified)
# ---------------------------------------------------------------------------

def passes_filters(
    filters: dict,
    timestamp_ns: int | float,
    value_fn: ValueFn,
    bar_idx: int,
    *,
    daily_trade_count: int = 0,
    consecutive_losses: int = 0,
) -> bool:
    """Evaluate all trade filters.  Returns True if the bar passes all filters.

    Parameters
    ----------
    filters : dict
        The strategy's filter configuration.
    timestamp_ns : int | float
        Bar timestamp — may be nanoseconds (>4e9) or Unix seconds.
    value_fn : ValueFn
        Indicator / price value resolver.
    bar_idx : int
        Current bar index.
    daily_trade_count : int
        Trades taken so far today (for max_trades_per_day filter).
    consecutive_losses : int
        Recent consecutive losses (for consecutive_loss_pause filter).
    """
    import datetime as _dt

    if not filters:
        return True

    # ── Normalise timestamp to datetime ─────────────────────────
    ts_sec = timestamp_ns
    if isinstance(ts_sec, (int, float)) and ts_sec > 4_102_444_800:
        ts_sec = ts_sec / 1_000_000_000
    try:
        dt = _dt.datetime.fromtimestamp(float(ts_sec), tz=_dt.timezone.utc)
    except (OSError, ValueError, OverflowError):
        return True  # can't determine → let it through

    # ── Day of week ─────────────────────────────────────────────
    days = filters.get("days_of_week", [])
    if days and dt.weekday() not in days:
        return False

    # ── Time range ──────────────────────────────────────────────
    time_start = filters.get("time_start", "")
    time_end = filters.get("time_end", "")
    if time_start and time_end:
        bar_time = dt.strftime("%H:%M")
        if not (time_start <= bar_time <= time_end):
            return False

    # ── Session preset ──────────────────────────────────────────
    session_preset = filters.get("session_preset", "")
    if session_preset:
        _SESSIONS = {
            "london":  (7, 16),
            "ny":      (12, 21),
            "asia":    (0, 9),
            "london_open":  (7, 10),
            "ny_open":      (12, 15),
            "london_close": (15, 17),
        }
        bounds = _SESSIONS.get(session_preset.lower())
        if bounds:
            if not (bounds[0] <= dt.hour < bounds[1]):
                return False

    # ── Kill zone preset ────────────────────────────────────────
    kill_zone = filters.get("kill_zone_preset", "")
    if kill_zone:
        _KZ = {
            "london_open":  (7, 10),
            "ny_open":      (12, 15),
            "london_close": (15, 17),
        }
        bounds = _KZ.get(kill_zone.lower())
        if bounds:
            if not (bounds[0] <= dt.hour < bounds[1]):
                return False

    # ── ADX filter ──────────────────────────────────────────────
    min_adx = filters.get("min_adx", 0)
    max_adx = filters.get("max_adx", 0)
    if (min_adx > 0 or max_adx > 0) and bar_idx >= 0:
        adx_val = _find_indicator_value(value_fn, bar_idx, "adx")
        if adx_val is not None:
            if min_adx > 0 and adx_val < min_adx:
                return False
            if max_adx > 0 and adx_val > max_adx:
                return False

    # ── Volatility filter (ATR-based) ───────────────────────────
    min_vol = filters.get("min_volatility", 0)
    max_vol = filters.get("max_volatility", 0)
    if (min_vol > 0 or max_vol > 0) and bar_idx >= 0:
        atr_val = _find_indicator_value(value_fn, bar_idx, "atr")
        if atr_val is not None and atr_val > 0:
            if min_vol > 0 and atr_val < min_vol:
                return False
            if max_vol > 0 and atr_val > max_vol:
                return False

    # ── Trend direction filter ──────────────────────────────────
    trend_ind = filters.get("trend_filter_indicator", "")
    trend_period = filters.get("trend_filter_period", 0)
    if trend_ind and trend_period > 0 and bar_idx >= 0:
        # e.g. trend_ind = "sma_trend" — user must add this indicator
        trend_val = _try_value(value_fn, trend_ind, bar_idx)
        price_val = _try_value(value_fn, "price.close", bar_idx)
        trend_dir = filters.get("trend_filter_direction", "")
        if trend_val is not None and price_val is not None:
            if trend_dir == "long" and price_val < trend_val:
                return False
            if trend_dir == "short" and price_val > trend_val:
                return False

    # ── Spread filter ───────────────────────────────────────────
    max_spread = filters.get("max_spread_pips", 0)
    if max_spread > 0:
        spread_val = _try_value(value_fn, "spread", bar_idx)
        if spread_val is not None and spread_val > max_spread:
            return False

    # ── Max trades per day ──────────────────────────────────────
    max_daily = filters.get("max_trades_per_day", 0)
    if max_daily > 0 and daily_trade_count >= max_daily:
        return False

    # ── Consecutive loss pause ──────────────────────────────────
    loss_limit = filters.get("consecutive_loss_limit", 0)
    if loss_limit > 0 and consecutive_losses >= loss_limit:
        return False

    return True


def _find_indicator_value(
    value_fn: ValueFn, bar_idx: int, prefix: str
) -> Optional[float]:
    """Try to resolve an indicator value by common naming patterns."""
    for name in (prefix, prefix.upper(), prefix.lower(), f"{prefix}_1"):
        try:
            v = value_fn(name, bar_idx)
            if not math.isnan(v):
                return v
        except Exception:
            continue
    return None


def _try_value(value_fn: ValueFn, source: str, bar_idx: int) -> Optional[float]:
    try:
        v = value_fn(source, bar_idx)
        if not math.isnan(v):
            return v
    except Exception:
        pass
    return None
