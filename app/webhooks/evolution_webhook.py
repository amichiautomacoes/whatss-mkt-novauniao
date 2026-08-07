from typing import Any

from fastapi import APIRouter, Request
from loguru import logger

router = APIRouter(tags=["evolution"])


@router.post("/evolution")
async def receive_evolution_event(request: Request) -> dict[str, Any]:
    payload = await request.json()
    logger.info("Evolution webhook event received: {}", payload.get("event"))

    # TODO: persist delivery, read, reply, and opt-out events in Supabase.
    return {"received": True}
