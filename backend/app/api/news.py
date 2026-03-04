"""
News API endpoints — economic calendar, market news, sentiment, and AI analysis.

Endpoints:
  GET  /api/news/calendar           — upcoming economic events
  GET  /api/news/feed               — market news articles
  GET  /api/news/articles/{id}      — single article detail
  GET  /api/news/sentiment/{sym}    — sentiment summary for a symbol
  GET  /api/news/overview           — combined dashboard widget data
  POST /api/news/fetch              — trigger manual refresh
  POST /api/news/articles/{id}/analyze — AI analysis of an article
  POST /api/news/batch-sentiment    — batch LLM sentiment for headlines
  GET  /api/news/providers          — list configured news providers
  POST /api/news/providers          — add a news provider
  PUT  /api/news/providers/{id}     — update a news provider
  DELETE /api/news/providers/{id}   — remove a news provider
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.news import NewsArticle, NewsProvider
from app.services.news.aggregator import (
    get_economic_calendar,
    get_news_feed,
    get_sentiment,
)
from app.services.news.analyzer import analyze_article, batch_sentiment

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/news", tags=["news"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class BatchSentimentRequest(BaseModel):
    headlines: list[str]

class ProviderCreate(BaseModel):
    name: str
    provider_type: str
    api_key: str = ""
    base_url: str = ""
    enabled: bool = True
    config: dict = {}

class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    enabled: Optional[bool] = None
    config: Optional[dict] = None


# ── Calendar & Feed ──────────────────────────────────────────────────────────

@router.get("/calendar")
async def calendar(
    from_date: Optional[str] = Query(None, alias="from", description="Start date YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, alias="to", description="End date YYYY-MM-DD"),
    currency: Optional[str] = Query(None, description="Filter by currency (USD, EUR, GBP...)"),
    impact: Optional[str] = Query(None, description="Filter by impact (high, medium, low)"),
    user: User = Depends(get_current_user),
):
    """
    Get economic calendar events.
    Defaults to past 1 day through next 7 days.
    """
    events = await get_economic_calendar(from_date, to_date, currency, impact)
    return {"items": events, "total": len(events)}


@router.get("/feed")
async def news_feed(
    category: str = Query("general", description="Category: general, forex, crypto"),
    symbol: Optional[str] = Query(None, description="Filter by related symbol"),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
):
    """
    Get market news articles.
    Categories: general, forex, crypto, merger.
    """
    articles = await get_news_feed(category, symbol, limit)
    return {"items": articles, "total": len(articles)}


@router.get("/articles/{article_id}")
async def get_article(
    article_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single article with full details including AI analysis."""
    article = db.query(NewsArticle).filter(NewsArticle.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    import json
    ai = None
    if article.ai_analysis:
        try:
            ai = json.loads(article.ai_analysis) if isinstance(article.ai_analysis, str) else article.ai_analysis
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "id": article.id,
        "external_id": article.external_id,
        "headline": article.headline,
        "summary": article.summary,
        "source": article.source,
        "url": article.url,
        "image_url": article.image_url,
        "category": article.category,
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "sentiment_score": article.sentiment_score,
        "sentiment_label": article.sentiment_label,
        "related_symbols": article.related_symbols,
        "ai_analysis": ai,
        "fetched_at": article.fetched_at.isoformat() if article.fetched_at else None,
    }


# ── Sentiment ────────────────────────────────────────────────────────────────

@router.get("/sentiment/{symbol}")
async def sentiment(
    symbol: str,
    user: User = Depends(get_current_user),
):
    """
    Get aggregated sentiment for a symbol.
    Returns score (-1 to 1), label (Bearish/Neutral/Bullish),
    and article count.
    """
    result = await get_sentiment(symbol)
    return result


# ── Overview ─────────────────────────────────────────────────────────────────

