"""
Expert Agent Training Pipeline — train multi-timeframe ensemble models.

Trains the full expert agent ML stack for XAUUSD, US30, and BTCUSD:

  1. Downloads M5 + H1 + H4 + D1 data from Databento
  2. Computes expert features (technical + market structure + session + MTF)
  3. Trains XGBoost ensemble member (direction classification)
  4. Trains LightGBM ensemble member (independent classifier)
  5. Trains LSTM forecaster (return distribution for SL/TP)
  6. Trains meta-labeler (trade/no-trade filter on ensemble output)
  7. Trains HMM regime detector
  8. Registers all models in DB as "expert_v1"

Usage:
    # Full training (downloads data + trains all)
    python scripts/train_expert_agent.py

    # Train specific symbols
    python scripts/train_expert_agent.py --symbols XAUUSD US30

    # Quick mode (fewer estimators, for testing)
    python scripts/train_expert_agent.py --quick

    # Skip download (use cached data)
    python scripts/train_expert_agent.py --skip-download
"""

import argparse
import csv
import json
import os
import sys
import time
import traceback
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Configuration ──────────────────────────────────────

DATA_DIR = Path(__file__).parent.parent / "data" / "databento"
MODEL_DIR = Path(__file__).parent.parent / "data" / "ml_models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# CME symbol → broker symbol mapping
CME_MAP = {
    "XAUUSD": "GC",
    "US30": "YM",
    "BTCUSD": "BTC",
}

BROKER_ALIAS = {
    "GC": "XAUUSD",
    "YM": "US30",
    "BTC": "BTCUSD",
}

# Symbol-specific trading parameters
SYMBOL_PARAMS = {
    "XAUUSD": {
        "commission": 0.0003,
        "spread": 0.30,
        "atr_sl_mult": 1.5,
        "atr_tp_mult": 2.5,
        "max_holding_bars": 12,     # 1 hour on M5
        "swing_lookback": 5,
    },
    "US30": {
        "commission": 0.0001,
        "spread": 1.0,
        "atr_sl_mult": 1.5,
        "atr_tp_mult": 2.0,
        "max_holding_bars": 12,
        "swing_lookback": 5,
    },
    "BTCUSD": {
        "commission": 0.0005,
        "spread": 5.0,
        "atr_sl_mult": 2.0,
        "atr_tp_mult": 3.0,
        "max_holding_bars": 24,     # 2 hours on M5 (crypto more patient)
        "swing_lookback": 7,
    },
}


def load_csv(path: str) -> list[dict]:
    """Load OHLCV data from CSV with datetime parsing."""
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
                dt_val = row.get("datetime") or row.get("Datetime") or row.get("date") or row.get("Date")
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


_DB_TABLES_ENSURED = False


def register_model_in_db(
    name: str,
    model_type: str,
    symbol: str,
    timeframe: str,
    level: int,
    model_path: str,
    train_metrics: dict,
    val_metrics: dict,
    features_config: dict,
    hyperparams: dict,
):
    """Register a trained model in the database."""
    global _DB_TABLES_ENSURED
    from app.core.database import SessionLocal, engine, Base
    from app.models.ml import MLModel

    if not _DB_TABLES_ENSURED:
        import importlib, pkgutil, app.models as _models_pkg
        for _, mod_name, _ in pkgutil.iter_modules(_models_pkg.__path__):
            importlib.import_module(f"app.models.{mod_name}")
        Base.metadata.create_all(bind=engine)
        _DB_TABLES_ENSURED = True

    db = SessionLocal()
    try:
        model = MLModel(
            name=name,
            level=level,
            model_type=model_type,
            symbol=symbol,
            timeframe=timeframe,
            features_config=features_config,
            hyperparams=hyperparams,
            train_metrics=train_metrics,
            val_metrics=val_metrics,
            status="ready",
            model_path=model_path,
            trained_at=datetime.now(timezone.utc),
        )
        db.add(model)
        db.commit()
        db.refresh(model)
        print(f"    Registered in DB: model_id={model.id}")
        return model.id
    except Exception as e:
        print(f"    WARNING: DB registration failed: {e}")
        db.rollback()
        return None
    finally:
        db.close()


# ── Expert Feature Computation ─────────────────────────

