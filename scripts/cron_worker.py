import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import _path  # noqa: F401
from loguru import logger

from app.config import get_settings
from app.utils.logging import configure_logging
from app.whatsapp.dispatcher import dispatch_campaign_messages
from run_scheduled_campaign import parse_bool_env, run_due_scheduled_campaigns


def _read_positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if not raw_value:
        return default

    try:
        value = int(raw_value)
    except ValueError:
        logger.warning("{} must be an integer. Using default: {}", name, default)
        return default

    if value < 1:
        logger.warning("{} must be positive. Using default: {}", name, default)
        return default

    return value


def main() -> None:
    configure_logging()
    settings = get_settings()
    interval_seconds = _read_positive_int("WORKER_INTERVAL_SECONDS", 60)
    batch_size = _read_positive_int("WORKER_BATCH_SIZE", settings.default_batch_size)
    schedule_enabled = parse_bool_env(os.getenv("WHATSAPP_SCHEDULE_ENABLED"), True)
    schedule_dry_run = parse_bool_env(os.getenv("WHATSAPP_SCHEDULE_DRY_RUN"), False)

    logger.info(
        "Worker started with interval={}s batch_size={} schedule_enabled={} schedule_dry_run={}",
        interval_seconds,
        batch_size,
        schedule_enabled,
        schedule_dry_run,
    )

    while True:
        if schedule_enabled:
            try:
                now = datetime.now(ZoneInfo(settings.campaign_timezone))
                scheduled_results = run_due_scheduled_campaigns(
                    settings=settings,
                    run_date=now.date(),
                    run_time=now.time().replace(second=0, microsecond=0),
                    dry_run=schedule_dry_run,
                )
                for result in scheduled_results:
                    logger.info(
                        "Scheduled campaign processed: campaign={} lote={} queued={} dry_run={}",
                        result.scheduled.campaign_name,
                        result.scheduled.lote_key,
                        result.queued,
                        result.dry_run,
                    )
            except Exception:
                logger.exception("Scheduled campaign sync failed")

        try:
            sent_count = dispatch_campaign_messages(batch_size=batch_size)
            logger.info("Worker cycle completed. sent_count={}", sent_count)
        except Exception:
            logger.exception("Worker cycle failed")

        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
