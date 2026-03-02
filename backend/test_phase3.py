"""Phase 3 — Strategy Builder Overhaul Tests.

Covers:
  3A: Condition engine (normalise, evaluate, direction, filters)
  3C: Candlestick patterns (16 detectors)
  3D: RiskParams schema (TP3, buffer)
  3E: FilterConfig schema (expanded fields)
  3F: ConditionGroup schema (nested tree)
"""

import math
import pytest

# ── 3A: Condition Engine ─────────────────────────────────────────────

from app.services.backtest.condition_engine import (
    normalise_rules,
    evaluate_condition_tree,
    evaluate_direction,
    passes_filters,
    _eval_single,
    _eval_node,
)


def _make_value_fn(data: dict[str, list[float]]):
    """Create a value function from a dict of source → values."""
    def fn(source: str, bar_idx: int) -> float:
        if source in data and 0 <= bar_idx < len(data[source]):
            return data[source][bar_idx]
        try:
            return float(source)
        except (ValueError, TypeError):
            return float("nan")
    return fn


class TestNormaliseRules:
    def test_empty_list(self):
        result = normalise_rules([])
        assert result == {"node_type": "group", "group_logic": "AND", "children": []}

    def test_flat_list_wrapped(self):
        rules = [
            {"left": "rsi", "operator": ">", "right": "70", "logic": "AND"},
        ]
        result = normalise_rules(rules)
        assert result["node_type"] == "group"
        assert len(result["children"]) == 1
        assert result["children"][0]["node_type"] == "condition"
        assert result["children"][0]["left"] == "rsi"

    def test_already_tree(self):
        tree = {"node_type": "group", "group_logic": "OR", "children": []}
        result = normalise_rules(tree)
        assert result == tree

    def test_single_dict_wrapped(self):
        rule = {"left": "ema", "operator": "crosses_above", "right": "sma"}
        result = normalise_rules(rule)
        assert result["node_type"] == "group"
        assert len(result["children"]) == 1


class TestEvalSingle:
    def test_greater_than(self):
        data = {"rsi": [30.0, 50.0, 75.0], "50": [50.0, 50.0, 50.0]}
        vf = _make_value_fn(data)
        rule = {"left": "rsi", "operator": ">", "right": "50"}
        assert _eval_single(rule, 2, vf) is True
        assert _eval_single(rule, 1, vf) is False

    def test_crosses_above(self):
        data = {"ema": [10.0, 19.0, 21.0], "sma": [20.0, 20.0, 20.0]}
        vf = _make_value_fn(data)
        rule = {"left": "ema", "operator": "crosses_above", "right": "sma"}
        assert _eval_single(rule, 2, vf) is True
        assert _eval_single(rule, 1, vf) is False

    def test_crosses_below(self):
        data = {"ema": [25.0, 21.0, 19.0], "sma": [20.0, 20.0, 20.0]}
        vf = _make_value_fn(data)
        rule = {"left": "ema", "operator": "crosses_below", "right": "sma"}
        assert _eval_single(rule, 2, vf) is True

    def test_less_than(self):
        data = {"rsi": [30.0]}
        vf = _make_value_fn(data)
        rule = {"left": "rsi", "operator": "<", "right": "50"}
        assert _eval_single(rule, 0, vf) is True

    def test_equals(self):
        data = {"a": [42.0], "b": [42.0]}
        vf = _make_value_fn(data)
        rule = {"left": "a", "operator": "==", "right": "b"}
        assert _eval_single(rule, 0, vf) is True

    def test_nan_returns_false(self):
        data = {"a": [float("nan")]}
        vf = _make_value_fn(data)
        rule = {"left": "a", "operator": ">", "right": "0"}
        assert _eval_single(rule, 0, vf) is False


