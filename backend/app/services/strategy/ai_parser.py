"""
AI Strategy Parser — takes uploaded documents (TXT, PineScript, PDF, MD)
and uses the LLM to produce a valid TradeForge strategy JSON config.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.core.encryption import decrypt_value
from app.models.settings import UserSettings
from app.services.llm.providers import get_provider

logger = logging.getLogger(__name__)

# ── Schema description for the LLM ──────────────────────────────────

STRATEGY_SCHEMA = """
You must return valid JSON with this exact structure:
{
  "name": "Strategy Name",
  "description": "1–2 sentence description of the strategy logic.",
  "indicators": [
    {
      "id": "<unique_slug>",
      "type": "<SMA|EMA|RSI|MACD|Bollinger|ATR|Stochastic|ADX|VWAP|ADR|Pivot|PivotHigh|PivotLow>",
      "params": { ... },
      "overlay": true/false
    }
  ],
  "entry_rules": [
    {
      "left": "<source>",
      "operator": "<crosses_above|crosses_below|greater_than|less_than|equals>",
      "right": "<source_or_value>",
      "logic": "<AND|OR>",
      "direction": "<long|short|both>"
    }
  ],
  "exit_rules": [
    {
      "left": "<source>",
      "operator": "<crosses_above|crosses_below|greater_than|less_than|equals>",
      "right": "<source_or_value>",
      "logic": "<AND|OR>",
      "direction": "<long|short|both>"
    }
  ],
  "risk_params": {
    "position_size_type": "fixed_lot",
    "position_size_value": 0.01,
    "stop_loss_type": "<fixed_pips|atr_multiple|adr_pct|percent|pivot_level|swing>",
    "stop_loss_value": <number>,
    "take_profit_type": "<fixed_pips|atr_multiple|adr_pct|percent|rr_ratio|pivot_level>",
    "take_profit_value": <number>,
    "take_profit_2_type": "<optional, same choices>",
    "take_profit_2_value": <optional number>,
    "lot_split": [0.6, 0.4],
    "breakeven_on_tp1": false,
    "trailing_stop": false,
    "trailing_stop_type": "fixed_pips",
    "trailing_stop_value": 0,
    "max_positions": 1,
    "max_drawdown_pct": 5
  },
  "filters": {
    "time_start": "08:00",
    "time_end": "17:00",
    "days_of_week": [1,2,3,4,5],
    "min_adx": 0,
    "max_adx": 0,
    "min_volatility": 0,
    "max_volatility": 0
  }
}

RULES FOR SOURCES:
- "price.close", "price.open", "price.high", "price.low" for raw price
- "<indicator_id>" for the main value (e.g., "rsi_1", "ema_1")
- "<indicator_id>_signal", "<indicator_id>_hist" for MACD sub-keys
- "<indicator_id>_upper", "<indicator_id>_lower" for Bollinger sub-keys
- "<indicator_id>_d" for Stochastic %D
- "<indicator_id>_pp", "<indicator_id>_r1"..."_r3", "<indicator_id>_s1"..."_s3" for Pivot sub-keys
- A plain number string like "80" or "20" for fixed threshold values

INDICATOR PARAMS:
- SMA/EMA: {"period": <int>}
- RSI: {"period": <int>}
- MACD: {"fast": <int>, "slow": <int>, "signal": <int>}
- Bollinger: {"period": <int>, "std_dev": <float>}
- ATR: {"period": <int>}
- Stochastic: {"k_period": <int>, "d_period": <int>, "smooth": <int>}
- ADX: {"period": <int>}
- VWAP: {}
- ADR: {"period": <int>}
- Pivot: {"type": "standard"}
- PivotHigh/PivotLow: {"lookback": <int>}
"""

SYSTEM_PROMPT = f"""You are a trading strategy conversion engine.
Your job is to read trading strategy descriptions, PineScript code, or general
trading documents and convert them into a structured TradeForge strategy JSON.

{STRATEGY_SCHEMA}

