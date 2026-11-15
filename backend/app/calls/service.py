"""A call's life: started, customer turns answered by the agent (or by a person after a take-over), a supervisor's
decision resuming a paused agent, and the end with its CRM note. Turns and events are stored in PostgreSQL and
published live. One turn at a time per call: a Redis lock serialises turns across processes."""

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, text

from app.agent.checkpoint import checkpointer
from app.agent.graph import build_graph, neutralise, resume, run_turn, waiting_for
from app.agent.tools import CallContext, run_tool
from app.calls.events import publish
from app.calls.masking import mask_identifiers
from app.calls.summary import handover_brief, write_summary
from app.config import get_settings
from app.db import tenant_session
from app.llm.base import LLMError
from app.models.calls import Call, CallEvent, Turn
from app.redis import get_redis

GREETING = "Hello, you're through to {org}'s assistant. How can I help today?"
STILL_WAITING = "I'm still waiting for my supervisor on that credit. Is there anything else while we wait?"
ABANDONED = {
    "outcome": "Read the transcript.",
    "follow_up": "",
    "sentiment": "neutral",
    "written_by": "system",
    "unsupported": [],
}
TIME_UP = "We have been talking for a while, so I'm passing you to a colleague who can see everything so far."
MODEL_DOWN = "I'm sorry, I'm having trouble on my side. I'm passing you to a colleague who can see everything so far."
log = logging.getLogger("voiceops.calls")
_graph = None
_graph_lock = asyncio.Lock()


async def graph():
    global _graph
    async with _graph_lock:
        if _graph is None:
            _graph = build_graph(await checkpointer())
    return _graph


LOCK_SECONDS = 30  # a turn holds the call for this lease; a crashed holder frees it within it
LOCK_RENEW_SECONDS = 10  # while a turn runs, its lease is renewed this often
# Compare-and-set in one step: a holder whose lease has run out must not delete the lock someone else now holds.
RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0"
RENEW = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) end return 0"


async def _keep_lease(redis, key: str, token: str) -> None:
    while True:
        await asyncio.sleep(LOCK_RENEW_SECONDS)
        try:
            if not await redis.eval(RENEW, 1, key, token, LOCK_SECONDS):
                log.warning("call lock lost while a turn ran", extra={"key": key})
                return
        except Exception:  # noqa: BLE001 - a Redis blip is retried at the next renewal
            log.warning("could not renew call lock", extra={"key": key}, exc_info=True)


@contextlib.asynccontextmanager
async def call_lock(call_id: UUID, wait_s: float = 60):
    """At most one turn per call at a time, in any process. The lease is renewed while the turn runs."""
    redis, key, token = get_redis(), f"call:{call_id}:lock", uuid4().hex
    deadline = asyncio.get_running_loop().time() + wait_s
    while not await redis.set(key, token, nx=True, ex=LOCK_SECONDS):
        if asyncio.get_running_loop().time() > deadline:
            raise HTTPException(409, "This call is busy with another turn.")
        await asyncio.sleep(0.05)
    keeper = asyncio.create_task(_keep_lease(redis, key, token))
    try:
        yield
    finally:
        keeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await keeper
        await redis.eval(RELEASE, 1, key, token)


async def load(db, call_id: UUID, *, lock: bool = False) -> Call:
    stmt = select(Call).where(Call.id == call_id)
    call = (await db.execute(stmt.with_for_update() if lock else stmt)).scalar_one_or_none()
    if call is None:
        raise HTTPException(404, "Call not found.")
    return call


