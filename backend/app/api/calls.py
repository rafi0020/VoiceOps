"""Calls: start one, speak or type to the agent, watch them live, take one over, end it."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from app.api.deps import audit, current_user, require_role
from app.calls import service
from app.calls.events import call_stream, org_stream, sse
from app.config import get_settings
from app.db import tenant_session
from app.models.calls import Call, CallEvent, Turn
from app.models.customers import Credit, Customer
from app.security.ratelimit import rate_limit
from app.security.sessions import Principal

router = APIRouter(prefix="/api/calls", tags=["calls"])
Staff = Depends(require_role("agent", "supervisor", "admin"))


class StartIn(BaseModel):
    channel: Literal["voice", "text"] = "text"


class SayIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def call_out(c: Call, customer: str | None = None) -> dict:
    return {"id": str(c.id), "status": c.status, "channel": c.channel, "started_at": c.started_at.isoformat(), "ended_at": c.ended_at.isoformat() if c.ended_at else None,
            "verified": c.verified_customer_id is not None, "customer": customer, "handled_by": str(c.handled_by) if c.handled_by else None,
            "handed_off_reason": c.handed_off_reason, "summary": c.summary, "model_calls": c.model_calls, "cost_usd": float(c.cost_usd)}  # fmt: skip


def _cursor(last_event_id: str | None) -> str:
    return last_event_id if last_event_id and all(p.isdigit() for p in last_event_id.split("-", 1)) else "0-0"


@router.post("", status_code=201, dependencies=[Depends(rate_limit("calls", get_settings().calls_per_minute, 60))])
async def start(body: StartIn, user: Principal = Depends(current_user)) -> dict:
    """Any signed-in person may place a call: the demo's customer line. A public deployment would put a separate,
    rate-limited entry point in front of this."""
    call, greeting = await service.start_call(user.org_id, user.id, body.channel)
    return call_out(call) | {"greeting": greeting}


@router.get("")
async def list_calls(
    user: Principal = Depends(current_user),
    status: str | None = Query(None, max_length=20),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    async with tenant_session(user.org_id) as db:
        stmt = (
            select(Call, Customer.name)
            .outerjoin(Customer, Customer.id == Call.verified_customer_id)
            .order_by(Call.started_at.desc())
            .limit(limit)
        )
        if status == "open":
            stmt = stmt.where(Call.status != "ended")
        elif status:
            stmt = stmt.where(Call.status == status)
        rows = (await db.execute(stmt)).all()
    return {"calls": [call_out(c, name) for c, name in rows]}


@router.get("/live/events")
async def live_events(
    user: Principal = Depends(current_user), last_event_id: str | None = Header(default=None)
) -> StreamingResponse:
    return StreamingResponse(
        sse(org_stream(user.org_id), _cursor(last_event_id)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/{call_id}")
async def get_call(call_id: UUID, user: Principal = Depends(current_user)) -> dict:
    async with tenant_session(user.org_id) as db:
        call = await service.load(db, call_id)
        customer = await db.get(Customer, call.verified_customer_id) if call.verified_customer_id else None
        turns = (await db.execute(select(Turn).where(Turn.call_id == call_id).order_by(Turn.idx))).scalars().all()
        events = (
            (await db.execute(select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.id)))
            .scalars()
            .all()
        )
        credits = (
            (await db.execute(select(Credit).where(Credit.call_id == call_id).order_by(Credit.requested_at)))
            .scalars()
            .all()
        )
    return call_out(call, customer.name if customer else None) | {
        "customer_account": customer.account_number if customer else None,
        "turns": [{"idx": t.idx, "speaker": t.speaker, "text": t.text, "interrupted": t.interrupted, "timings": t.timings, "at": t.created_at.isoformat()} for t in turns],
        "events": [{"kind": e.kind, "data": e.data, "at": e.at.isoformat()} for e in events],
        "credits": [{"id": str(c.id), "amount": f"{c.amount:.2f}", "status": c.status, "reason": c.reason} for c in credits],
    }  # fmt: skip


@router.get("/{call_id}/events")
async def call_events(
    call_id: UUID, user: Principal = Depends(current_user), last_event_id: str | None = Header(default=None)
) -> StreamingResponse:
    async with tenant_session(user.org_id) as db:
        await service.load(db, call_id)
    return StreamingResponse(
        sse(call_stream(call_id), _cursor(last_event_id)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/{call_id}/turns")
async def say(call_id: UUID, body: SayIn, user: Principal = Depends(current_user)) -> dict:
    """A typed customer turn (the voice socket sends spoken ones the same way)."""
    async with tenant_session(user.org_id) as db:
        call = await service.load(db, call_id)
    if call.started_by != user.id:
        from fastapi import HTTPException

        raise HTTPException(403, "Only the caller speaks as the customer on this call.")
    return await service.customer_turn(user.org_id, call_id, body.text)


@router.post("/{call_id}/take-over")
async def take_over(call_id: UUID, request: Request, user: Principal = Staff) -> dict:
    call = await service.take_over(user.org_id, call_id, user.id)
    async with tenant_session(user.org_id) as db:
        audit(db, user, "call.taken_over", str(call_id), None, request)
    return call_out(call)


@router.post("/{call_id}/reply")
async def reply(call_id: UUID, body: SayIn, user: Principal = Staff) -> dict:
    turn = await service.person_reply(user.org_id, call_id, user.id, body.text)
    return {"idx": turn.idx, "text": turn.text}


@router.post("/{call_id}/end")
async def end(call_id: UUID, user: Principal = Depends(current_user)) -> dict:
    async with tenant_session(user.org_id) as db:
        call = await service.load(db, call_id)
        allowed = call.started_by == user.id or call.handled_by == user.id or user.role in ("supervisor", "admin")
    if not allowed:
        from fastapi import HTTPException

        raise HTTPException(403, "Only the caller, the person handling it, or a supervisor ends a call.")
    return {"summary": await service.end_call(user.org_id, call_id)}


@router.get("/{call_id}/latency")
async def latency(call_id: UUID, user: Principal = Depends(current_user)) -> dict:
    async with tenant_session(user.org_id) as db:
        await service.load(db, call_id)
        rows = (
            await db.execute(
                text(
                    "SELECT idx, speaker, timings FROM turns WHERE call_id = :c AND timings <> '{}'::jsonb ORDER BY idx"
                ),
                {"c": call_id},
            )
        ).all()
    return {"turns": [{"idx": r.idx, "speaker": r.speaker, **r.timings} for r in rows]}
