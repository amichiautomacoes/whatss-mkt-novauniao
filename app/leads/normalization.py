import re


def normalize_phone(phone: str, default_country_code: str = "55") -> str:
    digits = re.sub(r"\D+", "", phone or "")
    if len(digits) in {10, 11}:
        return f"{default_country_code}{digits}"
    if digits.startswith(default_country_code) and len(digits) in {12, 13}:
        return digits
    return ""