async def add_turn(
    org_id: UUID, call_id: UUID, speaker: str, said: str, *, timings: dict | None = None, interrupted: bool = False
) -> Turn:
    async with tenant_session(org_id) as db:
        # Numbering is serialised per call: the row lock makes concurrent turns take the next index one at a time.
        await db.execute(select(Call.id).where(Call.id == call_id).with_for_update())
        idx = await db.scalar(select(func.coalesce(func.max(Turn.idx), -1) + 1).where(Turn.call_id == call_id))
        turn = Turn(
            org_id=org_id,
            call_id=call_id,
            idx=idx,
            speaker=speaker,
            text=said,
            timings=timings or {},
            interrupted=interrupted,
        )
        db.add(turn)
        await db.execute(text("UPDATE calls SET last_activity = now() WHERE id = :c"), {"c": call_id})
        await db.flush()
        turn_id = turn.id
    await publish(
        org_id,
        call_id,
        "turn",
        {"turn_id": str(turn_id), "idx": idx, "speaker": speaker, "text": said, "timings": timings or {}},
    )
    return turn


async def start_call(org_id: UUID, user_id: UUID, channel: str) -> tuple[Call, str]:
    settings = get_settings()
    async with tenant_session(org_id) as db:
        # Calls left open (a closed tab, a dropped socket, a restart) are ended first, so they cannot fill the limit.
        await db.execute(text("""UPDATE calls SET status = 'ended', ended_at = now(), summary = CAST(:note AS jsonb)
                                 WHERE status <> 'ended' AND last_activity < now() - make_interval(mins => :m)"""),
                         {"note": json.dumps(ABANDONED | {"reason": f"Ended after {settings.call_idle_minutes} minutes without activity."}),
                          "m": settings.call_idle_minutes})  # fmt: skip
        live = await db.scalar(select(func.count()).select_from(Call).where(Call.status != "ended"))
        if live >= settings.org_max_live_calls:
            raise HTTPException(
                429,
                "Too many calls are in progress for this organisation. Try again shortly.",
                headers={"Retry-After": "30"},
            )
        org_name = await db.scalar(text("SELECT name FROM orgs WHERE id = :o"), {"o": org_id})
        call = Call(org_id=org_id, started_by=user_id, channel=channel)
        db.add(call)
        await db.flush()
        await db.refresh(call)
    greeting = GREETING.format(org=org_name)
    await publish(org_id, call.id, "call_started", {"channel": channel})
    await add_turn(org_id, call.id, "agent", greeting)
    return call, greeting


