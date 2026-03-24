"""
NewsAPI.org provider — general market news + pre-trade news filter.

Provides:
  1. Market news fetching with keyword search
  2. High-impact news detection (NFP, FOMC, CPI, etc.)
  3. Pre-trade news filter: avoid entries near high-impact events
  4. Sentiment scoring from news headlines

Uses NewsAPI.org free tier (100 requests/day, 1-month history).
"""

import logging
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.core.config import settings

_log = logging.getLogger(__name__)

NEWSAPI_BASE = "https://newsapi.org/v2"

# Keywords that indicate high-impact events per symbol
HIGH_IMPACT_KEYWORDS = {
    "XAUUSD": [
        "federal reserve", "fomc", "interest rate", "nonfarm payroll", "nfp",
        "cpi", "inflation", "gold", "bullion", "precious metal",
        "treasury", "bond yield", "real yield", "dollar index", "dxy",
        "geopolitical", "war", "sanctions", "central bank",
    ],
    "US30": [
        "federal reserve", "fomc", "interest rate", "nonfarm payroll", "nfp",
        "cpi", "inflation", "gdp", "unemployment", "dow jones",
        "wall street", "stock market", "earnings", "recession",
        "trade war", "tariff", "fiscal policy", "debt ceiling",
    ],
    "ES": [
        "federal reserve", "fomc", "interest rate", "nonfarm payroll", "nfp",
        "cpi", "inflation", "gdp", "unemployment", "s&p 500", "s&p500",
        "wall street", "stock market", "earnings", "recession",
        "trade war", "tariff", "fiscal policy", "debt ceiling",
    ],
    "NAS100": [
        "federal reserve", "fomc", "interest rate", "nonfarm payroll", "nfp",
        "cpi", "inflation", "gdp", "nasdaq", "tech stocks", "technology",
        "wall street", "earnings", "recession", "semiconductor",
        "trade war", "tariff", "fiscal policy", "debt ceiling",
    ],
    "BTCUSD": [
        "bitcoin", "crypto", "cryptocurrency", "sec", "regulation",
        "etf", "halving", "blockchain", "binance", "coinbase",
        "stablecoin", "tether", "defi", "mining", "whale",
        "federal reserve", "interest rate", "risk appetite",
    ],
}

# Generic high-impact event keywords (affect all symbols)
GENERIC_HIGH_IMPACT = [
    "fomc", "federal reserve", "interest rate decision",
    "nonfarm payroll", "nfp", "jobs report",
    "cpi", "consumer price index", "inflation data",
    "gdp", "gross domestic product",
    "ecb", "bank of england", "bank of japan",
    "geopolitical", "war", "nuclear", "crisis",
]