def compute_expert_feature_matrix(
    m5_data: list[dict],
    h1_data: list[dict] | None,
    h4_data: list[dict] | None,
    d1_data: list[dict] | None,
) -> tuple[list[str], np.ndarray]:
    """Compute the full expert feature set."""
    from app.services.ml.features_mtf import compute_expert_features
    return compute_expert_features(m5_data, h1_data, h4_data, d1_data)


def compute_targets(
    m5_data: list[dict],
    params: dict,
) -> tuple[str, np.ndarray]:
    """Compute triple barrier targets for M5 data."""
    from app.services.ml.features import compute_targets as _compute_targets

    closes = [d["close"] for d in m5_data]
    highs = [d["high"] for d in m5_data]
    lows = [d["low"] for d in m5_data]

    target_config = {
        "type": "triple_barrier",
        "horizon": params.get("max_holding_bars", 12),
        "sl_atr_mult": params.get("atr_sl_mult", 1.5),
        "tp_atr_mult": params.get("atr_tp_mult", 2.5),
        "max_holding_bars": params.get("max_holding_bars", 12),
    }

    name, values = _compute_targets(closes, target_config, highs, lows)
    return name, np.array(values, dtype=np.float64)


# ── Training Functions ──────────────────────────────────

def train_expert_tree(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    symbol: str,
    model_type: str = "xgboost",
    quick: bool = False,
) -> dict | None:
    """Train XGBoost or LightGBM on expert features."""
    import joblib

    # Clean NaN rows
    valid = np.isfinite(y)
    if X.ndim == 2:
        valid &= np.all(np.isfinite(X), axis=1)
    X_clean = X[valid]
    y_clean = y[valid]

    # Map triple-barrier targets to integer classes: 0.0→0 (SL), 0.5→1 (neutral), 1.0→2 (TP)
    unique_vals = np.unique(y_clean)
    if not np.array_equal(unique_vals.astype(int), unique_vals):
        label_map = {v: i for i, v in enumerate(sorted(unique_vals))}
        y_clean = np.array([label_map[v] for v in y_clean], dtype=np.int64)
        print(f"    Mapped targets: {label_map}")

    if len(X_clean) < 500:
        print(f"    SKIP: Only {len(X_clean)} valid samples, need 500")
        return None

    # Walk-forward split: 80% train, 20% validation
    split = int(len(X_clean) * 0.8)
    X_train, X_val = X_clean[:split], X_clean[split:]
    y_train, y_val = y_clean[:split], y_clean[split:]

    print(f"    Train: {len(X_train):,} samples, Val: {len(X_val):,} samples")
    print(f"    Features: {len(feature_names)}")

    if model_type == "xgboost":
        try:
            from xgboost import XGBClassifier
        except ImportError:
            print("    ERROR: xgboost not installed")
            return None

        model = XGBClassifier(
            n_estimators=100 if quick else 300,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.7,
            min_child_weight=5,
            reg_alpha=0.1,
            reg_lambda=1.0,
            use_label_encoder=False,
            eval_metric="logloss",
            random_state=42,
            n_jobs=-1,
        )
    else:  # lightgbm
        try:
            from lightgbm import LGBMClassifier
        except ImportError:
            print("    ERROR: lightgbm not installed")
            return None

        model = LGBMClassifier(
            n_estimators=100 if quick else 300,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.7,
            min_child_samples=20,
            reg_alpha=0.1,
            reg_lambda=1.0,
            num_leaves=31,
            random_state=42,
            n_jobs=-1,
            verbose=-1,
        )

    print(f"    Training {model_type}...")
    model.fit(X_train, y_train)

    # Evaluate
    from sklearn.metrics import accuracy_score, classification_report

    train_pred = model.predict(X_train)
    val_pred = model.predict(X_val)
    train_acc = accuracy_score(y_train, train_pred)
    val_acc = accuracy_score(y_val, val_pred)

    print(f"    Train accuracy: {train_acc:.4f}")
    print(f"    Val accuracy:   {val_acc:.4f}")

    # Feature importance
    importances = model.feature_importances_
    top_features = sorted(
        zip(feature_names, importances),
        key=lambda x: x[1],
        reverse=True,
    )[:15]
    print(f"    Top features:")
    for fname, imp in top_features:
        print(f"      {fname}: {imp:.4f}")

    # Save model
    prefix = f"expert_{symbol}_M5"
    model_path = str(MODEL_DIR / f"{prefix}_{model_type}.joblib")
    joblib.dump({
        "model": model,
        "feature_names": feature_names,
        "symbol": symbol,
        "timeframe": "M5",
        "model_type": model_type,
        "train_accuracy": train_acc,
        "val_accuracy": val_acc,
    }, model_path)
    print(f"    Saved: {model_path}")

    train_metrics = {"accuracy": train_acc}
    val_metrics = {"accuracy": val_acc}

    return {
        "model_path": model_path,
        "train_metrics": train_metrics,
        "val_metrics": val_metrics,
        "feature_importance": dict(top_features),
    }


