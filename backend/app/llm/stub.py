"""A model that needs no network: scripted answers for tests, load runs and key-less demos."""

from collections.abc import Callable

from app.llm.base import LLMError
from app.llm.types import LLMResponse, Message, ToolSpec, Usage

Responder = Callable[[list[Message], list[ToolSpec]], LLMResponse]


class StubProvider:
    name = "stub"

    def __init__(self, script: list[LLMResponse | Exception] | None = None, responder: Responder | None = None):
        self.script = list(script or [])
        self.responder = responder
        self.calls: list[list[Message]] = []

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec], *, model: str, max_tokens: int, temperature: float = 0
    ) -> LLMResponse:
        self.calls.append(list(messages))
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        if self.responder:
            return self.responder(messages, tools)
        raise LLMError("The stub model has no more scripted answers.", retryable=False)


def reply(text: str = "", tool_calls=None, tokens: tuple[int, int] = (100, 20)) -> LLMResponse:
    """Shorthand for building a scripted answer."""
    return LLMResponse(
        text=text,
        tool_calls=list(tool_calls or []),
        usage=Usage(*tokens),
        stop_reason="tool_use" if tool_calls else "stop",
        model="stub",
        latency_ms=1,
    )
