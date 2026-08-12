import json
from datetime import datetime, timezone
from typing import Any

from redis import Redis

from app.config import get_settings


class RedisMessageQueue:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.redis_url:
            raise RuntimeError("REDIS_URL is missing in .env")

        self.settings = settings
        self.client = Redis.from_url(settings.redis_url, decode_responses=True)
        self.prefix = settings.redis_queue_prefix.strip(":")

    @property
    def scheduled_key(self) -> str:
        return f"{self.prefix}:scheduled"

    @property
    def processing_key(self) -> str:
        return f"{self.prefix}:processing"

    @property
    def failed_key(self) -> str:
        return f"{self.prefix}:failed"

    def _message_key(self, message_id: str) -> str:
        return f"{self.prefix}:message:{message_id}"

    def _message_id(self, campaign_id: int, lead_key: str) -> str:
        return f"{campaign_id}:{lead_key}"

    def enqueue_many(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0

        now = datetime.now(timezone.utc).isoformat()
        queued_count = 0

        with self.client.pipeline(transaction=True) as pipe:
            for row in rows:
                message_id = self._message_id(row["campaign_id"], row["lead_key"])
                key = self._message_key(message_id)
                scheduled_at = row["scheduled_at"]
                score = scheduled_at.timestamp()
                exists = self.client.exists(key)

                payload = {
                    "id": message_id,
                    "campaign_id": str(row["campaign_id"]),
                    "lead_key": row["lead_key"],
                    "phone": row["phone"],
                    "message": row["message"],
                    "image_path": row.get("image_path") or "",
                    "status": "pending",
                    "attempts": str(row.get("attempts", 0)),
                    "scheduled_at": scheduled_at.isoformat(),
                    "created_at": now,
                    "updated_at": now,
                    "last_error": "",
                    "provider_response": "",
                }

                pipe.hset(key, mapping=payload)
                pipe.zadd(self.scheduled_key, {message_id: score})
                pipe.zrem(self.processing_key, message_id)
                pipe.zrem(self.failed_key, message_id)

                if not exists:
                    queued_count += 1

            pipe.execute()

        return queued_count

    def requeue_expired_processing(self) -> int:
        now_score = datetime.now(timezone.utc).timestamp()
        expired_ids = self.client.zrangebyscore(
            self.processing_key,
            min="-inf",
            max=now_score,
        )
        requeued = 0

        with self.client.pipeline(transaction=True) as pipe:
            for message_id in expired_ids:
                key = self._message_key(message_id)
                if not self.client.exists(key):
                    pipe.zrem(self.processing_key, message_id)
                    continue

                pipe.hset(
                    key,
                    mapping={
                        "status": "pending",
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "last_error": "visibility timeout expired",
                    },
                )
                pipe.zrem(self.processing_key, message_id)
                pipe.zadd(self.scheduled_key, {message_id: now_score})
                requeued += 1

            pipe.execute()

        return requeued

    def list_pending(
        self,
        limit: int = 20,
        campaign_id: int | None = None,
    ) -> list[dict[str, Any]]:
        self.requeue_expired_processing()
        now_score = datetime.now(timezone.utc).timestamp()
        candidate_ids = self.client.zrangebyscore(
            self.scheduled_key,
            min="-inf",
            max=now_score,
            start=0,
            num=max(limit * 5, limit),
        )

        messages: list[dict[str, Any]] = []
        processing_deadline = now_score + self.settings.redis_visibility_timeout_seconds

        for message_id in candidate_ids:
            if len(messages) >= limit:
                break

            key = self._message_key(message_id)
            row = self.client.hgetall(key)
            if not row:
                self.client.zrem(self.scheduled_key, message_id)
                continue

            if campaign_id is not None and int(row["campaign_id"]) != campaign_id:
                continue

            removed = self.client.zrem(self.scheduled_key, message_id)
            if not removed:
                continue

            self.client.hset(
                key,
                mapping={
                    "status": "processing",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            self.client.zadd(self.processing_key, {message_id: processing_deadline})
            messages.append(self._decode_row(row | {"status": "processing"}))

        return messages

    def mark_sent(self, message_id: str, provider_response: dict[str, Any]) -> None:
        key = self._message_key(message_id)
        self.client.hset(
            key,
            mapping={
                "status": "sent",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "provider_response": json.dumps(provider_response, ensure_ascii=False),
            },
        )
        self.client.zrem(self.processing_key, message_id)
        self.client.zrem(self.scheduled_key, message_id)
        self.client.delete(key)

    def mark_cancelled(self, message_id: str, reason: str) -> None:
        key = self._message_key(message_id)
        self.client.hset(
            key,
            mapping={
                "status": "cancelled",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "last_error": reason,
            },
        )
        self.client.zrem(self.processing_key, message_id)
        self.client.zrem(self.scheduled_key, message_id)
        self.client.delete(key)

    def mark_failed(self, message_id: str, error: str) -> bool:
        key = self._message_key(message_id)
        row = self.client.hgetall(key)
        attempts = int(row.get("attempts") or 0) + 1
        now = datetime.now(timezone.utc)

        if attempts >= self.settings.redis_max_attempts:
            self.client.hset(
                key,
                mapping={
                    "status": "failed",
                    "attempts": str(attempts),
                    "last_error": error,
                    "updated_at": now.isoformat(),
                },
            )
            self.client.zrem(self.processing_key, message_id)
            self.client.zadd(self.failed_key, {message_id: now.timestamp()})
            return False

        retry_at = now.timestamp() + self.settings.redis_retry_delay_seconds
        self.client.hset(
            key,
            mapping={
                "status": "pending",
                "attempts": str(attempts),
                "last_error": error,
                "updated_at": now.isoformat(),
            },
        )
        self.client.zrem(self.processing_key, message_id)
        self.client.zadd(self.scheduled_key, {message_id: retry_at})
        return True

    def _decode_row(self, row: dict[str, str]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "campaign_id": int(row["campaign_id"]),
            "lead_key": row["lead_key"],
            "phone": row["phone"],
            "message": row["message"],
            "image_path": row.get("image_path") or "",
            "status": row["status"],
            "attempts": int(row.get("attempts") or 0),
            "scheduled_at": row["scheduled_at"],
            "last_error": row.get("last_error") or None,
        }
