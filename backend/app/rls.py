"""Row-level security helper used by every migration that creates a table holding tenant data."""

from alembic import op


def enable_rls(table: str, *, system_access: bool = False) -> None:
    """Restrict `table` to rows of the organisation set for the current transaction.

    FORCE makes the policy apply to the table owner too. With `system_access`, a transaction opened by
    `system_session()` may also see every row; that is reserved for sign-in, metrics and the global spend limit.
    """
    rule = "org_id = app_current_org()"
    if system_access:
        rule += " OR app_is_system()"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({rule}) WITH CHECK ({rule})")
