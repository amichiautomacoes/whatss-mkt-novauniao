from datetime import date, datetime
from typing import Any

from app.campaigns.scheduling import build_linear_schedule, build_split_schedule
from app.campaigns.templates import render_template
from app.leads.normalization import normalize_phone


def pick_lead_phone(lead: dict[str, Any]) -> str:
    return normalize_phone(
        str(lead.get("whatsapp_contato1") or lead.get("whatsapp_contato2") or "")
    )


def build_queue_rows(
    campaign_id: int,
    leads: list[dict[str, Any]],
    message_template: str,
    image_path: str = "",
    send_date: date | None = None,
    scheduled_start_at: datetime | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if scheduled_start_at is not None:
        schedule = build_linear_schedule(len(leads), scheduled_start_at)
    else:
        schedule = build_split_schedule(len(leads), send_date=send_date)

    for lead, scheduled_at in zip(leads, schedule):
        phone = pick_lead_phone(lead)
        if not phone:
            continue

        rows.append(
            {
                "campaign_id": campaign_id,
                "lead_key": lead["lead_key"],
                "phone": phone,
                "message": render_template(message_template, lead),
                "image_path": image_path,
                "status": "pending",
                "attempts": 0,
                "scheduled_at": scheduled_at,
            }
        )

    return rows