def train_expert_lstm(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    symbol: str,
    quick: bool = False,
) -> dict | None:
    """Train LSTM for direction prediction on expert features."""
    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError:
        print("    ERROR: PyTorch not installed, skipping LSTM")
        return None

    # Clean NaN rows
    valid = np.isfinite(y)
    if X.ndim == 2:
        valid &= np.all(np.isfinite(X), axis=1)

    X_clean = X[valid]
    y_clean = y[valid]

    # Convert to binary for BCE: TP (1.0) → 1, everything else → 0
    y_clean = (y_clean == 1.0).astype(np.float32)
    print(f"    Binary target: {y_clean.mean():.3f} positive rate")

    if len(X_clean) < 500:
        print(f"    SKIP: Only {len(X_clean)} valid samples")
        return None

    seq_len = 60
    n_features = X_clean.shape[1]

    # Build sequences
    sequences = []
    targets = []
    for i in range(seq_len, len(X_clean)):
        sequences.append(X_clean[i - seq_len:i])
        targets.append(y_clean[i])

    if len(sequences) < 200:
        print(f"    SKIP: Only {len(sequences)} sequences")
        return None

    X_seq = np.array(sequences, dtype=np.float32)
    y_seq = np.array(targets, dtype=np.float32)

    # Normalize
    mean = X_seq.reshape(-1, n_features).mean(axis=0)
    std = X_seq.reshape(-1, n_features).std(axis=0) + 1e-8
    X_seq = (X_seq - mean) / std

    # Split
    split = int(len(X_seq) * 0.8)
    X_train, X_val = X_seq[:split], X_seq[split:]
    y_train, y_val = y_seq[:split], y_seq[split:]

    print(f"    LSTM sequences — Train: {len(X_train):,}, Val: {len(X_val):,}")
    print(f"    Seq length: {seq_len}, Features: {n_features}")

    # Model
    class LSTMClassifier(nn.Module):
        def __init__(self, input_dim, hidden_dim=128, num_layers=2, dropout=0.2):
            super().__init__()
            self.lstm = nn.LSTM(input_dim, hidden_dim, num_layers,
                                batch_first=True, dropout=dropout)
            self.fc = nn.Sequential(
                nn.Linear(hidden_dim, 64),
                nn.ReLU(),
                nn.Dropout(dropout),
                nn.Linear(64, 1),
                nn.Sigmoid(),
            )

        def forward(self, x):
            lstm_out, _ = self.lstm(x)
            return self.fc(lstm_out[:, -1, :]).squeeze(-1)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = LSTMClassifier(n_features).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    criterion = nn.BCELoss()

    train_ds = TensorDataset(torch.tensor(X_train), torch.tensor(y_train))
    val_ds = TensorDataset(torch.tensor(X_val), torch.tensor(y_val))
    train_dl = DataLoader(train_ds, batch_size=256, shuffle=True)
    val_dl = DataLoader(val_ds, batch_size=512)

    epochs = 5 if quick else 15
    best_val_acc = 0.0
    best_state = None

    print(f"    Training LSTM ({epochs} epochs)...")
    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        for xb, yb in train_dl:
            xb, yb = xb.to(device), yb.to(device)
            pred = model(xb)
            loss = criterion(pred, yb)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            train_loss += loss.item()

        # Validate
        model.eval()
        correct = 0
        total = 0
        with torch.no_grad():
            for xb, yb in val_dl:
                xb, yb = xb.to(device), yb.to(device)
                pred = model(xb)
                predicted = (pred > 0.5).float()
                correct += (predicted == yb).sum().item()
                total += len(yb)

        val_acc = correct / max(total, 1)
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

        if (epoch + 1) % 5 == 0 or epoch == 0:
            print(f"      Epoch {epoch + 1}/{epochs}: loss={train_loss / len(train_dl):.4f}, val_acc={val_acc:.4f}")

    print(f"    Best val accuracy: {best_val_acc:.4f}")

    # Export to ONNX
    if best_state:
        model.load_state_dict(best_state)
    model.eval()

    prefix = f"expert_{symbol}_M5"
    onnx_path = str(MODEL_DIR / f"{prefix}_lstm.onnx")

    try:
        dummy = torch.randn(1, seq_len, n_features).to(device)
        torch.onnx.export(
            model, dummy, onnx_path,
            input_names=["features"],
            output_names=["prediction"],
            dynamic_axes={"features": {0: "batch"}, "prediction": {0: "batch"}},
            opset_version=14,
        )
        print(f"    Exported ONNX: {onnx_path}")
    except Exception as e:
        print(f"    ONNX export failed: {e}")
        return None

    # Save scaler
    scaler_path = str(MODEL_DIR / f"{prefix}_lstm_scaler.npz")
    np.savez(scaler_path, mean=mean, std=std)

    # Save metadata
    meta_path = str(MODEL_DIR / f"{prefix}_lstm_meta.json")
    with open(meta_path, "w") as f:
        json.dump({
            "feature_names": feature_names,
            "seq_len": seq_len,
            "n_features": n_features,
            "symbol": symbol,
            "timeframe": "M5",
        }, f)

    return {
        "model_path": onnx_path,
        "train_metrics": {"best_val_accuracy": best_val_acc},
        "val_metrics": {"accuracy": best_val_acc},
    }


