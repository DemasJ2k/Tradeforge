"""
LLM Tools for ML Lab — interprets natural language ML training requests
and maps them to structured MLTrainRequest parameters.

Flow:
  1. User types: "Train an XGBoost model on XAUUSD H1 data to predict direction"
  2. interpret_ml_request() sends this + context to the LLM
  3. LLM returns structured JSON → validated into MLActionPlan
  4. Frontend shows the plan for user confirmation
  5. On confirm, the plan is executed via the normal /api/ml/train endpoint
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.core.encryption import decrypt_value
from app.models.settings import UserSettings
from app.models.datasource import DataSource
from app.models.ml import MLModel
from app.services.llm.providers import get_provider
from app.services.ml.features import _DEFAULT_FEATURES

logger = logging.getLogger(__name__)

# ── Context builder ──────────────────────────────────────────────────

FEATURE_DESCRIPTIONS = {
    "returns": "1-bar price return",
    "returns_multi": "Multi-bar returns (2, 3, 5, 10 bars)",
    "volatility": "Rolling volatility (5, 10, 20 bar windows)",
    "candle_patterns": "Candle body ratio, upper/lower wick, range",
    "sma": "Distance from SMA (10, 20, 50 periods)",
    "ema": "Distance from EMA (10, 20, 50 periods)",
    "rsi": "RSI normalized (7, 14, 21 periods)",
    "atr": "ATR normalized by price (7, 14 periods)",
    "macd": "MACD line and histogram (normalized)",
    "bollinger": "Bollinger Band position and width",
    "adx": "Average Directional Index (14 period)",
    "stochastic": "Stochastic %K and %D",
    "volume": "Volume ratio vs 20-bar SMA",
}


def _build_ml_context(db: Session, user_id: int) -> str:
    """Build context about available data sources and existing models."""
    # Data sources
    sources = db.query(DataSource).all()
    source_lines = []
    for ds in sources:
        source_lines.append(
            f"  - ID {ds.id}: {ds.filename} | {ds.symbol} {ds.timeframe} | "
            f"{ds.row_count} bars | {ds.date_from} to {ds.date_to}"
        )
    sources_text = "\n".join(source_lines) if source_lines else "  (none uploaded yet)"

    # Existing models
    models = db.query(MLModel).order_by(MLModel.created_at.desc()).limit(10).all()
    model_lines = []
    for m in models:
        acc = ""
        if m.val_metrics and "accuracy" in m.val_metrics:
            acc = f" | val_acc={m.val_metrics['accuracy']:.1%}"
        model_lines.append(
            f"  - ID {m.id}: {m.name} | {m.model_type} | L{m.level} | "
            f"{m.symbol} {m.timeframe} | status={m.status}{acc}"
        )
    models_text = "\n".join(model_lines) if model_lines else "  (no models trained yet)"

    # Features
    feat_lines = [f"  - {k}: {v}" for k, v in FEATURE_DESCRIPTIONS.items()]
    features_text = "\n".join(feat_lines)

    return f"""Available data sources:
{sources_text}

Existing ML models (most recent):
{models_text}

Available feature groups:
{features_text}

Model types: random_forest, xgboost, gradient_boosting
Levels: 1 (Adaptive Params), 2 (Signal Prediction), 3 (Full ML/RL)
Target types: direction (binary up/down), return (magnitude), volatility
Timeframes: M1, M5, M15, M30, H1, H4, D1
"""


# ── LLM interpretation prompt ────────────────────────────────────────

ML_SYSTEM_PROMPT = """You are an ML training configuration assistant for the TradeForge platform.

Your job is to interpret natural language descriptions of ML training requests and
convert them into a structured JSON configuration.

You must return ONLY valid JSON with this structure:
{
  "action": "train",
  "name": "<descriptive model name>",
  "level": <1|2|3>,
  "model_type": "<random_forest|xgboost|gradient_boosting>",
  "datasource_id": <int>,
  "symbol": "<auto-detected or specified>",
  "timeframe": "<M1|M5|M15|M30|H1|H4|D1>",
  "target_type": "<direction|return|volatility>",
  "target_horizon": <1-20>,
  "features": ["<feature_group_1>", "<feature_group_2>", ...],
  "n_estimators": <50-500>,
  "max_depth": <3-20>,
  "learning_rate": <0.01-0.5>,
  "explanation": "<1-2 sentences explaining your choices>"
}

RULES:
- Return ONLY the JSON object. No markdown, no code fences, no extra text.
- If the user mentions a specific dataset, match it by symbol, filename, or ID.
- If no dataset is specified, pick the most appropriate one from available data.
- If no model type is specified, use "xgboost" as default (best general performance).
- Level 2 (Signal Prediction) is the default if not specified.
- Default features: use all available features unless the user wants specific ones.
- If the user asks for something impossible or unclear, set action to "clarify" and
  put the question in "explanation".
