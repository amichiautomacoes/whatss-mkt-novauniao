from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings


def parse_hhmm(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))


def default_send_date() -> date:
    settings = get_settings()
    local_now = datetime.now(ZoneInfo(settings.campaign_timezone))
    return local_now.date() + timedelta(days=1)


def build_split_schedule(total: int, send_date: date | None = None) -> list[datetime]:
    settings = get_settings()
    tz = ZoneInfo(settings.campaign_timezone)
    target_date = send_date or default_send_date()
    delay = timedelta(seconds=settings.default_send_delay_seconds)

    morning_start = datetime.combine(
        target_date,
        parse_hhmm(settings.morning_send_start),
        tzinfo=tz,
    )
    afternoon_start = datetime.combine(
        target_date,
        parse_hhmm(settings.afternoon_send_start),
        tzinfo=tz,
    )

    morning_count = (total + 1) // 2
    afternoon_count = total - morning_count

    schedule = [
        morning_start + (delay * index)
        for index in range(morning_count)
    ]
    schedule.extend(
        afternoon_start + (delay * index)
        for index in range(afternoon_count)
    )
    return schedule
