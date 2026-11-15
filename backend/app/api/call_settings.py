"""Per-organisation call settings: the credit the assistant may apply on one call without a supervisor."""

from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.agent.tools import credit_limit
from app.api.deps import audit, current_user, require_role
from app.db import tenant_session
from app.security.sessions import Principal

router = APIRouter(prefix="/api/call-settings", tags=["settings"])


class SettingsIn(BaseModel):
    credit_limit: Decimal = Field(ge=0, le=500, max_digits=8, decimal_places=2)


@router.get("")
async def get(user: Principal = Depends(current_user)) -> dict:
    async with tenant_session(user.org_id) as db:
        return {"credit_limit": f"{await credit_limit(db):.2f}"}


@router.put("")
async def put(body: SettingsIn, request: Request, admin: Principal = Depends(require_role("admin"))) -> dict:
    async with tenant_session(admin.org_id) as db:
        await db.execute(text("INSERT INTO org_call_settings (org_id, credit_limit) VALUES (:o, :l) ON CONFLICT (org_id) DO UPDATE SET credit_limit = excluded.credit_limit, updated_at = now()"),
                         {"o": admin.org_id, "l": body.credit_limit})  # fmt: skip
        audit(db, admin, "settings.credit_limit", None, {"credit_limit": f"{body.credit_limit:.2f}"}, request)
    return {"credit_limit": f"{body.credit_limit:.2f}"}
