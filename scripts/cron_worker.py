import time
from datetime import datetime, time as day_time, timedelta
from zoneinfo import ZoneInfo

try:
    import _path  # noqa: F401
except ModuleNotFoundError:
    from scripts import _path  # noqa: F401

from loguru import logger

from app.campaigns.scheduling import DailySendWindow, parse_hhmm
from app.config import Settings, get_settings
from app.utils.logging import configure_logging
from app.whatsapp.dispatcher import dispatch_campaign_messages
from scripts.run_opened_campaign import schedule_opened_email_campaign


def run_worker_cycle(settings: Settings, window: DailySendWindow, now: datetime) -> int:
    if not settings.whatsapp_schedule_enabled:
        return 0
    try:
        result = schedule_opened_email_campaign(
            settings, now, dry_run=settings.whatsapp_schedule_dry_run,
        )
        logger.info(
            "Supabase openings: eligible={} reserved={} dry_run={}",
            result.eligible, result.reserved, result.dry_run,
        )
        if settings.whatsapp_schedule_dry_run or not window.is_open(now):
            return 0
        if result.campaign_id is None:
            return 0
        tz = ZoneInfo(settings.campaign_timezone)
        next_midnight = datetime.combine(
            now.astimezone(tz).date() + timedelta(days=1), day_time.min, tzinfo=tz,
        )
        reservation_cutoff = datetime.combine(
            now.astimezone(tz).date(), parse_hhmm(settings.whatsapp_send_time), tzinfo=tz,
        ) + timedelta(minutes=1)
        return dispatch_campaign_messages(
            batch_size=settings.worker_batch_size, campaign_id=result.campaign_id,
            dispatch_until=next_midnight,
            reserved_before=reservation_cutoff,
        )
    except Exception:
        # A failed operational cycle closes today's window, avoiding late recovery.
        window.suspend(now)
        raise


def seconds_until_next_cycle(settings: Settings, now: datetime) -> float:
    tz = ZoneInfo(settings.campaign_timezone)
    local_now = now.astimezone(tz)
    start = datetime.combine(
        local_now.date(), parse_hhmm(settings.whatsapp_send_time), tzinfo=tz,
    )
    delay = max(settings.worker_interval_seconds, settings.default_send_delay_seconds)
    if local_now < start:
        return min(delay, (start - local_now).total_seconds())
    return delay


def main() -> None:
    configure_logging()
    settings = get_settings()
    window = DailySendWindow(settings=settings)
    logger.info(
        "Worker using Supabase openings: campaign={} opened_from={} send_time={} timezone={} dry_run={}",
        settings.whatsapp_campaign_name, settings.whatsapp_opened_from,
        settings.whatsapp_send_time, settings.campaign_timezone, settings.whatsapp_schedule_dry_run,
    )
    while True:
        now = datetime.now(ZoneInfo(settings.campaign_timezone))
        try:
            sent_count = run_worker_cycle(settings, window, now)
            logger.info("Worker cycle completed. sent_count={}", sent_count)
        except Exception:
            logger.exception("Worker cycle failed; pending sends wait for the next daily window")
        time.sleep(seconds_until_next_cycle(
            settings, datetime.now(ZoneInfo(settings.campaign_timezone)),
        ))


if __name__ == "__main__":
    main()
