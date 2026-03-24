"""
Agent-based backtest strategies for V2 engine.

Wraps the ScalpingAgent and ExpertAgent ML logic as StrategyBase subclasses
so they can run through the standard V2 event loop with full slippage,
spread, commission, and tearsheet analytics.

ScalpingAgentStrategy:
  - Loads XGBoost + LightGBM scalping models from disk
  - Computes 80+ expert features per bar (same pipeline as live agent)
  - Requires dual-model agreement + min confidence
  - Session filtering from bar timestamps (not live UTC)
  - ATR-based dynamic SL/TP
  - Cooldown between trades

ExpertAgentStrategy:
  - Loads full ensemble (XGBoost + LightGBM + LSTM) + meta-labeler
  - Multi-timeframe features (M5 + H1 + H4 context via DataHandler HTF)
  - Regime detection (HMM) with risk multiplier adjustment
  - Session/kill-zone awareness
  - Symbol-specific SL/TP multipliers
"""

from __future__ import annotations

import logging
import math
import os
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.services.backtest.v2.engine.events import BarEvent, FillEvent
from app.services.backtest.v2.engine.strategy_base import StrategyBase, StrategyContext
from app.services.backtest.v2.engine.order import OrderSide

logger = logging.getLogger(__name__)

MODEL_DIR = Path("data/ml_models")


# ── Shared Helpers ─────────────────────────────────────────────────


def _collect_ohlcv_bars(ctx: StrategyContext, symbol: str, count: int) -> list[dict]:
    """Collect recent bars as OHLCV dicts from the backtest DataHandler."""
    bars = []
    max_ago = min(count - 1, ctx.bar_index)
    for i in range(max_ago, -1, -1):
        bar = ctx.get_bar(symbol, bars_ago=i)
        if bar is None:
            continue
        bars.append({
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": getattr(bar, "volume", 0.0),
            "datetime": getattr(bar, "datetime", None) or getattr(bar, "timestamp", None),
        })
    return bars


def _collect_htf_bars(ctx: StrategyContext, symbol: str, tf_label: str, count: int) -> list[dict]:
    """Collect higher-timeframe bars from the DataHandler's HTF data."""
    bars = []
    for i in range(count - 1, -1, -1):
        bar = ctx.get_htf_bar(symbol, tf_label, bars_ago=i)
        if bar is None:
            continue
        bars.append({
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": getattr(bar, "volume", 0.0),
            "datetime": getattr(bar, "datetime", None) or getattr(bar, "timestamp", None),
        })
    return bars


def _get_session_from_bar(bar_data: dict) -> str:
    """Determine trading session from bar timestamp."""
    ts = bar_data.get("datetime")
    if ts is None:
        return "unknown"

    if isinstance(ts, (int, float)):
        try:
            ts = datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OSError, ValueError):
            # Nanosecond timestamps
            try:
                ts = datetime.fromtimestamp(ts / 1e9, tz=timezone.utc)
            except Exception:
                return "unknown"
    elif isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return "unknown"

    if not hasattr(ts, "hour"):
        return "unknown"

    h = ts.hour
    if 0 <= h < 8:
        return "asian"
    elif 8 <= h < 13:
        return "london"
    elif 13 <= h < 21:
        return "ny"
    return "dead"


def _compute_atr_from_bars(bars: list[dict], period: int = 14) -> float:
    """Compute ATR from OHLCV bar dicts."""
    if len(bars) < period + 1:
        return 0.0
    try:
        from app.services.backtest import indicators as ind
        highs = [b["high"] for b in bars[-50:]]
        lows = [b["low"] for b in bars[-50:]]
        closes = [b["close"] for b in bars[-50:]]
        atr_vals = ind.atr(highs, lows, closes, period)
        if atr_vals and atr_vals[-1] is not None:
            return atr_vals[-1]
    except Exception:
        pass
    return 0.0


# ═══════════════════════════════════════════════════════════════════
#  ScalpingAgentStrategy
# ═══════════════════════════════════════════════════════════════════


