"""The organisation's policies, split into passages for search and citation. Full-text search in PostgreSQL:
title and heading weigh more than body text."""

from alembic import op

from app.rls import enable_rls

revision = "0012"
down_revision = "0011"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE policy_documents (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            slug text NOT NULL,
            title text NOT NULL,
            body text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (org_id, slug)
        )
    """)
    op.execute("""
        CREATE TABLE policy_passages (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            document_id uuid NOT NULL REFERENCES policy_documents(id) ON DELETE CASCADE,
            section text NOT NULL,
            title text NOT NULL,
            heading text NOT NULL,
            body text NOT NULL,
            tsv tsvector GENERATED ALWAYS AS (
                setweight(to_tsvector('english', title), 'A') || setweight(to_tsvector('english', heading), 'B')
                || setweight(to_tsvector('english', body), 'C')
            ) STORED
        )
    """)
    op.execute("CREATE INDEX policy_passages_tsv_idx ON policy_passages USING gin (tsv)")
    op.execute("CREATE INDEX policy_passages_doc_idx ON policy_passages (document_id)")
    for table in ("policy_documents", "policy_passages"):
        enable_rls(table)


def downgrade() -> None:
    op.execute("DROP TABLE policy_passages")
    op.execute("DROP TABLE policy_documents")
