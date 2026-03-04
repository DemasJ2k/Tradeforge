"""Copilot Executor — Multi-turn tool calling loop with permission checks.

Flow:
  1. Call LLM with tools (non-streaming chat_with_tools)
  2. If tool_calls in response → check permissions → execute or request confirmation
  3. Feed results back to LLM as tool result messages
  4. Repeat until text-only response (max 5 iterations)
  5. Yield SSE events throughout

SSE Event types:
  - tool_call:       AI is calling a tool
  - tool_result:     Tool executed, result returned
  - confirm_required: Tool needs user approval
  - tool_blocked:    Tool blocked by permissions
  - chunk:           Text response content
  - done:            Completion metadata
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from sqlalchemy.orm import Session

from app.services.llm.copilot_tools import (
    TOOL_REGISTRY,
    CopilotTool,
    get_tools_for_provider,
)

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5

# ── Pending confirmations (in-memory, per-process) ───────────────────

_pending_confirmations: dict[str, dict] = {}  # confirm_id -> {tool_name, args, db, user_id, expires}


def resolve_permission(
    tool: CopilotTool,
    autonomy: str,
    user_overrides: dict,
) -> str:
    """Determine effective permission for a tool given user settings.

    Priority: user per-tool override > autonomy mode > tool default.
    """
    # User per-tool override (e.g. {"place_order": "blocked"})
    override = user_overrides.get(tool.name)
    if override in ("auto", "confirm", "blocked"):
        return override

    # Autonomy mode
    if autonomy == "analysis_only":
        # Only auto tools run; everything else is blocked
        return "auto" if tool.permission == "auto" else "blocked"
    elif autonomy == "full_auto":
        # Everything except blocked runs automatically
        return "blocked" if tool.permission == "blocked" else "auto"
    else:
        # "assisted" (default) — use tool's own permission
        return tool.permission


def get_allowed_tools(autonomy: str, user_overrides: dict) -> list[CopilotTool]:
    """Get tools the LLM should know about (everything except fully blocked)."""
    allowed = []
    for tool in TOOL_REGISTRY.values():
        perm = resolve_permission(tool, autonomy, user_overrides)
        if perm != "blocked":
            allowed.append(tool)
    return allowed


def _sse(event_type: str, data: dict) -> str:
    """Format an SSE event."""
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


async def copilot_stream(
    db: Session,
    user_id: int,
    messages: list[dict],
    system_prompt: str,
    provider,
    provider_name: str,
    model: str,
    temperature: float,
    max_tokens: int,
    autonomy: str = "assisted",
    user_overrides: dict | None = None,
) -> AsyncGenerator[str, None]:
    """Main copilot loop — call LLM with tools, execute, iterate.

    Yields SSE-formatted strings.
    """
    user_overrides = user_overrides or {}

    # Build tool list for the LLM
    allowed_tools = get_allowed_tools(autonomy, user_overrides)
    tool_defs = get_tools_for_provider(provider_name, allowed_tools)

    total_tokens_in = 0
    total_tokens_out = 0

    # Working copy of messages for multi-turn tool loop
    working_messages = list(messages)

    for iteration in range(MAX_TOOL_ITERATIONS):
        try:
            result = await provider.chat_with_tools(
                messages=working_messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                tools=tool_defs,
            )
        except Exception as e:
            logger.exception("chat_with_tools failed")
            yield _sse("error", {"content": f"LLM call failed: {str(e)[:300]}"})
            return

        total_tokens_in += result.get("tokens_in", 0)
        total_tokens_out += result.get("tokens_out", 0)

        tool_calls = result.get("tool_calls", [])
        text = result.get("text", "")

        # If no tool calls, we have the final text response
        if not tool_calls:
            if text:
                yield _sse("chunk", {"content": text})
            break

        # Process tool calls
        tool_results = []
        has_confirm = False

        for tc in tool_calls:
            tc_id = tc.get("id", str(uuid.uuid4()))
            tc_name = tc.get("name", "")
            tc_args = tc.get("arguments", {})

            tool = TOOL_REGISTRY.get(tc_name)
            if not tool:
                # Unknown tool
                tool_results.append({
                    "tool_call_id": tc_id,
                    "name": tc_name,
                    "result": {"error": f"Unknown tool: {tc_name}"},
                })
                yield _sse("tool_result", {"name": tc_name, "result": {"error": "Unknown tool"}})
                continue

            perm = resolve_permission(tool, autonomy, user_overrides)

            if perm == "blocked":
                yield _sse("tool_blocked", {"name": tc_name})
                tool_results.append({
                    "tool_call_id": tc_id,
                    "name": tc_name,
                    "result": {"error": f"Tool '{tc_name}' is blocked by user settings."},
                })
                continue

            if perm == "confirm":
                # Queue for user confirmation
                confirm_id = str(uuid.uuid4())
                _pending_confirmations[confirm_id] = {
                    "tool_name": tc_name,
                    "tool_call_id": tc_id,
                    "args": tc_args,
                    "user_id": user_id,
                    "expires": time.time() + 300,  # 5 minutes
                    "working_messages": working_messages.copy(),
                    "system_prompt": system_prompt,
                    "provider_name": provider_name,
                    "model": model,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "autonomy": autonomy,
                    "user_overrides": user_overrides,
                    "total_tokens_in": total_tokens_in,
                    "total_tokens_out": total_tokens_out,
                }
                yield _sse("confirm_required", {
                    "name": tc_name,
                    "description": tool.description,
                    "args": tc_args,
                    "confirm_id": confirm_id,
                })
                has_confirm = True
                continue

            # Auto — execute immediately
            yield _sse("tool_call", {"name": tc_name, "args": tc_args})

            try:
                result_data = await tool.handler(db, user_id, **tc_args)
            except Exception as e:
                logger.exception(f"Tool {tc_name} execution failed")
                result_data = {"error": f"Tool error: {str(e)[:200]}"}

            tool_results.append({
                "tool_call_id": tc_id,
                "name": tc_name,
                "result": result_data,
            })
            yield _sse("tool_result", {"name": tc_name, "result": result_data})

        if has_confirm:
            # Stop iteration — waiting for user confirmation
            # Send any text the LLM produced alongside tool calls
            if text:
                yield _sse("chunk", {"content": text})
            return

        # Feed tool results back to LLM for next iteration
        # Add assistant message with tool calls
        working_messages.append({
            "role": "assistant",
            "content": text or "",
            "tool_calls": tool_calls,
        })

        # Add tool results
        for tr in tool_results:
            working_messages.append({
                "role": "tool",
                "tool_call_id": tr["tool_call_id"],
                "name": tr["name"],
                "content": json.dumps(tr["result"]),
            })

    # Yield done event
    yield _sse("done", {
        "tokens_in": total_tokens_in,
        "tokens_out": total_tokens_out,
        "model": model,
    })


async def execute_confirmed_tool(
    db: Session,
    confirm_id: str,
    approved: bool,
) -> AsyncGenerator[str, None]:
    """Execute a previously confirmed tool call, then continue the copilot loop."""
    # Clean expired confirmations
    now = time.time()
    expired = [k for k, v in _pending_confirmations.items() if v["expires"] < now]
    for k in expired:
        del _pending_confirmations[k]

    pending = _pending_confirmations.pop(confirm_id, None)
    if not pending:
        yield _sse("error", {"content": "Confirmation expired or not found."})
        return

    tool_name = pending["tool_name"]
    tool = TOOL_REGISTRY.get(tool_name)

    if not approved:
        yield _sse("tool_result", {
            "name": tool_name,
            "result": {"status": "denied", "message": "User denied this action."},
        })
        # Feed denial back to LLM
        working_messages = pending["working_messages"]
        working_messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": pending["tool_call_id"], "name": tool_name, "arguments": pending["args"]}],
        })
        working_messages.append({
            "role": "tool",
            "tool_call_id": pending["tool_call_id"],
            "name": tool_name,
            "content": json.dumps({"status": "denied", "message": "User denied this action."}),
        })

        # Continue loop with denial result
        from app.services.llm.providers import get_provider
        from app.core.encryption import decrypt_value
        from app.models.settings import UserSettings

        settings = db.query(UserSettings).filter(UserSettings.user_id == pending["user_id"]).first()
        if settings:
            api_key = decrypt_value(settings.llm_api_key_encrypted)
            provider = get_provider(pending["provider_name"], api_key)

            async for event in copilot_stream(
                db=db,
                user_id=pending["user_id"],
                messages=working_messages,
                system_prompt=pending["system_prompt"],
                provider=provider,
                provider_name=pending["provider_name"],
                model=pending["model"],
                temperature=pending["temperature"],
                max_tokens=pending["max_tokens"],
                autonomy=pending["autonomy"],
                user_overrides=pending["user_overrides"],
            ):
                yield event
        return

    if not tool:
        yield _sse("error", {"content": f"Tool '{tool_name}' not found."})
        return

    # Execute the confirmed tool
    yield _sse("tool_call", {"name": tool_name, "args": pending["args"]})

    try:
        result_data = await tool.handler(db, pending["user_id"], **pending["args"])
    except Exception as e:
        logger.exception(f"Confirmed tool {tool_name} failed")
        result_data = {"error": f"Tool error: {str(e)[:200]}"}

    yield _sse("tool_result", {"name": tool_name, "result": result_data})

    # Continue the copilot loop with tool result
    working_messages = pending["working_messages"]
    working_messages.append({
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": pending["tool_call_id"], "name": tool_name, "arguments": pending["args"]}],
    })
    working_messages.append({
        "role": "tool",
        "tool_call_id": pending["tool_call_id"],
        "name": tool_name,
        "content": json.dumps(result_data),
    })

    # Resume the loop
    from app.services.llm.providers import get_provider
    from app.core.encryption import decrypt_value
    from app.models.settings import UserSettings

    settings = db.query(UserSettings).filter(UserSettings.user_id == pending["user_id"]).first()
    if not settings:
        yield _sse("error", {"content": "User settings not found."})
        return

    api_key = decrypt_value(settings.llm_api_key_encrypted)
    provider = get_provider(pending["provider_name"], api_key)

    async for event in copilot_stream(
        db=db,
        user_id=pending["user_id"],
        messages=working_messages,
        system_prompt=pending["system_prompt"],
        provider=provider,
        provider_name=pending["provider_name"],
        model=pending["model"],
        temperature=pending["temperature"],
        max_tokens=pending["max_tokens"],
        autonomy=pending["autonomy"],
        user_overrides=pending["user_overrides"],
    ):
        yield event
