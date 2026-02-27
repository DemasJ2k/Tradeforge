"""LLM-related database models: conversations, memories, usage tracking."""

from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Text, Float

from app.core.database import Base


class LLMConversation(Base):
    """Stores chat conversations between users and the AI assistant."""
    __tablename__ = "llm_conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), default="New Chat")
    page_context = Column(String(50), default="")  # strategies, backtest, chart, etc.
    messages = Column(JSON, default=list)  # [{role, content, timestamp}]
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class LLMMemory(Base):
    """Structured user profile memories auto-extracted from conversations."""
    __tablename__ = "llm_memories"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    key = Column(String(100), nullable=False)  # e.g. "trading_style", "risk_tolerance"
    value = Column(Text, nullable=False)
    category = Column(String(50), default="general")  # profile, preference, goal, instrument, note
    confidence = Column(Float, default=0.8)  # 0.0 to 1.0
    pinned = Column(Integer, default=0)  # 1 = user-pinned, won't auto-update
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class LLMUsage(Base):
    """Token usage and cost tracking per API call."""
    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    conversation_id = Column(Integer, ForeignKey("llm_conversations.id"), nullable=True)
    provider = Column(String(20), nullable=False)  # claude, openai, gemini
    model = Column(String(50), nullable=False)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost_estimate = Column(Float, default=0.0)  # USD
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
