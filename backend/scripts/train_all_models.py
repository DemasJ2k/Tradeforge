"""
Master ML Training Pipeline — train all model types across symbols & timeframes.

Downloads data from Databento (if not cached), then trains:
  1. Tree models (XGBoost, LightGBM) — signal prediction
  2. LSTM/GRU — price range forecasting for dynamic SL/TP
  3. PPO (RL) — autonomous trading agent
  4. HMM — market regime detection

All trained models are registered in the DB and ready for:
  - Backtest via ML Filter Strategy
  - Live agent signal filtering
  - Standalone autonomous trading (RL)

Usage:
    # Download data + train everything
    python scripts/train_all_models.py

    # Train specific symbols/timeframes
    python scripts/train_all_models.py --symbols GC ES --timeframes M15 H1

    # Train only specific model types
    python scripts/train_all_models.py --models xgboost lstm

    # Skip download (use cached data)
    python scripts/train_all_models.py --skip-download

    # Quick test run with fewer timesteps
    python scripts/train_all_models.py --quick
"""

import argparse
import csv
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Configuration ──────────────────────────────────────

DATA_DIR = Path(__file__).parent.parent / "data" / "databento"

# Symbol → broker name mapping (for DB registration)
BROKER_ALIAS = {
    "GC": "XAUUSD",
    "ES": "ES",
    "NQ": "NAS100",
    "YM": "US30",
    "BTC": "BTCUSD",
    "SI": "XAGUSD",
}

# Model-specific hyperparameters per symbol class
SYMBOL_PARAMS = {
    # Precious metals (GC, SI) — moderate volatility, trend-following
    "XAUUSD": {"commission": 0.0003, "spread": 0.30, "atr_mult": 1.5},
    "XAGUSD": {"commission": 0.0003, "spread": 0.015, "atr_mult": 1.5},
    # Index futures — low commission, tight spread
    "ES":     {"commission": 0.0001, "spread": 0.25, "atr_mult": 1.2},
    "NAS100": {"commission": 0.0001, "spread": 1.0,  "atr_mult": 1.2},
    "US30":   {"commission": 0.0001, "spread": 1.0,  "atr_mult": 1.2},
    # Crypto — higher vol, wider spread
    "BTCUSD": {"commission": 0.0005, "spread": 5.0,  "atr_mult": 2.0},
}

# Features used for each model type
FEATURES_CONFIG = {
    "tree": {
        "groups": [
            "returns", "returns_multi", "volatility", "candle_patterns",
            "sma", "ema", "rsi", "atr", "macd", "bollinger",
            "adx", "stochastic", "volume",
        ],
    },
    "lstm": {
        "groups": [
            "returns", "volatility", "candle_patterns",
            "rsi", "atr", "macd", "bollinger", "adx",
        ],
    },
    "rl": {
        "groups": [
            "returns", "returns_multi", "volatility", "candle_patterns",
            "sma", "ema", "rsi", "atr", "macd", "bollinger",
            "adx", "stochastic", "volume",
        ],
    },
}


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
                # Include datetime if available (for time features)
                dt_val = row.get("datetime") or row.get("Datetime") or row.get("date") or row.get("Date")
                if dt_val:
                    rec["datetime"] = dt_val

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

    # Ensure all referenced tables exist (one-time)
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
        model_id = model.id
        print(f"    Registered in DB: model_id={model_id}")
        return model_id
    except Exception as e:
        print(f"    WARNING: DB registration failed: {e}")
        db.rollback()
        return None
    finally:
        db.close()


# ── Training Functions ──────────────────────────────────


