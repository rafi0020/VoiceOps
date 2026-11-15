"""What the voice agent can do. Every tool runs for one call, under that call's organisation (row-level security),
and every account tool acts on the customer the server verified on this call: the model never supplies a
customer id, so nothing it says can point a tool at another account.

Each tool returns a plain dict (what the model reads) and records a call event (what people and the evaluation
read). A ToolError is returned to the model as an error it can act on, never raised to the caller.
"""

import hashlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select, text

from app.config import get_settings
from app.db import tenant_session
from app.knowledge.search import search
from app.llm.types import ToolSpec
from app.models.calls import Call, CallEvent
from app.models.customers import Bill, BillLine, Credit, Customer, Outage, Service, Ticket
from app.redis import get_redis

MAX_FAILURES = 3


class ToolError(Exception):
    """Something the model should hear and act on (ask again, verify first, hand over)."""


@dataclass(frozen=True)
class CallContext:
    org_id: UUID
    call_id: UUID


# --- reading what a caller says -------------------------------------------------------------------------------

DIGITS = {"zero": "0", "oh": "0", "o": "0", "nought": "0", "one": "1", "two": "2", "to": "2", "too": "2", "three": "3", "four": "4", "for": "4",
          "five": "5", "six": "6", "seven": "7", "eight": "8", "ate": "8", "nine": "9"}  # fmt: skip
MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        1,
    )
}


def spoken_code(value: str) -> str:
    """'L T one zero zero zero zero one' or 'lt-100 001' -> 'LT100001'. Speech recognition spells numbers either way."""
    out = []
    for word in re.split(r"[\s,.\-]+", value.lower()):
        if not word:
            continue
        if word in ("double", "triple"):
            out.append(word)
            continue
        token = DIGITS.get(word, word)
        if out and out[-1] in ("double", "triple"):
            out[-1:] = [token * (2 if out[-1] == "double" else 3)]
        else:
            out.append(token)
    return "".join(t for t in out if t not in ("double", "triple")).upper()


ORDINALS = {
    w: i
    for i, w in enumerate(
        [
            "first",
            "second",
            "third",
            "fourth",
            "fifth",
            "sixth",
            "seventh",
            "eighth",
            "ninth",
            "tenth",
            "eleventh",
            "twelfth",
            "thirteenth",
            "fourteenth",
            "fifteenth",
            "sixteenth",
            "seventeenth",
            "eighteenth",
            "nineteenth",
            "twentieth",
        ],
        1,
    )
}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
SMALL = {
    w: i
    for i, w in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
        ]
    )
}


def _spoken_day(words: list[str]) -> int | None:
    """'fourteenth' -> 14, 'twenty first' -> 21, 'thirtieth' -> 30."""
    for i, w in enumerate(words):
        if w in ORDINALS:
            return ORDINALS[w]
        if w in ("thirtieth",):
            return 30
        if w in TENS and i + 1 < len(words) and words[i + 1] in ORDINALS and ORDINALS[words[i + 1]] < 10:
            return TENS[w] + ORDINALS[words[i + 1]]
    return None


def _spoken_year(words: list[str]) -> int | None:
    """'nineteen eighty five' -> 1985, 'two thousand and four' -> 2004, 'two thousand' -> 2000."""
    for i, w in enumerate(words):
        if w in ("nineteen", "eighteen") and i + 1 < len(words) and words[i + 1] in TENS:
            unit = SMALL.get(words[i + 2], 0) if i + 2 < len(words) and SMALL.get(words[i + 2], 10) < 10 else 0
            return SMALL[w] * 100 + TENS[words[i + 1]] + unit
        if w == "two" and i + 1 < len(words) and words[i + 1] == "thousand":
            rest = [x for x in words[i + 2 : i + 5] if x != "and"]
            return 2000 + (SMALL.get(rest[0], 0) if rest and SMALL.get(rest[0], 20) < 20 else 0)
    return None


