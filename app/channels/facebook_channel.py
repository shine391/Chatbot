"""Facebook Messenger channel adapter."""

import hashlib
import hmac
from typing import Any

import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.base import BaseChannel
from app.config import get_settings
from app.schemas.message import ChannelType, IncomingMessage, MessageResponse


class FacebookChannel(BaseChannel):
    """Facebook Messenger channel adapter using Meta Graph API v21.0."""

    def __init__(
        self,
        access_token: str | None = None,
        app_secret: str | None = None,
        verify_token: str | None = None,
    ) -> None:
        self.settings = get_settings()
        self._access_token = access_token
        self._app_secret = app_secret
        self._verify_token = verify_token
        self.api_url = "https://graph.facebook.com/v21.0/me/messages"

    @classmethod
    async def from_settings(cls, session: AsyncSession) -> "FacebookChannel":
        """Construct FacebookChannel dynamically using settings from database with .env fallback."""
        from app.services.settings_service import SettingsService

        settings_service = SettingsService(session)
        access_token = await settings_service.get_setting("facebook_page_access_token")
        app_secret = await settings_service.get_setting("facebook_app_secret")
        verify_token = await settings_service.get_setting("facebook_verify_token")
        return cls(
            access_token=access_token or None,
            app_secret=app_secret or None,
            verify_token=verify_token or None,
        )

    @property
    def access_token(self) -> str:
        return self._access_token or self.settings.facebook_page_access_token

    @property
    def app_secret(self) -> str:
        return self._app_secret or self.settings.facebook_app_secret

    @property
    def verify_token(self) -> str:
        return self._verify_token or self.settings.facebook_verify_token

    async def parse_incoming(self, raw_data: dict[str, Any]) -> IncomingMessage:
        """Parse Facebook webhook payload into IncomingMessage."""
        try:
            entry = raw_data.get("entry", [{}])[0]
            messaging = entry.get("messaging", [{}])[0]
            sender_id = messaging.get("sender", {}).get("id", "")
            message = messaging.get("message", {})
            text = message.get("text")
            media_urls: list[str] = []

            for attachment in message.get("attachments", []):
                url = attachment.get("payload", {}).get("url")
                if url:
                    media_urls.append(url)

            return IncomingMessage(
                channel=ChannelType.FACEBOOK,
                sender_id=sender_id,
                content=text,
                media_urls=media_urls,
                platform_message_id=message.get("mid"),
                raw_data=raw_data,
            )
        except Exception as e:
            logger.error(f"Error parsing Facebook webhook: {e}")
            raise

    async def _send_request(self, payload: dict[str, Any]) -> MessageResponse:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.api_url,
                    params={"access_token": self.access_token},
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                return MessageResponse(success=True, message_id=data.get("message_id"))
        except httpx.HTTPError as e:
            logger.error(f"HTTP error sending to Facebook: {e}")
            return MessageResponse(success=False, error=str(e))
        except Exception as e:
            logger.error(f"Unexpected error sending to Facebook: {e}")
            return MessageResponse(success=False, error=str(e))

    async def send_text(
        self,
        recipient_id: str,
        text: str,
        messaging_type: str = "RESPONSE",
        tag: str | None = None,
    ) -> MessageResponse:
        """Send a text message with optional messaging_type and Meta policy tag."""
        if tag and messaging_type == "RESPONSE":
            messaging_type = "MESSAGE_TAG"

        payload: dict[str, Any] = {
            "recipient": {"id": recipient_id},
            "messaging_type": messaging_type,
            "message": {"text": text},
        }
        if tag:
            payload["tag"] = tag
        return await self._send_request(payload)

    async def send_image(
        self,
        recipient_id: str,
        image_url: str,
        caption: str | None = None,
        messaging_type: str = "RESPONSE",
        tag: str | None = None,
    ) -> MessageResponse:
        """Send an image attachment via URL with optional tag."""
        if tag and messaging_type == "RESPONSE":
            messaging_type = "MESSAGE_TAG"

        payload: dict[str, Any] = {
            "recipient": {"id": recipient_id},
            "messaging_type": messaging_type,
            "message": {
                "attachment": {
                    "type": "image",
                    "payload": {"url": image_url, "is_reusable": True},
                }
            },
        }
        if tag:
            payload["tag"] = tag
        return await self._send_request(payload)

    async def send_video(
        self,
        recipient_id: str,
        video_url: str,
        caption: str | None = None,
        messaging_type: str = "RESPONSE",
        tag: str | None = None,
    ) -> MessageResponse:
        """Send a video attachment via URL with optional tag."""
        if tag and messaging_type == "RESPONSE":
            messaging_type = "MESSAGE_TAG"

        payload: dict[str, Any] = {
            "recipient": {"id": recipient_id},
            "messaging_type": messaging_type,
            "message": {
                "attachment": {
                    "type": "video",
                    "payload": {"url": video_url, "is_reusable": True},
                }
            },
        }
        if tag:
            payload["tag"] = tag
        return await self._send_request(payload)

    def _build_element(self, product: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": product.get("name", "Product"),
            "subtitle": str(product.get("price", "")),
            "image_url": product.get("image_url", ""),
            "default_action": {
                "type": "web_url",
                "url": product.get("website_url") or product.get("url", ""),
            },
            "buttons": [
                {
                    "type": "web_url",
                    "title": "Xem chi tiết",
                    "url": product.get("website_url") or product.get("url", ""),
                }
            ],
        }

    async def send_product_card(
        self,
        recipient_id: str,
        product: dict[str, Any],
        messaging_type: str = "RESPONSE",
        tag: str | None = None,
    ) -> MessageResponse:
        """Send a single generic template element with optional tag."""
        if tag and messaging_type == "RESPONSE":
            messaging_type = "MESSAGE_TAG"

        payload: dict[str, Any] = {
            "recipient": {"id": recipient_id},
            "messaging_type": messaging_type,
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "generic",
                        "elements": [self._build_element(product)],
                    },
                }
            },
        }
        if tag:
            payload["tag"] = tag
        return await self._send_request(payload)

    async def send_carousel(
        self,
        recipient_id: str,
        products: list[dict[str, Any]],
        messaging_type: str = "RESPONSE",
        tag: str | None = None,
    ) -> MessageResponse:
        """Send a carousel generic template with optional tag."""
        if tag and messaging_type == "RESPONSE":
            messaging_type = "MESSAGE_TAG"

        elements = [self._build_element(p) for p in products[:4]]
        payload: dict[str, Any] = {
            "recipient": {"id": recipient_id},
            "messaging_type": messaging_type,
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "generic",
                        "elements": elements,
                    },
                }
            },
        }
        if tag:
            payload["tag"] = tag
        return await self._send_request(payload)

    def verify_webhook(
        self, headers: dict[str, str], body: bytes, params: dict[str, str] | None = None
    ) -> bool:
        """Verify HMAC-SHA256 signature."""
        signature = headers.get("x-hub-signature-256", "")
        if not signature.startswith("sha256="):
            return False

        expected_hash = hmac.new(
            self.app_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(signature[7:], expected_hash)

    def verify_webhook_subscription(self, params: dict[str, str]) -> str | None:
        """Verify webhook subscription via GET challenge."""
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge")

        if mode == "subscribe" and token == self.verify_token:
            return challenge
        return None
