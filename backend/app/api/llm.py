"""LLM API routes — chat, conversations, memories, usage stats."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User
from app.models.llm import LLMConversation, LLMMemory, LLMUsage
from app.schemas.llm import (
    ChatRequest,
    ChatResponse,
    ConversationSummary,
    ConversationDetail,
    ConversationList,
    ChatMessage,
    MemoryItem,
    MemoryUpdate,
    MemoryList,
    UsageStats,
    MLActionRequest,
    MLActionPlan,
)
from app.services.llm.service import LLMService
from app.services.llm.tools import interpret_ml_request, get_ml_context_for_chat

router = APIRouter(prefix="/api/llm", tags=["llm"])


# ─── Chat ────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send a message and get a response (non-streaming)."""
    try:
        result = await LLMService.chat(
            db=db,
            user_id=current_user.id,
            message=payload.message,
            conversation_id=payload.conversation_id,
            page_context=payload.page_context or "",
            context_data=payload.context_data,
        )
        return ChatResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM error: {str(e)[:300]}")


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send a message and stream the response (SSE)."""
    try:
        generator = LLMService.stream_chat(
            db=db,
            user_id=current_user.id,
            message=payload.message,
            conversation_id=payload.conversation_id,
            page_context=payload.page_context or "",
            context_data=payload.context_data,
        )
        return StreamingResponse(
            generator,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM error: {str(e)[:300]}")


# ─── Conversations ───────────────────────────────────────────────────

@router.get("/conversations", response_model=ConversationList)
def list_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all conversations for current user, newest first."""
    convos = (
        db.query(LLMConversation)
        .filter(LLMConversation.user_id == current_user.id)
        .order_by(LLMConversation.updated_at.desc())
        .all()
    )
    items = []
    for c in convos:
        items.append(ConversationSummary(
            id=c.id,
            title=c.title or "New Chat",
            page_context=c.page_context or "",
            message_count=len(c.messages or []),
            created_at=c.created_at.isoformat() if c.created_at else "",
            updated_at=c.updated_at.isoformat() if c.updated_at else "",
        ))
    return ConversationList(items=items, total=len(items))


@router.get("/conversations/{conv_id}", response_model=ConversationDetail)
def get_conversation(
    conv_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single conversation with all messages."""
    convo = db.query(LLMConversation).filter(
        LLMConversation.id == conv_id,
        LLMConversation.user_id == current_user.id,
    ).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = [ChatMessage(**m) for m in (convo.messages or [])]
    return ConversationDetail(
        id=convo.id,
        title=convo.title or "New Chat",
        page_context=convo.page_context or "",
        messages=messages,
        created_at=convo.created_at.isoformat() if convo.created_at else "",
        updated_at=convo.updated_at.isoformat() if convo.updated_at else "",
    )


@router.delete("/conversations/{conv_id}")
def delete_conversation(
    conv_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a conversation and its usage records."""
    convo = db.query(LLMConversation).filter(
        LLMConversation.id == conv_id,
        LLMConversation.user_id == current_user.id,
    ).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    db.query(LLMUsage).filter(LLMUsage.conversation_id == conv_id).delete()
    db.delete(convo)
    db.commit()
    return {"status": "ok"}


# ─── Memories ────────────────────────────────────────────────────────

@router.get("/memories", response_model=MemoryList)
def list_memories(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all memories for current user."""
    mems = (
        db.query(LLMMemory)
        .filter(LLMMemory.user_id == current_user.id)
        .order_by(LLMMemory.category, LLMMemory.key)
        .all()
    )
    items = [
        MemoryItem(
            id=m.id,
            key=m.key,
            value=m.value,
            category=m.category,
            confidence=m.confidence,
            pinned=bool(m.pinned),
            created_at=m.created_at.isoformat() if m.created_at else "",
            updated_at=m.updated_at.isoformat() if m.updated_at else "",
        )
        for m in mems
    ]
    return MemoryList(items=items, total=len(items))


@router.put("/memories/{mem_id}", response_model=MemoryItem)
def update_memory(
    mem_id: int,
    payload: MemoryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a memory (value, category, or pinned status)."""
    mem = db.query(LLMMemory).filter(
        LLMMemory.id == mem_id,
        LLMMemory.user_id == current_user.id,
    ).first()
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")

    data = payload.model_dump(exclude_none=True)
    if "pinned" in data:
        data["pinned"] = int(data["pinned"])
    for k, v in data.items():
        setattr(mem, k, v)
    db.commit()
    db.refresh(mem)

    return MemoryItem(
        id=mem.id,
        key=mem.key,
        value=mem.value,
        category=mem.category,
        confidence=mem.confidence,
        pinned=bool(mem.pinned),
        created_at=mem.created_at.isoformat() if mem.created_at else "",
        updated_at=mem.updated_at.isoformat() if mem.updated_at else "",
    )


@router.delete("/memories/{mem_id}")
def delete_memory(
    mem_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a memory."""
    mem = db.query(LLMMemory).filter(
        LLMMemory.id == mem_id,
        LLMMemory.user_id == current_user.id,
    ).first()
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")
    db.delete(mem)
    db.commit()
    return {"status": "ok"}


# ─── Usage ───────────────────────────────────────────────────────────

@router.get("/usage", response_model=UsageStats)
def get_usage_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get aggregated usage statistics."""
    user_id = current_user.id

    total_conversations = db.query(func.count(LLMConversation.id)).filter(
        LLMConversation.user_id == user_id
    ).scalar() or 0

    # Count total messages across all conversations
    convos = db.query(LLMConversation).filter(LLMConversation.user_id == user_id).all()
    total_messages = sum(len(c.messages or []) for c in convos)

    # Usage aggregation
    usage_rows = db.query(LLMUsage).filter(LLMUsage.user_id == user_id).all()
    total_tokens_in = sum(u.tokens_in for u in usage_rows)
    total_tokens_out = sum(u.tokens_out for u in usage_rows)
    total_cost = sum(u.cost_estimate for u in usage_rows)

    # Provider breakdown
    breakdown: dict = {}
    for u in usage_rows:
        p = u.provider
        if p not in breakdown:
            breakdown[p] = {"tokens_in": 0, "tokens_out": 0, "cost": 0.0, "calls": 0}
        breakdown[p]["tokens_in"] += u.tokens_in
        breakdown[p]["tokens_out"] += u.tokens_out
        breakdown[p]["cost"] += u.cost_estimate
        breakdown[p]["calls"] += 1

    return UsageStats(
        total_conversations=total_conversations,
        total_messages=total_messages,
        total_tokens_in=total_tokens_in,
        total_tokens_out=total_tokens_out,
        total_cost_estimate=round(total_cost, 4),
        provider_breakdown=breakdown,
    )


# ─── ML Action (LLM-driven training) ────────────────────────────────

@router.post("/ml-action", response_model=MLActionPlan)
async def ml_action(
    payload: MLActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Interpret a natural language ML training request using the LLM.
    Returns a structured plan that the frontend shows for user confirmation.
    The user then confirms and triggers /api/ml/train with the plan parameters.
    """
    try:
        plan = await interpret_ml_request(
            db=db,
            user_id=current_user.id,
            user_prompt=payload.prompt,
        )
        return MLActionPlan(**plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("ML action interpretation failed")
        raise HTTPException(status_code=500, detail=f"AI interpretation failed: {str(e)[:300]}")


@router.get("/ml-context")
async def get_ml_context(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get ML page context data for the ChatSidebar."""
    return get_ml_context_for_chat(db, current_user.id)
