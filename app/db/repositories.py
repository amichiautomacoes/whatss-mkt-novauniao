from datetime import datetime, timezone
from typing import Any

from psycopg import sql

from app.config import get_settings
from app.db.postgres import get_postgres_connection


def table_identifier(table_name: str) -> sql.Composed:
    return sql.SQL("{}.{}").format(
        sql.Identifier(get_settings().supabase_schema),
        sql.Identifier(table_name),
    )


class WhatsAppLeadRepository:
    def list_opened_since(
        self, opened_from: datetime, as_of: datetime, campaign_name: str, limit: int = 500,
    ) -> list[dict[str, Any]]:
        query = sql.SQL(
            """
            with contacts as (
                select id as source_id, lead_key::text as lead_key, empresa,
                       nome_decisor, email, telefone_contato, lote_key, primeira_abertura,
                       case when length(regexp_replace(telefone_contato, '[^0-9]', '', 'g')) in (10, 11)
                            then '55' || regexp_replace(telefone_contato, '[^0-9]', '', 'g')
                            else regexp_replace(telefone_contato, '[^0-9]', '', 'g') end as phone
                from {leads}
                where primeira_abertura >= %s and primeira_abertura <= %s
            ), unique_contacts as (
                select distinct on (phone) * from contacts
                where phone ~ '^55[0-9]{{10,11}}$'
                  and not exists (
                      select 1 from {history} h
                      where h.campaign_name = %s and h.phone = contacts.phone
                  )
                order by phone, primeira_abertura, source_id
            )
            select * from unique_contacts
            order by primeira_abertura, source_id
            limit %s
            """
        ).format(
            leads=table_identifier("whatsapp_marketing"),
            history=table_identifier("whatsapp_historico"),
        )
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (opened_from, as_of, campaign_name, limit))
                return list(cur.fetchall())

    def list_by_lote(self, lote: str, limit: int | None = None) -> list[dict[str, Any]]:
        query = sql.SQL(
            """
            select
                id as source_id,
                lead_key::text as lead_key,
                empresa,
                nome_decisor,
                email,
                telefone_contato,
                lote_key
            from {leads}
            where lote_key = %s
              and nullif(trim(telefone_contato), '') is not null
            order by id
            """
        ).format(leads=table_identifier("whatsapp_marketing"))

        params: list[Any] = [lote]
        if limit:
            query += sql.SQL(" limit %s")
            params.append(limit)

        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return list(cur.fetchall())

    def count_by_lote(self) -> list[dict[str, Any]]:
        query = sql.SQL(
            """
            select lote_key as lote, count(*) as total,
                   count(distinct lead_key) as unique_leads
            from {leads}
            group by lote_key
            order by lote_key
            """
        ).format(leads=table_identifier("whatsapp_marketing"))

        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return list(cur.fetchall())


LeadRepository = WhatsAppLeadRepository


class CampaignRepository:
    def find(self, name: str, lote: str) -> dict[str, Any] | None:
        query = sql.SQL("select * from {campaigns} where name = %s and lote = %s").format(
            campaigns=table_identifier("whatsapp_campaigns")
        )
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (name, lote))
                row = cur.fetchone()
                return dict(row) if row else None

    def create(
        self,
        name: str,
        message_template: str,
        lote: str | None = None,
        scheduled_at: datetime | None = None,
    ) -> dict[str, Any]:
        query = sql.SQL(
            """
            insert into {campaigns} (name, message_template, lote, scheduled_at)
            values (%s, %s, %s, %s)
            on conflict (name, lote) do update
            set message_template = excluded.message_template,
                scheduled_at = excluded.scheduled_at,
                updated_at = now()
            returning *
            """
        ).format(campaigns=table_identifier("whatsapp_campaigns"))

        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (name, message_template, lote, scheduled_at))
                campaign = cur.fetchone()
            conn.commit()

        return dict(campaign)

    def get(self, campaign_id: int) -> dict[str, Any] | None:
        query = sql.SQL("select * from {campaigns} where id = %s").format(
            campaigns=table_identifier("whatsapp_campaigns")
        )

        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (campaign_id,))
                campaign = cur.fetchone()

        return dict(campaign) if campaign else None

    def update_status(self, campaign_id: int, status: str) -> None:
        now = datetime.now(timezone.utc)
        extra_column = {
            "running": "started_at",
            "completed": "completed_at",
        }.get(status)

        set_parts = [
            sql.SQL("status = %s"),
            sql.SQL("updated_at = %s"),
        ]
        params: list[Any] = [status, now]

        if extra_column:
            set_parts.append(sql.SQL("{} = %s").format(sql.Identifier(extra_column)))
            params.append(now)

        params.append(campaign_id)
        query = sql.SQL("update {campaigns} set {sets} where id = %s").format(
            campaigns=table_identifier("whatsapp_campaigns"),
            sets=sql.SQL(", ").join(set_parts),
        )

        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
            conn.commit()


class OptOutRepository:
    def is_opted_out(self, phone: str) -> bool:
        query = sql.SQL(
            """
            select 1
            from {opt_outs}
            where phone = %s
            limit 1
            """
        ).format(opt_outs=table_identifier("whatsapp_opt_outs"))

        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (phone,))
                return cur.fetchone() is not None