def spoken_date(value: str) -> date | None:
    """'1985-03-14', '14/03/1985', '14 March 1985', 'March 14th 1985', 'the fourteenth of March nineteen eighty five'."""
    v = value.strip().lower().replace(",", " ")
    for pattern in (r"^(\d{4})-(\d{1,2})-(\d{1,2})$", r"^(\d{1,2})[/.](\d{1,2})[/.](\d{4})$"):
        if m := re.match(pattern, v):
            parts = [int(x) for x in m.groups()]
            y, mo, d = parts if pattern.startswith("^(\\d{4})") else (parts[2], parts[1], parts[0])
            try:
                return date(y, mo, d)
            except ValueError:
                return None
    words = re.findall(r"[a-z]+|\d+", v)
    numbers = [int(re.sub(r"\D", "", w)) for w in re.findall(r"\d+", v)]
    day = next((n for n in numbers if n <= 31), None) or _spoken_day(words)
    year = next((n for n in numbers if n > 1900), None) or _spoken_year(words)
    month = next((MONTHS[w] for w in words if w in MONTHS), None)
    if day and year and month:
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def _postcode(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", spoken_code(value))


# --- arguments -----------------------------------------------------------------------------------------------


class VerifyArgs(BaseModel):
    account_number: str | None = Field(
        default=None,
        max_length=60,
        description="The account number exactly as the caller said it, e.g. 'L T one zero zero'; do not convert spoken digits",
    )
    phone: str | None = Field(
        default=None, max_length=40, description="Or the phone number on the account, exactly as said"
    )
    postcode: str = Field(max_length=20)
    date_of_birth: str = Field(max_length=40, description="As said, e.g. 14 March 1985")


class SearchArgs(BaseModel):
    query: str = Field(min_length=2, max_length=300)


class NoArgs(BaseModel):
    pass


class BillsArgs(BaseModel):
    count: int = Field(default=3, ge=1, le=6)


class TicketArgs(BaseModel):
    category: Literal["fault", "billing", "complaint", "moving", "cancellation", "other"]
    summary: str = Field(min_length=5, max_length=600)


class CreditArgs(BaseModel):
    amount: str = Field(max_length=12, description="In the account's currency, e.g. 9.50")
    reason: str = Field(min_length=5, max_length=300)


class HandOffArgs(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


# --- helpers ---------------------------------------------------------------------------------------------------


async def _call(db, ctx: CallContext, *, lock: bool = False) -> Call:
    stmt = select(Call).where(Call.id == ctx.call_id)
    call = (await db.execute(stmt.with_for_update() if lock else stmt)).scalar_one_or_none()
    if call is None:
        raise ToolError("This call no longer exists.")
    return call


async def _customer(db, ctx: CallContext) -> Customer:
    call = await _call(db, ctx)
    if call.verified_customer_id is None:
        raise ToolError(
            "The caller is not verified yet. Ask for the account number or phone number, the postcode and the date of birth, then call verify_identity."
        )
    return await db.get(Customer, call.verified_customer_id)


async def _live(db, ctx: CallContext) -> None:
    if (await _call(db, ctx)).status != "live":
        raise ToolError("A person has this call now. Do not change the account; the person will take it from here.")


def _failure_keys(ctx: CallContext, identifier: str, placed_by: UUID | None) -> tuple[str, str]:
    digest = hashlib.sha256(f"{ctx.org_id}:{identifier}".encode()).hexdigest()[:32]  # no account number in Redis
    return f"verify:fail:acct:{digest}", f"verify:fail:user:{placed_by or ctx.call_id}"


def _event(db, ctx: CallContext, kind: str, data: dict) -> None:
    db.add(CallEvent(org_id=ctx.org_id, call_id=ctx.call_id, kind=kind, data=data))


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


# --- tools -----------------------------------------------------------------------------------------------------


async def verify_identity(ctx: CallContext, args: VerifyArgs) -> dict:
    if not (args.account_number or args.phone):
        raise ToolError("Ask for the account number or the phone number on the account.")
    async with tenant_session(ctx.org_id) as db:
        call = await _call(db, ctx, lock=True)  # one check at a time per call, so the failure count cannot race
        if call.verification_failures >= MAX_FAILURES:
            raise ToolError(
                "Verification is locked for this call after three failed attempts. Offer to hand the call to a person."
            )
        identifier = (
            spoken_code(args.account_number)
            if args.account_number
            else re.sub(r"\D", "", spoken_code(args.phone or ""))
        )
        settings, redis = get_settings(), get_redis()
        account_key, user_key = _failure_keys(ctx, identifier, call.started_by)
        if (
            int(await redis.get(account_key) or 0) >= settings.verify_account_max_failures
            or int(await redis.get(user_key) or 0) >= settings.verify_user_max_failures
        ):
            raise ToolError("There have been too many failed checks recently. Offer to hand the call to a person.")
        stmt = select(Customer)
        if args.account_number:
            stmt = stmt.where(Customer.account_number == spoken_code(args.account_number))
        else:
            stmt = stmt.where(Customer.phone == re.sub(r"\D", "", spoken_code(args.phone or "")))
        matches = (await db.execute(stmt)).scalars().all()
        if not args.account_number and len(matches) > 1:
            # Phone numbers are not unique: a shared number cannot say whose account this is. Neither a success nor a
            # failed check (nothing was matched to check), and nothing about the other accounts is said.
            return {"verified": False, "attempts_left": MAX_FAILURES - call.verification_failures,
                    "say": "Ask for the account number on the account instead."}  # fmt: skip
        customer = matches[0] if matches else None
        born = spoken_date(args.date_of_birth)
        ok = (customer is not None and born == customer.date_of_birth
              and _postcode(args.postcode) == re.sub(r"[^A-Z0-9]", "", customer.postcode.upper()))  # fmt: skip
        if ok and call.verified_customer_id not in (None, customer.id):
            raise ToolError("This call is already verified for another account. One account per call.")
        if not ok:
            for key, seconds in ((account_key, 86400), (user_key, 3600)):  # across calls, not just this one
                await redis.incr(key)
                await redis.expire(key, seconds, nx=True)
            call.verification_failures += 1
            _event(db, ctx, "verification", {"result": "failed", "attempt": call.verification_failures})
            left = MAX_FAILURES - call.verification_failures
            return {"verified": False, "attempts_left": left,
                    "say": "Those details do not match our records." + (" Ask the caller to check them." if left else " Verification is now locked for this call.")}  # fmt: skip
        call.verified_customer_id = customer.id
        _event(db, ctx, "verification", {"result": "verified", "customer_id": str(customer.id)})
        return {"verified": True, "first_name": customer.name.split()[0]}


async def search_policies(ctx: CallContext, args: SearchArgs) -> dict:
    async with tenant_session(ctx.org_id) as db:
        found = await search(db, args.query, k=4)
        _event(
            db, ctx, "tool", {"name": "search_policies", "query": args.query, "citations": [p.citation for p in found]}
        )
    if not found:
        return {"passages": [], "say": "No policy covers this; do not guess. Offer to hand the call to a person."}
    return {"passages": [{"cite": p.citation, "heading": p.heading, "text": p.body} for p in found]}


async def account_overview(ctx: CallContext, _: NoArgs) -> dict:
    async with tenant_session(ctx.org_id) as db:
        c = await _customer(db, ctx)
        services = (
            (await db.execute(select(Service).where(Service.customer_id == c.id, Service.status == "active")))
            .scalars()
            .all()
        )
        owed = await db.scalar(
            select(func.coalesce(func.sum(Bill.total), 0)).where(
                Bill.customer_id == c.id, Bill.status.in_(("due", "overdue"))
            )
        )
        overdue = await db.scalar(
            select(func.count()).select_from(Bill).where(Bill.customer_id == c.id, Bill.status == "overdue")
        )
        credits = (
            (
                await db.execute(
                    select(Credit).where(Credit.customer_id == c.id).order_by(Credit.requested_at.desc()).limit(5)
                )
            )
            .scalars()
            .all()
        )
        _event(db, ctx, "tool", {"name": "account_overview"})
    return {"name": c.name, "account_number": c.account_number, "balance_due": _money(owed), "overdue_bills": overdue,
            "services": [{"kind": s.kind, "plan": s.plan, "monthly_price": _money(s.monthly_price), "contract_ends": s.contract_ends.isoformat() if s.contract_ends else None}
                         for s in services],
            "recent_credits": [{"amount": _money(cr.amount), "status": cr.status, "reason": cr.reason} for cr in credits]}  # fmt: skip


async def recent_bills(ctx: CallContext, args: BillsArgs) -> dict:
    async with tenant_session(ctx.org_id) as db:
        c = await _customer(db, ctx)
        bills = (
            (
                await db.execute(
                    select(Bill).where(Bill.customer_id == c.id).order_by(Bill.issued_on.desc()).limit(args.count)
                )
            )
            .scalars()
            .all()
        )
        lines = (await db.execute(select(BillLine).where(BillLine.bill_id.in_([b.id for b in bills])))).scalars().all()
        _event(db, ctx, "tool", {"name": "recent_bills", "count": len(bills)})
    by_bill: dict = {}
    for line in lines:
        by_bill.setdefault(line.bill_id, []).append({"item": line.description, "amount": _money(line.amount)})
    return {
        "bills": [
            {
                "issued_on": b.issued_on.isoformat(),
                "total": _money(b.total),
                "status": b.status,
                "lines": by_bill.get(b.id, []),
            }
            for b in bills
        ]
    }


async def service_status(ctx: CallContext, _: NoArgs) -> dict:
    now = datetime.now(UTC)
    async with tenant_session(ctx.org_id) as db:
        c = await _customer(db, ctx)
        services = (
            (await db.execute(select(Service).where(Service.customer_id == c.id, Service.status == "active")))
            .scalars()
            .all()
        )
        out = []
        for s in services:
            outages = (await db.execute(select(Outage).where(Outage.area == s.area, Outage.kind == s.kind, Outage.started_at <= now,
                                                              (Outage.resolved_at.is_(None)) | (Outage.resolved_at >= now - timedelta(days=7))))).scalars().all()  # fmt: skip
            out.append({"service": f"{s.plan} ({s.kind})", "outages": [{"title": o.title, "ongoing": o.resolved_at is None,
                        "expected_fix": o.expected_fix.isoformat(timespec="minutes") if o.expected_fix and o.resolved_at is None else None} for o in outages]})  # fmt: skip
        _event(
            db,
            ctx,
            "tool",
            {"name": "service_status", "ongoing": sum(1 for s in out for o in s["outages"] if o["ongoing"])},
        )
    return {"services": out}


async def open_ticket(ctx: CallContext, args: TicketArgs) -> dict:
    async with tenant_session(ctx.org_id) as db:
        c = await _customer(db, ctx)
        await _live(db, ctx)
        ticket = Ticket(
            org_id=ctx.org_id,
            customer_id=c.id,
            call_id=ctx.call_id,
            category=args.category,
            summary=args.summary,
            opened_by="ai",
        )
        db.add(ticket)
        await db.flush()
        _event(db, ctx, "ticket", {"ticket_id": str(ticket.id), "category": args.category, "summary": args.summary})
        return {"ticket_reference": str(ticket.id)[:8].upper(), "category": args.category}


async def credit_limit(db) -> Decimal:
    limit = await db.scalar(text("SELECT credit_limit FROM org_call_settings"))
    return Decimal(str(limit if limit is not None else get_settings().credit_limit))


async def request_credit(ctx: CallContext, args: CreditArgs) -> dict:
    try:
        amount = Decimal(args.amount.replace(",", "").strip().lstrip("£$€")).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ToolError("Give the amount as a number, for example 9.50.") from exc
    if amount <= 0 or amount > Decimal(500):
        raise ToolError("A credit must be more than 0 and at most 500.00; larger amounts are for a person to handle.")
    async with tenant_session(ctx.org_id) as db:
        c = await _customer(db, ctx)
        await _live(db, ctx)
        limit = await credit_limit(db)
        # The limit is per call, not per credit: several small credits cannot add up past it without a supervisor.
        # And per customer over 30 days, so calling back does not reset it.
        applied = await db.scalar(
            select(func.coalesce(func.sum(Credit.amount), 0)).where(
                Credit.call_id == ctx.call_id, Credit.status == "applied"
            )
        )
        recent = await db.scalar(
            select(func.coalesce(func.sum(Credit.amount), 0)).where(
                Credit.customer_id == c.id, Credit.status == "applied", Credit.decided_by.is_(None),
                Credit.requested_at >= datetime.now(UTC) - timedelta(days=30),
            )
        )  # fmt: skip
        within = applied + amount <= limit and recent + amount <= Decimal(str(get_settings().customer_credit_30d))
        status = "applied" if within else "pending"
        credit = Credit(
            org_id=ctx.org_id, customer_id=c.id, call_id=ctx.call_id, amount=amount, reason=args.reason, status=status
        )
        db.add(credit)
        await db.flush()
        _event(
            db,
            ctx,
            "credit",
            {"credit_id": str(credit.id), "amount": _money(amount), "status": status, "reason": args.reason},
        )
        if status == "applied":
            return {"status": "applied", "amount": _money(amount)}
        return {"status": "needs_approval", "credit_id": str(credit.id), "amount": _money(amount), "limit": _money(limit),
                "say": "Tell the customer a supervisor must approve this credit and they will hear back within two working days."}  # fmt: skip


async def hand_off(ctx: CallContext, args: HandOffArgs) -> dict:
    async with tenant_session(ctx.org_id) as db:
        call = await _call(db, ctx, lock=True)
        if call.status == "live":
            call.status = "handed_off"
            call.handed_off_reason = args.reason
        _event(db, ctx, "hand_off", {"reason": args.reason})
    return {
        "handed_off": True,
        "say": "Tell the customer you are passing them to a colleague who can see everything so far.",
    }


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    run: Callable[[CallContext, Any], Awaitable[dict]]
    needs_verification: bool


TOOLS = {t.name: t for t in (
    Tool("verify_identity", "Check who the caller is: the account number or the phone number on the account, plus the postcode and date of birth. Required before any account detail.", VerifyArgs, verify_identity, False),
    Tool("search_policies", "Search the company's policies. Answer policy questions only from these passages and cite them as [doc §section].", SearchArgs, search_policies, False),
    Tool("account_overview", "The verified caller's plan, services, balance due and recent credits.", NoArgs, account_overview, True),
    Tool("recent_bills", "The verified caller's most recent bills with their lines.", BillsArgs, recent_bills, True),
    Tool("service_status", "Outages affecting the verified caller's services, ongoing or in the last 7 days.", NoArgs, service_status, True),
    Tool("open_ticket", "Open a ticket for the verified caller (fault, billing, complaint, moving, cancellation, other).", TicketArgs, open_ticket, True),
    Tool("request_credit", "Credit the verified caller's account. Up to the limit per call it is applied; above it a supervisor must approve.", CreditArgs, request_credit, True),
    Tool("hand_off", "Pass the call to a person: when asked, when the caller is very upset, for cancellations or bereavement, or after two failed attempts to help.", HandOffArgs, hand_off, False),
)}  # fmt: skip


def specs() -> list[ToolSpec]:
    return [ToolSpec(t.name, t.description, t.args.model_json_schema()) for t in TOOLS.values()]


async def run_tool(ctx: CallContext, name: str, arguments: dict) -> dict:
    """Run a tool by name for this call. Errors the model can act on come back as {"error": ...}."""
    tool = TOOLS.get(name)
    if tool is None:
        return {"error": f"There is no tool called {name}."}
    try:
        args = tool.args.model_validate(arguments or {})
    except ValidationError as exc:
        return {
            "error": "Invalid arguments: "
            + "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())[:400]
        }
    try:
        return await tool.run(ctx, args)
    except ToolError as exc:
        return {"error": str(exc)}
