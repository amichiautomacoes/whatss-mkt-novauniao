from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.db.postgres import get_postgres_connection
from app.db.repositories import table_identifier


class MessageHistoryRepository:
    """Durable send control; source identifiers are snapshots, without source FKs."""

    def _execute(self, query: str, params: tuple = (), fetch: str = "none") -> Any:
        statement = sql.SQL(query).format(history=table_identifier("whatsapp_historico"))
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(statement, params)
                if fetch == "all":
                    result = cur.fetchall()
                elif fetch == "one":
                    result = cur.fetchone()
                else:
                    result = None
            conn.commit()
        return result

    def list_campaign_phones(self, campaign_name: str) -> set[str]:
        rows = self._execute(
            "select phone from {history} where campaign_name = %s",
            (campaign_name,),
            fetch="all",
        )
        return {row["phone"] for row in rows}

    def reserve(self, row: dict[str, Any], campaign_name: str) -> int | None:
        reserved = self._execute(
            """
            insert into {history} (
                campaign_id, campaign_name, source_id, lead_key,
                phone, message, image_path, scheduled_at, email_opened_at
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (campaign_name, phone) do nothing
            returning id
            """,
            (row["campaign_id"], campaign_name, row["source_id"], row["lead_key"],
             row["phone"], row["message"], row.get("image_path") or "", row["scheduled_at"],
             row.get("email_opened_at")),
            fetch="one",
        )
        return reserved["id"] if reserved else None

    def list_pending(
        self, limit: int = 100, campaign_id: int | None = None,
        reserved_before: datetime | None = None,
    ) -> list[dict[str, Any]]:
        return list(self._execute(
            """
            select id as history_id, campaign_id, source_id, lead_key::text as lead_key,
                   phone, message, image_path, attempts, scheduled_at
            from {history}
            where status = 'pending' and (%s::bigint is null or campaign_id = %s)
              and (%s::timestamptz is null or created_at < %s)
            order by scheduled_at, id
            limit %s
            """,
            (campaign_id, campaign_id, reserved_before, reserved_before, limit),
            fetch="all",
        ))

    def get(self, history_id: int) -> dict[str, Any] | None:
        return self._execute(
            "select * from {history} where id = %s", (history_id,), fetch="one",
        )

    def expire_processing(self) -> None:
        # A crashed in-flight call may already have sent a message. Do not retry it blindly.
        self._execute(
            """
            update {history}
            set status = 'uncertain', updated_at = now(),
                last_error = 'Processing expired; verify provider before retrying'
            where status = 'processing' and last_attempt_at < %s
            """,
            (datetime.now(timezone.utc) - timedelta(
                seconds=get_settings().redis_visibility_timeout_seconds),),
        )

    def claim(
        self, history_id: int, reserved_before: datetime | None = None,
    ) -> dict[str, Any] | None:
        return self._execute(
            """
            update {history}
            set status = 'processing', attempts = attempts + 1,
                last_attempt_at = now(), updated_at = now()
            where id = %s and status = 'pending' and scheduled_at <= now()
              and (%s::timestamptz is null or created_at < %s)
            returning *
            """,
            (history_id, reserved_before, reserved_before),
            fetch="one",
        )

    def mark_sent(
        self, history_id: int, response: dict[str, Any], sent_at: datetime,
    ) -> None:
        key = response.get("key")
        provider_id = key.get("id") if isinstance(key, dict) else response.get("id")
        self._execute(
            """
            update {history}
            set status = 'sent', sent_at = %s, provider_message_id = %s,
                provider_response = %s, last_error = null, updated_at = now()
            where id = %s
            """,
            (sent_at, str(provider_id) if provider_id else None, Jsonb(response), history_id),
        )

    def mark_failed(self, history_id: int, error: str, will_retry: bool) -> None:
        self._execute(
            """
            update {history}
            set status = %s, last_error = %s, updated_at = now(),
                scheduled_at = case when %s then %s else scheduled_at end
            where id = %s
            """,
            ("pending" if will_retry else "failed", error, will_retry,
             datetime.now(timezone.utc) + timedelta(seconds=get_settings().redis_retry_delay_seconds),
             history_id),
        )

    def mark_uncertain(self, history_id: int, error: str) -> None:
        self._execute(
            """
            update {history}
            set status = 'uncertain', last_error = %s, updated_at = now()
            where id = %s
            """,
            (error, history_id),
        )

    def mark_cancelled(self, history_id: int, reason: str) -> None:
        self._execute(
            """
            update {history}
            set status = 'cancelled', last_error = %s, updated_at = now()
            where id = %s and status = 'pending'
            """,
            (reason, history_id),
        )
