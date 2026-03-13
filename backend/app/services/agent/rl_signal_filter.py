"""
RL Signal Filter — PPO-based filter for strategy signals.

Loads an ONNX PPO policy and decides:
  0 = SKIP (reject this signal)
  1 = TAKE (accept the signal, enter trade)
  2 = CLOSE (close current position)

Supports multiple feature spaces:
  - lw_25: Larry Williams breakout (prev_range breakout levels)
  - mb_25: Momentum-Breakout (ATR envelope + ROC momentum + RSI guard)

Feature space: 25 technical features + 7 position context = 32 dims.
Requires only onnxruntime + numpy (no SB3/gymnasium).
"""

import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

ACTION_NAMES = {0: "skip", 1: "take", 2: "close"}


# ── Indicator helpers (exact replicas from train_rl_larry_williams.py) ──


def _compute_atr(bars: list[dict], period: int = 20) -> np.ndarray:
    """Wilder-smoothed ATR."""
    n = len(bars)
    trs = np.zeros(n)
    for i in range(1, n):
        trs[i] = max(
            bars[i]["high"] - bars[i]["low"],
            abs(bars[i]["high"] - bars[i - 1]["close"]),
            abs(bars[i]["low"] - bars[i - 1]["close"]),
        )
    out = np.zeros(n)
    if period + 1 > n:
        return out
    out[period] = np.mean(trs[1:period + 1])
    for i in range(period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + trs[i]) / period
    return out


def _compute_williams_r(bars: list[dict], period: int = 14) -> np.ndarray:
    """Williams %R oscillator."""
    n = len(bars)
    out = np.full(n, -50.0)
    for i in range(period - 1, n):
        hh = max(bars[j]["high"] for j in range(i - period + 1, i + 1))
        ll = min(bars[j]["low"] for j in range(i - period + 1, i + 1))
        if hh != ll:
            out[i] = -100 * (hh - bars[i]["close"]) / (hh - ll)
    return out


def _compute_rsi(bars: list[dict], period: int = 14) -> np.ndarray:
    """RSI with Wilder smoothing."""
    n = len(bars)
    out = np.full(n, 50.0)
    if n < period + 1:
        return out
    gains = np.zeros(n)
    losses = np.zeros(n)
    for i in range(1, n):
        diff = bars[i]["close"] - bars[i - 1]["close"]
        gains[i] = diff if diff > 0 else 0
        losses[i] = -diff if diff < 0 else 0
    avg_gain = np.mean(gains[1:period + 1])
    avg_loss = np.mean(losses[1:period + 1])
    for i in range(period, n):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i] = 100 - (100 / (1 + rs))
    return out


