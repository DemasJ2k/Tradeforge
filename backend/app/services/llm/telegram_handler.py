"""Telegram AI message handler — bridges free-form Telegram messages to the copilot engine.

Telegram is request/response (not SSE streaming), so this module:
1. Collects all tool calls and results into a buffer
2. Runs the full copilot loop
3. Returns the final text response
4. For confirmation-required tools, tells user to approve in web app
"""

import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.core.encryption import decrypt_value, encrypt_value
from app.models.settings import UserSettings
from app.models.llm import LLMConversation, LLMMemory
from app.services.llm.providers import get_provider
from app.services.llm.copilot_executor import copilot_stream
from app.services.llm.service import _build_system_prompt

logger = logging.getLogger(__name__)

# Per-user Telegram conversation tracking (in-memory, keyed by user_id)
_telegram_conversations: dict[int, int] = {}

TELEGRAM_SYSTEM_ADDENDUM = """

You are responding via Telegram. Keep responses concise and under 3000 characters.
Use Telegram HTML formatting: <b>bold</b>, <i>italic</i>, <code>monospace</code>.
Do NOT use markdown — Telegram uses HTML parse_mode.
When tools return data, summarize key numbers clearly in a readable format.
You have access to all platform tools. Use them to fulfill user requests.
For actions that need confirmation (like placing trades), tell the user to approve in the web app."""


async def handle_telegram_message(
    db: Session,
    user_id: int,
    message: str,
    chat_id: str,
) -> str:
    """Process a Telegram message through the copilot and return response text."""

    # Get user's LLM settings (or platform fallback)
    settings = db.query(UserSettings).filter(
        UserSettings.user_id == user_id
    ).first()

    if not settings:
        settings = UserSettings(user_id=user_id)

    # Resolve API key: user's own or platform-level
    api_key = None
    if settings.llm_api_key_encrypted:
        api_key = decrypt_value(settings.llm_api_key_encrypted)
    else:
        from app.core.config import settings as app_settings
        platform_key = app_settings.PLATFORM_LLM_API_KEY
        if platform_key:
            api_key = platform_key

    if not api_key:
        return "AI not configured. Ask the admin to set PLATFORM_LLM_API_KEY, or set your own key in Settings."

    provider_name = settings.llm_provider or "claude"
    model = settings.llm_model or "claude-sonnet-4-20250514"
    temperature = float(settings.llm_temperature or "0.7")
    max_tokens = int(settings.llm_max_tokens or "2048")  # smaller for Telegram
    autonomy = getattr(settings, "copilot_autonomy", "assisted") or "assisted"

    # Parse user permission overrides
    user_overrides = {}
    raw_perms = getattr(settings, "copilot_permissions", None)
    if raw_perms:
        if isinstance(raw_perms, str):
            try:
                user_overrides = json.loads(raw_perms)
            except (json.JSONDecodeError, TypeError):
                pass
        elif isinstance(raw_perms, dict):
            user_overrides = raw_perms

    # Load user memories for context
    memories = db.query(LLMMemory).filter(LLMMemory.user_id == user_id).all()

    # Build system prompt with Telegram-specific instructions
    system_prompt = _build_system_prompt(
        memories, "telegram", None,
        settings.llm_system_prompt or ""
    ) + TELEGRAM_SYSTEM_ADDENDUM

    # Build messages (single user message for now — no multi-turn in Telegram)
    api_messages = [{"role": "user", "content": message}]

    provider = get_provider(provider_name, api_key)

    # Collect full response from copilot stream
    response_parts = []
    tool_summaries = []

    try:
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
            if not event_str.startswith("data: "):
                continue

            try:
                data = json.loads(event_str[6:].strip())
            except (json.JSONDecodeError, ValueError):
                continue

            event_type = data.get("type", "")

            if event_type == "chunk":
                response_parts.append(data.get("content", ""))

            elif event_type == "tool_call":
                tool_name = data.get("name", "")
                tool_summaries.append(tool_name)

            elif event_type == "confirm_required":
                tool_name = data.get("name", "")
                response_parts.append(
                    f"\n\nAction '<b>{tool_name}</b>' needs your approval. "
                    "Please approve it in the FlowrexAlgo web app."
                )

            elif event_type == "error":
                response_parts.append(f"\n\nError: {data.get('content', 'Unknown error')}")

    except Exception as e:
        logger.exception("Telegram copilot stream error for user %d", user_id)
        return f"Something went wrong: {str(e)[:200]}"

    full_response = "".join(response_parts).strip()

    # Truncate for Telegram's 4096 char limit (leave room for HTML tags)
    if len(full_response) > 3900:
        full_response = full_response[:3850] + "\n\n<i>... truncated. See full response in web app.</i>"

    return full_response or "I couldn't generate a response. Try again or use the web app."