@router.get("/overview")
async def overview(
    user: User = Depends(get_current_user),
):
    """
    Combined news overview for dashboard widgets.
    Returns upcoming high-impact events, latest headlines, and
    sentiment for key symbols.
    """
    # Get high-impact events in next 48 hours
    cal = await get_economic_calendar(impact="high")
    upcoming = [e for e in cal if e.get("actual") is None][:10]

    # Get latest forex + crypto news
    forex_news = await get_news_feed(category="forex", limit=10)
    crypto_news = await get_news_feed(category="crypto", limit=5)

    # Get sentiment for key symbols (from cache, no extra API calls)
    sentiment_summary = {}
    for sym in ["XAUUSD", "EURUSD", "BTCUSD", "US30"]:
        try:
            s = await get_sentiment(sym)
            sentiment_summary[sym] = s
        except Exception:
            sentiment_summary[sym] = {"score": 0.0, "label": "Neutral", "articles": 0}

    return {
        "upcoming_events": upcoming,
        "forex_news": forex_news,
        "crypto_news": crypto_news,
        "sentiment": sentiment_summary,
    }


# ── Manual Fetch ─────────────────────────────────────────────────────────────

@router.post("/fetch")
async def trigger_fetch(
    category: str = Query("general", description="Category to refresh: general, forex, crypto"),
    user: User = Depends(get_current_user),
):
    """Trigger an immediate refresh of news data (bypasses cache TTL)."""
    try:
        await get_economic_calendar(force_refresh=True)
        articles = await get_news_feed(category=category, force_refresh=True)
        return {
            "message": f"Refreshed calendar and {category} news",
            "articles_count": len(articles),
        }
    except Exception as e:
        _log.error("Manual fetch failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── AI Analysis ──────────────────────────────────────────────────────────────

@router.post("/articles/{article_id}/analyze")
async def analyze_news_article(
    article_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Run AI analysis on a news article using the user's configured LLM.
    Returns structured trading analysis with key points, impact assessment,
    affected symbols, and a recommendation.
    """
    analysis = await analyze_article(db, user.id, article_id)
    if analysis is None:
        raise HTTPException(
            status_code=400,
            detail="Analysis failed — check that LLM is configured in Settings",
        )
    return {"article_id": article_id, "analysis": analysis}


@router.post("/batch-sentiment")
async def batch_sentiment_endpoint(
    body: BatchSentimentRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Score sentiment for a batch of headlines using LLM.
    Returns list of {headline, score, label}.
    """
    results = await batch_sentiment(db, user.id, body.headlines)
    return {"results": results}


# ── News Providers ───────────────────────────────────────────────────────────

@router.get("/providers")
async def list_providers(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all configured news providers."""
    providers = db.query(NewsProvider).all()
    return {
        "providers": [
            {
                "id": p.id,
                "name": p.name,
                "provider_type": p.provider_type,
                "base_url": p.base_url,
                "enabled": p.enabled,
                "config": p.config or {},
                "has_api_key": bool(p.api_key),
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in providers
        ]
    }


@router.post("/providers")
async def create_provider(
    body: ProviderCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a new news provider configuration."""
    provider = NewsProvider(
        name=body.name,
        provider_type=body.provider_type,
        api_key=body.api_key,
        base_url=body.base_url,
        enabled=body.enabled,
        config=body.config,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return {"id": provider.id, "name": provider.name, "message": "Provider created"}


@router.put("/providers/{provider_id}")
async def update_provider(
    provider_id: int,
    body: ProviderUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a news provider configuration."""
    provider = db.query(NewsProvider).filter(NewsProvider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    if body.name is not None:
        provider.name = body.name
    if body.api_key is not None:
        provider.api_key = body.api_key
    if body.base_url is not None:
        provider.base_url = body.base_url
    if body.enabled is not None:
        provider.enabled = body.enabled
    if body.config is not None:
        provider.config = body.config

    db.commit()
    return {"id": provider.id, "message": "Provider updated"}


@router.delete("/providers/{provider_id}")
async def delete_provider(
    provider_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a news provider."""
    provider = db.query(NewsProvider).filter(NewsProvider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    db.delete(provider)
    db.commit()
    return {"message": "Provider deleted"}
