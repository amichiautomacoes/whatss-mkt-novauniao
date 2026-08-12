from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.config import get_settings
from app.db.repositories import MessageEventRepository, OptOutRepository
from app.queue.redis_queue import RedisMessageQueue
from app.whatsapp.evolution_client import EvolutionClient
from app.whatsapp.rate_limiter import wait_between_messages


def _record_event(
    events: MessageEventRepository,
    event_type: str,
    payload: dict[str, Any],
    row: dict[str, Any],
) -> None:
    try:
        events.create(
            event_type=event_type,
            payload=payload,
            campaign_id=row["campaign_id"],
            lead_key=row["lead_key"],
            phone=row["phone"],
        )
    except Exception:
        logger.exception("Failed to record {} event for {}", event_type, row["id"])


def dispatch_pending_messages(batch_size: int | None = None) -> int:
    return dispatch_campaign_messages(batch_size=batch_size)


def dispatch_campaign_messages(
    batch_size: int | None = None,
    campaign_id: int | None = None,
) -> int:
    settings = get_settings()
    limit = batch_size or settings.default_batch_size

    queue = RedisMessageQueue()
    events = MessageEventRepository()
    opt_outs = OptOutRepository()
    client: EvolutionClient | None = None
    messages = queue.list_pending(limit=limit, campaign_id=campaign_id)
    sent_count = 0

    for index, row in enumerate(messages):
        message_id = row["id"]
        if opt_outs.is_opted_out(row["phone"]):
            queue.mark_cancelled(message_id, "phone is opted out")
            _record_event(
                events,
                "cancelled",
                payload={
                    "redis_message_id": message_id,
                    "reason": "phone is opted out",
                },
                row=row,
            )
            logger.info("Message skipped due to opt-out: {}", row["phone"])
            continue

        try:
            if client is None:
                client = EvolutionClient()
            if row.get("image_path"):
                result = client.send_image(
                    phone=row["phone"],
                    image_path=row["image_path"],
                    caption=row["message"],
                )
            else:
                result = client.send_text(
                    row["phone"],
                    row["message"],
                    link_preview=False,
                )
        except Exception as exc:
            will_retry = queue.mark_failed(message_id, str(exc))
            _record_event(
                events,
                "failed",
                payload={
                    "redis_message_id": message_id,
                    "attempts": int(row.get("attempts") or 0) + 1,
                    "will_retry": will_retry,
                    "last_error": str(exc),
                },
                row=row,
            )
            logger.exception("Failed to send message {}", message_id)
        else:
            queue.mark_sent(message_id, result)
            _record_event(
                events,
                "sent",
                payload={
                    "redis_message_id": message_id,
                    "provider_response": result,
                    "image_path": row.get("image_path") or "",
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                },
                row=row,
            )
            sent_count += 1
            logger.info("Message sent to {}", row["phone"])

        if index < len(messages) - 1:
            wait_between_messages(settings.default_send_delay_seconds)

    return sent_count