def train_expert_meta_labeler(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    xgb_path: str,
    lgb_path: str,
    symbol: str,
    quick: bool = False,
) -> dict | None:
    """
    Train a meta-labeler on ensemble predictions.

    The meta-labeler learns WHEN to trade (not which direction).
    Input: features + ensemble vote direction + ensemble confidence.
    Output: probability that the ensemble signal is profitable.
    """
    import joblib

    # Clean NaN
    valid = np.isfinite(y)
    if X.ndim == 2:
        valid &= np.all(np.isfinite(X), axis=1)
    X_clean = X[valid]
    y_clean = y[valid]

    if len(X_clean) < 500:
        print(f"    SKIP: Only {len(X_clean)} valid samples")
        return None

    # Load primary models
    try:
        xgb_saved = joblib.load(xgb_path)
        lgb_saved = joblib.load(lgb_path)
        xgb_model = xgb_saved["model"]
        lgb_model = lgb_saved["model"]
    except Exception as e:
        print(f"    ERROR loading primary models: {e}")
        return None

    # Generate primary predictions for all samples
    xgb_pred = xgb_model.predict(X_clean).astype(float)
    lgb_pred = lgb_model.predict(X_clean).astype(float)

    xgb_conf = np.max(xgb_model.predict_proba(X_clean), axis=1) if hasattr(xgb_model, "predict_proba") else np.full(len(X_clean), 0.5)
    lgb_conf = np.max(lgb_model.predict_proba(X_clean), axis=1) if hasattr(lgb_model, "predict_proba") else np.full(len(X_clean), 0.5)

    # Ensemble direction: majority vote
    # Classes: 0=SL(bearish), 1=neutral, 2=TP(bullish)
    ensemble_dir = np.where(xgb_pred + lgb_pred >= 3.0, 1.0, -1.0)  # both predict TP → bullish
    ensemble_conf = (xgb_conf * 0.5 + lgb_conf * 0.5)
    agreement = np.where(xgb_pred == lgb_pred, 1.0, 0.5)

    # Meta-labeler features: original features + ensemble info
    meta_features = np.column_stack([X_clean, ensemble_dir, ensemble_conf, agreement])

    # Meta-labeler target: was the ensemble direction correct?
    # y_clean is triple barrier: 1.0 = TP, 0.0 = SL, 0.5 = neutral
    # "Correct" means: ensemble predicted direction matches actual outcome
    meta_target = np.where(
        (ensemble_dir == 1) & (y_clean == 1.0), 1.0,  # predicted bull, was TP → correct
        np.where(
            (ensemble_dir == -1) & (y_clean == 0.0), 1.0,  # predicted bear, was SL → correct
            0.0,  # everything else → wrong
        ),
    )

    # Ensure integer labels for XGBClassifier
    meta_target = meta_target.astype(np.int64)

    # Split
    split = int(len(meta_features) * 0.8)
    Xm_train = meta_features[:split]
    Xm_val = meta_features[split:]
    ym_train = meta_target[:split]
    ym_val = meta_target[split:]

    print(f"    Meta-labeler: Train {len(Xm_train):,}, Val {len(Xm_val):,}")
    print(f"    Positive class rate: {meta_target.mean():.3f}")

    try:
        from xgboost import XGBClassifier
    except ImportError:
        print("    ERROR: xgboost not installed")
        return None

    meta_model = XGBClassifier(
        n_estimators=50 if quick else 150,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        min_child_weight=10,
        use_label_encoder=False,
        eval_metric="logloss",
        random_state=42,
        n_jobs=-1,
    )

    print(f"    Training meta-labeler...")
    meta_model.fit(Xm_train, ym_train)

    from sklearn.metrics import accuracy_score
    train_acc = accuracy_score(ym_train, meta_model.predict(Xm_train))
    val_acc = accuracy_score(ym_val, meta_model.predict(Xm_val))
    print(f"    Meta train acc: {train_acc:.4f}, val acc: {val_acc:.4f}")

    # Save
    prefix = f"expert_{symbol}_M5"
    model_path = str(MODEL_DIR / f"{prefix}_meta.joblib")
    joblib.dump({
        "model": meta_model,
        "feature_names": feature_names + ["ensemble_dir", "ensemble_conf", "agreement"],
        "symbol": symbol,
        "is_meta_model": True,
    }, model_path)
    print(f"    Saved: {model_path}")

    return {
        "model_path": model_path,
        "train_metrics": {"accuracy": train_acc},
        "val_metrics": {"accuracy": val_acc},
    }


