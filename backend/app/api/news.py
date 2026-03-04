"""
News API endpoints — economic calendar, market news, and sentiment.

Endpoints:
  GET /api/news/calendar         — upcoming economic events
  GET /api/news/feed             — market news articles
  GET /api/news/sentiment/{sym}  — sentiment summary for a symbol
  GET /api/news/overview         — combined dashboard widget data
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from app.core.auth import get_current_user
from app.models.user import User
from app.services.news.aggregator import (
    get_economic_calendar,
    get_news_feed,
    get_sentiment,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/news", tags=["news"])


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
