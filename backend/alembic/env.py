"""Migrations run as voiceops_owner, straight to PostgreSQL (not through the pooler)."""

from alembic import context
from sqlalchemy import create_engine, text

from app.config import get_settings

LOCK_ID = 724_101  # one migrator at a time, however many containers start together


def run() -> None:
    engine = create_engine(get_settings().database_url_owner)
    with engine.connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(:id)"), {"id": LOCK_ID})
        try:
            context.configure(connection=conn, target_metadata=None, transaction_per_migration=True)
            with context.begin_transaction():
                context.run_migrations()
            conn.commit()
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
            conn.commit()
    engine.dispose()


run()
