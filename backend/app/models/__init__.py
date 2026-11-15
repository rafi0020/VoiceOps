from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Mapped classes mirror the tables created by the Alembic migrations, which are the source of truth."""


# Importing every model module here means any process that touches one table has all of them registered,
# so foreign keys between them always resolve.
from app.models import audit, calls, customers, identity, llm, policies  # noqa: E402, F401