class ScalpingAgentStrategy(StrategyBase):
    """V2 backtest strategy replicating the ScalpingAgent's live logic.

    Loads the same Optuna-tuned XGBoost + LightGBM models and applies:
    - 80+ expert features (M5 + H1 context)
    - Dual-model agreement (both must predict same direction)
    - Minimum confidence threshold
    - Session/kill-zone filtering (from bar timestamps)
    - ATR-based SL/TP with configurable multipliers
    - Cooldown between trades (min_bars_between_trades)
    - Risk-based position sizing
    """

    def __init__(
        self,
        symbol: str = "XAUUSD",
        model_dir: str | None = None,
        risk_per_trade: float = 0.005,
        min_confidence: float = 0.55,
        session_filter: bool = True,
        min_bars_between_trades: int = 3,
        sl_mult: float = 1.5,
        tp_mult: float = 2.5,
        lot_size: float = 0.01,
    ):
        super().__init__(
            name=f"ScalpingAgent({symbol})",
            params={
                "risk_per_trade": risk_per_trade,
                "min_confidence": min_confidence,
                "session_filter": session_filter,
                "sl_mult": sl_mult,
                "tp_mult": tp_mult,
            },
        )
        self.symbol = symbol
        self._model_dir = Path(model_dir) if model_dir else MODEL_DIR
        self.risk_per_trade = risk_per_trade
        self.min_confidence = min_confidence
        self.session_filter = session_filter
        self.min_bars_between_trades = min_bars_between_trades
        self.sl_mult = sl_mult
        self.tp_mult = tp_mult
        self.default_lot_size = lot_size

        # Models
        self._xgb = None
        self._lgb = None
        self._feature_names: list[str] = []

        # State
        self._last_trade_bar = -100
        self._daily_pnl = 0.0

        # Stats
        self.total_signals = 0
        self.signals_taken = 0
        self.signals_filtered_confidence = 0
        self.signals_filtered_session = 0
        self.signals_filtered_disagreement = 0

    def on_init(self) -> None:
        self._load_models()

    def _load_models(self) -> None:
        """Load XGBoost + LightGBM scalping models from disk."""
        try:
            import joblib
        except ImportError:
            logger.error("[ScalpBT] joblib not available — cannot load models")
            return

        prefix = f"scalping_{self.symbol}_M5"

        xgb_path = self._model_dir / f"{prefix}_xgboost.joblib"
        if xgb_path.exists():
            try:
                data = joblib.load(xgb_path)
                self._xgb = data["model"]
                if not self._feature_names:
                    self._feature_names = data.get("feature_names", [])
                logger.info("[ScalpBT] XGBoost loaded (Grade %s)", data.get("grade", "?"))
            except Exception as e:
                logger.error("[ScalpBT] XGBoost load failed: %s", e)

        lgb_path = self._model_dir / f"{prefix}_lightgbm.joblib"
        if lgb_path.exists():
            try:
                data = joblib.load(lgb_path)
                self._lgb = data["model"]
                if not self._feature_names:
                    self._feature_names = data.get("feature_names", [])
                logger.info("[ScalpBT] LightGBM loaded (Grade %s)", data.get("grade", "?"))
            except Exception as e:
                logger.error("[ScalpBT] LightGBM load failed: %s", e)

        if not self._xgb and not self._lgb:
            logger.warning("[ScalpBT] No models found for %s in %s", self.symbol, self._model_dir)

    def on_bar(self, event: BarEvent) -> None:
        bar_idx = self.ctx.bar_index
        if bar_idx < 60:
            return  # Warm-up for features

        if not self._xgb and not self._lgb:
            return

        # Already in a position — skip
        pos = self.ctx.get_position(self.symbol)
        if pos and not pos.is_flat:
            return

        # Cooldown
        if bar_idx - self._last_trade_bar < self.min_bars_between_trades:
            return

        # Collect M5 bars for feature computation
        m5_bars = _collect_ohlcv_bars(self.ctx, self.symbol, 500)
        if len(m5_bars) < 60:
            return

        current_bar = m5_bars[-1]
        price = current_bar.get("close", 0)
        if price <= 0:
            return

        # Session filter
        session = _get_session_from_bar(current_bar)
        if self.session_filter and session == "dead" and self.symbol != "BTCUSD":
            self.signals_filtered_session += 1
            return

        # Compute expert features
        try:
            from app.services.ml.features_mtf import compute_expert_features

            # Try to get H1 context from DataHandler HTF
            h1_bars = _collect_htf_bars(self.ctx, self.symbol, "H1", 200)

            feat_names, X = compute_expert_features(
                m5_bars,
                h1_bars if len(h1_bars) >= 50 else None,
                None,  # No H4 for scalping
                None,  # No daily for scalping
            )
            if len(feat_names) == 0 or X.shape[0] == 0:
                return

            latest = X[-1].copy()
            latest = np.nan_to_num(latest, nan=0.0, posinf=0.0, neginf=0.0)
        except Exception as e:
            logger.debug("[ScalpBT] Feature computation error: %s", e)
            return

        # Predict with both models
        votes = []
        confs = []

        if self._xgb:
            try:
                pred = self._xgb.predict(latest.reshape(1, -1))[0]
                proba = self._xgb.predict_proba(latest.reshape(1, -1))[0]
                conf = float(np.max(proba))
                if pred != 1 and conf >= self.min_confidence:
                    votes.append(2 if pred == 2 else 0)
                    confs.append(conf)
            except Exception as e:
                logger.debug("[ScalpBT] XGBoost predict error: %s", e)

        if self._lgb:
            try:
                pred = self._lgb.predict(latest.reshape(1, -1))[0]
                proba = self._lgb.predict_proba(latest.reshape(1, -1))[0]
                conf = float(np.max(proba))
                if pred != 1 and conf >= self.min_confidence:
                    votes.append(2 if pred == 2 else 0)
                    confs.append(conf)
            except Exception as e:
                logger.debug("[ScalpBT] LightGBM predict error: %s", e)

        self.total_signals += 1

        # Require agreement from all available models
        n_models = (1 if self._xgb else 0) + (1 if self._lgb else 0)
        if len(votes) < min(2, n_models):
            self.signals_filtered_confidence += 1
            return

        if len(set(votes)) != 1:
            self.signals_filtered_disagreement += 1
            return

        direction = 1 if votes[0] == 2 else -1
        confidence = float(np.mean(confs))

        # Compute ATR-based SL/TP
        atr = _compute_atr_from_bars(m5_bars)
        if atr <= 0:
            return

        if direction == 1:
            sl = price - atr * self.sl_mult
            tp = price + atr * self.tp_mult
        else:
            sl = price + atr * self.sl_mult
            tp = price - atr * self.tp_mult

        sl_dist = abs(price - sl)
        if sl_dist <= 0:
            return

        # Position sizing
        session_mult = 0.5 if session == "asian" and self.symbol != "BTCUSD" else 1.0
        equity = self.ctx.get_equity()
        risk_amount = equity * self.risk_per_trade * session_mult

        try:
            from app.services.agent.instrument_specs import calc_lot_size
            lot_size = calc_lot_size(self.symbol, risk_amount, sl_dist)
        except Exception:
            lot_size = self.default_lot_size

        if lot_size <= 0:
            lot_size = self.default_lot_size

        # Place bracket order
        self._last_trade_bar = bar_idx
        self.signals_taken += 1

        if direction == 1:
            self.ctx.buy_bracket(
                self.symbol, lot_size,
                stop_loss=sl, take_profit=tp,
                tag="entry_scalp_buy",
            )
        else:
            self.ctx.sell_bracket(
                self.symbol, lot_size,
                stop_loss=sl, take_profit=tp,
                tag="entry_scalp_sell",
            )

    def on_fill(self, event: FillEvent) -> None:
        pass

    def on_end(self) -> None:
        if self.total_signals > 0:
            logger.info(
                "[ScalpBT] Stats: signals=%d taken=%d filtered(conf=%d disag=%d sess=%d)",
                self.total_signals, self.signals_taken,
                self.signals_filtered_confidence,
                self.signals_filtered_disagreement,
                self.signals_filtered_session,
            )

    def get_agent_stats(self) -> dict:
        """Return agent-specific stats for inclusion in backtest results."""
        return {
            "agent_type": "scalping",
            "symbol": self.symbol,
            "total_signals": self.total_signals,
            "signals_taken": self.signals_taken,
            "signals_filtered_confidence": self.signals_filtered_confidence,
            "signals_filtered_disagreement": self.signals_filtered_disagreement,
            "signals_filtered_session": self.signals_filtered_session,
            "models_loaded": {
                "xgboost": self._xgb is not None,
                "lightgbm": self._lgb is not None,
            },
            "config": {
                "min_confidence": self.min_confidence,
                "session_filter": self.session_filter,
                "sl_mult": self.sl_mult,
                "tp_mult": self.tp_mult,
                "risk_per_trade": self.risk_per_trade,
            },
        }


