"""
Expert Agent — autonomous trading agent that trades like an expert human.

Combines multi-timeframe analysis, market structure detection, session awareness,
news filtering, and ensemble ML voting into a single decision engine.

Pipeline on each M5 bar:
  1. Fetch H1/H4 context bars from broker
  2. Compute expert features (80+ technical + structure + session + MTF)
  3. Check news filter (skip if high-impact news imminent)
  4. Get regime classification (trending/ranging/volatile)
  5. Run ensemble vote (XGBoost + LightGBM + LSTM → 2/3 agreement)
  6. Apply meta-label filter (should I take this trade?)
  7. Compute dynamic SL/TP via LSTM price distribution
  8. Apply risk gate (0.5% risk, prop firm limits)
  9. Execute or skip

Configuration (stored in agent.risk_config):
  {
      "agent_type": "expert",
      "risk_per_trade": 0.005,
      "max_daily_loss_pct": 0.04,
      "max_drawdown_pct": 0.08,
      "news_filter_enabled": true,
      "news_window_minutes": 15,
      "ensemble_min_agreement": 2,
      "ensemble_min_confidence": 0.55,
      "session_filter": true,      # reduce risk in dead zone
      "regime_filter": true,       # reduce risk in volatile regime
  }
"""

import asyncio
import logging
import numpy as np
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class ExpertAgent:
    """
    Expert-level autonomous trading agent.

    Designed for: XAUUSD, US30, BTCUSD on M5 timeframe.
    Account: $10K prop firm, 0.5% risk per trade.
    Hours: 24/5 (Gold/US30), 24/7 (BTC), session-aware.
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

        # Config with defaults
        self.risk_per_trade = config.get("risk_per_trade", 0.005)
        self.max_daily_loss_pct = config.get("max_daily_loss_pct", 0.04)
        self.max_drawdown_pct = config.get("max_drawdown_pct", 0.08)
        self.news_filter_enabled = config.get("news_filter_enabled", True)
        self.news_window_minutes = config.get("news_window_minutes", 15)
        self.min_agreement = config.get("ensemble_min_agreement", 2)
        self.min_confidence = config.get("ensemble_min_confidence", 0.55)
        self.session_filter = config.get("session_filter", True)
        self.regime_filter = config.get("regime_filter", True)

        # Components (loaded on start)
        self._ensemble = None
        self._regime_detector = None
        self._risk_manager = None

        # State
        self._h1_buffer: list[dict] = []
        self._h4_buffer: list[dict] = []
        self._daily_buffer: list[dict] = []
        self._htf_last_fetch = 0.0
        self._news_cache: dict = {}
        self._news_cache_time = 0.0
        self._daily_pnl = 0.0
        self._trade_count_today = 0
        self._last_trade_bar = -100

    def load(self) -> bool:
        """Load all ML components."""
        try:
            from app.services.ml.ensemble_engine import EnsembleSignalEngine
            self._ensemble = EnsembleSignalEngine(
                symbol=self.symbol,
                timeframe="M5",
                min_agreement=self.min_agreement,
                min_confidence=self.min_confidence,
            )
            ensemble_loaded = self._ensemble.load_models()

            if not ensemble_loaded:
                logger.warning("[Expert %d] Ensemble models not loaded for %s — "
                               "run train_expert_agent.py first", self.agent_id, self.symbol)
                return False

            # Try to load regime detector
            try:
                from app.services.ml.regime_detector import RegimeDetector
                # Search for the expert regime model in the model directory
                import os
                from pathlib import Path
                model_dir = Path("data/ml_models")
                regime_path = model_dir / f"expert_{self.symbol}_M5_regime.joblib"
                if not regime_path.exists():
                    # Search by pattern
                    candidates = list(model_dir.glob(f"*regime*{self.symbol}*"))
                    if candidates:
                        regime_path = candidates[0]

                if regime_path.exists():
                    rd = RegimeDetector(model_id=0)
                    rd._model_path = str(regime_path)
                    if rd.load():
                        self._regime_detector = rd
                        logger.info("[Expert %d] Regime detector loaded", self.agent_id)
            except Exception as e:
                logger.warning("[Expert %d] Regime detector not available: %s", self.agent_id, e)

            logger.info("[Expert %d] Expert agent loaded for %s", self.agent_id, self.symbol)
            return True

        except Exception as e:
            logger.error("[Expert %d] Failed to load: %s", self.agent_id, e)
            return False

    async def evaluate(
        self,
        m5_bars: list[dict],
        broker_adapter=None,
    ) -> Optional[dict]:
        """
        Main evaluation — called on each new M5 bar.

        Returns trade signal dict or None (no trade).

        Signal dict:
          {
              "direction": 1 or -1,
              "confidence": float,
              "entry_price": float,
              "stop_loss": float,
              "take_profit": float,
              "lot_size": float,
              "reason": str,
              "regime": str,
              "session": str,
              "ensemble_votes": dict,
          }
        """
        if not self._ensemble:
            return None

        if len(m5_bars) < 60:
            return None

        current_bar = m5_bars[-1]
        current_price = current_bar.get("close", 0)
        if current_price <= 0:
            return None

        # ── Step 1: Fetch HTF context ──
        await self._fetch_htf_bars(broker_adapter)

        # ── Step 2: Compute expert features ──
        try:
            from app.services.ml.features_mtf import compute_expert_features
            feature_names, X = compute_expert_features(
                m5_bars,
                self._h1_buffer if self._h1_buffer else None,
                self._h4_buffer if self._h4_buffer else None,
                self._daily_buffer if self._daily_buffer else None,
            )

            if len(feature_names) == 0 or X.shape[0] == 0:
                return None

            # Get the latest feature vector and recent sequence
            latest_features = X[-1]
            if np.any(~np.isfinite(latest_features)):
                # Replace NaN with 0 for robustness
                latest_features = np.nan_to_num(latest_features, nan=0.0)

            # Build sequence for LSTM (last 60 bars)
            seq_len = min(60, X.shape[0])
            feature_sequence = X[-seq_len:]
            feature_sequence = np.nan_to_num(feature_sequence, nan=0.0)

        except Exception as e:
            logger.error("[Expert %d] Feature computation failed: %s", self.agent_id, e)
            return None

        # ── Step 3: News filter ──
        if self.news_filter_enabled:
            news_ok = await self._check_news_filter()
            if not news_ok:
                logger.info("[Expert %d] Trade blocked by news filter", self.agent_id)
                return None

        # ── Step 4: Session awareness ──
        session = self._get_current_session()
        session_risk_mult = 1.0

        if self.session_filter:
            if session == "dead_zone" and self.symbol != "BTCUSD":
                # Dead zone for non-crypto: skip trading
                logger.debug("[Expert %d] Dead zone — skipping", self.agent_id)
                return None

            if session == "asian" and self.symbol in ("XAUUSD", "US30"):
                # Asian session: reduce risk for Gold/Indices (low liquidity)
                session_risk_mult = 0.5

        # ── Step 5: Regime detection ──
        regime = "unknown"
        regime_risk_mult = 1.0

        if self._regime_detector and self.regime_filter:
            try:
                regime_ctx = self._regime_detector.predict_regime(m5_bars)
                if regime_ctx:
                    regime = regime_ctx.get("regime", "unknown")
                    regime_conf = regime_ctx.get("confidence", 0)

                    if regime == "volatile" and regime_conf > 0.5:
                        # Volatile regime: reduce risk by 40%
                        regime_risk_mult = 0.6
                    elif regime == "ranging" and regime_conf > 0.6:
                        # Ranging: reduce risk by 20% (fewer breakouts)
                        regime_risk_mult = 0.8
                    elif regime in ("trending_up", "trending_down"):
                        # Trending: slight boost
                        regime_risk_mult = 1.1
            except Exception as e:
                logger.warning("[Expert %d] Regime error: %s", self.agent_id, e)

        # ── Step 6: Ensemble vote ──
        try:
            ensemble_result = self._ensemble.predict(
                feature_vector=latest_features,
                feature_sequence=feature_sequence,
            )
        except Exception as e:
            logger.error("[Expert %d] Ensemble prediction failed: %s", self.agent_id, e)
            return None

        if not ensemble_result or ensemble_result["direction"] == 0:
            return None

        direction = ensemble_result["direction"]
        confidence = ensemble_result["confidence"]
        agreement = ensemble_result["agreement"]

        # ── Step 7: Cooldown check ──
        # Don't trade too frequently (min 3 bars between trades on M5 = 15 min)
        bar_index = len(m5_bars) - 1
        if bar_index - self._last_trade_bar < 3:
            return None

        # ── Step 8: Compute SL/TP ──
        sl, tp = self._compute_sl_tp(m5_bars, direction, current_price)

        if sl == 0 or tp == 0:
            return None

        # ── Step 9: Position sizing ──
        sl_distance = abs(current_price - sl)
        if sl_distance <= 0:
            return None

        # Risk amount adjusted by session and regime
        effective_risk = self.risk_per_trade * session_risk_mult * regime_risk_mult
        risk_amount = 10000 * effective_risk  # Assuming $10K account

        # Calculate lot size
        from app.services.agent.instrument_specs import calc_lot_size
        lot_size = calc_lot_size(self.symbol, risk_amount, sl_distance, broker_name=self.broker_name)

        if lot_size <= 0:
            return None

        self._last_trade_bar = bar_index

        signal = {
            "direction": direction,
            "confidence": confidence,
            "entry_price": current_price,
            "stop_loss": sl,
            "take_profit": tp,
            "lot_size": lot_size,
            "reason": ensemble_result["reason"],
            "regime": regime,
            "session": session,
            "ensemble_votes": ensemble_result.get("votes", {}),
            "agreement": agreement,
            "meta_approved": ensemble_result.get("meta_approved", True),
            "risk_per_trade": effective_risk,
            "signal_type": "expert_ensemble",
        }

        logger.info(
            "[Expert %d] SIGNAL: %s %s @ %.2f | SL=%.2f TP=%.2f | conf=%.1f%% | "
            "regime=%s session=%s | %s",
            self.agent_id,
            "BUY" if direction == 1 else "SELL",
            self.symbol,
            current_price,
            sl, tp,
            confidence * 100,
            regime, session,
            ensemble_result["reason"],
        )

        return signal

    def _compute_sl_tp(
        self,
        bars: list[dict],
        direction: int,
        entry_price: float,
    ) -> tuple[float, float]:
        """
        Compute dynamic SL/TP based on ATR and market structure.

        Uses ATR for base distance, adjusted by symbol-specific multipliers.
        """
        from app.services.backtest import indicators as ind

        highs = [b["high"] for b in bars[-50:]]
        lows = [b["low"] for b in bars[-50:]]
        closes = [b["close"] for b in bars[-50:]]

        atr_vals = ind.atr(highs, lows, closes, 14)
        atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0

        if atr <= 0:
            return 0.0, 0.0

        # Symbol-specific multipliers
        sl_mult = {"XAUUSD": 1.5, "US30": 1.5, "BTCUSD": 2.0}.get(self.symbol, 1.5)
        tp_mult = {"XAUUSD": 2.5, "US30": 2.0, "BTCUSD": 3.0}.get(self.symbol, 2.0)

        sl_dist = atr * sl_mult
        tp_dist = atr * tp_mult

        if direction == 1:  # BUY
            sl = entry_price - sl_dist
            tp = entry_price + tp_dist
        else:  # SELL
            sl = entry_price + sl_dist
            tp = entry_price - tp_dist

        return round(sl, 5), round(tp, 5)

    def _get_current_session(self) -> str:
        """Determine current trading session based on UTC time."""
        now = datetime.now(timezone.utc)
        hour = now.hour

        if 0 <= hour < 8:
            return "asian"
        elif 8 <= hour < 13:
            return "london"
        elif 13 <= hour < 21:
            return "new_york"
        else:
            return "dead_zone"

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
                logger.info("[Expert %d] News filter: %s", self.agent_id, result["reason"])

            return result["should_trade"]

        except Exception as e:
            logger.warning("[Expert %d] News check failed: %s", self.agent_id, e)
            return True  # Fail open

    async def _fetch_htf_bars(self, adapter=None):
        """Fetch H1, H4, and Daily bars from broker for MTF context."""
        import time as _time
        now = _time.time()

        # Refresh HTF data every 5 minutes (H1 bar is 60 min, so 5 min is fine)
        if now - self._htf_last_fetch < 300:
            return

        if adapter is None:
            try:
                from app.services.broker.manager import broker_manager
                adapter = broker_manager.get_adapter(self.broker_name)
            except Exception:
                return

        if adapter is None:
            return

        try:
            connected = await adapter.is_connected()
            if not connected:
                return
        except Exception:
            return

        try:
            # Fetch H1, H4, D1 in sequence (can't do truly parallel without asyncio.gather on brokers)
            for tf, buf_name, count in [("H1", "_h1_buffer", 200), ("H4", "_h4_buffer", 100), ("D1", "_daily_buffer", 50)]:
                try:
                    candles = await adapter.get_candles(self.symbol, tf, count)
                    if candles:
                        bars = [
                            {
                                "open": c.open,
                                "high": c.high,
                                "low": c.low,
                                "close": c.close,
                                "volume": c.volume,
                                "datetime": c.timestamp if hasattr(c, "timestamp") else None,
                            }
                            for c in candles
                        ]
                        setattr(self, buf_name, bars)
                        logger.debug("[Expert %d] Fetched %d %s bars", self.agent_id, len(bars), tf)
                except Exception as e:
                    logger.warning("[Expert %d] Failed to fetch %s bars: %s", self.agent_id, tf, e)

            self._htf_last_fetch = now

        except Exception as e:
            logger.warning("[Expert %d] HTF fetch error: %s", self.agent_id, e)

    def get_status(self) -> dict:
        """Return agent status for monitoring."""
        return {
            "agent_id": self.agent_id,
            "symbol": self.symbol,
            "type": "expert",
            "ensemble": self._ensemble.get_status() if self._ensemble else None,
            "regime_detector": self._regime_detector is not None,
            "config": {
                "risk_per_trade": self.risk_per_trade,
                "news_filter": self.news_filter_enabled,
                "session_filter": self.session_filter,
                "regime_filter": self.regime_filter,
                "min_agreement": self.min_agreement,
                "min_confidence": self.min_confidence,
            },
            "state": {
                "session": self._get_current_session(),
                "h1_bars": len(self._h1_buffer),
                "h4_bars": len(self._h4_buffer),
                "daily_bars": len(self._daily_buffer),
                "trade_count_today": self._trade_count_today,
            },
        }
