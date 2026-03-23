"""
Scalping Pipeline — Optuna-tuned XGBoost + LightGBM with walk-forward validation.

Trains production-grade scalping models for XAUUSD and US30 on M5:
  1. Loads M5 + H1 data from cached CSVs
  2. Computes full expert features (80+ technical + structure + session + MTF)
  3. Triple-barrier labeling (ATR-based SL/TP + time expiry)
  4. Optuna hyperparameter search (50 trials per model)
  5. Walk-forward validation (5 folds, expanding window)
  6. Backtests best model per fold with realistic costs
  7. Grades models: A (deploy) / B (paper) / C (review) / D (reject)
  8. Saves A/B-grade models for agent use

Usage:
    python scripts/train_scalping_pipeline.py
    python scripts/train_scalping_pipeline.py --symbols XAUUSD
    python scripts/train_scalping_pipeline.py --quick   # 10 Optuna trials
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

# ── Configuration ──────────────────────────────────────

DATA_DIR = Path(__file__).parent.parent / "data" / "databento"
MODEL_DIR = Path(__file__).parent.parent / "data" / "ml_models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR = Path(__file__).parent.parent / "data" / "scalping_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

SYMBOL_PARAMS = {
    "XAUUSD": {
        "commission_per_lot": 0.30,   # $0.30 per side
        "spread_points": 0.30,        # typical spread
        "point_value": 100.0,         # $100 per 1.0 move per lot
        "atr_sl_mult": 1.5,
        "atr_tp_mult": 2.5,
        "max_holding_bars": 12,       # 1 hour on M5
    },
    "US30": {
        "commission_per_lot": 1.0,
        "spread_points": 2.0,
        "point_value": 1.0,           # $1 per 1.0 move per lot
        "atr_sl_mult": 1.5,
        "atr_tp_mult": 2.0,
        "max_holding_bars": 12,
    },
}

# Grade thresholds
GRADE_THRESHOLDS = {
    "A": {"min_profit_factor": 1.5, "min_sharpe": 1.0, "min_win_rate": 0.52},
    "B": {"min_profit_factor": 1.2, "min_sharpe": 0.5, "min_win_rate": 0.50},
    "C": {"min_profit_factor": 1.0, "min_sharpe": 0.0, "min_win_rate": 0.48},
}

N_WF_FOLDS = 5
OPTUNA_TRIALS = 50


# ── Data Loading ───────────────────────────────────────

def load_csv(path: str) -> list[dict]:
    """Load OHLCV CSV into list of dicts."""
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


def extract_arrays(data: list[dict]):
    """Extract numpy arrays + lists from data dicts."""
    opens = [d["open"] for d in data]
    highs = [d["high"] for d in data]
    lows = [d["low"] for d in data]
    closes = [d["close"] for d in data]
    volumes = [d["volume"] for d in data]
    timestamps = [d.get("datetime") for d in data]
    return opens, highs, lows, closes, volumes, timestamps


# ── Feature Computation ───────────────────────────────

def compute_all_features(m5_data, h1_data):
    """Compute full expert features for M5 data with H1 context."""
    from app.services.ml.features_mtf import compute_expert_features
    feature_names, feature_matrix = compute_expert_features(
        m5_data, h1_data, None, None
    )
    return feature_names, np.array(feature_matrix, dtype=np.float64)


def compute_triple_barrier_targets(m5_data, params):
    """Compute triple-barrier labels."""
    from app.services.ml.features import compute_targets

    closes = [d["close"] for d in m5_data]
    highs = [d["high"] for d in m5_data]
    lows = [d["low"] for d in m5_data]

    target_config = {
        "type": "triple_barrier",
        "horizon": params["max_holding_bars"],
        "sl_atr_mult": params["atr_sl_mult"],
        "tp_atr_mult": params["atr_tp_mult"],
        "max_holding_bars": params["max_holding_bars"],
    }
    name, values = compute_targets(closes, target_config, highs, lows)
    return np.array(values, dtype=np.float64)


# ── Clean Data ─────────────────────────────────────────

def clean_xy(X, y):
    """Remove NaN/inf rows from X and y."""
    valid = np.isfinite(y)
    if X.ndim == 2:
        valid &= np.all(np.isfinite(X), axis=1)
    return X[valid], y[valid]


def map_targets_to_classes(y):
    """Map triple-barrier {0.0, 0.5, 1.0} → {0, 1, 2}."""
    unique = np.unique(y[np.isfinite(y)])
    label_map = {v: i for i, v in enumerate(sorted(unique))}
    return np.array([label_map.get(v, 1) for v in y], dtype=np.int64), label_map


# ── Optuna Hyperparameter Search ──────────────────────

def optuna_xgboost(X_train, y_train, X_val, y_val, n_trials=50):
    """Optuna search for XGBoost hyperparameters."""
    import optuna
    from xgboost import XGBClassifier
    from sklearn.metrics import log_loss

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial):
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 100, 500),
            "max_depth": trial.suggest_int("max_depth", 3, 8),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 20),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
            "gamma": trial.suggest_float("gamma", 0.0, 5.0),
        }
        model = XGBClassifier(
            **params,
            use_label_encoder=False,
            eval_metric="mlogloss",
            random_state=42,
            n_jobs=-1,
        )
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
        pred_proba = model.predict_proba(X_val)
        return log_loss(y_val, pred_proba)

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    return study.best_params


def optuna_lightgbm(X_train, y_train, X_val, y_val, n_trials=50):
    """Optuna search for LightGBM hyperparameters."""
    import optuna
    from lightgbm import LGBMClassifier
    from sklearn.metrics import log_loss

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial):
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 100, 500),
            "max_depth": trial.suggest_int("max_depth", 3, 8),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "min_child_samples": trial.suggest_int("min_child_samples", 5, 50),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
            "num_leaves": trial.suggest_int("num_leaves", 15, 63),
        }
        model = LGBMClassifier(
            **params, random_state=42, n_jobs=-1, verbose=-1,
        )
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)])
        pred_proba = model.predict_proba(X_val)
        return log_loss(y_val, pred_proba)

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    return study.best_params


# ── Walk-Forward Backtest ─────────────────────────────

def backtest_predictions(
    predictions: np.ndarray,
    confidences: np.ndarray,
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    params: dict,
    confidence_threshold: float = 0.55,
) -> dict:
    """
    Backtest model predictions with realistic costs.

    predictions: 0=SL(short bias), 1=neutral, 2=TP(long bias)
    confidences: probability of predicted class
    """
    n = len(predictions)
    trades = []
    max_bars = params["max_holding_bars"]
    sl_mult = params["atr_sl_mult"]
    tp_mult = params["atr_tp_mult"]
    spread = params["spread_points"]
    commission = params["commission_per_lot"]
    point_value = params["point_value"]

    # Compute ATR(14) for SL/TP sizing
    atr = np.full(n, np.nan)
    for i in range(14, n):
        tr_vals = []
        for j in range(i - 13, i + 1):
            tr = max(highs[j] - lows[j],
                     abs(highs[j] - closes[j - 1]),
                     abs(lows[j] - closes[j - 1]))
            tr_vals.append(tr)
        atr[i] = np.mean(tr_vals)

    for i in range(14, n - max_bars):
        pred = predictions[i]
        conf = confidences[i]

        # Only trade strong directional signals
        if pred == 1:  # neutral → skip
            continue
        if conf < confidence_threshold:
            continue
        if np.isnan(atr[i]):
            continue

        direction = 1 if pred == 2 else -1  # 2=TP=long, 0=SL=short
        entry = closes[i]
        sl_dist = atr[i] * sl_mult
        tp_dist = atr[i] * tp_mult

        if direction == 1:
            sl = entry - sl_dist
            tp = entry + tp_dist
        else:
            sl = entry + sl_dist
            tp = entry - tp_dist

        # Simulate forward
        exit_price = None
        exit_bar = None
        exit_reason = None

        for j in range(i + 1, min(i + max_bars + 1, n)):
            if direction == 1:
                if lows[j] <= sl:
                    exit_price = sl
                    exit_reason = "sl"
                    exit_bar = j
                    break
                if highs[j] >= tp:
                    exit_price = tp
                    exit_reason = "tp"
                    exit_bar = j
                    break
            else:
                if highs[j] >= sl:
                    exit_price = sl
                    exit_reason = "sl"
                    exit_bar = j
                    break
                if lows[j] <= tp:
                    exit_price = tp
                    exit_reason = "tp"
                    exit_bar = j
                    break

        if exit_price is None:
            # Time expiry
            exit_bar = min(i + max_bars, n - 1)
            exit_price = closes[exit_bar]
            exit_reason = "time"

        pnl_points = (exit_price - entry) * direction
        cost_points = spread + (2 * commission / point_value)
        net_pnl = pnl_points - cost_points

        trades.append({
            "entry_bar": i,
            "exit_bar": exit_bar,
            "direction": direction,
            "entry": entry,
            "exit": exit_price,
            "pnl_points": pnl_points,
            "cost_points": cost_points,
            "net_pnl": net_pnl,
            "exit_reason": exit_reason,
            "confidence": conf,
        })

    return _compute_metrics(trades)


def _compute_metrics(trades: list[dict]) -> dict:
    """Compute performance metrics from trade list."""
    if not trades:
        return {
            "n_trades": 0, "win_rate": 0, "profit_factor": 0,
            "sharpe": 0, "max_dd_pct": 0, "avg_pnl": 0,
            "total_pnl": 0, "trades": [],
        }

    pnls = [t["net_pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_rate = len(wins) / len(pnls)
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0.001
    profit_factor = gross_profit / gross_loss

    pnl_arr = np.array(pnls)
    avg_pnl = np.mean(pnl_arr)
    std_pnl = np.std(pnl_arr) if len(pnl_arr) > 1 else 1.0
    sharpe = (avg_pnl / std_pnl) * np.sqrt(252 * 12) if std_pnl > 1e-10 else 0  # annualized ~M5

    # Max drawdown
    equity = np.cumsum(pnl_arr)
    peak = np.maximum.accumulate(equity)
    dd = peak - equity
    max_dd = np.max(dd) if len(dd) > 0 else 0
    max_dd_pct = max_dd / (np.max(np.abs(peak)) + 1e-10)

    return {
        "n_trades": len(trades),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "sharpe": round(sharpe, 4),
        "max_dd_pct": round(max_dd_pct, 4),
        "avg_pnl": round(avg_pnl, 4),
        "total_pnl": round(sum(pnls), 2),
        "trades": trades,
    }


# ── Grade Assignment ──────────────────────────────────

def grade_model(metrics: dict) -> str:
    """Assign A/B/C/D grade based on walk-forward metrics."""
    for grade in ("A", "B", "C"):
        thresh = GRADE_THRESHOLDS[grade]
        if (metrics["profit_factor"] >= thresh["min_profit_factor"]
                and metrics["sharpe"] >= thresh["min_sharpe"]
                and metrics["win_rate"] >= thresh["min_win_rate"]):
            return grade
    return "D"


# ── Walk-Forward Training ─────────────────────────────

def walk_forward_train(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    symbol: str,
    model_type: str,
    params: dict,
    n_folds: int = 5,
    n_trials: int = 50,
) -> dict:
    """
    Walk-forward validation with Optuna tuning per fold.

    Expanding window: each fold trains on all data up to fold boundary,
    validates on the next chunk.
    """
    n = len(X)
    fold_size = n // (n_folds + 1)  # reserve 1 chunk for initial training

    print(f"\n{'='*60}")
    print(f"  Walk-Forward: {symbol} {model_type.upper()}")
    print(f"  Samples: {n:,}  |  Folds: {n_folds}  |  Fold size: {fold_size:,}")
    print(f"{'='*60}")

    all_fold_metrics = []
    best_model = None
    best_fold_grade = "D"

    for fold in range(n_folds):
        train_end = fold_size * (fold + 2)
        val_start = train_end
        val_end = min(val_start + fold_size, n)

        if val_end <= val_start + 100:
            print(f"\n  Fold {fold + 1}: skipped (too few val samples)")
            continue

        X_train, y_train = X[:train_end], y[:train_end]
        X_val, y_val = X[val_start:val_end], y[val_start:val_end]

        print(f"\n  Fold {fold + 1}/{n_folds}: train[0:{train_end:,}] → val[{val_start:,}:{val_end:,}]")

        # Optuna search on a small held-out set from training data
        optuna_split = int(len(X_train) * 0.85)
        X_opt_train = X_train[:optuna_split]
        y_opt_train = y_train[:optuna_split]
        X_opt_val = X_train[optuna_split:]
        y_opt_val = y_train[optuna_split:]

        t0 = time.time()
        if model_type == "xgboost":
            best_params = optuna_xgboost(X_opt_train, y_opt_train, X_opt_val, y_opt_val, n_trials)
        else:
            best_params = optuna_lightgbm(X_opt_train, y_opt_train, X_opt_val, y_opt_val, n_trials)
        print(f"    Optuna: {n_trials} trials in {time.time() - t0:.1f}s")
        print(f"    Best params: {json.dumps({k: round(v, 4) if isinstance(v, float) else v for k, v in best_params.items()})}")

        # Train final model on full training data with best params
        if model_type == "xgboost":
            from xgboost import XGBClassifier
            model = XGBClassifier(
                **best_params,
                use_label_encoder=False,
                eval_metric="mlogloss",
                random_state=42,
                n_jobs=-1,
            )
        else:
            from lightgbm import LGBMClassifier
            model = LGBMClassifier(
                **best_params, random_state=42, n_jobs=-1, verbose=-1,
            )

        model.fit(X_train, y_train)

        # Predict on validation
        from sklearn.metrics import accuracy_score
        val_pred = model.predict(X_val)
        val_proba = model.predict_proba(X_val)
        val_conf = np.max(val_proba, axis=1)
        val_acc = accuracy_score(y_val, val_pred)
        print(f"    Val accuracy: {val_acc:.4f}")

        # Backtest on validation period
        val_closes = closes[val_start:val_end]
        val_highs = highs[val_start:val_end]
        val_lows = lows[val_start:val_end]
        bt = backtest_predictions(val_pred, val_conf, val_closes, val_highs, val_lows, params)

        fold_grade = grade_model(bt)
        print(f"    Backtest: {bt['n_trades']} trades | WR={bt['win_rate']:.2%} | PF={bt['profit_factor']:.2f} | Sharpe={bt['sharpe']:.2f} | Grade={fold_grade}")

        fold_result = {
            "fold": fold + 1,
            "train_size": train_end,
            "val_size": val_end - val_start,
            "val_accuracy": round(val_acc, 4),
            "best_params": best_params,
            "backtest": {k: v for k, v in bt.items() if k != "trades"},
            "grade": fold_grade,
        }
        all_fold_metrics.append(fold_result)

        # Keep best model
        grade_rank = {"A": 4, "B": 3, "C": 2, "D": 1}
        if grade_rank.get(fold_grade, 0) >= grade_rank.get(best_fold_grade, 0):
            best_fold_grade = fold_grade
            best_model = {
                "model": model,
                "params": best_params,
                "feature_names": feature_names,
                "fold": fold + 1,
                "grade": fold_grade,
                "metrics": bt,
            }

    # Aggregate walk-forward metrics
    if all_fold_metrics:
        avg_pf = np.mean([f["backtest"]["profit_factor"] for f in all_fold_metrics])
        avg_sharpe = np.mean([f["backtest"]["sharpe"] for f in all_fold_metrics])
        avg_wr = np.mean([f["backtest"]["win_rate"] for f in all_fold_metrics])
        total_trades = sum(f["backtest"]["n_trades"] for f in all_fold_metrics)

        aggregate = {
            "avg_profit_factor": round(avg_pf, 4),
            "avg_sharpe": round(avg_sharpe, 4),
            "avg_win_rate": round(avg_wr, 4),
            "total_trades": total_trades,
        }
        agg_grade = grade_model({
            "profit_factor": avg_pf,
            "sharpe": avg_sharpe,
            "win_rate": avg_wr,
        })
    else:
        aggregate = {}
        agg_grade = "D"

    print(f"\n  {'─'*50}")
    print(f"  AGGREGATE: PF={aggregate.get('avg_profit_factor', 0):.2f} | Sharpe={aggregate.get('avg_sharpe', 0):.2f} | WR={aggregate.get('avg_win_rate', 0):.2%} | Grade={agg_grade}")
    print(f"  Total trades across folds: {aggregate.get('total_trades', 0)}")

    return {
        "symbol": symbol,
        "model_type": model_type,
        "folds": all_fold_metrics,
        "aggregate": aggregate,
        "aggregate_grade": agg_grade,
        "best_model": best_model,
    }


# ── Save Model ────────────────────────────────────────

def save_best_model(result: dict, symbol: str, model_type: str) -> str | None:
    """Save the best model from walk-forward to disk."""
    import joblib

    best = result.get("best_model")
    if not best:
        print(f"  No model to save for {symbol} {model_type}")
        return None

    grade = result["aggregate_grade"]
    if grade == "D":
        print(f"  Grade D — not saving {symbol} {model_type}")
        return None

    prefix = f"scalping_{symbol}_M5"
    model_path = str(MODEL_DIR / f"{prefix}_{model_type}.joblib")

    joblib.dump({
        "model": best["model"],
        "feature_names": best["feature_names"],
        "symbol": symbol,
        "timeframe": "M5",
        "model_type": model_type,
        "grade": grade,
        "best_params": best["params"],
        "metrics": {k: v for k, v in best["metrics"].items() if k != "trades"},
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }, model_path)

    print(f"  Saved: {model_path} (Grade {grade})")
    return model_path


# ── Main Pipeline ─────────────────────────────────────

def run_pipeline(symbol: str, quick: bool = False):
    """Run full scalping pipeline for one symbol."""
    params = SYMBOL_PARAMS[symbol]
    trials = 10 if quick else OPTUNA_TRIALS

    print(f"\n{'#'*60}")
    print(f"  SCALPING PIPELINE: {symbol} M5")
    print(f"  Optuna trials: {trials} | WF folds: {N_WF_FOLDS}")
    print(f"{'#'*60}")

    # Load data
    print("\n  Loading M5 data...")
    m5_path = DATA_DIR / f"{symbol}_M5.csv"
    h1_path = DATA_DIR / f"{symbol}_H1.csv"

    if not m5_path.exists():
        print(f"  ERROR: {m5_path} not found")
        return None

    m5_data_full = load_csv(str(m5_path))
    h1_data_full = load_csv(str(h1_path)) if h1_path.exists() else None

    # Use last N M5 bars — 50K for quick (~10 months), 150K for full (~2.5 years)
    MAX_BARS = 50_000 if quick else 150_000
    m5_data = m5_data_full[-MAX_BARS:] if len(m5_data_full) > MAX_BARS else m5_data_full
    h1_data = h1_data_full[-(MAX_BARS // 12):] if h1_data_full and len(h1_data_full) > MAX_BARS // 12 else h1_data_full
    print(f"  M5: {len(m5_data):,} bars (of {len(m5_data_full):,}) | H1: {len(h1_data):,} bars" if h1_data else f"  M5: {len(m5_data):,} bars")

    # Compute features
    print("  Computing features...")
    t0 = time.time()
    feature_names, X = compute_all_features(m5_data, h1_data)
    print(f"  {len(feature_names)} features computed in {time.time() - t0:.1f}s")

    # Compute targets
    print("  Computing triple-barrier targets...")
    y_raw = compute_triple_barrier_targets(m5_data, params)

    # Clean
    X_clean, y_clean = clean_xy(X, y_raw)
    y_classes, label_map = map_targets_to_classes(y_clean)
    print(f"  Clean samples: {len(X_clean):,} | Label map: {label_map}")

    # Class distribution
    unique, counts = np.unique(y_classes, return_counts=True)
    for u, c in zip(unique, counts):
        print(f"    Class {u}: {c:,} ({c/len(y_classes):.1%})")

    # Extract price arrays for backtesting (aligned with clean data)
    closes_all = np.array([d["close"] for d in m5_data], dtype=np.float64)
    highs_all = np.array([d["high"] for d in m5_data], dtype=np.float64)
    lows_all = np.array([d["low"] for d in m5_data], dtype=np.float64)

    # We need to align closes/highs/lows with the cleaned X indices
    valid_mask = np.isfinite(y_raw)
    if X.ndim == 2:
        valid_mask &= np.all(np.isfinite(X), axis=1)
    closes_clean = closes_all[valid_mask]
    highs_clean = highs_all[valid_mask]
    lows_clean = lows_all[valid_mask]

    results = {}

    # Train XGBoost
    print("\n  ── XGBoost ──")
    xgb_result = walk_forward_train(
        X_clean, y_classes, feature_names,
        closes_clean, highs_clean, lows_clean,
        symbol, "xgboost", params,
        n_folds=N_WF_FOLDS, n_trials=trials,
    )
    xgb_path = save_best_model(xgb_result, symbol, "xgboost")
    results["xgboost"] = xgb_result

    # Train LightGBM
    print("\n  ── LightGBM ──")
    lgb_result = walk_forward_train(
        X_clean, y_classes, feature_names,
        closes_clean, highs_clean, lows_clean,
        symbol, "lightgbm", params,
        n_folds=N_WF_FOLDS, n_trials=trials,
    )
    lgb_path = save_best_model(lgb_result, symbol, "lightgbm")
    results["lightgbm"] = lgb_result

    # Summary
    print(f"\n  {'='*50}")
    print(f"  FINAL RESULTS: {symbol}")
    print(f"  {'='*50}")
    for mt, res in results.items():
        g = res["aggregate_grade"]
        agg = res["aggregate"]
        print(f"  {mt.upper():>10}: Grade {g} | PF={agg.get('avg_profit_factor', 0):.2f} | Sharpe={agg.get('avg_sharpe', 0):.2f} | WR={agg.get('avg_win_rate', 0):.2%} | Trades={agg.get('total_trades', 0)}")

    # Save results JSON
    results_path = RESULTS_DIR / f"scalping_{symbol}_results.json"
    serializable = {}
    for mt, res in results.items():
        serializable[mt] = {
            "aggregate": res["aggregate"],
            "aggregate_grade": res["aggregate_grade"],
            "folds": res["folds"],
        }
    with open(results_path, "w") as f:
        json.dump(serializable, f, indent=2, default=str)
    print(f"\n  Results saved: {results_path}")

    return results


# ── Entry Point ───────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Scalping ML Pipeline")
    parser.add_argument("--symbols", nargs="+", default=["XAUUSD", "US30"])
    parser.add_argument("--quick", action="store_true", help="Quick mode (10 Optuna trials)")
    args = parser.parse_args()

    all_results = {}
    for symbol in args.symbols:
        if symbol not in SYMBOL_PARAMS:
            print(f"  Unknown symbol: {symbol}, skipping")
            continue
        result = run_pipeline(symbol, quick=args.quick)
        if result:
            all_results[symbol] = result

    # Final summary
    print(f"\n\n{'#'*60}")
    print(f"  PIPELINE COMPLETE")
    print(f"{'#'*60}")
    for symbol, results in all_results.items():
        for mt, res in results.items():
            g = res["aggregate_grade"]
            print(f"  {symbol} {mt.upper():>10}: Grade {g}")

    # List deployable models
    deployable = []
    for symbol, results in all_results.items():
        for mt, res in results.items():
            if res["aggregate_grade"] in ("A", "B"):
                deployable.append(f"{symbol}_{mt}")
    if deployable:
        print(f"\n  Deployable models: {', '.join(deployable)}")
    else:
        print(f"\n  No deployable models (all Grade C/D)")


if __name__ == "__main__":
    main()