# ═══════════════════════════════════════════════════════════════════
#  ExpertAgentStrategy
# ═══════════════════════════════════════════════════════════════════


class ExpertAgentStrategy(StrategyBase):
    """V2 backtest strategy replicating the ExpertAgent's live logic.

    Loads full ensemble (XGBoost + LightGBM + LSTM) plus optional
    meta-labeler and regime detector. Applies:
    - 80+ expert features with multi-timeframe context (M5 + H1 + H4 + D1)
    - Ensemble voting (min 2/3 agreement)
    - Meta-labeler filter (trade/no-trade gate)
    - HMM regime detection with risk adjustment
    - Session/kill-zone awareness
    - Symbol-specific ATR SL/TP multipliers
    - Risk-based position sizing with regime + session multipliers
    """

    def __init__(
        self,
        symbol: str = "XAUUSD",
        model_dir: str | None = None,
        risk_per_trade: float = 0.005,
        min_confidence: float = 0.55,
        min_agreement: int = 2,
        session_filter: bool = True,
        regime_filter: bool = True,
        min_bars_between_trades: int = 3,
        lot_size: float = 0.01,
    ):
        super().__init__(
            name=f"ExpertAgent({symbol})",
            params={
                "risk_per_trade": risk_per_trade,
                "min_confidence": min_confidence,
                "min_agreement": min_agreement,
                "session_filter": session_filter,
                "regime_filter": regime_filter,
            },
        )
        self.symbol = symbol
        self._model_dir = Path(model_dir) if model_dir else MODEL_DIR
        self.risk_per_trade = risk_per_trade
        self.min_confidence = min_confidence
        self.min_agreement = min_agreement
        self.session_filter = session_filter
        self.regime_filter = regime_filter
        self.min_bars_between_trades = min_bars_between_trades
        self.default_lot_size = lot_size

        # Components
        self._ensemble = None
        self._regime_detector = None

        # Symbol-specific SL/TP multipliers
        self._sl_mults = {"XAUUSD": 1.5, "US30": 1.5, "BTCUSD": 2.0, "ES": 1.5, "NAS100": 1.5}
        self._tp_mults = {"XAUUSD": 2.5, "US30": 2.0, "BTCUSD": 3.0, "ES": 2.0, "NAS100": 2.0}

        # State
        self._last_trade_bar = -100

        # Stats
        self.total_evaluations = 0
        self.signals_generated = 0
        self.signals_taken = 0
        self.signals_filtered_session = 0
        self.signals_filtered_regime = 0
        self.signals_filtered_ensemble = 0
        self.signals_filtered_meta = 0
        self.regime_history: list[tuple[int, str]] = []

    def on_init(self) -> None:
        self._load_components()

    def _load_components(self) -> None:
        """Load ensemble engine and regime detector."""
        try:
            from app.services.ml.ensemble_engine import EnsembleSignalEngine
            self._ensemble = EnsembleSignalEngine(
                symbol=self.symbol,
                timeframe="M5",
                model_dir=str(self._model_dir),
                min_agreement=self.min_agreement,
                min_confidence=self.min_confidence,
            )
            loaded = self._ensemble.load_models()
            if not loaded:
                logger.warning("[ExpertBT] Ensemble not loaded for %s", self.symbol)
                self._ensemble = None
        except Exception as e:
            logger.error("[ExpertBT] Failed to load ensemble: %s", e)
            self._ensemble = None

        # Regime detector (optional)
        if self.regime_filter:
            try:
                from app.services.ml.regime_detector import RegimeDetector
                regime_path = self._model_dir / f"expert_{self.symbol}_M5_regime.joblib"
                if not regime_path.exists():
                    candidates = list(self._model_dir.glob(f"*regime*{self.symbol}*"))
                    if candidates:
                        regime_path = candidates[0]

                if regime_path.exists():
                    rd = RegimeDetector(model_id=0)
                    rd._model_path = str(regime_path)
                    if rd.load():
                        self._regime_detector = rd
                        logger.info("[ExpertBT] Regime detector loaded")
            except Exception as e:
                logger.debug("[ExpertBT] Regime detector not available: %s", e)

    def on_bar(self, event: BarEvent) -> None:
        bar_idx = self.ctx.bar_index
        if bar_idx < 60:
            return

        if not self._ensemble:
            return

        # Already in a position — skip
        pos = self.ctx.get_position(self.symbol)
        if pos and not pos.is_flat:
            return

        # Cooldown
        if bar_idx - self._last_trade_bar < self.min_bars_between_trades:
            return

        self.total_evaluations += 1

        # Collect M5 bars
        m5_bars = _collect_ohlcv_bars(self.ctx, self.symbol, 500)
        if len(m5_bars) < 60:
            return

        current_bar = m5_bars[-1]
        price = current_bar.get("close", 0)
        if price <= 0:
            return

        # Session filter
        session = _get_session_from_bar(current_bar)
        session_risk_mult = 1.0

        if self.session_filter:
            if session == "dead" and self.symbol != "BTCUSD":
                self.signals_filtered_session += 1
                return
            if session == "asian" and self.symbol in ("XAUUSD", "US30"):
                session_risk_mult = 0.5

        # Regime detection
        regime = "unknown"
        regime_risk_mult = 1.0

        if self._regime_detector and self.regime_filter:
            try:
                regime_ctx = self._regime_detector.predict_regime(m5_bars)
                if regime_ctx:
                    regime = regime_ctx.get("regime", "unknown")
                    regime_conf = regime_ctx.get("confidence", 0)
                    self.regime_history.append((bar_idx, regime))

                    if regime == "volatile" and regime_conf > 0.5:
                        regime_risk_mult = 0.6
                    elif regime == "ranging" and regime_conf > 0.6:
                        regime_risk_mult = 0.8
                    elif regime in ("trending_up", "trending_down"):
                        regime_risk_mult = 1.1
            except Exception:
                pass

        # Compute expert features
        try:
            from app.services.ml.features_mtf import compute_expert_features

            h1_bars = _collect_htf_bars(self.ctx, self.symbol, "H1", 200)
            h4_bars = _collect_htf_bars(self.ctx, self.symbol, "H4", 100)

            feat_names, X = compute_expert_features(
                m5_bars,
                h1_bars if len(h1_bars) >= 50 else None,
                h4_bars if len(h4_bars) >= 50 else None,
                None,  # Daily bars via HTF if available
            )
            if len(feat_names) == 0 or X.shape[0] == 0:
                return

            latest_features = X[-1].copy()
            latest_features = np.nan_to_num(latest_features, nan=0.0, posinf=0.0, neginf=0.0)

            # Build sequence for LSTM
            seq_len = min(60, X.shape[0])
            feature_sequence = X[-seq_len:].copy()
            feature_sequence = np.nan_to_num(feature_sequence, nan=0.0, posinf=0.0, neginf=0.0)

        except Exception as e:
            logger.debug("[ExpertBT] Feature error: %s", e)
            return

        # Ensemble vote
        try:
            result = self._ensemble.predict(
                feature_vector=latest_features,
                feature_sequence=feature_sequence,
            )
        except Exception as e:
            logger.debug("[ExpertBT] Ensemble error: %s", e)
            return

        if not result or result["direction"] == 0:
            reason = result.get("reason", "") if result else ""
            if "Meta-labeler" in reason:
                self.signals_filtered_meta += 1
            else:
                self.signals_filtered_ensemble += 1
            return

        self.signals_generated += 1

        direction = result["direction"]
        confidence = result["confidence"]

        # Compute SL/TP
        atr = _compute_atr_from_bars(m5_bars)
        if atr <= 0:
            return

        sl_mult = self._sl_mults.get(self.symbol, 1.5)
        tp_mult = self._tp_mults.get(self.symbol, 2.0)

        if direction == 1:
            sl = price - atr * sl_mult
            tp = price + atr * tp_mult
        else:
            sl = price + atr * sl_mult
            tp = price - atr * tp_mult

        sl_dist = abs(price - sl)
        if sl_dist <= 0:
            return

        # Position sizing with regime + session adjustment
        effective_risk = self.risk_per_trade * session_risk_mult * regime_risk_mult
        equity = self.ctx.get_equity()
        risk_amount = equity * effective_risk

        try:
            from app.services.agent.instrument_specs import calc_lot_size
            lot_size = calc_lot_size(self.symbol, risk_amount, sl_dist)
        except Exception:
            lot_size = self.default_lot_size

        if lot_size <= 0:
            lot_size = self.default_lot_size

        # Place bracket order
        self._last_trade_bar = bar_idx
        self.signals_taken += 1

        if direction == 1:
            self.ctx.buy_bracket(
                self.symbol, lot_size,
                stop_loss=sl, take_profit=tp,
                tag="entry_expert_buy",
            )
        else:
            self.ctx.sell_bracket(
                self.symbol, lot_size,
                stop_loss=sl, take_profit=tp,
                tag="entry_expert_sell",
            )

    def on_fill(self, event: FillEvent) -> None:
        pass

    def on_end(self) -> None:
        if self.total_evaluations > 0:
            logger.info(
                "[ExpertBT] Stats: evals=%d signals=%d taken=%d "
                "filtered(sess=%d regime=%d ensemble=%d meta=%d)",
                self.total_evaluations, self.signals_generated, self.signals_taken,
                self.signals_filtered_session, self.signals_filtered_regime,
                self.signals_filtered_ensemble, self.signals_filtered_meta,
            )

    def get_agent_stats(self) -> dict:
        """Return agent-specific stats for inclusion in backtest results."""
        # Regime distribution
        regime_counts: dict[str, int] = {}
        for _, r in self.regime_history:
            regime_counts[r] = regime_counts.get(r, 0) + 1

        return {
            "agent_type": "expert",
            "symbol": self.symbol,
            "total_evaluations": self.total_evaluations,
            "signals_generated": self.signals_generated,
            "signals_taken": self.signals_taken,
            "signals_filtered_session": self.signals_filtered_session,
            "signals_filtered_regime": self.signals_filtered_regime,
            "signals_filtered_ensemble": self.signals_filtered_ensemble,
            "signals_filtered_meta": self.signals_filtered_meta,
            "regime_distribution": regime_counts,
            "models_loaded": self._ensemble.get_status() if self._ensemble else None,
            "config": {
                "min_confidence": self.min_confidence,
                "min_agreement": self.min_agreement,
                "session_filter": self.session_filter,
                "regime_filter": self.regime_filter,
                "risk_per_trade": self.risk_per_trade,
            },
        }