class TestEvalNode:
    def test_group_and(self):
        data = {"rsi": [0, 0, 75.0], "ema": [0, 19, 21], "sma": [0, 20, 20]}
        vf = _make_value_fn(data)
        node = {
            "node_type": "group",
            "group_logic": "AND",
            "children": [
                {"node_type": "condition", "left": "rsi", "operator": ">", "right": "50"},
                {"node_type": "condition", "left": "ema", "operator": "crosses_above", "right": "sma"},
            ],
        }
        assert _eval_node(node, 2, vf) is True

    def test_group_or(self):
        data = {"rsi": [0, 0, 40.0], "ema": [0, 19, 21], "sma": [0, 20, 20]}
        vf = _make_value_fn(data)
        node = {
            "node_type": "group",
            "group_logic": "OR",
            "children": [
                {"node_type": "condition", "left": "rsi", "operator": ">", "right": "50"},
                {"node_type": "condition", "left": "ema", "operator": "crosses_above", "right": "sma"},
            ],
        }
        assert _eval_node(node, 2, vf) is True  # ema cross triggers OR

    def test_if_then_else(self):
        data = {"rsi": [0, 0, 75.0], "ema": [0, 0, 21], "sma": [0, 0, 20]}
        vf = _make_value_fn(data)
        node = {
            "node_type": "if_then_else",
            "if_cond": {"node_type": "condition", "left": "rsi", "operator": ">", "right": "50"},
            "then_cond": {"node_type": "condition", "left": "ema", "operator": ">", "right": "sma"},
            "else_cond": {"node_type": "condition", "left": "rsi", "operator": "<", "right": "30"},
        }
        assert _eval_node(node, 2, vf) is True  # if true → then true

    def test_if_then_else_takes_else(self):
        data = {"rsi": [0, 0, 25.0]}
        vf = _make_value_fn(data)
        node = {
            "node_type": "if_then_else",
            "if_cond": {"node_type": "condition", "left": "rsi", "operator": ">", "right": "50"},
            "then_cond": {"node_type": "condition", "left": "rsi", "operator": ">", "right": "90"},
            "else_cond": {"node_type": "condition", "left": "rsi", "operator": "<", "right": "30"},
        }
        assert _eval_node(node, 2, vf) is True  # if false → else true


class TestEvaluateConditionTree:
    def test_legacy_flat_list(self):
        data = {"rsi": [0, 0, 75.0]}
        vf = _make_value_fn(data)
        rules = [{"left": "rsi", "operator": ">", "right": "50", "logic": "AND"}]
        assert evaluate_condition_tree(rules, 2, vf) is True

    def test_empty_rules(self):
        vf = _make_value_fn({})
        assert evaluate_condition_tree([], 0, vf) is False

    def test_tree_format(self):
        data = {"rsi": [0, 0, 75.0]}
        vf = _make_value_fn(data)
        tree = {
            "node_type": "group",
            "group_logic": "AND",
            "children": [
                {"node_type": "condition", "left": "rsi", "operator": ">", "right": "50"},
            ],
        }
        assert evaluate_condition_tree(tree, 2, vf) is True


class TestEvaluateDirection:
    def test_explicit_long(self):
        data = {"rsi": [0, 0, 75.0]}
        vf = _make_value_fn(data)
        rules = [{"left": "rsi", "operator": ">", "right": "50", "direction": "long"}]
        assert evaluate_direction(rules, 2, vf) == "long"

    def test_explicit_short(self):
        data = {"rsi": [0, 0, 25.0]}
        vf = _make_value_fn(data)
        rules = [{"left": "rsi", "operator": "<", "right": "50", "direction": "short"}]
        assert evaluate_direction(rules, 2, vf) == "short"

    def test_inferred_long_from_crosses_above(self):
        data = {"ema": [0, 19, 21], "sma": [0, 20, 20]}
        vf = _make_value_fn(data)
        rules = [{"left": "ema", "operator": "crosses_above", "right": "sma", "direction": "both"}]
        assert evaluate_direction(rules, 2, vf) == "long"

    def test_no_signal(self):
        data = {"rsi": [0, 0, 40.0]}
        vf = _make_value_fn(data)
        rules = [{"left": "rsi", "operator": ">", "right": "50"}]
        assert evaluate_direction(rules, 2, vf) == ""