IMPORTANT:
- Return ONLY the JSON object. No markdown, no explanation, no code fences.
- If the document describes multiple strategies, pick the primary one.
- If specific parameter values aren't given, use sensible defaults.
- Make sure every indicator referenced in rules is defined in the indicators array.
- Use lowercase indicator IDs with underscores (e.g., "ema_200", "rsi_14").
- The first entry rule should have logic "AND"; subsequent ones use "AND" or "OR" as appropriate.
- If the strategy has both long and short conditions, set direction accordingly.
"""


def _extract_text_from_pdf(file_bytes: bytes) -> str:
    """Best-effort PDF text extraction."""
    try:
        import io
        # Try PyPDF2 first
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(io.BytesIO(file_bytes))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(pages)
        except ImportError:
            pass
        # Fallback: pdfplumber
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                pages = [p.extract_text() or "" for p in pdf.pages]
                return "\n\n".join(pages)
        except ImportError:
            pass
        return "[PDF content could not be extracted — install PyPDF2 or pdfplumber]"
    except Exception as e:
        return f"[PDF extraction error: {e}]"


def _extract_json(text: str) -> dict:
    """Extract the first JSON object from a potentially noisy LLM response."""
    # Strip markdown fences
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text)
    text = text.strip()

    # Try direct parse
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
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    start = None

    raise ValueError("Could not extract valid JSON from LLM response")


def _validate_strategy(data: dict) -> dict:
    """Basic validation and defaults."""
    if "name" not in data or not data["name"]:
        data["name"] = "AI-Generated Strategy"
    if "indicators" not in data:
        data["indicators"] = []
    if "entry_rules" not in data:
        data["entry_rules"] = []
    if "exit_rules" not in data:
        data["exit_rules"] = []
    if "risk_params" not in data:
        data["risk_params"] = {}
    if "filters" not in data:
        data["filters"] = {}

    # Ensure each indicator has required fields
    for ind in data["indicators"]:
        ind.setdefault("id", ind.get("type", "ind").lower() + "_1")
        ind.setdefault("type", "SMA")
        ind.setdefault("params", {})
        ind.setdefault("overlay", True)

    # Ensure each rule has required fields
    for rules in [data["entry_rules"], data["exit_rules"]]:
        for r in rules:
            r.setdefault("left", "price.close")
            r.setdefault("operator", "crosses_above")
            r.setdefault("right", "0")
            r.setdefault("logic", "AND")
            r.setdefault("direction", "both")

    # Risk param defaults
    rp = data["risk_params"]
    rp.setdefault("position_size_type", "fixed_lot")
    rp.setdefault("position_size_value", 0.01)
    rp.setdefault("stop_loss_type", "fixed_pips")
    rp.setdefault("stop_loss_value", 50)
    rp.setdefault("take_profit_type", "fixed_pips")
    rp.setdefault("take_profit_value", 100)
    rp.setdefault("trailing_stop", False)
    rp.setdefault("trailing_stop_value", 0)
    rp.setdefault("max_positions", 1)
    rp.setdefault("max_drawdown_pct", 5)

    return data


async def parse_trading_document(
    db: Session,
    user_id: int,
    file_content: str | bytes,
    filename: str,
    user_prompt: str = "",
) -> dict:
    """
    Parse a trading document into a TradeForge strategy JSON.

    Args:
        db: Database session (for loading LLM settings)
        user_id: Current user ID
        file_content: Raw file content (str for text, bytes for PDF)
        filename: Original filename (used to detect type)
        user_prompt: Optional extra instructions from the user

    Returns:
        Validated strategy dict ready for the StrategyEditor
    """
    # ── Get user LLM settings ────────────────────────────
    settings = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
    if not settings or not settings.llm_provider or not settings.llm_api_key_encrypted:
        raise ValueError("LLM not configured. Please set your API key in Settings → AI / LLM.")

    api_key = decrypt_value(settings.llm_api_key_encrypted)
    provider = get_provider(settings.llm_provider, api_key)
    model = settings.llm_model or "claude-sonnet-4-20250514"
    temperature = float(settings.llm_temperature or "0.3")  # Lower temp for structured output
    max_tokens = 4096

    # ── Extract text ─────────────────────────────────────
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"

    if ext == "pdf":
        if isinstance(file_content, str):
            file_content = file_content.encode("utf-8")
        document_text = _extract_text_from_pdf(file_content)
    else:
        if isinstance(file_content, bytes):
            document_text = file_content.decode("utf-8", errors="replace")
        else:
            document_text = file_content

    # Truncate very long documents
    if len(document_text) > 15000:
        document_text = document_text[:15000] + "\n\n[... truncated ...]"

    # ── Build messages ───────────────────────────────────
    user_msg = f"Convert the following trading strategy document into a TradeForge strategy JSON.\n\n"
    if user_prompt:
        user_msg += f"Additional instructions: {user_prompt}\n\n"
    user_msg += f"--- DOCUMENT ({filename}) ---\n{document_text}\n--- END DOCUMENT ---"

    messages = [{"role": "user", "content": user_msg}]

    # ── Call LLM ─────────────────────────────────────────
    logger.info(f"AI strategy parse: file={filename} ext={ext} chars={len(document_text)}")
    reply, tokens_in, tokens_out = await provider.chat(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        system_prompt=SYSTEM_PROMPT,
    )
    logger.info(f"AI strategy parse: tokens_in={tokens_in} tokens_out={tokens_out}")

    # ── Parse + validate ─────────────────────────────────
    strategy = _extract_json(reply)
    strategy = _validate_strategy(strategy)

    return strategy
