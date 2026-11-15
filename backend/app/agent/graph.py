"""The voice agent as a LangGraph graph, checkpointed in PostgreSQL per call (thread id = call id).

    customer turn -> agent -> tools -> agent -> ... -> END
                       \\-> (a credit pending, the caller told) approval (interrupt, waits for a supervisor) -> agent

The model sees the conversation and the tools; the tools act only through the call's verified customer. A credit
over the limit pauses the graph with `interrupt()`; the supervisor's decision resumes it, from the checkpoint, in
whatever process handles it next. Budgets: model calls within one customer turn; model calls, tokens and cost for the
whole call; the organisation's and all organisations' model spend today. When one is reached the agent apologises and
hands the call to a person. Several credits over the limit in one step wait one after another.
"""

import json
import operator
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import text

from app.agent.prompts import SYSTEM
from app.agent.tools import CallContext, run_tool, specs
from app.config import get_settings
from app.db import system_session, tenant_session
from app.llm import factory
from app.llm.types import Message, ToolCall
from app.obs.tracing import INPUT_TOKENS, OUTPUT_TOKENS, traced

SYSTEM_NOTE = "[Note from the system, not from the customer] "
# The marker the agent's system notes carry. A caller who says it must not be able to pass their words off as a note.
NOTE_MARKER = re.compile(r"\[?\s*note from the system(?:,?\s*not from the customer)?\s*\]?\s*[:\-]?\s*", re.IGNORECASE)


def neutralise(said: str) -> str:
    """The caller's words without the system-note marker in them."""
    return NOTE_MARKER.sub("", said).strip()


OUT_OF_BUDGET = (
    "I'm sorry, I'm not able to sort this out myself. I'm passing you to a colleague who can see everything so far."
)


class CallState(TypedDict):
    messages: Annotated[list[dict], operator.add]
    org_id: str
    call_id: str
    turn_steps: int
    pending: dict | None


def to_message(m: dict) -> Message:
    calls = [ToolCall(c["id"], c["name"], c.get("arguments") or {}) for c in m.get("tool_calls", [])]
    return Message(m["role"], m.get("content", ""), calls, m.get("tool_call_id"))


def _ctx(state: CallState) -> CallContext:
    return CallContext(UUID(state["org_id"]), UUID(state["call_id"]))


async def _usage(ctx: CallContext) -> tuple[int, int, Decimal, str, Decimal]:
    async with tenant_session(ctx.org_id) as db:
        row = (await db.execute(text("SELECT c.model_calls, c.tokens, c.cost_usd, o.name, "
                                     "(SELECT coalesce(sum(cost_usd), 0) FROM calls WHERE started_at >= date_trunc('day', now())) AS org_today "
                                     "FROM calls c JOIN orgs o ON o.id = c.org_id WHERE c.id = :c"), {"c": ctx.call_id})).one()  # fmt: skip
    return row.model_calls, row.tokens, Decimal(row.cost_usd), row.name, Decimal(row.org_today)


async def _spent_today() -> Decimal:
    """Every organisation's model spend today: the global limit bounds what open sign-up can cost."""
    async with system_session() as db:
        return Decimal(
            await db.scalar(
                text("SELECT coalesce(sum(cost_usd), 0) FROM calls WHERE started_at >= date_trunc('day', now())")
            )
        )


async def within_daily_limits(org_id: UUID) -> bool:
    """The organisation's and all organisations' model spend today are under their limits."""
    s = get_settings()
    async with tenant_session(org_id) as db:
        org_today = Decimal(
            await db.scalar(
                text("SELECT coalesce(sum(cost_usd), 0) FROM calls WHERE started_at >= date_trunc('day', now())")
            )
        )
    return org_today < Decimal(str(s.org_daily_cost_usd)) and await _spent_today() < Decimal(
        str(s.global_daily_cost_usd)
    )


def _over(state: CallState, calls: int, tokens: int, cost: Decimal, org_today: Decimal) -> bool:
    s = get_settings()
    return (state["turn_steps"] >= s.turn_max_steps or calls >= s.call_max_model_calls or tokens >= s.call_max_tokens
            or cost >= Decimal(str(s.call_max_cost_usd)) or org_today >= Decimal(str(s.org_daily_cost_usd)))  # fmt: skip


