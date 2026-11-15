"""Demo data: customers with services, six months of bills, outages and policies, for both demo organisations.

    python -m seed.generate --customers 200

Deterministic for a seed. Larkspur Telecom carries the planted customers the evaluation and the journeys use
(PLANTED below); their details are fixed so a test can say them on a call.
"""

import argparse
import asyncio
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

from sqlalchemy import select, text

from app.db import dispose_engines, tenant_session
from app.knowledge.index import sections
from app.models.customers import Bill, BillLine, Customer, Outage, Service
from app.models.policies import PolicyDocument, PolicyPassage
from app.redis import close_redis
from seed.demo_users import FERNHILL, LARKSPUR, ensure_demo_users
from seed.policies import FERNHILL as FERNHILL_POLICIES
from seed.policies import LARKSPUR as LARKSPUR_POLICIES

FIRST = ["Olivia", "Jack", "Amira", "Noah", "Isla", "Leo", "Maya", "Oscar", "Zara", "Ethan", "Ruby", "Arjun", "Ellie", "Samuel",
         "Chloe", "Kwame", "Lucy", "Mohammed", "Freya", "Callum", "Aisha", "Finn", "Grace", "Tariq", "Hollie", "Lewis"]  # fmt: skip
LAST = ["Smith", "Patel", "Jones", "Khan", "Williams", "Brown", "Taylor", "Davies", "Evans", "Wilson", "Ahmed", "Thomas", "Roberts",
        "Walker", "Wright", "Hughes", "Green", "Hall", "Clarke", "Lewis", "Begum", "Murphy", "Campbell", "Kelly"]  # fmt: skip
AREAS = ["NG4", "LS6", "M14", "BS7", "CF10", "G12", "B15", "SE5", "EH9", "NE6", "L17", "S10"]
TELECOM = [("broadband", "Fibre 150", D("32.00")), ("broadband", "Fibre 500", D("45.00")), ("mobile", "SIM 30GB", D("12.00")),
           ("mobile", "SIM Unlimited", D("20.00")), ("tv", "TV Essentials", D("15.00"))]  # fmt: skip
ENERGY = [
    ("electricity", "Fixed Saver 12", D("68.00")),
    ("gas", "Fixed Saver 12", D("54.00")),
    ("electricity", "Flexible", D("75.00")),
]


@dataclass(frozen=True)
class Planted:
    key: str
    name: str
    account_number: str
    phone: str
    postcode: str
    date_of_birth: date
    area: str
    services: tuple[tuple[str, str, str], ...]
    note: str


PLANTED = {
    p.key: p
    for p in (
        Planted("outage", "Amelia Hart", "LT100001", "07700900001", "NG4 2AB", date(1985, 3, 14), "NG4",
                (("broadband", "Fibre 150", "32.00"),), "broadband in an area with a live outage"),
        Planted("double_charge", "Tom Okafor", "LT100002", "07700900002", "LS6 3HJ", date(1979, 11, 2), "LS6",
                (("broadband", "Fibre 500", "45.00"), ("tv", "TV Essentials", "15.00")), "last bill charged the Sports add-on twice (12.00)"),
        Planted("fault", "Priya Nair", "LT100003", "07700900003", "M14 5RT", date(1992, 7, 21), "M14",
                (("broadband", "Fibre 150", "32.00"),), "broadband fault with no outage in the area"),
        Planted("cancel", "George Bell", "LT100004", "07700900004", "BS7 8QQ", date(1968, 1, 30), "BS7",
                (("mobile", "SIM Unlimited", "20.00"),), "contract ends in 10 days; wants to cancel"),
        Planted("overdue", "Hannah Price", "LT100005", "07700900005", "CF10 1AA", date(1990, 5, 5), "CF10",
                (("broadband", "Fibre 150", "32.00"), ("mobile", "SIM 30GB", "12.00")), "an overdue bill; asks about paying over time"),
        Planted("missed_engineer", "Daniel Moss", "LT100006", "07700900006", "G12 8QQ", date(1983, 9, 9), "G12",
                (("broadband", "Fibre 500", "45.00"),), "engineer missed yesterday's appointment (30.00 compensation)"),
        Planted("slow", "Sofia Rossi", "LT100007", "07700900007", "B15 2TT", date(1995, 12, 1), "B15",
                (("broadband", "Fibre 500", "45.00"),), "slow speeds for two days; a small goodwill credit fits"),
    )
}  # fmt: skip


def _money(x: float) -> D:
    return D(str(round(x, 2))).quantize(D("0.01"))


async def load_policies(org, documents: dict) -> int:
    async with tenant_session(org) as db:
        n = 0
        for slug, (title, body) in documents.items():
            doc = PolicyDocument(org_id=org, slug=slug, title=title, body=body.strip())
            db.add(doc)
            await db.flush()
            for number, heading, passage in sections(body):
                db.add(
                    PolicyPassage(
                        org_id=org, document_id=doc.id, section=number, title=title, heading=heading, body=passage
                    )
                )
                n += 1
        return n


