from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import Settings, get_settings


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


def build_linear_schedule(total: int, start_at: datetime) -> list[datetime]:
    settings = get_settings()
    delay = timedelta(seconds=settings.default_send_delay_seconds)
    return [start_at + (delay * index) for index in range(total)]


def schedule_after_email_open(opened_at: datetime, settings: Settings | None = None) -> datetime:
    if opened_at.tzinfo is None:
        raise ValueError("Email opening must include a timezone")
    settings = settings or get_settings()
    tz = ZoneInfo(settings.campaign_timezone)
    send_date = opened_at.astimezone(tz).date() + timedelta(days=1)
    return datetime.combine(send_date, parse_hhmm(settings.whatsapp_send_time), tzinfo=tz)


@dataclass
class DailySendWindow:
    """Open at the daily start minute; a restart or outage waits for the next start."""

    active_date: date | None = None
    suspended_date: date | None = None
    settings: Settings = field(default_factory=get_settings, repr=False)

    def is_open(self, now: datetime) -> bool:
        settings = self.settings
        local_now = now.astimezone(ZoneInfo(settings.campaign_timezone))
        start = datetime.combine(
            local_now.date(), parse_hhmm(settings.whatsapp_send_time), tzinfo=local_now.tzinfo,
        )
        if self.suspended_date == local_now.date() or local_now < start:
            return False
        if start <= local_now < start + timedelta(minutes=1):
            self.active_date = local_now.date()
        return self.active_date == local_now.date()

    def suspend(self, now: datetime) -> None:
        settings = self.settings
        local_now = now.astimezone(ZoneInfo(settings.campaign_timezone))
        if local_now.time().replace(tzinfo=None) >= parse_hhmm(settings.whatsapp_send_time):
            self.suspended_date = local_now.date()
            self.active_date = None
