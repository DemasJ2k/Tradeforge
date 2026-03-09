"""LLM Service — orchestrates providers, conversations, memories, and context.

Responsibilities:
  1. Load user's LLM settings (provider, key, model, temperature)
  2. Build system prompt with user memories + page context
  3. Manage conversation history (create / append / retrieve)
  4. Track token usage and cost
  5. Auto-generate conversation titles
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from sqlalchemy.orm import Session

from app.core.encryption import decrypt_value
from app.models.settings import UserSettings
from app.models.llm import LLMConversation, LLMMemory, LLMUsage
from app.services.llm.providers import get_provider, estimate_cost


# ── System prompt template ──

BASE_SYSTEM_PROMPT = """You are FlowrexAlgo AI, an expert trading assistant embedded in a trading platform.

Your capabilities:
- Explain trading concepts, indicators, and strategies
- Help build and review trading strategies
- Analyze backtest results and suggest improvements
- Guide optimization parameter selection
- Discuss risk management best practices
- Answer questions about the platform's features

Communication style:
- Be concise but thorough
- Use trading terminology naturally
- Provide actionable advice
- Reference specific numbers and data when available
- Format responses with markdown (headers, lists, code blocks, tables)

{user_profile}

{page_context}

{custom_instructions}"""


def _build_system_prompt(
    memories: list[LLMMemory],
    page_context: str,
    context_data: Optional[dict],
    custom_instructions: str,
) -> str:
    """Build a system prompt enriched with user memories and page context."""
    # User profile from memories
    profile_lines = []
    for mem in memories:
        profile_lines.append(f"- {mem.key}: {mem.value}")
    user_profile = ""
    if profile_lines:
        user_profile = "Known about this user:\n" + "\n".join(profile_lines)

    # Page context
    ctx_section = ""
    if page_context:
        ctx_section = f"The user is currently on the '{page_context}' page."
        if context_data:
            ctx_parts = []
            for k, v in context_data.items():
                if isinstance(v, dict):
                    ctx_parts.append(f"\n{k}:")
                    for sk, sv in v.items():
                        ctx_parts.append(f"  {sk}: {sv}")
                elif isinstance(v, list):
                    ctx_parts.append(f"\n{k}: {len(v)} items")
                else:
                    ctx_parts.append(f"\n{k}: {v}")
            ctx_section += "\n\nPage data:" + "".join(ctx_parts)

    custom_section = ""
    if custom_instructions:
        custom_section = f"Additional instructions from user:\n{custom_instructions}"

    return BASE_SYSTEM_PROMPT.format(
        user_profile=user_profile,
        page_context=ctx_section,
        custom_instructions=custom_section,
    ).strip()


class LLMService:
    """High-level interface for AI assistant features."""

    @staticmethod
    def _get_settings(db: Session, user_id: int) -> UserSettings:
        s = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
        if not s:
            s = UserSettings(user_id=user_id)

        # If user doesn't have their own key, fall back to platform-level key
        if not s.llm_api_key_encrypted:
            from app.core.config import settings as app_settings
            from app.core.encryption import encrypt_value
            platform_key = app_settings.PLATFORM_LLM_API_KEY
            if not platform_key:
                raise ValueError("LLM not configured. Please set your API key in Settings → AI / LLM.")
            s.llm_api_key_encrypted = encrypt_value(platform_key)
            s.llm_provider = s.llm_provider or "claude"
            s.llm_model = s.llm_model or "claude-sonnet-4-20250514"

        if not s.llm_provider:
            s.llm_provider = "claude"
        return s

    @staticmethod
    async def chat(
        db: Session,
        user_id: int,
        message: str,
        conversation_id: Optional[int],
        page_context: str = "",
        context_data: Optional[dict] = None,
    ) -> dict:
        """Send a message and get a response. Returns dict with reply + metadata."""
        settings = LLMService._get_settings(db, user_id)
        api_key = decrypt_value(settings.llm_api_key_encrypted)
        provider_name = settings.llm_provider
        model = settings.llm_model
        temperature = float(settings.llm_temperature or "0.7")
        max_tokens = int(settings.llm_max_tokens or "4096")
        custom_prompt = settings.llm_system_prompt or ""

        # Load user memories
        memories = db.query(LLMMemory).filter(LLMMemory.user_id == user_id).all()

        # Build system prompt
        system_prompt = _build_system_prompt(memories, page_context, context_data, custom_prompt)

        # Load or create conversation
        if conversation_id:
            convo = db.query(LLMConversation).filter(
                LLMConversation.id == conversation_id,
                LLMConversation.user_id == user_id,
            ).first()
            if not convo:
                raise ValueError("Conversation not found")
        else:
            convo = LLMConversation(
                user_id=user_id,
                page_context=page_context,
                messages=[],
                title="New Chat",
            )
            db.add(convo)
            db.commit()
            db.refresh(convo)

        # Add user message to history
        now_str = datetime.now(timezone.utc).isoformat()
        msgs = list(convo.messages or [])
        msgs.append({"role": "user", "content": message, "timestamp": now_str})

        # Prepare messages for provider (limit context window to last N messages)
        MAX_HISTORY = 30
        api_messages = msgs[-MAX_HISTORY:]

        # Call LLM
        provider = get_provider(provider_name, api_key)
        reply, tokens_in, tokens_out = await provider.chat(
            api_messages, model, temperature, max_tokens, system_prompt
        )

        # Append assistant reply
        msgs.append({"role": "assistant", "content": reply, "timestamp": datetime.now(timezone.utc).isoformat()})
        convo.messages = msgs
        convo.updated_at = datetime.now(timezone.utc)

        # Auto-title on first assistant message
        if len(msgs) == 2:  # user + assistant
            convo.title = _auto_title(message)

        db.commit()

        # Track usage
        cost = estimate_cost(provider_name, model, tokens_in, tokens_out)
        usage = LLMUsage(
            user_id=user_id,
            conversation_id=convo.id,
            provider=provider_name,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_estimate=cost,
        )
        db.add(usage)
        db.commit()

        return {
            "reply": reply,
            "conversation_id": convo.id,
            "title": convo.title,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "model": model,
        }

    @staticmethod
    async def stream_chat(
        db: Session,
        user_id: int,
        message: str,
        conversation_id: Optional[int],
        page_context: str = "",
        context_data: Optional[dict] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream a chat response. Yields text chunks, then a final metadata JSON line."""
        import json

        settings = LLMService._get_settings(db, user_id)
        api_key = decrypt_value(settings.llm_api_key_encrypted)
        provider_name = settings.llm_provider
        model = settings.llm_model
        temperature = float(settings.llm_temperature or "0.7")
        max_tokens = int(settings.llm_max_tokens or "4096")
        custom_prompt = settings.llm_system_prompt or ""

        memories = db.query(LLMMemory).filter(LLMMemory.user_id == user_id).all()
        system_prompt = _build_system_prompt(memories, page_context, context_data, custom_prompt)

        # Load or create conversation
        if conversation_id:
            convo = db.query(LLMConversation).filter(
                LLMConversation.id == conversation_id,
                LLMConversation.user_id == user_id,
            ).first()
            if not convo:
                raise ValueError("Conversation not found")
        else:
            convo = LLMConversation(
                user_id=user_id,
                page_context=page_context,
                messages=[],
                title="New Chat",
            )
            db.add(convo)
            db.commit()
            db.refresh(convo)

        now_str = datetime.now(timezone.utc).isoformat()
        msgs = list(convo.messages or [])
        msgs.append({"role": "user", "content": message, "timestamp": now_str})

        MAX_HISTORY = 30
        api_messages = msgs[-MAX_HISTORY:]

        provider = get_provider(provider_name, api_key)

        # Stream response chunks
        full_reply = []
        try:
            async for chunk in provider.stream(api_messages, model, temperature, max_tokens, system_prompt):
                full_reply.append(chunk)
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
        except Exception as e:
            error_msg = str(e)[:300]
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
            return

        reply_text = "".join(full_reply)
        msgs.append({"role": "assistant", "content": reply_text, "timestamp": datetime.now(timezone.utc).isoformat()})
        convo.messages = msgs
        convo.updated_at = datetime.now(timezone.utc)

        if len(msgs) == 2:
            convo.title = _auto_title(message)

        db.commit()

        # Rough token estimate for streaming (provider doesn't always return counts)
        est_tokens_in = sum(len(m["content"]) // 4 for m in api_messages)
        est_tokens_out = len(reply_text) // 4
        cost = estimate_cost(provider_name, model, est_tokens_in, est_tokens_out)

        usage = LLMUsage(
            user_id=user_id,
            conversation_id=convo.id,
            provider=provider_name,
            model=model,
            tokens_in=est_tokens_in,
            tokens_out=est_tokens_out,
            cost_estimate=cost,
        )
        db.add(usage)
        db.commit()

        # Final metadata event
        yield f"data: {json.dumps({'type': 'done', 'conversation_id': convo.id, 'title': convo.title, 'tokens_in': est_tokens_in, 'tokens_out': est_tokens_out, 'model': model})}\n\n"


    @staticmethod
    async def stream_copilot_chat(
        db: Session,
        user_id: int,
        message: str,
        conversation_id: Optional[int],
        page_context: str = "",
        context_data: Optional[dict] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream a copilot chat with tool calling. Yields SSE events."""
        import json

        settings = LLMService._get_settings(db, user_id)
        api_key = decrypt_value(settings.llm_api_key_encrypted)
        provider_name = settings.llm_provider
        model = settings.llm_model
        temperature = float(settings.llm_temperature or "0.7")
        max_tokens = int(settings.llm_max_tokens or "4096")
        custom_prompt = settings.llm_system_prompt or ""

        # Copilot settings
        copilot_enabled = bool(getattr(settings, "copilot_enabled", 1))
        if not copilot_enabled:
            yield f"data: {json.dumps({'type': 'error', 'content': 'Copilot is disabled. Enable it in Settings → AI Copilot.'})}\n\n"
            return

        autonomy = getattr(settings, "copilot_autonomy", "assisted") or "assisted"
        raw_perms = getattr(settings, "copilot_permissions", {}) or {}
        if isinstance(raw_perms, str):
            try:
                raw_perms = json.loads(raw_perms)
            except (ValueError, TypeError):
                raw_perms = {}
        user_overrides = raw_perms or {}

        memories = db.query(LLMMemory).filter(LLMMemory.user_id == user_id).all()

        # Enhanced system prompt for copilot mode
        copilot_instructions = (
            "\n\nYou have access to platform tools that let you take real actions. "
            "When the user asks you to do something (list strategies, run a backtest, check positions, etc.), "
            "use the appropriate tool rather than explaining how to do it manually. "
            "Always explain what you're about to do and summarize results clearly after tool execution. "
            "If a tool returns an error, explain it to the user and suggest alternatives."
        )
        system_prompt = _build_system_prompt(
            memories, page_context, context_data, custom_prompt
        ) + copilot_instructions

        # Load or create conversation
        if conversation_id:
            convo = db.query(LLMConversation).filter(
                LLMConversation.id == conversation_id,
                LLMConversation.user_id == user_id,
            ).first()
            if not convo:
                raise ValueError("Conversation not found")
        else:
            convo = LLMConversation(
                user_id=user_id,
                page_context=page_context,
                messages=[],
                title="New Chat",
            )
            db.add(convo)
            db.commit()
            db.refresh(convo)

        now_str = datetime.now(timezone.utc).isoformat()
        msgs = list(convo.messages or [])
        msgs.append({"role": "user", "content": message, "timestamp": now_str})

        MAX_HISTORY = 30
        api_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in msgs[-MAX_HISTORY:]
            if m.get("role") in ("user", "assistant")
        ]

        provider = get_provider(provider_name, api_key)

        # Emit conversation_id immediately so frontend can track it
        yield f"data: {json.dumps({'type': 'conversation', 'conversation_id': convo.id})}\n\n"

        # Run copilot executor
        from app.services.llm.copilot_executor import copilot_stream

        full_text_parts = []
        total_tokens_in = 0
        total_tokens_out = 0

        async for event_str in copilot_stream(
            db=db,
            user_id=user_id,
            messages=api_messages,
            system_prompt=system_prompt,
            provider=provider,
            provider_name=provider_name,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            autonomy=autonomy,
            user_overrides=user_overrides,
        ):
            # Forward SSE events to client
            yield event_str

            # Extract text and metadata from events
            try:
                # Parse the SSE data line
                if event_str.startswith("data: "):
                    data = json.loads(event_str[6:].strip())
                    if data.get("type") == "chunk":
                        full_text_parts.append(data.get("content", ""))
                    elif data.get("type") == "done":
                        total_tokens_in = data.get("tokens_in", 0)
                        total_tokens_out = data.get("tokens_out", 0)
            except (json.JSONDecodeError, KeyError):
                pass

        # Save conversation with the reply
        reply_text = "".join(full_text_parts)
        if reply_text:
            msgs.append({
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        convo.messages = msgs
        convo.updated_at = datetime.now(timezone.utc)

        if len([m for m in msgs if m.get("role") in ("user", "assistant")]) == 2:
            convo.title = _auto_title(message)

        db.commit()

        # Track usage
        if total_tokens_in or total_tokens_out:
            cost = estimate_cost(provider_name, model, total_tokens_in, total_tokens_out)
            usage = LLMUsage(
                user_id=user_id,
                conversation_id=convo.id,
                provider=provider_name,
                model=model,
                tokens_in=total_tokens_in,
                tokens_out=total_tokens_out,
                cost_estimate=cost,
            )
            db.add(usage)
            db.commit()

        # Final done event with conversation metadata
        yield f"data: {json.dumps({'type': 'done', 'conversation_id': convo.id, 'title': convo.title, 'tokens_in': total_tokens_in, 'tokens_out': total_tokens_out, 'model': model})}\n\n"


def _auto_title(first_message: str) -> str:
    """Generate a short title from the first user message."""
    title = first_message.strip()
    # Remove common prefixes
    for prefix in ("help me ", "can you ", "please ", "i want to ", "how do i "):
        if title.lower().startswith(prefix):
            title = title[len(prefix):]
            break
    # Truncate
    if len(title) > 60:
        title = title[:57] + "..."
    return title.capitalize() if title else "New Chat"