def train_tree_model(
    data: list[dict],
    symbol: str,
    timeframe: str,
    model_type: str = "xgboost",
    quick: bool = False,
) -> dict | None:
    """Train a tree-based model (XGBoost/LightGBM) for signal prediction."""
    from app.services.ml.trainer import MLTrainer

    min_bars = 500
    if len(data) < min_bars:
        print(f"    SKIP: Only {len(data)} bars, need {min_bars}")
        return None

    # Target config: predict next-bar direction using triple barrier
    target_cfg = {
        "type": "triple_barrier",
        "horizon": 10,
        "sl_mult": 1.5,
        "tp_mult": 2.0,
    }

    hyperparams = {}
    if model_type == "xgboost":
        hyperparams = {
            "n_estimators": 50 if quick else 200,
            "max_depth": 5,
            "learning_rate": 0.08,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_weight": 5,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
        }
    elif model_type == "lightgbm":
        hyperparams = {
            "n_estimators": 50 if quick else 200,
            "max_depth": 5,
            "learning_rate": 0.08,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_samples": 20,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "num_leaves": 31,
        }

    model_id_counter = int(time.time()) % 100000

    print(f"    Training {model_type} for {symbol} {timeframe}...")
    try:
        result = MLTrainer.train_model(
            ohlcv_data=data,
            model_type=model_type,
            features_config=FEATURES_CONFIG["tree"],
            target_config=target_cfg,
            hyperparams=hyperparams,
            model_id=model_id_counter,
        )

        if result and result.get("model_path"):
            name = f"{model_type}_{symbol}_{timeframe}"
            train_m = result.get("train_metrics", {})
            val_m = result.get("val_metrics", {})
            print(f"    Train acc: {train_m.get('accuracy', 'N/A')}, Val acc: {val_m.get('accuracy', 'N/A')}")
            db_id = register_model_in_db(
                name=name,
                model_type=model_type,
                symbol=symbol,
                timeframe=timeframe,
                level=2,
                model_path=result.get("model_path", ""),
                train_metrics=train_m,
                val_metrics=val_m,
                features_config=FEATURES_CONFIG["tree"],
                hyperparams=hyperparams,
            )
            return {"name": name, "model_id": db_id, **result}
        else:
            print(f"    FAILED: {result.get('error', 'No model produced')}")
            return None
    except Exception as e:
        print(f"    ERROR: {e}")
        traceback.print_exc()
        return None


def train_lstm_model(
    data: list[dict],
    symbol: str,
    timeframe: str,
    quick: bool = False,
) -> dict | None:
    """Train LSTM price range forecaster."""
    from app.services.ml.lstm_forecaster import LSTMForecaster

    seq_len = 60
    horizon = 10
    min_bars = seq_len + horizon + 200

    if len(data) < min_bars:
        print(f"    SKIP: Only {len(data)} bars, need {min_bars}")
        return None

    model_id_counter = int(time.time()) % 100000
    forecaster = LSTMForecaster(model_id=model_id_counter)

    print(f"    Training LSTM for {symbol} {timeframe}...")
    try:
        result = forecaster.train(
            ohlcv_data=data,
            seq_len=seq_len,
            horizon=horizon,
            hidden_size=128,
            num_layers=2,
            dropout=0.2,
            cell_type="lstm",
            epochs=10 if quick else 50,
            batch_size=64,
            learning_rate=1e-3,
        )

        name = f"lstm_{symbol}_{timeframe}"
        db_id = register_model_in_db(
            name=name,
            model_type="lstm",
            symbol=symbol,
            timeframe=timeframe,
            level=2,
            model_path=result.get("model_path", ""),
            train_metrics=result.get("train_metrics", {}),
            val_metrics=result.get("val_metrics", {}),
            features_config=FEATURES_CONFIG["lstm"],
            hyperparams={
                "seq_len": seq_len, "horizon": horizon,
                "hidden_size": 128, "num_layers": 2,
                "cell_type": "lstm",
            },
        )
        return {"name": name, "model_id": db_id, **result}
    except Exception as e:
        print(f"    ERROR: {e}")
        traceback.print_exc()
        return None


