"""Run once before the API and workers start: apply migrations, then load demo data if asked to."""

import asyncio
import logging
import time
from collections.abc import Callable

from alembic import command
from alembic.config import Config
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from app.obs.logging import configure_logging

log = logging.getLogger("voiceops.bootstrap")


def with_retries[T](step: Callable[[], T], *, attempts: int = 30, delay_s: float = 2.0) -> T:
    """Run `step`, retrying while the database refuses connections (it may still be starting, or PgBouncer may
    be holding on to a failed login for a few seconds). Any other error is a real one and is raised at once."""
    for attempt in range(1, attempts + 1):
        try:
            return step()
        except OperationalError:
            if attempt == attempts:
                raise
            log.warning("database not reachable yet; retrying", extra={"attempt": attempt})
            time.sleep(delay_s)
    raise AssertionError("unreachable")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    with_retries(lambda: command.upgrade(Config("alembic.ini"), "head"))
    from app.agent.checkpoint import create_tables

    with_retries(lambda: asyncio.run(create_tables()))  # LangGraph's own tables, owned like every other table
    log.info("migrations applied")
    if settings.seed_demo:
        with_retries(lambda: asyncio.run(seed_demo()))


async def seed_demo() -> None:
    from app.db import dispose_engines
    from seed.demo_users import ensure_demo_users

    try:
        await ensure_demo_users()
        log.info("demo accounts ready")
        from seed.generate import generate, has_data

        if not await has_data():
            counts = await generate(customers=get_settings().demo_customers)
            log.info("demo data generated", extra=counts)
    finally:
        await dispose_engines()  # each retry runs in a new event loop, which needs fresh connections


if __name__ == "__main__":
    main()
