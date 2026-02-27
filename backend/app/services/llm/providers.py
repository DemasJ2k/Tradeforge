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
