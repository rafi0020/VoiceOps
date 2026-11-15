"""Credits waiting for a supervisor. Deciding one resumes the call it came from, if that call is still waiting."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import audit, require_role
from app.calls import service
from app.db import tenant_session
from app.models.calls import Call, CallEvent
from app.models.customers import Credit, Customer
from app.security.sessions import Principal

router = APIRouter(prefix="/api/credits", tags=["credits"])
Deciders = Depends(require_role("supervisor", "admin"))


class DecisionIn(BaseModel):
    decision: Literal["approved", "refused"]
    reason: str | None = Field(default=None, max_length=500)


@router.get("")
async def list_credits(
    user: Principal = Depends(require_role("agent", "supervisor", "admin")),
    status: str = Query("pending", max_length=20),
) -> dict:
    async with tenant_session(user.org_id) as db:
        rows = (await db.execute(select(Credit, Customer.name, Customer.account_number, Call.status).join(Customer, Customer.id == Credit.customer_id)
                                 .outerjoin(Call, Call.id == Credit.call_id).where(Credit.status == status).order_by(Credit.requested_at).limit(500))).all()  # fmt: skip
    return {"credits": [{"id": str(c.id), "amount": f"{c.amount:.2f}", "reason": c.reason, "status": c.status, "customer": name, "account_number": acct,
                         "call_id": str(c.call_id) if c.call_id else None, "call_status": call_status, "requested_at": c.requested_at.isoformat(),
                         "decided_at": c.decided_at.isoformat() if c.decided_at else None, "decision_reason": c.decision_reason}
                        for c, name, acct, call_status in rows]}  # fmt: skip


@router.post("/{credit_id}/decide")
async def decide(credit_id: UUID, body: DecisionIn, request: Request, user: Principal = Deciders) -> dict:
    if body.decision == "refused" and not (body.reason and body.reason.strip()):
        raise HTTPException(422, "Give a reason for refusing; the customer will be told.")
    async with tenant_session(user.org_id) as db:
        credit = (await db.execute(select(Credit).where(Credit.id == credit_id).with_for_update())).scalar_one_or_none()
        if credit is None:
            raise HTTPException(404, "Credit not found.")
        if credit.status != "pending":
            raise HTTPException(409, f"This credit was already {credit.status}.")
        call = await db.get(Call, credit.call_id) if credit.call_id else None
        if call and user.id in (call.started_by, call.handled_by):
            raise HTTPException(403, "You were on this call; another supervisor decides its credit.")
        credit.status = "applied" if body.decision == "approved" else "refused"
        credit.decided_by, credit.decided_at, credit.decision_reason = user.id, datetime.now(UTC), body.reason
        if call:
            db.add(
                CallEvent(
                    org_id=user.org_id,
                    call_id=call.id,
                    kind="credit_decided",
                    data={"credit_id": str(credit_id), "decision": body.decision, "amount": f"{credit.amount:.2f}"},
                )
            )
        audit(
            db,
            user,
            "credit.decided",
            str(credit_id),
            {"decision": body.decision, "amount": f"{credit.amount:.2f}"},
            request,
        )
        call_id, live = (call.id, call.status == "live") if call else (None, False)
    said = (
        await service.decision_reached(
            user.org_id, call_id, {"decision": body.decision, "reason": body.reason, "credit_id": str(credit_id)}
        )
        if live
        else ""
    )
    return {"id": str(credit_id), "status": "applied" if body.decision == "approved" else "refused", "agent_said": said}