class TestPassesFilters:
    def test_empty_filters(self):
        vf = _make_value_fn({})
        assert passes_filters({}, 0, vf, 0) is True

    def test_day_of_week_filter(self):
        vf = _make_value_fn({})
        # 2025-01-06 = Monday (weekday 0)
        ts = 1736121600  # 2025-01-06 00:00:00 UTC
        assert passes_filters({"days_of_week": [0]}, ts, vf, 0) is True
        assert passes_filters({"days_of_week": [1, 2, 3]}, ts, vf, 0) is False

    def test_time_filter(self):
        vf = _make_value_fn({})
        # 2025-01-06 10:30 UTC
        ts = 1736121600 + 10 * 3600 + 30 * 60
        assert passes_filters({"time_start": "08:00", "time_end": "16:00"}, ts, vf, 0) is True
        assert passes_filters({"time_start": "12:00", "time_end": "16:00"}, ts, vf, 0) is False

    def test_adx_filter(self):
        data = {"adx": [25.0]}
        vf = _make_value_fn(data)
        assert passes_filters({"min_adx": 20}, 0, vf, 0) is True
        assert passes_filters({"min_adx": 30}, 0, vf, 0) is False
        assert passes_filters({"max_adx": 30}, 0, vf, 0) is True
        assert passes_filters({"max_adx": 20}, 0, vf, 0) is False

    def test_max_trades_per_day(self):
        vf = _make_value_fn({})
        assert passes_filters({"max_trades_per_day": 3}, 0, vf, 0, daily_trade_count=2) is True
        assert passes_filters({"max_trades_per_day": 3}, 0, vf, 0, daily_trade_count=3) is False

    def test_consecutive_loss_limit(self):
        vf = _make_value_fn({})
        assert passes_filters({"consecutive_loss_limit": 3}, 0, vf, 0, consecutive_losses=2) is True
        assert passes_filters({"consecutive_loss_limit": 3}, 0, vf, 0, consecutive_losses=3) is False


# ── 3C: Candlestick Patterns ────────────────────────────────────────

from app.services.backtest.patterns import (
    detect_pattern,
    PATTERN_CATALOGUE,
    engulfing,
    pin_bar,
    doji,
    hammer,
    inverted_hammer,
    shooting_star,
    morning_star,
    evening_star,
    inside_bar,
    outside_bar,
    three_white_soldiers,
    three_black_crows,
    harami,
    tweezer_top,
    tweezer_bottom,
    spinning_top,
)


class TestPatternCatalogue:
    def test_all_16_patterns_present(self):
        expected = [
            "engulfing", "pin_bar", "doji", "hammer", "inverted_hammer",
            "shooting_star", "morning_star", "evening_star", "inside_bar",
            "outside_bar", "three_white_soldiers", "three_black_crows",
            "harami", "tweezer_top", "tweezer_bottom", "spinning_top",
        ]
        for name in expected:
            assert name in PATTERN_CATALOGUE, f"Pattern {name} missing from catalogue"

    def test_detect_pattern_dispatch(self):
        opens = [100.0, 105.0]
        highs = [110.0, 115.0]
        lows = [95.0, 100.0]
        closes = [105.0, 110.0]
        result = detect_pattern("engulfing", opens, highs, lows, closes)
        assert len(result) == 2

    def test_unknown_pattern_raises(self):
        with pytest.raises(KeyError):
            detect_pattern("nonexistent_pattern", [], [], [], [])


