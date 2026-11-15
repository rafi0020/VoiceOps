"""Demo organisations and accounts, created when SEED_DEMO=true. Safe to run more than once."""

import asyncio
import os
from uuid import UUID

from sqlalchemy import select

from app.db import system_session
from app.models.identity import Org, User
from app.security.passwords import hash_password

# Fixed ids so generated demo data can refer to its organisation.
LARKSPUR = UUID("11111111-1111-4111-8111-111111111111")
FERNHILL = UUID("22222222-2222-4222-8222-222222222222")
DEMO_ORGS = {LARKSPUR: ("Larkspur Telecom", "larkspur.demo"), FERNHILL: ("Fernhill Energy", "fernhill.demo")}
DEMO_ROLES = {
    "admin": os.environ.get("DEMO_ADMIN_PASSWORD", "Admin#Demo2026"),
    "supervisor": os.environ.get("DEMO_APPROVER_PASSWORD", "Supervisor#Demo2026"),
    "agent": os.environ.get("DEMO_CLERK_PASSWORD", "Agent#Demo2026"),
    "viewer": os.environ.get("DEMO_VIEWER_PASSWORD", "Viewer#Demo2026"),
}


async def ensure_demo_users() -> None:
    hashes = {role: await asyncio.to_thread(hash_password, pw) for role, pw in DEMO_ROLES.items()}
    async with system_session() as db:
        for org_id, (name, domain) in DEMO_ORGS.items():
            if await db.get(Org, org_id) is None:
                db.add(Org(id=org_id, name=name))
                await db.flush()
            for role in DEMO_ROLES:
                email = f"{role}@{domain}"
                if (await db.execute(select(User.id).where(User.email == email))).first() is None:
                    db.add(
                        User(org_id=org_id, email=email, name=f"{name} {role.title()}", role=role,
                             password_hash=hashes[role])
                    )  # fmt: skip
