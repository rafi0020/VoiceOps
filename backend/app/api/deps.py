"""Request dependencies: who is calling, and whether they may."""

import hmac

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.security import sessions
from app.security.ratelimit import client_ip
from app.security.redact import redact
from app.security.sessions import Principal

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


async def current_user(request: Request) -> Principal:
    token = request.cookies.get(sessions.COOKIE)
    principal = await sessions.resolve(token) if token else None
    if principal is None:
        raise HTTPException(401, "Not signed in.")
    if request.method not in SAFE_METHODS:
        # The cookie is sent automatically by the browser; this header is not, so a forged cross-site
        # request cannot supply it.
        supplied = request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(supplied, principal.csrf):
            raise HTTPException(403, "Missing or invalid CSRF token.")
    request.state.principal = principal
    return principal


def require_role(*roles: str):
    async def dependency(user: Principal = Depends(current_user)) -> Principal:
        if user.role not in roles:
            raise HTTPException(403, "Your role does not allow this.")
        return user

    return dependency


def audit(
    db: AsyncSession,
    user: Principal,
    action: str,
    target: str | None = None,
    detail: dict | None = None,
    request: Request | None = None,
) -> None:
    """Record who did what. Added to the caller's transaction, so it commits or rolls back with the change."""
    db.add(
        AuditLog(
            org_id=user.org_id,
            user_id=user.id,
            action=action,
            target=target,
            detail=redact(detail) if detail else None,
            ip=client_ip(request) if request else None,
        )
    )