def _bills(
    rng: random.Random, org, customer: Customer, services: list[Service], today: date, planted: str | None
) -> list[tuple[Bill, list[BillLine]]]:
    out = []
    monthly = sum((s.monthly_price for s in services), D(0))
    for m in range(6, 0, -1):
        issued = today.replace(day=1) - timedelta(days=30 * (m - 1))
        lines = [(f"{s.plan} ({s.kind})", s.monthly_price) for s in services]
        if any(s.kind == "mobile" for s in services) and rng.random() < 0.3:
            lines.append(("Calls and texts outside allowance", _money(rng.uniform(1, 9))))
        if planted == "double_charge" and m == 1:
            lines += [("Sports add-on", D("12.00")), ("Sports add-on", D("12.00"))]
        total = sum((a for _, a in lines), D(0))
        status = "paid" if m > 1 else "due"
        if planted == "overdue" and m <= 2:
            status = "overdue"
        bill = Bill(
            org_id=org,
            customer_id=customer.id,
            period_start=issued,
            period_end=issued + timedelta(days=29),
            issued_on=issued,
            total=total,
            status=status,
        )
        out.append((bill, [BillLine(org_id=org, description=d, amount=a) for d, a in lines]))
    assert monthly >= 0
    return out


async def _customers(
    org, prefix: str, catalogue, n: int, rng: random.Random, today: date, planted: dict[str, Planted]
) -> int:
    async with tenant_session(org) as db:
        people: list[tuple[Customer, list[Service], str | None]] = []
        for p in planted.values():
            c = Customer(org_id=org, account_number=p.account_number, name=p.name, phone=p.phone, postcode=p.postcode, date_of_birth=p.date_of_birth,
                         email=f"{p.name.split()[0].lower()}@example.test")  # fmt: skip
            contract_end = today + timedelta(days=10) if p.key == "cancel" else today + timedelta(days=200)
            svcs = [Service(org_id=org, kind=k, plan=pl, monthly_price=D(price), area=p.area, started_on=today - timedelta(days=500), contract_ends=contract_end)
                    for k, pl, price in p.services]  # fmt: skip
            people.append((c, svcs, p.key))
        for i in range(n):
            area = rng.choice(AREAS)
            c = Customer(org_id=org, account_number=f"{prefix}{200000 + i}", name=f"{rng.choice(FIRST)} {rng.choice(LAST)}", phone=f"07{rng.randint(100000000, 999999999)}",
                         postcode=f"{area} {rng.randint(1, 9)}{rng.choice('ABDEFGHJLNPQRSTUWXYZ')}{rng.choice('ABDEFGHJLNPQRSTUWXYZ')}",
                         date_of_birth=date(rng.randint(1945, 2004), rng.randint(1, 12), rng.randint(1, 28)), vulnerable=rng.random() < 0.05)  # fmt: skip
            picks = rng.sample(catalogue, rng.randint(1, 2))
            svcs = [Service(org_id=org, kind=k, plan=pl, monthly_price=price, area=area, started_on=today - timedelta(days=rng.randint(30, 900)),
                            contract_ends=today + timedelta(days=rng.randint(-200, 600))) for k, pl, price in picks]  # fmt: skip
            people.append((c, svcs, None))
        for c, _, _ in people:
            db.add(c)
        await db.flush()
        for c, svcs, key in people:
            for s in svcs:
                s.customer_id = c.id
                db.add(s)
            for bill, lines in _bills(rng, org, c, svcs, today, key):
                db.add(bill)
                await db.flush()
                for line in lines:
                    line.bill_id = bill.id
                    db.add(line)
        return len(people)


async def generate(seed: int = 7, customers: int = 200, today: date | None = None) -> dict:
    await ensure_demo_users()
    today = today or datetime.now(UTC).date()
    now = datetime.now(UTC)
    rng = random.Random(seed)
    counts = {}
    counts["larkspur_customers"] = await _customers(LARKSPUR, "LT", TELECOM, customers, rng, today, PLANTED)
    counts["fernhill_customers"] = await _customers(FERNHILL, "FE", ENERGY, customers, rng, today, {})
    async with tenant_session(LARKSPUR) as db:
        db.add(Outage(org_id=LARKSPUR, area="NG4", kind="broadband", title="Fibre cable damaged by roadworks in Gedling",
                      started_at=now - timedelta(hours=7), expected_fix=now + timedelta(hours=17)))  # fmt: skip
        db.add(Outage(org_id=LARKSPUR, area="SE5", kind="mobile", title="Mast maintenance, Camberwell", started_at=now - timedelta(days=9),
                      resolved_at=now - timedelta(days=8)))  # fmt: skip
    async with tenant_session(FERNHILL) as db:
        db.add(Outage(org_id=FERNHILL, area="EH9", kind="electricity", title="Planned network work, Marchmont", started_at=now + timedelta(days=2),
                      expected_fix=now + timedelta(days=2, hours=4)))  # fmt: skip
    counts["larkspur_passages"] = await load_policies(LARKSPUR, LARKSPUR_POLICIES)
    counts["fernhill_passages"] = await load_policies(FERNHILL, FERNHILL_POLICIES)
    return counts


async def has_data() -> bool:
    async with tenant_session(LARKSPUR) as db:
        return bool(await db.scalar(text("SELECT EXISTS (SELECT 1 FROM customers)")))


async def planted_customer(key: str) -> Customer:
    async with tenant_session(LARKSPUR) as db:
        return (
            await db.execute(select(Customer).where(Customer.account_number == PLANTED[key].account_number))
        ).scalar_one()


async def main(args) -> None:
    print(await generate(args.seed, args.customers))
    await close_redis()
    await dispose_engines()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--customers", type=int, default=200)
    asyncio.run(main(parser.parse_args()))
