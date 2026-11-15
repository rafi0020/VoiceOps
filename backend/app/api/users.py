"""User management for administrators. Every query runs inside the caller's organisation."""

import asyncio
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.auth import normalise_email
from app.api.deps import audit, require_role
from app.db import system_session, tenant_session
from app.models.identity import User
from app.security import sessions
from app.security.passwords import hash_password, password_problem
from app.security.sessions import Principal

router = APIRouter(prefix="/api/users", tags=["users"])
Role = Literal["viewer", "agent", "supervisor", "admin"]


class UserCreate(BaseModel):
    email: str
    name: str = Field(min_length=1, max_length=100)
    role: Role
    password: str = Field(min_length=1, max_length=200)
    _email = field_validator("email")(normalise_email)


class UserPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    role: Role | None = None
    is_active: bool | None = None


def out(u: User) -> dict:
    return {
        "id": str(u.id), "email": u.email, "name": u.name, "role": u.role, "is_active": u.is_active,
        "created_at": u.created_at.isoformat(),
    }  # fmt: skip


@router.get("")
async def list_users(admin: Principal = Depends(require_role("admin"))) -> dict:
    async with tenant_session(admin.org_id) as db:
        users = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    return {"users": [out(u) for u in users]}


@router.post("", status_code=201)
async def create_user(body: UserCreate, request: Request, admin: Principal = Depends(require_role("admin"))) -> dict:
    if problem := password_problem(body.password):
        raise HTTPException(422, problem)
    async with system_session() as db:  # e-mail addresses are unique across all organisations
        if (await db.execute(select(User.id).where(User.email == body.email))).first():
            raise HTTPException(409, "An account with this e-mail already exists.")
    password_hash = await asyncio.to_thread(hash_password, body.password)
    try:
        async with tenant_session(admin.org_id) as db:
            user = User(
                org_id=admin.org_id, email=body.email, name=body.name.strip(), role=body.role,
                password_hash=password_hash,
            )  # fmt: skip
            db.add(user)
            await db.flush()
            await db.refresh(user)
            audit(db, admin, "user.created", str(user.id), {"email": user.email, "role": user.role}, request)
    except IntegrityError as exc:  # the address check and this insert are two steps: a second request can win between
        if "users_email" not in str(exc.orig):
            raise
        raise HTTPException(409, "An account with this e-mail already exists.") from exc
    return out(user)


@router.patch("/{user_id}")
async def update_user(
    user_id: UUID, body: UserPatch, request: Request, admin: Principal = Depends(require_role("admin"))
) -> dict:
    changes = body.model_dump(exclude_none=True)
    async with tenant_session(admin.org_id) as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None:  # also the answer for a user of another organisation
            raise HTTPException(404, "User not found.")
        losing_admin = user.role == "admin" and (
            changes.get("role", "admin") != "admin" or changes.get("is_active") is False
        )
        if losing_admin:
            others = await db.scalar(
                select(func.count()).select_from(User).where(
                    User.role == "admin", User.is_active, User.id != user.id
                )
            )  # fmt: skip
            if not others:
                raise HTTPException(409, "An organisation must keep at least one active administrator.")
        for field, value in changes.items():
            setattr(user, field, value.strip() if field == "name" else value)
        audit(db, admin, "user.updated", str(user.id), changes, request)
        result = out(user)
    if changes.get("is_active") is False:
        await sessions.revoke_user_sessions(user_id)
    elif changes:
        await sessions.forget_cached_sessions(user_id)
    return result
