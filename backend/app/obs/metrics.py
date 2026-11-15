"""Prometheus metrics at /metrics.

Request metrics are measured in this process. Call, token and cost figures are read from the database when
the endpoint is scraped, so they are correct however many API processes there are.

Each API container runs one process, so a scrape always sees that container's complete request metrics;
scale by adding containers. Set METRICS_TOKEN to require `Authorization: Bearer <token>`.
"""

import hmac
import time

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, Histogram, generate_latest
from sqlalchemy import text

from app.config import get_settings
from app.db import system_session

registry = CollectorRegistry()
REQUESTS = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "route", "status"], registry=registry,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)  # fmt: skip
CALLS = Gauge("voiceops_calls", "Calls by status", ["status"], registry=registry)
TOKENS = Gauge("voiceops_tokens_total", "Model tokens used by all calls", registry=registry)
COST = Gauge("voiceops_cost_usd_total", "Estimated model cost of all calls, USD", registry=registry)
COST_TODAY = Gauge(
    "voiceops_cost_usd_today", "Estimated model cost of today's calls, USD (the global daily limit)", registry=registry
)
STATUSES = ("live", "handed_off", "ended")

router = APIRouter(tags=["health"])


def install_request_metrics(app: FastAPI) -> None:
    @app.middleware("http")
    async def measure(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        # The route template, not the raw path, so ids in URLs do not create a new time series each.
        REQUESTS.labels(request.method, getattr(route, "path", "unmatched"), response.status_code).observe(
            time.perf_counter() - started
        )
        return response


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    token = get_settings().metrics_token
    if token and not hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {token}"):
        raise HTTPException(401, "Metrics require a bearer token.")
    async with system_session() as db:
        rows = (
            await db.execute(text("SELECT status, count(*), sum(tokens), sum(cost_usd) FROM calls GROUP BY status"))
        ).all()
        today = await db.scalar(
            text("SELECT coalesce(sum(cost_usd), 0) FROM calls WHERE started_at >= date_trunc('day', now())")
        )
    counts = {status: 0 for status in STATUSES} | {r[0]: r[1] for r in rows}
    for status, count in counts.items():
        CALLS.labels(status).set(count)
    TOKENS.set(sum(r[2] or 0 for r in rows))
    COST.set(float(sum(r[3] or 0 for r in rows)))
    COST_TODAY.set(float(today))
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
