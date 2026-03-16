"""
Train RL Agent on Larry Williams V2 (H1) -- With SMA50 Trend Filter
====================================================================
PPO agent trained to filter Williams breakout signals on US30 H1.
Uses V2 params: BF=0.5, SL=2.0x ATR, TP=6.0x ATR, SMA50 trend filter.

The RL agent sees the same signals the V2 strategy would generate,
but decides whether to TAKE or SKIP each one, plus can CLOSE early.

Usage:
  python train_rl_lw_h1.py --timesteps 2000000
"""

import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def load_bars(csv_path):
    df = pd.read_csv(csv_path)
    df.columns = [c.strip().lower() for c in df.columns]
    if "tick_volume" in df.columns and "volume" not in df.columns:
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
    bars = []
    times = df["time"].astype(str).tolist()
    opens = df["open"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    closes = df["close"].tolist()
    vols = df["volume"].tolist() if "volume" in df.columns else [0.0] * len(df)
    for i in range(len(df)):
        bars.append({
            "time": times[i], "open": opens[i], "high": highs[i],
            "low": lows[i], "close": closes[i], "volume": vols[i],
        })
    return bars


def compute_atr(bars, period=14):
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


def compute_sma(bars, period=50):
    n = len(bars)
    out = np.zeros(n)
    if period > n:
        return out
    s = sum(bars[j]["close"] for j in range(period))
    out[period - 1] = s / period
    for i in range(period, n):
        s += bars[i]["close"] - bars[i - period]["close"]
        out[i] = s / period
    return out


def compute_williams_r(bars, period=14):
    n = len(bars)
    out = np.full(n, -50.0)
    for i in range(period - 1, n):
        hh = max(bars[j]["high"] for j in range(i - period + 1, i + 1))
        ll = min(bars[j]["low"] for j in range(i - period + 1, i + 1))
        if hh != ll:
            out[i] = -100 * (hh - bars[i]["close"]) / (hh - ll)
    return out


def compute_rsi(bars, period=14):
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


def build_feature_matrix(bars, atr, sma, wr, rsi, breakout_factor=0.5):
    """Build feature matrix with SMA trend context.

    Features (28 dims):
      0-3:   returns (1,3,5,10)
      4-6:   volatility (5,10,20)
      7:     atr_norm
      8:     rsi normalized
      9:     wr normalized
      10-12: candle shape (body, upper wick, lower wick)
      13:    volume ratio
      14-15: breakout distance (long/short)
      16:    prev_range / ATR
      17-18: hour encoding (sin/cos)
      19:    atr slope
      20-21: momentum (10,20)
      22-23: distance from 20-bar high/low
      24:    signal type (-1/0/1)
      25:    trend direction (close vs SMA: >0 = above, <0 = below)
      26:    sma slope (current - 10-bar ago, normalized)
      27:    distance from SMA (normalized by ATR)
    """
    n = len(bars)
    features = np.zeros((n, 28), dtype=np.float32)
    closes = np.array([b["close"] for b in bars])
    highs_arr = np.array([b["high"] for b in bars])
    lows_arr = np.array([b["low"] for b in bars])

    for i in range(55, n):
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

        # Breakout levels
        prev_range = bars[i - 1]["high"] - bars[i - 1]["low"]
        buy_level = o + breakout_factor * prev_range
        sell_level = o - breakout_factor * prev_range
        if atr[i] > 0:
            features[i, 14] = max(0, (c - buy_level) / atr[i])
            features[i, 15] = max(0, (sell_level - c) / atr[i])
            features[i, 16] = prev_range / atr[i]

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

        # ATR slope
        if i >= 5:
            features[i, 19] = (atr[i] - atr[i - 5]) / atr[i] if atr[i] > 0 else 0

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

        # Signal type (with SMA trend filter like V2)
        sma_val = sma[i]
        if h >= buy_level and c > buy_level and sma_val > 0 and c > sma_val:
            features[i, 24] = 1.0
        elif l <= sell_level and c < sell_level and sma_val > 0 and c < sma_val:
            features[i, 24] = -1.0

        # NEW: Trend context features
        if sma_val > 0:
            features[i, 25] = (c - sma_val) / sma_val * 100  # % distance from SMA
            if atr[i] > 0:
                features[i, 27] = (c - sma_val) / atr[i]  # ATR-normalized distance
        if i >= 10 and sma[i - 10] > 0:
            features[i, 26] = (sma[i] - sma[i - 10]) / sma[i - 10] * 100  # SMA slope

    features = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
    return features


def create_lw_h1_env(bars, features, atr, sma,
                      breakout_factor=0.5, spread=1.0,
                      atr_sl_mult=2.0, atr_tp_mult=6.0,
                      cooldown_bars=20):
    """RL env for Larry Williams V2 on H1 with SMA50 trend filter."""
    import gymnasium as gym
    from gymnasium import spaces

    class LWH1Env(gym.Env):
        """
        RL env for H1 Williams breakout.
        Only presents signals that pass the SMA50 trend filter.
        Longer timeouts (200 bars = 200 hours) vs M5.
        Includes cooldown between trades like V2.
        """
        metadata = {"render_modes": []}

        def __init__(self):
            super().__init__()
            self.bars = bars
            self.features = features
            self.atr = atr
            self.sma = sma
            self.n_bars = len(bars)
            self.breakout_factor = breakout_factor
            self.spread = spread
            self.atr_sl_mult = atr_sl_mult
            self.atr_tp_mult = atr_tp_mult
            self.cooldown_bars = cooldown_bars

            # 28 features + 7 context = 35
            self.observation_space = spaces.Box(
                low=-np.inf, high=np.inf, shape=(35,), dtype=np.float32,
            )
            self.action_space = spaces.Discrete(3)  # SKIP, TAKE, CLOSE
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
            self.last_trade_bar = -999
            self.total_trades = 0
            self.winning_trades = 0
            self.total_pnl = 0.0
            self.trade_pnls = []

        def reset(self, seed=None, options=None):
            super().reset(seed=seed)
            self._reset_state()
            # H1: 50K bars, use episodes of ~8000 bars (~1 year)
            min_start = 60
            max_start = max(min_start + 1, self.n_bars - 10000)
            if max_start <= min_start:
                max_start = min_start + 1
            self.current_bar = self.np_random.integers(min_start, max_start)
            self.start_bar = self.current_bar
            self.episode_end = min(self.current_bar + 8000, self.n_bars - 1)
            self._advance_to_signal()
            return self._get_obs(), {}

        def _check_sl_tp(self, bar_idx):
            if self.position_dir == 0:
                return False
            bar = self.bars[bar_idx]
            if self.position_dir == 1:
                if self.stop_loss > 0 and bar["low"] <= self.stop_loss:
                    pnl = self.stop_loss - self.entry_price
                    self._close_position(pnl, "sl")
                    return True
                elif self.take_profit > 0 and bar["high"] >= self.take_profit:
                    pnl = self.take_profit - self.entry_price
                    self._close_position(pnl, "tp")
                    return True
            elif self.position_dir == -1:
                if self.stop_loss > 0 and bar["high"] >= self.stop_loss:
                    pnl = self.entry_price - self.stop_loss
                    self._close_position(pnl, "sl")
                    return True
                elif self.take_profit > 0 and bar["low"] <= self.take_profit:
                    pnl = self.entry_price - self.take_profit
                    self._close_position(pnl, "tp")
                    return True
            return False

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

        def _get_signal_direction(self, i):
            """Check if bar i has a V2-style breakout signal (with SMA filter)."""
            if i < 2 or self.atr[i] <= 0:
                return 0
            prev = self.bars[i - 1]
            prev_range = prev["high"] - prev["low"]
            if prev_range <= 0:
                return 0
            bar = self.bars[i]
            buy_level = bar["open"] + self.breakout_factor * prev_range
            sell_level = bar["open"] - self.breakout_factor * prev_range
            c = bar["close"]
            sma_val = self.sma[i]
            if sma_val <= 0:
                return 0
            # Long: price breaks out above AND above SMA (uptrend)
            if bar["high"] >= buy_level and c > buy_level and c > sma_val:
                return 1
            # Short: price breaks out below AND below SMA (downtrend)
            elif bar["low"] <= sell_level and c < sell_level and c < sma_val:
                return -1
            return 0

        def _advance_to_signal(self):
            while self.current_bar < self.episode_end:
                self._check_sl_tp(self.current_bar)
                if self.position_dir != 0:
                    self.bars_in_trade += 1
                    # Force close after 200 bars (200 hours on H1)
                    if self.bars_in_trade > 200:
                        c = self.bars[self.current_bar]["close"]
                        pnl = (c - self.entry_price) * self.position_dir
                        self._close_position(pnl, "timeout")
                self.peak_balance = max(self.peak_balance, self.balance)

                sig = self._get_signal_direction(self.current_bar)
                if sig != 0 and self.position_dir == 0:
                    # Only present signal if cooldown passed
                    if self.current_bar - self.last_trade_bar >= self.cooldown_bars:
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
                # TAKE
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
                self.last_trade_bar = self.current_bar
            elif action == 2 and self.position_dir != 0:
                # CLOSE early
                pnl = (c - self.entry_price) * self.position_dir
                self._close_position(pnl, "agent_close")
                reward += pnl / self.initial_balance * 10

            self.current_bar += 1
            self._advance_to_signal()

            # Reward from resolved trades
            if len(self.trade_pnls) > 0:
                recent_pnl = sum(self.trade_pnls)
                reward += recent_pnl / self.initial_balance * 10
                self.trade_pnls = []

            # Small penalty for skipping (less aggressive than M5)
            if action == 0 and sig != 0:
                reward -= 0.0005

            # Drawdown penalty
            equity = self.balance
            if self.position_dir != 0:
                idx = min(self.current_bar, self.n_bars - 1)
                equity += (self.bars[idx]["close"] - self.entry_price) * self.position_dir
            dd = (self.peak_balance - equity) / self.peak_balance if self.peak_balance > 0 else 0
            if dd > 0.05:
                reward -= dd * 0.15  # Stronger DD penalty for higher WR goal

            # Win rate bonus: reward winning trades more
            if len(self.trade_pnls) == 0 and action == 1 and self.position_dir != 0:
                # Just entered a trade, no immediate reward
                pass

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
                reward -= 2.0

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
                min(self.bars_in_trade / 200.0, 1.0),
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

    return LWH1Env()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Train RL on Larry Williams V2 (H1)")
    parser.add_argument("--timesteps", type=int, default=2000000)
    parser.add_argument("--n-envs", type=int, default=4)
    parser.add_argument("--output-dir", default=os.path.join(os.path.dirname(__file__), "..", "data", "ml_models"))
    args = parser.parse_args()

    csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "uploads", "1772956289_US30_H1_50320bars.csv")
    print(f"\n{'=' * 60}")
    print(f"  Training RL Agent -- US30 H1 (Larry Williams V2)")
    print(f"  Timesteps: {args.timesteps:,}")
    print(f"  Params: BF=0.5, SL=2.0x, TP=6.0x, SMA50, CD=20")
    print(f"{'=' * 60}")

    print(f"\n  Loading bars from {csv_path}...")
    bars = load_bars(csv_path)
    print(f"  Loaded {len(bars):,} bars")

    print("  Computing indicators...")
    atr = compute_atr(bars, 14)
    sma = compute_sma(bars, 50)
    wr = compute_williams_r(bars, 14)
    rsi = compute_rsi(bars, 14)

    print("  Building feature matrix...")
    features = build_feature_matrix(bars, atr, sma, wr, rsi, breakout_factor=0.5)
    print(f"  Feature matrix shape: {features.shape}")

    n_signals = np.sum(np.abs(features[:, 24]) > 0)
    print(f"  Total breakout signals (SMA-filtered): {n_signals:,}")

    try:
        import gymnasium as gym
        from stable_baselines3 import PPO
        from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize
        from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback
    except ImportError:
        print("ERROR: gymnasium and stable-baselines3 required!")
        print("  pip install gymnasium stable-baselines3")
        return

    print(f"  Creating {args.n_envs} parallel environments...")

    def make_env():
        def _init():
            return create_lw_h1_env(
                bars, features, atr, sma,
                breakout_factor=0.5, spread=1.0,
                atr_sl_mult=2.0, atr_tp_mult=6.0,
                cooldown_bars=20,
            )
        return _init

    env = DummyVecEnv([make_env() for _ in range(args.n_envs)])
    env = VecNormalize(env, norm_obs=True, norm_reward=True, clip_obs=10.0)

    eval_env = DummyVecEnv([make_env()])
    eval_env = VecNormalize(eval_env, norm_obs=True, norm_reward=False, clip_obs=10.0)

    os.makedirs(args.output_dir, exist_ok=True)
    checkpoint_dir = os.path.join(args.output_dir, "rl_lw_us30_h1_checkpoints")
    os.makedirs(checkpoint_dir, exist_ok=True)

    callbacks = [
        CheckpointCallback(
            save_freq=max(50000, args.timesteps // 10),
            save_path=checkpoint_dir,
            name_prefix="rl_lw_us30_h1",
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

    print("  Initializing PPO agent...")
    model = PPO(
        "MlpPolicy",
        env,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=256,
        n_epochs=10,
        gamma=0.995,       # Higher gamma for H1 (longer horizon)
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

    print(f"\n  Training for {args.timesteps:,} timesteps...")
    t0 = time.time()
    model.learn(total_timesteps=args.timesteps, callback=callbacks, progress_bar=False)
    elapsed = time.time() - t0
    print(f"\n  Training complete in {elapsed:.0f}s ({elapsed/60:.1f} min)")

    # Save
    model_path = os.path.join(args.output_dir, "rl_lw_us30_h1_final")
    model.save(model_path)
    env.save(os.path.join(args.output_dir, "rl_lw_us30_h1_vecnorm.pkl"))
    print(f"  Model saved: {model_path}.zip")

    # Export ONNX
    try:
        import torch
        import onnx
        policy = model.policy.to("cpu")
        dummy_input = torch.zeros(1, 35)
        onnx_path = os.path.join(args.output_dir, "rl_lw_us30_h1.onnx")
        torch.onnx.export(
            policy, dummy_input, onnx_path,
            input_names=["obs"], output_names=["action"],
            opset_version=11,
        )
        print(f"  ONNX exported: {onnx_path}")
    except Exception as e:
        print(f"  ONNX export failed: {e}")

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

    results = {
        "symbol": "US30",
        "timeframe": "H1",
        "strategy": "larry_williams_v2",
        "timesteps": args.timesteps,
        "training_time_s": round(elapsed),
        "model_path": model_path + ".zip",
        "params": {
            "breakout_factor": 0.5,
            "atr_sl_mult": 2.0,
            "atr_tp_mult": 6.0,
            "sma_period": 50,
            "cooldown_bars": 20,
        },
        "eval_avg_pnl": round(avg_pnl, 2),
        "eval_pnl_std": round(pnl_std, 2),
        "eval_avg_trades": round(avg_trades, 1),
        "eval_avg_wr": round(avg_wr, 1),
        "eval_avg_dd": round(avg_dd, 1),
    }
    results_path = os.path.join(args.output_dir, "rl_lw_us30_h1_results.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Results saved: {results_path}")

    # Compare with base strategy
    print(f"\n  {'=' * 50}")
    print(f"  Comparison: Base V2 vs RL-Filtered")
    print(f"  {'=' * 50}")
    print(f"  Base V2:     PF 1.064, WR 27.9%, DD 53.7%, +$8,999")
    print(f"  RL-Filtered: WR {avg_wr:.1f}%, DD {avg_dd:.1f}%, P&L ${avg_pnl:,.0f}/episode")
    print(f"  {'=' * 50}")


if __name__ == "__main__":
    main()
