"""Per-organisation model settings. The API key is stored encrypted."""

from alembic import op

from app.rls import enable_rls

revision = "0004"
down_revision = "0001"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE llm_settings (
            org_id uuid PRIMARY KEY REFERENCES orgs(id) ON DELETE CASCADE,
            provider text NOT NULL CHECK (provider IN ('openai_compat', 'anthropic', 'ollama', 'stub')),
            model text NOT NULL,
            base_url text NOT NULL DEFAULT '',
            api_key_enc text NOT NULL DEFAULT '',
            fallback_model text NOT NULL DEFAULT '',
            price_input_per_mtok numeric(10,4) NOT NULL DEFAULT 3,
            price_output_per_mtok numeric(10,4) NOT NULL DEFAULT 15,
            updated_by uuid REFERENCES users(id) ON DELETE SET NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    enable_rls("llm_settings")


def downgrade() -> None:
    op.execute("DROP TABLE llm_settings")
