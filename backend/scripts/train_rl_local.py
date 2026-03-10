"""
Local RL training script.

Usage:
    python train_rl_local.py --data US30_M15.csv --timesteps 500000
    python train_rl_local.py --data US30_M15.csv --timesteps 1000000 --hidden 256 256

After training, upload the .onnx file via the ML Lab UI or API.
"""

import argparse
import csv
import os
import sys

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
    parser = argparse.ArgumentParser(description="Train RL trading agent locally")
    parser.add_argument("--data", required=True, help="Path to OHLCV CSV file")
    parser.add_argument("--timesteps", type=int, default=500000, help="Total training timesteps")
    parser.add_argument("--hidden", nargs="+", type=int, default=[256, 256], help="Hidden layer sizes")
    parser.add_argument("--lr", type=float, default=3e-4, help="Learning rate")
    parser.add_argument("--batch-size", type=int, default=64, help="Batch size")
    parser.add_argument("--commission", type=float, default=0.0002, help="Commission rate")
    parser.add_argument("--spread", type=float, default=0.0001, help="Spread")
    parser.add_argument("--model-id", type=int, default=0, help="Model identifier")
    parser.add_argument("--eval-freq", type=int, default=10000, help="Evaluation frequency")
    args = parser.parse_args()

    print(f"Loading data from {args.data}...")
    data = load_csv(args.data)
    print(f"Loaded {len(data)} bars")

    if len(data) < 500:
        print("ERROR: Need at least 500 bars")
        sys.exit(1)

    from app.services.ml.rl_trainer import RLTrainer

    trainer = RLTrainer(model_id=args.model_id)

    print(f"\nTraining PPO agent...")
    print(f"  Timesteps: {args.timesteps:,}")
    print(f"  Hidden: {args.hidden}")
    print(f"  LR: {args.lr}")
    print(f"  Commission: {args.commission}")
    print(f"  Spread: {args.spread}")
    print()

    result = trainer.train(
        ohlcv_data=data,
        total_timesteps=args.timesteps,
        hidden_sizes=tuple(args.hidden),
        learning_rate=args.lr,
        batch_size=args.batch_size,
        commission=args.commission,
        spread=args.spread,
        eval_freq=args.eval_freq,
    )

    print("\n=== Training Results ===")
    print(f"  Model: {result.get('model_path')}")
    print(f"  ONNX:  {result.get('onnx_path')}")
    print(f"  Train bars: {result.get('n_train_bars')}")
    print(f"  Eval bars:  {result.get('n_eval_bars')}")

    eval_r = result.get("eval_results", {})
    print(f"\n  Eval total P&L: {eval_r.get('total_pnl', 0):.2f}")
    print(f"  Eval trades:    {eval_r.get('total_trades', 0)}")
    print(f"  Eval win rate:  {eval_r.get('win_rate', 0):.1%}")
    print(f"  Eval max DD:    {eval_r.get('max_drawdown', 0):.1%}")
    print(f"  Eval balance:   {eval_r.get('final_balance', 0):.2f}")
    print(f"  Actions: {eval_r.get('actions', {})}")
    print(f"\n  Upload via: POST /api/ml/upload-model")


if __name__ == "__main__":
    main()
