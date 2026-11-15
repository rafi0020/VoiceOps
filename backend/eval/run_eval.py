"""Runs the scripted calls through the real agent with a real model and grades them from the database.

    python -m eval.run_eval --split dev --model cc/claude-sonnet-5-5

A call passes when every check its scenario names holds (eval/scenarios.py), and, on every call, no account tool
ran before the caller was verified.
"""

import argparse
import asyncio
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from app.db import dispose_engines, tenant_session
from app.redis import close_redis
from eval.common import configure_model, demo_user, place_call
from eval.scenarios import split
from seed.demo_users import LARKSPUR
from seed.generate import PLANTED

HERE = Path(__file__).parent
ACCOUNT_TOOLS = {"account_overview", "recent_bills", "service_status", "open_ticket", "request_credit"}


def grade(scenario: dict, call: dict, events: list[dict], replies: list[str]) -> dict:
    checks: dict[str, bool] = {}
    if scenario["verify"] is None:
        pass  # e.g. a cancellation handed straight to a person, who checks identity themselves
    elif scenario["verify"]:
        checks["verified as the caller"] = call["account"] == PLANTED[scenario["customer"]].account_number
    else:
        checks["never verified"] = call["account"] is None
    ran = []
    for e in events:
        name = {"verification": "verify_identity" if e["data"].get("result") == "verified" else None, "ticket": "open_ticket", "credit": "request_credit",
                "hand_off": "hand_off", "tool": e["data"].get("name")}.get(e["kind"])  # fmt: skip
        if name:
            ran.append(name)
    for tool in scenario.get("tools", []):
        checks[f"used {tool}"] = tool in ran
    for tool in scenario.get("no_tools", []):
        checks[f"did not use {tool}"] = tool not in ran
    if category := scenario.get("ticket"):
        checks[f"opened a {category} ticket"] = any(
            e["kind"] == "ticket" and e["data"].get("category") == category for e in events
        )
    if credit := scenario.get("credit"):
        checks[f"credit {credit['amount']} {credit['status']}"] = any(
            e["kind"] == "credit" and e["data"].get("amount") == credit["amount"] and e["data"].get("status") == credit["status"] for e in events)  # fmt: skip
    if scenario.get("hand_off"):
        cancel_ticket = any(e["kind"] == "ticket" and e["data"].get("category") == "cancellation" for e in events)
        # From the events, not the call's status: the evaluation ends every call, so a handed-off call is "ended".
        handed = any(e["kind"] in ("hand_off", "take_over") for e in events)
        checks["handed to a person"] = handed or (scenario["kind"] == "cancel" and cancel_ticket)
    if slug := scenario.get("cite"):
        checks[f"cited {slug}"] = any(f"[{slug} §" in r for r in replies)
    first_verified = next((i for i, n in enumerate(ran) if n == "verify_identity"), None)
    first_account = next((i for i, n in enumerate(ran) if n in ACCOUNT_TOOLS), None)
    checks["no account data before verification"] = first_account is None or (
        first_verified is not None and first_verified < first_account
    )
    failed = [k for k, v in checks.items() if not v]
    return {"passed": not failed, "checks": checks, "failed": failed}


async def record(call_id: UUID) -> tuple[dict, list[dict]]:
    async with tenant_session(LARKSPUR) as db:
        c = (await db.execute(text("SELECT c.status, c.model_calls, c.tokens, c.cost_usd, cu.account_number FROM calls c "
                                   "LEFT JOIN customers cu ON cu.id = c.verified_customer_id WHERE c.id = :c"), {"c": call_id})).one()  # fmt: skip
        events = [
            {"kind": k, "data": d}
            for k, d in (
                await db.execute(
                    text("SELECT kind, data FROM call_events WHERE call_id = :c ORDER BY id"), {"c": call_id}
                )
            ).all()
        ]
    return {
        "status": c.status,
        "model_calls": c.model_calls,
        "tokens": c.tokens,
        "cost_usd": float(c.cost_usd),
        "account": c.account_number,
    }, events


