"""Customer records for people: search, and one customer's services, bills, tickets, credits and calls."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select

from app.api.deps import require_role
from app.db import tenant_session
from app.models.calls import Call
from app.models.customers import Bill, Credit, Customer, Service, Ticket
from app.security.sessions import Principal

router = APIRouter(prefix="/api/customers", tags=["customers"])
Staff = Depends(require_role("agent", "supervisor", "admin"))


@router.get("")
async def find(q: str = Query("", max_length=100), user: Principal = Staff) -> dict:
    async with tenant_session(user.org_id) as db:
        stmt = select(Customer).order_by(Customer.name).limit(50)
        if q.strip():
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(Customer.name.ilike(like), Customer.account_number.ilike(like), Customer.phone.ilike(like))
            )
        rows = (await db.execute(stmt)).scalars().all()
    return {
        "customers": [
            {"id": str(c.id), "name": c.name, "account_number": c.account_number, "postcode": c.postcode} for c in rows
        ]
    }


@router.get("/{customer_id}")
async def one(customer_id: UUID, user: Principal = Staff) -> dict:
    async with tenant_session(user.org_id) as db:
        c = await db.get(Customer, customer_id)
        if c is None:
            raise HTTPException(404, "Customer not found.")
        services = (await db.execute(select(Service).where(Service.customer_id == c.id))).scalars().all()
        bills = (
            (await db.execute(select(Bill).where(Bill.customer_id == c.id).order_by(Bill.issued_on.desc()).limit(12)))
            .scalars()
            .all()
        )
        tickets = (
            (
                await db.execute(
                    select(Ticket).where(Ticket.customer_id == c.id).order_by(Ticket.created_at.desc()).limit(20)
                )
            )
            .scalars()
            .all()
        )
        credits = (
            (
                await db.execute(
                    select(Credit).where(Credit.customer_id == c.id).order_by(Credit.requested_at.desc()).limit(20)
                )
            )
            .scalars()
            .all()
        )
        calls = (
            (
                await db.execute(
                    select(Call).where(Call.verified_customer_id == c.id).order_by(Call.started_at.desc()).limit(20)
                )
            )
            .scalars()
            .all()
        )
    return {"id": str(c.id), "name": c.name, "account_number": c.account_number, "phone": c.phone, "postcode": c.postcode, "email": c.email, "vulnerable": c.vulnerable,
            "services": [{"kind": s.kind, "plan": s.plan, "monthly_price": f"{s.monthly_price:.2f}", "area": s.area, "status": s.status,
                          "contract_ends": s.contract_ends.isoformat() if s.contract_ends else None} for s in services],
            "bills": [{"issued_on": b.issued_on.isoformat(), "total": f"{b.total:.2f}", "status": b.status} for b in bills],
            "tickets": [{"id": str(t.id), "category": t.category, "summary": t.summary, "status": t.status, "opened_by": t.opened_by, "created_at": t.created_at.isoformat()} for t in tickets],
            "credits": [{"amount": f"{cr.amount:.2f}", "status": cr.status, "reason": cr.reason, "requested_at": cr.requested_at.isoformat()} for cr in credits],
            "calls": [{"id": str(k.id), "status": k.status, "started_at": k.started_at.isoformat(), "summary": k.summary} for k in calls]}  # fmt: skip
