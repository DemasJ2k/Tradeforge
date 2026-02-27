"""Pydantic schemas for LLM chat, conversations, memories, and usage."""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel


# ─── Chat ────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str  # user, assistant, system
    content: str
    timestamp: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[int] = None  # None = start new conversation
    page_context: Optional[str] = ""  # which page the user is on
    context_data: Optional[dict] = None  # injected page-specific data


class ChatResponse(BaseModel):
    reply: str
    conversation_id: int
    title: str
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""


# ─── Conversations ───────────────────────────────────────────────────

class ConversationSummary(BaseModel):
    id: int
    title: str
    page_context: str
    message_count: int
    created_at: str
    updated_at: str


class ConversationDetail(BaseModel):
    id: int
    title: str
    page_context: str
    messages: list[ChatMessage]
    created_at: str
    updated_at: str


class ConversationList(BaseModel):
    items: list[ConversationSummary]
    total: int


# ─── Memories ────────────────────────────────────────────────────────

class MemoryItem(BaseModel):
    id: int
    key: str
    value: str
    category: str
    confidence: float
    pinned: bool
    created_at: str
    updated_at: str


class MemoryUpdate(BaseModel):
    value: Optional[str] = None
    category: Optional[str] = None
    pinned: Optional[bool] = None


class MemoryList(BaseModel):
    items: list[MemoryItem]
    total: int


# ─── Usage ───────────────────────────────────────────────────────────

class UsageStats(BaseModel):
    total_conversations: int
    total_messages: int
    total_tokens_in: int
    total_tokens_out: int
    total_cost_estimate: float
    provider_breakdown: dict  # {provider: {tokens_in, tokens_out, cost, calls}}


# ─── ML Action (LLM-driven training) ────────────────────────────────

class MLActionRequest(BaseModel):
    prompt: str  # Natural language description of what to train


class MLActionPlan(BaseModel):
    action: str  # "train" or "clarify"
    name: str = ""
    level: int = 2
    model_type: str = "xgboost"
    datasource_id: int = 0
    datasource_name: str = ""
    datasource_info: str = ""
    symbol: str = ""
    timeframe: str = "H1"
    target_type: str = "direction"
    target_horizon: int = 1
    features: list[str] = []
    n_estimators: int = 100
    max_depth: int = 10
    learning_rate: float = 0.1
    explanation: str = ""
    tokens_used: dict = {}
