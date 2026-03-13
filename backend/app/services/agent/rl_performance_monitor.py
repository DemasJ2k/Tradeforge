"""
RL Performance Monitor — tracks rolling performance of RL-filtered trades.

Detects model degradation and alerts/disables when performance drops below thresholds.
Stores metrics in agent risk_config (no DB migration needed).
"""

import logging
from collections import defaultdict
from typing import Optional

logger = logging.getLogger(__name__)

# Thresholds
MIN_TRADES_FOR_ALERT = 50      # Don't alert until we have enough trades
PF_WARNING_THRESHOLD = 1.0     # Warn if PF drops below this
PF_CRITICAL_THRESHOLD = 0.9    # Auto-disable if PF drops below this
MIN_TRADES_FOR_CRITICAL = 100  # Need more trades before auto-disable
MAX_CONSECUTIVE_LOSSES = 10    # Alert on losing streak


class RLPerformanceMonitor:
    """
    Lightweight per-model performance tracker.

    Tracks rolling profit factor, win rate, and consecutive losses.
    Can be used by the agent engine to detect and react to model degradation.
    """

    def __init__(self):
        # In-memory tracking: model_id -> metrics
        self._metrics: dict[int, dict] = defaultdict(lambda: {
            "total_trades": 0,
            "winning_trades": 0,
            "total_pnl": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "consecutive_losses": 0,
            "max_consecutive_losses": 0,
            "alerts": [],
        })

    def record_trade(self, model_id: int, pnl: float) -> Optional[dict]:
        """
        Record a closed trade result for an RL model.

        Args:
            model_id: The MLModel.id of the RL model
            pnl: Profit/loss of the closed trade

        Returns:
            Alert dict if a threshold was crossed, else None.
            Alert: {level: "warning"|"critical", message, metrics}
        """
        m = self._metrics[model_id]
        m["total_trades"] += 1
        m["total_pnl"] += pnl

        if pnl > 0:
            m["winning_trades"] += 1
            m["gross_profit"] += pnl
            m["consecutive_losses"] = 0
        else:
            m["gross_loss"] += abs(pnl)
            m["consecutive_losses"] += 1
            m["max_consecutive_losses"] = max(
                m["max_consecutive_losses"], m["consecutive_losses"]
            )

        total = m["total_trades"]
        pf = m["gross_profit"] / m["gross_loss"] if m["gross_loss"] > 0 else float("inf")
        wr = m["winning_trades"] / total * 100 if total > 0 else 0

        # Check for consecutive loss alert
        if m["consecutive_losses"] >= MAX_CONSECUTIVE_LOSSES:
            alert = {
                "level": "warning",
                "type": "losing_streak",
                "message": f"RL model {model_id}: {m['consecutive_losses']} consecutive losses",
                "metrics": self.get_metrics(model_id),
            }
            m["alerts"].append(alert)
            logger.warning("[RLMonitor] %s", alert["message"])
            return alert

        # Check for PF degradation
        if total >= MIN_TRADES_FOR_CRITICAL and pf < PF_CRITICAL_THRESHOLD:
            alert = {
                "level": "critical",
                "type": "pf_critical",
                "message": f"RL model {model_id}: PF={pf:.2f} below critical threshold ({PF_CRITICAL_THRESHOLD}). Auto-disable recommended.",
                "metrics": self.get_metrics(model_id),
            }
            m["alerts"].append(alert)
            logger.error("[RLMonitor] %s", alert["message"])
            return alert

        if total >= MIN_TRADES_FOR_ALERT and pf < PF_WARNING_THRESHOLD:
            alert = {
                "level": "warning",
                "type": "pf_warning",
                "message": f"RL model {model_id}: PF={pf:.2f} below warning threshold ({PF_WARNING_THRESHOLD})",
                "metrics": self.get_metrics(model_id),
            }
            m["alerts"].append(alert)
            logger.warning("[RLMonitor] %s", alert["message"])
            return alert

        return None

    def get_metrics(self, model_id: int) -> dict:
        """Get current performance metrics for a model."""
        m = self._metrics[model_id]
        total = m["total_trades"]
        pf = m["gross_profit"] / m["gross_loss"] if m["gross_loss"] > 0 else float("inf")
        wr = m["winning_trades"] / total * 100 if total > 0 else 0

        return {
            "total_trades": total,
            "winning_trades": m["winning_trades"],
            "win_rate": round(wr, 1),
            "total_pnl": round(m["total_pnl"], 2),
            "profit_factor": round(pf, 3) if pf != float("inf") else None,
            "gross_profit": round(m["gross_profit"], 2),
            "gross_loss": round(m["gross_loss"], 2),
            "consecutive_losses": m["consecutive_losses"],
            "max_consecutive_losses": m["max_consecutive_losses"],
        }

    def should_disable(self, model_id: int) -> bool:
        """Check if model should be auto-disabled due to poor performance."""
        m = self._metrics[model_id]
        if m["total_trades"] < MIN_TRADES_FOR_CRITICAL:
            return False
        pf = m["gross_profit"] / m["gross_loss"] if m["gross_loss"] > 0 else float("inf")
        return pf < PF_CRITICAL_THRESHOLD

    def reset(self, model_id: int):
        """Reset metrics for a model (e.g., after retraining)."""
        if model_id in self._metrics:
            del self._metrics[model_id]


# Singleton instance
rl_performance_monitor = RLPerformanceMonitor()