async def customer_turn(org_id: UUID, call_id: UUID, said: str, *, timings: dict | None = None) -> dict[str, Any]:
    """The customer said something. Returns what to say back (empty when a person is handling the call)."""
    timings = dict(timings or {})
    said = neutralise(said) or "(said nothing the system could hear)"
    async with call_lock(call_id):
        async with tenant_session(org_id) as db:
            call = await load(db, call_id)
        if call.status == "ended":
            raise HTTPException(409, "This call has ended.")
        async with tenant_session(org_id) as db:
            turns = await db.scalar(select(func.count()).select_from(Turn).where(Turn.call_id == call_id))
        if turns >= get_settings().call_max_turns:
            raise HTTPException(409, "This call has reached its length limit; end it and start another.")
        # Until the caller is verified, the details they give (to verify_identity) are kept masked in the transcript.
        shown = said if call.verified_customer_id else mask_identifiers(said)
        customer = await add_turn(org_id, call_id, "customer", shown, timings=timings)
        if call.status == "live" and await _past_time_limit(org_id, call_id):
            minutes = get_settings().call_max_minutes
            await run_tool(
                CallContext(org_id, call_id),
                "hand_off",
                {"reason": f"The call reached its time limit of {minutes} minutes."},
            )
            await _leave_brief(org_id, call_id)
            agent = await add_turn(org_id, call_id, "agent", TIME_UP)
            await publish(org_id, call_id, "call_state", {"status": "handed_off"})
            return {"reply": TIME_UP, "status": "handed_off", "waiting": None, "timings": timings,
                    "customer_idx": customer.idx, "agent_idx": agent.idx}  # fmt: skip
        if call.status == "handed_off":
            return {
                "reply": "",
                "status": call.status,
                "waiting": None,
                "customer_idx": customer.idx,
                "agent_idx": None,
            }
        g = await graph()
        waited = await waiting_for(g, call_id)
        decided = await _decision_for(org_id, waited) if waited else None
        if decided:  # decided, but the decision never reached the call (a failure after it was recorded)
            outcome = await resume(g, call_id, decided)
            reply, waiting = outcome.reply, outcome.waiting
        elif waited:
            reply, waiting = STILL_WAITING, waited
        else:
            started = asyncio.get_running_loop().time()
            try:
                outcome = await run_turn(g, CallContext(org_id, call_id), said)
                reply, waiting = outcome.reply, outcome.waiting
            except LLMError as exc:  # the model is down even after retries and the fallback: a person takes over
                log.warning(
                    "model failed on a call turn; handing over",
                    extra={"call_id": str(call_id), "error": str(exc)[:200]},
                )
                await run_tool(
                    CallContext(org_id, call_id), "hand_off", {"reason": "The assistant could not reach its model."}
                )
                reply, waiting = MODEL_DOWN, None
            timings["agent_ms"] = round((asyncio.get_running_loop().time() - started) * 1000)
        async with tenant_session(org_id) as db:
            now = await load(db, call_id)
            status = now.status
        if now.handled_by is not None:  # a person took the call during this turn: the agent's reply is not given
            reply, waiting = "", None
        if status == "handed_off" and call.status == "live" and now.handled_by is None:
            await _leave_brief(org_id, call_id)  # the agent handed over: the person gets a brief at once
        agent_idx = (
            (await add_turn(org_id, call_id, "agent", reply, timings={"agent_ms": timings.get("agent_ms")})).idx
            if reply
            else None
        )
        if waiting:
            await publish(org_id, call_id, "approval_needed", waiting)
        if status != call.status:
            await publish(org_id, call_id, "call_state", {"status": status})
        return {
            "reply": reply,
            "status": status,
            "waiting": waiting,
            "timings": timings,
            "customer_idx": customer.idx,
            "agent_idx": agent_idx,
        }


async def _past_time_limit(org_id: UUID, call_id: UUID) -> bool:
    async with tenant_session(org_id) as db:
        return bool(
            await db.scalar(
                text("SELECT now() - started_at > make_interval(mins => :m) FROM calls WHERE id = :c"),
                {"m": get_settings().call_max_minutes, "c": call_id},
            )
        )


async def _decision_for(org_id: UUID, waited: dict) -> dict | None:
    async with tenant_session(org_id) as db:
        row = (
            await db.execute(
                text("SELECT status, decision_reason FROM credits WHERE id = :c"), {"c": waited["credit_id"]}
            )
        ).one_or_none()
    if row is None or row.status == "pending":
        return None
    return {
        "decision": "approved" if row.status == "applied" else "refused",
        "reason": row.decision_reason,
        "credit_id": waited["credit_id"],
    }


async def _leave_brief(org_id: UUID, call_id: UUID) -> None:
    async with tenant_session(org_id) as db:
        call = await load(db, call_id, lock=True)
        name = (
            await db.scalar(text("SELECT name FROM customers WHERE id = :c"), {"c": call.verified_customer_id})
            if call.verified_customer_id
            else None
        )
        events = (
            (await db.execute(select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.id)))
            .scalars()
            .all()
        )
        call.summary = handover_brief(call.handed_off_reason, name, [{"kind": e.kind, **e.data} for e in events])


async def set_timings(org_id: UUID, call_id: UUID, idx: int, timings: dict) -> None:
    async with tenant_session(org_id) as db:
        await db.execute(text("UPDATE turns SET timings = timings || CAST(:t AS jsonb) WHERE call_id = :c AND idx = :i"),
                         {"t": json.dumps(timings), "c": call_id, "i": idx})  # fmt: skip


