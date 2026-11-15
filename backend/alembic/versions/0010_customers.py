"""Customers and what the agent may tell them about: services, bills, outages; and what it may do: tickets, credits."""

from alembic import op

from app.rls import enable_rls

revision = "0010"
down_revision = "0004"

TABLES = ("customers", "services", "bills", "bill_lines", "outages", "tickets", "credits", "org_call_settings")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE customers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            account_number text NOT NULL,
            name text NOT NULL,
            phone text NOT NULL,
            postcode text NOT NULL,
            date_of_birth date NOT NULL,
            email text,
            vulnerable boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (org_id, account_number)
        )
    """)
    op.execute("CREATE INDEX customers_phone_idx ON customers (org_id, phone)")
    op.execute("""
        CREATE TABLE services (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            customer_id uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            kind text NOT NULL CHECK (kind IN ('broadband', 'mobile', 'tv', 'electricity', 'gas')),
            plan text NOT NULL,
            monthly_price numeric(10,2) NOT NULL,
            area text NOT NULL,
            status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'ceased')),
            started_on date NOT NULL,
            contract_ends date
        )
    """)
    op.execute("CREATE INDEX services_customer_idx ON services (customer_id)")
    op.execute("""
        CREATE TABLE bills (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            customer_id uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            period_start date NOT NULL,
            period_end date NOT NULL,
            issued_on date NOT NULL,
            total numeric(10,2) NOT NULL,
            status text NOT NULL CHECK (status IN ('paid', 'due', 'overdue'))
        )
    """)
    op.execute("CREATE INDEX bills_customer_idx ON bills (customer_id, issued_on DESC)")
    op.execute("""
        CREATE TABLE bill_lines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            bill_id uuid NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
            description text NOT NULL,
            amount numeric(10,2) NOT NULL
        )
    """)
    op.execute("CREATE INDEX bill_lines_bill_idx ON bill_lines (bill_id)")
    op.execute("""
        CREATE TABLE outages (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            area text NOT NULL,
            kind text NOT NULL,
            title text NOT NULL,
            started_at timestamptz NOT NULL,
            resolved_at timestamptz,
            expected_fix timestamptz
        )
    """)
    op.execute("CREATE INDEX outages_area_idx ON outages (org_id, area)")
    op.execute("""
        CREATE TABLE tickets (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            customer_id uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            call_id uuid,
            category text NOT NULL CHECK (category IN ('fault', 'billing', 'complaint', 'moving', 'cancellation', 'other')),
            summary text NOT NULL,
            status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
            opened_by text NOT NULL CHECK (opened_by IN ('ai', 'person')),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX tickets_customer_idx ON tickets (customer_id, created_at DESC)")
    op.execute("""
        CREATE TABLE credits (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            customer_id uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            call_id uuid,
            amount numeric(10,2) NOT NULL CHECK (amount > 0),
            reason text NOT NULL,
            status text NOT NULL CHECK (status IN ('applied', 'pending', 'refused')),
            requested_at timestamptz NOT NULL DEFAULT now(),
            decided_by uuid REFERENCES users(id) ON DELETE SET NULL,
            decided_at timestamptz,
            decision_reason text
        )
    """)
    op.execute("CREATE INDEX credits_pending_idx ON credits (org_id, requested_at) WHERE status = 'pending'")
    op.execute("""
        CREATE TABLE org_call_settings (
            org_id uuid PRIMARY KEY REFERENCES orgs(id) ON DELETE CASCADE,
            credit_limit numeric(10,2) NOT NULL DEFAULT 10.00 CHECK (credit_limit >= 0),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    for table in TABLES:
        enable_rls(table)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table}")