def train_rl_model(
    data: list[dict],
    symbol: str,
    timeframe: str,
    quick: bool = False,
) -> dict | None:
    """Train PPO reinforcement learning agent."""
    from app.services.ml.rl_trainer import RLTrainer

    min_bars = 1000
    if len(data) < min_bars:
        print(f"    SKIP: Only {len(data)} bars, need {min_bars}")
        return None

    params = SYMBOL_PARAMS.get(symbol, {"commission": 0.0002, "spread": 0.0001})

    model_id_counter = int(time.time()) % 100000
    trainer = RLTrainer(model_id=model_id_counter)

    timesteps = 50_000 if quick else 500_000

    print(f"    Training PPO RL for {symbol} {timeframe} ({timesteps:,} timesteps)...")
    try:
        result = trainer.train(
            ohlcv_data=data,
            total_timesteps=timesteps,
            hidden_sizes=(256, 256),
            learning_rate=3e-4,
            batch_size=64,
            commission=params.get("commission", 0.0002),
            spread=params.get("spread", 0.0001),
            features_config=FEATURES_CONFIG["rl"],
        )

        name = f"rl_ppo_{symbol}_{timeframe}"
        db_id = register_model_in_db(
            name=name,
            model_type="rl_ppo",
            symbol=symbol,
            timeframe=timeframe,
            level=3,
            model_path=result.get("onnx_path", result.get("model_path", "")),
            train_metrics=result.get("train_metrics", {}),
            val_metrics=result.get("eval_metrics", {}),
            features_config=FEATURES_CONFIG["rl"],
            hyperparams={
                "timesteps": timesteps,
                "hidden_sizes": [256, 256],
                "commission": params.get("commission"),
                "spread": params.get("spread"),
            },
        )
        return {"name": name, "model_id": db_id, **result}
    except Exception as e:
        print(f"    ERROR: {e}")
        traceback.print_exc()
        return None


def train_regime_model(
    data: list[dict],
    symbol: str,
    timeframe: str,
) -> dict | None:
    """Train HMM regime detector."""
    from app.services.ml.regime_detector import RegimeDetector

    min_bars = 500
    if len(data) < min_bars:
        print(f"    SKIP: Only {len(data)} bars, need {min_bars}")
        return None

    model_id_counter = int(time.time()) % 100000
    detector = RegimeDetector(model_id=model_id_counter)

    print(f"    Training HMM Regime Detector for {symbol} {timeframe}...")
    try:
        result = detector.train(ohlcv_data=data, n_states=4)

        name = f"regime_{symbol}_{timeframe}"
        db_id = register_model_in_db(
            name=name,
            model_type="hmm_regime",
            symbol=symbol,
            timeframe=timeframe,
            level=1,
            model_path=result.get("model_path", ""),
            train_metrics=result.get("stats", {}),
            val_metrics={},
            features_config={"type": "hmm_regime", "n_states": 4},
            hyperparams={"n_states": 4},
        )
        return {"name": name, "model_id": db_id, **result}
    except Exception as e:
        print(f"    ERROR: {e}")
        traceback.print_exc()
        return None


