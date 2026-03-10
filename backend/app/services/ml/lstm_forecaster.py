"""
LSTM/GRU Price Range Forecaster.

Predicts future price distribution (mean, std, p20, p80) for dynamic SL/TP.

Architecture:
  Input:  (batch, seq_len, n_features)
  Model:  LSTM/GRU(hidden=128, layers=2, dropout=0.2) → Linear → 4 outputs
  Output: [predicted_mean_return, predicted_std, predicted_p20, predicted_p80]

Training requires PyTorch (local only).
Inference uses ONNX Runtime (Render-compatible).
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


class LSTMForecaster:
    """
    LSTM/GRU-based price range forecaster.

    Predicts future price distribution for dynamic SL/TP placement.
    Train locally with PyTorch, deploy with ONNX Runtime.
    """

    def __init__(self, model_id: int = 0):
        self.model_id = model_id
        self._onnx_session = None
        self._scaler_mean = None
        self._scaler_std = None
        self._feature_names: list[str] = []
        self._seq_len = 60
        self._horizon = 10
        self._loaded = False
        self._model_path = str(_MODEL_DIR / f"lstm_{model_id}.onnx")
        self._meta_path = str(_MODEL_DIR / f"lstm_{model_id}_meta.npz")

    def train(
        self,
        ohlcv_data: list[dict],
        seq_len: int = 60,
        horizon: int = 10,
        hidden_size: int = 128,
        num_layers: int = 2,
        dropout: float = 0.2,
        cell_type: str = "lstm",
        epochs: int = 50,
        batch_size: int = 64,
        learning_rate: float = 1e-3,
        val_ratio: float = 0.2,
    ) -> dict:
        """
        Train LSTM/GRU forecaster on OHLCV data.

        Requires PyTorch (local only).
        Returns dict with training stats and model_path.
        """
        try:
            import torch
            import torch.nn as nn
            from torch.utils.data import DataLoader, TensorDataset
        except ImportError:
            raise ImportError(
                "PyTorch required for LSTM training. "
                "Install locally: pip install torch>=2.0"
            )

        self._seq_len = seq_len
        self._horizon = horizon

        n = len(ohlcv_data)
        if n < seq_len + horizon + 100:
            raise ValueError(f"Need at least {seq_len + horizon + 100} bars, got {n}")

        # Build features using existing feature pipeline
        from app.services.ml.features import compute_features

        opens = [d["open"] for d in ohlcv_data]
        highs = [d["high"] for d in ohlcv_data]
        lows = [d["low"] for d in ohlcv_data]
        closes = [d["close"] for d in ohlcv_data]
        volumes = [d.get("volume", 0) for d in ohlcv_data]

        feature_config = {
            "features": [
                "returns", "returns_multi", "volatility",
                "rsi", "atr", "macd", "bollinger", "momentum",
            ]
        }
        self._feature_names, feature_matrix = compute_features(
            opens, highs, lows, closes, volumes, feature_config,
        )

        if not feature_matrix or len(feature_matrix) < seq_len + horizon + 50:
            raise ValueError("Not enough valid feature rows")

        X_raw = np.array(feature_matrix, dtype=np.float64)

        # Replace NaN with 0
        X_raw = np.nan_to_num(X_raw, nan=0.0, posinf=0.0, neginf=0.0)

        # Normalize features (z-score)
        self._scaler_mean = X_raw.mean(axis=0)
        self._scaler_std = X_raw.std(axis=0) + 1e-8
        X_norm = (X_raw - self._scaler_mean) / self._scaler_std

        # Build targets: future return distribution over next `horizon` bars
        close_arr = np.array(closes, dtype=np.float64)
        n_features = X_norm.shape[1]

        sequences = []
        targets = []

        for i in range(seq_len, len(X_norm) - horizon):
            seq = X_norm[i - seq_len:i]
            sequences.append(seq)

            # Future returns over horizon
            current_price = close_arr[i]
            if current_price <= 0:
                continue
            future_prices = close_arr[i + 1:i + 1 + horizon]
            future_returns = (future_prices - current_price) / current_price

            target = [
                float(np.mean(future_returns)),
                float(np.std(future_returns)),
                float(np.percentile(future_returns, 20)),
                float(np.percentile(future_returns, 80)),
            ]
            targets.append(target)

        if len(sequences) != len(targets):
            sequences = sequences[:len(targets)]

        X = np.array(sequences, dtype=np.float32)
        y = np.array(targets, dtype=np.float32)

        # Walk-forward split
        split_idx = int(len(X) * (1 - val_ratio))
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]

        logger.info(
            "LSTM training: %d train, %d val samples, %d features, seq_len=%d, horizon=%d",
            len(X_train), len(X_val), n_features, seq_len, horizon,
        )

        # Build model
        class PriceForecaster(nn.Module):
            def __init__(self, input_size, hidden_size, num_layers, dropout, cell_type):
                super().__init__()
                RNN = nn.LSTM if cell_type == "lstm" else nn.GRU
                self.rnn = RNN(
                    input_size=input_size,
                    hidden_size=hidden_size,
                    num_layers=num_layers,
                    dropout=dropout if num_layers > 1 else 0,
                    batch_first=True,
                )
                self.fc = nn.Linear(hidden_size, 4)  # mean, std, p20, p80

            def forward(self, x):
                out, _ = self.rnn(x)
                last = out[:, -1, :]  # Take last timestep
                return self.fc(last)

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = PriceForecaster(n_features, hidden_size, num_layers, dropout, cell_type).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
        criterion = nn.MSELoss()

        train_ds = TensorDataset(torch.FloatTensor(X_train), torch.FloatTensor(y_train))
        val_ds = TensorDataset(torch.FloatTensor(X_val), torch.FloatTensor(y_val))
        train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
        val_loader = DataLoader(val_ds, batch_size=batch_size)

        best_val_loss = float("inf")
        best_state = None
        train_losses = []
        val_losses = []

        for epoch in range(epochs):
            model.train()
            epoch_loss = 0
            for X_batch, y_batch in train_loader:
                X_batch, y_batch = X_batch.to(device), y_batch.to(device)
                optimizer.zero_grad()
                pred = model(X_batch)
                loss = criterion(pred, y_batch)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                epoch_loss += loss.item()

            avg_train = epoch_loss / len(train_loader)
            train_losses.append(avg_train)

            # Validation
            model.eval()
            val_loss = 0
            with torch.no_grad():
                for X_batch, y_batch in val_loader:
                    X_batch, y_batch = X_batch.to(device), y_batch.to(device)
                    pred = model(X_batch)
                    val_loss += criterion(pred, y_batch).item()

            avg_val = val_loss / len(val_loader) if len(val_loader) > 0 else float("inf")
            val_losses.append(avg_val)

            if avg_val < best_val_loss:
                best_val_loss = avg_val
                best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

            if (epoch + 1) % 10 == 0:
                logger.info("Epoch %d/%d: train=%.6f val=%.6f", epoch + 1, epochs, avg_train, avg_val)

        # Load best model
        if best_state:
            model.load_state_dict(best_state)

        # Export to ONNX
        model.eval()
        model.cpu()
        dummy = torch.randn(1, seq_len, n_features)
        torch.onnx.export(
            model, dummy, self._model_path,
            input_names=["input"],
            output_names=["output"],
            dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
            opset_version=14,
        )

        # Save scaler metadata
        np.savez(
            self._meta_path,
            scaler_mean=self._scaler_mean,
            scaler_std=self._scaler_std,
            feature_names=np.array(self._feature_names),
            seq_len=np.array([seq_len]),
            horizon=np.array([horizon]),
        )

        self._loaded = True
        self._load_onnx()

        # Evaluate on validation set
        val_preds = self.predict_batch(X_val)
        if val_preds is not None:
            direction_correct = np.sum(
                (val_preds[:, 0] > 0) == (y_val[:, 0] > 0)
            )
            direction_accuracy = direction_correct / len(y_val)
        else:
            direction_accuracy = 0

        model_size_kb = os.path.getsize(self._model_path) / 1024

        logger.info(
            "LSTM trained: %s (%.1f KB), best_val_loss=%.6f, dir_accuracy=%.1f%%",
            self._model_path, model_size_kb, best_val_loss, direction_accuracy * 100,
        )

        return {
            "model_path": self._model_path,
            "meta_path": self._meta_path,
            "cell_type": cell_type,
            "hidden_size": hidden_size,
            "num_layers": num_layers,
            "seq_len": seq_len,
            "horizon": horizon,
            "n_features": n_features,
            "n_train": len(X_train),
            "n_val": len(X_val),
            "best_val_loss": float(best_val_loss),
            "direction_accuracy": float(direction_accuracy),
            "model_size_kb": round(model_size_kb, 1),
            "train_losses": [round(l, 6) for l in train_losses[-10:]],
            "val_losses": [round(l, 6) for l in val_losses[-10:]],
        }

    def load(self, model_path: Optional[str] = None) -> bool:
        """Load a trained LSTM model (ONNX) for inference."""
        path = model_path or self._model_path
        meta_path = path.replace(".onnx", "_meta.npz")

        if not os.path.exists(path):
            logger.warning("LSTM model not found: %s", path)
            return False
        if not os.path.exists(meta_path):
            logger.warning("LSTM meta not found: %s", meta_path)
            return False

        try:
            meta = np.load(meta_path, allow_pickle=True)
            self._scaler_mean = meta["scaler_mean"]
            self._scaler_std = meta["scaler_std"]
            self._feature_names = meta["feature_names"].tolist()
            self._seq_len = int(meta["seq_len"][0])
            self._horizon = int(meta["horizon"][0])
            self._model_path = path
            self._meta_path = meta_path
            return self._load_onnx()
        except Exception as e:
            logger.error("Failed to load LSTM model: %s", e)
            return False

    def _load_onnx(self) -> bool:
        """Load ONNX model for inference."""
        try:
            import onnxruntime as ort
            self._onnx_session = ort.InferenceSession(self._model_path)
            self._loaded = True
            logger.info("LSTM model loaded: %s", self._model_path)
            return True
        except ImportError:
            logger.error("onnxruntime not installed")
            return False
        except Exception as e:
            logger.error("Failed to load ONNX: %s", e)
            return False

    def predict(self, ohlcv_data: list[dict]) -> Optional[dict]:
        """
        Predict future price distribution from recent bars.

        Returns:
            Dict with predicted_mean, predicted_std, predicted_p20, predicted_p80,
            plus derived sl_distance and tp_distance as price multipliers.
        """
        if not self._loaded:
            return None

        if len(ohlcv_data) < self._seq_len + 10:
            return None

        try:
            from app.services.ml.features import compute_features

            opens = [d["open"] for d in ohlcv_data]
            highs = [d["high"] for d in ohlcv_data]
            lows = [d["low"] for d in ohlcv_data]
            closes = [d["close"] for d in ohlcv_data]
            volumes = [d.get("volume", 0) for d in ohlcv_data]

            feature_config = {
                "features": [
                    "returns", "returns_multi", "volatility",
                    "rsi", "atr", "macd", "bollinger", "momentum",
                ]
            }
            _, feature_matrix = compute_features(
                opens, highs, lows, closes, volumes, feature_config,
            )

            if not feature_matrix or len(feature_matrix) < self._seq_len:
                return None

            X_raw = np.array(feature_matrix[-self._seq_len:], dtype=np.float64)
            X_raw = np.nan_to_num(X_raw, nan=0.0, posinf=0.0, neginf=0.0)

            # Apply same normalization as training
            X_norm = (X_raw - self._scaler_mean) / self._scaler_std
            X_input = X_norm.reshape(1, self._seq_len, -1).astype(np.float32)

            # Run ONNX inference
            input_name = self._onnx_session.get_inputs()[0].name
            result = self._onnx_session.run(None, {input_name: X_input})
            pred = result[0][0]  # [mean, std, p20, p80]

            current_price = closes[-1]
            predicted_mean = float(pred[0])
            predicted_std = float(pred[1])
            predicted_p20 = float(pred[2])
            predicted_p80 = float(pred[3])

            return {
                "predicted_mean_return": predicted_mean,
                "predicted_std": predicted_std,
                "predicted_p20": predicted_p20,
                "predicted_p80": predicted_p80,
                "horizon": self._horizon,
                "current_price": current_price,
                # Derived SL/TP distances as price levels
                "tp_price_long": current_price * (1 + predicted_p80),
                "sl_price_long": current_price * (1 + predicted_p20),
                "tp_price_short": current_price * (1 + predicted_p20),
                "sl_price_short": current_price * (1 + predicted_p80),
            }

        except Exception as e:
            logger.error("LSTM prediction failed: %s", e)
            return None

    def predict_batch(self, X: np.ndarray) -> Optional[np.ndarray]:
        """Run batch prediction on pre-processed input array."""
        if not self._onnx_session:
            return None
        try:
            input_name = self._onnx_session.get_inputs()[0].name
            X_input = X.astype(np.float32)
            result = self._onnx_session.run(None, {input_name: X_input})
            return result[0]
        except Exception as e:
            logger.error("Batch prediction failed: %s", e)
            return None
