"""Calls, what was said in them, and what happened (tool calls, state changes): the record a person reviews."""

from alembic import op

from app.rls import enable_rls

revision = "0011"
down_revision = "0010"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE calls (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            status text NOT NULL DEFAULT 'live' CHECK (status IN ('live', 'handed_off', 'ended')),
            channel text NOT NULL DEFAULT 'voice' CHECK (channel IN ('voice', 'text')),
            started_by uuid REFERENCES users(id) ON DELETE SET NULL,
            verified_customer_id uuid REFERENCES customers(id) ON DELETE SET NULL,
            verification_failures int NOT NULL DEFAULT 0,
            handed_off_reason text,
            handled_by uuid REFERENCES users(id) ON DELETE SET NULL,
            summary jsonb,
            model_calls int NOT NULL DEFAULT 0,
            tokens int NOT NULL DEFAULT 0,
            cost_usd numeric(12,6) NOT NULL DEFAULT 0,
            started_at timestamptz NOT NULL DEFAULT now(),
            ended_at timestamptz,
            last_activity timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX calls_org_idx ON calls (org_id, started_at DESC)")
    op.execute("CREATE INDEX calls_live_idx ON calls (org_id, last_activity) WHERE status <> 'ended'")
    op.execute("""
        CREATE TABLE turns (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            call_id uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
            idx int NOT NULL,
            speaker text NOT NULL CHECK (speaker IN ('customer', 'agent', 'person', 'system')),
            text text NOT NULL,
            interrupted boolean NOT NULL DEFAULT false,
            timings jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (call_id, idx)
        )
    """)
    op.execute("""
        CREATE TABLE call_events (
            id bigserial PRIMARY KEY,
            org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            call_id uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
            kind text NOT NULL,
            data jsonb NOT NULL DEFAULT '{}'::jsonb,
            at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX call_events_call_idx ON call_events (call_id, id)")
    op.execute(
        "ALTER TABLE tickets ADD CONSTRAINT tickets_call_fk FOREIGN KEY (call_id) REFERENCES calls(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE credits ADD CONSTRAINT credits_call_fk FOREIGN KEY (call_id) REFERENCES calls(id) ON DELETE SET NULL"
    )
    for table in ("calls", "turns", "call_events"):
        enable_rls(table)


def downgrade() -> None:
    op.execute("ALTER TABLE credits DROP CONSTRAINT credits_call_fk")
    op.execute("ALTER TABLE tickets DROP CONSTRAINT tickets_call_fk")
    for table in ("call_events", "turns", "calls"):
        op.execute(f"DROP TABLE {table}")
