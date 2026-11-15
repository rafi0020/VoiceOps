"""Row-level security: one organisation can never read or write another's rows."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import get_engine, make_engine, system_session, tenant_session

INSERT = "INSERT INTO audit_log (org_id, action) VALUES (:org, :action)"
COUNT = "SELECT count(*) FROM audit_log WHERE action = :action"
POOLER_URL = "postgresql+psycopg://voiceops_app:voiceops_app@localhost:56462/voiceops_test"


async def test_rows_of_one_org_are_invisible_to_another(two_orgs):
    a, b = two_orgs
    async with tenant_session(a) as db:
        await db.execute(text(INSERT), {"org": a, "action": f"secret-{a}"})
    async with tenant_session(a) as db:
        assert (await db.execute(text(COUNT), {"action": f"secret-{a}"})).scalar_one() == 1
    async with tenant_session(b) as db:
        assert (await db.execute(text(COUNT), {"action": f"secret-{a}"})).scalar_one() == 0


async def test_cannot_write_a_row_for_another_org(two_orgs):
    a, b = two_orgs
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_session(a) as db:
            await db.execute(text(INSERT), {"org": b, "action": "forged"})


async def test_no_org_set_means_no_rows(two_orgs):
    a, _ = two_orgs
    async with tenant_session(a) as db:
        await db.execute(text(INSERT), {"org": a, "action": f"visible-{a}"})
    async with get_engine().connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM audit_log"))).scalar_one() == 0


async def test_system_session_does_not_open_ordinary_tenant_tables(two_orgs):
    a, _ = two_orgs
    async with tenant_session(a) as db:
        await db.execute(text(INSERT), {"org": a, "action": f"sys-{a}"})
    async with system_session() as db:
        assert (await db.execute(text("SELECT count(*) FROM audit_log"))).scalar_one() == 0


async def test_org_does_not_leak_between_transactions_on_a_pooled_connection(two_orgs):
    a, b = two_orgs
    engine = make_engine(POOLER_URL, pool_size=1)
    try:
        async with tenant_session(a, engine=engine) as db:
            await db.execute(text(INSERT), {"org": a, "action": f"pooled-{a}"})
        async with tenant_session(b, engine=engine) as db:
            assert (await db.execute(text(COUNT), {"action": f"pooled-{a}"})).scalar_one() == 0
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT app_current_org()"))).scalar_one() is None
    finally:
        await engine.dispose()


async def test_application_cannot_rewrite_the_audit_log(two_orgs):
    a, _ = two_orgs
    with pytest.raises(DBAPIError, match="permission denied"):
        async with tenant_session(a) as db:
            await db.execute(text("DELETE FROM audit_log"))