class TestEngulfing:
    def test_bullish_engulfing(self):
        # Bar 0: bearish (open > close), Bar 1: bullish engulfing
        opens = [110.0, 95.0]
        highs = [115.0, 115.0]
        lows = [95.0, 90.0]
        closes = [100.0, 112.0]
        result = engulfing(opens, highs, lows, closes)
        assert result[1] == 1.0  # bullish

    def test_bearish_engulfing(self):
        # Bar 0: bullish, Bar 1: bearish engulfing
        opens = [100.0, 112.0]
        highs = [110.0, 115.0]
        lows = [95.0, 90.0]
        closes = [108.0, 98.0]
        result = engulfing(opens, highs, lows, closes)
        assert result[1] == -1.0  # bearish


class TestPinBar:
    def test_bullish_pin(self):
        # Long lower wick, small body at top
        opens = [100.0]
        highs = [101.0]
        lows = [90.0]
        closes = [100.5]
        result = pin_bar(opens, highs, lows, closes)
        assert result[0] == 1.0

    def test_bearish_pin(self):
        # Long upper wick, small body at bottom
        opens = [100.0]
        highs = [110.0]
        lows = [99.0]
        closes = [99.5]
        result = pin_bar(opens, highs, lows, closes)
        assert result[0] == -1.0


class TestDoji:
    def test_doji_detected(self):
        opens = [100.0]
        highs = [105.0]
        lows = [95.0]
        closes = [100.1]  # tiny body relative to range
        result = doji(opens, highs, lows, closes)
        assert result[0] == 1.0


class TestHammer:
    def test_hammer_detected(self):
        opens = [100.0]
        highs = [100.8]  # tiny upper wick (0.3 < body 0.5)
        lows = [90.0]    # long lower wick
        closes = [100.5]
        result = hammer(opens, highs, lows, closes)
        assert result[0] == 1.0


class TestInsideBar:
    def test_inside_bar_detected(self):
        opens = [100.0, 102.0]
        highs = [110.0, 108.0]  # bar 1 high < bar 0 high
        lows = [90.0, 92.0]     # bar 1 low > bar 0 low
        closes = [105.0, 103.0]
        result = inside_bar(opens, highs, lows, closes)
        assert result[1] == 1.0


class TestOutsideBar:
    def test_outside_bar_bullish(self):
        opens = [102.0, 89.0]
        highs = [108.0, 112.0]
        lows = [92.0, 88.0]
        closes = [103.0, 110.0]
        result = outside_bar(opens, highs, lows, closes)
        assert result[1] == 1.0

    def test_outside_bar_bearish(self):
        opens = [102.0, 111.0]
        highs = [108.0, 112.0]
        lows = [92.0, 88.0]
        closes = [103.0, 90.0]
        result = outside_bar(opens, highs, lows, closes)
        assert result[1] == -1.0


class TestHarami:
    def test_bullish_harami(self):
        # Bar 0: large bearish, Bar 1: small bullish inside bar 0's body
        opens = [110.0, 101.0]
        highs = [112.0, 103.0]
        lows = [98.0, 100.0]
        closes = [100.0, 102.0]
        result = harami(opens, highs, lows, closes)
        assert result[1] == 1.0


class TestMorningEvening:
    def test_morning_star(self):
        # Bar 0: large bearish, Bar 1: small body, Bar 2: large bullish closing above midpoint of bar 0
        opens = [110.0, 100.0, 101.0]
        highs = [112.0, 101.0, 108.0]
        lows = [99.0, 99.0, 100.0]
        closes = [100.0, 100.5, 107.0]
        result = morning_star(opens, highs, lows, closes)
        assert result[2] == 1.0

    def test_evening_star(self):
        # Bar 0: large bullish, Bar 1: small body, Bar 2: large bearish
        opens = [100.0, 110.0, 110.0]
        highs = [112.0, 111.0, 111.0]
        lows = [99.0, 109.0, 100.0]
        closes = [110.0, 110.5, 103.0]
        result = evening_star(opens, highs, lows, closes)
        assert result[2] == -1.0


