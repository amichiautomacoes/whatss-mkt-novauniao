from datetime import datetime, timezone

from loguru import logger

from app.config import get_settings
from app.db.repositories import MessageQueueRepository
from app.whatsapp.evolution_client import EvolutionClient
from app.whatsapp.rate_limiter import wait_between_messages


def dispatch_pending_messages(batch_size: int | None = None) -> int:
    return dispatch_campaign_messages(batch_size=batch_size)


def dispatch_campaign_messages(
    batch_size: int | None = None,
    campaign_id: int | None = None,
) -> int:
    settings = get_settings()
    limit = batch_size or settings.default_batch_size

    queue = MessageQueueRepository()
    client = EvolutionClient()
    messages = queue.list_pending(limit=limit, campaign_id=campaign_id)
    sent_count = 0

    for row in messages:
        message_id = row["id"]
        try:
            queue.update_status(message_id, "processing")
            result = client.send_text(row["phone"], row["message"])
            queue.update_status(
                message_id,
                "sent",
                {
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "provider_response": result,
                },
            )
            sent_count += 1
            logger.info("Message sent to {}", row["phone"])
        except Exception as exc:
            attempts = int(row.get("attempts") or 0) + 1
            queue.update_status(
                message_id,
                "failed",
                {"attempts": attempts, "last_error": str(exc)},
            )
            logger.exception("Failed to send message {}", message_id)

        wait_between_messages(settings.default_send_delay_seconds)

    return sent_count
