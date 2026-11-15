"""Organisations, users, sessions, audit log, and the tenant-isolation functions."""

from alembic import op

from app.rls import enable_rls

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION app_current_org() RETURNS uuid LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.org_id', true), '')::uuid $$
    """)
    op.execute("""
        CREATE FUNCTION app_is_system() RETURNS boolean LANGUAGE sql STABLE AS
        $$ SELECT coalesce(current_setting('app.system', true), '') = 'on' $$
    """)
    op.execute("GRANT EXECUTE ON FUNCTION app_current_org(), app_is_system() TO voiceops_app")
    op.execute("""
        CREATE TABLE orgs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE users (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            email text NOT NULL UNIQUE,
            name text NOT NULL DEFAULT '',
            password_hash text NOT NULL,
            role text NOT NULL CHECK (role IN ('viewer', 'agent', 'supervisor', 'admin')),
            is_active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX users_org_idx ON users (org_id)")
    enable_rls("users", system_access=True)
    op.execute("""
        CREATE TABLE sessions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash text NOT NULL UNIQUE,
            csrf_token text NOT NULL,
            expires_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX sessions_user_idx ON sessions (user_id)")
    op.execute("""
        CREATE TABLE audit_log (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            user_id uuid REFERENCES users(id) ON DELETE SET NULL,
            action text NOT NULL,
            target text,
            detail jsonb,
            ip text,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX audit_org_time_idx ON audit_log (org_id, created_at DESC)")
    enable_rls("audit_log")
    # The audit log is append-only for the application.
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM voiceops_app")


def downgrade() -> None:
    op.execute("DROP TABLE audit_log, sessions, users, orgs CASCADE")
    op.execute("DROP FUNCTION app_current_org(), app_is_system()")
