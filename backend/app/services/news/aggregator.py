"""
News aggregator — fetches, caches, and serves news data.

In-memory cache with DB persistence for economic calendar and news articles.
Background refresh runs on a timer to stay within API rate limits.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.news import EconomicEvent, NewsArticle
from app.services.news.provider import (
    fetch_economic_calendar,
    fetch_market_news,
    fetch_sentiment,
)

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------

_calendar_cache: list[dict] = []
_calendar_updated: Optional[datetime] = None

_news_cache: dict[str, list[dict]] = {}  # category -> articles
_news_updated: dict[str, datetime] = {}

_sentiment_cache: dict[str, dict] = {}  # symbol -> {score, label, articles, updated}

CALENDAR_TTL = timedelta(minutes=15)
NEWS_TTL = timedelta(minutes=10)
SENTIMENT_TTL = timedelta(minutes=60)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_economic_calendar(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    currency: Optional[str] = None,
    impact: Optional[str] = None,
    force_refresh: bool = False,
) -> list[dict]:
    """Get economic calendar events (cached)."""
    global _calendar_cache, _calendar_updated

    now = datetime.now(timezone.utc)
    if force_refresh or not _calendar_updated or (now - _calendar_updated) > CALENDAR_TTL:
        raw = await fetch_economic_calendar(from_date, to_date)
        if raw:
            _calendar_cache = _normalize_calendar(raw)
            _calendar_updated = now
            _persist_calendar(_calendar_cache)

    # If cache is still empty, try loading from DB
    if not _calendar_cache:
        _calendar_cache = _load_calendar_from_db(from_date, to_date)

    results = _calendar_cache

    # Apply filters
    if currency:
        cur_upper = currency.upper()
        results = [e for e in results if e.get("currency", "").upper() == cur_upper]
    if impact:
        imp_lower = impact.lower()
        results = [e for e in results if e.get("impact", "").lower() == imp_lower]

    return results


async def get_news_feed(
    category: str = "general",
    symbol: Optional[str] = None,
    limit: int = 50,
    force_refresh: bool = False,
) -> list[dict]:
    """Get market news articles (cached)."""
    now = datetime.now(timezone.utc)
    last = _news_updated.get(category)

    if force_refresh or not last or (now - last) > NEWS_TTL:
        raw = await fetch_market_news(category)
        if raw:
            _news_cache[category] = _normalize_news(raw)
            _news_updated[category] = now
            _persist_news(_news_cache[category])

    articles = _news_cache.get(category, [])

    # If empty, try DB
    if not articles:
        articles = _load_news_from_db(category)
        if articles:
            _news_cache[category] = articles

    # Filter by symbol if provided
    if symbol:
        sym_upper = symbol.upper()
        articles = [
            a for a in articles
            if sym_upper in (a.get("related_symbols", "") or "").upper()
            or sym_upper in (a.get("headline", "") or "").upper()
        ]

    return articles[:limit]


async def get_sentiment(symbol: str, force_refresh: bool = False) -> dict:
    """Get aggregated sentiment for a symbol."""
    now = datetime.now(timezone.utc)
    cached = _sentiment_cache.get(symbol.upper())

    if force_refresh or not cached or (now - cached["updated"]) > SENTIMENT_TTL:
        raw = await fetch_sentiment(symbol)
        if raw:
            sentiment = _aggregate_sentiment(raw, symbol)
            _sentiment_cache[symbol.upper()] = {**sentiment, "updated": now}
        elif cached:
            return cached  # Return stale cache if refresh fails
        else:
            return {"score": 0.0, "label": "Neutral", "articles": 0, "symbol": symbol}

    return _sentiment_cache.get(symbol.upper(), {"score": 0.0, "label": "Neutral", "articles": 0, "symbol": symbol})


# ---------------------------------------------------------------------------
# Background refresh task
# ---------------------------------------------------------------------------

_refresh_task: Optional[asyncio.Task] = None


async def start_background_refresh():
    """Start background refresh loop for news data."""
    global _refresh_task
    if _refresh_task and not _refresh_task.done():
        return
    _refresh_task = asyncio.create_task(_refresh_loop())
    _log.info("News background refresh started")


async def stop_background_refresh():
    """Stop the background refresh loop."""
    global _refresh_task
    if _refresh_task and not _refresh_task.done():
        _refresh_task.cancel()
        try:
            await _refresh_task
        except asyncio.CancelledError:
            pass
    _refresh_task = None
    _log.info("News background refresh stopped")


async def _refresh_loop():
    """Periodically refresh calendar and news."""
    while True:
        try:
            _log.debug("News refresh cycle starting")
            # Refresh calendar
            await get_economic_calendar(force_refresh=True)
            # Refresh general + forex + crypto news
            for cat in ["general", "forex", "crypto"]:
                await get_news_feed(category=cat, force_refresh=True)
                await asyncio.sleep(1)  # Rate limit courtesy
            _log.debug("News refresh cycle complete")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _log.error("News refresh error: %s", e)
        await asyncio.sleep(600)  # Every 10 minutes


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def _normalize_calendar(raw: list[dict]) -> list[dict]:
    """Normalize Finnhub calendar events to our format."""
    events = []
    for r in raw:
        try:
            # Finnhub returns time as "HH:MM" and date as separate fields or combined
            event_time_str = r.get("time", "")
            event_date = r.get("date", "")
            if event_date and event_time_str:
                dt_str = f"{event_date}T{event_time_str}:00Z"
            elif event_date:
                dt_str = f"{event_date}T00:00:00Z"
            else:
                continue

            try:
                event_dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            except ValueError:
                event_dt = datetime.now(timezone.utc)

            # Map country to currency
            country = r.get("country", "")
            currency = _country_to_currency(country)

            events.append({
                "event": r.get("event", "Unknown"),
                "country": country,
                "currency": currency,
                "impact": _classify_impact(r.get("impact", "")),
                "event_time": event_dt.isoformat(),
                "actual": r.get("actual"),
                "estimate": r.get("estimate"),
                "prev": r.get("prev"),
                "unit": r.get("unit", ""),
                "source": "finnhub",
            })
        except Exception:
            continue

    # Sort by event_time
    events.sort(key=lambda e: e["event_time"])
    return events


def _normalize_news(raw: list[dict]) -> list[dict]:
    """Normalize Finnhub news articles to our format."""
    articles = []
    for r in raw:
        try:
            ts = r.get("datetime", 0)
            if isinstance(ts, (int, float)):
                pub_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            else:
                pub_dt = datetime.now(timezone.utc)

            articles.append({
                "external_id": str(r.get("id", "")),
                "headline": r.get("headline", ""),
                "summary": r.get("summary", ""),
                "source": r.get("source", ""),
                "url": r.get("url", ""),
                "image_url": r.get("image", ""),
                "category": r.get("category", "general"),
                "published_at": pub_dt.isoformat(),
                "related_symbols": r.get("related", ""),
                "sentiment_score": None,
                "sentiment_label": None,
            })
        except Exception:
            continue

    # Sort newest first
    articles.sort(key=lambda a: a["published_at"], reverse=True)
    return articles


def _aggregate_sentiment(raw: list[dict], symbol: str) -> dict:
    """Aggregate Alpha Vantage sentiment articles into a summary."""
    scores = []
    for article in raw:
        # Alpha Vantage has overall_sentiment_score
        score = article.get("overall_sentiment_score")
        if score is not None:
            try:
                scores.append(float(score))
            except (ValueError, TypeError):
                pass

    if not scores:
        return {"score": 0.0, "label": "Neutral", "articles": 0, "symbol": symbol}

    avg_score = sum(scores) / len(scores)
    if avg_score >= 0.15:
        label = "Bullish"
    elif avg_score <= -0.15:
        label = "Bearish"
    else:
        label = "Neutral"

    return {
        "score": round(avg_score, 4),
        "label": label,
        "articles": len(scores),
        "symbol": symbol,
        "bullish_pct": round(len([s for s in scores if s >= 0.15]) / len(scores) * 100, 1),
        "bearish_pct": round(len([s for s in scores if s <= -0.15]) / len(scores) * 100, 1),
    }


def _classify_impact(raw: str) -> str:
    """Classify event impact level."""
    if not raw:
        return "low"
    raw_lower = str(raw).lower()
    if raw_lower in ("high", "3", "red"):
        return "high"
    if raw_lower in ("medium", "2", "orange"):
        return "medium"
    return "low"


_COUNTRY_CURRENCY = {
    "US": "USD", "EU": "EUR", "GB": "GBP", "JP": "JPY",
    "AU": "AUD", "CA": "CAD", "NZ": "NZD", "CH": "CHF",
    "CN": "CNY", "DE": "EUR", "FR": "EUR", "IT": "EUR",
    "ES": "EUR", "IN": "INR", "BR": "BRL", "MX": "MXN",
    "KR": "KRW", "SG": "SGD", "HK": "HKD", "SE": "SEK",
    "NO": "NOK", "DK": "DKK", "PL": "PLN", "ZA": "ZAR",
    "TR": "TRY", "RU": "RUB",
}


def _country_to_currency(country: str) -> str:
    return _COUNTRY_CURRENCY.get(country.upper(), country.upper())


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------


def _persist_calendar(events: list[dict]):
    """Save calendar events to DB for persistence across restarts."""
    try:
        db: Session = SessionLocal()
        count = 0
        for e in events:
            try:
                event_dt = datetime.fromisoformat(e["event_time"])
            except Exception:
                continue

            # Upsert by event + event_time
            existing = db.query(EconomicEvent).filter(
                EconomicEvent.event == e["event"],
                EconomicEvent.event_time == event_dt,
            ).first()

            if existing:
                existing.actual = e.get("actual")
                existing.estimate = e.get("estimate")
                existing.prev = e.get("prev")
                existing.fetched_at = datetime.now(timezone.utc)
            else:
                db.add(EconomicEvent(
                    event=e["event"],
                    country=e.get("country", ""),
                    currency=e.get("currency", ""),
                    impact=e.get("impact", "low"),
                    event_time=event_dt,
                    actual=e.get("actual"),
                    estimate=e.get("estimate"),
                    prev=e.get("prev"),
                    unit=e.get("unit", ""),
                    source=e.get("source", "finnhub"),
                ))
                count += 1

        db.commit()
        if count:
            _log.info("Persisted %d new calendar events", count)
    except Exception as ex:
        _log.error("Calendar persist error: %s", ex)
        db.rollback()
    finally:
        db.close()


def _persist_news(articles: list[dict]):
    """Save news articles to DB."""
    try:
        db: Session = SessionLocal()
        count = 0
        for a in articles:
            ext_id = a.get("external_id", "")
            if not ext_id:
                continue

            existing = db.query(NewsArticle).filter(
                NewsArticle.external_id == ext_id
            ).first()

            if existing:
                continue  # Don't update existing articles

            try:
                pub_dt = datetime.fromisoformat(a["published_at"])
            except Exception:
                pub_dt = datetime.now(timezone.utc)

            db.add(NewsArticle(
                external_id=ext_id,
                headline=a.get("headline", ""),
                summary=a.get("summary", ""),
                source=a.get("source", ""),
                url=a.get("url", ""),
                image_url=a.get("image_url", ""),
                category=a.get("category", "general"),
                published_at=pub_dt,
                related_symbols=a.get("related_symbols", ""),
                sentiment_score=a.get("sentiment_score"),
                sentiment_label=a.get("sentiment_label"),
            ))
            count += 1

        db.commit()
        if count:
            _log.info("Persisted %d new news articles", count)
    except Exception as ex:
        _log.error("News persist error: %s", ex)
        db.rollback()
    finally:
        db.close()


def _load_calendar_from_db(from_date: Optional[str] = None, to_date: Optional[str] = None) -> list[dict]:
    """Load calendar from DB as fallback."""
    try:
        db: Session = SessionLocal()
        q = db.query(EconomicEvent)

        now = datetime.now(timezone.utc)
        if from_date:
            try:
                q = q.filter(EconomicEvent.event_time >= datetime.fromisoformat(from_date))
            except Exception:
                pass
        else:
            q = q.filter(EconomicEvent.event_time >= now - timedelta(days=1))

        if to_date:
            try:
                q = q.filter(EconomicEvent.event_time <= datetime.fromisoformat(to_date))
            except Exception:
                pass
        else:
            q = q.filter(EconomicEvent.event_time <= now + timedelta(days=7))

        events = q.order_by(EconomicEvent.event_time).limit(500).all()
        return [
            {
                "event": e.event,
                "country": e.country,
                "currency": e.currency,
                "impact": e.impact,
                "event_time": e.event_time.isoformat() if e.event_time else "",
                "actual": e.actual,
                "estimate": e.estimate,
                "prev": e.prev,
                "unit": e.unit,
                "source": e.source,
            }
            for e in events
        ]
    except Exception as ex:
        _log.error("Calendar DB load error: %s", ex)
        return []
    finally:
        db.close()


def _load_news_from_db(category: str) -> list[dict]:
    """Load news from DB as fallback."""
    try:
        db: Session = SessionLocal()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        articles = (
            db.query(NewsArticle)
            .filter(NewsArticle.category == category, NewsArticle.published_at >= cutoff)
            .order_by(NewsArticle.published_at.desc())
            .limit(100)
            .all()
        )
        return [
            {
                "external_id": a.external_id,
                "headline": a.headline,
                "summary": a.summary,
                "source": a.source,
                "url": a.url,
                "image_url": a.image_url,
                "category": a.category,
                "published_at": a.published_at.isoformat() if a.published_at else "",
                "related_symbols": a.related_symbols,
                "sentiment_score": a.sentiment_score,
                "sentiment_label": a.sentiment_label,
            }
            for a in articles
        ]
    except Exception as ex:
        _log.error("News DB load error: %s", ex)
        return []
    finally:
        db.close()
