"""HTTP plumbing shared by the providers: one pooled client each, and uniform error mapping."""

import httpx

from app.llm.base import RETRYABLE_STATUS, LLMError
from app.security.redact import redact

TIMEOUT = httpx.Timeout(connect=10, read=120, write=30, pool=30)
LIMITS = httpx.Limits(max_connections=200, max_keepalive_connections=50)


def make_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, limits=LIMITS, transport=transport)


async def post_json(client: httpx.AsyncClient, url: str, headers: dict, body: dict) -> httpx.Response:
    try:
        response = await client.post(url, headers=headers, json=body)
    except httpx.TimeoutException as exc:
        raise LLMError("The model did not answer in time.", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach the model provider: {type(exc).__name__}.", retryable=True) from exc
    if response.status_code >= 400:
        retry_after = None
        try:
            retry_after = float(response.headers.get("retry-after", ""))
        except ValueError:
            pass
        detail = redact(response.text[:300])
        raise LLMError(
            f"Provider returned {response.status_code}: {detail}",
            status=response.status_code,
            retryable=response.status_code in RETRYABLE_STATUS,
            retry_after=retry_after,
        )
    return response


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
