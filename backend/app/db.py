"""Database access.

Every piece of tenant data is protected by PostgreSQL row-level security, so the organisation is not something
each query has to remember to filter on: it is set once per transaction and the database enforces it.

    async with tenant_session(user.org_id) as db:   # sees exactly one organisation's rows
    async with system_session() as db:              # sign-in, metrics and the global spend limit only

`SET LOCAL` semantics (set_config(..., true)) are used because connections go through PgBouncer in transaction
mode, where nothing set at session level survives to the next transaction.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.config import get_settings

_engines: dict[str, AsyncEngine] = {}


def make_engine(url: str, pool_size: int | None = None) -> AsyncEngine:
    return create_async_engine(
        url,
        pool_size=pool_size or get_settings().db_pool_size,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=1800,
        # Server-side prepared statements cannot be used through a transaction pooler.
        connect_args={"prepare_threshold": None},
    )


def get_engine(kind: str = "app") -> AsyncEngine:
    if kind not in _engines:
        _engines[kind] = make_engine(get_settings().database_url)
    return _engines[kind]


async def dispose_engines() -> None:
    for engine in _engines.values():
        await engine.dispose()
    _engines.clear()


@asynccontextmanager
async def tenant_session(org_id: UUID, *, engine: AsyncEngine | None = None) -> AsyncIterator[AsyncSession]:
    """One transaction bound to one organisation. Commits on success, rolls back on error."""
    async with AsyncSession(engine or get_engine(), expire_on_commit=False) as session, session.begin():
        await session.execute(text("SELECT set_config('app.org_id', :org, true)"), {"org": str(org_id)})
        yield session


@asynccontextmanager
async def system_session(*, engine: AsyncEngine | None = None) -> AsyncIterator[AsyncSession]:
    """A transaction with no organisation. It can read the identity tables and the calls table (for metrics and the global spend limit), nothing else."""
    async with AsyncSession(engine or get_engine(), expire_on_commit=False) as session, session.begin():
        await session.execute(text("SELECT set_config('app.system', 'on', true)"))
        yield session
