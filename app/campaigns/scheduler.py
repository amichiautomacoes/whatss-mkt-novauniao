from datetime import date

from app.campaigns.queue_builder import build_queue_rows
from app.db.repositories import (
    CampaignRepository,
    MessageQueueRepository,
    WhatsAppLeadRepository,
)
from app.leads.segmentation import filter_eligible_leads


def create_campaign_queue(
    campaign_id: int,
    limit: int | None = None,
    send_date: date | None = None,
) -> int:
    campaign = CampaignRepository().get(campaign_id)
    if not campaign:
        raise RuntimeError(f"Campaign not found: {campaign_id}")
    if not campaign.get("lote"):
        raise RuntimeError("Campaign must have a lote before queue generation.")

    leads = WhatsAppLeadRepository().list_by_lote(campaign["lote"], limit=limit)
    eligible_leads = filter_eligible_leads(leads)
    rows = build_queue_rows(
        campaign_id,
        eligible_leads,
        campaign["message_template"],
        send_date=send_date,
    )
    inserted = MessageQueueRepository().enqueue_many(rows)
    CampaignRepository().update_status(campaign_id, "queued")
    return inserted
