import os

# Tests run against the real PostgreSQL and Redis started by `make dev-up`, using a separate database.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://voiceops_app:voiceops_app@localhost:55462/voiceops_test")
os.environ.setdefault(
    "DATABASE_URL_OWNER", "postgresql+psycopg://voiceops_owner:voiceops_owner@localhost:55462/voiceops_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:56409/1")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("SEED_DEMO", "false")

os.environ.setdefault("LLM_PROVIDER", "stub")
os.environ.setdefault(
    "MODELS_DIR", str(__import__("pathlib").Path(__file__).resolve().parents[1] / ".models")
)  # the image sets /models
os.environ.setdefault("SCRYPT_N", "1024")  # fast hashing in tests only
os.environ.setdefault("LOGIN_IP_PER_MINUTE", "100000")
os.environ.setdefault("SIGNUP_IP_PER_HOUR", "100000")

# Live model tests read the gateway key from New_Project/.env.local when it exists.
_local = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env.local")
if os.path.exists(_local):
    for _line in open(_local):
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.strip().split("=", 1)
            os.environ.setdefault(_k, _v)


import httpx  # noqa: E402
import pytest  # noqa: E402
import sqlalchemy as sa  # noqa: E402

# Empties the *test* database (voiceops_test) so the migrations can be applied from scratch.
RESET_SQL = """
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT schemaname, viewname FROM pg_views WHERE schemaname IN ('public', 'analytics') LOOP
    EXECUTE format('DROP VIEW IF EXISTS %I.%I CASCADE', r.schemaname, r.viewname);
  END LOOP;
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
    EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', r.tablename);
  END LOOP;
  -- aggregates first (they depend on functions), each with the statement that removes its kind
  FOR r IN SELECT p.oid::regprocedure::text AS sig, p.prokind FROM pg_proc p JOIN pg_roles o ON o.oid = p.proowner
           WHERE o.rolname = 'voiceops_owner' ORDER BY (p.prokind = 'a') DESC LOOP
    EXECUTE format('DROP %s IF EXISTS %s CASCADE', CASE WHEN r.prokind = 'a' THEN 'AGGREGATE' ELSE 'FUNCTION' END, r.sig);
  END LOOP;
END $$;
"""


def owner_engine() -> sa.Engine:
    url = os.environ["DATABASE_URL_OWNER"]
    assert url.endswith("/voiceops_test"), "tests must never run against a non-test database"
    return sa.create_engine(url)


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    """Rebuild the test database from the migrations once per test run."""
    from alembic import command
    from alembic.config import Config

    engine = owner_engine()
    with engine.begin() as conn:
        conn.execute(sa.text(RESET_SQL))
    engine.dispose()
    command.upgrade(Config("alembic.ini"), "head")
    import asyncio

    from app.agent.checkpoint import create_tables

    asyncio.run(create_tables())


@pytest.fixture(scope="session", autouse=True)
async def _dispose_engines(migrated_database):
    yield
    from app.db import dispose_engines

    await dispose_engines()


@pytest.fixture
def two_orgs():
    """Two fresh organisations for isolation tests."""
    engine = owner_engine()
    with engine.begin() as conn:
        a = conn.execute(sa.text("INSERT INTO orgs (name) VALUES ('Org A') RETURNING id")).scalar_one()
        b = conn.execute(sa.text("INSERT INTO orgs (name) VALUES ('Org B') RETURNING id")).scalar_one()
    engine.dispose()
    return a, b


@pytest.fixture
async def client():
    from app.main import create_app

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(scope="session", autouse=True)
async def _clean_redis(migrated_database):
    from app.redis import close_redis, get_redis

    await get_redis().flushdb()
    yield
    await close_redis()


PASSWORD = "Correct-Horse-9"


class Team:
    """One organisation with a signed-in HTTP client per role."""

    def __init__(self, app):
        self.app = app
        self.clients: list[httpx.AsyncClient] = []
        self.org_id = None
        self.emails: dict[str, str] = {}

    def _client(self) -> httpx.AsyncClient:
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test")
        self.clients.append(c)
        return c

    async def login(self, email: str, password: str = PASSWORD) -> httpx.AsyncClient:
        c = self._client()
        r = await c.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        return c

    async def build(self) -> "Team":
        import uuid

        tag = uuid.uuid4().hex[:10]
        self.emails = {role: f"{role}-{tag}@example.test" for role in ("admin", "supervisor", "agent", "viewer")}
        self.admin = self._client()
        r = await self.admin.post(
            "/api/auth/signup",
            json={
                "email": self.emails["admin"],
                "password": PASSWORD,
                "name": "Ada",
                "org_name": f"Org {tag}",
            },
        )
        assert r.status_code == 201, r.text
        self.admin.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        self.org_id = r.json()["user"]["org_id"]
        self.user_ids = {"admin": r.json()["user"]["id"]}
        for role in ("supervisor", "agent", "viewer"):
            r = await self.admin.post(
                "/api/users",
                json={"email": self.emails[role], "password": PASSWORD, "name": role.title(), "role": role},
            )
            assert r.status_code == 201, r.text
            self.user_ids[role] = r.json()["id"]
            setattr(self, role, await self.login(self.emails[role]))
        return self

    async def close(self) -> None:
        for c in self.clients:
            await c.aclose()


@pytest.fixture(scope="session")
async def app():
    from app.main import create_app

    return create_app()


@pytest.fixture
async def team(app):
    t = await Team(app).build()
    yield t
    await t.close()


@pytest.fixture
async def other_team(app):
    t = await Team(app).build()
    yield t
    await t.close()


def pytest_collection_modifyitems(config, items):
    if os.environ.get("NINEROUTER_API_KEY") and os.environ.get("RUN_LIVE", "1") == "1":
        return
    skip = pytest.mark.skip(reason="needs NINEROUTER_API_KEY (and RUN_LIVE not set to 0)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def stub_llm():
    """Replace the model for every organisation with a scripted stub; yields the stub to load a script into."""
    from app.llm import factory
    from app.llm.stub import StubProvider

    stub = StubProvider()
    factory.set_override(stub)
    yield stub
    factory.set_override(None)


async def rows(org_id, sql, **params):
    from sqlalchemy import text

    from app.db import tenant_session

    async with tenant_session(org_id) as db:
        return (await db.execute(text(sql), params)).all()


@pytest.fixture(scope="session")
async def demo(migrated_database):
    """The demo data for both organisations with 20 ordinary customers each, loaded once per test run."""
    from seed.generate import generate, has_data

    if not await has_data():
        await generate(seed=7, customers=20)


@pytest.fixture
async def graph(migrated_database):
    """The compiled call graph on the real Postgres checkpointer."""
    from app.agent.checkpoint import checkpointer
    from app.agent.graph import build_graph

    return build_graph(await checkpointer())