def train_expert_regime(
    m5_data: list[dict],
    symbol: str,
) -> dict | None:
    """Train HMM regime detector."""
    from app.services.ml.regime_detector import RegimeDetector

    if len(m5_data) < 500:
        print(f"    SKIP: Only {len(m5_data)} bars")
        return None

    model_id = int(time.time()) % 100000
    detector = RegimeDetector(model_id=model_id)

    print(f"    Training HMM Regime Detector...")
    try:
        result = detector.train(ohlcv_data=m5_data, n_states=4)
        return result
    except Exception as e:
        print(f"    ERROR: {e}")
        traceback.print_exc()
        return None


# ── Main Pipeline ──────────────────────────────────────

def train_symbol(symbol: str, quick: bool = False, skip_download: bool = False):
    """Train the full expert model stack for one symbol."""
    print(f"\n{'=' * 70}")
    print(f"  EXPERT AGENT — {symbol}")
    print(f"{'=' * 70}")

    cme_sym = CME_MAP.get(symbol, symbol)
    params = SYMBOL_PARAMS.get(symbol, SYMBOL_PARAMS["XAUUSD"])

    # ── Load data ──
    timeframes = {"M5": None, "H1": None, "H4": None, "D1": None}

    for tf in timeframes:
        csv_path = DATA_DIR / f"{symbol}_{tf}.csv"
        if not csv_path.exists():
            # Try CME alias
            csv_path = DATA_DIR / f"{BROKER_ALIAS.get(cme_sym, symbol)}_{tf}.csv"
        if csv_path.exists():
            data = load_csv(str(csv_path))
            # Cap data size — 100K M5 bars ≈ 347 trading days, enough for training
            # while keeping O(n²) feature loops tractable
            if len(data) > 100_000:
                data = data[-100_000:]
            timeframes[tf] = data
            print(f"  {tf}: {len(data):,} bars loaded")
        else:
            print(f"  {tf}: NOT FOUND ({csv_path})")

    m5_data = timeframes["M5"]
    if not m5_data or len(m5_data) < 1000:
        print(f"  FATAL: Insufficient M5 data for {symbol}")
        return {}

    h1_data = timeframes["H1"]
    h4_data = timeframes["H4"]
    d1_data = timeframes["D1"]

    # ── Compute features ──
    print(f"\n  Computing expert features...")
    t0 = time.time()
    feature_names, X = compute_expert_feature_matrix(m5_data, h1_data, h4_data, d1_data)
    print(f"  Features computed: {len(feature_names)} features x {X.shape[0]:,} bars ({time.time() - t0:.1f}s)")

    if X.shape[0] == 0:
        print(f"  FATAL: No features computed")
        return {}

    # ── Compute targets ──
    print(f"  Computing triple barrier targets...")
    target_name, y = compute_targets(m5_data, params)
    print(f"  Target: {target_name}, classes: {np.unique(y[np.isfinite(y)])}")

    # Align lengths
    min_len = min(len(X), len(y))
    X = X[:min_len]
    y = y[:min_len]

    results = {}

    # ── Train XGBoost ──
    print(f"\n  [1/5] XGBoost")
    print(f"  {'─' * 50}")
    t0 = time.time()
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
        print(f"  XGBoost done in {time.time() - t0:.1f}s")

    # ── Train LightGBM ──
    print(f"\n  [2/5] LightGBM")
    print(f"  {'─' * 50}")
    t0 = time.time()
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
        print(f"  LightGBM done in {time.time() - t0:.1f}s")

    # ── Train LSTM ──
    print(f"\n  [3/5] LSTM")
    print(f"  {'─' * 50}")
    t0 = time.time()
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
        print(f"  LSTM done in {time.time() - t0:.1f}s")

    # ── Train Meta-labeler ──
    if xgb_result and lgb_result:
        print(f"\n  [4/5] Meta-Labeler")
        print(f"  {'─' * 50}")
        t0 = time.time()
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
            print(f"  Meta-labeler done in {time.time() - t0:.1f}s")
    else:
        print(f"\n  [4/5] SKIPPING Meta-Labeler (need both XGBoost + LightGBM)")

    # ── Train Regime Detector ──
    print(f"\n  [5/5] Regime Detector")
    print(f"  {'─' * 50}")
    t0 = time.time()
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
        print(f"  Regime done in {time.time() - t0:.1f}s")

    return results


