"""
Walk-Forward Backtest — Validate all trained models against overfitting.

For each symbol × model type:
  1. Loads M5 + H1 data
  2. Computes features and targets
  3. Splits data into 5 expanding-window folds (train → test)
  4. Trains fresh model on train, predicts on test
  5. Backtests predictions with realistic costs
  6. Compares in-sample vs out-of-sample metrics
  7. Flags overfitting if train_metric >> test_metric

Overfitting detection:
  - If train PF > 2× test PF → OVERFIT
  - If train WR > test WR + 10% → OVERFIT
  - If test Sharpe < 0.5 → UNDERPERFORM

Usage:
    python scripts/walk_forward_backtest.py
    python scripts/walk_forward_backtest.py --symbols XAUUSD ES
    python scripts/walk_forward_backtest.py --quick  # 3 folds instead of 5
"""

import argparse
import csv
import json
import os
import sys
import time
import warnings
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DATA_DIR = Path(__file__).parent.parent / "data" / "databento"
MODEL_DIR = Path(__file__).parent.parent / "data" / "ml_models"
RESULTS_DIR = Path(__file__).parent.parent / "data" / "wf_backtest_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

SYMBOL_PARAMS = {
    "XAUUSD": {"spread": 0.30, "commission": 0.30, "pv": 100.0, "sl_mult": 1.5, "tp_mult": 2.5, "hold": 12},
    "US30":   {"spread": 2.0,  "commission": 1.0,  "pv": 1.0,   "sl_mult": 1.5, "tp_mult": 2.0, "hold": 12},
    "ES":     {"spread": 0.25, "commission": 1.24, "pv": 50.0,  "sl_mult": 1.5, "tp_mult": 2.0, "hold": 12},
    "NAS100": {"spread": 0.50, "commission": 1.24, "pv": 20.0,  "sl_mult": 1.5, "tp_mult": 2.0, "hold": 12},
    "BTCUSD": {"spread": 5.0,  "commission": 0.50, "pv": 1.0,   "sl_mult": 2.0, "tp_mult": 3.0, "hold": 24},
}

ALL_SYMBOLS = ["XAUUSD", "US30", "ES", "NAS100", "BTCUSD"]