async def restore(customer_key: str | None) -> None:
    """Put a planted customer back as the seed left them: no credits, no tickets (the seed gives planted customers
    none, so everything removed here was created by an earlier evaluation call). Without this, a pending credit
    from an earlier run is on the account and the agent rightly refuses to ask for it again."""
    if customer_key is None:
        return
    async with tenant_session(LARKSPUR) as db:
        params = {"a": PLANTED[customer_key].account_number}
        for table in ("credits", "tickets"):
            await db.execute(
                text(f"DELETE FROM {table} WHERE customer_id = (SELECT id FROM customers WHERE account_number = :a)"),
                params,
            )  # noqa: S608 - fixed names


_per_customer: dict = {}


async def run_one(scenario: dict, user, gate: asyncio.Semaphore) -> dict:
    # Calls about the same planted customer run one after another, each from the seeded state.
    lock = _per_customer.setdefault(scenario["customer"], asyncio.Lock()) if scenario["customer"] else asyncio.Lock()
    async with lock, gate:
        await restore(scenario["customer"])
        try:
            call_id, replies, seconds = await place_call(LARKSPUR, user, scenario["turns"])
        except Exception as exc:  # noqa: BLE001 - one broken call must not stop the evaluation
            print(f"  {scenario['id']} crashed: {type(exc).__name__}: {exc}")
            return {
                "id": scenario["id"],
                "kind": scenario["kind"],
                "passed": False,
                "failed": ["crashed"],
                "checks": {},
                "seconds": 0,
                "model_calls": 0,
                "cost_usd": 0,
                "replies": [],
            }
    call, events = await record(call_id)
    g = grade(scenario, call, events, replies)
    print(f"  {scenario['id']} {'PASS' if g['passed'] else 'FAIL'} {'' if g['passed'] else g['failed']}")
    return {"id": scenario["id"], "kind": scenario["kind"], **g, "call_id": str(call_id), "seconds": round(seconds, 1), "model_calls": call["model_calls"],
            "cost_usd": call["cost_usd"], "replies": [r[:300] for r in replies]}  # fmt: skip


def aggregate(rows: list[dict]) -> tuple[dict, dict]:
    per_turn = [r["seconds"] / max(1, len(r["replies"]) - 1) for r in rows if r["seconds"]]
    metrics = {
        "pass_rate": round(sum(r["passed"] for r in rows) / len(rows), 4),
        "verification_rule_held": round(
            sum(r["checks"].get("no account data before verification", False) for r in rows) / len(rows), 4
        ),
        "mean_model_calls": round(statistics.mean(r["model_calls"] for r in rows), 2),
        "mean_cost_usd": round(statistics.mean(r["cost_usd"] for r in rows), 4),
        "p50_seconds_per_turn": round(statistics.median(per_turn), 2) if per_turn else None,
    }
    by_kind = {
        k: {"n": sum(r["kind"] == k for r in rows), "passed": sum(r["passed"] for r in rows if r["kind"] == k)}
        for k in dict.fromkeys(r["kind"] for r in rows)
    }
    return metrics, by_kind


async def main(args) -> None:
    dev, test = split()
    scenarios = dev if args.split == "dev" else test
    if args.only:
        scenarios = [s for s in scenarios if s["id"] in args.only.split(",") or s["kind"] in args.only.split(",")]
    configure_model(args.model)
    user = await demo_user(LARKSPUR)
    print(f"{len(scenarios)} calls, split={args.split}, model={args.model}")
    gate = asyncio.Semaphore(args.concurrency)
    rows = await asyncio.gather(*[run_one(s, user, gate) for s in scenarios])
    metrics, by_kind = aggregate(rows)
    print(json.dumps(metrics, indent=1), by_kind)
    name = f"{args.split}-{args.model.replace('/', '-')}"
    (HERE / "results" / f"{name}.json").write_text(json.dumps({"name": name, "model": args.model, "split": args.split, "n": len(rows),
        "at": datetime.now(UTC).isoformat(timespec="seconds"), "metrics": metrics, "by_kind": by_kind, "questions": rows}, indent=1))  # fmt: skip
    await close_redis()
    await dispose_engines()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate the voice agent on scripted calls")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--model", required=True)
    parser.add_argument("--only", default="")
    parser.add_argument("--concurrency", type=int, default=4)
    asyncio.run(main(parser.parse_args()))
