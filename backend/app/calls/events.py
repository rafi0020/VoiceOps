"""Live call events in Redis streams: one stream per call (its transcript as it happens) and one per organisation
(calls starting, changing state, ending) for the Live console. Redis is only the live copy; turns and events are in
PostgreSQL."""

import json
import time
from collections.abc import AsyncIterator
from uuid import UUID

from app.redis import get_redis

MAXLEN = 2000
POLL_SECONDS = 0.3


def call_stream(call_id: UUID) -> str:
    return f"call:{call_id}:events"


def org_stream(org_id: UUID) -> str:
    return f"org:{org_id}:calls"


async def publish(org_id: UUID, call_id: UUID, kind: str, data: dict) -> None:
    redis, payload = get_redis(), {"type": kind, "data": json.dumps({"call_id": str(call_id), **data}, default=str)}
    await redis.xadd(call_stream(call_id), payload, maxlen=MAXLEN, approximate=True)
    if kind in ("call_started", "call_state", "call_ended", "turn", "approval_needed"):
        await redis.xadd(org_stream(org_id), payload, maxlen=MAXLEN, approximate=True)
    await redis.expire(call_stream(call_id), 24 * 3600)


async def sse(key: str, cursor: str, *, max_seconds: int = 1800, heartbeat: int = 15) -> AsyncIterator[str]:
    """Server-Sent Events from a stream, resuming after `cursor` (the browser's Last-Event-ID)."""
    import asyncio

    redis = get_redis()
    started = last = time.monotonic()
    yield "retry: 2000\n\n"
    while time.monotonic() - started < max_seconds:
        for event_id, fields in await redis.xrange(key, min=f"({cursor}", count=200):
            cursor, last = event_id, time.monotonic()
            yield f"id: {event_id}\nevent: {fields['type']}\ndata: {fields['data']}\n\n"
        if time.monotonic() - last > heartbeat:
            last = time.monotonic()
            yield ": keep-alive\n\n"
        await asyncio.sleep(POLL_SECONDS)
