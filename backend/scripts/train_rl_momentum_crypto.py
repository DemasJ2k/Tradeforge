"""
Train RL Agent on Momentum Crypto Strategy (s45_momentum_crypto)
================================================================
Custom PPO agent for BTCUSD/ETHUSD D1 using the Momentum strategy:
  - ROC(10) + SMA(20) trend alignment + ATR(14) rising filter
  - Confirmed by RSI guard (avoid overbought/oversold entries)

Uses the `mom_25` feature space (25 dims):
  0-13: Shared features (returns, vol, ATR, RSI, WR, candle shape, volume ratio)
  14:   ROC(10) / 100.0 — rate of change normalized
  15:   (close - SMA20) / ATR — SMA distance
  16:   ATR slope over 5 bars
  17-23: Shared (hour sin/cos, ATR slope, momentum, high/low dist)
  24:   Signal type — 1.0 if ROC>0 AND close>SMA20 AND ATR rising;
                      -1.0 if ROC<0 AND close<SMA20 AND ATR rising; 0 otherwise

The agent sees:
  - Technical features (25 dims)
  - Position state (7 dims: position, PnL, drawdown, etc.)

Actions:
  0 = SKIP (reject signal)
  1 = TAKE (accept signal, direction from momentum)
  2 = CLOSE (close current position)

Usage:
  python train_rl_momentum_crypto.py --symbol BTCUSD --timesteps 1000000
  python train_rl_momentum_crypto.py --symbol ETHUSD --timesteps 500000 --n-envs 2
"""

import argparse
import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# -- Data loading --------------------------------------------------

