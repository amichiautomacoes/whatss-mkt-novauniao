from app.leads.normalization import normalize_phone


def is_valid_br_phone(phone: str) -> bool:
    normalized = normalize_phone(phone)
    return len(normalized) in {12, 13} and normalized.startswith("55")
