"""Provider-neutral message and response types. The agent runtime only ever sees these."""

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    invalid: bool = False  # the model produced arguments that are not a JSON object
    raw: str | None = None  # the unparsed text, kept when invalid


@dataclass
class Message:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)  # on assistant messages
    tool_call_id: str | None = None  # on tool messages: which call this answers


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    estimated: bool = False  # the provider reported no usage; counts were estimated from text length


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    usage: Usage
    stop_reason: str
    model: str
    latency_ms: int = 0
