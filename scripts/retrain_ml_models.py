"""
Retrain ML models with better hyperparameters to reduce overfitting.

Strategy:
  - Lower max_depth (4 instead of 8) to reduce model complexity
  - Add L1/L2 regularization (reg_alpha, reg_lambda)
  - Higher min_child_weight to prevent fitting noise
  - Lower subsample and colsample_bytree for bagging
  - Larger horizon (direction is easier over more bars)
  - Try multiple configurations and keep the best
  - Add Random Forest as comparison model
"""
import requests
import json
import sys
import time

BASE = "http://localhost:8000/api"


def login():
    r = requests.post(f"{BASE}/auth/login", json={
        "username": "TradeforgeAdmin",
        "password": "Tradeforge2025!",
    })
    r.raise_for_status()
    return r.json()["access_token"]


def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def train_model(h, config):
    """Train a single model and return results."""
    print(f"\n  Training: {config['name']}")
    print(f"    Type: {config['model_type']}, Depth: {config['max_depth']}, "
          f"LR: {config['learning_rate']}, Est: {config['n_estimators']}")
    print(f"    Target: {config['target_type']} (horizon={config['target_horizon']})")
    print(f"    Reg: alpha={config.get('reg_alpha', 0)}, "
          f"lambda={config.get('reg_lambda', 1)}, "
          f"min_child_weight={config.get('min_child_weight', 1)}, "
          f"gamma={config.get('gamma', 0)}")

    r = requests.post(f"{BASE}/ml/train", headers=h, json=config)
    if r.status_code in (200, 201):
        model = r.json()
        train_acc = model.get("train_metrics", {}).get("accuracy", 0)
        val_acc = model.get("val_metrics", {}).get("accuracy", 0)
        val_f1 = model.get("val_metrics", {}).get("f1", 0)
        val_prec = model.get("val_metrics", {}).get("precision", 0)
        val_rec = model.get("val_metrics", {}).get("recall", 0)
        print(f"    Train Acc: {train_acc:.1%}, Val Acc: {val_acc:.1%}")
        print(f"    Val F1: {val_f1:.3f}, Precision: {val_prec:.3f}, Recall: {val_rec:.3f}")

        # Top 5 feature importances
        fi = model.get("feature_importance", {})
        top5 = sorted(fi.items(), key=lambda x: -x[1])[:5]
        if top5:
            print(f"    Top features: {', '.join(f'{n}={v:.3f}' for n, v in top5)}")

        return model
    else:
        print(f"    ERROR: {r.status_code} — {r.text[:200]}")
        return None


