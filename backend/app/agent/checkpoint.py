"""LangGraph's checkpoints in PostgreSQL. The tables are created once by the owner role (bootstrap); the API uses
the application role through PgBouncer, so statements are not prepared (transaction pooling)."""

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.api.health import libpq_url
from app.config import get_settings

_pool: AsyncConnectionPool | None = None
_saver: AsyncPostgresSaver | None = None


async def checkpointer() -> AsyncPostgresSaver:
    global _pool, _saver
    if _saver is None:
        _pool = AsyncConnectionPool(libpq_url(get_settings().database_url), min_size=1, max_size=10, open=False,
                                    kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row})  # fmt: skip
        await _pool.open()
        _saver = AsyncPostgresSaver(_pool)
    return _saver


async def close_checkpointer() -> None:
    global _pool, _saver
    if _pool is not None:
        await _pool.close()
    _pool, _saver = None, None


async def create_tables() -> None:
    async with AsyncPostgresSaver.from_conn_string(libpq_url(get_settings().database_url_owner)) as saver:
        await saver.setup()
