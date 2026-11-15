"""Calls readable by a system transaction too: the global daily spend limit and /metrics sum across organisations.
Every other access to calls stays scoped to the organisation."""

from alembic import op

revision = "0013"
down_revision = "0012"


def upgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON calls")
    rule = "org_id = app_current_org() OR app_is_system()"
    op.execute(f"CREATE POLICY tenant_isolation ON calls USING ({rule}) WITH CHECK ({rule})")
    op.execute("CREATE INDEX calls_started_idx ON calls (started_at)")


def downgrade() -> None:
    op.execute("DROP INDEX calls_started_idx")
    op.execute("DROP POLICY tenant_isolation ON calls")
    op.execute(
        "CREATE POLICY tenant_isolation ON calls USING (org_id = app_current_org()) WITH CHECK (org_id = app_current_org())"
    )
