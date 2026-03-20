"""
Train All New RL Models (v2)
============================
Runs all 4 new RL model training scripts sequentially:
  1. rl_mom_btcusd_d1   — Momentum crypto on BTCUSD D1
  2. rl_mom_ethusd_d1   — Momentum crypto on ETHUSD D1
  3. rl_ttm_btcusd_h1   — TTM Squeeze on BTCUSD H1
  4. rl_lw_nas100_h1    — Larry Williams on NAS100 H1

After training, exports all models to ONNX + normalization stats.

Usage:
  python train_all_rl_v2.py
  python train_all_rl_v2.py --timesteps 500000  (faster, for testing)
  python train_all_rl_v2.py --model mom_btcusd   (train single model)

Estimated time: ~8 hours total (2hr each) at 1M timesteps
"""

import argparse
import os
import subprocess
import sys
import time

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable


def run_script(script_name, extra_args=None):
    """Run a training script and capture output."""
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    if not os.path.exists(script_path):
        print(f"  [SKIP] {script_name} not found")
        return False

    cmd = [PYTHON, script_path] + (extra_args or [])
    print(f"\n{'=' * 70}")
    print(f"  Running: {script_name}")
    print(f"  Command: {' '.join(cmd)}")
    print(f"{'=' * 70}\n")

    t0 = time.time()
    result = subprocess.run(cmd, cwd=SCRIPTS_DIR)
    elapsed = time.time() - t0

    status = "OK" if result.returncode == 0 else "FAILED"
    print(f"\n  [{status}] {script_name} completed in {elapsed/60:.1f} min")
    return result.returncode == 0


def export_onnx(model_name, obs_dim=32):
    """Export a trained model to ONNX using the export script."""
    export_script = os.path.join(SCRIPTS_DIR, "export_lw_onnx.py")
    if not os.path.exists(export_script):
        print(f"  [SKIP] export_lw_onnx.py not found, ONNX export skipped for {model_name}")
        return

    model_dir = os.path.join(SCRIPTS_DIR, "..", "data", "ml_models")
    zip_path = os.path.join(model_dir, f"{model_name}_final.zip")
    pkl_path = os.path.join(model_dir, f"{model_name}_vecnorm.pkl")

    if not os.path.exists(zip_path):
        print(f"  [SKIP] {zip_path} not found")
        return

    cmd = [PYTHON, export_script, "--model", zip_path, "--obs-dim", str(obs_dim)]
    print(f"  Exporting ONNX: {model_name} (obs_dim={obs_dim})...")
    subprocess.run(cmd, cwd=SCRIPTS_DIR)


def main():
    parser = argparse.ArgumentParser(description="Train all new RL models")
    parser.add_argument("--timesteps", type=int, default=1000000,
                        help="Training timesteps per model (default: 1M)")
    parser.add_argument("--model", type=str, default="all",
                        help="Train specific model: mom_btcusd, mom_ethusd, ttm_btcusd, lw_nas100, or 'all'")
    parser.add_argument("--n-envs", type=int, default=4)
    args = parser.parse_args()

    ts_args = ["--timesteps", str(args.timesteps), "--n-envs", str(args.n_envs)]

    models = {
        "mom_btcusd": {
            "script": "train_rl_momentum_crypto.py",
            "args": ts_args + ["--symbol", "BTCUSD"],
            "output": "rl_mom_btcusd_d1",
            "obs_dim": 32,
        },
        "mom_ethusd": {
            "script": "train_rl_momentum_crypto.py",
            "args": ts_args + ["--symbol", "ETHUSD"],
            "output": "rl_mom_ethusd_d1",
            "obs_dim": 32,
        },
        "ttm_btcusd": {
            "script": "train_rl_ttm_crypto.py",
            "args": ts_args,
            "output": "rl_ttm_btcusd_h1",
            "obs_dim": 32,
        },
        "lw_nas100": {
            "script": "train_rl_lw_nas100.py",
            "args": ts_args,
            "output": "rl_lw_nas100_h1",
            "obs_dim": 35,  # 28 features + 7 context (LW uses extended feature set)
        },
    }

    # Filter to requested model
    if args.model != "all":
        if args.model not in models:
            print(f"Unknown model: {args.model}")
            print(f"Available: {', '.join(models.keys())}")
            return
        models = {args.model: models[args.model]}

    print(f"\n{'#' * 70}")
    print(f"  FlowrexAlgo RL Training Pipeline v2")
    print(f"  Models to train: {len(models)}")
    print(f"  Timesteps per model: {args.timesteps:,}")
    print(f"  Parallel envs: {args.n_envs}")
    print(f"{'#' * 70}")

    results = {}
    total_t0 = time.time()

    for name, config in models.items():
        t0 = time.time()
        success = run_script(config["script"], config["args"])
        elapsed = time.time() - t0
        results[name] = {"success": success, "time_min": round(elapsed / 60, 1)}

        if success:
            export_onnx(config["output"], config["obs_dim"])

    total_elapsed = time.time() - total_t0

    # Summary
    print(f"\n\n{'#' * 70}")
    print(f"  Training Complete — Total time: {total_elapsed/60:.1f} min ({total_elapsed/3600:.1f} hr)")
    print(f"{'#' * 70}")
    for name, r in results.items():
        status = "OK" if r["success"] else "FAILED"
        print(f"  [{status}] {name:20s}  {r['time_min']:6.1f} min")
    print(f"{'#' * 70}\n")


if __name__ == "__main__":
    main()