async def mark_interrupted(org_id: UUID, call_id: UUID, idx: int, spoken: str | None) -> None:
    """The customer spoke over the agent: the transcript keeps what was actually said aloud. With `spoken` None nothing
    reached the caller (cut off before the first sentence, held, or dropped): the turn's text is empty, and what the
    agent decided is kept in the event log ("reply_not_heard") for anyone who needs to know."""
    async with tenant_session(org_id) as db:
        if spoken is None:
            decided = await db.scalar(
                text("SELECT text FROM turns WHERE call_id = :c AND idx = :i"), {"c": call_id, "i": idx}
            )
            await db.execute(
                text("UPDATE turns SET interrupted = true, text = '' WHERE call_id = :c AND idx = :i"),
                {"c": call_id, "i": idx},
            )
            db.add(
                CallEvent(org_id=org_id, call_id=call_id, kind="reply_not_heard", data={"idx": idx, "decided": decided})
            )
        else:
            await db.execute(
                text("UPDATE turns SET interrupted = true, text = :s WHERE call_id = :c AND idx = :i"),
                {"s": spoken, "c": call_id, "i": idx},
            )
    await publish(org_id, call_id, "turn_interrupted", {"idx": idx, "spoken": spoken})


async def decision_reached(org_id: UUID, call_id: UUID, decision: dict) -> str:
    """A supervisor decided a credit this call is paused on: the agent continues and says so."""
    async with call_lock(call_id):
        g = await graph()
        waited = await waiting_for(g, call_id)
        if not waited or waited.get("credit_id") != decision.get("credit_id"):
            return ""  # not the credit the call is waiting on: recorded, and read when the call reaches it
        outcome = await resume(g, call_id, decision)
        if outcome.reply:
            turn = await add_turn(org_id, call_id, "agent", outcome.reply)
            await publish(
                org_id, call_id, "agent_reply", {"text": outcome.reply, "idx": turn.idx}
            )  # spoken on the call
        return outcome.reply


async def take_over(org_id: UUID, call_id: UUID, user_id: UUID) -> Call:
    async with tenant_session(org_id) as db:
        call = await load(db, call_id, lock=True)
        if call.status == "ended":
            raise HTTPException(409, "This call has ended.")
        if call.handled_by not in (None, user_id):
            raise HTTPException(409, "Someone else has already taken this call.")
        call.status, call.handled_by = "handed_off", user_id
        call.handed_off_reason = call.handed_off_reason or "Taken over by a person."
        db.add(CallEvent(org_id=org_id, call_id=call_id, kind="take_over", data={"by": str(user_id)}))
    await _leave_brief(org_id, call_id)
    await publish(org_id, call_id, "call_state", {"status": "handed_off", "handled_by": str(user_id)})
    return call


async def person_reply(org_id: UUID, call_id: UUID, user_id: UUID, said: str) -> Turn:
    async with tenant_session(org_id) as db:
        call = await load(db, call_id)
    if call.status != "handed_off" or call.handled_by != user_id:
        raise HTTPException(409, "Take the call over before replying.")
    return await add_turn(org_id, call_id, "person", said)


async def end_call(org_id: UUID, call_id: UUID) -> dict:
    async with tenant_session(org_id) as db:
        call = await load(db, call_id, lock=True)
        if call.status == "ended":
            return call.summary or {}
        turns = (await db.execute(select(Turn).where(Turn.call_id == call_id).order_by(Turn.idx))).scalars().all()
        events = (
            (await db.execute(select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.id)))
            .scalars()
            .all()
        )
        transcript = [(t.speaker, t.text) for t in turns]
        evidence = [{"kind": e.kind, **e.data} for e in events]
    summary = await write_summary(org_id, transcript, evidence, call_id=call_id)
    async with tenant_session(org_id) as db:
        call = await load(db, call_id, lock=True)
        call.status, call.ended_at, call.summary = "ended", datetime.now(UTC), summary
    await publish(org_id, call_id, "call_ended", {"summary": summary})
    return summary