async def agent(state: CallState) -> dict:
    ctx = _ctx(state)
    calls, tokens, cost, org_name, org_today = await _usage(ctx)
    if _over(state, calls, tokens, cost, org_today) or await _spent_today() >= Decimal(
        str(get_settings().global_daily_cost_usd)
    ):
        await run_tool(ctx, "hand_off", {"reason": "The agent reached its limit for this call."})
        return {"messages": [{"role": "assistant", "content": OUT_OF_BUDGET, "budget": True}]}
    client = await factory.get_client(ctx.org_id)
    messages = [Message("system", SYSTEM.format(org=org_name))] + [to_message(m) for m in state["messages"]]
    with traced("model", client.config.model, run_id=ctx.call_id, org_id=ctx.org_id, step=calls) as span:
        response, step_cost = await client.complete(messages, specs(), max_tokens=500)
        span.set_attribute(INPUT_TOKENS, response.usage.input_tokens)
        span.set_attribute(OUTPUT_TOKENS, response.usage.output_tokens)
    async with tenant_session(ctx.org_id) as db:
        await db.execute(text("UPDATE calls SET model_calls = model_calls + 1, tokens = tokens + :t, cost_usd = cost_usd + :c, last_activity = now() WHERE id = :id"),
                         {"t": response.usage.input_tokens + response.usage.output_tokens, "c": step_cost, "id": ctx.call_id})  # fmt: skip
    message = {"role": "assistant", "content": response.text or "",
               "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in response.tool_calls]}  # fmt: skip
    return {"messages": [message], "turn_steps": state["turn_steps"] + 1}


async def tools(state: CallState) -> dict:
    ctx = _ctx(state)
    out, pending = [], []
    for call in state["messages"][-1]["tool_calls"]:
        with traced("tool", call["name"], run_id=ctx.call_id, org_id=ctx.org_id, step=state["turn_steps"]):
            result = await run_tool(ctx, call["name"], call.get("arguments") or {})
        if result.get("status") == "needs_approval":
            pending.append({"credit_id": result["credit_id"], "amount": result["amount"]})
        out.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, default=str)})
    return {"messages": out, "pending": (state.get("pending") or []) + pending or None}


async def _decided(ctx: CallContext, credit_id: str) -> tuple[str, str | None]:
    async with tenant_session(ctx.org_id) as db:
        row = (
            await db.execute(text("SELECT status, decision_reason FROM credits WHERE id = :c"), {"c": credit_id})
        ).one()
    return row.status, row.decision_reason


async def approval(state: CallState) -> dict:
    """Waits for a supervisor on the first credit still pending, then the next. The credit's row is the truth: a
    credit decided while the call waited on another is not waited for again. This node runs again from its start
    when it is resumed, so nothing before `interrupt` has side effects."""
    ctx, (first, *rest) = _ctx(state), state["pending"]
    status, reason = await _decided(ctx, first["credit_id"])
    if status == "pending":
        decision = interrupt({"kind": "credit_approval", **first})
        status = {"approved": "applied", "refused": "refused"}.get(decision.get("decision"), "pending")
        reason = decision.get("reason") or reason
    notes = {"applied": f"A supervisor approved the credit of {first['amount']}; it is now on the account.",
             "refused": f"A supervisor did not approve the credit of {first['amount']}. Reason: {reason or 'none given'}.",
             "pending": f"The supervisor has not decided the credit of {first['amount']} yet. Tell the customer they will hear back within two working days."}  # fmt: skip
    return {"messages": [{"role": "user", "content": SYSTEM_NOTE + notes[status]}], "pending": rest or None}


def after_agent(state: CallState) -> str:
    """Tools if the model asked for any; otherwise, with a credit pending, the call waits for a supervisor only after
    the agent has told the caller so."""
    last = state["messages"][-1]
    if last.get("tool_calls"):
        return "tools"
    return "approval" if state.get("pending") and not last.get("budget") else END


def after_approval(state: CallState) -> str:
    return "approval" if state.get("pending") else "agent"


def build_graph(checkpointer):
    g = StateGraph(CallState)
    g.add_node("agent", agent)
    g.add_node("tools", tools)
    g.add_node("approval", approval)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", after_agent, ["tools", "approval", END])
    g.add_edge("tools", "agent")
    g.add_conditional_edges("approval", after_approval, ["approval", "agent"])
    return g.compile(checkpointer=checkpointer)


@dataclass
class TurnOutcome:
    reply: str  # what the agent says, to be spoken
    waiting: dict[str, Any] | None  # an approval the graph is paused on, if any


def _config(call_id: UUID) -> dict:
    return {"configurable": {"thread_id": str(call_id)}}


async def _outcome(graph, call_id: UUID, before: int) -> TurnOutcome:
    state = await graph.aget_state(_config(call_id))
    new = state.values.get("messages", [])[before:]
    said = " ".join(m["content"].strip() for m in new if m["role"] == "assistant" and m.get("content", "").strip())
    waiting = next((i.value for task in state.tasks for i in task.interrupts), None)
    return TurnOutcome(said, waiting)


async def waiting_for(graph, call_id: UUID) -> dict | None:
    state = await graph.aget_state(_config(call_id))
    return next((i.value for task in state.tasks for i in task.interrupts), None)


async def run_turn(graph, ctx: CallContext, customer_text: str) -> TurnOutcome:
    before = len((await graph.aget_state(_config(ctx.call_id))).values.get("messages", []))
    entry = {
        "messages": [{"role": "user", "content": customer_text}],
        "org_id": str(ctx.org_id),
        "call_id": str(ctx.call_id),
        "turn_steps": 0,
        "pending": None,
    }
    await graph.ainvoke(entry, _config(ctx.call_id))
    return await _outcome(graph, ctx.call_id, before)


async def resume(graph, call_id: UUID, decision: dict) -> TurnOutcome:
    """Continue a call paused for approval with the supervisor's decision: approved, refused (with reason) or later."""
    before = len((await graph.aget_state(_config(call_id))).values.get("messages", []))
    await graph.ainvoke(Command(resume=decision), _config(call_id))
    return await _outcome(graph, call_id, before)