def _compute_ema(values: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average (for MB feature space)."""
    n = len(values)
    ema = np.zeros(n)
    if n < period:
        return ema
    ema[period - 1] = np.mean(values[:period])
    mult = 2.0 / (period + 1)
    for i in range(period, n):
        ema[i] = values[i] * mult + ema[i - 1] * (1 - mult)
    return ema


def _compute_roc(closes: np.ndarray, period: int = 10) -> np.ndarray:
    """Rate of Change (for MB feature space)."""
    n = len(closes)
    roc = np.zeros(n)
    for i in range(period, n):
        if closes[i - period] != 0:
            roc[i] = (closes[i] - closes[i - period]) / closes[i - period] * 100
    return roc


# ── Feature builder (exact replica of build_feature_matrix) ──


def _build_features_for_bar(
    bars: list[dict],
    bar_idx: int,
    atr: np.ndarray,
    wr: np.ndarray,
    rsi: np.ndarray,
    breakout_factor: float = 0.6,
) -> np.ndarray:
    """Build 25-dim feature vector for a single bar.

    Feature layout (same as train_rl_larry_williams.py):
      0: return_1       1: return_3       2: return_5       3: return_10
      4: vol_5          5: vol_10         6: vol_20
      7: atr_norm       8: rsi            9: wr
     10: body_ratio    11: upper_wick    12: lower_wick
     13: volume_ratio
     14: breakout_long 15: breakout_short 16: prev_range
     17: hour_sin      18: hour_cos
     19: atr_slope
     20: momentum_10   21: momentum_20
     22: high_dist     23: low_dist
     24: signal_type
    """
    feat = np.zeros(25, dtype=np.float32)
    i = bar_idx
    c = bars[i]["close"]
    if c == 0 or i < 30:
        return feat

    closes = np.array([b["close"] for b in bars[max(0, i - 25):i + 1]])
    highs_arr = np.array([b["high"] for b in bars[max(0, i - 25):i + 1]])
    lows_arr = np.array([b["low"] for b in bars[max(0, i - 25):i + 1]])
    offset = i - max(0, i - 25)  # index of current bar within slice

    # Returns
    for j, lb in enumerate([1, 3, 5, 10]):
        if i >= lb:
            pc = bars[i - lb]["close"]
            feat[j] = (c - pc) / pc if pc != 0 else 0

    # Volatility
    all_closes = [b["close"] for b in bars[max(0, i - 20):i + 1]]
    for j, w in enumerate([5, 10, 20]):
        if i >= w:
            seg = [b["close"] for b in bars[i - w:i + 1]]
            seg_arr = np.array(seg)
            rets = np.diff(seg_arr) / seg_arr[:-1]
            feat[4 + j] = np.std(rets) * 100

    # ATR, RSI, WR
    feat[7] = atr[i] / c if c != 0 else 0
    feat[8] = (rsi[i] - 50) / 50
    feat[9] = (wr[i] + 50) / 50

    # Candle shape
    o = bars[i]["open"]
    h = bars[i]["high"]
    low = bars[i]["low"]
    full = h - low
    if full > 0:
        feat[10] = (c - o) / full
        feat[11] = (h - max(c, o)) / full
        feat[12] = (min(c, o) - low) / full

    # Volume ratio
    if i >= 20:
        vols = [bars[k]["volume"] for k in range(i - 19, i + 1)]
        avg_vol = np.mean(vols)
        feat[13] = bars[i]["volume"] / avg_vol if avg_vol > 0 else 1.0

    # Breakout levels
    prev_range = bars[i - 1]["high"] - bars[i - 1]["low"]
    buy_level = o + breakout_factor * prev_range
    sell_level = o - breakout_factor * prev_range
    if atr[i] > 0:
        feat[14] = max(0, (c - buy_level) / atr[i])
        feat[15] = max(0, (sell_level - c) / atr[i])
        feat[16] = prev_range / atr[i]

    # Hour encoding
    try:
        time_str = bars[i].get("time", "")
        if isinstance(time_str, str):
            if "T" in time_str:
                hour = int(time_str.split("T")[1].split(":")[0])
            else:
                parts = time_str.split(" ")
                hour = int(parts[1].split(":")[0]) if len(parts) >= 2 else 12
        else:
            hour = 12
    except (ValueError, IndexError):
        hour = 12
    feat[17] = np.sin(2 * np.pi * hour / 24)
    feat[18] = np.cos(2 * np.pi * hour / 24)

    # ATR slope
    if i >= 5:
        feat[19] = (atr[i] - atr[i - 5]) / atr[i] if atr[i] > 0 else 0

    # Momentum
    if i >= 10:
        feat[20] = (c - bars[i - 10]["close"]) / bars[i - 10]["close"] * 100
    if i >= 20:
        feat[21] = (c - bars[i - 20]["close"]) / bars[i - 20]["close"] * 100

    # Distance from recent high/low
    if i >= 20:
        h20 = max(b["high"] for b in bars[i - 20:i + 1])
        l20 = min(b["low"] for b in bars[i - 20:i + 1])
        rng = h20 - l20
        if rng > 0:
            feat[22] = (h20 - c) / rng
            feat[23] = (c - l20) / rng

    # Signal type
    if h >= buy_level and c > buy_level:
        feat[24] = 1.0
    elif low <= sell_level and c < sell_level:
        feat[24] = -1.0

    # Clean
    feat = np.nan_to_num(feat, nan=0.0, posinf=0.0, neginf=0.0)
    return feat


# ── MB Feature builder (momentum-breakout, from train_rl_btcusd_momentum.py) ──


def _build_mb_features_for_bar(
    bars: list[dict],
    bar_idx: int,
    atr: np.ndarray,
    wr: np.ndarray,
    rsi: np.ndarray,
    ema20: np.ndarray,
    roc10: np.ndarray,
    atr_breakout_mult: float = 2.0,
) -> np.ndarray:
    """Build 25-dim feature vector for a single bar (Momentum-Breakout space).

    Shared features 0-13 and 17-23 are identical to LW.
    Differs in features 14-16 and 24:
      14: breakout_up   - how far price is above upper ATR band (norm by ATR)
      15: breakout_down - how far price is below lower ATR band (norm by ATR)
      16: roc_10        - 10-bar rate of change (normalized)
      24: signal_type   - momentum-breakout signal (-1=short, 0=none, 1=long)
    """
    feat = np.zeros(25, dtype=np.float32)
    i = bar_idx
    c = bars[i]["close"]
    if c == 0 or i < 30:
        return feat

    # ── Shared features 0-13 (identical to LW) ──

    # Returns
    for j, lb in enumerate([1, 3, 5, 10]):
        if i >= lb:
            pc = bars[i - lb]["close"]
            feat[j] = (c - pc) / pc if pc != 0 else 0

    # Volatility
    for j, w in enumerate([5, 10, 20]):
        if i >= w:
            seg = [b["close"] for b in bars[i - w:i + 1]]
            seg_arr = np.array(seg)
            rets = np.diff(seg_arr) / seg_arr[:-1]
            feat[4 + j] = np.std(rets) * 100

    # ATR, RSI, WR
    feat[7] = atr[i] / c if c != 0 else 0
    feat[8] = (rsi[i] - 50) / 50
    feat[9] = (wr[i] + 50) / 50

    # Candle shape
    o = bars[i]["open"]
    h = bars[i]["high"]
    low = bars[i]["low"]
    full = h - low
    if full > 0:
        feat[10] = (c - o) / full
        feat[11] = (h - max(c, o)) / full
        feat[12] = (min(c, o) - low) / full

    # Volume ratio
    if i >= 20:
        vols = [bars[k]["volume"] for k in range(i - 19, i + 1)]
        avg_vol = np.mean(vols)
        feat[13] = bars[i]["volume"] / avg_vol if avg_vol > 0 else 1.0

    # ── MB-specific features 14-16 (ATR envelope breakout + ROC) ──

    upper_band = ema20[i] + atr[i] * atr_breakout_mult
    lower_band = ema20[i] - atr[i] * atr_breakout_mult
    if atr[i] > 0:
        feat[14] = max(0, (c - upper_band) / atr[i])
        feat[15] = max(0, (lower_band - c) / atr[i])

    # ROC(10) normalized (replaces prev_range in LW)
    feat[16] = roc10[i] / 100.0

    # ── Shared features 17-23 ──

    # Hour encoding
    try:
        time_str = bars[i].get("time", "")
        if isinstance(time_str, str):
            if "T" in time_str:
                hour = int(time_str.split("T")[1].split(":")[0])
            else:
                parts = time_str.split(" ")
                hour = int(parts[1].split(":")[0]) if len(parts) >= 2 else 12
        else:
            hour = 12
    except (ValueError, IndexError):
        hour = 12
    feat[17] = np.sin(2 * np.pi * hour / 24)
    feat[18] = np.cos(2 * np.pi * hour / 24)

    # ATR slope
    if i >= 5:
        feat[19] = (atr[i] - atr[i - 5]) / atr[i] if atr[i] > 0 else 0

    # Momentum
    if i >= 10:
        feat[20] = (c - bars[i - 10]["close"]) / bars[i - 10]["close"] * 100
    if i >= 20:
        feat[21] = (c - bars[i - 20]["close"]) / bars[i - 20]["close"] * 100

    # Distance from recent high/low
    if i >= 20:
        h20 = max(b["high"] for b in bars[i - 20:i + 1])
        l20 = min(b["low"] for b in bars[i - 20:i + 1])
        rng = h20 - l20
        if rng > 0:
            feat[22] = (h20 - c) / rng
            feat[23] = (c - l20) / rng

    # ── MB-specific feature 24 (momentum-breakout signal) ──
    # Long: price above upper band + positive momentum + RSI not overbought
    if c > upper_band and roc10[i] > 0 and rsi[i] < 80:
        feat[24] = 1.0
    # Short: price below lower band + negative momentum + RSI not oversold
    elif c < lower_band and roc10[i] < 0 and rsi[i] > 20:
        feat[24] = -1.0

    # Clean
    feat = np.nan_to_num(feat, nan=0.0, posinf=0.0, neginf=0.0)
    return feat


# ── RL Signal Filter ─────────────────────────────────────────────────


class RLSignalFilter:
    """
    RL-based signal filter for strategy signals.

    Loads an ONNX PPO policy and filters strategy signals using the same
    feature space as the training environment.

    Supports feature spaces:
      - "lw_25": Larry Williams breakout (prev_range breakout levels)
      - "mb_25": Momentum-Breakout (ATR envelope + ROC + RSI guard)

    Action space: 0=SKIP, 1=TAKE, 2=CLOSE
    Observation: 25 features + 7 context = 32 dims
    """

    SUPPORTED_FEATURE_SPACES = {"lw_25", "mb_25"}

    def __init__(self, onnx_path: str, stats_path: Optional[str] = None,
                 feature_space: str = "lw_25"):
        self.onnx_path = onnx_path
        self.stats_path = stats_path or onnx_path.replace(".onnx", "_stats.npz")
        self.feature_space = feature_space if feature_space in self.SUPPORTED_FEATURE_SPACES else "lw_25"
        self._session = None
        self._obs_mean = None
        self._obs_var = None
        self._clip_obs = 10.0
        self._loaded = False

        # Cached indicator arrays (recomputed when bar buffer changes length)
        self._cached_n_bars = 0
        self._atr = None
        self._wr = None
        self._rsi = None
        self._ema20 = None   # Only for mb_25
        self._roc10 = None   # Only for mb_25

    def load(self) -> bool:
        """Load ONNX model and normalization stats."""
        if not os.path.exists(self.onnx_path):
            logger.warning("[RLFilter] ONNX model not found: %s", self.onnx_path)
            return False

        try:
            import onnxruntime as ort

            self._session = ort.InferenceSession(self.onnx_path)

            # Load normalization stats
            if os.path.exists(self.stats_path):
                stats = np.load(self.stats_path)
                self._obs_mean = stats.get("obs_mean")
                self._obs_var = stats.get("obs_var")
                if "clip_obs" in stats:
                    self._clip_obs = float(stats["clip_obs"][0]) if stats["clip_obs"].ndim > 0 else float(stats["clip_obs"])
                logger.info("[RLFilter] Loaded normalization stats from %s", self.stats_path)
            else:
                logger.warning("[RLFilter] No stats file found at %s, running without normalization", self.stats_path)

            self._loaded = True
            logger.info("[RLFilter] Loaded ONNX model: %s", self.onnx_path)
            return True

        except ImportError:
            logger.error("[RLFilter] onnxruntime not installed")
            return False
        except Exception as e:
            logger.error("[RLFilter] Failed to load: %s", e)
            return False

    def _update_indicators(self, bars: list[dict]):
        """Recompute indicators if bar buffer size changed."""
        n = len(bars)
        if n != self._cached_n_bars:
            self._atr = _compute_atr(bars, 20)
            self._wr = _compute_williams_r(bars, 14)
            self._rsi = _compute_rsi(bars, 14)
            # MB feature space also needs EMA20 and ROC10
            if self.feature_space == "mb_25":
                closes = np.array([b["close"] for b in bars])
                self._ema20 = _compute_ema(closes, 20)
                self._roc10 = _compute_roc(closes, 10)
            self._cached_n_bars = n

    def evaluate_signal(
        self,
        strategy_direction: int,
        strategy_confidence: float,
        bars: list[dict],
        position_dir: int = 0,
        position_pnl: float = 0.0,
        unrealized_return: float = 0.0,
        drawdown: float = 0.0,
        bars_in_trade: int = 0,
        total_trades: int = 0,
        bars_elapsed: int = 1,
        regime_context: Optional[dict] = None,
        **kwargs,
    ) -> dict:
        """
        Evaluate a strategy signal through the RL filter.

        Returns dict compatible with MLSignalFilter interface:
            approved: bool
            combined_confidence: float
            rl_action: str ("skip", "take", "close")
            rl_action_id: int
            rl_confidence: float
            close_position: bool (True if RL wants to close existing position)
            reason: str
            probabilities: dict
        """
        if not self._loaded:
            return {
                "approved": True,
                "combined_confidence": strategy_confidence,
                "rl_action": "take",
                "rl_action_id": 1,
                "rl_confidence": 0.0,
                "close_position": False,
                "reason": "RL filter not loaded, passing through",
                "probabilities": {},
            }

        if len(bars) < 35:
            return {
                "approved": True,
                "combined_confidence": strategy_confidence,
                "rl_action": "take",
                "rl_action_id": 1,
                "rl_confidence": 0.0,
                "close_position": False,
                "reason": "Insufficient bars for RL filter (need 35+)",
                "probabilities": {},
            }

        try:
            # Update cached indicators
            self._update_indicators(bars)

            # Build features for the last bar (select feature builder by space)
            bar_idx = len(bars) - 1
            if self.feature_space == "mb_25":
                features = _build_mb_features_for_bar(
                    bars, bar_idx, self._atr, self._wr, self._rsi,
                    self._ema20, self._roc10,
                    atr_breakout_mult=2.0,
                )
            else:
                features = _build_features_for_bar(
                    bars, bar_idx, self._atr, self._wr, self._rsi,
                )

            # Build context vector (7 dims, same order as training env _get_obs)
            context = np.array([
                float(position_dir),
                unrealized_return,
                position_pnl,          # running P&L as fraction of initial balance
                drawdown,
                min(bars_in_trade / 100.0, 1.0),
                float(strategy_direction),  # current signal direction (-1, 0, 1)
                total_trades / max(1, bars_elapsed) * 100,  # trade frequency
            ], dtype=np.float32)

            # Concatenate: 25 features + 7 context = 32
            obs = np.concatenate([features, context]).astype(np.float32)

            # Normalize with VecNormalize stats
            if self._obs_mean is not None and self._obs_var is not None:
                obs = (obs - self._obs_mean) / np.sqrt(self._obs_var + 1e-8)
                obs = np.clip(obs, -self._clip_obs, self._clip_obs)

            # Run ONNX inference
            input_name = self._session.get_inputs()[0].name
            result = self._session.run(None, {input_name: obs.reshape(1, -1)})
            logits = result[0][0]

            # Softmax for probabilities
            exp_logits = np.exp(logits - np.max(logits))
            probs = exp_logits / exp_logits.sum()

            action = int(np.argmax(probs))
            confidence = float(probs[action])
            action_name = ACTION_NAMES.get(action, f"action_{action}")

            prob_dict = {ACTION_NAMES.get(i, f"a{i}"): round(float(p), 4) for i, p in enumerate(probs)}

            # Map action to filter decision
            if action == 0:  # SKIP
                return {
                    "approved": False,
                    "combined_confidence": 0.0,
                    "rl_action": "skip",
                    "rl_action_id": 0,
                    "rl_confidence": round(confidence, 4),
                    "close_position": False,
                    "reason": f"RL filter: skip signal (conf={confidence:.1%})",
                    "probabilities": prob_dict,
                }
            elif action == 1:  # TAKE
                # Boost or attenuate confidence based on RL certainty
                rl_boost = 0.8 + 0.4 * confidence  # Range: 0.8 to 1.2
                combined = min(strategy_confidence * rl_boost, 1.0)
                return {
                    "approved": True,
                    "combined_confidence": round(combined, 4),
                    "rl_action": "take",
                    "rl_action_id": 1,
                    "rl_confidence": round(confidence, 4),
                    "close_position": False,
                    "reason": f"RL filter: take signal (conf={confidence:.1%})",
                    "probabilities": prob_dict,
                }
            else:  # CLOSE (action == 2)
                return {
                    "approved": False,
                    "combined_confidence": 0.0,
                    "rl_action": "close",
                    "rl_action_id": 2,
                    "rl_confidence": round(confidence, 4),
                    "close_position": position_dir != 0,
                    "reason": f"RL filter: close position (conf={confidence:.1%})",
                    "probabilities": prob_dict,
                }

        except Exception as e:
            logger.error("[RLFilter] Decision failed: %s", e)
            return {
                "approved": True,
                "combined_confidence": strategy_confidence,
                "rl_action": "error",
                "rl_action_id": -1,
                "rl_confidence": 0.0,
                "close_position": False,
                "reason": f"RL filter error: {e}",
                "probabilities": {},
            }
