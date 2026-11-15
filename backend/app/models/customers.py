from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.id"))
    account_number: Mapped[str]
    name: Mapped[str]
    phone: Mapped[str]
    postcode: Mapped[str]
    date_of_birth: Mapped[date]
    email: Mapped[str | None]
    vulnerable: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Service(Base):
    __tablename__ = "services"
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.id"))
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"))
    kind: Mapped[str]
    plan: Mapped[str]
    monthly_price: Mapped[Decimal]
    area: Mapped[str]
    status: Mapped[str] = mapped_column(default="active")
    started_on: Mapped[date]
    contract_ends: Mapped[date | None]


class Bill(Base):
    __tablename__ = "bills"
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.id"))
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"))
    period_start: Mapped[date]
    period_end: Mapped[date]
    issued_on: Mapped[date]
    total: Mapped[Decimal]
    status: Mapped[str]


class BillLine(Base):
    __tablename__ = "bill_lines"
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.id"))
    bill_id: Mapped[UUID] = mapped_column(ForeignKey("bills.id"))
    description: Mapped[str]
    amount: Mapped[Decimal]


class Outage(Base):
    __tablename__ = "outages"
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.id"))
    area: Mapped[str]
    kind: Mapped[str]
    title: Mapped[str]
    started_at: Mapped[datetime]
    resolved_at: Mapped[datetime | None]
    expected_fix: Mapped[datetime | None]


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.id"))
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"))
    call_id: Mapped[UUID | None] = mapped_column(ForeignKey("calls.id"))
    category: Mapped[str]
    summary: Mapped[str]
    status: Mapped[str] = mapped_column(default="open")
    opened_by: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Credit(Base):
    __tablename__ = "credits"
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.id"))
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"))
    call_id: Mapped[UUID | None] = mapped_column(ForeignKey("calls.id"))
    amount: Mapped[Decimal]
    reason: Mapped[str]
    status: Mapped[str]
    requested_at: Mapped[datetime] = mapped_column(server_default=func.now())
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None]
    decision_reason: Mapped[str | None]
