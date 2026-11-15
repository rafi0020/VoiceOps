"""Provider interface, error types, and the retry / fallback policy shared by every provider."""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Protocol

from app.llm.types import LLMResponse, Message, ToolSpec

log = logging.getLogger("voiceops.llm")

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


class LLMError(Exception):
    """A provider call failed. `retryable` says whether trying again could help."""

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False,
                 retry_after: float | None = None):  # fmt: skip
        super().__init__(message)
        self.status, self.retryable, self.retry_after = status, retryable, retry_after


class LLMUnavailable(LLMError):
    """Every attempt, including the fallback model, failed."""


class LLMProvider(Protocol):
    name: str

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec], *, model: str, max_tokens: int, temperature: float = 0
    ) -> LLMResponse: ...


# Back-pressure: at most this many model calls in flight per process, whatever the number of runs.
_gate: asyncio.Semaphore | None = None


def _semaphore() -> asyncio.Semaphore:
    global _gate
    if _gate is None:
        from app.config import get_settings

        _gate = asyncio.Semaphore(get_settings().llm_max_concurrency)
    return _gate


async def call_with_retry(
    provider: LLMProvider,
    messages: list[Message],
    tools: list[ToolSpec],
    *,
    model: str,
    max_tokens: int,
    fallback_model: str | None = None,
    temperature: float = 0.0,
    attempts: int = 4,
    base_delay: float = 0.5,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> LLMResponse:
    """Call the model, retrying transient failures with exponential back-off and jitter.

    Timeouts, 429 and 5xx are retried (honouring Retry-After). Other errors, such as a bad request or a wrong
    key, are raised at once because repeating them cannot succeed. When the primary model is exhausted the
    fallback model, if configured, gets one attempt.
    """
    last: LLMError | None = None
    for attempt in range(attempts):
        try:
            async with _semaphore():
                return await provider.complete(
                    messages, tools, model=model, max_tokens=max_tokens, temperature=temperature
                )
        except LLMError as exc:
            if not exc.retryable:
                raise
            last = exc
            if attempt + 1 < attempts:
                delay = exc.retry_after if exc.retry_after is not None else base_delay * 2**attempt
                delay = min(delay, 30) * random.uniform(0.8, 1.2)  # noqa: S311 - jitter, not security
                log.warning("llm retry", extra={"model": model, "attempt": attempt + 1, "status": exc.status})
                await sleep(delay)
    if fallback_model and fallback_model != model:
        log.warning("llm falling back", extra={"model": model, "fallback": fallback_model})
        try:
            async with _semaphore():
                return await provider.complete(
                    messages, tools, model=fallback_model, max_tokens=max_tokens, temperature=temperature
                )
        except LLMError as exc:
            last = exc
    raise LLMUnavailable(f"The model is unavailable: {last}", status=last.status if last else None)
