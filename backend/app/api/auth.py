"""Sign-up, sign-in, sign-out, current user, password change."""

import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import audit, current_user
from app.config import get_settings
from app.db import system_session, tenant_session
from app.models.identity import Org, User
from app.security import sessions
from app.security.passwords import dummy_hash, hash_password, password_problem, verify_password
from app.security.ratelimit import client_ip, enforce
from app.security.sessions import Principal

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
BAD_LOGIN = "Incorrect e-mail or password."


def normalise_email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 254 or not EMAIL.match(value):
        raise ValueError("Enter a valid e-mail address.")
    return value


class Credentials(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=200)
    _email = field_validator("email")(normalise_email)


class SignUp(Credentials):
    name: str = Field(min_length=1, max_length=100)
    org_name: str = Field(min_length=2, max_length=100)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


def user_out(u: Principal | User) -> dict:
    return {"id": str(u.id), "org_id": str(u.org_id), "email": u.email, "name": u.name, "role": u.role}


def _set_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        sessions.COOKIE, token, max_age=s.session_hours * 3600, httponly=True, samesite="lax",
        secure=s.cookie_secure, path="/",
    )  # fmt: skip


@router.post("/signup", status_code=201)
async def signup(body: SignUp, request: Request, response: Response) -> dict:
    """Create a new organisation; the person signing up becomes its first administrator."""
    s = get_settings()
    if not s.allow_signup:
        raise HTTPException(403, "Sign-up is disabled.")
    await enforce(f"signup:ip:{client_ip(request)}", s.signup_ip_per_hour, 3600)
    if problem := password_problem(body.password):
        raise HTTPException(422, problem)
    password_hash = await asyncio.to_thread(hash_password, body.password)
    try:
        async with system_session() as db:
            if (await db.execute(select(User.id).where(User.email == body.email))).first():
                raise HTTPException(409, "An account with this e-mail already exists.")
            org = Org(name=body.org_name.strip())
            db.add(org)
            await db.flush()
            user = User(
                org_id=org.id, email=body.email, name=body.name.strip(), password_hash=password_hash, role="admin"
            )
            db.add(user)
            await db.flush()
            token, csrf = await sessions.create_session(db, user)
    except IntegrityError as exc:  # two sign-ups with one address passed the check together: the index decides
        if "users_email" not in str(exc.orig):
            raise
        raise HTTPException(409, "An account with this e-mail already exists.") from exc
    _set_cookie(response, token)
    return {"user": user_out(user), "csrf_token": csrf}


@router.post("/login")
async def login(body: Credentials, request: Request, response: Response) -> dict:
    s = get_settings()
    await enforce(f"login:ip:{client_ip(request)}", s.login_ip_per_minute, 60)
    await enforce(f"login:email:{body.email}", s.login_attempts_per_minute, 60)
    async with system_session() as db:
        user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    # Verify against a real hash even when the account does not exist, so the response time is the same.
    stored = user.password_hash if user else dummy_hash()
    ok = await asyncio.to_thread(verify_password, body.password, stored)
    if not (ok and user and user.is_active):
        raise HTTPException(401, BAD_LOGIN)
    async with system_session() as db:
        token, csrf = await sessions.create_session(db, user)
    async with tenant_session(user.org_id) as db:
        principal = Principal(user.id, user.org_id, user.email, user.name, user.role, user.id, csrf)
        audit(db, principal, "auth.login", request=request)
    _set_cookie(response, token)
    return {"user": user_out(user), "csrf_token": csrf}


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, user: Principal = Depends(current_user)) -> None:
    await sessions.revoke_token(request.cookies[sessions.COOKIE])
    response.delete_cookie(sessions.COOKIE, path="/")


@router.get("/me")
async def me(user: Principal = Depends(current_user)) -> dict:
    return {"user": user_out(user), "csrf_token": user.csrf}


@router.post("/password", status_code=204)
async def change_password(body: PasswordChange, request: Request, user: Principal = Depends(current_user)) -> None:
    if problem := password_problem(body.new_password):
        raise HTTPException(422, problem)
    async with tenant_session(user.org_id) as db:
        row = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        if not await asyncio.to_thread(verify_password, body.current_password, row.password_hash):
            raise HTTPException(403, "Current password is incorrect.")
        row.password_hash = await asyncio.to_thread(hash_password, body.new_password)
        audit(db, user, "auth.password_changed", request=request)
    await sessions.revoke_user_sessions(user.id, keep_session=user.session_id)
