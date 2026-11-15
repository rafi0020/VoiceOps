"""Anthropic Messages API (native), with prompt caching on the stable prefix."""

import time

import httpx

from app.llm.base import LLMError
from app.llm.http import make_client, post_json
from app.llm.types import LLMResponse, Message, ToolCall, ToolSpec, Usage

API_VERSION = "2023-06-01"
CACHE = {"type": "ephemeral"}


def to_wire(messages: list[Message]) -> tuple[list[dict], list[dict]]:
    """Split into (system blocks, conversation). Tool results become user turns, as the API requires."""
    system, out = [], []
    for m in messages:
        if m.role == "system":
            system.append({"type": "text", "text": m.content})
        elif m.role == "tool":
            block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)  # results of parallel calls share one user turn
            else:
                out.append({"role": "user", "content": [block]})
        elif m.role == "assistant":
            blocks = [{"type": "text", "text": m.content}] if m.content else []
            blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in m.tool_calls]
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "(no content)"}]})
        else:
            out.append({"role": "user", "content": m.content})
    return system, out


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, base_url: str = "", transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = (base_url or "https://api.anthropic.com").rstrip("/")
        self.api_key = api_key
        self.client = make_client(transport)

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec], *, model: str, max_tokens: int, temperature: float = 0
    ) -> LLMResponse:
        system, conversation = to_wire(messages)
        body: dict = {"model": model, "max_tokens": max_tokens, "messages": conversation}
        body["temperature"] = temperature  # zero is a setting (deterministic), not 'unset'
        # The system prompt and the tool definitions do not change between steps of a run, so they are marked
        # cacheable: later steps read them from the provider's cache at a fraction of the price.
        if system:
            system[-1]["cache_control"] = CACHE
            body["system"] = system
        if tools:
            body["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools
            ]
            body["tools"][-1]["cache_control"] = CACHE
        headers = {"x-api-key": self.api_key, "anthropic-version": API_VERSION}
        started = time.perf_counter()
        response = await post_json(self.client, f"{self.base_url}/v1/messages", headers, body)
        try:
            data = response.json()
            blocks = data["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMError("The provider returned a response that could not be read.", retryable=True) from exc
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        calls = [
            ToolCall(b["id"], b["name"], b["input"])
            if isinstance(b.get("input"), dict)
            else ToolCall(b["id"], b["name"], {}, invalid=True, raw=str(b.get("input"))[:2000])
            for b in blocks
            if b.get("type") == "tool_use"
        ]
        u = data.get("usage") or {}
        cached = u.get("cache_read_input_tokens", 0) or 0
        usage = Usage(
            input_tokens=(u.get("input_tokens", 0) or 0) + cached + (u.get("cache_creation_input_tokens", 0) or 0),
            output_tokens=u.get("output_tokens", 0) or 0,
            cached_tokens=cached,
        )
        return LLMResponse(
            text=text,
            tool_calls=calls,
            usage=usage,
            stop_reason=data.get("stop_reason") or "end_turn",
            model=data.get("model") or model,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
