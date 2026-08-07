from datetime import datetime, timezone
from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.db.postgres import get_postgres_connection


def table_identifier(table_name: str) -> sql.Composed:
    return sql.SQL("{}.{}").format(
        sql.Identifier(get_settings().supabase_schema),
        sql.Identifier(table_name),
    )


class WhatsAppLeadRepository:
    def list_by_lote(self, lote: str, limit: int | None = None) -> list[dict[str, Any]]:
        query = sql.SQL(
            """
            select
                lead_key,
                empresa,
                decisor,
                email,
                whatsapp_contato1,
                whatsapp_contato2,
                url_instagram,
                lote
            from {leads}
            where lote = %s
              and (
                nullif(whatsapp_contato1, '') is not null
                or nullif(whatsapp_contato2, '') is not null
              )
            order by lead_key
            """
        ).format(leads=table_identifier("whatsapp_mkt"))

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
            select lote, count(*) as total
            from {leads}
            group by lote
            order by lote
            """
        ).format(leads=table_identifier("whatsapp_mkt"))

        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return list(cur.fetchall())


LeadRepository = WhatsAppLeadRepository


class CampaignRepository:
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


class MessageQueueRepository:
    def enqueue_many(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0

        query = sql.SQL(
            """
            insert into {queue} (
                campaign_id,
                lead_key,
                phone,
                message,
                status,
                attempts,
                scheduled_at
            )
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (campaign_id, lead_key) do update
            set phone = excluded.phone,
                message = excluded.message,
                scheduled_at = excluded.scheduled_at,
                updated_at = now()
            where {queue}.status in ('pending', 'failed', 'cancelled')
            """
        ).format(queue=table_identifier("whatsapp_message_queue"))

        inserted = 0
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                for row in rows:
                    cur.execute(
                        query,
                        (
                            row["campaign_id"],
                            row["lead_key"],
                            row["phone"],
                            row["message"],
                            row.get("status", "pending"),
                            row.get("attempts", 0),
                            row["scheduled_at"],
                        ),
                    )
                    inserted += cur.rowcount
            conn.commit()

        return inserted

    def list_pending(
        self,
        limit: int = 20,
        campaign_id: int | None = None,
    ) -> list[dict[str, Any]]:
        query = sql.SQL(
            """
            select *
            from {queue}
            where status = 'pending'
              and scheduled_at <= now()
              and phone not in (select phone from {opt_outs})
            """
        ).format(
            queue=table_identifier("whatsapp_message_queue"),
            opt_outs=table_identifier("whatsapp_opt_outs"),
        )
        params: list[Any] = []

        if campaign_id is not None:
            query += sql.SQL(" and campaign_id = %s")
            params.append(campaign_id)

        query += sql.SQL(" order by scheduled_at, id limit %s")
        params.append(limit)

        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return list(cur.fetchall())

    def update_status(
        self,
        message_id: int,
        status: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload = {"status": status, "updated_at": datetime.now(timezone.utc)}
        payload.update(extra or {})

        set_parts = []
        params: list[Any] = []
        for key, value in payload.items():
            set_parts.append(sql.SQL("{} = %s").format(sql.Identifier(key)))
            params.append(Jsonb(value) if key == "provider_response" else value)

        params.append(message_id)
        query = sql.SQL("update {queue} set {sets} where id = %s").format(
            queue=table_identifier("whatsapp_message_queue"),
            sets=sql.SQL(", ").join(set_parts),
        )

        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
            conn.commit()


class MessageEventRepository:
    def create(
        self,
        event_type: str,
        payload: dict[str, Any],
        message_id: int | None = None,
        campaign_id: int | None = None,
        lead_key: str | None = None,
        phone: str | None = None,
    ) -> None:
        query = sql.SQL(
            """
            insert into {events} (
                message_id,
                campaign_id,
                lead_key,
                phone,
                event_type,
                payload
            )
            values (%s, %s, %s, %s, %s, %s)
            """
        ).format(events=table_identifier("whatsapp_message_events"))

        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    (message_id, campaign_id, lead_key, phone, event_type, Jsonb(payload)),
                )
            conn.commit()
