from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Call(Base):
    __tablename__ = "calls"
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.id"))
    status: Mapped[str] = mapped_column(default="live")
    channel: Mapped[str] = mapped_column(default="voice")
    started_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    verified_customer_id: Mapped[UUID | None] = mapped_column(ForeignKey("customers.id"))
    verification_failures: Mapped[int] = mapped_column(default=0)
    handed_off_reason: Mapped[str | None]
    handled_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model_calls: Mapped[int] = mapped_column(default=0)
    tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[Decimal] = mapped_column(default=Decimal(0))
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    ended_at: Mapped[datetime | None]
    last_activity: Mapped[datetime] = mapped_column(server_default=func.now())


class Turn(Base):
    __tablename__ = "turns"
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.id"))
    call_id: Mapped[UUID] = mapped_column(ForeignKey("calls.id"))
    idx: Mapped[int]
    speaker: Mapped[str]
    text: Mapped[str]
    interrupted: Mapped[bool] = mapped_column(default=False)
    timings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CallEvent(Base):
    __tablename__ = "call_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.id"))
    call_id: Mapped[UUID] = mapped_column(ForeignKey("calls.id"))
    kind: Mapped[str]
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    at: Mapped[datetime] = mapped_column(server_default=func.now())
