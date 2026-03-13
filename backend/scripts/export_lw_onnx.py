"""
Export trained SB3 PPO models to ONNX for lightweight Render deployment.
==================================================================
Converts:
  - SB3 .zip model  →  .onnx policy
  - VecNormalize .pkl  →  .npz stats (obs_mean, obs_var, clip_obs)

Requires local-only deps: stable-baselines3, gymnasium, torch, onnx

Usage:
  python export_lw_onnx.py --model rl_lw_us30_final.zip
  python export_lw_onnx.py --model rl_lw_xauusd_final.zip
  python export_lw_onnx.py --all   (export both US30 and XAUUSD)
"""

import argparse
import os
import pickle
import sys

import numpy as np

# Ensure project root on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "ml_models")


def extract_vecnorm_stats(pkl_path: str, output_npz: str):
    """Extract obs normalization stats from VecNormalize pickle → .npz."""
    with open(pkl_path, "rb") as f:
        vec_norm = pickle.load(f)

    obs_mean = vec_norm.obs_rms.mean.astype(np.float32)
    obs_var = vec_norm.obs_rms.var.astype(np.float32)
    clip_obs = float(vec_norm.clip_obs)

    np.savez(output_npz, obs_mean=obs_mean, obs_var=obs_var, clip_obs=np.array([clip_obs]))
    print(f"  [OK] Saved normalization stats: {output_npz}")
    print(f"    obs_mean shape: {obs_mean.shape}, clip_obs: {clip_obs}")
    return obs_mean, obs_var, clip_obs


def export_to_onnx(zip_path: str, output_onnx: str, obs_dim: int = 32):
    """Export SB3 PPO policy to ONNX."""
    try:
        import torch
        import torch.onnx
        from stable_baselines3 import PPO
    except ImportError:
        print("ERROR: torch and stable-baselines3 required for export!")
        print("  pip install torch stable-baselines3")
        sys.exit(1)

    # Load model
    model = PPO.load(zip_path, device="cpu")
    policy = model.policy
    policy.eval()

    # Create dummy input
    dummy_obs = torch.randn(1, obs_dim, dtype=torch.float32)

    # Extract the MLP extractor + action net for a lean export
    class PolicyWrapper(torch.nn.Module):
        """Wrap SB3 policy to output action logits only."""
        def __init__(self, sb3_policy):
            super().__init__()
            self.features_extractor = sb3_policy.features_extractor
            self.mlp_extractor = sb3_policy.mlp_extractor
            self.action_net = sb3_policy.action_net

        def forward(self, obs):
            features = self.features_extractor(obs)
            latent_pi, _ = self.mlp_extractor(features)
            return self.action_net(latent_pi)

    wrapper = PolicyWrapper(policy)
    wrapper.eval()

    # Export
    torch.onnx.export(
        wrapper,
        dummy_obs,
        output_onnx,
        input_names=["obs"],
        output_names=["action_logits"],
        dynamic_axes={"obs": {0: "batch"}, "action_logits": {0: "batch"}},
        opset_version=14,
    )
    print(f"  [OK] Exported ONNX model: {output_onnx}")

    # Verify
    verify_onnx(output_onnx, wrapper, obs_dim)
    return output_onnx


def verify_onnx(onnx_path: str, torch_model, obs_dim: int = 32):
    """Verify ONNX output matches PyTorch output."""
    import torch
    try:
        import onnxruntime as ort
    except ImportError:
        print("  [WARN] onnxruntime not installed, skipping verification")
        return

    # Random test input
    test_obs = np.random.randn(5, obs_dim).astype(np.float32)

    # PyTorch inference
    with torch.no_grad():
        torch_out = torch_model(torch.from_numpy(test_obs)).numpy()

    # ONNX inference
    sess = ort.InferenceSession(onnx_path)
    onnx_out = sess.run(None, {"obs": test_obs})[0]

    # Compare
    max_diff = np.max(np.abs(torch_out - onnx_out))
    print(f"  [OK] Verification: max difference = {max_diff:.2e} ", end="")
    if max_diff < 1e-5:
        print("(PASS)")
    else:
        print("(WARNING: difference exceeds 1e-5)")


def export_model(symbol: str):
    """Export a single model (zip + vecnorm → onnx + npz)."""
    sym = symbol.lower()
    zip_path = os.path.join(MODEL_DIR, f"rl_lw_{sym}_final.zip")
    pkl_path = os.path.join(MODEL_DIR, f"rl_lw_{sym}_vecnorm.pkl")
    onnx_path = os.path.join(MODEL_DIR, f"rl_lw_{sym}.onnx")
    npz_path = os.path.join(MODEL_DIR, f"rl_lw_{sym}_stats.npz")

    if not os.path.exists(zip_path):
        print(f"  [MISS] Model not found: {zip_path}")
        return False
    if not os.path.exists(pkl_path):
        print(f"  [MISS] VecNormalize not found: {pkl_path}")
        return False

    print(f"\n{'=' * 50}")
    print(f"  Exporting {symbol} RL model to ONNX")
    print(f"{'=' * 50}")

    # Extract normalization stats
    extract_vecnorm_stats(pkl_path, npz_path)

    # Export ONNX
    export_to_onnx(zip_path, onnx_path, obs_dim=32)

    # Print file sizes
    onnx_size = os.path.getsize(onnx_path) / 1024
    npz_size = os.path.getsize(npz_path) / 1024
    print(f"\n  Output files:")
    print(f"    {onnx_path} ({onnx_size:.1f} KB)")
    print(f"    {npz_path} ({npz_size:.1f} KB)")
    return True


def main():
    parser = argparse.ArgumentParser(description="Export LW RL models to ONNX")
    parser.add_argument("--model", help="Path to specific .zip model file")
    parser.add_argument("--all", action="store_true", help="Export both US30 and XAUUSD")
    parser.add_argument("--symbol", choices=["US30", "XAUUSD"], help="Export specific symbol")
    args = parser.parse_args()

    if args.model:
        # Custom model path
        base = os.path.splitext(args.model)[0]
        pkl_path = base.replace("_final", "_vecnorm") + ".pkl"
        onnx_path = base.replace("_final", "") + ".onnx"
        npz_path = base.replace("_final", "") + "_stats.npz"

        if not os.path.exists(pkl_path):
            # Try same dir
            pkl_path = os.path.join(os.path.dirname(args.model),
                                     os.path.basename(base).replace("_final", "_vecnorm") + ".pkl")

        print(f"Exporting: {args.model}")
        extract_vecnorm_stats(pkl_path, npz_path)
        export_to_onnx(args.model, onnx_path, obs_dim=32)

    elif args.all:
        for sym in ["US30", "XAUUSD"]:
            export_model(sym)

    elif args.symbol:
        export_model(args.symbol)

    else:
        # Default: export all available
        for sym in ["US30", "XAUUSD"]:
            export_model(sym)

    print(f"\n{'=' * 50}")
    print("  Done! ONNX models ready for Render deployment.")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