class TestSpinningTop:
    def test_spinning_top_detected(self):
        opens = [100.0]
        highs = [108.0]
        lows = [92.0]
        closes = [101.0]  # small body, roughly equal wicks
        result = spinning_top(opens, highs, lows, closes)
        assert result[0] == 1.0


# ── 3D/3E/3F: Schema Tests ──────────────────────────────────────────

from app.schemas.strategy import (
    ConditionRow,
    ConditionGroup,
    RiskParams,
    FilterConfig,
)


class TestConditionGroupSchema:
    def test_leaf_condition(self):
        cg = ConditionGroup(
            node_type="condition",
            left="rsi",
            operator=">",
            right="70",
        )
        assert cg.node_type == "condition"
        assert cg.left == "rsi"

    def test_group_node(self):
        cg = ConditionGroup(
            node_type="group",
            group_logic="OR",
            children=[
                ConditionGroup(node_type="condition", left="a", operator=">", right="b"),
                ConditionGroup(node_type="condition", left="c", operator="<", right="d"),
            ],
        )
        assert cg.node_type == "group"
        assert len(cg.children) == 2

    def test_if_then_else_node(self):
        cg = ConditionGroup(
            node_type="if_then_else",
            if_cond=ConditionGroup(node_type="condition", left="rsi", operator=">", right="50"),
            then_cond=ConditionGroup(node_type="condition", left="ema", operator=">", right="sma"),
            else_cond=ConditionGroup(node_type="condition", left="rsi", operator="<", right="30"),
        )
        assert cg.node_type == "if_then_else"
        assert cg.if_cond.left == "rsi"
        assert cg.then_cond.left == "ema"


class TestRiskParamsSchema:
    def test_tp3_fields(self):
        rp = RiskParams(
            take_profit_3_type="fixed_pips",
            take_profit_3_value=200.0,
            lot_split=[0.5, 0.3, 0.2],
        )
        assert rp.take_profit_3_type == "fixed_pips"
        assert rp.take_profit_3_value == 200.0
        assert len(rp.lot_split) == 3

    def test_sl_buffer(self):
        rp = RiskParams(stop_loss_buffer_pips=5.0)
        assert rp.stop_loss_buffer_pips == 5.0

    def test_move_sl_to_tp1_on_tp2(self):
        rp = RiskParams(move_sl_to_tp1_on_tp2=True)
        assert rp.move_sl_to_tp1_on_tp2 is True

    def test_structure_sl_type(self):
        rp = RiskParams(stop_loss_type="structure")
        assert rp.stop_loss_type == "structure"

    def test_defaults(self):
        rp = RiskParams()
        assert rp.take_profit_3_type == ""
        assert rp.take_profit_3_value == 0.0
        assert rp.stop_loss_buffer_pips == 0.0
        assert rp.move_sl_to_tp1_on_tp2 is False


class TestFilterConfigSchema:
    def test_new_filter_fields(self):
        fc = FilterConfig(
            session_preset="london",
            kill_zone_preset="ny_open",
            trend_filter_indicator="EMA",
            trend_filter_period=200,
            max_spread_pips=3.5,
            max_trades_per_day=5,
            consecutive_loss_limit=3,
        )
        assert fc.session_preset == "london"
        assert fc.kill_zone_preset == "ny_open"
        assert fc.trend_filter_indicator == "EMA"
        assert fc.trend_filter_period == 200
        assert fc.max_spread_pips == 3.5
        assert fc.max_trades_per_day == 5
        assert fc.consecutive_loss_limit == 3

    def test_defaults(self):
        fc = FilterConfig()
        assert fc.session_preset == ""
        assert fc.kill_zone_preset == ""
        assert fc.trend_filter_indicator == ""
        assert fc.trend_filter_period == 0
        assert fc.max_spread_pips == 0.0
        assert fc.max_trades_per_day == 0
        assert fc.consecutive_loss_limit == 0
