import argparse
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import _path  # noqa: F401
except ModuleNotFoundError:
    from scripts import _path  # noqa: F401

from app.campaigns.queue_builder import pick_lead_phone
from app.campaigns.scheduling import schedule_after_email_open
from app.campaigns.templates import find_campaign_template, render_template
from app.config import Settings, get_settings
from app.db.history import MessageHistoryRepository
from app.db.repositories import CampaignRepository, WhatsAppLeadRepository


AUTOMATIC_LOTE = "automatico"


@dataclass(frozen=True)
class OpenedRunResult:
    campaign_id: int | None
    eligible: int
    reserved: int
    dry_run: bool


def schedule_opened_email_campaign(
    settings: Settings, now: datetime, dry_run: bool = False,
) -> OpenedRunResult:
    if now.tzinfo is None:
        raise ValueError("Current time must include a timezone")
    if not settings.whatsapp_campaign_name.strip():
        raise RuntimeError("Configure WHATSAPP_CAMPAIGN_NAME depois de cadastrar a nova mensagem.")
    template = find_campaign_template(settings.whatsapp_campaign_name)
    message_template = str(template["corpo"])
    campaign_name = str(template["nome"])
    image_path = str(template.get("image_path") or "").strip()
    if image_path and not Path(image_path).is_file():
        raise RuntimeError(f"Campaign image not found: {image_path}")

    tz = ZoneInfo(settings.campaign_timezone)
    opened_from = datetime.combine(settings.whatsapp_opened_from, time.min, tzinfo=tz)
    leads = WhatsAppLeadRepository().list_opened_since(
        opened_from=opened_from, as_of=now, campaign_name=campaign_name,
        limit=settings.whatsapp_schedule_limit,
    )
    campaigns = CampaignRepository()
    campaign = campaigns.find(campaign_name, AUTOMATIC_LOTE)
    if dry_run or not leads:
        return OpenedRunResult(campaign["id"] if campaign else None, len(leads), 0, dry_run)

    if campaign is None:
        campaign = campaigns.create(campaign_name, message_template, lote=AUTOMATIC_LOTE)
    history = MessageHistoryRepository()
    reserved = 0
    for lead in leads:
        phone = pick_lead_phone(lead)
        if not phone:
            continue
        row = {
            "campaign_id": campaign["id"], "source_id": lead["source_id"],
            "lead_key": str(lead["lead_key"]), "phone": phone,
            "message": render_template(message_template, lead), "image_path": image_path,
            "email_opened_at": lead["primeira_abertura"],
            "scheduled_at": schedule_after_email_open(lead["primeira_abertura"], settings),
        }
        if history.reserve(row, campaign_name) is not None:
            reserved += 1
    if reserved:
        campaigns.update_status(campaign["id"], "queued")
    return OpenedRunResult(campaign["id"], len(leads), reserved, False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reserve WhatsApp sends from Supabase email openings; does not send messages.")
    parser.add_argument("--dry-run", action="store_true", help="Read candidates without creating campaigns or history.")
    args = parser.parse_args()
    settings = get_settings()
    result = schedule_opened_email_campaign(
        settings, datetime.now(ZoneInfo(settings.campaign_timezone)),
        dry_run=args.dry_run or settings.whatsapp_schedule_dry_run,
    )
    print(f"eligible={result.eligible} reserved={result.reserved} campaign_id={result.campaign_id} dry_run={result.dry_run}")


if __name__ == "__main__":
    main()
