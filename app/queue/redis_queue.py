import json
from datetime import datetime, timezone
from typing import Any

from redis import Redis

from app.config import get_settings


ENQUEUE_IF_ABSENT = """
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
redis.call('HSET', KEYS[1], unpack(ARGV, 3))
redis.call('ZADD', KEYS[2], ARGV[1], ARGV[2])
return 1
"""


CLAIM_PENDING = """
if redis.call('ZREM', KEYS[1], ARGV[1]) == 0 then return 0 end
redis.call('HSET', KEYS[3], 'status', 'processing', 'updated_at', ARGV[3])
redis.call('ZADD', KEYS[2], ARGV[2], ARGV[1])
return 1
"""


class RedisMessageQueue:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.redis_url:
            raise RuntimeError("REDIS_URL is missing in .env")

        self.settings = settings
        self.client = Redis.from_url(settings.redis_url, decode_responses=True)
        # Old queue entries have no durable history ID and must not enter this flow.
        self.prefix = f"{settings.redis_queue_prefix.strip(':')}:v2"

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

    def _message_id(self, history_id: int) -> str:
        return f"history:{history_id}"

    def enqueue_many(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0

        now = datetime.now(timezone.utc).isoformat()
        with self.client.pipeline(transaction=True) as pipe:
            for row in rows:
                message_id = self._message_id(row["history_id"])
                key = self._message_key(message_id)
                scheduled_at = row["scheduled_at"]
                score = scheduled_at.timestamp()
                payload = {
                    "id": message_id,
                    "history_id": str(row["history_id"]),
                    "source_id": str(row["source_id"]),
                    "campaign_id": str(row["campaign_id"]),
                    "lead_key": str(row["lead_key"]),
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
                    "accepted_at": "",
                }
                fields = [value for pair in payload.items() for value in pair]
                pipe.eval(ENQUEUE_IF_ABSENT, 2, key, self.scheduled_key, score, message_id, *fields)
            results = pipe.execute()
        return sum(int(result) for result in results)

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
            **({"start": 0, "num": max(limit * 5, limit)} if campaign_id is None else {}),
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

            claimed = self.client.eval(
                CLAIM_PENDING, 3, self.scheduled_key, self.processing_key, key,
                message_id, processing_deadline, datetime.now(timezone.utc).isoformat(),
            )
            if not claimed:
                continue
            messages.append(self._decode_row(row | {"status": "processing"}))

        return messages

    def record_provider_response(
        self, message_id: str, provider_response: dict[str, Any], accepted_at: datetime,
    ) -> None:
        self.client.hset(
            self._message_key(message_id),
            mapping={
                "provider_response": json.dumps(provider_response, ensure_ascii=False),
                "accepted_at": accepted_at.isoformat(),
            },
        )

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
            "history_id": int(row["history_id"]),
            "source_id": int(row["source_id"]),
            "campaign_id": int(row["campaign_id"]),
            "lead_key": row["lead_key"],
            "phone": row["phone"],
            "message": row["message"],
            "image_path": row.get("image_path") or "",
            "status": row["status"],
            "attempts": int(row.get("attempts") or 0),
            "scheduled_at": row["scheduled_at"],
            "last_error": row.get("last_error") or None,
            "provider_response": json.loads(row["provider_response"]) if row.get("provider_response") else None,
            "accepted_at": row.get("accepted_at") or None,
        }