async def fetch_market_news(
    query: Optional[str] = None,
    symbol: Optional[str] = None,
    hours_back: int = 24,
    page_size: int = 20,
) -> list[dict]:
    """
    Fetch market news from NewsAPI.org.

    Args:
        query: search query (e.g. "gold federal reserve")
        symbol: trading symbol to auto-generate relevant query
        hours_back: how far back to search (max 720h for free tier)
        page_size: max articles to return (max 100)

    Returns:
        List of article dicts with: title, description, publishedAt, source, url, content
    """
    api_key = settings.NEWSAPI_ORG_KEY
    if not api_key:
        _log.warning("NEWSAPI_ORG_KEY not set — skipping news fetch")
        return []

    # Auto-generate query from symbol if not provided
    if not query and symbol:
        query = _symbol_to_query(symbol)

    if not query:
        query = "financial markets economy"

    from_time = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).isoformat()

    params = {
        "q": query,
        "from": from_time,
        "sortBy": "publishedAt",
        "pageSize": min(page_size, 100),
        "language": "en",
        "apiKey": api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{NEWSAPI_BASE}/everything", params=params)
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "ok":
                _log.warning("NewsAPI error: %s", data.get("message", "unknown"))
                return []

            articles = data.get("articles", [])
            _log.info("NewsAPI: %d articles for query '%s'", len(articles), query[:50])
            return articles

    except Exception as e:
        _log.error("NewsAPI fetch error: %s", e)
        return []


async def fetch_top_headlines(
    category: str = "business",
    country: str = "us",
    page_size: int = 10,
) -> list[dict]:
    """Fetch top headlines for business/general category."""
    api_key = settings.NEWSAPI_ORG_KEY
    if not api_key:
        return []

    params = {
        "category": category,
        "country": country,
        "pageSize": min(page_size, 100),
        "apiKey": api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{NEWSAPI_BASE}/top-headlines", params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("articles", []) if data.get("status") == "ok" else []
    except Exception as e:
        _log.error("NewsAPI headlines error: %s", e)
        return []


# ── Pre-Trade News Filter ─────────────────────────────

async def check_high_impact_news(
    symbol: str,
    window_minutes: int = 15,
) -> dict:
    """
    Check if there's high-impact news near the current time that should
    prevent trading.

    Expert traders avoid entering positions ±15 minutes around
    major news events (NFP, FOMC, CPI, etc.).

    Args:
        symbol: trading symbol (XAUUSD, US30, BTCUSD)
        window_minutes: how far ahead/behind to check

    Returns:
        {
            "should_trade": bool,
            "reason": str,
            "high_impact_count": int,
            "recent_articles": list[str],  # headlines
        }
    """
    # Fetch recent news
    articles = await fetch_market_news(
        symbol=symbol,
        hours_back=2,
        page_size=30,
    )

    if not articles:
        return {
            "should_trade": True,
            "reason": "No recent news data available",
            "high_impact_count": 0,
            "recent_articles": [],
        }

    now = datetime.now(timezone.utc)
    window = timedelta(minutes=window_minutes)

    # Check for high-impact articles published very recently
    keywords = HIGH_IMPACT_KEYWORDS.get(symbol.upper(), []) + GENERIC_HIGH_IMPACT
    high_impact_articles = []

    for article in articles:
        pub_str = article.get("publishedAt", "")
        try:
            pub_time = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue

        # Only check articles within the window
        time_diff = abs((now - pub_time).total_seconds())
        if time_diff > window_minutes * 60:
            continue

        # Check if headline/description contains high-impact keywords
        title = (article.get("title") or "").lower()
        desc = (article.get("description") or "").lower()
        text = f"{title} {desc}"

        for kw in keywords:
            if kw in text:
                high_impact_articles.append(article.get("title", "Unknown"))
                break

    if high_impact_articles:
        return {
            "should_trade": False,
            "reason": f"High-impact news detected: {high_impact_articles[0][:80]}",
            "high_impact_count": len(high_impact_articles),
            "recent_articles": high_impact_articles[:5],
        }

    return {
        "should_trade": True,
        "reason": "No high-impact news in window",
        "high_impact_count": 0,
        "recent_articles": [a.get("title", "") for a in articles[:3]],
    }


# ── Sentiment Scoring ─────────────────────────────────

def score_headlines_sentiment(articles: list[dict]) -> float:
    """
    Simple keyword-based sentiment scoring of news headlines.

    Returns score between -1.0 (very bearish) and +1.0 (very bullish).
    0.0 = neutral.
    """
    if not articles:
        return 0.0

    BULLISH_WORDS = {
        "surge", "rally", "soar", "jump", "gain", "rise", "climb",
        "bullish", "breakout", "record high", "all-time high", "buy",
        "strong", "growth", "recovery", "boom", "positive", "upgrade",
        "optimism", "beat", "exceed", "outperform",
    }
    BEARISH_WORDS = {
        "crash", "plunge", "tumble", "drop", "fall", "decline", "sink",
        "bearish", "breakdown", "record low", "sell-off", "selloff",
        "weak", "recession", "crisis", "collapse", "negative", "downgrade",
        "pessimism", "miss", "disappoint", "underperform", "fear",
    }

    total_score = 0.0
    count = 0

    for article in articles:
        title = (article.get("title") or "").lower()
        desc = (article.get("description") or "").lower()
        text = f"{title} {desc}"

        bull_count = sum(1 for w in BULLISH_WORDS if w in text)
        bear_count = sum(1 for w in BEARISH_WORDS if w in text)

        if bull_count + bear_count > 0:
            score = (bull_count - bear_count) / (bull_count + bear_count)
            total_score += score
            count += 1

    return total_score / max(count, 1)


# ── Helpers ───────────────────────────────────────────

def _symbol_to_query(symbol: str) -> str:
    """Map trading symbol to a relevant NewsAPI search query."""
    mapping = {
        "XAUUSD": "gold OR bullion OR precious metals OR federal reserve",
        "XAGUSD": "silver OR precious metals",
        "US30": "dow jones OR wall street OR stock market OR economy",
        "ES": "s&p 500 OR wall street OR stock market OR economy",
        "NAS100": "nasdaq OR tech stocks OR technology sector",
        "US100": "nasdaq OR tech stocks OR technology sector",
        "BTCUSD": "bitcoin OR cryptocurrency OR crypto",
        "ETHUSD": "ethereum OR cryptocurrency OR crypto",
        "EURUSD": "euro OR european central bank OR ecb",
        "GBPUSD": "british pound OR bank of england",
    }
    return mapping.get(symbol.upper(), f"{symbol} financial markets")
