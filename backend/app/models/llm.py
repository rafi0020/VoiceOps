from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class LLMSettings(Base):
    __tablename__ = "llm_settings"
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.id"), primary_key=True)
    provider: Mapped[str]
    model: Mapped[str]
    base_url: Mapped[str] = mapped_column(default="")
    api_key_enc: Mapped[str] = mapped_column(default="")
    fallback_model: Mapped[str] = mapped_column(default="")
    price_input_per_mtok: Mapped[Decimal] = mapped_column(default=Decimal(3))
    price_output_per_mtok: Mapped[Decimal] = mapped_column(default=Decimal(15))
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
