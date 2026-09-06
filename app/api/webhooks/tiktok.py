"""TikTok webhook endpoints."""

import hashlib
import hmac
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from loguru import logger

from app.config import get_settings

router = APIRouter(prefix="/webhook", tags=["webhooks"])


async def _process_tiktok_event(payload: Dict[str, Any]) -> None:
    """Process TikTok webhook events."""
    logger.info(
        f"Processing TikTok event type: {payload.get('type')}, event: {payload.get('event')}"
    )


@router.post("/tiktok")
async def receive_tiktok_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Receive and process TikTok webhook events."""
    settings = get_settings()
    raw_body = await request.body()

    signature_header = request.headers.get("X-Tiktok-Signature", "")
    if getattr(settings, "tiktok_app_secret", None) and signature_header:
        expected_sig = hmac.new(
            settings.tiktok_app_secret.encode(),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature_header, expected_sig):
            logger.warning("Invalid TikTok webhook signature")
            raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.json()
    background_tasks.add_task(_process_tiktok_event, payload)
    return {"status": "EVENT_RECEIVED"}
