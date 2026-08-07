import re


def normalize_phone(phone: str, default_country_code: str = "55") -> str:
    digits = re.sub(r"\D+", "", phone or "")
    if not digits:
        return ""

    if not digits.startswith(default_country_code):
        digits = f"{default_country_code}{digits}"

    return digits
