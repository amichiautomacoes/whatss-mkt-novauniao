from datetime import datetime, timezone

import httpx
from loguru import logger

from app.config import get_settings
from app.db.history import MessageHistoryRepository
from app.db.repositories import OptOutRepository
from app.queue.redis_queue import RedisMessageQueue
from app.whatsapp.evolution_client import EvolutionClient
from app.whatsapp.rate_limiter import wait_between_messages


def dispatch_pending_messages(batch_size: int | None = None) -> int:
    return dispatch_campaign_messages(batch_size=batch_size)


def dispatch_campaign_messages(
    batch_size: int | None = None,
    campaign_id: int | None = None,
    dispatch_until: datetime | None = None,
    reserved_before: datetime | None = None,
) -> int:
    settings = get_settings()
    limit = batch_size or settings.default_batch_size
    queue = RedisMessageQueue()
    history = MessageHistoryRepository()
    opt_outs = OptOutRepository()
    client: EvolutionClient | None = None

    history.expire_processing()
    # Recover reservations if enqueueing failed or Redis lost pending entries.
    eligibility = {"reserved_before": reserved_before} if reserved_before is not None else {}
    queue.enqueue_many(history.list_pending(
        limit=max(limit * 5, 100), campaign_id=campaign_id, **eligibility,
    ))
    messages = queue.list_pending(limit=limit, campaign_id=campaign_id)
    sent_count = 0

    for index, row in enumerate(messages):
        if dispatch_until is not None and datetime.now(timezone.utc) >= dispatch_until:
            break
        message_id = row["id"]
        history_id = row["history_id"]

        if row.get("provider_response") is not None:
            # A previous cycle sent successfully but could not persist the result.
            accepted_at = datetime.fromisoformat(row["accepted_at"])
            history.mark_sent(history_id, row["provider_response"], accepted_at)
            queue.mark_sent(message_id, row["provider_response"])
            continue

        if opt_outs.is_opted_out(row["phone"]):
            history.mark_cancelled(history_id, "phone is opted out")
            queue.mark_cancelled(message_id, "phone is opted out")
            continue

        # Persist the attempt before any provider call. DB failure stops the send.
        claimed = history.claim(history_id, **eligibility)
        if claimed is None:
            existing = history.get(history_id)
            if existing is None or existing["status"] != "processing":
                queue.mark_cancelled(message_id, "history is not eligible for this dispatch")
            continue

        try:
            if client is None:
                client = EvolutionClient()
            if row.get("image_path"):
                result = client.send_image(
                    phone=row["phone"], image_path=row["image_path"], caption=row["message"],
                )
            else:
                result = client.send_text(row["phone"], row["message"], link_preview=False)
        except (RuntimeError, FileNotFoundError) as exc:
            # Local configuration/media failure, before a request could be sent.
            will_retry = claimed["attempts"] < settings.redis_max_attempts
            history.mark_failed(history_id, str(exc), will_retry)
            queue.mark_failed(message_id, str(exc))
            logger.exception("Message {} could not be prepared", message_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                will_retry = claimed["attempts"] < settings.redis_max_attempts
                history.mark_failed(history_id, str(exc), will_retry)
                queue.mark_failed(message_id, str(exc))
            else:
                history.mark_uncertain(history_id, str(exc))
                queue.mark_cancelled(message_id, "provider result is uncertain")
            logger.exception("Provider rejected message {}", message_id)
        except Exception as exc:
            # A timeout/connection loss does not establish whether a send occurred.
            history.mark_uncertain(history_id, str(exc))
            queue.mark_cancelled(message_id, "provider result is uncertain")
            logger.exception("Message {} needs provider verification", message_id)
        else:
            accepted_at = datetime.now(timezone.utc)
            try:
                queue.record_provider_response(message_id, result, accepted_at)
            except Exception:
                logger.exception("Could not cache provider result for {}", message_id)
            history.mark_sent(history_id, result, accepted_at)
            queue.mark_sent(message_id, result)
            sent_count += 1
            logger.info("Message sent; history_id={}", history_id)

        if index < len(messages) - 1:
            wait_between_messages(settings.default_send_delay_seconds)

    return sent_count
