"""
Local LSTM/GRU training script.

Usage:
    python train_lstm_local.py --data US30_M15.csv --cell lstm --epochs 50
    python train_lstm_local.py --data US30_M15.csv --cell gru --hidden 256 --epochs 100

After training, upload the .onnx file via the ML Lab UI or API:
    POST /api/ml/upload-model?name=lstm_us30_m15
"""

import argparse
import csv
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def load_csv(path: str) -> list[dict]:
    """Load OHLCV data from CSV."""
    data = []
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rec = {
                    "open": float(row.get("open") or row.get("Open") or 0),
                    "high": float(row.get("high") or row.get("High") or 0),
                    "low": float(row.get("low") or row.get("Low") or 0),
                    "close": float(row.get("close") or row.get("Close") or 0),
                    "volume": float(row.get("volume") or row.get("Volume") or row.get("tick_volume") or 0),
                }
                if rec["close"] > 0:
                    data.append(rec)
            except (ValueError, TypeError):
                continue
    return data


def main():
    parser = argparse.ArgumentParser(description="Train LSTM/GRU price forecaster locally")
    parser.add_argument("--data", required=True, help="Path to OHLCV CSV file")
    parser.add_argument("--cell", default="lstm", choices=["lstm", "gru"], help="RNN cell type")
    parser.add_argument("--seq-len", type=int, default=60, help="Sequence length")
    parser.add_argument("--horizon", type=int, default=10, help="Forecast horizon (bars)")
    parser.add_argument("--hidden", type=int, default=128, help="Hidden size")
    parser.add_argument("--layers", type=int, default=2, help="Number of RNN layers")
    parser.add_argument("--dropout", type=float, default=0.2, help="Dropout rate")
    parser.add_argument("--epochs", type=int, default=50, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=64, help="Batch size")
    parser.add_argument("--lr", type=float, default=1e-3, help="Learning rate")
    parser.add_argument("--output", default=None, help="Output ONNX path")
    parser.add_argument("--model-id", type=int, default=0, help="Model identifier")
    args = parser.parse_args()

    print(f"Loading data from {args.data}...")
    data = load_csv(args.data)
    print(f"Loaded {len(data)} bars")

    if len(data) < args.seq_len + args.horizon + 100:
        print(f"ERROR: Need at least {args.seq_len + args.horizon + 100} bars")
        sys.exit(1)

    from app.services.ml.lstm_forecaster import LSTMForecaster

    forecaster = LSTMForecaster(model_id=args.model_id)

    print(f"\nTraining {args.cell.upper()} forecaster...")
    print(f"  Cell: {args.cell}, Hidden: {args.hidden}, Layers: {args.layers}")
    print(f"  Seq len: {args.seq_len}, Horizon: {args.horizon}")
    print(f"  Epochs: {args.epochs}, Batch: {args.batch_size}, LR: {args.lr}")
    print()

    result = forecaster.train(
        ohlcv_data=data,
        seq_len=args.seq_len,
        horizon=args.horizon,
        hidden_size=args.hidden,
        num_layers=args.layers,
        dropout=args.dropout,
        cell_type=args.cell,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
    )

    print("\n=== Training Results ===")
    print(f"  Model path: {result['model_path']}")
    print(f"  Model size: {result['model_size_kb']:.1f} KB")
    print(f"  Train samples: {result['n_train']}")
    print(f"  Val samples: {result['n_val']}")
    print(f"  Best val loss: {result['best_val_loss']:.6f}")
    print(f"  Direction accuracy: {result['direction_accuracy']:.1%}")
    print(f"\n  Upload via: POST /api/ml/upload-model")

    # Test prediction
    print("\nTesting prediction on last bars...")
    pred = forecaster.predict(data)
    if pred:
        print(f"  Predicted mean return: {pred['predicted_mean_return']:.4%}")
        print(f"  Predicted std: {pred['predicted_std']:.4%}")
        print(f"  P20: {pred['predicted_p20']:.4%}")
        print(f"  P80: {pred['predicted_p80']:.4%}")
        print(f"  Current price: {pred['current_price']:.5f}")
        print(f"  Long TP: {pred['tp_price_long']:.5f}")
        print(f"  Long SL: {pred['sl_price_long']:.5f}")


if __name__ == "__main__":
    main()
