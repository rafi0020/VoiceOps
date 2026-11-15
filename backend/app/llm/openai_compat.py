"""OpenAI-compatible chat completions: OpenAI, Gemini's and Groq's compatible endpoints, 9Router, LiteLLM,
vLLM, Ollama's /v1 endpoint, and any other gateway that speaks the same protocol."""

import json
import time

import httpx

from app.llm.base import LLMError
from app.llm.http import estimate_tokens, make_client, post_json
from app.llm.types import LLMResponse, Message, ToolCall, ToolSpec, Usage


def parse_arguments(call_id: str, name: str, raw: str | dict | None) -> ToolCall:
    if isinstance(raw, dict):
        return ToolCall(call_id, name, raw)
    text = (raw or "").strip() or "{}"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if not isinstance(parsed, dict):
        return ToolCall(call_id, name, {}, invalid=True, raw=text[:2000])
    return ToolCall(call_id, name, parsed)


def to_wire(messages: list[Message]) -> list[dict]:
    out = []
    for m in messages:
        if m.role == "tool":
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
        elif m.role == "assistant" and m.tool_calls:
            calls = [
                {"id": c.id, "type": "function",
                 "function": {"name": c.name, "arguments": c.raw if c.invalid else json.dumps(c.arguments)}}
                for c in m.tool_calls
            ]  # fmt: skip
            out.append({"role": "assistant", "content": m.content or None, "tool_calls": calls})
        else:
            out.append({"role": m.role, "content": m.content})
    return out


def merge_stream(body: str) -> dict:
    """Fold a server-sent-event stream of chunks into the shape of a non-streamed response.

    Some gateways stream even when asked not to, so the same parser must cope with both.
    """
    text, calls, finish, usage, model = "", {}, None, None, ""
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        model = chunk.get("model") or model
        usage = chunk.get("usage") or usage
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            text += delta.get("content") or ""
            for part in delta.get("tool_calls") or []:
                slot = calls.setdefault(part.get("index", 0), {"id": "", "name": "", "arguments": ""})
                slot["id"] = part.get("id") or slot["id"]
                function = part.get("function") or {}
                slot["name"] = function.get("name") or slot["name"]
                slot["arguments"] += function.get("arguments") or ""
            finish = choice.get("finish_reason") or finish
    message = {"content": text}
    if calls:
        message["tool_calls"] = [
            {"id": c["id"], "function": {"name": c["name"], "arguments": c["arguments"]}}
            for _, c in sorted(calls.items())
        ]
    return {"model": model, "usage": usage, "choices": [{"message": message, "finish_reason": finish}]}


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(self, base_url: str, api_key: str = "", transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = make_client(transport)

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec], *, model: str, max_tokens: int, temperature: float = 0
    ) -> LLMResponse:
        body: dict = {"model": model, "messages": to_wire(messages), "max_tokens": max_tokens, "stream": False}
        body["temperature"] = temperature  # zero is a setting (deterministic), not 'unset'
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.input_schema},
                }
                for t in tools
            ]
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        started = time.perf_counter()
        response = await post_json(self.client, f"{self.base_url}/chat/completions", headers, body)
        raw = response.text
        streamed = "text/event-stream" in response.headers.get("content-type", "") or raw.lstrip().startswith("data:")
        try:
            data = merge_stream(raw) if streamed else response.json()
            choice = data["choices"][0]
            message = choice["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("The provider returned a response that could not be read.", retryable=True) from exc
        calls = [
            parse_arguments(c.get("id") or f"call_{i}", (c.get("function") or {}).get("name", ""),
                            (c.get("function") or {}).get("arguments"))
            for i, c in enumerate(message.get("tool_calls") or [])
        ]  # fmt: skip
        text = message.get("content") or ""
        reported = data.get("usage") or {}
        if reported.get("prompt_tokens") is not None:
            details = reported.get("prompt_tokens_details") or {}
            usage = Usage(
                reported["prompt_tokens"], reported.get("completion_tokens", 0), details.get("cached_tokens", 0)
            )
        else:
            sent = sum(len(m.content) for m in messages)
            usage = Usage(estimate_tokens("x" * sent), estimate_tokens(text + json.dumps([c.arguments for c in calls])),
                          estimated=True)  # fmt: skip
        return LLMResponse(
            text=text,
            tool_calls=calls,
            usage=usage,
            stop_reason="tool_use" if calls else (choice.get("finish_reason") or "stop"),
            model=data.get("model") or model,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
