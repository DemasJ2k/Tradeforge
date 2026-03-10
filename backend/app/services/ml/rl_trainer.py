"""
RL Training Pipeline using Stable-Baselines3.

Trains a PPO agent on the TradingEnv.
Exports policy as ONNX for lightweight Render inference.

Requires: stable-baselines3>=2.3, gymnasium>=0.29, torch>=2.0 (local only)
"""

import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)

_MODEL_DIR = Path(settings.UPLOAD_DIR).parent / "ml_models"
_MODEL_DIR.mkdir(parents=True, exist_ok=True)


class RLTrainer:
    """
    PPO-based RL training pipeline for autonomous trading.
    """

    def __init__(self, model_id: int = 0):
        self.model_id = model_id
        self._model_path = str(_MODEL_DIR / f"rl_ppo_{model_id}")
        self._onnx_path = str(_MODEL_DIR / f"rl_ppo_{model_id}.onnx")
        self._stats_path = str(_MODEL_DIR / f"rl_ppo_{model_id}_stats.npz")

    def train(
        self,
        ohlcv_data: list[dict],
        total_timesteps: int = 500000,
        hidden_sizes: tuple = (256, 256),
        learning_rate: float = 3e-4,
        n_steps: int = 2048,
        batch_size: int = 64,
        n_epochs: int = 10,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        clip_range: float = 0.2,
        ent_coef: float = 0.01,
        eval_freq: int = 10000,
        commission: float = 0.0002,
        spread: float = 0.0001,
        features_config: Optional[dict] = None,
    ) -> dict:
        """
        Train PPO agent on OHLCV data.

        Returns dict with training stats.
        """
        try:
            import torch
            from stable_baselines3 import PPO
            from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize
            from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback
        except ImportError:
            raise ImportError(
                "RL training requires stable-baselines3, gymnasium, and torch. "
                "Install: pip install stable-baselines3[extra] gymnasium torch"
            )

        if len(ohlcv_data) < 500:
            raise ValueError(f"Need at least 500 bars for RL training, got {len(ohlcv_data)}")

        # Build feature matrix
        feature_matrix = self._build_features(ohlcv_data, features_config)

        # Split data: 80% train, 20% eval
        split = int(len(feature_matrix) * 0.8)
        train_data = ohlcv_data[:split]
        train_features = feature_matrix[:split]
        eval_data = ohlcv_data[split:]
        eval_features = feature_matrix[split:]

        from app.services.ml.rl_environment import create_trading_env

        # Create environments
        def make_train_env():
            return create_trading_env(
                train_data, train_features,
                commission=commission, spread=spread,
            )

        def make_eval_env():
            return create_trading_env(
                eval_data, eval_features,
                commission=commission, spread=spread,
            )

        train_env = DummyVecEnv([make_train_env])
        train_env = VecNormalize(train_env, norm_obs=True, norm_reward=True, clip_obs=10.0)

        eval_env = DummyVecEnv([make_eval_env])
        eval_env = VecNormalize(eval_env, norm_obs=True, norm_reward=False, clip_obs=10.0)

        # Callbacks
        checkpoint_dir = str(_MODEL_DIR / f"rl_checkpoints_{self.model_id}")
        os.makedirs(checkpoint_dir, exist_ok=True)

        eval_callback = EvalCallback(
            eval_env,
            best_model_save_path=checkpoint_dir,
            eval_freq=eval_freq,
            n_eval_episodes=5,
            deterministic=True,
        )

        checkpoint_callback = CheckpointCallback(
            save_freq=eval_freq * 2,
            save_path=checkpoint_dir,
            name_prefix="rl_ppo",
        )

        # Create PPO model
        policy_kwargs = dict(
            net_arch=dict(pi=list(hidden_sizes), vf=list(hidden_sizes)),
        )

        model = PPO(
            "MlpPolicy",
            train_env,
            learning_rate=learning_rate,
            n_steps=n_steps,
            batch_size=batch_size,
            n_epochs=n_epochs,
            gamma=gamma,
            gae_lambda=gae_lambda,
            clip_range=clip_range,
            ent_coef=ent_coef,
            policy_kwargs=policy_kwargs,
            verbose=1,
            device="auto",
        )

        logger.info(
            "Starting RL training: %d timesteps, %d train bars, %d eval bars",
            total_timesteps, len(train_data), len(eval_data),
        )

        # Train
        model.learn(
            total_timesteps=total_timesteps,
            callback=[eval_callback, checkpoint_callback],
        )

        # Save model
        model.save(self._model_path)

        # Save VecNormalize stats for inference
        train_env.save(self._stats_path.replace(".npz", "_vecnorm.pkl"))

        # Export to ONNX
        onnx_exported = self._export_onnx(model, train_env)

        # Evaluate on eval set
        eval_results = self.evaluate(eval_data, eval_features, model, eval_env)

        result = {
            "model_path": self._model_path + ".zip",
            "onnx_path": self._onnx_path if onnx_exported else None,
            "total_timesteps": total_timesteps,
            "n_train_bars": len(train_data),
            "n_eval_bars": len(eval_data),
            "n_features": feature_matrix.shape[1],
            "hidden_sizes": list(hidden_sizes),
            "eval_results": eval_results,
        }

        logger.info("RL training complete: %s", result)
        return result

    def evaluate(
        self,
        ohlcv_data: list[dict],
        feature_matrix: np.ndarray,
        model=None,
        vec_env=None,
    ) -> dict:
        """Evaluate RL agent on data. Returns trading metrics."""
        from app.services.ml.rl_environment import create_trading_env

        env = create_trading_env(ohlcv_data, feature_matrix)

        if model is None:
            try:
                from stable_baselines3 import PPO
                model = PPO.load(self._model_path)
            except Exception as e:
                logger.error("Failed to load RL model: %s", e)
                return {}

        obs, _ = env.reset()

        # Normalize obs if we have vec_env
        if vec_env is not None:
            obs = vec_env.normalize_obs(obs.reshape(1, -1)).flatten()

        total_reward = 0
        steps = 0
        actions_taken = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}

        done = False
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            action = int(action)
            actions_taken[action] = actions_taken.get(action, 0) + 1

            obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated

            if vec_env is not None:
                obs = vec_env.normalize_obs(obs.reshape(1, -1)).flatten()

            total_reward += reward
            steps += 1

        return {
            "total_reward": round(total_reward, 4),
            "total_pnl": round(info.get("total_pnl", 0), 2),
            "total_trades": info.get("total_trades", 0),
            "win_rate": round(info.get("win_rate", 0), 4),
            "max_drawdown": round(info.get("drawdown", 0), 4),
            "final_balance": round(info.get("balance", 0), 2),
            "steps": steps,
            "actions": actions_taken,
        }

    def _export_onnx(self, model, vec_env) -> bool:
        """Export PPO policy to ONNX."""
        try:
            import torch

            policy = model.policy
            policy.eval()

            obs_dim = model.observation_space.shape[0]
            dummy_input = torch.randn(1, obs_dim)

            # Extract just the actor network for ONNX
            class PolicyWrapper(torch.nn.Module):
                def __init__(self, policy):
                    super().__init__()
                    self.features_extractor = policy.features_extractor
                    self.mlp_extractor = policy.mlp_extractor
                    self.action_net = policy.action_net

                def forward(self, x):
                    features = self.features_extractor(x)
                    latent_pi, _ = self.mlp_extractor(features)
                    return self.action_net(latent_pi)

            wrapper = PolicyWrapper(policy)
            wrapper.eval()

            torch.onnx.export(
                wrapper, dummy_input, self._onnx_path,
                input_names=["obs"],
                output_names=["action_logits"],
                dynamic_axes={"obs": {0: "batch"}, "action_logits": {0: "batch"}},
                opset_version=14,
            )

            # Save normalization stats alongside ONNX
            if vec_env is not None:
                np.savez(
                    self._stats_path,
                    obs_mean=vec_env.obs_rms.mean,
                    obs_var=vec_env.obs_rms.var,
                    clip_obs=vec_env.clip_obs,
                )

            logger.info("Exported RL ONNX: %s (%.1f KB)",
                        self._onnx_path, os.path.getsize(self._onnx_path) / 1024)
            return True

        except Exception as e:
            logger.error("ONNX export failed: %s", e)
            return False

    @staticmethod
    def _build_features(
        ohlcv_data: list[dict],
        features_config: Optional[dict] = None,
    ) -> np.ndarray:
        """Build feature matrix from OHLCV data."""
        from app.services.ml.features import compute_features

        opens = [d["open"] for d in ohlcv_data]
        highs = [d["high"] for d in ohlcv_data]
        lows = [d["low"] for d in ohlcv_data]
        closes = [d["close"] for d in ohlcv_data]
        volumes = [d.get("volume", 0) for d in ohlcv_data]

        config = features_config or {
            "features": [
                "returns", "returns_multi", "volatility", "candle_patterns",
                "rsi", "atr", "macd", "bollinger", "adx", "momentum",
            ]
        }

        _, feature_matrix = compute_features(
            opens, highs, lows, closes, volumes, config,
        )

        if not feature_matrix:
            raise ValueError("Failed to compute features")

        X = np.array(feature_matrix, dtype=np.float32)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        return X
