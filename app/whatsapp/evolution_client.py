import mimetypes
from pathlib import Path
from typing import Any

import httpx

from app.campaigns.templates import shorten_marketing_links
from app.config import get_settings


def build_text_payload(
    phone: str,
    message: str,
    link_preview: bool = False,
) -> dict[str, Any]:
    return {
        "number": phone,
        "text": shorten_marketing_links(message),
        "linkPreview": link_preview,
    }


class EvolutionClient:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.evolution_api_url or not settings.evolution_api_key:
            raise RuntimeError("Evolution API credentials are missing in .env")

        self.base_url = settings.evolution_api_url.rstrip("/")
        self.api_key = settings.evolution_api_key
        self.instance = settings.evolution_instance

    def _headers(self, content_type: str | None = "application/json") -> dict[str, str]:
        headers = {"apikey": self.api_key}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def send_text(
        self,
        phone: str,
        message: str,
        link_preview: bool = False,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/message/sendText/{self.instance}"
        payload = build_text_payload(phone, message, link_preview)

        with httpx.Client(timeout=30, trust_env=False) as client:
            response = client.post(url, json=payload, headers=self._headers())
            response.raise_for_status()
            return response.json()

    def send_image(
        self,
        phone: str,
        image_path: str | Path,
        caption: str = "",
    ) -> dict[str, Any]:
        path = Path(image_path)
        if not path.is_file():
            raise RuntimeError(f"Image file not found: {path}")

        url = f"{self.base_url}/message/sendMedia/{self.instance}"
        file_name = path.name
        mime_type = mimetypes.guess_type(file_name)[0] or "image/png"
        data = {
            "number": phone,
            "mediatype": "image",
            "caption": shorten_marketing_links(caption),
            "fileName": file_name,
        }

        with path.open("rb") as media_file:
            files = {"media": (file_name, media_file, mime_type)}
            with httpx.Client(timeout=60, trust_env=False) as client:
                response = client.post(
                    url,
                    data=data,
                    files=files,
                    headers=self._headers(content_type=None),
                )
                response.raise_for_status()
                return response.json()

    def check_instance_status(self) -> dict[str, Any]:
        url = f"{self.base_url}/instance/connectionState/{self.instance}"

        with httpx.Client(timeout=30, trust_env=False) as client:
            response = client.get(url, headers=self._headers())
            response.raise_for_status()
            return response.json()
