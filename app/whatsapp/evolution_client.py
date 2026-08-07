from typing import Any

import httpx

from app.config import get_settings


class EvolutionClient:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.evolution_api_url or not settings.evolution_api_key:
            raise RuntimeError("Evolution API credentials are missing in .env")

        self.base_url = settings.evolution_api_url.rstrip("/")
        self.api_key = settings.evolution_api_key
        self.instance = settings.evolution_instance

    def _headers(self) -> dict[str, str]:
        return {"apikey": self.api_key, "Content-Type": "application/json"}

    def send_text(
        self,
        phone: str,
        message: str,
        link_preview: bool = True,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/message/sendText/{self.instance}"
        payload = {
            "number": phone,
            "text": message,
            "linkPreview": link_preview,
        }

        with httpx.Client(timeout=30, trust_env=False) as client:
            response = client.post(url, json=payload, headers=self._headers())
            response.raise_for_status()
            return response.json()

    def check_instance_status(self) -> dict[str, Any]:
        url = f"{self.base_url}/instance/connectionState/{self.instance}"

        with httpx.Client(timeout=30, trust_env=False) as client:
            response = client.get(url, headers=self._headers())
            response.raise_for_status()
            return response.json()
