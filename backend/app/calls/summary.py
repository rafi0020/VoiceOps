"""The CRM note written when a call ends. Every figure in it must appear in the transcript or the call's events;
figures that do not are removed and listed, the way the other systems ground their reports."""

import json
import re
from decimal import Decimal

from sqlalchemy import text as sql

from app.agent.graph import within_daily_limits
from app.agent.prompts import SUMMARY
from app.db import tenant_session
from app.llm import factory
from app.llm.types import Message

NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
KEYS = ("reason", "outcome", "follow_up", "sentiment")


def _numbers(text: str) -> set[str]:
    out = set()
    for raw in NUMBER.findall(text):
        try:
            out.add(f"{Decimal(raw.replace(',', '')).normalize():f}")
        except ArithmeticError:
            continue
    return out


AMOUNT = re.compile(r"[£$€]\s?\d[\d,]*(?:\.\d+)?|(?<![\w.])\d[\d,]*\.\d{2}(?!\d)")


def ground(summary: dict, evidence: str, trusted: str | None = None) -> dict:
    """Remove any sentence with a figure not in the evidence, and list what was removed. An amount (money, or a figure
    with pence) must also appear in `trusted`: the agent's turns and the call's events, not what the caller said."""
    known, trusted_known = _numbers(evidence), _numbers(evidence if trusted is None else trusted)
    removed = []
    for key in ("reason", "outcome", "follow_up"):
        kept = []
        for sentence in re.split(r"(?<=[.!?])\s+", str(summary.get(key, "")).strip()):
            if not sentence:
                continue
            amounts = set().union(*(_numbers(a) for a in AMOUNT.findall(sentence)))
            if _numbers(sentence) <= known and amounts <= trusted_known:
                kept.append(sentence)
            else:
                removed.append(sentence)
        summary[key] = " ".join(kept)
    summary["unsupported"] = removed
    return summary


MAX_TRANSCRIPT = 20_000  # characters the model reads: the start of the call and its most recent part


def _bounded(lines: str) -> str:
    if len(lines) <= MAX_TRANSCRIPT:
        return lines
    return lines[:4000] + "\n[... middle of the call omitted ...]\n" + lines[-(MAX_TRANSCRIPT - 4000) :]


def handover_brief(reason: str | None, customer: str | None, events: list[dict]) -> dict:
    """What a person taking the call sees at once, built from the call's events (no model, nothing to ground)."""
    done = [f"Verified as {customer}." if customer else "Not verified."]
    done += [f"Credit {e['amount']} {e['status']}." for e in events if e.get("kind") == "credit"]
    done += [f"Ticket opened ({e['category']}): {e['summary']}" for e in events if e.get("kind") == "ticket"]
    return {"reason": reason or "Handed to a person.", "outcome": " ".join(done), "follow_up": "A person has the call.",
            "sentiment": "neutral", "written_by": "system", "stage": "hand_off", "unsupported": []}  # fmt: skip


async def write_summary(org_id, transcript: list[tuple[str, str]], events: list[dict], call_id=None) -> dict:
    lines = "\n".join(f"{who}: {said}" for who, said in transcript)
    evidence = lines + "\n" + json.dumps(events, default=str)
    data = {}
    try:
        if not await within_daily_limits(org_id):
            raise RuntimeError("over the daily model spend")
        client = await factory.get_client(org_id)
        response, cost = await client.complete(
            [
                Message("system", SUMMARY),
                Message("user", f"Transcript:\n{_bounded(lines)}\n\nEvents:\n{json.dumps(events, default=str)[:6000]}"),
            ],
            [],
            # Reasoning models spend part of this budget before writing; at 400 a long call's note was cut off.
            max_tokens=1200,
        )
        if call_id is not None:
            async with tenant_session(org_id) as db:
                await db.execute(sql("UPDATE calls SET model_calls = model_calls + 1, tokens = tokens + :t, cost_usd = cost_usd + :c WHERE id = :id"),
                                 {"t": response.usage.input_tokens + response.usage.output_tokens, "c": cost, "id": call_id})  # fmt: skip
        text = response.text.strip()
        data = json.loads(text[text.find("{") : text.rfind("}") + 1]) if "{" in text else {}
    except Exception:  # noqa: BLE001 - a summary must never block ending a call; a plain one is written instead
        data = {}
    if not all(k in data for k in KEYS):  # no usable note from the model: a plain one, with nothing to ground
        return {"reason": "Not summarised automatically.", "outcome": "Read the transcript.", "follow_up": "", "sentiment": "neutral",
                "written_by": "system", "unsupported": []}  # fmt: skip
    trusted = (
        "\n".join(f"{who}: {said}" for who, said in transcript if who != "customer")
        + "\n"
        + json.dumps(events, default=str)
    )
    return ground({k: data.get(k, "") for k in KEYS} | {"written_by": "model"}, evidence, trusted)
