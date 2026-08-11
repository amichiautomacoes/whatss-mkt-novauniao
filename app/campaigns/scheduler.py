from datetime import date, datetime

from app.campaigns.queue_builder import build_queue_rows
from app.db.repositories import (
    CampaignRepository,
    MessageEventRepository,
    WhatsAppLeadRepository,
)
from app.leads.segmentation import filter_eligible_leads
from app.queue.redis_queue import RedisMessageQueue


def create_campaign_queue(
    campaign_id: int,
    limit: int | None = None,
    send_date: date | None = None,
    scheduled_start_at: datetime | None = None,
    excluded_event_types: list[str] | None = None,
) -> int:
    campaign = CampaignRepository().get(campaign_id)
    if not campaign:
        raise RuntimeError(f"Campaign not found: {campaign_id}")
    if not campaign.get("lote"):
        raise RuntimeError("Campaign must have a lote before queue generation.")

    leads = WhatsAppLeadRepository().list_by_lote(campaign["lote"])
    eligible_leads = filter_eligible_leads(leads)
    event_repo = MessageEventRepository()
    already_used_lead_keys = event_repo.list_lead_keys_with_events(
        campaign_id=campaign_id,
        event_types=excluded_event_types or ["sent"],
    )
    eligible_leads = [
        lead
        for lead in eligible_leads
        if lead["lead_key"] not in already_used_lead_keys
    ]
    if limit is not None:
        eligible_leads = eligible_leads[:limit]
    rows = build_queue_rows(
        campaign_id,
        eligible_leads,
        campaign["message_template"],
        send_date=send_date,
        scheduled_start_at=scheduled_start_at,
    )
    inserted = RedisMessageQueue().enqueue_many(rows)
    for row in rows:
        event_repo.create(
            event_type="queued",
            payload={
                "redis_message_id": f"{row['campaign_id']}:{row['lead_key']}",
                "scheduled_at": row["scheduled_at"].isoformat(),
            },
            campaign_id=row["campaign_id"],
            lead_key=row["lead_key"],
            phone=row["phone"],
        )
    CampaignRepository().update_status(campaign_id, "queued")
    return inserted
