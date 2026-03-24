"""
Master Training Pipeline — Train all scalping + expert models for all symbols.

Trains in sections to avoid timeouts:
  Section 1: Scalping models (XGB + LGB with walk-forward Optuna) for BTCUSD, ES, NAS100
  Section 2: Expert models (XGB + LGB + LSTM + Meta + Regime) for US30, ES
  Section 3: Expert models for NAS100, BTCUSD

Each scalping section does walk-forward validation (5 folds) with Optuna tuning.
Models graded A/B/C/D — only A/B get saved for production use.

Usage:
    python scripts/train_all_models.py --section 1
    python scripts/train_all_models.py --section 2
    python scripts/train_all_models.py --section 3
    python scripts/train_all_models.py --section all
    python scripts/train_all_models.py --section all --quick  # 10 Optuna trials
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DATA_DIR = Path(__file__).parent.parent / "data" / "databento"
MODEL_DIR = Path(__file__).parent.parent / "data" / "ml_models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR = Path(__file__).parent.parent / "data" / "training_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Symbol Parameters ─────────────────────────────────

SYMBOL_PARAMS = {
    "XAUUSD": {
        "commission_per_lot": 0.30,
        "spread_points": 0.30,
        "point_value": 100.0,
        "atr_sl_mult": 1.5,
        "atr_tp_mult": 2.5,
        "max_holding_bars": 12,
        "swing_lookback": 5,
    },
    "US30": {
        "commission_per_lot": 1.0,
        "spread_points": 2.0,
        "point_value": 1.0,
        "atr_sl_mult": 1.5,
        "atr_tp_mult": 2.0,
        "max_holding_bars": 12,
        "swing_lookback": 5,
    },
    "ES": {
        "commission_per_lot": 1.24,
        "spread_points": 0.25,
        "point_value": 50.0,
        "atr_sl_mult": 1.5,
        "atr_tp_mult": 2.0,
        "max_holding_bars": 12,
        "swing_lookback": 5,
    },
    "NAS100": {
        "commission_per_lot": 1.24,
        "spread_points": 0.50,
        "point_value": 20.0,
        "atr_sl_mult": 1.5,
        "atr_tp_mult": 2.0,
        "max_holding_bars": 12,
        "swing_lookback": 5,
    },
    "BTCUSD": {
        "commission_per_lot": 0.50,
        "spread_points": 5.0,
        "point_value": 1.0,
        "atr_sl_mult": 2.0,
        "atr_tp_mult": 3.0,
        "max_holding_bars": 24,
        "swing_lookback": 7,
    },
}


def run_scalping_section(symbols: list[str], quick: bool = False):
    """Train scalping models (XGB + LGB with walk-forward Optuna)."""
    from scripts.train_scalping_pipeline import run_pipeline
    import scripts.train_scalping_pipeline as scalp_mod

    # Inject missing symbol params into the scalping pipeline module
    for sym, params in SYMBOL_PARAMS.items():
        if sym not in scalp_mod.SYMBOL_PARAMS:
            scalp_mod.SYMBOL_PARAMS[sym] = params

    all_results = {}
    for symbol in symbols:
        print(f"\n{'#' * 70}")
        print(f"  SCALPING: {symbol}")
        print(f"{'#' * 70}")
        t0 = time.time()
        try:
            result = run_pipeline(symbol, quick=quick)
            if result:
                all_results[symbol] = {
                    mt: {
                        "aggregate": res["aggregate"],
                        "aggregate_grade": res["aggregate_grade"],
                        "folds": res["folds"],
                    }
                    for mt, res in result.items()
                }
            elapsed = time.time() - t0
            print(f"\n  {symbol} scalping done in {elapsed:.0f}s")
        except Exception as e:
            print(f"\n  ERROR training {symbol}: {e}")
            import traceback
            traceback.print_exc()

    return all_results


def run_expert_section(symbols: list[str], quick: bool = False):
    """Train expert models (XGB + LGB + LSTM + Meta + Regime)."""
    from scripts.train_expert_agent import train_symbol
    import scripts.train_expert_agent as expert_mod

    # Inject missing symbol params
    for sym, params in SYMBOL_PARAMS.items():
        if sym not in expert_mod.SYMBOL_PARAMS:
            expert_mod.SYMBOL_PARAMS[sym] = params

    all_results = {}
    for symbol in symbols:
        print(f"\n{'#' * 70}")
        print(f"  EXPERT: {symbol}")
        print(f"{'#' * 70}")
        t0 = time.time()
        try:
            result = train_symbol(symbol, quick=quick, skip_download=True)
            if result:
                all_results[symbol] = {}
                for comp, res in result.items():
                    if isinstance(res, dict) and "model_path" in res:
                        all_results[symbol][comp] = {
                            "model_path": res.get("model_path"),
                            "train_metrics": res.get("train_metrics", {}),
                            "val_metrics": res.get("val_metrics", {}),
                        }
            elapsed = time.time() - t0
            print(f"\n  {symbol} expert done in {elapsed:.0f}s")
        except Exception as e:
            print(f"\n  ERROR training {symbol}: {e}")
            import traceback
            traceback.print_exc()

    return all_results


def print_summary(section_name: str, results: dict):
    """Print training results summary."""
    print(f"\n{'=' * 70}")
    print(f"  {section_name} — RESULTS SUMMARY")
    print(f"{'=' * 70}")
    for symbol, data in results.items():
        print(f"\n  {symbol}:")
        for model_type, info in data.items():
            if "aggregate_grade" in info:
                agg = info.get("aggregate", {})
                print(f"    {model_type:>12}: Grade {info['aggregate_grade']} | "
                      f"PF={agg.get('avg_profit_factor', 0):.2f} | "
                      f"Sharpe={agg.get('avg_sharpe', 0):.2f} | "
                      f"WR={agg.get('avg_win_rate', 0):.2%}")
            elif "val_metrics" in info:
                vm = info["val_metrics"]
                acc = vm.get("accuracy", vm.get("best_val_accuracy", 0))
                print(f"    {model_type:>12}: Val accuracy={acc:.4f}")


def save_results(section_name: str, results: dict):
    """Save results to JSON."""
    path = RESULTS_DIR / f"{section_name}_results.json"
    with open(path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved: {path}")


def main():
    parser = argparse.ArgumentParser(description="Master Training Pipeline")
    parser.add_argument(
        "--section",
        choices=["1", "2", "3", "all"],
        default="all",
        help="Which section to run",
    )
    parser.add_argument("--quick", action="store_true", help="Quick mode (10 Optuna trials)")
    args = parser.parse_args()

    sections = ["1", "2", "3"] if args.section == "all" else [args.section]

    print("=" * 70)
    print("  TRADEFORGE — Master Training Pipeline")
    print("=" * 70)
    print(f"  Sections:   {sections}")
    print(f"  Quick mode: {args.quick}")
    print(f"  Data dir:   {DATA_DIR}")
    print(f"  Model dir:  {MODEL_DIR}")
    print()

    grand_start = time.time()

    for section in sections:
        section_start = time.time()

        if section == "1":
            print(f"\n{'█' * 70}")
            print(f"  SECTION 1: Scalping — BTCUSD, ES, NAS100")
            print(f"{'█' * 70}")
            results = run_scalping_section(["BTCUSD", "ES", "NAS100"], quick=args.quick)
            print_summary("Section 1 — Scalping", results)
            save_results("section1_scalping", results)

        elif section == "2":
            print(f"\n{'█' * 70}")
            print(f"  SECTION 2: Expert — US30, ES")
            print(f"{'█' * 70}")
            results = run_expert_section(["US30", "ES"], quick=args.quick)
            print_summary("Section 2 — Expert", results)
            save_results("section2_expert", results)

        elif section == "3":
            print(f"\n{'█' * 70}")
            print(f"  SECTION 3: Expert — NAS100, BTCUSD")
            print(f"{'█' * 70}")
            results = run_expert_section(["NAS100", "BTCUSD"], quick=args.quick)
            print_summary("Section 3 — Expert", results)
            save_results("section3_expert", results)

        elapsed = time.time() - section_start
        print(f"\n  Section {section} completed in {elapsed:.0f}s ({elapsed/60:.1f}m)")

    total = time.time() - grand_start
    print(f"\n\n{'█' * 70}")
    print(f"  ALL TRAINING COMPLETE — {total:.0f}s ({total/60:.1f}m)")
    print(f"{'█' * 70}")

    # List all model files
    print(f"\n  Model files:")
    for f in sorted(MODEL_DIR.glob("*")):
        if f.is_file() and f.suffix in (".joblib", ".onnx"):
            size_mb = f.stat().st_size / 1024 / 1024
            name = f.name
            if name.startswith("scalping_") or name.startswith("expert_"):
                print(f"    {name:<50} {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
