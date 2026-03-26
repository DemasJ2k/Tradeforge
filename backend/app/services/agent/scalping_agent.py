"""
ScalpingAgent — deploys Optuna-tuned XGBoost/LightGBM scalping models.

Loads scalping_<SYMBOL>_M5_xgboost.joblib and scalping_<SYMBOL>_M5_lightgbm.joblib
trained by train_scalping_pipeline.py.  Runs on each M5 bar to produce
high-conviction scalp signals with ATR-based SL/TP.

Pipeline per bar:
  1. Compute expert features (80+ from M5 + H1 context)
  2. Predict with XGBoost + LightGBM independently
  3. Require 2/2 agreement + min confidence
  4. Session / kill-zone filter
  5. ATR-based SL/TP with dynamic sizing
  6. Risk gate (0.5% per trade, 4% daily max)
"""

import logging
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "ml_models"


class ScalpingAgent:
    """
    Production scalping agent using Optuna-tuned tree models.

    Symbol-locked: one agent per symbol (XAUUSD or US30).
    Timeframe: M5 only.
    """

    def __init__(
        self,
        agent_id: int,
        symbol: str,
        broker_name: str,
        config: dict,
    ):
        self.agent_id = agent_id
        self.symbol = symbol
        self.broker_name = broker_name
        self.config = config

        # Config
        self.risk_per_trade = config.get("risk_per_trade", 0.005)
        self.max_daily_loss_pct = config.get("max_daily_loss_pct", 0.04)
        self.min_confidence = config.get("min_confidence", 0.55)
        self.session_filter = config.get("session_filter", True)
        self.min_bars_between_trades = config.get("min_bars_between_trades", 3)
        self.news_filter_enabled = config.get("news_filter_enabled", True)
        self.news_window_minutes = config.get("news_window_minutes", 15)

        # News cache
        self._news_cache: dict = {}
        self._news_cache_time = 0.0

        # Models
        self._xgb = None
        self._lgb = None
        self._xgb_grade = "?"
        self._lgb_grade = "?"
        self._feature_names: list[str] = []

        # HTF buffers
        self._h1_buffer: list[dict] = []
        self._htf_last_fetch = 0.0

        # State
        self._daily_pnl = 0.0
        self._trade_count_today = 0
        self._last_trade_bar = -100
        self._balance = 10000.0  # Updated by engine before evaluate()

    def load(self) -> bool:
        """Load scalping models from disk."""
        import joblib

        loaded = 0
        prefix = f"scalping_{self.symbol}_M5"

        # XGBoost
        xgb_path = MODEL_DIR / f"{prefix}_xgboost.joblib"
        if xgb_path.exists():
            try:
                data = joblib.load(xgb_path)
                self._xgb = data["model"]
                self._xgb_grade = data.get("grade", "?")
                if not self._feature_names:
                    self._feature_names = data.get("feature_names", [])
                loaded += 1
                logger.info("[Scalp %d] XGBoost loaded (Grade %s) for %s",
                            self.agent_id, self._xgb_grade, self.symbol)
            except Exception as e:
                logger.error("[Scalp %d] XGBoost load failed: %s", self.agent_id, e)

        # LightGBM
        lgb_path = MODEL_DIR / f"{prefix}_lightgbm.joblib"
        if lgb_path.exists():
            try:
                data = joblib.load(lgb_path)
                self._lgb = data["model"]
                self._lgb_grade = data.get("grade", "?")
                if not self._feature_names:
                    self._feature_names = data.get("feature_names", [])
                loaded += 1
                logger.info("[Scalp %d] LightGBM loaded (Grade %s) for %s",
                            self.agent_id, self._lgb_grade, self.symbol)
            except Exception as e:
                logger.error("[Scalp %d] LightGBM load failed: %s", self.agent_id, e)

        if loaded == 0:
            logger.warning("[Scalp %d] No models found for %s — run train_scalping_pipeline.py",
                           self.agent_id, self.symbol)
        return loaded >= 1

    async def evaluate(
        self,
        m5_bars: list[dict],
        broker_adapter=None,
    ) -> Optional[dict]:
        """
        Evaluate on latest M5 bar. Returns signal dict or None.

        Signal: {direction, confidence, entry_price, stop_loss, take_profit,
                 lot_size, reason, session, grades}
        """
        if not self._xgb and not self._lgb:
            return None
        if len(m5_bars) < 60:
            return None

        current_bar = m5_bars[-1]
        price = current_bar.get("close", 0)
        if price <= 0:
            return None

        # Cooldown
        bar_idx = len(m5_bars) - 1
        if bar_idx - self._last_trade_bar < self.min_bars_between_trades:
            return None

        # Daily loss gate
        if self._daily_pnl < -(self._balance * self.max_daily_loss_pct):
            logger.info("[Scalp %d] Daily loss limit hit", self.agent_id)
            return None

        # News filter — avoid trading during high-impact events
        if self.news_filter_enabled:
            news_ok = await self._check_news_filter()
            if not news_ok:
                logger.info("[Scalp %d] Trade blocked by news filter", self.agent_id)
                return None

        # Fetch H1 context
        await self._fetch_htf(broker_adapter)

        # Compute features
        try:
            from app.services.ml.features_mtf import compute_expert_features
            feat_names, X = compute_expert_features(
                m5_bars,
                self._h1_buffer if self._h1_buffer else None,
                None, None,
            )
            if len(feat_names) == 0 or X.shape[0] == 0:
                return None

            latest = X[-1].copy()
            latest = np.nan_to_num(latest, nan=0.0, posinf=0.0, neginf=0.0)
        except Exception as e:
            logger.error("[Scalp %d] Features failed: %s", self.agent_id, e)
            return None

        # Session filter
        session = self._get_session()
        if self.session_filter and session == "dead" and self.symbol != "BTCUSD":
            return None

        # Predict with both models
        votes = []
        confs = []

        if self._xgb:
            pred = self._xgb.predict(latest.reshape(1, -1))[0]
            proba = self._xgb.predict_proba(latest.reshape(1, -1))[0]
            conf = float(np.max(proba))
            if pred != 1 and conf >= self.min_confidence:
                votes.append(2 if pred == 2 else 0)
                confs.append(conf)

        if self._lgb:
            pred = self._lgb.predict(latest.reshape(1, -1))[0]
            proba = self._lgb.predict_proba(latest.reshape(1, -1))[0]
            conf = float(np.max(proba))
            if pred != 1 and conf >= self.min_confidence:
                votes.append(2 if pred == 2 else 0)
                confs.append(conf)

        # Require agreement
        n_models = (1 if self._xgb else 0) + (1 if self._lgb else 0)
        if len(votes) < min(2, n_models):
            return None

        # Check direction agreement
        if len(set(votes)) != 1:
            return None

        direction = 1 if votes[0] == 2 else -1
        confidence = float(np.mean(confs))

        # SL/TP
        sl, tp = self._compute_sl_tp(m5_bars, direction, price)
        if sl == 0 or tp == 0:
            return None

        sl_dist = abs(price - sl)
        if sl_dist <= 0:
            return None

        # Position sizing
        session_mult = 0.5 if session == "asian" and self.symbol != "BTCUSD" else 1.0
        risk_amount = 10000 * self.risk_per_trade * session_mult

        try:
            from app.services.agent.instrument_specs import calc_lot_size
            lot_size = calc_lot_size(self.symbol, risk_amount, sl_dist, broker_name=self.broker_name)
        except Exception:
            lot_size = 0.01

        if lot_size <= 0:
            return None

        self._last_trade_bar = bar_idx

        return {
            "direction": direction,
            "confidence": round(confidence, 4),
            "entry_price": price,
            "stop_loss": round(sl, 5),
            "take_profit": round(tp, 5),
            "lot_size": lot_size,
            "reason": f"scalp_ensemble_{self.symbol}",
            "session": session,
            "grades": {"xgboost": self._xgb_grade, "lightgbm": self._lgb_grade},
            "agent_type": "scalping",
        }

    def _compute_sl_tp(self, bars: list[dict], direction: int, price: float):
        """ATR-based SL/TP."""
        if len(bars) < 15:
            return 0, 0

        from app.services.backtest import indicators as ind
        highs = [b["high"] for b in bars[-50:]]
        lows = [b["low"] for b in bars[-50:]]
        closes = [b["close"] for b in bars[-50:]]
        atr_vals = ind.atr(highs, lows, closes, 14)

        atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0
        if atr <= 0:
            return 0, 0

        sl_mult = 1.5
        tp_mult = 2.5

        if direction == 1:
            sl = price - atr * sl_mult
            tp = price + atr * tp_mult
        else:
            sl = price + atr * sl_mult
            tp = price - atr * tp_mult

        return sl, tp

    def _get_session(self) -> str:
        """Current trading session."""
        h = datetime.now(timezone.utc).hour
        if 0 <= h < 8:
            return "asian"
        elif 8 <= h < 13:
            return "london"
        elif 13 <= h < 21:
            return "ny"
        return "dead"

    async def _fetch_htf(self, broker_adapter):
        """Fetch H1 bars from broker if stale."""
        import time as _time
        now = _time.time()
        if now - self._htf_last_fetch < 3600:
            return

        if broker_adapter:
            try:
                h1 = await broker_adapter.get_candles(self.symbol, "H1", 200)
                if h1:
                    self._h1_buffer = h1
                    self._htf_last_fetch = now
            except Exception as e:
                logger.warning("[Scalp %d] HTF fetch failed: %s", self.agent_id, e)

    async def _check_news_filter(self) -> bool:
        """Check if it's safe to trade (no high-impact news imminent)."""
        import time as _time
        now = _time.time()

        # Cache news check for 5 minutes
        if now - self._news_cache_time < 300 and self._news_cache:
            return self._news_cache.get("should_trade", True)

        try:
            from app.services.news.newsapi_provider import check_high_impact_news
            result = await check_high_impact_news(
                self.symbol,
                window_minutes=self.news_window_minutes,
            )
            self._news_cache = result
            self._news_cache_time = now

            if not result["should_trade"]:
                logger.info("[Scalp %d] News filter: %s", self.agent_id, result["reason"])

            return result["should_trade"]

        except Exception as e:
            logger.warning("[Scalp %d] News check failed: %s", self.agent_id, e)
            return True  # Fail open

    def get_status(self) -> dict:
        """Return agent status for UI."""
        return {
            "agent_type": "scalping",
            "symbol": self.symbol,
            "models_loaded": bool(self._xgb or self._lgb),
            "xgb_grade": self._xgb_grade,
            "lgb_grade": self._lgb_grade,
            "daily_pnl": self._daily_pnl,
            "trade_count_today": self._trade_count_today,
            "last_trade_bar": self._last_trade_bar,
            "config": {
                "risk_per_trade": self.risk_per_trade,
                "min_confidence": self.min_confidence,
                "session_filter": self.session_filter,
                "news_filter_enabled": self.news_filter_enabled,
            },
        }
