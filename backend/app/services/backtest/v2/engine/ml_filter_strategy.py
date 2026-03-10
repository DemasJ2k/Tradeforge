"""
ML-enhanced strategy wrapper for V2 backtest engine.

Wraps any existing StrategyBase and intercepts trade signals,
running them through the ML signal filter and/or regime detector
before allowing execution.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

from app.services.backtest.v2.engine.events import BarEvent, FillEvent
from app.services.backtest.v2.engine.strategy_base import StrategyBase, StrategyContext
from app.services.backtest.v2.engine.order import Order, OrderSide

logger = logging.getLogger(__name__)


class MLFilterStrategy(StrategyBase):
    """Wraps an inner strategy and filters its signals through ML models.

    On each bar:
    1. Calls inner_strategy.on_bar() which queues orders
    2. Intercepts the order queue
    3. For each entry order, runs ML filter and/or regime check
    4. Only allows orders that pass the ML filter

    Tracks:
    - total_signals: how many entry signals the inner strategy generated
    - signals_approved: how many passed the ML filter
    - signals_filtered: how many were blocked
    - per_regime_trades: trade counts by regime (if regime model active)
    """

    def __init__(
        self,
        inner_strategy: StrategyBase,
        ml_model=None,
        regime_detector=None,
        ml_threshold: float = 0.5,
        symbol: str = "ASSET",
    ):
        super().__init__(name=f"MLFilter({inner_strategy.name})")
        self.inner = inner_strategy
        self.ml_model = ml_model
        self.regime_detector = regime_detector
        self.ml_threshold = ml_threshold
        self.symbol = symbol

        # Stats
        self.total_signals = 0
        self.signals_approved = 0
        self.signals_filtered = 0
        self.per_regime_trades = {}  # regime_name -> {total, approved, filtered}
        self._current_regime = None
        self._regime_history = []  # (bar_idx, regime_name)

    def initialize(self, ctx: StrategyContext) -> None:
        """Wire context to both this strategy and the inner one."""
        super().initialize(ctx)
        self.inner.initialize(ctx)

    def on_init(self) -> None:
        pass  # Inner strategy's on_init was called via initialize

    def on_bar(self, event: BarEvent) -> None:
        bar_idx = self.ctx.bar_index

        # 1. Detect current regime (if regime detector available)
        if self.regime_detector and bar_idx >= 60:
            bars_data = self._collect_recent_bars(60)
            if bars_data:
                try:
                    regime_result = self.regime_detector.predict_regime(bars_data)
                    if regime_result:
                        self._current_regime = regime_result.get("regime", "unknown")
                        self._regime_history.append((bar_idx, self._current_regime))
                except Exception:
                    pass

        # 2. Let inner strategy generate orders
        self.inner.on_bar(event)

        # 3. Intercept and filter entry orders
        if not self.ml_model and not self.regime_detector:
            return  # No filtering — pass through

        pending = self.ctx._order_queue
        if not pending:
            return

        approved = []
        for order in pending:
            # Only filter entry orders (not closes/exits)
            tag = getattr(order, "tag", "") or ""
            is_entry = "entry" in tag or "rl_" in tag
            is_close = "close" in tag or "exit" in tag or "trail" in tag

            if is_close or not is_entry:
                approved.append(order)
                continue

            # This is an entry signal — run through ML filter
            self.total_signals += 1
            direction = "BUY" if order.side == OrderSide.BUY else "SELL"

            passed = self._evaluate_ml_filter(event, direction, bar_idx)

            if passed:
                self.signals_approved += 1
                approved.append(order)
                if self._current_regime:
                    r = self.per_regime_trades.setdefault(
                        self._current_regime, {"total": 0, "approved": 0, "filtered": 0}
                    )
                    r["total"] += 1
                    r["approved"] += 1
            else:
                self.signals_filtered += 1
                if self._current_regime:
                    r = self.per_regime_trades.setdefault(
                        self._current_regime, {"total": 0, "approved": 0, "filtered": 0}
                    )
                    r["total"] += 1
                    r["filtered"] += 1

        # Replace order queue with only approved orders
        self.ctx._order_queue = approved

    def _evaluate_ml_filter(self, event: BarEvent, direction: str, bar_idx: int) -> bool:
        """Run ML model prediction on current bar features."""
        if not self.ml_model:
            # No ML model — only regime-based filtering
            return self._regime_filter(direction)

        try:
            # Build feature vector from recent bars
            bars_data = self._collect_recent_bars(30)
            if not bars_data:
                return True  # Not enough data — pass through

            from app.services.ml.features import compute_features
            features = compute_features(bars_data)
            if not features:
                return True

            last_features = {k: v[-1] for k, v in features.items()
                            if len(v) > 0 and not math.isnan(v[-1])}
            if not last_features:
                return True

            # Get ML prediction
            prediction = self.ml_model.predict(last_features, direction)
            if prediction is None:
                return True

            confidence = prediction.get("confidence", 0.5)

            # Apply regime adjustment
            if self._current_regime:
                confidence = self._adjust_confidence_by_regime(confidence, direction)

            return confidence >= self.ml_threshold

        except Exception as e:
            logger.debug("ML filter error: %s", e)
            return True  # On error, pass through

    def _regime_filter(self, direction: str) -> bool:
        """Simple regime-based filtering when no ML model is present."""
        if not self._current_regime:
            return True

        regime = self._current_regime
        # Block counter-trend trades in strong trends
        if regime == "trending_up" and direction == "SELL":
            return False
        if regime == "trending_down" and direction == "BUY":
            return False
        return True

    def _adjust_confidence_by_regime(self, confidence: float, direction: str) -> float:
        """Adjust ML confidence based on current regime."""
        regime = self._current_regime
        if not regime:
            return confidence

        if regime == "trending_up":
            if direction == "BUY":
                confidence *= 1.1
            else:
                confidence *= 0.8
        elif regime == "trending_down":
            if direction == "SELL":
                confidence *= 1.1
            else:
                confidence *= 0.8
        elif regime == "ranging":
            confidence *= 0.9
        elif regime == "volatile":
            confidence *= 0.85

        return min(confidence, 1.0)

    def on_fill(self, event: FillEvent) -> None:
        self.inner.on_fill(event)

    def on_end(self) -> None:
        self.inner.on_end()
        if self.total_signals > 0:
            logger.info(
                "ML filter stats: total=%d approved=%d filtered=%d (%.1f%% filter rate)",
                self.total_signals, self.signals_approved, self.signals_filtered,
                self.signals_filtered / self.total_signals * 100,
            )

    def get_ml_stats(self) -> dict:
        """Return ML filtering statistics for inclusion in backtest results."""
        filter_rate = (
            self.signals_filtered / self.total_signals * 100
            if self.total_signals > 0 else 0.0
        )
        return {
            "total_signals": self.total_signals,
            "signals_approved": self.signals_approved,
            "signals_filtered": self.signals_filtered,
            "filter_rate": round(filter_rate, 1),
            "per_regime_trades": self.per_regime_trades,
            "regime_history_length": len(self._regime_history),
        }

    # ── Helpers ──

    def _collect_recent_bars(self, count: int) -> list[dict]:
        bars = []
        max_ago = min(count - 1, self.ctx.bar_index)
        for i in range(max_ago, -1, -1):
            bar = self.ctx.get_bar(self.symbol, bars_ago=i)
            if bar is None:
                continue
            bars.append({
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": getattr(bar, "volume", 0.0),
            })
        return bars
