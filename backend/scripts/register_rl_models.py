"""
Register pre-trained RL ONNX models into the MLModel database table.
Run this once after ONNX export to make models available in the UI.

Usage:
  python register_rl_models.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
# Import all model modules so SQLAlchemy resolves all FK references (same as main.py)
from app.models import user, strategy, backtest, optimization, trade, datasource, knowledge  # noqa: F401
from app.models import settings as settings_model  # noqa: F401
from app.models import llm as llm_model  # noqa: F401
from app.models import ml as ml_model  # noqa: F401
from app.models import invitation  # noqa: F401
from app.models import agent as agent_model  # noqa: F401
from app.models import password_reset as password_reset_model  # noqa: F401
from app.models import optimization_phase as optimization_phase_model  # noqa: F401
from app.models import news as news_model  # noqa: F401
from app.models import watchlist as watchlist_model  # noqa: F401
from app.models import prop_firm as prop_firm_model  # noqa: F401
from app.models import broadcast as broadcast_model  # noqa: F401
from app.models.ml import MLModel
from datetime import datetime, timezone


MODELS = [
    {
        "name": "RL LW US30 PPO",
        "symbol": "US30",
        "timeframe": "M5",
        "onnx_filename": "rl_lw_us30.onnx",
        "eval_avg_pnl": 640.44,
        "eval_avg_wr": 55.1,
        "eval_avg_trades": 563.7,
        "eval_avg_dd": 4.9,
        "timesteps": 500000,
        "feature_space": "lw_25",
    },
    {
        "name": "RL LW XAUUSD PPO",
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "onnx_filename": "rl_lw_xauusd.onnx",
        "eval_avg_pnl": 29.04,
        "eval_avg_wr": 53.6,
        "eval_avg_trades": 587.4,
        "eval_avg_dd": 0.6,
        "timesteps": 500000,
        "feature_space": "lw_25",
    },
    {
        "name": "RL MB BTCUSD PPO",
        "symbol": "BTCUSD",
        "timeframe": "M5",
        "onnx_filename": "rl_mb_btcusd.onnx",
        "eval_avg_pnl": 335.73,
        "eval_avg_wr": 51.3,
        "eval_avg_trades": 225.0,
        "eval_avg_dd": 17.2,
        "timesteps": 1000000,
        "feature_space": "mb_25",
    },
]


def register_models():
    db = SessionLocal()
    try:
        for m in MODELS:
            # Check if already registered
            existing = db.query(MLModel).filter(
                MLModel.name == m["name"],
                MLModel.model_type == "rl_ppo",
            ).first()

            if existing:
                print(f"[SKIP] Already registered: {m['name']} (id={existing.id})")
                continue

            model_path = os.path.join("data", "ml_models", m["onnx_filename"])
            abs_path = os.path.join(os.path.dirname(__file__), "..", model_path)
            if not os.path.exists(abs_path):
                print(f"[MISS] ONNX file not found: {abs_path}")
                continue

            ml_model = MLModel(
                name=m["name"],
                level=3,
                model_type="rl_ppo",
                symbol=m["symbol"],
                timeframe=m["timeframe"],
                status="ready",
                model_path=model_path,
                features_config={"feature_space": m["feature_space"], "obs_dims": 32},
                target_config={"action_space": 3, "actions": ["skip", "take", "close"]},
                hyperparams={
                    "algorithm": "PPO",
                    "timesteps": m["timesteps"],
                    "feature_space": m["feature_space"],
                },
                train_metrics={
                    "eval_avg_pnl": m["eval_avg_pnl"],
                    "eval_avg_wr": m["eval_avg_wr"],
                    "eval_avg_trades": m["eval_avg_trades"],
                    "eval_avg_dd": m["eval_avg_dd"],
                },
                val_metrics={},
                feature_importance={},
                trained_at=datetime.now(timezone.utc),
            )
            db.add(ml_model)
            db.flush()
            print(f"[OK] Registered: {m['name']} (id={ml_model.id})")

        db.commit()
        print("\n[DONE] All RL models registered.")

        # List all RL models
        rl_models = db.query(MLModel).filter(MLModel.model_type == "rl_ppo").all()
        print(f"\nRL models in database ({len(rl_models)}):")
        for rm in rl_models:
            print(f"  id={rm.id} | {rm.name} | {rm.symbol} | status={rm.status} | path={rm.model_path}")

    except Exception as e:
        print(f"[ERROR] {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    register_models()
