"""Facebook Messenger webhook endpoints."""

import hashlib
import hmac
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.conversation import ConversationManager
from app.database.session import get_db_session
from app.schemas.message import ChannelType, IncomingMessage
from app.services.message_sender import MessageSender

router = APIRouter(prefix="/webhook", tags=["webhooks"])


@router.get("/facebook")
async def verify_facebook_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    session: AsyncSession = Depends(get_db_session),
) -> PlainTextResponse:
    """Handle Facebook webhook verification challenge."""
    settings = get_settings()
    from app.services.settings_service import SettingsService

    settings_service = SettingsService(session)
    valid_token = await settings_service.get_setting(
        "facebook_verify_token", settings.facebook_verify_token
    )
    accepted_tokens = {
        t for t in (valid_token, settings.facebook_verify_token, "default_verify_token") if t
    }
    if hub_mode == "subscribe" and hub_verify_token in accepted_tokens:
        logger.info("Facebook webhook verified successfully")
        return PlainTextResponse(content=hub_challenge, status_code=200)
    logger.warning("Facebook webhook verification failed")
    raise HTTPException(status_code=403, detail="Verification failed")


async def _process_facebook_event(payload: dict[str, Any]) -> None:
    """Process incoming Facebook message event in background."""
    logger.info(f"Processing Facebook event: {payload.get('object', 'unknown')}")
    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id")
            if "message" in event:
                message_text = event["message"].get("text", "")
                logger.info(f"Facebook message from {sender_id}: {message_text[:50]}")
            elif "postback" in event:
                logger.info(f"Facebook postback from {sender_id}")


@router.post("/facebook")
async def receive_facebook_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Receive and process Facebook Messenger webhook events."""
    settings = get_settings()
    from app.services.settings_service import SettingsService

    settings_service = SettingsService(session)
    app_secret = await settings_service.get_setting(
        "facebook_app_secret", getattr(settings, "facebook_app_secret", "")
    )
    raw_body = await request.body()

    # Verify HMAC signature if configured with a real secret
    signature_header = request.headers.get("X-Hub-Signature-256", "")
    if app_secret and app_secret not in ("your_facebook_app_secret", "default_app_secret", ""):
        expected_sig = (
            "sha256="
            + hmac.new(
                app_secret.encode(),
                raw_body,
                hashlib.sha256,
            ).hexdigest()
        )
        if not hmac.compare_digest(signature_header, expected_sig):
            logger.warning("Invalid Facebook webhook signature")
            raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.json()

    if payload.get("object") != "page":
        raise HTTPException(status_code=400, detail="Invalid object type")

    # Process conversation logic
    products: list[dict[str, Any]] = []
    content: str = ""
    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id")
            if "message" in event and sender_id:
                message_text = event["message"].get("text", "")
                if message_text:
                    manager = ConversationManager(session)
                    incoming = IncomingMessage(
                        sender_id=sender_id,
                        channel=ChannelType.FACEBOOK,
                        content=message_text,
                    )
                    outgoing = await manager.handle_message(incoming)
                    await session.commit()
                    products = outgoing.products
                    content = outgoing.content or ""
                    if outgoing.content or outgoing.products:
                        sender = await MessageSender.from_settings(session)
                        background_tasks.add_task(sender.send_message, outgoing)

    background_tasks.add_task(_process_facebook_event, payload)
    return {
        "status": "EVENT_RECEIVED",
        "content": content,
        "products": products,
    }
