"""Read access to the audit log for administrators."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import require_role
from app.db import tenant_session
from app.models.audit import AuditLog
from app.models.identity import User
from app.security.sessions import Principal

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
async def list_audit(
    admin: Principal = Depends(require_role("admin")),
    limit: int = Query(50, ge=1, le=200),
    before: int | None = Query(None, ge=1, le=2**63 - 1, description="Return entries with an id below this one."),
    action: str | None = Query(None, max_length=64, description="Exact action or prefix, e.g. 'user.'"),
) -> dict:
    stmt = (
        select(AuditLog, User.email)
        .outerjoin(User, User.id == AuditLog.user_id)
        .order_by(AuditLog.id.desc())
        .limit(limit + 1)
    )
    if before is not None:
        stmt = stmt.where(AuditLog.id < before)
    if action:
        stmt = stmt.where(AuditLog.action.startswith(action, autoescape=True))
    async with tenant_session(admin.org_id) as db:
        rows = (await db.execute(stmt)).all()
    entries = [
        {
            "id": a.id,
            "at": a.created_at.isoformat(),
            "user": email,
            "action": a.action,
            "target": a.target,
            "detail": a.detail,
            "ip": a.ip,
        }  # fmt: skip
        for a, email in rows[:limit]
    ]
    return {"entries": entries, "next_before": entries[-1]["id"] if len(rows) > limit else None}
