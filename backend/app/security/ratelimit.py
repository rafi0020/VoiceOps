"""Sliding-window rate limiting on Redis.

Each key is a sorted set of request timestamps. A request is allowed when fewer than `limit` timestamps
fall inside the last `window_s` seconds. Counting is done in Redis so it holds across every API process.
"""

import math
import secrets
import time

from fastapi import HTTPException, Request
from redis.exceptions import RedisError

from app.config import get_settings
from app.redis import get_redis
from app.security import sessions


def client_ip(request: Request) -> str:
    if get_settings().trusted_proxy:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


async def hit(key: str, limit: int, window_s: int, *, fail_open: bool = False) -> int | None:
    """Record one request. Returns None when allowed, or the seconds to wait when over the limit.

    When Redis is unavailable the request is refused with 503, unless `fail_open`: then it is allowed, for
    paths where refusing costs more than an unenforced limit (ingestion, whose data is safe in PostgreSQL)."""
    now = time.time()
    try:
        pipe = get_redis().pipeline()
        pipe.zremrangebyscore(key, 0, now - window_s)
        pipe.zadd(key, {f"{now}:{secrets.token_hex(4)}": now})
        pipe.zcard(key)
        pipe.expire(key, window_s + 1)
        pipe.zrange(key, 0, 0, withscores=True)
        _, _, count, _, oldest = await pipe.execute()
    except RedisError as exc:
        if fail_open:
            return None
        raise HTTPException(503, "Rate limiter unavailable; try again shortly.", headers={"Retry-After": "5"}) from exc
    if count <= limit:
        return None
    return max(1, math.ceil(oldest[0][1] + window_s - now)) if oldest else window_s


async def enforce(key: str, limit: int, window_s: int, *, fail_open: bool = False) -> None:
    wait = await hit(f"rl:{key}", limit, window_s, fail_open=fail_open)
    if wait is not None:
        raise HTTPException(429, "Too many requests. Try again later.", headers={"Retry-After": str(wait)})


def rate_limit(name: str, limit: int, window_s: int):
    """Dependency: limit a route per signed-in user (or per client address when nobody is signed in)."""

    async def dependency(request: Request) -> None:
        principal = getattr(request.state, "principal", None)
        if principal is None and (token := request.cookies.get(sessions.COOKIE)):
            principal = await sessions.resolve(token)  # route dependencies run before the endpoint's own sign-in check
        who = f"u:{principal.id}" if principal else f"ip:{client_ip(request)}"
        await enforce(f"{name}:{who}", limit, window_s)

    return dependency
