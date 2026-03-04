"""News & economic calendar models for caching API data."""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Index

from app.core.database import Base


class EconomicEvent(Base):
    """Cached economic calendar event from Finnhub."""
    __tablename__ = "economic_events"

    id = Column(Integer, primary_key=True, index=True)
    event = Column(String(300), nullable=False)           # e.g. "Nonfarm Payrolls"
    country = Column(String(10), default="")               # e.g. "US"
    currency = Column(String(10), default="")              # e.g. "USD"
    impact = Column(String(20), default="low")             # low / medium / high
    event_time = Column(DateTime, nullable=False)          # When the event is released
    actual = Column(Float, nullable=True)
    estimate = Column(Float, nullable=True)
    prev = Column(Float, nullable=True)
    unit = Column(String(20), default="")                  # e.g. "%", "K"
    source = Column(String(50), default="finnhub")
    fetched_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_econ_event_time", "event_time"),
        Index("ix_econ_currency", "currency"),
    )


class NewsArticle(Base):
    """Cached news article from Finnhub / Alpha Vantage."""
    __tablename__ = "news_articles"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(100), nullable=True, unique=True)  # Dedupe key
    headline = Column(String(500), nullable=False)
    summary = Column(Text, default="")
    source = Column(String(100), default="")
    url = Column(String(1000), default="")
    image_url = Column(String(1000), default="")
    category = Column(String(50), default="general")       # general / forex / crypto
    published_at = Column(DateTime, nullable=False)
    # Sentiment
    sentiment_score = Column(Float, nullable=True)          # -1.0 to 1.0
    sentiment_label = Column(String(30), nullable=True)     # Bearish / Neutral / Bullish
    # Related symbols
    related_symbols = Column(String(500), default="")       # Comma-separated: "XAUUSD,EURUSD"
    fetched_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_news_published", "published_at"),
        Index("ix_news_category", "category"),
    )
