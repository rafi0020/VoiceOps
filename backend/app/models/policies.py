from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class PolicyDocument(Base):
    __tablename__ = "policy_documents"
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.id"))
    slug: Mapped[str]
    title: Mapped[str]
    body: Mapped[str]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PolicyPassage(Base):
    __tablename__ = "policy_passages"
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.id"))
    document_id: Mapped[UUID] = mapped_column(ForeignKey("policy_documents.id"))
    section: Mapped[str]
    title: Mapped[str]
    heading: Mapped[str]
    body: Mapped[str]
