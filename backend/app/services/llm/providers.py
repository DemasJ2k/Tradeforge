"""LLM provider implementations: Claude, OpenAI, Gemini.

Each provider exposes:
 - chat(messages, model, temperature, max_tokens, system_prompt) -> (reply, tokens_in, tokens_out)
 - stream(messages, ...) -> AsyncGenerator[str, None]  (yields text chunks)
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import AsyncGenerator

# ── Cost per 1M tokens (input/output) in USD ──
COST_TABLE: dict[str, dict[str, tuple[float, float]]] = {
    "claude": {
        "claude-sonnet-4-20250514": (3.0, 15.0),
        "claude-opus-4-20250514": (15.0, 75.0),
        "claude-haiku-3-5-20241022": (0.80, 4.0),
    },
    "openai": {
        "gpt-4o": (2.50, 10.0),
        "gpt-4o-mini": (0.15, 0.60),
        "o3-mini": (1.10, 4.40),
    },
    "gemini": {
        "gemini-2.5-pro": (1.25, 10.0),
        "gemini-2.0-flash": (0.10, 0.40),
    },
}


def estimate_cost(provider: str, model: str, tokens_in: int, tokens_out: int) -> float:
    """Estimate cost in USD for a given call."""
    table = COST_TABLE.get(provider, {})
    rates = table.get(model, (0.0, 0.0))
    return (tokens_in * rates[0] + tokens_out * rates[1]) / 1_000_000


# ══════════════════════════════════════════════════════════════════════
# Abstract base
# ══════════════════════════════════════════════════════════════════════


class LLMProvider(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: str,
    ) -> tuple[str, int, int]:
        """Return (reply_text, tokens_in, tokens_out)."""
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: str,
    ) -> AsyncGenerator[str, None]:
        """Yield text chunks as they arrive."""
        ...

    async def chat_with_tools(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: str,
        tools: list[dict] | None = None,
    ) -> dict:
        """Call LLM with tool definitions. Returns:
        {
            "text": str,
            "tool_calls": [{"id": str, "name": str, "arguments": dict}],
            "tokens_in": int,
            "tokens_out": int,
        }
        Default implementation falls back to regular chat (no tool calling).
        """
        reply, t_in, t_out = await self.chat(messages, model, temperature, max_tokens, system_prompt)
        return {"text": reply, "tool_calls": [], "tokens_in": t_in, "tokens_out": t_out}


# ══════════════════════════════════════════════════════════════════════
# Claude (Anthropic)
# ══════════════════════════════════════════════════════════════════════


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.async_client = anthropic.AsyncAnthropic(api_key=api_key)

    async def chat(self, messages, model, temperature, max_tokens, system_prompt):
        model = model or "claude-sonnet-4-20250514"

        # Anthropic uses a separate system param, not in messages list
        api_messages = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]

        resp = await self.async_client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt or "You are a helpful AI trading assistant.",
            messages=api_messages,
        )
        reply = resp.content[0].text
        return reply, resp.usage.input_tokens, resp.usage.output_tokens

    async def chat_with_tools(self, messages, model, temperature, max_tokens, system_prompt, tools=None):
        model = model or "claude-sonnet-4-20250514"

        # Build messages — handle tool-related message types
        api_messages = []
        for m in messages:
            role = m.get("role", "")
            if role == "system":
                continue
            elif role == "tool":
                # Tool result → Anthropic format
                api_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": m.get("tool_call_id", ""),
                        "content": m.get("content", ""),
                    }],
                })
            elif role == "assistant" and m.get("tool_calls"):
                # Assistant message with tool calls
                content = []
                if m.get("content"):
                    content.append({"type": "text", "text": m["content"]})
                for tc in m["tool_calls"]:
                    content.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": tc.get("name", ""),
                        "input": tc.get("arguments", {}),
                    })
                api_messages.append({"role": "assistant", "content": content})
            else:
                api_messages.append({"role": role, "content": m.get("content", "")})

        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt or "You are a helpful AI trading assistant.",
            "messages": api_messages,
        }
        if tools:
            kwargs["tools"] = tools

        resp = await self.async_client.messages.create(**kwargs)

        # Parse response content blocks
        text_parts = []
        tool_calls = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "arguments": block.input,
                })

        return {
            "text": "\n".join(text_parts),
            "tool_calls": tool_calls,
            "tokens_in": resp.usage.input_tokens,
            "tokens_out": resp.usage.output_tokens,
        }

    async def stream(self, messages, model, temperature, max_tokens, system_prompt):
        model = model or "claude-sonnet-4-20250514"
        api_messages = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]

        async with self.async_client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt or "You are a helpful AI trading assistant.",
            messages=api_messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text


# ══════════════════════════════════════════════════════════════════════
# OpenAI
# ══════════════════════════════════════════════════════════════════════


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key)

    async def chat(self, messages, model, temperature, max_tokens, system_prompt):
        model = model or "gpt-4o-mini"

        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        api_messages.extend(
            {"role": m["role"], "content": m["content"]}
            for m in messages if m["role"] != "system"
        )

        resp = await self.client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=api_messages,
        )
        choice = resp.choices[0]
        usage = resp.usage
        return choice.message.content, usage.prompt_tokens, usage.completion_tokens

    async def chat_with_tools(self, messages, model, temperature, max_tokens, system_prompt, tools=None):
        import json as _json
        model = model or "gpt-4o-mini"

        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})

        for m in messages:
            role = m.get("role", "")
            if role == "system":
                continue
            elif role == "tool":
                api_messages.append({
                    "role": "tool",
                    "tool_call_id": m.get("tool_call_id", ""),
                    "content": m.get("content", ""),
                })
            elif role == "assistant" and m.get("tool_calls"):
                msg = {"role": "assistant", "content": m.get("content") or None}
                msg["tool_calls"] = [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": _json.dumps(tc.get("arguments", {})),
                        },
                    }
                    for tc in m["tool_calls"]
                ]
                api_messages.append(msg)
            else:
                api_messages.append({"role": role, "content": m.get("content", "")})

        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": api_messages,
        }
        if tools:
            kwargs["tools"] = tools

        resp = await self.client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        usage = resp.usage

        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = _json.loads(tc.function.arguments)
                except (ValueError, TypeError):
                    args = {}
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": args,
                })

        return {
            "text": choice.message.content or "",
            "tool_calls": tool_calls,
            "tokens_in": usage.prompt_tokens,
            "tokens_out": usage.completion_tokens,
        }

    async def stream(self, messages, model, temperature, max_tokens, system_prompt):
        model = model or "gpt-4o-mini"
        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        api_messages.extend(
            {"role": m["role"], "content": m["content"]}
            for m in messages if m["role"] != "system"
        )

        stream = await self.client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=api_messages,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content


# ══════════════════════════════════════════════════════════════════════
# Gemini (Google)
# ══════════════════════════════════════════════════════════════════════


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str):
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self.genai = genai

    async def chat(self, messages, model, temperature, max_tokens, system_prompt):
        model_name = model or "gemini-2.0-flash"
        gm = self.genai.GenerativeModel(
            model_name,
            system_instruction=system_prompt or "You are a helpful AI trading assistant.",
            generation_config=self.genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        # Convert to Gemini format: alternating user/model turns
        history = []
        for m in messages[:-1]:
            role = "model" if m["role"] == "assistant" else "user"
            history.append({"role": role, "parts": [m["content"]]})

        chat = gm.start_chat(history=history)
        last_msg = messages[-1]["content"] if messages else ""

        # Run synchronously in executor since genai doesn't have native async
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, lambda: chat.send_message(last_msg))

        tokens_in = resp.usage_metadata.prompt_token_count if hasattr(resp, 'usage_metadata') and resp.usage_metadata else 0
        tokens_out = resp.usage_metadata.candidates_token_count if hasattr(resp, 'usage_metadata') and resp.usage_metadata else 0

        return resp.text, tokens_in, tokens_out

    async def chat_with_tools(self, messages, model, temperature, max_tokens, system_prompt, tools=None):
        model_name = model or "gemini-2.0-flash"

        kwargs = {
            "system_instruction": system_prompt or "You are a helpful AI trading assistant.",
            "generation_config": self.genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        }
        if tools:
            kwargs["tools"] = tools

        gm = self.genai.GenerativeModel(model_name, **kwargs)

        # Build history — filter out tool-related messages for Gemini's simpler format
        history = []
        for m in messages[:-1]:
            role_raw = m.get("role", "user")
            if role_raw == "system":
                continue
            elif role_raw == "tool":
                # Gemini: function response
                import google.generativeai as genai_mod
                from google.protobuf.struct_pb2 import Struct
                import json as _json

                func_name = m.get("name", "tool_result")
                try:
                    result_data = _json.loads(m.get("content", "{}"))
                except (ValueError, TypeError):
                    result_data = {"result": m.get("content", "")}

                s = Struct()
                s.update(result_data)
                part = genai_mod.protos.Part(
                    function_response=genai_mod.protos.FunctionResponse(
                        name=func_name, response=s
                    )
                )
                history.append({"role": "user", "parts": [part]})
            elif role_raw == "assistant" and m.get("tool_calls"):
                # Gemini: function call from model
                import google.generativeai as genai_mod
                from google.protobuf.struct_pb2 import Struct

                parts = []
                if m.get("content"):
                    parts.append(m["content"])
                for tc in m["tool_calls"]:
                    s = Struct()
                    s.update(tc.get("arguments", {}))
                    parts.append(genai_mod.protos.Part(
                        function_call=genai_mod.protos.FunctionCall(
                            name=tc.get("name", ""), args=s
                        )
                    ))
                history.append({"role": "model", "parts": parts})
            else:
                role = "model" if role_raw == "assistant" else "user"
                history.append({"role": role, "parts": [m.get("content", "")]})

        chat_session = gm.start_chat(history=history)
        last_msg = messages[-1].get("content", "") if messages else ""

        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, lambda: chat_session.send_message(last_msg))

        # Parse response parts
        text_parts = []
        tool_calls = []
        for part in resp.parts:
            if hasattr(part, "text") and part.text:
                text_parts.append(part.text)
            elif hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                tool_calls.append({
                    "id": f"gemini_{fc.name}_{id(fc)}",
                    "name": fc.name,
                    "arguments": dict(fc.args) if fc.args else {},
                })

        tokens_in = resp.usage_metadata.prompt_token_count if hasattr(resp, 'usage_metadata') and resp.usage_metadata else 0
        tokens_out = resp.usage_metadata.candidates_token_count if hasattr(resp, 'usage_metadata') and resp.usage_metadata else 0

        return {
            "text": "\n".join(text_parts),
            "tool_calls": tool_calls,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }

    async def stream(self, messages, model, temperature, max_tokens, system_prompt):
        model_name = model or "gemini-2.0-flash"
        gm = self.genai.GenerativeModel(
            model_name,
            system_instruction=system_prompt or "You are a helpful AI trading assistant.",
            generation_config=self.genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        history = []
        for m in messages[:-1]:
            role = "model" if m["role"] == "assistant" else "user"
            history.append({"role": role, "parts": [m["content"]]})

        chat = gm.start_chat(history=history)
        last_msg = messages[-1]["content"] if messages else ""

        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None, lambda: chat.send_message(last_msg, stream=True)
        )
        for chunk in resp:
            if chunk.text:
                yield chunk.text


# ══════════════════════════════════════════════════════════════════════
# Factory
# ══════════════════════════════════════════════════════════════════════

PROVIDER_MAP = {
    "claude": ClaudeProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
}


def get_provider(provider_name: str, api_key: str) -> LLMProvider:
    """Create an LLM provider instance."""
    cls = PROVIDER_MAP.get(provider_name.lower())
    if cls is None:
        raise ValueError(f"Unknown LLM provider: {provider_name}")
    return cls(api_key=api_key)
