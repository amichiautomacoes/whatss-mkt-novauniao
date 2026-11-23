import argparse

try:
    import _path  # noqa: F401
except ModuleNotFoundError:
    from scripts import _path  # noqa: F401
from psycopg import sql

from app.config import get_settings
from app.db.postgres import get_postgres_connection


def build_statements(schema: str) -> list[sql.Composed]:
    statements = [
        """
        create table if not exists {schema}.whatsapp_campaigns (
            id bigint generated always as identity primary key,
            name text not null,
            message_template text not null,
            lote text,
            status text not null default 'draft'
                check (status in ('draft', 'queued', 'running', 'paused', 'completed', 'cancelled')),
            scheduled_at timestamptz,
            started_at timestamptz,
            completed_at timestamptz,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )
        """,
        """
        create unique index if not exists whatsapp_campaigns_name_lote_idx
        on {schema}.whatsapp_campaigns(name, lote)
        """,
        """
        create table if not exists {schema}.whatsapp_historico (
            id bigint generated always as identity primary key,
            campaign_id bigint not null references {schema}.whatsapp_campaigns(id),
            campaign_name text not null,
            source_id bigint not null,
            lead_key uuid not null,
            phone text not null check (phone ~ '^55[0-9]{{10,11}}$'),
            message text not null,
            image_path text not null default '',
            status text not null default 'pending'
                check (status in ('pending', 'processing', 'sent', 'failed', 'cancelled', 'uncertain')),
            attempts integer not null default 0 check (attempts >= 0),
            scheduled_at timestamptz not null,
            email_opened_at timestamptz,
            last_attempt_at timestamptz,
            sent_at timestamptz,
            provider_message_id text,
            provider_response jsonb not null default '{{}}'::jsonb,
            last_error text,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            unique (campaign_name, phone)
        )
        """,
        """
        alter table {schema}.whatsapp_historico
        add column if not exists email_opened_at timestamptz
        """,
        """
        create index if not exists whatsapp_historico_status_schedule_idx
        on {schema}.whatsapp_historico(status, scheduled_at, id)
        """,
        """
        create index if not exists whatsapp_historico_lead_key_idx
        on {schema}.whatsapp_historico(lead_key)
        """,
        """
        create table if not exists {schema}.whatsapp_opt_outs (
            id bigint generated always as identity primary key,
            phone text not null unique,
            lead_key uuid,
            reason text,
            source text not null default 'manual',
            created_at timestamptz not null default now()
        )
        """,
    ]
    return [
        sql.SQL(statement).format(schema=sql.Identifier(schema))
        for statement in statements
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare WhatsApp operational tables.")
    parser.add_argument("--dry-run", action="store_true", help="Print SQL without connecting to the database.")
    args = parser.parse_args()
    schema = get_settings().supabase_schema
    statements = build_statements(schema)

    if args.dry_run:
        for statement in statements:
            print(statement.as_string().strip() + ";\n")
        return

    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
        conn.commit()

    print(f"Operational tables are ready in schema {schema}. Source table and triggers were not changed.")


if __name__ == "__main__":
    main()