def main():
    parser = argparse.ArgumentParser(description="Expert Agent Training Pipeline")
    parser.add_argument(
        "--symbols", nargs="+", default=["XAUUSD", "US30", "BTCUSD"],
        help="Symbols to train (broker names)",
    )
    parser.add_argument("--skip-download", action="store_true", help="Skip data download")
    parser.add_argument("--quick", action="store_true", help="Quick mode (fewer epochs)")
    parser.add_argument("--start", default="2020-01-01", help="Data start date")
    args = parser.parse_args()

    print("=" * 70)
    print("  TRADEFORGE — Expert Agent Training Pipeline")
    print("=" * 70)
    print(f"  Symbols:    {args.symbols}")
    print(f"  Quick mode: {args.quick}")
    print(f"  Data dir:   {DATA_DIR}")
    print(f"  Model dir:  {MODEL_DIR}")
    print()

    # ── Step 1: Download data ──
    if not args.skip_download:
        print("STEP 1: Downloading data from Databento...")
        print("-" * 50)
        try:
            from scripts.download_databento import main as download_main
            cme_symbols = []
            for sym in args.symbols:
                cme = CME_MAP.get(sym, sym)
                if cme not in cme_symbols:
                    cme_symbols.append(cme)

            sys.argv = [
                "download_databento.py",
                "--symbols", *cme_symbols,
                "--timeframes", "M5", "H1", "H4", "D1",
                "--start", args.start,
            ]
            download_main()
        except Exception as e:
            print(f"  Download error: {e}")
            print("  Continuing with cached data...")
        print()
    else:
        print("STEP 1: Skipping download (--skip-download)")
        print()

    # ── Step 2: Train expert models ──
    print("STEP 2: Training Expert Agent Models")
    print("=" * 70)

    all_results = {}
    for symbol in args.symbols:
        try:
            results = train_symbol(symbol, args.quick, args.skip_download)
            all_results[symbol] = results
        except Exception as e:
            print(f"\n  FATAL ERROR for {symbol}: {e}")
            traceback.print_exc()
            all_results[symbol] = {"error": str(e)}

    # ── Summary ──
    print(f"\n\n{'=' * 70}")
    print(f"  EXPERT AGENT TRAINING COMPLETE")
    print(f"{'=' * 70}")

    for symbol, results in all_results.items():
        print(f"\n  {symbol}:")
        if "error" in results:
            print(f"    ERROR: {results['error']}")
            continue
        for model_name, result in results.items():
            if isinstance(result, dict):
                val = result.get("val_metrics", {})
                acc = val.get("accuracy", "N/A")
                print(f"    {model_name:<15} val_acc={acc}")

    print(f"\n  Models saved to: {MODEL_DIR}")
    print(f"  Models registered in DB and ready for ExpertAgent")
    print()


if __name__ == "__main__":
    main()
