from tests.conftest import rows


async def test_healthz_reports_ok(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_readyz_ok_when_database_and_redis_answer(client):
    r = await client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}


async def test_readyz_names_the_failing_dependency(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://voiceops_app:wrong@localhost:1/none")
    get_settings.cache_clear()
    try:
        r = await client.get("/readyz")
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    assert r.status_code == 503
    assert r.json() == {"status": "unavailable", "failing": ["database"]}


async def test_every_response_carries_a_request_id(client):
    r = await client.get("/healthz", headers={"X-Request-ID": "abc-123"})
    assert r.headers["X-Request-ID"] == "abc-123"
    assert len((await client.get("/healthz")).headers["X-Request-ID"]) >= 16


async def test_an_exhausted_connection_pool_is_a_503_to_retry_not_a_500(team, monkeypatch):
    """Found at 1,000 simultaneous users: requests that waited 30 s for a database connection got 500."""
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    from app.api import users

    def busy(*_args, **_kwargs):
        raise PoolTimeout("QueuePool limit of size 10 overflow 10 reached")

    monkeypatch.setattr(users, "tenant_session", busy)
    r = await team.admin.get("/api/users")
    assert r.status_code == 503 and r.headers["Retry-After"] == "5" and "busy" in r.json()["detail"]


async def test_metrics_report_calls_tokens_and_spend(team, client):
    await rows(
        team.org_id,
        "INSERT INTO calls (org_id, status, tokens, cost_usd) VALUES (:o, 'ended', 120, 0.25) RETURNING 1",
        o=team.org_id,
    )
    r = await client.get("/metrics")
    assert r.status_code == 200, r.text
    assert 'voiceops_calls{status="ended"}' in r.text and "voiceops_cost_usd_today" in r.text
