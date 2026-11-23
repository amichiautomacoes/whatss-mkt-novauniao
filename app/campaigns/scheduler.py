from datetime import date, datetime
from pathlib import Path

from app.campaigns.queue_builder import build_queue_rows, pick_lead_phone
from app.campaigns.templates import find_campaign_image_path
from app.db.history import MessageHistoryRepository
from app.db.repositories import (
    CampaignRepository,
    WhatsAppLeadRepository,
)
from app.leads.segmentation import filter_eligible_leads
from app.queue.redis_queue import RedisMessageQueue


def create_campaign_queue(
    campaign_id: int,
    limit: int | None = None,
    send_date: date | None = None,
    scheduled_start_at: datetime | None = None,
) -> int:
    campaign = CampaignRepository().get(campaign_id)
    if not campaign:
        raise RuntimeError(f"Campaign not found: {campaign_id}")
    if not campaign.get("lote"):
        raise RuntimeError("Campaign must have a lote before queue generation.")

    leads = WhatsAppLeadRepository().list_by_lote(campaign["lote"])
    eligible_leads = filter_eligible_leads(leads)
    history = MessageHistoryRepository()
    already_used_phones = history.list_campaign_phones(campaign["name"])
    eligible_leads = [
        lead
        for lead in eligible_leads
        if pick_lead_phone(lead) not in already_used_phones
    ]
    if limit is not None:
        eligible_leads = eligible_leads[:limit]

    image_path = find_campaign_image_path(campaign["name"])
    if image_path and not Path(image_path).is_file():
        raise RuntimeError(f"Campaign image not found: {image_path}")

    rows = build_queue_rows(
        campaign_id,
        eligible_leads,
        campaign["message_template"],
        image_path=image_path,
        send_date=send_date,
        scheduled_start_at=scheduled_start_at,
    )
    reserved_rows = []
    for row in rows:
        history_id = history.reserve(row, campaign["name"])
        if history_id is not None:
            reserved_rows.append({**row, "history_id": history_id})
    inserted = RedisMessageQueue().enqueue_many(reserved_rows)
    CampaignRepository().update_status(campaign_id, "queued")
    return inserted
