import os
import time

import _path  # noqa: F401
from loguru import logger

from app.config import get_settings
from app.utils.logging import configure_logging
from app.whatsapp.dispatcher import dispatch_campaign_messages


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

    logger.info(
        "Worker started with interval={}s batch_size={}",
        interval_seconds,
        batch_size,
    )

    while True:
        try:
            sent_count = dispatch_campaign_messages(batch_size=batch_size)
            logger.info("Worker cycle completed. sent_count={}", sent_count)
        except Exception:
            logger.exception("Worker cycle failed")

        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
