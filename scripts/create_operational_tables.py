import _path  # noqa: F401
from psycopg import sql

from app.config import get_settings
from app.db.postgres import get_postgres_connection


def main() -> None:
    settings = get_settings()
    schema = settings.supabase_schema

    statements = [
        sql.SQL(
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
            """
        ),
        sql.SQL(
            """
            create table if not exists {schema}.whatsapp_message_events (
                id bigint generated always as identity primary key,
                message_id text,
                campaign_id bigint
                    references {schema}.whatsapp_campaigns(id)
                    on delete set null,
                lead_key text
                    references {schema}.whatsapp_mkt(lead_key)
                    on delete set null,
                phone text,
                event_type text not null,
                payload jsonb not null default '{{}}'::jsonb,
                created_at timestamptz not null default now()
            )
            """
        ),
        sql.SQL(
            """
            create table if not exists {schema}.whatsapp_opt_outs (
                id bigint generated always as identity primary key,
                phone text not null unique,
                lead_key text
                    references {schema}.whatsapp_mkt(lead_key)
                    on delete set null,
                reason text,
                source text not null default 'manual',
                created_at timestamptz not null default now()
            )
            """
        ),
        sql.SQL(
            "create unique index if not exists whatsapp_campaigns_name_lote_idx on {schema}.whatsapp_campaigns(name, lote)"
        ),
        sql.SQL(
            "create index if not exists whatsapp_mkt_lote_idx on {schema}.whatsapp_mkt(lote)"
        ),
        sql.SQL(
            "create index if not exists whatsapp_message_events_phone_idx on {schema}.whatsapp_message_events(phone)"
        ),
        sql.SQL(
            "create index if not exists whatsapp_message_events_campaign_lead_idx on {schema}.whatsapp_message_events(campaign_id, lead_key)"
        ),
    ]

    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement.format(schema=sql.Identifier(schema)))
        conn.commit()

    print(f"Operational tables are ready in schema {schema}.")


if __name__ == "__main__":
    main()
