"""
News data providers — Finnhub (calendar + news) & Alpha Vantage (sentiment).

Caching strategy:
- Economic calendar: refresh every 15 min, store in DB
- Market news: refresh every 10 min, store in DB
- Sentiment: refresh every 60 min (25 req/day budget)
"""

import logging
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.core.config import settings

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Finnhub
# ---------------------------------------------------------------------------

FINNHUB_BASE = "https://finnhub.io/api/v1"


async def fetch_economic_calendar(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> list[dict]:
    """
    Fetch economic calendar from Finnhub.
    Returns list of dicts with keys: event, country, actual, estimate, prev,
    time, unit, impact, currency.
    """
    api_key = settings.FINNHUB_API_KEY
    if not api_key:
        _log.warning("FINNHUB_API_KEY not set — skipping economic calendar fetch")
        return []

    now = datetime.now(timezone.utc)
    if not from_date:
        from_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    if not to_date:
        to_date = (now + timedelta(days=7)).strftime("%Y-%m-%d")

    url = f"{FINNHUB_BASE}/calendar/economic"
    params = {"from": from_date, "to": to_date, "token": api_key}

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            events = data.get("economicCalendar", [])
            _log.info("Finnhub economic calendar: %d events (%s to %s)", len(events), from_date, to_date)
            return events
    except Exception as e:
        _log.error("Finnhub economic calendar error: %s", e)
        return []


async def fetch_market_news(category: str = "general") -> list[dict]:
    """
    Fetch market news from Finnhub.
    Categories: general, forex, crypto, merger.
    Returns list of dicts with: id, category, datetime, headline, summary,
    source, url, image, related.
    """
    api_key = settings.FINNHUB_API_KEY
    if not api_key:
        _log.warning("FINNHUB_API_KEY not set — skipping news fetch")
        return []

    url = f"{FINNHUB_BASE}/news"
    params = {"category": category, "token": api_key}

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            articles = resp.json()
            _log.info("Finnhub news (%s): %d articles", category, len(articles))
            return articles if isinstance(articles, list) else []
    except Exception as e:
        _log.error("Finnhub news error: %s", e)
        return []


# ---------------------------------------------------------------------------
# Alpha Vantage — Sentiment
# ---------------------------------------------------------------------------

AV_BASE = "https://www.alphavantage.co/query"

# Map our symbols to Alpha Vantage ticker format
_AV_TICKER_MAP = {
    "XAUUSD": "FOREX:XAU",
    "XAGUSD": "FOREX:XAG",
    "EURUSD": "FOREX:EUR",
    "GBPUSD": "FOREX:GBP",
    "USDJPY": "FOREX:JPY",
    "AUDUSD": "FOREX:AUD",
    "USDCAD": "FOREX:CAD",
    "BTCUSD": "CRYPTO:BTC",
    "ETHUSD": "CRYPTO:ETH",
    "US30": "DIA",
    "US100": "QQQ",
    "US500": "SPY",
    "NAS100": "QQQ",
    "SPY": "SPY",
    "DIA": "DIA",
    "QQQ": "QQQ",
}


async def fetch_sentiment(symbol: str) -> list[dict]:
    """
    Fetch news + sentiment from Alpha Vantage for a given symbol.
    Returns list of article dicts with sentiment scores.
    Budget: ~25 req/day — caller should cache aggressively.
    """
    api_key = settings.ALPHAVANTAGE_API_KEY
    if not api_key:
        _log.warning("ALPHAVANTAGE_API_KEY not set — skipping sentiment fetch")
        return []

    ticker = _AV_TICKER_MAP.get(symbol.upper(), symbol.upper())
    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": ticker,
        "sort": "LATEST",
        "limit": "50",
        "apikey": api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(AV_BASE, params=params)
            resp.raise_for_status()
            data = resp.json()
            if "feed" not in data:
                _log.warning("Alpha Vantage sentiment: no feed in response for %s: %s",
                             symbol, str(data)[:200])
                return []
            articles = data["feed"]
            _log.info("Alpha Vantage sentiment for %s: %d articles", symbol, len(articles))
            return articles
    except Exception as e:
        _log.error("Alpha Vantage sentiment error for %s: %s", symbol, e)
        return []