def main():
    print("=" * 80)
    print("  TRADEFORGE — ML MODEL RETRAINING (Improved Regularization)")
    print("=" * 80)

    token = login()
    h = headers(token)
    print("  Logged in successfully")

    best_models = {}

    # ═══════════════════════════════════════════════════════════
    #  MSS STRATEGY — XAUUSD M10 (datasource_id=6, strategy_id=2)
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  MSS STRATEGY — Training Multiple Configs")
    print("=" * 80)

    mss_base = {
        "level": 2,
        "datasource_id": 6,
        "strategy_id": 2,
        "symbol": "XAUUSD",
        "timeframe": "M10",
    }

    mss_features_full = [
        "returns", "returns_multi", "volatility", "candle_patterns",
        "sma", "ema", "rsi", "atr", "macd",
        "bollinger", "adx", "stochastic", "volume",
    ]

    mss_features_slim = [
        "returns", "volatility", "candle_patterns",
        "rsi", "atr", "macd", "bollinger", "adx",
    ]

    mss_configs = [
        # Config 1: XGBoost strong regularization, direction h=5
        {
            **mss_base,
            "name": "MSS-XGB-Reg-H5",
            "model_type": "xgboost",
            "features": mss_features_full,
            "target_type": "direction",
            "target_horizon": 5,
            "n_estimators": 500,
            "max_depth": 4,
            "learning_rate": 0.01,
            "subsample": 0.7,
            "colsample_bytree": 0.7,
            "reg_alpha": 0.1,
            "reg_lambda": 5.0,
            "min_child_weight": 10,
            "gamma": 0.1,
            "early_stopping_rounds": 50,
        },
        # Config 2: XGBoost moderate reg, direction h=10
        {
            **mss_base,
            "name": "MSS-XGB-Mod-H10",
            "model_type": "xgboost",
            "features": mss_features_full,
            "target_type": "direction",
            "target_horizon": 10,
            "n_estimators": 300,
            "max_depth": 5,
            "learning_rate": 0.03,
            "subsample": 0.75,
            "colsample_bytree": 0.75,
            "reg_alpha": 0.05,
            "reg_lambda": 3.0,
            "min_child_weight": 5,
            "gamma": 0.05,
            "early_stopping_rounds": 30,
        },
        # Config 3: XGBoost slim features, direction h=3
        {
            **mss_base,
            "name": "MSS-XGB-Slim-H3",
            "model_type": "xgboost",
            "features": mss_features_slim,
            "target_type": "direction",
            "target_horizon": 3,
            "n_estimators": 400,
            "max_depth": 3,
            "learning_rate": 0.02,
            "subsample": 0.65,
            "colsample_bytree": 0.65,
            "reg_alpha": 0.2,
            "reg_lambda": 8.0,
            "min_child_weight": 15,
            "gamma": 0.2,
            "early_stopping_rounds": 40,
        },
        # Config 4: Random Forest (different algorithm comparison)
        {
            **mss_base,
            "name": "MSS-RF-H5",
            "model_type": "random_forest",
            "features": mss_features_full,
            "target_type": "direction",
            "target_horizon": 5,
            "n_estimators": 500,
            "max_depth": 6,
            "learning_rate": 0.1,
            "min_samples_split": 20,
            "min_samples_leaf": 10,
        },
    ]

    mss_best_val = 0
    mss_best_model = None

    for cfg in mss_configs:
        result = train_model(h, cfg)
        if result:
            val_acc = result.get("val_metrics", {}).get("accuracy", 0)
            if val_acc > mss_best_val:
                mss_best_val = val_acc
                mss_best_model = result
                best_models["mss"] = result

    if mss_best_model:
        print(f"\n  MSS BEST: {mss_best_model['name']} — Val Acc: {mss_best_val:.1%}")

    # ═══════════════════════════════════════════════════════════
    #  GOLD BT STRATEGY — XAUUSD M1 (datasource_id=5, strategy_id=3)
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  GOLD BT STRATEGY — Training Multiple Configs")
    print("=" * 80)

    gold_base = {
        "level": 2,
        "datasource_id": 5,
        "strategy_id": 3,
        "symbol": "XAUUSD",
        "timeframe": "M1",
    }

    gold_features_full = [
        "returns", "returns_multi", "volatility", "candle_patterns",
        "sma", "ema", "rsi", "atr", "macd",
        "bollinger", "adx", "stochastic", "volume",
    ]

    gold_features_slim = [
        "returns", "volatility", "candle_patterns",
        "rsi", "atr", "bollinger", "stochastic",
    ]

    gold_configs = [
        # Config 1: XGBoost strong regularization, direction h=10
        {
            **gold_base,
            "name": "GoldBT-XGB-Reg-H10",
            "model_type": "xgboost",
            "features": gold_features_full,
            "target_type": "direction",
            "target_horizon": 10,
            "n_estimators": 500,
            "max_depth": 4,
            "learning_rate": 0.01,
            "subsample": 0.7,
            "colsample_bytree": 0.7,
            "reg_alpha": 0.1,
            "reg_lambda": 5.0,
            "min_child_weight": 10,
            "gamma": 0.1,
            "early_stopping_rounds": 50,
        },
        # Config 2: XGBoost moderate, direction h=20 (stronger trend signal)
        {
            **gold_base,
            "name": "GoldBT-XGB-Mod-H20",
            "model_type": "xgboost",
            "features": gold_features_full,
            "target_type": "direction",
            "target_horizon": 20,
            "n_estimators": 300,
            "max_depth": 5,
            "learning_rate": 0.03,
            "subsample": 0.75,
            "colsample_bytree": 0.75,
            "reg_alpha": 0.05,
            "reg_lambda": 3.0,
            "min_child_weight": 5,
            "gamma": 0.05,
            "early_stopping_rounds": 30,
        },
        # Config 3: XGBoost slim features, volatility target
        {
            **gold_base,
            "name": "GoldBT-XGB-Vol-H10",
            "model_type": "xgboost",
            "features": gold_features_slim,
            "target_type": "volatility",
            "target_horizon": 10,
            "n_estimators": 400,
            "max_depth": 4,
            "learning_rate": 0.02,
            "subsample": 0.7,
            "colsample_bytree": 0.7,
            "reg_alpha": 0.05,
            "reg_lambda": 3.0,
            "min_child_weight": 8,
            "gamma": 0.1,
        },
        # Config 4: Random Forest comparison
        {
            **gold_base,
            "name": "GoldBT-RF-H10",
            "model_type": "random_forest",
            "features": gold_features_full,
            "target_type": "direction",
            "target_horizon": 10,
            "n_estimators": 500,
            "max_depth": 6,
            "learning_rate": 0.1,
            "min_samples_split": 20,
            "min_samples_leaf": 10,
        },
    ]

    gold_best_val = 0
    gold_best_model = None

    for cfg in gold_configs:
        result = train_model(h, cfg)
        if result:
            val_acc = result.get("val_metrics", {}).get("accuracy", 0)
            # For volatility target, use R² instead
            if cfg["target_type"] == "volatility":
                r2 = result.get("val_metrics", {}).get("r2", -1)
                print(f"    [Volatility model — R²: {r2:.4f}]")
                # Skip accuracy comparison for regression models
                continue
            if val_acc > gold_best_val:
                gold_best_val = val_acc
                gold_best_model = result
                best_models["gold"] = result

    if gold_best_model:
        print(f"\n  GOLD BT BEST: {gold_best_model['name']} — Val Acc: {gold_best_val:.1%}")

    # ═══════════════════════════════════════════════════════════
    #  SUMMARY
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  RETRAINING COMPLETE — ALL MODELS")
    print("=" * 80)

    r = requests.get(f"{BASE}/ml/models", headers=h)
    if r.status_code == 200:
        models = r.json()
        for m in models:
            acc = m.get("val_accuracy")
            acc_str = f"{acc:.1%}" if acc else "N/A"
            train_acc = m.get("train_accuracy")
            train_str = f"{train_acc:.1%}" if train_acc else "N/A"
            gap = f"{(train_acc - acc):.1%}" if (train_acc and acc) else "N/A"
            print(f"  ID={m['id']:2d}: {m['name']:<30s} | {m['model_type']:<8s} | "
                  f"Train: {train_str} | Val: {acc_str} | Gap: {gap} | {m['status']}")

    print("\n" + "=" * 80)
    print("  DONE")
    print("=" * 80)


if __name__ == "__main__":
    main()
