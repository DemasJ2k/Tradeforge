"""
News article AI analyzer — uses LLM to extract trading insights from articles.

Provides:
  - analyze_article()  : Full LLM analysis of a single article
  - batch_sentiment()  : Quick sentiment scoring for multiple headlines
"""

import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.core.encryption import decrypt_value
from app.models.settings import UserSettings
from app.models.news import NewsArticle
from app.services.llm.providers import get_provider

_log = logging.getLogger(__name__)

ANALYSIS_PROMPT = """You are a financial market analyst AI. Analyze the following news article and provide a structured trading analysis.

Article:
Headline: {headline}
Summary: {summary}
Source: {source}
Published: {published_at}
Related Symbols: {related_symbols}

Provide your analysis as JSON with these fields:
{{
  "key_points": ["point1", "point2", "point3"],
  "trading_impact": "bullish | bearish | neutral | mixed",
  "impact_magnitude": "high | medium | low",
  "affected_symbols": ["XAUUSD", "EURUSD"],
  "affected_sectors": ["commodities", "forex", "indices", "crypto"],
  "risk_factors": ["factor1", "factor2"],
  "recommendation": "A 1-2 sentence trading recommendation based on this news.",
  "time_horizon": "immediate | short_term | medium_term | long_term",
  "confidence": 0.75
}}

Rules:
- affected_symbols should use standard forex/CFD format (XAUUSD, EURUSD, BTCUSD, US30, NAS100, etc.)
- confidence is 0.0 to 1.0
- Be specific and actionable in your recommendation
- Consider both direct and indirect market impacts
- Return ONLY the JSON object, no other text"""


SENTIMENT_PROMPT = """Rate the sentiment of each headline for financial markets. Return a JSON array.
Each entry: {{"headline": "...", "score": -1.0 to 1.0, "label": "Bearish|Neutral|Bullish"}}

Headlines:
{headlines}

Return ONLY the JSON array."""


async def analyze_article(
    db: Session,
    user_id: int,
    article_id: int,
) -> Optional[dict]:
    """
    Analyze a news article using the user's configured LLM provider.
    Stores the analysis in the article's ai_analysis column.
    Returns the analysis dict or None on failure.
    """
    # Get user's LLM settings
    user_settings = db.query(UserSettings).filter(
        UserSettings.user_id == user_id
    ).first()

    if not user_settings or not user_settings.api_key_encrypted:
        _log.warning("No LLM API key configured for user %d", user_id)
        return None

    # Get the article
    article = db.query(NewsArticle).filter(NewsArticle.id == article_id).first()
    if not article:
        _log.warning("Article %d not found", article_id)
        return None

    # Check if already analyzed
    if article.ai_analysis:
        try:
            existing = json.loads(article.ai_analysis) if isinstance(article.ai_analysis, str) else article.ai_analysis
            if existing and isinstance(existing, dict) and "key_points" in existing:
                return existing
        except (json.JSONDecodeError, TypeError):
            pass

    # Build prompt
    prompt = ANALYSIS_PROMPT.format(
        headline=article.headline or "",
        summary=article.summary or "",
        source=article.source or "",
        published_at=article.published_at.isoformat() if article.published_at else "",
        related_symbols=article.related_symbols or "",
    )

    # Call LLM
    try:
        api_key = decrypt_value(user_settings.api_key_encrypted)
        provider_name = user_settings.provider or "claude"
        model = user_settings.model or "claude-sonnet-4-20250514"

        provider = get_provider(provider_name, api_key)
        messages = [{"role": "user", "content": prompt}]

        reply, tokens_in, tokens_out = await provider.chat(
            messages=messages,
            model=model,
            temperature=0.3,
            max_tokens=1024,
            system_prompt="You are a financial market analysis AI. Always respond with valid JSON only.",
        )

        # Parse JSON from response
        analysis = _extract_json(reply)
        if not analysis:
            _log.warning("Failed to parse analysis JSON for article %d", article_id)
            return None

        # Validate required fields
        analysis.setdefault("key_points", [])
        analysis.setdefault("trading_impact", "neutral")
        analysis.setdefault("impact_magnitude", "low")
        analysis.setdefault("affected_symbols", [])
        analysis.setdefault("affected_sectors", [])
        analysis.setdefault("risk_factors", [])
        analysis.setdefault("recommendation", "")
        analysis.setdefault("time_horizon", "short_term")
        analysis.setdefault("confidence", 0.5)

        # Store in DB
        article.ai_analysis = json.dumps(analysis) if not isinstance(analysis, str) else analysis

        # Update symbol_tags from affected_symbols
        if analysis.get("affected_symbols"):
            existing_symbols = set((article.related_symbols or "").split(","))
            existing_symbols.update(analysis["affected_symbols"])
            existing_symbols.discard("")
            article.related_symbols = ",".join(sorted(existing_symbols))

        db.commit()

        _log.info("Analyzed article %d: impact=%s, confidence=%.2f",
                   article_id, analysis["trading_impact"], analysis["confidence"])
        return analysis

    except Exception as e:
        _log.error("Article analysis failed for %d: %s", article_id, e)
        return None


async def batch_sentiment(
    db: Session,
    user_id: int,
    headlines: list[str],
) -> list[dict]:
    """
    Quick sentiment scoring for a batch of headlines using LLM.
    Returns list of {headline, score, label} dicts.
    """
    if not headlines:
        return []

    user_settings = db.query(UserSettings).filter(
        UserSettings.user_id == user_id
    ).first()

    if not user_settings or not user_settings.api_key_encrypted:
        return [{"headline": h, "score": 0.0, "label": "Neutral"} for h in headlines]

    # Limit batch size
    batch = headlines[:20]
    headlines_text = "\n".join(f"- {h}" for h in batch)
    prompt = SENTIMENT_PROMPT.format(headlines=headlines_text)

    try:
        api_key = decrypt_value(user_settings.api_key_encrypted)
        provider_name = user_settings.provider or "claude"
        model = user_settings.model or "claude-sonnet-4-20250514"

        provider = get_provider(provider_name, api_key)
        messages = [{"role": "user", "content": prompt}]

        reply, _, _ = await provider.chat(
            messages=messages,
            model=model,
            temperature=0.2,
            max_tokens=2048,
            system_prompt="You are a financial sentiment analysis AI. Always respond with valid JSON only.",
        )

        results = _extract_json(reply)
        if isinstance(results, list):
            return results

        return [{"headline": h, "score": 0.0, "label": "Neutral"} for h in batch]

    except Exception as e:
        _log.error("Batch sentiment failed: %s", e)
        return [{"headline": h, "score": 0.0, "label": "Neutral"} for h in batch]


def _extract_json(text: str) -> Optional[dict | list]:
    """Extract JSON from LLM response, handling markdown code blocks."""
    if not text:
        return None

    # Try direct parse
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            clean = part.strip()
            if clean.startswith("json"):
                clean = clean[4:].strip()
            try:
                return json.loads(clean)
            except json.JSONDecodeError:
                continue

    # Try finding JSON object/array boundaries
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

    return None