def load_csv(path: str) -> list[dict]:
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
                dt_val = row.get("datetime") or row.get("Datetime") or row.get("date")
                if dt_val:
                    try:
                        rec["datetime"] = datetime.fromisoformat(str(dt_val).replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        rec["datetime"] = None
                if rec["close"] > 0:
                    data.append(rec)
            except (ValueError, TypeError):
                continue
    return data


def compute_features_and_targets(m5_data, h1_data, params):
    """Compute expert features + triple-barrier targets."""
    from app.services.ml.features_mtf import compute_expert_features
    from app.services.ml.features import compute_targets

    feat_names, X = compute_expert_features(m5_data, h1_data, None, None)
    X = np.array(X, dtype=np.float64)

    closes = [d["close"] for d in m5_data]
    highs = [d["high"] for d in m5_data]
    lows = [d["low"] for d in m5_data]

    target_config = {
        "type": "triple_barrier",
        "horizon": params["hold"],
        "sl_atr_mult": params["sl_mult"],
        "tp_atr_mult": params["tp_mult"],
        "max_holding_bars": params["hold"],
    }
    _, y_raw = compute_targets(closes, target_config, highs, lows)
    y_raw = np.array(y_raw, dtype=np.float64)

    # Align lengths
    n = min(len(X), len(y_raw))
    X, y_raw = X[:n], y_raw[:n]

    # Clean
    valid = np.isfinite(y_raw)
    if X.ndim == 2:
        valid &= np.all(np.isfinite(X), axis=1)

    X_clean = X[valid]
    y_clean = y_raw[valid]

    # Map to classes
    unique = np.unique(y_clean)
    label_map = {v: i for i, v in enumerate(sorted(unique))}
    y_classes = np.array([label_map[v] for v in y_clean], dtype=np.int64)

    # Price arrays aligned with clean data
    closes_arr = np.array(closes, dtype=np.float64)[:n][valid]
    highs_arr = np.array(highs, dtype=np.float64)[:n][valid]
    lows_arr = np.array(lows, dtype=np.float64)[:n][valid]

    return feat_names, X_clean, y_classes, closes_arr, highs_arr, lows_arr


def backtest_predictions(preds, confs, closes, highs, lows, params, conf_thresh=0.55):
    """Simple backtest on model predictions."""
    n = len(preds)
    spread = params["spread"]
    comm = params["commission"]
    pv = params["pv"]
    sl_mult = params["sl_mult"]
    tp_mult = params["tp_mult"]
    max_bars = params["hold"]

    # ATR
    atr = np.full(n, np.nan)
    for i in range(14, n):
        trs = []
        for j in range(i - 13, i + 1):
            tr = max(highs[j] - lows[j],
                     abs(highs[j] - closes[j - 1]),
                     abs(lows[j] - closes[j - 1]))
            trs.append(tr)
        atr[i] = np.mean(trs)

    trades = []
    for i in range(14, n - 1):
        if preds[i] == 1 or confs[i] < conf_thresh or np.isnan(atr[i]):
            continue

        direction = 1 if preds[i] == 2 else -1
        entry = closes[i]
        sl_d = atr[i] * sl_mult
        tp_d = atr[i] * tp_mult

        sl = entry - sl_d * direction * (-1 if direction == -1 else 1)
        tp = entry + tp_d * direction * (1 if direction == 1 else -1)

        if direction == 1:
            sl = entry - sl_d
            tp = entry + tp_d
        else:
            sl = entry + sl_d
            tp = entry - tp_d

        exit_price = None
        for j in range(i + 1, min(i + max_bars + 1, n)):
            if direction == 1:
                if lows[j] <= sl:
                    exit_price = sl; break
                if highs[j] >= tp:
                    exit_price = tp; break
            else:
                if highs[j] >= sl:
                    exit_price = sl; break
                if lows[j] <= tp:
                    exit_price = tp; break

        if exit_price is None:
            exit_bar = min(i + max_bars, n - 1)
            exit_price = closes[exit_bar]

        pnl = (exit_price - entry) * direction
        cost = spread + (2 * comm / pv)
        trades.append(pnl - cost)

    if not trades:
        return {"n_trades": 0, "win_rate": 0, "pf": 0, "sharpe": 0, "total_pnl": 0}

    pnls = np.array(trades)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    wr = len(wins) / len(pnls)
    gp = wins.sum() if len(wins) > 0 else 0
    gl = abs(losses.sum()) if len(losses) > 0 else 0.001
    pf = gp / gl
    std = pnls.std() if len(pnls) > 1 else 1.0
    sharpe = (pnls.mean() / std) * np.sqrt(252) if std > 1e-10 else 0

    return {
        "n_trades": len(trades),
        "win_rate": round(wr, 4),
        "pf": round(pf, 4),
        "sharpe": round(sharpe, 4),
        "total_pnl": round(float(pnls.sum()), 2),
    }


def walk_forward_validate(
    symbol: str,
    model_type: str,  # "xgboost" or "lightgbm"
    n_folds: int = 5,
    max_bars: int = 150_000,
):
    """Run walk-forward validation for one symbol × model type."""
    params = SYMBOL_PARAMS[symbol]

    m5_path = DATA_DIR / f"{symbol}_M5.csv"
    h1_path = DATA_DIR / f"{symbol}_H1.csv"

    if not m5_path.exists():
        print(f"    SKIP: {m5_path} not found")
        return None

    print(f"    Loading data...")
    m5_data = load_csv(str(m5_path))
    h1_data = load_csv(str(h1_path)) if h1_path.exists() else None

    # Use last N bars
    m5_data = m5_data[-max_bars:] if len(m5_data) > max_bars else m5_data
    if h1_data:
        h1_data = h1_data[-(max_bars // 12):] if len(h1_data) > max_bars // 12 else h1_data

    print(f"    M5: {len(m5_data):,} bars")

    print(f"    Computing features...")
    t0 = time.time()
    feat_names, X, y, closes, highs, lows = compute_features_and_targets(m5_data, h1_data, params)
    print(f"    {len(feat_names)} features, {len(X):,} samples ({time.time() - t0:.1f}s)")

    n = len(X)
    fold_size = n // (n_folds + 1)

    fold_results = []

    for fold in range(n_folds):
        train_end = fold_size * (fold + 2)
        val_start = train_end
        val_end = min(val_start + fold_size, n)

        if val_end <= val_start + 100:
            continue

        X_train, y_train = X[:train_end], y[:train_end]
        X_val, y_val = X[val_start:val_end], y[val_start:val_end]

        print(f"\n    Fold {fold + 1}/{n_folds}: train[0:{train_end:,}] → val[{val_start:,}:{val_end:,}]")

        # Train model
        if model_type == "xgboost":
            from xgboost import XGBClassifier
            model = XGBClassifier(
                n_estimators=200, max_depth=6, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.7, min_child_weight=5,
                reg_alpha=0.1, reg_lambda=1.0,
                use_label_encoder=False, eval_metric="mlogloss",
                random_state=42, n_jobs=-1,
            )
        else:
            from lightgbm import LGBMClassifier
            model = LGBMClassifier(
                n_estimators=200, max_depth=6, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.7, min_child_samples=20,
                reg_alpha=0.1, reg_lambda=1.0, num_leaves=31,
                random_state=42, n_jobs=-1, verbose=-1,
            )

        model.fit(X_train, y_train)

        # In-sample metrics
        from sklearn.metrics import accuracy_score
        train_pred = model.predict(X_train)
        train_proba = model.predict_proba(X_train)
        train_conf = np.max(train_proba, axis=1)
        train_acc = accuracy_score(y_train, train_pred)

        train_bt = backtest_predictions(
            train_pred, train_conf,
            closes[:train_end], highs[:train_end], lows[:train_end],
            params,
        )

        # Out-of-sample metrics
        val_pred = model.predict(X_val)
        val_proba = model.predict_proba(X_val)
        val_conf = np.max(val_proba, axis=1)
        val_acc = accuracy_score(y_val, val_pred)

        val_bt = backtest_predictions(
            val_pred, val_conf,
            closes[val_start:val_end], highs[val_start:val_end], lows[val_start:val_end],
            params,
        )

        # Overfitting checks
        overfit_flags = []
        if train_bt["pf"] > 0 and val_bt["pf"] > 0 and train_bt["pf"] > 2 * val_bt["pf"]:
            overfit_flags.append(f"PF ratio {train_bt['pf']:.1f}/{val_bt['pf']:.1f} > 2×")
        if train_bt["win_rate"] > val_bt["win_rate"] + 0.10:
            overfit_flags.append(f"WR gap {train_bt['win_rate']:.1%} vs {val_bt['win_rate']:.1%}")
        if val_bt["sharpe"] < 0.5 and val_bt["n_trades"] > 20:
            overfit_flags.append(f"Low OOS Sharpe {val_bt['sharpe']:.2f}")

        status = "OVERFIT" if overfit_flags else "OK"

        print(f"      Train: acc={train_acc:.4f} | {train_bt['n_trades']} trades | WR={train_bt['win_rate']:.2%} | PF={train_bt['pf']:.2f} | Sharpe={train_bt['sharpe']:.2f}")
        print(f"      Test:  acc={val_acc:.4f} | {val_bt['n_trades']} trades | WR={val_bt['win_rate']:.2%} | PF={val_bt['pf']:.2f} | Sharpe={val_bt['sharpe']:.2f}")
        print(f"      Status: {status}" + (f" — {'; '.join(overfit_flags)}" if overfit_flags else ""))

        fold_results.append({
            "fold": fold + 1,
            "train_acc": round(train_acc, 4),
            "val_acc": round(val_acc, 4),
            "train_bt": train_bt,
            "val_bt": val_bt,
            "overfit_flags": overfit_flags,
            "status": status,
        })

    # Aggregate
    if not fold_results:
        return None

    oos_pfs = [f["val_bt"]["pf"] for f in fold_results]
    oos_sharpes = [f["val_bt"]["sharpe"] for f in fold_results]
    oos_wrs = [f["val_bt"]["win_rate"] for f in fold_results]
    oos_trades = sum(f["val_bt"]["n_trades"] for f in fold_results)
    overfit_count = sum(1 for f in fold_results if f["status"] == "OVERFIT")

    agg = {
        "avg_oos_pf": round(np.mean(oos_pfs), 4),
        "avg_oos_sharpe": round(np.mean(oos_sharpes), 4),
        "avg_oos_wr": round(np.mean(oos_wrs), 4),
        "total_oos_trades": oos_trades,
        "overfit_folds": overfit_count,
        "total_folds": len(fold_results),
        "verdict": "OVERFIT" if overfit_count > len(fold_results) // 2 else "PASS",
    }

    print(f"\n    {'─' * 50}")
    print(f"    AGGREGATE OOS: PF={agg['avg_oos_pf']:.2f} | Sharpe={agg['avg_oos_sharpe']:.2f} | WR={agg['avg_oos_wr']:.2%} | Trades={oos_trades}")
    print(f"    Overfit folds: {overfit_count}/{len(fold_results)} → {agg['verdict']}")

    return {
        "symbol": symbol,
        "model_type": model_type,
        "folds": fold_results,
        "aggregate": agg,
    }


def main():
    parser = argparse.ArgumentParser(description="Walk-Forward Backtest")
    parser.add_argument("--symbols", nargs="+", default=ALL_SYMBOLS)
    parser.add_argument("--quick", action="store_true", help="3 folds instead of 5")
    args = parser.parse_args()

    n_folds = 3 if args.quick else 5

    print("=" * 70)
    print("  TRADEFORGE — Walk-Forward Backtest (Overfitting Check)")
    print("=" * 70)
    print(f"  Symbols: {args.symbols}")
    print(f"  Folds:   {n_folds}")
    print()

    all_results = {}
    grand_start = time.time()

    for symbol in args.symbols:
        if symbol not in SYMBOL_PARAMS:
            print(f"  Unknown symbol: {symbol}")
            continue

        for model_type in ["xgboost", "lightgbm"]:
            key = f"{symbol}_{model_type}"
            print(f"\n{'#' * 60}")
            print(f"  {symbol} — {model_type.upper()}")
            print(f"{'#' * 60}")

            t0 = time.time()
            result = walk_forward_validate(symbol, model_type, n_folds=n_folds)
            elapsed = time.time() - t0

            if result:
                all_results[key] = result
                print(f"\n  Done in {elapsed:.0f}s")
            else:
                print(f"\n  No results")

    # Final summary
    total = time.time() - grand_start
    print(f"\n\n{'=' * 70}")
    print(f"  WALK-FORWARD BACKTEST SUMMARY")
    print(f"  Total time: {total:.0f}s ({total/60:.1f}m)")
    print(f"{'=' * 70}")
    print(f"\n  {'Symbol':<10} {'Model':<12} {'OOS PF':>8} {'OOS Sharpe':>12} {'OOS WR':>8} {'Trades':>8} {'Verdict':>10}")
    print(f"  {'─' * 70}")

    for key, result in all_results.items():
        agg = result["aggregate"]
        print(f"  {result['symbol']:<10} {result['model_type']:<12} "
              f"{agg['avg_oos_pf']:>8.2f} {agg['avg_oos_sharpe']:>12.2f} "
              f"{agg['avg_oos_wr']:>7.2%} {agg['total_oos_trades']:>8} "
              f"{'✗ OVERFIT' if agg['verdict'] == 'OVERFIT' else '✓ PASS':>10}")

    # Save results
    results_path = RESULTS_DIR / "walk_forward_results.json"
    with open(results_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Full results: {results_path}")

    # Check for any overfitting
    overfit_models = [k for k, v in all_results.items() if v["aggregate"]["verdict"] == "OVERFIT"]
    if overfit_models:
        print(f"\n  ⚠ OVERFIT MODELS: {', '.join(overfit_models)}")
        print(f"  These models may need retraining with stronger regularization.")
    else:
        print(f"\n  ✓ All models PASS walk-forward validation — no overfitting detected.")


if __name__ == "__main__":
    main()