def load_bars(csv_path):
    """Load CSV to list of bar dicts."""
    df = pd.read_csv(csv_path)
    df.columns = [c.strip().lower() for c in df.columns]

    # Handle column name variants
    if "tick_volume" in df.columns and "volume" not in df.columns:
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
    if "datetime" in df.columns and "time" not in df.columns:
        df.rename(columns={"datetime": "time"}, inplace=True)

    bars = []
    times = df["time"].astype(str).tolist()
    opens = df["open"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    closes = df["close"].tolist()
    vols = df["volume"].tolist() if "volume" in df.columns else [0.0] * len(df)

    for i in range(len(df)):
        bars.append({
            "time": times[i],
            "open": opens[i],
            "high": highs[i],
            "low": lows[i],
            "close": closes[i],
            "volume": vols[i],
        })
    return bars


# -- Indicators ----------------------------------------------------

def compute_atr(bars, period=14):
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


def compute_rsi(bars, period=14):
    """Wilder RSI."""
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


def compute_williams_r(bars, period=14):
    """Williams %R oscillator."""
    n = len(bars)
    out = np.full(n, -50.0)
    for i in range(period - 1, n):
        hh = max(bars[j]["high"] for j in range(i - period + 1, i + 1))
        ll = min(bars[j]["low"] for j in range(i - period + 1, i + 1))
        if hh != ll:
            out[i] = -100 * (hh - bars[i]["close"]) / (hh - ll)
    return out


def compute_sma(closes, period):
    """Simple moving average."""
    n = len(closes)
    sma = np.zeros(n)
    if n < period:
        return sma
    # First SMA value
    sma[period - 1] = np.mean(closes[:period])
    for i in range(period, n):
        sma[i] = sma[i - 1] + (closes[i] - closes[i - period]) / period
    return sma


def compute_roc(closes, period=10):
    """Rate of Change."""
    n = len(closes)
    roc = np.zeros(n)
    for i in range(period, n):
        if closes[i - period] != 0:
            roc[i] = (closes[i] - closes[i - period]) / closes[i - period] * 100
    return roc


# -- Feature matrix (mom_25) ----------------------------------------

def build_feature_matrix(bars, atr, wr, rsi, sma20, roc_10, closes,
                         roc_period=10, sma_period=20):
    """Build 25-dim mom_25 feature matrix for each bar.

    Features (25 dims):
      0: return_1      - 1-bar return
      1: return_3      - 3-bar return
      2: return_5      - 5-bar return
      3: return_10     - 10-bar return
      4: vol_5         - 5-bar volatility (%)
      5: vol_10        - 10-bar volatility (%)
      6: vol_20        - 20-bar volatility (%)
      7: atr_norm      - ATR normalized by price
      8: rsi           - RSI(14) normalized to [-1, 1]
      9: wr            - Williams %R normalized to [-1, 1]
     10: body_ratio    - candle body / range
     11: upper_wick    - upper wick / range
     12: lower_wick    - lower wick / range
     13: volume_ratio  - volume / 20-bar avg volume
     14: roc_norm      - ROC(10) / 100.0  (rate of change normalized)
     15: sma_dist      - (close - SMA20) / ATR  (SMA distance)
     16: atr_slope_5   - ATR slope over 5 bars
     17: hour_sin      - hour of day (sin encoding)
     18: hour_cos      - hour of day (cos encoding)
     19: atr_slope     - ATR trend (current - 5-bar ago, normalized)
     20: momentum_10   - 10-bar price momentum (%)
     21: momentum_20   - 20-bar price momentum (%)
     22: high_dist     - distance from 20-bar high (normalized)
     23: low_dist      - distance from 20-bar low (normalized)
     24: signal_type   - -1=short signal, 0=no signal, 1=long signal
    """
    n = len(bars)
    features = np.zeros((n, 25), dtype=np.float32)

    highs_arr = np.array([b["high"] for b in bars])
    lows_arr = np.array([b["low"] for b in bars])

    for i in range(30, n):
        c = bars[i]["close"]
        if c == 0:
            continue

        # Returns
        for j, lb in enumerate([1, 3, 5, 10]):
            if i >= lb:
                pc = bars[i - lb]["close"]
                features[i, j] = (c - pc) / pc if pc != 0 else 0

        # Volatility
        for j, w in enumerate([5, 10, 20]):
            if i >= w:
                rets = np.diff(closes[i - w:i + 1]) / closes[i - w:i]
                features[i, 4 + j] = np.std(rets) * 100

        # ATR, RSI, WR
        features[i, 7] = atr[i] / c if c != 0 else 0
        features[i, 8] = (rsi[i] - 50) / 50
        features[i, 9] = (wr[i] + 50) / 50

        # Candle shape
        o = bars[i]["open"]
        h = bars[i]["high"]
        l = bars[i]["low"]
        full = h - l
        if full > 0:
            features[i, 10] = (c - o) / full
            features[i, 11] = (h - max(c, o)) / full
            features[i, 12] = (min(c, o) - l) / full

        # Volume ratio
        if i >= 20:
            vols = [bars[k]["volume"] for k in range(i - 19, i + 1)]
            avg_vol = np.mean(vols)
            features[i, 13] = bars[i]["volume"] / avg_vol if avg_vol > 0 else 1.0

        # ROC(10) normalized
        features[i, 14] = roc_10[i] / 100.0

        # SMA distance: (close - SMA20) / ATR
        if sma20[i] > 0 and atr[i] > 0:
            features[i, 15] = (c - sma20[i]) / atr[i]

        # ATR slope over 5 bars
        if i >= 5 and atr[i] > 0:
            features[i, 16] = (atr[i] - atr[i - 5]) / atr[i]

        # Hour encoding
        try:
            time_str = bars[i]["time"]
            if "T" in time_str:
                hour = int(time_str.split("T")[1].split(":")[0])
            else:
                parts = time_str.split(" ")
                hour = int(parts[1].split(":")[0]) if len(parts) >= 2 else 12
        except (ValueError, IndexError):
            hour = 12
        features[i, 17] = np.sin(2 * np.pi * hour / 24)
        features[i, 18] = np.cos(2 * np.pi * hour / 24)

        # ATR slope (same as feature 16, kept for compatibility with shared layout)
        if i >= 5 and atr[i] > 0:
            features[i, 19] = (atr[i] - atr[i - 5]) / atr[i]

        # Momentum
        if i >= 10:
            features[i, 20] = (c - bars[i - 10]["close"]) / bars[i - 10]["close"] * 100
        if i >= 20:
            features[i, 21] = (c - bars[i - 20]["close"]) / bars[i - 20]["close"] * 100

        # Distance from recent high/low
        if i >= 20:
            h20 = max(highs_arr[i - 20:i + 1])
            l20 = min(lows_arr[i - 20:i + 1])
            rng = h20 - l20
            if rng > 0:
                features[i, 22] = (h20 - c) / rng
                features[i, 23] = (c - l20) / rng

        # Signal type (Momentum strategy):
        #   Long:  ROC(10) > 0 AND close > SMA(20) AND ATR rising
        #   Short: ROC(10) < 0 AND close < SMA(20) AND ATR rising
        atr_rising = (i >= 5 and atr[i] > atr[i - 5])
        if roc_10[i] > 0 and c > sma20[i] and atr_rising and rsi[i] < 80:
            features[i, 24] = 1.0
        elif roc_10[i] < 0 and c < sma20[i] and atr_rising and rsi[i] > 20:
            features[i, 24] = -1.0

    features = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
    return features


# -- Momentum Crypto RL Environment ----------------------------------

def create_momentum_env(bars, features, atr, sma20, closes,
                        spread=5.0, atr_sl_mult=2.0, atr_tp_mult=4.0,
                        cooldown=5, max_hold=50):
    """Create RL env for Momentum crypto signals on D1."""
    import gymnasium as gym
    from gymnasium import spaces

    class MomentumCryptoEnv(gym.Env):
        """
        RL env for crypto D1 Momentum signals.

        The agent is called ONLY when a momentum signal fires.
        Between signals, the env auto-advances and manages SL/TP.

        Key D1-specific adaptations:
          - ROC(10) + SMA(20) trend alignment
          - ATR rising filter for volatility expansion
          - RSI guard (no longs above 80, no shorts below 20)
          - Cooldown of 5 bars between trades
          - Max hold 50 bars (D1 = ~2.5 months)
        """
        metadata = {"render_modes": []}

        def __init__(self):
            super().__init__()
            self.bars = bars
            self.features = features
            self.atr = atr
            self.sma20 = sma20
            self.closes = closes
            self.n_bars = len(bars)
            self.spread = spread
            self.atr_sl_mult = atr_sl_mult
            self.atr_tp_mult = atr_tp_mult
            self.cooldown = cooldown
            self.max_hold = max_hold

            # 25 features + 7 context = 32
            self.observation_space = spaces.Box(
                low=-np.inf, high=np.inf, shape=(32,), dtype=np.float32,
            )
            self.action_space = spaces.Discrete(3)

            self.initial_balance = 10000.0
            self._reset_state()

        def _reset_state(self):
            self.balance = self.initial_balance
            self.peak_balance = self.initial_balance
            self.position_dir = 0
            self.entry_price = 0.0
            self.stop_loss = 0.0
            self.take_profit = 0.0
            self.bars_in_trade = 0
            self.bars_since_close = 0
            self.total_trades = 0
            self.winning_trades = 0
            self.total_pnl = 0.0
            self.trade_pnls = []

        def reset(self, seed=None, options=None):
            super().reset(seed=seed)
            self._reset_state()

            min_start = 35
            max_start = max(min_start + 1, self.n_bars - 1000)
            if max_start <= min_start:
                max_start = min_start + 1
            self.current_bar = self.np_random.integers(min_start, max_start)
            self.start_bar = self.current_bar
            self.episode_end = min(self.current_bar + 1500, self.n_bars - 1)

            self._advance_to_signal()
            return self._get_obs(), {}

        def _check_sl_tp(self, bar_idx):
            if self.position_dir == 0:
                return False
            bar = self.bars[bar_idx]
            closed = False
            if self.position_dir == 1:
                if self.stop_loss > 0 and bar["low"] <= self.stop_loss:
                    pnl = self.stop_loss - self.entry_price
                    self._close_position(pnl, "sl")
                    closed = True
                elif self.take_profit > 0 and bar["high"] >= self.take_profit:
                    pnl = self.take_profit - self.entry_price
                    self._close_position(pnl, "tp")
                    closed = True
            elif self.position_dir == -1:
                if self.stop_loss > 0 and bar["high"] >= self.stop_loss:
                    pnl = self.entry_price - self.stop_loss
                    self._close_position(pnl, "sl")
                    closed = True
                elif self.take_profit > 0 and bar["low"] <= self.take_profit:
                    pnl = self.entry_price - self.take_profit
                    self._close_position(pnl, "tp")
                    closed = True
            return closed

        def _close_position(self, pnl, reason=""):
            self.balance += pnl
            self.total_pnl += pnl
            self.trade_pnls.append(pnl)
            if pnl > 0:
                self.winning_trades += 1
            self.position_dir = 0
            self.entry_price = 0.0
            self.stop_loss = 0.0
            self.take_profit = 0.0
            self.bars_in_trade = 0
            self.bars_since_close = 0

        def _get_signal_direction(self, i):
            """Check if bar i has a momentum signal."""
            if i < 30 or self.atr[i] <= 0:
                return 0
            return int(self.features[i, 24])

        def _advance_to_signal(self):
            """Advance bars until a signal fires or episode ends."""
            while self.current_bar < self.episode_end:
                self._check_sl_tp(self.current_bar)
                if self.position_dir != 0:
                    self.bars_in_trade += 1
                    # Force close if held > max_hold bars (D1: ~2.5 months)
                    if self.bars_in_trade > self.max_hold:
                        c = self.bars[self.current_bar]["close"]
                        pnl = (c - self.entry_price) * self.position_dir
                        self._close_position(pnl, "timeout")
                else:
                    self.bars_since_close += 1
                self.peak_balance = max(self.peak_balance, self.balance)

                sig = self._get_signal_direction(self.current_bar)
                if sig != 0:
                    # Enforce cooldown: skip signal if too soon after last close
                    if self.position_dir == 0 and self.bars_since_close >= self.cooldown:
                        self._current_signal = sig
                        return
                    elif self.position_dir != 0:
                        # Already in position — let agent decide to close
                        self._current_signal = sig
                        return
                self.current_bar += 1

            self._current_signal = 0

        def step(self, action):
            reward = 0.0
            i = self.current_bar
            c = self.bars[i]["close"]
            atr_val = self.atr[i]

            if i >= self.episode_end:
                if self.position_dir != 0:
                    pnl = (c - self.entry_price) * self.position_dir
                    self._close_position(pnl, "end")
                    reward += pnl / self.initial_balance * 10
                return self._get_obs(), reward, True, False, self._get_info()

            sig = self._current_signal

            if action == 0:
                # SKIP
                pass

            elif action == 1 and self.position_dir == 0 and sig != 0:
                # TAKE signal
                direction = sig
                entry = c + self.spread * direction
                if direction == 1:
                    sl = entry - atr_val * self.atr_sl_mult
                    tp = entry + atr_val * self.atr_tp_mult
                else:
                    sl = entry + atr_val * self.atr_sl_mult
                    tp = entry - atr_val * self.atr_tp_mult

                self.position_dir = direction
                self.entry_price = entry
                self.stop_loss = sl
                self.take_profit = tp
                self.bars_in_trade = 0
                self.total_trades += 1

            elif action == 2 and self.position_dir != 0:
                # CLOSE position
                pnl = (c - self.entry_price) * self.position_dir
                self._close_position(pnl, "agent_close")
                reward += pnl / self.initial_balance * 10

            # Advance to next signal
            self.current_bar += 1
            self._advance_to_signal()

            # Reward from closed trades during advance
            if len(self.trade_pnls) > 0:
                recent_pnl = sum(self.trade_pnls)
                reward += recent_pnl / self.initial_balance * 10
                self.trade_pnls = []

            # Small skip penalty
            if action == 0 and sig != 0:
                reward -= 0.001

            # Drawdown penalty
            equity = self.balance
            if self.position_dir != 0:
                equity += (self.bars[min(self.current_bar, self.n_bars - 1)]["close"] - self.entry_price) * self.position_dir
            dd = (self.peak_balance - equity) / self.peak_balance if self.peak_balance > 0 else 0
            if dd > 0.05:
                reward -= dd * 0.1

            # Termination
            terminated = False
            if self.current_bar >= self.episode_end:
                terminated = True
                if self.position_dir != 0:
                    c_end = self.bars[min(self.current_bar, self.n_bars - 1)]["close"]
                    pnl = (c_end - self.entry_price) * self.position_dir
                    self._close_position(pnl, "end")
                    reward += pnl / self.initial_balance * 10
            elif self.balance < self.initial_balance * 0.7:
                terminated = True
                reward -= 1.0

            return self._get_obs(), float(reward), terminated, False, self._get_info()

        def _get_obs(self):
            idx = min(self.current_bar, self.n_bars - 1)
            feat = self.features[idx].copy()

            c = self.bars[idx]["close"]
            unrealized = 0.0
            if self.position_dir != 0 and self.entry_price > 0:
                unrealized = (c - self.entry_price) * self.position_dir / self.entry_price

            equity = self.balance + (unrealized * self.entry_price if self.position_dir != 0 else 0)
            dd = (self.peak_balance - equity) / self.peak_balance if self.peak_balance > 0 else 0

            context = np.array([
                float(self.position_dir),
                unrealized,
                (self.balance - self.initial_balance) / self.initial_balance,
                dd,
                min(self.bars_in_trade / 50.0, 1.0),  # Normalized by max_hold
                float(getattr(self, '_current_signal', 0)),
                self.total_trades / max(1, self.current_bar - self.start_bar) * 100,
            ], dtype=np.float32)

            return np.concatenate([feat, context]).astype(np.float32)

        def _get_info(self):
            wr = self.winning_trades / max(1, self.total_trades) * 100
            return {
                "balance": round(self.balance, 2),
                "total_pnl": round(self.total_pnl, 2),
                "total_trades": self.total_trades,
                "win_rate": round(wr, 1),
                "drawdown": round((self.peak_balance - self.balance) / self.peak_balance * 100, 1) if self.peak_balance > 0 else 0,
            }

    return MomentumCryptoEnv()


# -- ONNX Export ---------------------------------------------------

def export_onnx(model, output_path, obs_size=32):
    """Export trained PPO model to ONNX format."""
    try:
        import torch
        import torch.onnx

        policy = model.policy
        policy.eval()

        dummy_input = torch.zeros(1, obs_size, dtype=torch.float32)
        dummy_input = dummy_input.to(policy.device)

        class PolicyWrapper(torch.nn.Module):
            def __init__(self, policy):
                super().__init__()
                self.policy = policy

            def forward(self, obs):
                features = self.policy.extract_features(obs, self.policy.features_extractor)
                latent_pi = self.policy.mlp_extractor.forward_actor(features)
                action_logits = self.policy.action_net(latent_pi)
                return action_logits

        wrapper = PolicyWrapper(policy)
        wrapper.eval()

        torch.onnx.export(
            wrapper,
            dummy_input,
            output_path,
            input_names=["obs"],
            output_names=["action_logits"],
            dynamic_axes={"obs": {0: "batch"}, "action_logits": {0: "batch"}},
            opset_version=18,
            dynamo=False,
        )
        print(f"  ONNX exported: {output_path}")
        return True
    except Exception as e:
        print(f"  ONNX export failed: {e}")
        return False


# -- Main training -------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Train RL on Momentum crypto signals (D1)")
    parser.add_argument("--symbol", type=str, default="BTCUSD",
                        choices=["BTCUSD", "ETHUSD"],
                        help="Symbol to train on (BTCUSD or ETHUSD)")
    parser.add_argument("--timesteps", type=int, default=1000000)
    parser.add_argument("--n-envs", type=int, default=4, help="Parallel envs")
    parser.add_argument("--output-dir", default=os.path.join(os.path.dirname(__file__), "..", "data", "ml_models"))
    args = parser.parse_args()

    symbol = args.symbol.upper()

    # Symbol-specific config
    if symbol == "BTCUSD":
        csv_path = r"D:\Doc\DATA\Backtest Data\BTCUSD_D1.csv"
        spread = 5.0         # $5 BTC spread
    elif symbol == "ETHUSD":
        csv_path = r"D:\Doc\DATA\Backtest Data\ETHUSD_D1.csv"
        spread = 0.50        # $0.50 ETH spread
    else:
        print(f"ERROR: Unknown symbol {symbol}")
        return

    # Momentum strategy parameters
    roc_period = 10
    sma_period = 20
    atr_period = 14
    atr_sl_mult = 2.0     # SL = 2.0x ATR
    atr_tp_mult = 4.0     # TP = 4.0x ATR
    cooldown = 5           # 5 bars between trades
    max_hold = 50          # Max hold 50 bars (D1 = ~2.5 months)

    model_prefix = f"rl_mom_{symbol.lower()}_d1"

    print(f"\n{'=' * 60}")
    print(f"  Training RL Agent -- {symbol} D1 (Momentum Crypto)")
    print(f"  Strategy: s45_momentum_crypto (mom_25 features)")
    print(f"  Timesteps: {args.timesteps:,}")
    print(f"  Spread: ${spread}")
    print(f"  SL: {atr_sl_mult}x ATR  |  TP: {atr_tp_mult}x ATR")
    print(f"  ROC period: {roc_period}  |  SMA period: {sma_period}")
    print(f"  ATR period: {atr_period}  |  Cooldown: {cooldown} bars")
    print(f"  Max hold: {max_hold} bars")
    print(f"{'=' * 60}")

    # Load data
    print(f"\n  Loading bars from {csv_path}...")
    bars = load_bars(csv_path)
    print(f"  Loaded {len(bars):,} bars")

    # Compute indicators
    print("  Computing indicators...")
    closes = np.array([b["close"] for b in bars])
    atr = compute_atr(bars, atr_period)
    wr = compute_williams_r(bars, 14)
    rsi = compute_rsi(bars, 14)
    sma20 = compute_sma(closes, sma_period)
    roc_10 = compute_roc(closes, roc_period)

    # Build features
    print("  Building mom_25 feature matrix...")
    features = build_feature_matrix(bars, atr, wr, rsi, sma20, roc_10, closes,
                                    roc_period=roc_period, sma_period=sma_period)
    print(f"  Feature matrix shape: {features.shape}")

    # Count signals
    n_long = int(np.sum(features[:, 24] > 0))
    n_short = int(np.sum(features[:, 24] < 0))
    print(f"  Momentum signals: {n_long + n_short:,} (long={n_long:,}, short={n_short:,})")

    if n_long + n_short == 0:
        print("  ERROR: No signals found! Check data and indicator parameters.")
        return

    # Import RL libs
    try:
        import gymnasium as gym
        from stable_baselines3 import PPO
        from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize
        from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback
    except ImportError:
        print("ERROR: gymnasium and stable-baselines3 required!")
        print("  pip install gymnasium stable-baselines3")
        return

    # Create vectorized environments
    print(f"  Creating {args.n_envs} parallel environments...")

    def make_env():
        def _init():
            return create_momentum_env(
                bars, features, atr, sma20, closes,
                spread=spread,
                atr_sl_mult=atr_sl_mult,
                atr_tp_mult=atr_tp_mult,
                cooldown=cooldown,
                max_hold=max_hold,
            )
        return _init

    env = DummyVecEnv([make_env() for _ in range(args.n_envs)])
    env = VecNormalize(env, norm_obs=True, norm_reward=True, clip_obs=10.0)

    # Eval env
    eval_env = DummyVecEnv([make_env()])
    eval_env = VecNormalize(eval_env, norm_obs=True, norm_reward=False, clip_obs=10.0)

    # Callbacks
    os.makedirs(args.output_dir, exist_ok=True)
    checkpoint_dir = os.path.join(args.output_dir, f"{model_prefix}_checkpoints")
    os.makedirs(checkpoint_dir, exist_ok=True)

    callbacks = [
        CheckpointCallback(
            save_freq=max(50000, args.timesteps // 10),
            save_path=checkpoint_dir,
            name_prefix=model_prefix,
        ),
        EvalCallback(
            eval_env,
            best_model_save_path=args.output_dir,
            log_path=checkpoint_dir,
            eval_freq=max(25000, args.timesteps // 20),
            n_eval_episodes=10,
            deterministic=True,
        ),
    ]

    # Create PPO agent
    print("  Initializing PPO agent...")
    model = PPO(
        "MlpPolicy",
        env,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=256,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,
        vf_coef=0.5,
        max_grad_norm=0.5,
        policy_kwargs=dict(
            net_arch=dict(pi=[256, 256], vf=[256, 256]),
        ),
        verbose=1,
    )

    # Train
    print(f"\n  Training for {args.timesteps:,} timesteps...")
    t0 = time.time()
    model.learn(total_timesteps=args.timesteps, callback=callbacks, progress_bar=False)
    elapsed = time.time() - t0
    print(f"\n  Training complete in {elapsed:.0f}s ({elapsed/60:.1f} min)")

    # Save final model
    model_path = os.path.join(args.output_dir, f"{model_prefix}_final")
    model.save(model_path)
    env.save(os.path.join(args.output_dir, f"{model_prefix}_vecnorm.pkl"))
    print(f"  Model saved: {model_path}.zip")
    print(f"  VecNormalize saved: {model_prefix}_vecnorm.pkl")

    # ONNX export
    onnx_path = os.path.join(args.output_dir, f"{model_prefix}_final.onnx")
    export_onnx(model, onnx_path, obs_size=32)

    # Evaluate
    print("\n  Running evaluation (50 episodes)...")
    eval_results = []
    for ep in range(50):
        obs = eval_env.reset()
        done = False
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, done, info = eval_env.step(action)
        eval_results.append(info[0])

    # Summarize
    avg_pnl = np.mean([r["total_pnl"] for r in eval_results])
    avg_trades = np.mean([r["total_trades"] for r in eval_results])
    avg_wr = np.mean([r["win_rate"] for r in eval_results])
    avg_dd = np.mean([r["drawdown"] for r in eval_results])
    pnl_std = np.std([r["total_pnl"] for r in eval_results])

    print(f"\n  Evaluation Results (50 episodes):")
    print(f"    Avg P&L:      ${avg_pnl:,.2f} (+/- ${pnl_std:,.2f})")
    print(f"    Avg Trades:   {avg_trades:.0f}")
    print(f"    Avg Win Rate: {avg_wr:.1f}%")
    print(f"    Avg Max DD:   {avg_dd:.1f}%")

    # Save stats as NPZ
    stats_path = os.path.join(args.output_dir, f"{model_prefix}_stats.npz")
    np.savez(
        stats_path,
        eval_pnls=np.array([r["total_pnl"] for r in eval_results]),
        eval_trades=np.array([r["total_trades"] for r in eval_results]),
        eval_win_rates=np.array([r["win_rate"] for r in eval_results]),
        eval_drawdowns=np.array([r["drawdown"] for r in eval_results]),
    )
    print(f"  Stats saved: {stats_path}")

    # Save results as JSON
    results = {
        "symbol": symbol,
        "strategy": "momentum_crypto",
        "strategy_id": "s45_momentum_crypto",
        "feature_space": "mom_25",
        "timeframe": "D1",
        "timesteps": args.timesteps,
        "training_time_s": round(elapsed),
        "model_path": model_path + ".zip",
        "onnx_path": onnx_path,
        "eval_avg_pnl": round(avg_pnl, 2),
        "eval_pnl_std": round(pnl_std, 2),
        "eval_avg_trades": round(avg_trades, 1),
        "eval_avg_wr": round(avg_wr, 1),
        "eval_avg_dd": round(avg_dd, 1),
        "config": {
            "spread": spread,
            "roc_period": roc_period,
            "sma_period": sma_period,
            "atr_period": atr_period,
            "atr_sl_mult": atr_sl_mult,
            "atr_tp_mult": atr_tp_mult,
            "cooldown": cooldown,
            "max_hold": max_hold,
        },
    }
    results_path = os.path.join(args.output_dir, f"{model_prefix}_results.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Results saved: {results_path}")

    print(f"\n{'=' * 60}")
    print(f"  {symbol} D1 Momentum RL training complete!")
    print(f"  Output prefix: {model_prefix}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
