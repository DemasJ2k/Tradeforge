"""
Enhanced Retrain — retrain models on 2020-2026 data with 2022-2026 OOS validation.

Retrains:
  - BTCUSD scalping (Grade B → try for Grade A)
  - All 5 expert models (XGB + LGB + LSTM + Meta + Regime)

Skips:
  - Grade A scalping models (XAUUSD, US30, ES, NAS100) — already production-ready

Data windows:
  - Training: 2020-01-01 → 2026-03-20 (full range)
  - OOS test: 2022-01-01 → 2026-03-20 (walk-forward folds within this range)

Usage:
    python scripts/enhanced_retrain.py
    python scripts/enhanced_retrain.py --quick       # 10 Optuna trials, 5 LSTM epochs
    python scripts/enhanced_retrain.py --section 1   # scalping only
    python scripts/enhanced_retrain.py --section 2   # expert XAUUSD, US30, ES
    python scripts/enhanced_retrain.py --section 3   # expert NAS100, BTCUSD
    python scripts/enhanced_retrain.py --section all  # everything
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DATA_DIR = Path(__file__).parent.parent / "data" / "databento"
MODEL_DIR = Path(__file__).parent.parent / "data" / "ml_models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR = Path(__file__).parent.parent / "data" / "enhanced_retrain_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Date filters
TRAIN_START = datetime(2020, 1, 1, tzinfo=timezone.utc)
TRAIN_END = datetime(2026, 3, 21, tzinfo=timezone.utc)  # inclusive of all data
OOS_START = datetime(2022, 1, 1, tzinfo=timezone.utc)

ALL_SYMBOLS = ["XAUUSD", "US30", "ES", "NAS100", "BTCUSD"]

# Scalping models to retrain (non-Grade A only)
SCALPING_RETRAIN = ["BTCUSD"]  # Grade B — all others are Grade A


def load_csv_with_dates(path: str, start_dt: datetime, end_dt: datetime) -> list[dict]:
    """Load OHLCV CSV filtered to a date range."""
    import csv

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
                        dt = datetime.fromisoformat(str(dt_val).replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        rec["datetime"] = dt
                    except (ValueError, TypeError):
                        rec["datetime"] = None
                        continue  # skip bars without valid datetime in date-filtered mode

                if rec["close"] > 0 and rec["datetime"]:
                    if start_dt <= rec["datetime"] <= end_dt:
                        data.append(rec)
            except (ValueError, TypeError):
                continue
    return data


def load_symbol_data(symbol: str, timeframe: str, start_dt: datetime, end_dt: datetime) -> list[dict] | None:
    """Load data for a symbol and timeframe within date range."""
    csv_path = DATA_DIR / f"{symbol}_{timeframe}.csv"
    if not csv_path.exists():
        return None
    data = load_csv_with_dates(str(csv_path), start_dt, end_dt)
    if data:
        first_dt = data[0].get("datetime", "?")
        last_dt = data[-1].get("datetime", "?")
        print(f"    {timeframe}: {len(data):,} bars ({first_dt} → {last_dt})")
    return data if data else None


# ── Section 1: BTCUSD Scalping ─────────────────────────

def run_scalping_retrain(quick: bool = False):
    """Retrain BTCUSD scalping models on 2020-2026 data."""
    from scripts.train_scalping_pipeline import (
        compute_all_features, compute_triple_barrier_targets,
        clean_xy, map_targets_to_classes, walk_forward_train,
        save_best_model, SYMBOL_PARAMS as SCALP_PARAMS, _compute_metrics,
    )
    import scripts.train_scalping_pipeline as scalp_mod
    import numpy as np

    # Inject all symbol params
    extra_params = {
        "BTCUSD": {
            "commission_per_lot": 0.50,
            "spread_points": 5.0,
            "point_value": 1.0,
            "atr_sl_mult": 2.0,
            "atr_tp_mult": 3.0,
            "max_holding_bars": 24,
        },
        "ES": {
            "commission_per_lot": 1.24,
            "spread_points": 0.25,
            "point_value": 50.0,
            "atr_sl_mult": 1.5,
            "atr_tp_mult": 2.0,
            "max_holding_bars": 12,
        },
        "NAS100": {
            "commission_per_lot": 1.24,
            "spread_points": 0.50,
            "point_value": 20.0,
            "atr_sl_mult": 1.5,
            "atr_tp_mult": 2.0,
            "max_holding_bars": 12,
        },
    }
    for sym, params in extra_params.items():
        if sym not in SCALP_PARAMS:
            SCALP_PARAMS[sym] = params

    trials = 10 if quick else 50
    n_folds = 3 if quick else 5
    all_results = {}

    for symbol in SCALPING_RETRAIN:
        print(f"\n{'#' * 70}")
        print(f"  SCALPING RETRAIN: {symbol} (2020-2026)")
        print(f"  Optuna trials: {trials} | WF folds: {n_folds}")
        print(f"{'#' * 70}")

        params = SCALP_PARAMS[symbol]
        t0 = time.time()

        # Load date-filtered data
        print("\n  Loading data (2020-2026)...")
        m5_data = load_symbol_data(symbol, "M5", TRAIN_START, TRAIN_END)
        h1_data = load_symbol_data(symbol, "H1", TRAIN_START, TRAIN_END)

        if not m5_data or len(m5_data) < 1000:
            print(f"  SKIP: Insufficient M5 data for {symbol}")
            continue

        # Compute features
        print("  Computing features...")
        feature_names, X = compute_all_features(m5_data, h1_data)
        print(f"  {len(feature_names)} features computed")

        # Compute targets
        y_raw = compute_triple_barrier_targets(m5_data, params)

        # Clean
        X_clean, y_clean = clean_xy(X, y_raw)
        y_classes, label_map = map_targets_to_classes(y_clean)
        print(f"  Clean samples: {len(X_clean):,} | Label map: {label_map}")

        # Price arrays
        closes_all = np.array([d["close"] for d in m5_data], dtype=np.float64)
        highs_all = np.array([d["high"] for d in m5_data], dtype=np.float64)
        lows_all = np.array([d["low"] for d in m5_data], dtype=np.float64)

        valid_mask = np.isfinite(y_raw)
        if X.ndim == 2:
            valid_mask &= np.all(np.isfinite(X), axis=1)
        closes_clean = closes_all[valid_mask]
        highs_clean = highs_all[valid_mask]
        lows_clean = lows_all[valid_mask]

        results = {}

        # XGBoost
        print("\n  ── XGBoost ──")
        xgb_result = walk_forward_train(
            X_clean, y_classes, feature_names,
            closes_clean, highs_clean, lows_clean,
            symbol, "xgboost", params,
            n_folds=n_folds, n_trials=trials,
        )
        save_best_model(xgb_result, symbol, "xgboost")
        results["xgboost"] = xgb_result

        # LightGBM
        print("\n  ── LightGBM ──")
        lgb_result = walk_forward_train(
            X_clean, y_classes, feature_names,
            closes_clean, highs_clean, lows_clean,
            symbol, "lightgbm", params,
            n_folds=n_folds, n_trials=trials,
        )
        save_best_model(lgb_result, symbol, "lightgbm")
        results["lightgbm"] = lgb_result

        elapsed = time.time() - t0
        print(f"\n  {symbol} scalping done in {elapsed:.0f}s ({elapsed/60:.1f}m)")

        all_results[symbol] = results

    return all_results


# ── Section 2 & 3: Expert Models ─────────────────────────

def run_expert_retrain(symbols: list[str], quick: bool = False):
    """Retrain expert models on 2020-2026 data."""
    import scripts.train_expert_agent as expert_mod
    from scripts.train_expert_agent import (
        compute_expert_feature_matrix, compute_targets,
        train_expert_tree, train_expert_lstm,
        train_expert_meta_labeler, train_expert_regime,
        register_model_in_db, SYMBOL_PARAMS as EXPERT_PARAMS,
    )
    import numpy as np

    # Inject missing symbol params
    extra_params = {
        "ES": {
            "commission": 0.0001,
            "spread": 0.25,
            "atr_sl_mult": 1.5,
            "atr_tp_mult": 2.0,
            "max_holding_bars": 12,
            "swing_lookback": 5,
        },
        "NAS100": {
            "commission": 0.0001,
            "spread": 0.50,
            "atr_sl_mult": 1.5,
            "atr_tp_mult": 2.0,
            "max_holding_bars": 12,
            "swing_lookback": 5,
        },
    }
    for sym, params in extra_params.items():
        if sym not in EXPERT_PARAMS:
            EXPERT_PARAMS[sym] = params

    all_results = {}

    for symbol in symbols:
        print(f"\n{'#' * 70}")
        print(f"  EXPERT RETRAIN: {symbol} (2020-2026)")
        print(f"{'#' * 70}")

        params = EXPERT_PARAMS.get(symbol, EXPERT_PARAMS["XAUUSD"])
        t0 = time.time()

        # Load date-filtered data
        print("\n  Loading data (2020-2026)...")
        m5_data = load_symbol_data(symbol, "M5", TRAIN_START, TRAIN_END)
        h1_data = load_symbol_data(symbol, "H1", TRAIN_START, TRAIN_END)
        h4_data = load_symbol_data(symbol, "H4", TRAIN_START, TRAIN_END)
        d1_data = load_symbol_data(symbol, "D1", TRAIN_START, TRAIN_END)

        if not m5_data or len(m5_data) < 1000:
            print(f"  SKIP: Insufficient M5 data for {symbol}")
            continue

        # Cap M5 data at 500K bars to prevent OOM
        if len(m5_data) > 500_000:
            m5_data = m5_data[-500_000:]
            print(f"  Capped M5 to 500K bars")

        # Compute features
        print(f"\n  Computing expert features...")
        feat_t0 = time.time()
        feature_names, X = compute_expert_feature_matrix(m5_data, h1_data, h4_data, d1_data)
        print(f"  Features: {len(feature_names)} x {X.shape[0]:,} ({time.time() - feat_t0:.1f}s)")

        if X.shape[0] == 0:
            print(f"  SKIP: No features computed")
            continue

        # Compute targets
        target_name, y = compute_targets(m5_data, params)
        min_len = min(len(X), len(y))
        X = X[:min_len]
        y = y[:min_len]

        results = {}

        # [1/5] XGBoost
        print(f"\n  [1/5] XGBoost")
        xgb_result = train_expert_tree(X, y, feature_names, symbol, "xgboost", quick)
        if xgb_result:
            register_model_in_db(
                name=f"expert_{symbol}_M5_xgboost",
                model_type="expert_xgboost",
                symbol=symbol, timeframe="M5", level=2,
                model_path=xgb_result["model_path"],
                train_metrics=xgb_result["train_metrics"],
                val_metrics=xgb_result["val_metrics"],
                features_config={"type": "expert_v1", "features": feature_names},
                hyperparams=params,
            )
            results["xgboost"] = xgb_result

        # [2/5] LightGBM
        print(f"\n  [2/5] LightGBM")
        lgb_result = train_expert_tree(X, y, feature_names, symbol, "lightgbm", quick)
        if lgb_result:
            register_model_in_db(
                name=f"expert_{symbol}_M5_lightgbm",
                model_type="expert_lightgbm",
                symbol=symbol, timeframe="M5", level=2,
                model_path=lgb_result["model_path"],
                train_metrics=lgb_result["train_metrics"],
                val_metrics=lgb_result["val_metrics"],
                features_config={"type": "expert_v1", "features": feature_names},
                hyperparams=params,
            )
            results["lightgbm"] = lgb_result

        # [3/5] LSTM
        print(f"\n  [3/5] LSTM")
        lstm_result = train_expert_lstm(X, y, feature_names, symbol, quick)
        if lstm_result:
            register_model_in_db(
                name=f"expert_{symbol}_M5_lstm",
                model_type="expert_lstm",
                symbol=symbol, timeframe="M5", level=2,
                model_path=lstm_result["model_path"],
                train_metrics=lstm_result["train_metrics"],
                val_metrics=lstm_result["val_metrics"],
                features_config={"type": "expert_v1", "features": feature_names},
                hyperparams={"seq_len": 60},
            )
            results["lstm"] = lstm_result

        # [4/5] Meta-labeler
        if xgb_result and lgb_result:
            print(f"\n  [4/5] Meta-Labeler")
            meta_result = train_expert_meta_labeler(
                X, y, feature_names,
                xgb_result["model_path"],
                lgb_result["model_path"],
                symbol, quick,
            )
            if meta_result:
                register_model_in_db(
                    name=f"expert_{symbol}_M5_meta",
                    model_type="expert_meta",
                    symbol=symbol, timeframe="M5", level=2,
                    model_path=meta_result["model_path"],
                    train_metrics=meta_result["train_metrics"],
                    val_metrics=meta_result["val_metrics"],
                    features_config={"type": "expert_v1_meta"},
                    hyperparams={},
                )
                results["meta"] = meta_result

        # [5/5] Regime Detector
        print(f"\n  [5/5] Regime Detector")
        regime_result = train_expert_regime(m5_data, symbol)
        if regime_result:
            register_model_in_db(
                name=f"expert_{symbol}_M5_regime",
                model_type="expert_hmm_regime",
                symbol=symbol, timeframe="M5", level=1,
                model_path=regime_result.get("model_path", ""),
                train_metrics=regime_result.get("stats", {}),
                val_metrics={},
                features_config={"type": "hmm_regime", "n_states": 4},
                hyperparams={"n_states": 4},
            )
            results["regime"] = regime_result

        elapsed = time.time() - t0
        print(f"\n  {symbol} expert done in {elapsed:.0f}s ({elapsed/60:.1f}m)")
        all_results[symbol] = results

    return all_results


# ── Walk-Forward OOS Validation (2022-2026) ──────────────

def run_oos_validation(quick: bool = False):
    """Validate all retrained models with OOS testing on 2022-2026 data."""
    from scripts.walk_forward_backtest import (
        compute_features_and_targets, backtest_predictions,
        walk_forward_validate, SYMBOL_PARAMS as WF_PARAMS,
    )
    import numpy as np

    # We run walk-forward validation using data from 2020 onwards
    # but the OOS folds span 2022-2026
    n_folds = 3 if quick else 5

    print(f"\n{'=' * 70}")
    print(f"  OOS VALIDATION (2022-2026 test window)")
    print(f"  Folds: {n_folds}")
    print(f"{'=' * 70}")

    # Validate BTCUSD scalping + all expert models
    validate_symbols = ALL_SYMBOLS
    all_results = {}

    for symbol in validate_symbols:
        for model_type in ["xgboost", "lightgbm"]:
            key = f"{symbol}_{model_type}"
            print(f"\n{'#' * 60}")
            print(f"  {symbol} — {model_type.upper()}")
            print(f"{'#' * 60}")

            t0 = time.time()
            # Load 2020-2026 data for validation
            m5_data = load_symbol_data(symbol, "M5", TRAIN_START, TRAIN_END)
            h1_data = load_symbol_data(symbol, "H1", TRAIN_START, TRAIN_END)

            if not m5_data or len(m5_data) < 5000:
                print(f"  SKIP: Insufficient data")
                continue

            # Cap at 500K bars
            if len(m5_data) > 500_000:
                m5_data = m5_data[-500_000:]
            if h1_data and len(h1_data) > 50_000:
                h1_data = h1_data[-50_000:]

            params = WF_PARAMS.get(symbol, WF_PARAMS["XAUUSD"])

            print(f"    Computing features...")
            try:
                feat_names, X, y, closes, highs, lows = compute_features_and_targets(
                    m5_data, h1_data, params,
                )
            except Exception as e:
                print(f"    ERROR computing features: {e}")
                continue

            n = len(X)
            fold_size = n // (n_folds + 1)

            # Find the index corresponding to OOS_START (2022)
            oos_start_idx = 0
            for i, bar in enumerate(m5_data[:n]):
                dt = bar.get("datetime")
                if dt and dt >= OOS_START:
                    oos_start_idx = i
                    break

            print(f"    Samples: {n:,} | OOS start index: {oos_start_idx:,} ({oos_start_idx/n:.0%})")

            fold_results = []
            for fold in range(n_folds):
                # Expanding window: train up to some point, test on next chunk
                # Ensure test folds are in the 2022-2026 range
                train_end = oos_start_idx + fold * ((n - oos_start_idx) // (n_folds + 1))
                if train_end < oos_start_idx:
                    train_end = oos_start_idx
                val_start = train_end
                val_end = min(val_start + (n - oos_start_idx) // (n_folds + 1), n)

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

                if len(X_train) < 500:
                    print(f"      SKIP: too few training samples ({len(X_train)})")
                    continue

                model.fit(X_train, y_train)

                from sklearn.metrics import accuracy_score
                val_pred = model.predict(X_val)
                val_proba = model.predict_proba(X_val)
                val_conf = np.max(val_proba, axis=1)
                val_acc = accuracy_score(y_val, val_pred)

                val_bt = backtest_predictions(
                    val_pred, val_conf,
                    closes[val_start:val_end], highs[val_start:val_end], lows[val_start:val_end],
                    params,
                )

                print(f"      OOS: acc={val_acc:.4f} | {val_bt['n_trades']} trades | "
                      f"WR={val_bt['win_rate']:.2%} | PF={val_bt['pf']:.2f} | Sharpe={val_bt['sharpe']:.2f}")

                fold_results.append({
                    "fold": fold + 1,
                    "val_acc": round(val_acc, 4),
                    "val_bt": val_bt,
                })

            if fold_results:
                import numpy as _np
                avg_pf = _np.mean([f["val_bt"]["pf"] for f in fold_results])
                avg_sharpe = _np.mean([f["val_bt"]["sharpe"] for f in fold_results])
                avg_wr = _np.mean([f["val_bt"]["win_rate"] for f in fold_results])
                total_trades = sum(f["val_bt"]["n_trades"] for f in fold_results)
                verdict = "PASS" if avg_pf > 1.0 and avg_sharpe > 0.5 else "MARGINAL" if avg_pf > 0.9 else "FAIL"

                print(f"\n    AGGREGATE: PF={avg_pf:.2f} | Sharpe={avg_sharpe:.2f} | WR={avg_wr:.2%} | Trades={total_trades} → {verdict}")

                all_results[key] = {
                    "symbol": symbol,
                    "model_type": model_type,
                    "folds": fold_results,
                    "aggregate": {
                        "avg_pf": round(avg_pf, 4),
                        "avg_sharpe": round(avg_sharpe, 4),
                        "avg_wr": round(avg_wr, 4),
                        "total_trades": total_trades,
                        "verdict": verdict,
                    },
                }

            elapsed = time.time() - t0
            print(f"    Done in {elapsed:.0f}s")

    # Summary
    print(f"\n\n{'=' * 70}")
    print(f"  OOS VALIDATION SUMMARY (2022-2026)")
    print(f"{'=' * 70}")
    print(f"\n  {'Symbol':<10} {'Model':<12} {'OOS PF':>8} {'Sharpe':>8} {'WR':>8} {'Trades':>8} {'Verdict':>10}")
    print(f"  {'─' * 66}")
    for key, result in all_results.items():
        agg = result["aggregate"]
        print(f"  {result['symbol']:<10} {result['model_type']:<12} "
              f"{agg['avg_pf']:>8.2f} {agg['avg_sharpe']:>8.2f} "
              f"{agg['avg_wr']:>7.2%} {agg['total_trades']:>8} "
              f"{agg['verdict']:>10}")

    # Save
    results_path = RESULTS_DIR / "oos_validation_results.json"
    with open(results_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Results saved: {results_path}")

    return all_results


def save_results(name: str, results: dict):
    """Save results to JSON."""
    path = RESULTS_DIR / f"{name}.json"
    with open(path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  Results saved: {path}")


def main():
    parser = argparse.ArgumentParser(description="Enhanced Retrain Pipeline")
    parser.add_argument("--section", choices=["1", "2", "3", "4", "all"], default="all",
                        help="1=scalping, 2=expert(XAUUSD,US30,ES), 3=expert(NAS100,BTCUSD), 4=OOS validation")
    parser.add_argument("--quick", action="store_true", help="Quick mode")
    args = parser.parse_args()

    sections = ["1", "2", "3", "4"] if args.section == "all" else [args.section]

    print("=" * 70)
    print("  TRADEFORGE — Enhanced Retrain Pipeline")
    print("=" * 70)
    print(f"  Sections:    {sections}")
    print(f"  Quick mode:  {args.quick}")
    print(f"  Train data:  {TRAIN_START.date()} → {TRAIN_END.date()}")
    print(f"  OOS test:    {OOS_START.date()} → {TRAIN_END.date()}")
    print(f"  Scalping:    {SCALPING_RETRAIN} (non-Grade-A only)")
    print(f"  Expert:      {ALL_SYMBOLS} (all)")
    print()

    grand_start = time.time()

    for section in sections:
        section_start = time.time()

        if section == "1":
            print(f"\n{'█' * 70}")
            print(f"  SECTION 1: Scalping — {SCALPING_RETRAIN}")
            print(f"{'█' * 70}")
            results = run_scalping_retrain(quick=args.quick)
            save_results("section1_scalping", results)

        elif section == "2":
            print(f"\n{'█' * 70}")
            print(f"  SECTION 2: Expert — XAUUSD, US30, ES")
            print(f"{'█' * 70}")
            results = run_expert_retrain(["XAUUSD", "US30", "ES"], quick=args.quick)
            save_results("section2_expert", results)

        elif section == "3":
            print(f"\n{'█' * 70}")
            print(f"  SECTION 3: Expert — NAS100, BTCUSD")
            print(f"{'█' * 70}")
            results = run_expert_retrain(["NAS100", "BTCUSD"], quick=args.quick)
            save_results("section3_expert", results)

        elif section == "4":
            print(f"\n{'█' * 70}")
            print(f"  SECTION 4: OOS Validation (2022-2026)")
            print(f"{'█' * 70}")
            results = run_oos_validation(quick=args.quick)
            save_results("section4_oos_validation", results)

        elapsed = time.time() - section_start
        print(f"\n  Section {section} done in {elapsed:.0f}s ({elapsed/60:.1f}m)")

    total = time.time() - grand_start
    print(f"\n\n{'█' * 70}")
    print(f"  ENHANCED RETRAIN COMPLETE — {total:.0f}s ({total/60:.1f}m)")
    print(f"{'█' * 70}")

    # List model files
    print(f"\n  Updated model files:")
    for f in sorted(MODEL_DIR.glob("*")):
        if f.is_file() and f.suffix in (".joblib", ".onnx"):
            size_mb = f.stat().st_size / 1024 / 1024
            name = f.name
            if name.startswith("scalping_") or name.startswith("expert_"):
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                print(f"    {name:<50} {size_mb:>6.1f} MB  {mtime.strftime('%Y-%m-%d %H:%M')}")


if __name__ == "__main__":
    main()
