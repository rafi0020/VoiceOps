from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.id"))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str]
    target: Mapped[str | None]
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
