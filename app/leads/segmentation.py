from typing import Any


def filter_eligible_leads(leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        lead
        for lead in leads
        if lead.get("whatsapp_contato1") or lead.get("whatsapp_contato2")
    ]
