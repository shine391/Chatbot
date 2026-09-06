"""Instagram channel adapter."""

import hashlib
import hmac
from typing import Any

import httpx
from loguru import logger

from app.channels.base import BaseChannel
from app.config import get_settings
from app.schemas.message import ChannelType, IncomingMessage, MessageResponse


class InstagramChannel(BaseChannel):
    """Instagram channel adapter using Meta Graph API v21.0."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.api_url = "https://graph.facebook.com/v21.0/me/messages"

    async def parse_incoming(self, raw_data: dict[str, Any]) -> IncomingMessage:
        """Parse Instagram webhook payload."""
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
                channel=ChannelType.INSTAGRAM,
                sender_id=sender_id,
                content=text,
                media_urls=media_urls,
                platform_message_id=message.get("mid"),
                raw_data=raw_data,
            )
        except Exception as e:
            logger.error(f"Error parsing Instagram webhook: {e}")
            raise

    async def _send_request(self, payload: dict[str, Any]) -> MessageResponse:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.api_url,
                    params={"access_token": self.settings.instagram_page_access_token},
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                return MessageResponse(success=True, message_id=data.get("message_id"))
        except httpx.HTTPError as e:
            logger.error(f"HTTP error sending to Instagram: {e}")
            return MessageResponse(success=False, error=str(e))
        except Exception as e:
            logger.error(f"Unexpected error sending to Instagram: {e}")
            return MessageResponse(success=False, error=str(e))

    async def send_text(self, recipient_id: str, text: str) -> MessageResponse:
        """Send a text message."""
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": text},
        }
        return await self._send_request(payload)

    async def send_image(
        self, recipient_id: str, image_url: str, caption: str | None = None
    ) -> MessageResponse:
        """Send an image attachment via URL."""
        payload = {
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": "image",
                    "payload": {"url": image_url, "is_reusable": True},
                }
            },
        }
        return await self._send_request(payload)

    async def send_video(
        self, recipient_id: str, video_url: str, caption: str | None = None
    ) -> MessageResponse:
        """Send a video attachment via URL."""
        payload = {
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": "video",
                    "payload": {"url": video_url, "is_reusable": True},
                }
            },
        }
        return await self._send_request(payload)

    async def send_product_card(
        self, recipient_id: str, product: dict[str, Any]
    ) -> MessageResponse:
        """Send a product card. Fallback to image + text for Instagram."""
        image_url = product.get("image_url")
        if image_url:
            await self.send_image(recipient_id, image_url)
        name = product.get("name", "Sản phẩm")
        price = product.get("price", "")
        url = product.get("website_url") or product.get("url", "")
        text = f"{name}\nGiá: {price}\nXem chi tiết: {url}"
        return await self.send_text(recipient_id, text)

    async def send_carousel(
        self, recipient_id: str, products: list[dict[str, Any]]
    ) -> MessageResponse:
        """Send a carousel. Fallback to multiple messages for Instagram."""
        res = MessageResponse(success=True)
        for p in products[:4]:
            res = await self.send_product_card(recipient_id, p)
        return res

    def verify_webhook(
        self, headers: dict[str, str], body: bytes, params: dict[str, str] | None = None
    ) -> bool:
        """Verify HMAC-SHA256 signature."""
        signature = headers.get("x-hub-signature-256", "")
        if not signature.startswith("sha256="):
            return False

        expected_hash = hmac.new(
            self.settings.facebook_app_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(signature[7:], expected_hash)
