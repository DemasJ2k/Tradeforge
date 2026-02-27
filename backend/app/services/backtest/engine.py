"""
Bar-by-bar backtesting engine.
Processes OHLCV data with strategy rules and produces trade results.
"""
import math
from dataclasses import dataclass, field
from typing import Optional

from app.services.backtest import indicators as ind


@dataclass
class Bar:
    time: float
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class Trade:
    entry_bar: int
    entry_time: float
    entry_price: float
    direction: str  # "long" or "short"
    size: float
    stop_loss: float = 0.0
    take_profit: float = 0.0
    exit_bar: Optional[int] = None
    exit_time: Optional[float] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    # Summary stats
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_profit: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    avg_trade: float = 0.0
    sharpe_ratio: float = 0.0
    expectancy: float = 0.0
    total_bars: int = 0


class BacktestEngine:
    def __init__(
        self,
        bars: list[Bar],
        strategy_config: dict,
        initial_balance: float = 10000.0,
        spread_points: float = 0.0,
        commission_per_lot: float = 0.0,
        point_value: float = 1.0,
    ):
        self.bars = bars
        self.config = strategy_config
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.spread = spread_points
        self.commission = commission_per_lot
        self.point_value = point_value

        self.indicator_values: dict[str, list[float]] = {}
        self.open_trades: list[Trade] = []
        self.closed_trades: list[Trade] = []
        self.equity_curve: list[float] = []

    def run(self) -> BacktestResult:
        """Execute the backtest."""
        self._compute_indicators()

        n = len(self.bars)
        for i in range(n):
            # Check exits first
            self._check_exits(i)

            # Check entries
            self._check_entries(i)

            # Record equity
            unrealized = sum(self._unrealized_pnl(t, i) for t in self.open_trades)
            self.equity_curve.append(self.balance + unrealized)

        # Close any remaining open trades at last bar
        for trade in list(self.open_trades):
            self._close_trade(trade, n - 1, self.bars[-1].close, "end_of_data")

        return self._build_result()

    def _compute_indicators(self):
        """Pre-compute all indicators from strategy config."""
        opens = [b.open for b in self.bars]
        highs = [b.high for b in self.bars]
        lows = [b.low for b in self.bars]
        closes = [b.close for b in self.bars]
        volumes = [b.volume for b in self.bars]
        timestamps = [b.time for b in self.bars]

        source_map = {
            "open": opens, "high": highs, "low": lows,
            "close": closes, "volume": volumes,
        }

        for indicator_cfg in self.config.get("indicators", []):
            ind_id = indicator_cfg["id"]
            ind_type = indicator_cfg["type"].upper()
            params = indicator_cfg.get("params", {})
            source = source_map.get(params.get("source", "close"), closes)

            if ind_type == "SMA":
                self.indicator_values[ind_id] = ind.sma(source, int(params.get("period", 20)))
            elif ind_type == "EMA":
                self.indicator_values[ind_id] = ind.ema(source, int(params.get("period", 20)))
            elif ind_type == "RSI":
                self.indicator_values[ind_id] = ind.rsi(source, int(params.get("period", 14)))
            elif ind_type == "ATR":
                self.indicator_values[ind_id] = ind.atr(highs, lows, closes, int(params.get("period", 14)))
            elif ind_type == "MACD":
                ml, sl, hist = ind.macd(source, int(params.get("fast", 12)), int(params.get("slow", 26)), int(params.get("signal", 9)))
                self.indicator_values[ind_id] = ml
                self.indicator_values[f"{ind_id}_signal"] = sl
                self.indicator_values[f"{ind_id}_hist"] = hist
            elif ind_type == "BOLLINGER":
                upper, middle, lower = ind.bollinger_bands(source, int(params.get("period", 20)), float(params.get("std_dev", 2.0)))
                self.indicator_values[f"{ind_id}_upper"] = upper
                self.indicator_values[ind_id] = middle
                self.indicator_values[f"{ind_id}_lower"] = lower
            elif ind_type == "STOCHASTIC":
                k, d = ind.stochastic(highs, lows, closes, int(params.get("k_period", 14)), int(params.get("d_period", 3)), int(params.get("smooth", 3)))
                self.indicator_values[ind_id] = k
                self.indicator_values[f"{ind_id}_d"] = d
            elif ind_type == "ADX":
                self.indicator_values[ind_id] = ind.adx(highs, lows, closes, int(params.get("period", 14)))
            elif ind_type == "PIVOTHIGH":
                self.indicator_values[ind_id] = ind.pivot_high(highs, int(params.get("lookback", 42)))
            elif ind_type == "PIVOTLOW":
                self.indicator_values[ind_id] = ind.pivot_low(lows, int(params.get("lookback", 42)))
            elif ind_type == "ADR":
                self.indicator_values[ind_id] = ind.adr(highs, lows, int(params.get("period", 10)), timestamps)
            elif ind_type == "VWAP":
                self.indicator_values[ind_id] = ind.vwap(highs, lows, closes, volumes, timestamps)
            elif ind_type in ("PIVOT", "PIVOT_POINTS"):
                pivots = ind.daily_pivot_points(highs, lows, closes, timestamps)
                self.indicator_values[f"{ind_id}_pp"] = pivots["pp"]
                self.indicator_values[f"{ind_id}_r1"] = pivots["r1"]
                self.indicator_values[f"{ind_id}_r2"] = pivots["r2"]
                self.indicator_values[f"{ind_id}_r3"] = pivots["r3"]
                self.indicator_values[f"{ind_id}_s1"] = pivots["s1"]
                self.indicator_values[f"{ind_id}_s2"] = pivots["s2"]
                self.indicator_values[f"{ind_id}_s3"] = pivots["s3"]
                self.indicator_values[ind_id] = pivots["pp"]  # default = pivot point

    def _get_value(self, source: str, bar_idx: int) -> float:
        """Get a value for a condition source at a given bar."""
        if source.startswith("price."):
            field = source.split(".")[1]
            bar = self.bars[bar_idx]
            return getattr(bar, field, bar.close)
        if source in self.indicator_values:
            return self.indicator_values[source][bar_idx]
        # Try as literal number
        try:
            return float(source)
        except (ValueError, TypeError):
            return float("nan")

    def _eval_condition(self, rule: dict, bar_idx: int) -> bool:
        """Evaluate a single condition row at bar_idx."""
        if bar_idx < 1:
            return False

        left_now = self._get_value(rule["left"], bar_idx)
        right_now = self._get_value(rule["right"], bar_idx)
        left_prev = self._get_value(rule["left"], bar_idx - 1)
        right_prev = self._get_value(rule["right"], bar_idx - 1)

        if any(math.isnan(v) for v in [left_now, right_now, left_prev, right_prev]):
            return False

        op = rule.get("operator", ">")

        if op == "crosses_above":
            return left_prev <= right_prev and left_now > right_now
        elif op == "crosses_below":
            return left_prev >= right_prev and left_now < right_now
        elif op == ">":
            return left_now > right_now
        elif op == "<":
            return left_now < right_now
        elif op == ">=":
            return left_now >= right_now
        elif op == "<=":
            return left_now <= right_now
        elif op == "==":
            return abs(left_now - right_now) < 1e-10
        return False

    def _eval_rules(self, rules: list[dict], bar_idx: int) -> bool:
        """Evaluate a list of condition rows with AND/OR logic."""
        if not rules:
            return False

        result = self._eval_condition(rules[0], bar_idx)
        for i in range(1, len(rules)):
            cond_result = self._eval_condition(rules[i], bar_idx)
            logic = rules[i].get("logic", "AND").upper()
            if logic == "OR":
                result = result or cond_result
            else:
                result = result and cond_result
        return result

    def _check_entries(self, bar_idx: int):
        """Check entry rules and open trades."""
        risk = self.config.get("risk_params", {})
        max_pos = risk.get("max_positions", 1)

        if len(self.open_trades) >= max_pos:
            return

        # Check filters
        if not self._passes_filters(bar_idx):
            return

        entry_rules = self.config.get("entry_rules", [])
        direction = self._eval_rules_with_direction(entry_rules, bar_idx)
        if direction:
            self._open_trade(bar_idx, direction)

    def _eval_rules_with_direction(self, rules: list[dict], bar_idx: int) -> str:
        """Evaluate entry rules and determine trade direction.
        Returns 'long', 'short', or '' (no signal).

        Each rule can carry a 'direction' field ('long', 'short', 'both').
        - Rules with direction='long' only fire for long trades.
        - Rules with direction='short' only fire for short trades.
        - Rules with direction='both' fire for either (direction inferred from operator).

        For OR-connected rules, checks each rule independently and returns
        the direction of the first matching rule.
        For AND-connected rules, all must pass; direction comes from
        the first rule that specifies one, otherwise inferred."""
        if not rules:
            return ""

        # Check if rules use OR logic — evaluate each independently
        has_or = any(r.get("logic", "AND").upper() == "OR" for r in rules)

        if has_or:
            # For OR-connected rules, find the first matching one
            for rule in rules:
                if self._eval_condition(rule, bar_idx):
                    return self._direction_from_rule(rule)
            return ""
        else:
            # AND logic: all must pass
            if self._eval_rules(rules, bar_idx):
                return self._direction_from_rules(rules)
            return ""

    def _direction_from_rule(self, rule: dict) -> str:
        """Get trade direction from a single rule.
        If rule has an explicit direction ('long'/'short'), use it.
        If 'both', infer from operator."""
        explicit = rule.get("direction", "both")
        if explicit in ("long", "short"):
            return explicit
        return self._infer_direction(rule)

    def _direction_from_rules(self, rules: list[dict]) -> str:
        """Determine direction from a set of AND-connected rules.
        Returns the first explicit direction found, else infers from first rule."""
        for r in rules:
            d = r.get("direction", "both")
            if d in ("long", "short"):
                return d
        # No explicit direction — infer from first rule's operator
        return self._infer_direction(rules[0]) if rules else "long"

    def _infer_direction(self, rule: dict) -> str:
        """Infer trade direction from a rule's operator and operands."""
        op = rule.get("operator", ">")
        # crosses_above / > typically means bullish (long)
        # crosses_below / < typically means bearish (short)
        if op in ("crosses_above", ">", ">="):
            return "long"
        elif op in ("crosses_below", "<", "<="):
            return "short"
        return "long"  # default

    def _passes_filters(self, bar_idx: int) -> bool:
        """Check time, day, ADX, and volatility filters."""
        filters = self.config.get("filters", {})
        if not filters:
            return True

        bar = self.bars[bar_idx]

        # Day of week filter
        days = filters.get("days_of_week", [])
        if days:
            import datetime
            dt = datetime.datetime.fromtimestamp(bar.time, tz=datetime.timezone.utc)
            if dt.weekday() not in days:
                return False

        # Time filter
        time_start = filters.get("time_start", "")
        time_end = filters.get("time_end", "")
        if time_start and time_end:
            import datetime
            dt = datetime.datetime.fromtimestamp(bar.time, tz=datetime.timezone.utc)
            bar_time = dt.strftime("%H:%M")
            if not (time_start <= bar_time <= time_end):
                return False

        # ADX filter — look up any ADX indicator value
        min_adx = filters.get("min_adx", 0)
        max_adx = filters.get("max_adx", 0)
        if min_adx > 0 or max_adx > 0:
            adx_val = None
            for key, vals in self.indicator_values.items():
                if "adx" in key.lower() and "_" not in key.split("adx")[-1]:
                    # Only match the main ADX line, not sub-keys
                    if bar_idx < len(vals) and not math.isnan(vals[bar_idx]):
                        adx_val = vals[bar_idx]
                        break
            if adx_val is not None:
                if min_adx > 0 and adx_val < min_adx:
                    return False
                if max_adx > 0 and adx_val > max_adx:
                    return False

        # Volatility filter (uses ATR value)
        min_vol = filters.get("min_volatility", 0)
        max_vol = filters.get("max_volatility", 0)
        if min_vol > 0 or max_vol > 0:
            atr_val = self._get_atr_value(bar_idx)
            if atr_val > 0:
                if min_vol > 0 and atr_val < min_vol:
                    return False
                if max_vol > 0 and atr_val > max_vol:
                    return False

        return True

    def _open_trade(self, bar_idx: int, direction: str):
        """Open a new trade."""
        bar = self.bars[bar_idx]
        risk = self.config.get("risk_params", {})

        entry_price = bar.close + (self.spread / 2 if direction == "long" else -self.spread / 2)
        size = risk.get("position_size_value", 0.01)

        # Calculate SL/TP
        sl_type = risk.get("stop_loss_type", "fixed_pips")
        sl_val = risk.get("stop_loss_value", 50)
        tp_type = risk.get("take_profit_type", "fixed_pips")
        tp_val = risk.get("take_profit_value", 100)

        atr_val = self._get_atr_value(bar_idx)

        if direction == "long":
            sl = self._calc_sl_tp(entry_price, sl_type, sl_val, atr_val, is_sl=True, is_long=True, bar_idx=bar_idx)
            tp = self._calc_sl_tp(entry_price, tp_type, tp_val, atr_val, is_sl=False, is_long=True, bar_idx=bar_idx)
            # RR ratio
            if tp_type == "rr_ratio" and sl > 0:
                risk_dist = entry_price - sl
                tp = entry_price + risk_dist * tp_val
        else:
            sl = self._calc_sl_tp(entry_price, sl_type, sl_val, atr_val, is_sl=True, is_long=False, bar_idx=bar_idx)
            tp = self._calc_sl_tp(entry_price, tp_type, tp_val, atr_val, is_sl=False, is_long=False, bar_idx=bar_idx)
            if tp_type == "rr_ratio" and sl > 0:
                risk_dist = sl - entry_price
                tp = entry_price - risk_dist * tp_val

        # TP2 / lot split support
        tp2_type = risk.get("take_profit_2_type", "")
        tp2_val = risk.get("take_profit_2_value", 0)
        lot_split = risk.get("lot_split", [])  # e.g. [0.6, 0.4]
        tp2 = 0.0
        if tp2_type and tp2_val > 0:
            tp2 = self._calc_sl_tp(entry_price, tp2_type, tp2_val, atr_val,
                                   is_sl=False, is_long=(direction == "long"), bar_idx=bar_idx)

        if lot_split and len(lot_split) == 2 and tp2 > 0:
            # Split into two trades: TP1 portion + TP2 portion
            size1 = round(size * lot_split[0], 4)
            size2 = round(size * lot_split[1], 4)
            if size1 > 0:
                t1 = Trade(entry_bar=bar_idx, entry_time=bar.time,
                           entry_price=entry_price, direction=direction,
                           size=size1, stop_loss=sl, take_profit=tp)
                self.open_trades.append(t1)
            if size2 > 0:
                t2 = Trade(entry_bar=bar_idx, entry_time=bar.time,
                           entry_price=entry_price, direction=direction,
                           size=size2, stop_loss=sl, take_profit=tp2)
                self.open_trades.append(t2)
        else:
            trade = Trade(
                entry_bar=bar_idx,
                entry_time=bar.time,
                entry_price=entry_price,
                direction=direction,
                size=size,
                stop_loss=sl,
                take_profit=tp,
            )
            self.open_trades.append(trade)

    def _get_atr_value(self, bar_idx: int) -> float:
        """Get ATR value if available."""
        for key, vals in self.indicator_values.items():
            if "atr" in key.lower() and bar_idx < len(vals):
                v = vals[bar_idx]
                if not math.isnan(v):
                    return v
        # Fallback: compute from recent bars
        if bar_idx >= 14:
            highs = [self.bars[i].high for i in range(bar_idx - 13, bar_idx + 1)]
            lows = [self.bars[i].low for i in range(bar_idx - 13, bar_idx + 1)]
            closes = [self.bars[i].close for i in range(bar_idx - 13, bar_idx + 1)]
            atr_vals = ind.atr(highs, lows, closes, 14)
            if atr_vals and not math.isnan(atr_vals[-1]):
                return atr_vals[-1]
        return 0.0

    def _get_adr_value(self, bar_idx: int) -> float:
        """Get ADR value if available from indicators."""
        for key, vals in self.indicator_values.items():
            if "adr" in key.lower() and bar_idx < len(vals):
                v = vals[bar_idx]
                if not math.isnan(v):
                    return v
        # Fallback: compute daily range from recent bars grouped by date
        import datetime as _dt
        if bar_idx < 1:
            return 0.0
        # Group bars by calendar date to compute daily ranges
        day_ranges: list[float] = []
        day_high = -math.inf
        day_low = math.inf
        prev_ord = -1
        start = max(0, bar_idx - 1500)  # look back enough bars to get 10+ days
        for i in range(start, bar_idx + 1):
            dt = _dt.datetime.fromtimestamp(self.bars[i].time, tz=_dt.timezone.utc)
            date_ord = dt.toordinal()
            if prev_ord == -1:
                prev_ord = date_ord
                day_high = self.bars[i].high
                day_low = self.bars[i].low
            elif date_ord != prev_ord:
                dr = day_high - day_low
                if dr > 0:
                    day_ranges.append(dr)
                prev_ord = date_ord
                day_high = self.bars[i].high
                day_low = self.bars[i].low
            else:
                if self.bars[i].high > day_high:
                    day_high = self.bars[i].high
                if self.bars[i].low < day_low:
                    day_low = self.bars[i].low
        if not day_ranges:
            # Absolute fallback: use bar range (legacy)
            lookback = min(10, bar_idx)
            total = sum(self.bars[i].high - self.bars[i].low for i in range(bar_idx - lookback + 1, bar_idx + 1))
            return total / lookback
        period = min(10, len(day_ranges))
        return sum(day_ranges[-period:]) / period

    def _calc_sl_tp(self, entry: float, sl_type: str, value: float, atr_val: float,
                     is_sl: bool, is_long: bool, bar_idx: int = 0) -> float:
        """Calculate stop loss or take profit price."""
        if value <= 0:
            return 0.0

        if sl_type == "fixed_pips":
            dist = value * self.point_value
        elif sl_type == "atr_multiple":
            dist = value * atr_val if atr_val > 0 else value
        elif sl_type == "atr_pct" or sl_type == "adr_pct":
            # ADR-based: value is a percentage of ADR
            adr_val = self._get_adr_value(bar_idx)
            dist = adr_val * value / 100 if adr_val > 0 else value * self.point_value
        elif sl_type == "percent":
            dist = entry * value / 100
        elif sl_type == "rr_ratio":
            return 0.0  # Handled by caller
        else:
            dist = value * self.point_value

        if is_long:
            return entry - dist if is_sl else entry + dist
        else:
            return entry + dist if is_sl else entry - dist

    def _check_exits(self, bar_idx: int):
        """Check exits: SL/TP hit, exit rules, trailing stop."""
        bar = self.bars[bar_idx]

        for trade in list(self.open_trades):
            # Check SL
            if trade.stop_loss > 0:
                if trade.direction == "long" and bar.low <= trade.stop_loss:
                    self._close_trade(trade, bar_idx, trade.stop_loss, "stop_loss")
                    continue
                elif trade.direction == "short" and bar.high >= trade.stop_loss:
                    self._close_trade(trade, bar_idx, trade.stop_loss, "stop_loss")
                    continue

            # Check TP
            if trade.take_profit > 0:
                if trade.direction == "long" and bar.high >= trade.take_profit:
                    self._close_trade(trade, bar_idx, trade.take_profit, "take_profit")
                    continue
                elif trade.direction == "short" and bar.low <= trade.take_profit:
                    self._close_trade(trade, bar_idx, trade.take_profit, "take_profit")
                    continue

            # Check exit rules
            exit_rules = self.config.get("exit_rules", [])
            if exit_rules and self._eval_rules(exit_rules, bar_idx):
                self._close_trade(trade, bar_idx, bar.close, "exit_signal")
                continue

            # Trailing stop
            risk = self.config.get("risk_params", {})
            if risk.get("trailing_stop") and risk.get("trailing_stop_value", 0) > 0:
                trail_type = risk.get("trailing_stop_type", "fixed_pips")
                trail_val = risk["trailing_stop_value"]
                if trail_type == "atr_multiple":
                    atr_v = self._get_atr_value(bar_idx)
                    trail_dist = trail_val * atr_v if atr_v > 0 else trail_val
                else:
                    trail_dist = trail_val * self.point_value
                if trade.direction == "long":
                    new_sl = bar.high - trail_dist
                    if new_sl > trade.stop_loss:
                        trade.stop_loss = new_sl
                else:
                    new_sl = bar.low + trail_dist
                    if trade.stop_loss == 0 or new_sl < trade.stop_loss:
                        trade.stop_loss = new_sl

    def _close_trade(self, trade: Trade, bar_idx: int, exit_price: float, reason: str):
        """Close a trade and calculate PnL."""
        bar = self.bars[bar_idx]
        trade.exit_bar = bar_idx
        trade.exit_time = bar.time
        trade.exit_price = exit_price
        trade.exit_reason = reason

        if trade.direction == "long":
            trade.pnl = (exit_price - trade.entry_price) * trade.size * self.point_value
        else:
            trade.pnl = (trade.entry_price - exit_price) * trade.size * self.point_value

        # Subtract commission
        trade.pnl -= self.commission * trade.size * 2  # round trip

        if trade.entry_price > 0:
            trade.pnl_pct = trade.pnl / (trade.entry_price * trade.size * self.point_value) * 100

        self.balance += trade.pnl

        if trade in self.open_trades:
            self.open_trades.remove(trade)
        self.closed_trades.append(trade)

        # Breakeven on TP1: if this was a TP hit and breakeven_on_tp1 is enabled,
        # move sibling trade's SL to entry price (breakeven)
        risk = self.config.get("risk_params", {})
        if reason == "take_profit" and risk.get("breakeven_on_tp1", False):
            for sibling in self.open_trades:
                if (sibling.entry_bar == trade.entry_bar
                        and sibling.entry_price == trade.entry_price
                        and sibling.direction == trade.direction):
                    sibling.stop_loss = sibling.entry_price

    def _unrealized_pnl(self, trade: Trade, bar_idx: int) -> float:
        """Calculate unrealized PnL for an open trade."""
        bar = self.bars[bar_idx]
        if trade.direction == "long":
            return (bar.close - trade.entry_price) * trade.size * self.point_value
        else:
            return (trade.entry_price - bar.close) * trade.size * self.point_value

    def _build_result(self) -> BacktestResult:
        """Build the result summary from closed trades."""
        result = BacktestResult()
        result.trades = self.closed_trades
        result.equity_curve = self.equity_curve
        result.total_bars = len(self.bars)
        result.total_trades = len(self.closed_trades)

        if result.total_trades == 0:
            return result

        wins = [t for t in self.closed_trades if t.pnl > 0]
        losses = [t for t in self.closed_trades if t.pnl <= 0]

        result.winning_trades = len(wins)
        result.losing_trades = len(losses)
        result.win_rate = len(wins) / result.total_trades * 100

        result.gross_profit = sum(t.pnl for t in wins)
        result.gross_loss = sum(t.pnl for t in losses)
        result.net_profit = result.gross_profit + result.gross_loss

        result.profit_factor = abs(result.gross_profit / result.gross_loss) if result.gross_loss != 0 else float("inf")

        result.avg_win = result.gross_profit / len(wins) if wins else 0
        result.avg_loss = result.gross_loss / len(losses) if losses else 0
        result.largest_win = max((t.pnl for t in wins), default=0)
        result.largest_loss = min((t.pnl for t in losses), default=0)
        result.avg_trade = result.net_profit / result.total_trades

        # Expectancy
        result.expectancy = (result.win_rate / 100 * result.avg_win) + ((1 - result.win_rate / 100) * result.avg_loss)

        # Max drawdown
        peak = self.initial_balance
        max_dd = 0
        max_dd_pct = 0
        for eq in self.equity_curve:
            if eq > peak:
                peak = eq
            dd = peak - eq
            dd_pct = dd / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
        result.max_drawdown = max_dd
        result.max_drawdown_pct = max_dd_pct

        # Sharpe ratio (simplified: using trade returns)
        if result.total_trades > 1:
            returns = [t.pnl for t in self.closed_trades]
            avg_ret = sum(returns) / len(returns)
            std_ret = math.sqrt(sum((r - avg_ret) ** 2 for r in returns) / (len(returns) - 1))
            result.sharpe_ratio = (avg_ret / std_ret) * math.sqrt(252) if std_ret > 0 else 0

        return result
