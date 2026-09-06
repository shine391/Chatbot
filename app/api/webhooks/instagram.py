"""Instagram webhook endpoints."""

import hashlib
import hmac
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from loguru import logger

from app.config import get_settings

router = APIRouter(prefix="/webhook", tags=["webhooks"])


@router.get("/instagram")
async def verify_instagram_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
) -> PlainTextResponse:
    """Handle Instagram webhook verification challenge."""
    settings = get_settings()
    if hub_mode == "subscribe" and hub_verify_token == settings.facebook_verify_token:
        logger.info("Instagram webhook verified successfully")
        return PlainTextResponse(content=hub_challenge, status_code=200)
    logger.warning("Instagram webhook verification failed")
    raise HTTPException(status_code=403, detail="Verification failed")


async def _process_instagram_event(payload: dict[str, Any]) -> None:
    """Process incoming Instagram message event in background."""
    logger.info(f"Processing Instagram event: {payload.get('object', 'unknown')}")
    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id")
            if "message" in event:
                message_text = event["message"].get("text", "")
                logger.info(f"Instagram message from {sender_id}: {message_text[:50]}")
            elif "postback" in event:
                logger.info(f"Instagram postback from {sender_id}")


@router.post("/instagram")
async def receive_instagram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Receive and process Instagram webhook events."""
    settings = get_settings()
    raw_body = await request.body()

    # Verify HMAC signature using facebook_app_secret
    signature_header = request.headers.get("X-Hub-Signature-256", "")
    if getattr(settings, "facebook_app_secret", None):
        expected_sig = (
            "sha256="
            + hmac.new(
                settings.facebook_app_secret.encode(),
                raw_body,
                hashlib.sha256,
            ).hexdigest()
        )
        if not hmac.compare_digest(signature_header, expected_sig):
            logger.warning("Invalid Instagram webhook signature")
            raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.json()

    if payload.get("object") != "instagram":
        raise HTTPException(status_code=400, detail="Invalid object type")

    background_tasks.add_task(_process_instagram_event, payload)
    return {"status": "EVENT_RECEIVED"}
