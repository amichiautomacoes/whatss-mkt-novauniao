from typing import Any

from app.leads.normalization import normalize_phone


def filter_eligible_leads(leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = []
    seen_phones: set[str] = set()
    for lead in leads:
        phone = normalize_phone(str(lead.get("telefone_contato") or ""))
        if not phone or phone in seen_phones:
            continue
        seen_phones.add(phone)
        eligible.append(lead)
    return eligible
