import json
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


CAMPAIGN_TEMPLATES_PATH = Path("campanhas/campanhas_extraidas.json")


def load_campaign_templates(path: Path = CAMPAIGN_TEMPLATES_PATH) -> list[dict[str, Any]]:
    templates = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(templates, list):
        raise RuntimeError(f"Templates file must contain a list: {path}")
    return templates


def find_campaign_template(
    campaign_name: str,
    templates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    target = _normalize_lookup_key(campaign_name)
    for template in templates or load_campaign_templates():
        if _normalize_lookup_key(str(template.get("nome", ""))) == target:
            return template
    raise RuntimeError(f"Template nao encontrado para {campaign_name!r}")


def find_campaign_message_template(
    campaign_name: str,
    templates: list[dict[str, Any]] | None = None,
) -> str:
    return str(find_campaign_template(campaign_name, templates)["corpo"])


def find_campaign_image_path(campaign_name: str) -> str:
    try:
        template = find_campaign_template(campaign_name)
    except RuntimeError:
        return ""
    image_path = str(template.get("image_path") or "").strip()
    return image_path


def render_template(template: str, lead: dict[str, Any]) -> str:
    message = template
    for key, value in lead.items():
        message = message.replace(f"{{{{{key}}}}}", str(value or ""))
    message = shorten_marketing_links(message)
    return re.sub(r"\s+([!?.,:;])", r"\1", message)


def shorten_marketing_links(message: str) -> str:
    return re.sub(r"https?://[^\s]+", _shorten_url_match, message)


def _shorten_url_match(match: re.Match[str]) -> str:
    url = match.group(0)
    trailing = ""
    while url and url[-1] in ".,;:)":
        trailing = url[-1] + trailing
        url = url[:-1]

    return _shorten_url(url) + trailing


def _shorten_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if host in {"www.instagram.com", "instagram.com"}:
        return f"https://instagram.com{parsed.path}"

    if host == "api.whatsapp.com" and parsed.path.rstrip("/") == "/send":
        phone = parse_qs(parsed.query).get("phone", [""])[0]
        digits = re.sub(r"\D", "", phone)
        if digits:
            return f"https://wa.me/{digits}"

    if host == "wa.me":
        digits = re.sub(r"\D", "", parsed.path)
        if digits:
            return f"https://wa.me/{digits}"

    return url


def _normalize_lookup_key(value: str) -> str:
    without_accents = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"[^a-z0-9]", "", without_accents.lower())
