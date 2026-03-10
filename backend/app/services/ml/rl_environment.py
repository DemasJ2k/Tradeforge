"""
Gymnasium-based trading environment for RL agent training.

Observation space (~40 dims):
  - 30 technical features (from existing feature pipeline)
  - regime_id (0-3)
  - position_direction (-1, 0, 1)
  - position_pnl (unrealized P&L as fraction of balance)
  - unrealized_return (price change since entry)
  - current_drawdown (from peak equity)
  - time_in_trade (bars since entry, normalized)
  - bars_since_last_trade (normalized)

Action space: Discrete(5)
  0 = WAIT (do nothing)
  1 = BUY_MARKET (open long)
  2 = SELL_MARKET (open short)
  3 = CLOSE_POSITION (close any open position)
  4 = TRAIL_STOP (tighten stop by 50%)

Reward: Risk-adjusted P&L with penalties.

Requires: gymnasium>=0.29 (local only)
"""

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Action constants
WAIT = 0
BUY = 1
SELL = 2
CLOSE = 3
TRAIL = 4

ACTION_NAMES = {0: "wait", 1: "buy", 2: "sell", 3: "close", 4: "trail"}


def create_trading_env(
    ohlcv_data: list[dict],
    feature_matrix: np.ndarray,
    initial_balance: float = 10000.0,
    commission: float = 0.0002,
    spread: float = 0.0001,
    max_position_hold: int = 100,
    reward_scaling: float = 1.0,
):
    """
    Factory to create TradingEnv with Gymnasium.

    Keeps gymnasium import inside function so the module can be
    imported on Render without gymnasium installed.
    """
    try:
        import gymnasium as gym
        from gymnasium import spaces
    except ImportError:
        raise ImportError(
            "gymnasium required for RL training. "
            "Install locally: pip install gymnasium>=0.29"
        )

    class TradingEnv(gym.Env):
        """
        Custom Gymnasium environment for training RL trading agents.
        """
        metadata = {"render_modes": []}

        def __init__(self):
            super().__init__()

            self.ohlcv = ohlcv_data
            self.features = feature_matrix  # (n_bars, n_features)
            self.n_bars = len(feature_matrix)
            self.n_features = feature_matrix.shape[1]
            self.initial_balance = initial_balance
            self.commission = commission
            self.spread = spread
            self.max_hold = max_position_hold
            self.reward_scale = reward_scaling

            # State dimensions: features + 7 position/context features
            obs_dim = self.n_features + 7
            self.observation_space = spaces.Box(
                low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32,
            )
            self.action_space = spaces.Discrete(5)

            # Internal state
            self._reset_state()

        def _reset_state(self):
            self.balance = self.initial_balance
            self.peak_balance = self.initial_balance
            self.position_dir = 0        # -1, 0, 1
            self.entry_price = 0.0
            self.stop_loss = 0.0
            self.bars_in_trade = 0
            self.bars_since_close = 0
            self.total_trades = 0
            self.winning_trades = 0
            self.total_pnl = 0.0

        def reset(self, seed=None, options=None):
            super().reset(seed=seed)

            self._reset_state()

            # Random start point (leave room for episode)
            min_start = 50  # Need some warmup
            max_start = max(min_start + 1, self.n_bars - 500)
            if max_start <= min_start:
                max_start = min_start + 1

            self.current_bar = self.np_random.integers(min_start, max_start)
            self.start_bar = self.current_bar

            return self._get_obs(), {}

        def step(self, action: int):
            if self.current_bar >= self.n_bars - 1:
                return self._get_obs(), 0.0, True, False, self._get_info()

            reward = 0.0
            current_close = self.ohlcv[self.current_bar]["close"]
            next_bar = self.current_bar + 1
            next_close = self.ohlcv[next_bar]["close"]

            # Execute action
            if action == BUY and self.position_dir == 0:
                # Open long
                self.position_dir = 1
                self.entry_price = current_close * (1 + self.spread)
                self.stop_loss = self.entry_price * 0.98  # 2% default SL
                self.bars_in_trade = 0
                self.bars_since_close = 0
                self.total_trades += 1
                self.balance -= current_close * self.commission
                reward -= 0.001  # Small cost for trading

            elif action == SELL and self.position_dir == 0:
                # Open short
                self.position_dir = -1
                self.entry_price = current_close * (1 - self.spread)
                self.stop_loss = self.entry_price * 1.02  # 2% default SL
                self.bars_in_trade = 0
                self.bars_since_close = 0
                self.total_trades += 1
                self.balance -= current_close * self.commission
                reward -= 0.001

            elif action == CLOSE and self.position_dir != 0:
                # Close position
                pnl = self._calc_pnl(current_close)
                self.balance += pnl
                self.balance -= abs(pnl) * self.commission
                self.total_pnl += pnl
                if pnl > 0:
                    self.winning_trades += 1
                reward += pnl / self.initial_balance * self.reward_scale
                self.position_dir = 0
                self.entry_price = 0.0
                self.bars_in_trade = 0
                self.bars_since_close = 0

            elif action == TRAIL and self.position_dir != 0:
                # Tighten stop by 50%
                if self.position_dir == 1:
                    distance = current_close - self.stop_loss
                    self.stop_loss = current_close - distance * 0.5
                else:
                    distance = self.stop_loss - current_close
                    self.stop_loss = current_close + distance * 0.5

            elif action == WAIT:
                # Do nothing
                pass

            # Advance bar
            self.current_bar = next_bar
            self.bars_since_close += 1

            # Update position state
            if self.position_dir != 0:
                self.bars_in_trade += 1

                # Check stop loss hit
                bar = self.ohlcv[self.current_bar]
                if self.position_dir == 1 and bar["low"] <= self.stop_loss:
                    pnl = (self.stop_loss - self.entry_price) * self.position_dir
                    self.balance += pnl
                    self.total_pnl += pnl
                    reward += pnl / self.initial_balance * self.reward_scale
                    self.position_dir = 0
                    self.bars_in_trade = 0

                elif self.position_dir == -1 and bar["high"] >= self.stop_loss:
                    pnl = (self.entry_price - self.stop_loss) * abs(self.position_dir)
                    self.balance += pnl
                    self.total_pnl += pnl
                    reward += pnl / self.initial_balance * self.reward_scale
                    self.position_dir = 0
                    self.bars_in_trade = 0

                # Forced close if held too long
                elif self.bars_in_trade >= self.max_hold:
                    pnl = self._calc_pnl(next_close)
                    self.balance += pnl
                    self.total_pnl += pnl
                    reward += pnl / self.initial_balance * self.reward_scale
                    reward -= 0.005  # Penalty for holding too long
                    self.position_dir = 0
                    self.bars_in_trade = 0

                # Unrealized P&L as reward shaping
                else:
                    unrealized = self._calc_pnl(next_close)
                    reward += unrealized / self.initial_balance * 0.1 * self.reward_scale

            # Update peak balance
            equity = self.balance + (self._calc_pnl(next_close) if self.position_dir != 0 else 0)
            self.peak_balance = max(self.peak_balance, equity)

            # Penalties
            # Drawdown penalty
            dd = (self.peak_balance - equity) / self.peak_balance if self.peak_balance > 0 else 0
            if dd > 0.1:  # >10% drawdown
                reward -= dd * 0.01

            # Overtrading penalty (more than 1 trade per 5 bars on average)
            bars_elapsed = max(1, self.current_bar - self.start_bar)
            if self.total_trades > 0 and bars_elapsed / self.total_trades < 5:
                reward -= 0.001

            # Check if episode should end
            terminated = False
            if self.balance <= self.initial_balance * 0.5:  # 50% drawdown → game over
                terminated = True
                reward -= 1.0  # Big penalty for blowing up

            if self.current_bar >= self.n_bars - 2:
                terminated = True
                # Close any open position
                if self.position_dir != 0:
                    pnl = self._calc_pnl(next_close)
                    self.balance += pnl
                    self.total_pnl += pnl
                    reward += pnl / self.initial_balance * self.reward_scale

            truncated = False

            return self._get_obs(), float(reward), terminated, truncated, self._get_info()

        def _calc_pnl(self, current_price: float) -> float:
            """Calculate unrealized P&L."""
            if self.position_dir == 0:
                return 0.0
            if self.position_dir == 1:
                return current_price - self.entry_price
            else:
                return self.entry_price - current_price

        def _get_obs(self) -> np.ndarray:
            """Build observation vector."""
            if self.current_bar >= self.n_bars:
                return np.zeros(self.observation_space.shape[0], dtype=np.float32)

            features = self.features[self.current_bar].copy()
            current_price = self.ohlcv[self.current_bar]["close"]

            # Position context features
            unrealized_return = 0.0
            if self.position_dir != 0 and self.entry_price > 0:
                unrealized_return = self._calc_pnl(current_price) / self.entry_price

            equity = self.balance + (self._calc_pnl(current_price) if self.position_dir != 0 else 0)
            drawdown = (self.peak_balance - equity) / self.peak_balance if self.peak_balance > 0 else 0

            context = np.array([
                0.0,  # regime_id placeholder (set externally if available)
                float(self.position_dir),
                self._calc_pnl(current_price) / self.initial_balance,
                unrealized_return,
                drawdown,
                min(self.bars_in_trade / self.max_hold, 1.0),
                min(self.bars_since_close / 50.0, 1.0),
            ], dtype=np.float32)

            obs = np.concatenate([features, context]).astype(np.float32)
            return obs

        def _get_info(self) -> dict:
            current_price = self.ohlcv[min(self.current_bar, self.n_bars - 1)]["close"]
            equity = self.balance + (self._calc_pnl(current_price) if self.position_dir != 0 else 0)
            return {
                "balance": self.balance,
                "equity": equity,
                "total_pnl": self.total_pnl,
                "total_trades": self.total_trades,
                "winning_trades": self.winning_trades,
                "win_rate": self.winning_trades / max(1, self.total_trades),
                "drawdown": (self.peak_balance - equity) / self.peak_balance if self.peak_balance > 0 else 0,
                "bars_elapsed": self.current_bar - self.start_bar,
            }

    return TradingEnv()