# ── Main Pipeline ──────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Master ML Training Pipeline")
    parser.add_argument(
        "--symbols", nargs="+", default=["GC", "ES", "NQ", "YM", "BTC"],
        help="Symbols to train (CME names)",
    )
    parser.add_argument(
        "--timeframes", nargs="+", default=["M1", "M5", "M15", "H1", "H4"],
        help="Timeframes to train",
    )
    parser.add_argument(
        "--models", nargs="+", default=["xgboost", "lightgbm", "lstm", "rl", "regime"],
        help="Model types to train",
    )
    parser.add_argument("--skip-download", action="store_true", help="Skip Databento download")
    parser.add_argument("--quick", action="store_true", help="Quick mode (fewer epochs/timesteps)")
    parser.add_argument("--start", default="2015-01-01", help="Data start date")
    parser.add_argument("--api-key", default=None, help="Databento API key")
    args = parser.parse_args()

    print("=" * 70)
    print("  TRADEFORGE — Master ML Training Pipeline")
    print("=" * 70)
    print(f"  Symbols:    {args.symbols}")
    print(f"  Timeframes: {args.timeframes}")
    print(f"  Models:     {args.models}")
    print(f"  Quick mode: {args.quick}")
    print(f"  Data dir:   {DATA_DIR}")
    print()

    # ── Step 1: Download data from Databento ──
    if not args.skip_download:
        print("STEP 1: Downloading data from Databento...")
        print("-" * 50)
        from scripts.download_databento import main as download_main
        sys.argv = [
            "download_databento.py",
            "--symbols", *args.symbols,
            "--timeframes", *args.timeframes,
            "--start", args.start,
        ]
        if args.api_key:
            sys.argv.extend(["--api-key", args.api_key])
        download_main()
        print()
    else:
        print("STEP 1: Skipping download (--skip-download)")
        print()

    # ── Step 2: Train models ──
    print("STEP 2: Training ML models")
    print("=" * 70)

    results_summary = []
    total_trained = 0
    total_failed = 0

    for symbol_key in args.symbols:
        broker_sym = BROKER_ALIAS.get(symbol_key, symbol_key)

        for tf in args.timeframes:
            csv_path = DATA_DIR / f"{broker_sym}_{tf}.csv"

            if not csv_path.exists():
                print(f"\n  [{broker_sym} {tf}] CSV not found: {csv_path}")
                continue

            print(f"\n{'━' * 60}")
            print(f"  {broker_sym} {tf}")
            print(f"{'━' * 60}")

            data = load_csv(str(csv_path))
            print(f"  Loaded {len(data):,} bars from {csv_path.name}")

            # Cap data size to prevent OOM on large datasets
            MAX_ROWS = 200_000
            if len(data) > MAX_ROWS:
                print(f"  Trimming to last {MAX_ROWS:,} bars (memory limit)")
                data = data[-MAX_ROWS:]

            if len(data) < 200:
                print(f"  SKIP: Insufficient data ({len(data)} bars)")
                continue

            # Train each requested model type
            for model_name in args.models:
                print(f"\n  [{model_name.upper()}]")
                result = None
                start_time = time.time()

                if model_name == "xgboost":
                    result = train_tree_model(data, broker_sym, tf, "xgboost", args.quick)
                elif model_name == "lightgbm":
                    result = train_tree_model(data, broker_sym, tf, "lightgbm", args.quick)
                elif model_name == "lstm":
                    result = train_lstm_model(data, broker_sym, tf, args.quick)
                elif model_name == "rl":
                    result = train_rl_model(data, broker_sym, tf, args.quick)
                elif model_name == "regime":
                    result = train_regime_model(data, broker_sym, tf)
                else:
                    print(f"    Unknown model type: {model_name}")
                    continue

                elapsed = time.time() - start_time

                if result:
                    total_trained += 1
                    results_summary.append({
                        "name": result.get("name", f"{model_name}_{broker_sym}_{tf}"),
                        "model_id": result.get("model_id"),
                        "status": "OK",
                        "time": f"{elapsed:.1f}s",
                    })
                    print(f"    Done in {elapsed:.1f}s")
                else:
                    total_failed += 1
                    results_summary.append({
                        "name": f"{model_name}_{broker_sym}_{tf}",
                        "model_id": None,
                        "status": "FAILED",
                        "time": f"{elapsed:.1f}s",
                    })

    # ── Summary ──
    print(f"\n\n{'=' * 70}")
    print(f"  TRAINING COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Total trained: {total_trained}")
    print(f"  Total failed:  {total_failed}")
    print()
    print(f"  {'Model':<40} {'ID':>6} {'Status':>8} {'Time':>8}")
    print(f"  {'─' * 40} {'─' * 6} {'─' * 8} {'─' * 8}")
    for r in results_summary:
        mid = str(r['model_id'] or '-')
        print(f"  {r['name']:<40} {mid:>6} {r['status']:>8} {r['time']:>8}")

    print(f"\n  Models are registered in the DB and ready for:")
    print(f"    - Backtest:  Select model in ML Lab → Run Backtest")
    print(f"    - Agent:     Create agent → Set ML Model → auto/confirmation mode")
    print(f"    - Filtering: Agents use ML models to filter trade signals")
    print()


if __name__ == "__main__":
    main()