- Choose sensible hyperparameters based on dataset size.
- The "name" should be descriptive and include the symbol and approach.
"""


# ── Core functions ───────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """Extract JSON from potentially noisy LLM response."""
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find first { ... } block
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start: i + 1])
                except json.JSONDecodeError:
                    start = None

    raise ValueError("Could not extract valid JSON from LLM response")


def _validate_plan(plan: dict, datasources: list[DataSource]) -> dict:
    """Validate and fill defaults in the action plan."""
    plan.setdefault("action", "train")
    plan.setdefault("name", "AI-Configured Model")
    plan.setdefault("level", 2)
    plan.setdefault("model_type", "xgboost")
    plan.setdefault("target_type", "direction")
    plan.setdefault("target_horizon", 1)
    plan.setdefault("features", _DEFAULT_FEATURES)
    plan.setdefault("n_estimators", 100)
    plan.setdefault("max_depth", 10)
    plan.setdefault("learning_rate", 0.1)
    plan.setdefault("explanation", "")

    # Validate datasource_id exists
    ds_ids = {ds.id for ds in datasources}
    if "datasource_id" not in plan or plan["datasource_id"] not in ds_ids:
        # Try to pick first available
        if datasources:
            plan["datasource_id"] = datasources[0].id
            # Auto-fill symbol/timeframe from datasource
            ds = datasources[0]
            if not plan.get("symbol"):
                plan["symbol"] = ds.symbol or ""
            if not plan.get("timeframe"):
                plan["timeframe"] = ds.timeframe or "H1"
        else:
            plan["action"] = "clarify"
            plan["explanation"] = "No data sources available. Please upload a CSV dataset first."

    # Validate model type
    valid_types = {"random_forest", "xgboost", "gradient_boosting"}
    if plan["model_type"] not in valid_types:
        plan["model_type"] = "xgboost"

    # Validate level
    if plan["level"] not in (1, 2, 3):
        plan["level"] = 2

    # Validate target type
    if plan["target_type"] not in ("direction", "return", "volatility"):
        plan["target_type"] = "direction"

    # Clamp hyperparameters
    plan["n_estimators"] = max(10, min(1000, int(plan.get("n_estimators", 100))))
    plan["max_depth"] = max(2, min(30, int(plan.get("max_depth", 10))))
    plan["learning_rate"] = max(0.001, min(1.0, float(plan.get("learning_rate", 0.1))))
    plan["target_horizon"] = max(1, min(20, int(plan.get("target_horizon", 1))))

    # Validate features
    valid_features = set(_DEFAULT_FEATURES)
    plan["features"] = [f for f in plan["features"] if f in valid_features] or _DEFAULT_FEATURES

    return plan


async def interpret_ml_request(
    db: Session,
    user_id: int,
    user_prompt: str,
) -> dict:
    """
    Interpret a natural language ML request using the LLM.

    Returns:
        dict with keys: action, name, level, model_type, datasource_id, symbol,
        timeframe, target_type, target_horizon, features, n_estimators,
        max_depth, learning_rate, explanation
    """
    # Get user LLM settings
    settings = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
    if not settings or not settings.llm_provider or not settings.llm_api_key_encrypted:
        raise ValueError("LLM not configured. Please set your API key in Settings → AI / LLM.")

    api_key = decrypt_value(settings.llm_api_key_encrypted)
    provider = get_provider(settings.llm_provider, api_key)
    model = settings.llm_model or "claude-sonnet-4-20250514"
    temperature = 0.3  # Low temp for structured output

    # Build context
    context = _build_ml_context(db, user_id)
    datasources = db.query(DataSource).all()

    # Build user message
    user_msg = (
        f"Platform context:\n{context}\n\n"
        f"User request: {user_prompt}"
    )

    messages = [{"role": "user", "content": user_msg}]

    # Call LLM
    logger.info(f"ML interpret: prompt_len={len(user_prompt)}")
    reply, tokens_in, tokens_out = await provider.chat(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=2048,
        system_prompt=ML_SYSTEM_PROMPT,
    )
    logger.info(f"ML interpret: tokens_in={tokens_in} tokens_out={tokens_out}")

    # Parse and validate
    plan = _extract_json(reply)
    plan = _validate_plan(plan, datasources)

    # Enrich with datasource info for display
    ds = next((d for d in datasources if d.id == plan.get("datasource_id")), None)
    if ds:
        plan["datasource_name"] = ds.filename
        plan["datasource_info"] = f"{ds.symbol} {ds.timeframe} — {ds.row_count} bars"
        if not plan.get("symbol"):
            plan["symbol"] = ds.symbol or ""
        if not plan.get("timeframe"):
            plan["timeframe"] = ds.timeframe or "H1"

    plan["tokens_used"] = {"input": tokens_in, "output": tokens_out}

    return plan


def get_ml_context_for_chat(db: Session, user_id: int) -> dict:
    """
    Build ML page context data for the ChatSidebar.
    Called when page_context == "ml".
    """
    # Data sources summary
    sources = db.query(DataSource).all()
    source_list = [
        {"id": ds.id, "filename": ds.filename, "symbol": ds.symbol,
         "timeframe": ds.timeframe, "rows": ds.row_count}
        for ds in sources
    ]

    # Models summary
    models = db.query(MLModel).order_by(MLModel.created_at.desc()).limit(10).all()
    model_list = []
    for m in models:
        val_acc = None
        if m.val_metrics and "accuracy" in m.val_metrics:
            val_acc = round(m.val_metrics["accuracy"], 4)
        model_list.append({
            "id": m.id, "name": m.name, "type": m.model_type,
            "level": m.level, "symbol": m.symbol, "timeframe": m.timeframe,
            "status": m.status, "val_accuracy": val_acc,
        })

    return {
        "data_sources": source_list,
        "trained_models": model_list,
        "available_features": _DEFAULT_FEATURES,
        "model_types": ["random_forest", "xgboost", "gradient_boosting"],
        "target_types": ["direction", "return", "volatility"],
    }
