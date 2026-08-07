from hmac import compare_digest
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator

from app.config import get_settings
from app.whatsapp.dispatcher import dispatch_campaign_messages
from app.whatsapp.evolution_client import EvolutionClient


router = APIRouter(tags=["dispatch"])


class DispatchRequest(BaseModel):
    campaign_id: int | None = None
    batch_size: int = Field(default=1, ge=1, le=20)
    phone: str | None = None
    message: str | None = None
    link_preview: bool = True

    @model_validator(mode="after")
    def validate_dispatch_mode(self) -> "DispatchRequest":
        has_direct_message = bool(self.phone or self.message)
        if has_direct_message and not (self.phone and self.message):
            raise ValueError("phone and message must be provided together")
        if has_direct_message and self.campaign_id is not None:
            raise ValueError("use either direct message fields or campaign_id, not both")
        if not has_direct_message and self.campaign_id is None:
            raise ValueError("provide campaign_id or phone/message")
        return self


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def _validate_dispatch_token(
    authorization: str | None,
    x_dispatch_token: str | None,
    token: str | None,
) -> None:
    expected_token = get_settings().dispatch_webhook_token
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DISPATCH_WEBHOOK_TOKEN is not configured",
        )

    provided_token = x_dispatch_token or _extract_bearer_token(authorization) or token
    if not provided_token or not compare_digest(provided_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid dispatch token",
        )


@router.post("/dispatch")
def dispatch_webhook(
    payload: DispatchRequest,
    authorization: str | None = Header(default=None),
    x_dispatch_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict[str, Any]:
    _validate_dispatch_token(authorization, x_dispatch_token, token)

    if payload.phone and payload.message:
        result = EvolutionClient().send_text(
            phone=payload.phone,
            message=payload.message,
            link_preview=payload.link_preview,
        )
        return {
            "mode": "direct",
            "sent": True,
            "phone": payload.phone,
            "provider_response": result,
        }

    sent_count = dispatch_campaign_messages(
        batch_size=payload.batch_size,
        campaign_id=payload.campaign_id,
    )
    return {
        "mode": "campaign",
        "campaign_id": payload.campaign_id,
        "batch_size": payload.batch_size,
        "sent_count": sent_count,
    }
