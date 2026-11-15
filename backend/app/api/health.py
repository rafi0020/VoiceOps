"""Liveness (/healthz: the process is up) and readiness (/readyz: its dependencies answer)."""

import psycopg
import redis.asyncio as aioredis
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import get_settings

router = APIRouter(tags=["health"])


def libpq_url(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://", 1)


async def _database_ok(url: str) -> bool:
    try:
        async with await psycopg.AsyncConnection.connect(libpq_url(url), connect_timeout=2) as conn:
            await conn.execute("SELECT 1")
        return True
    except (psycopg.Error, OSError):
        return False


async def _redis_ok(url: str) -> bool:
    client = aioredis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
    try:
        return bool(await client.ping())
    except (aioredis.RedisError, OSError):
        return False
    finally:
        await client.aclose()


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz():
    s = get_settings()
    failing = []
    if not await _database_ok(s.database_url):
        failing.append("database")
    if not await _redis_ok(s.redis_url):
        failing.append("redis")
    if failing:
        return JSONResponse({"status": "unavailable", "failing": failing}, status_code=503)
    return {"status": "ready"}
